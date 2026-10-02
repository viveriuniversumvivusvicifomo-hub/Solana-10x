"""Dune Q5 P0 feature pull — microstructure (Q5a) + creator/age (Q5b).

Reuses expand-v2 batching: UNION ALL sample CTE, ~300 mints/batch, dual API keys
with claim queue, skip done mints, graceful credit stop.

Never logs or writes DUNE_API_KEY values.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.dune import DuneClient, DuneQuotaOrAuth
from ingestion.env import load_dotenv
from ingestion.run_dune_q4_api import (
    _is_credit_or_rate,
    _normalize_t0,
    execute_sql_with_fallback,
)

ROOT = Path(__file__).resolve().parents[2]
UPLOAD = ROOT / "data/samples/dune_sample_primary_ready_expand_v2_upload.csv"
SMOKE_UPLOAD = ROOT / "data/samples/dune_q5_smoke10_upload.csv"
OUT_DIR = ROOT / "data/samples"

PACKS: dict[str, dict[str, Any]] = {
    "q5a": {
        "sql_template": ROOT / "cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql",
        "batch_dir": OUT_DIR / "dune_q5a_batches",
        "merged_out": OUT_DIR / "dune_q5a_features.csv",
        "meta_out": OUT_DIR / "dune_q5a_features_meta.json",
        "feature_set_version": "features.dune.p0.q5a.v1",
        "sample_marker": "  -- RUNNER_INJECTS_SAMPLE\n  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0",
    },
    "q5b": {
        "sql_template": ROOT / "cycle0/q5_sql/dune-q5b-creator-age-pre-t0.sql",
        "batch_dir": OUT_DIR / "dune_q5b_batches",
        "merged_out": OUT_DIR / "dune_q5b_features.csv",
        "meta_out": OUT_DIR / "dune_q5b_features_meta.json",
        "feature_set_version": "features.dune.p0.q5b.v1",
        "sample_marker": "  -- RUNNER_INJECTS_SAMPLE\n  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0",
    },
}

BATCH_SIZE = 300
SLEEP_S = 2.0
POLL_S = 2.0
MAX_WAIT_S = 900.0
MERGE_EVERY_N = 3
_LEAK_COL_RE = re.compile(r"(max_mc|hit_|label_|after_t0|primary_ready)", re.IGNORECASE)


def _log(tag: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][{tag}] {msg}", flush=True)


def _key_for_worker(worker: str) -> str:
    load_dotenv()
    env_map = {"A": "DUNE_API_KEY", "B": "DUNE_API_KEY_2", "C": "DUNE_API_KEY_3", "D": "DUNE_API_KEY_4", "E": "DUNE_API_KEY_5", "F": "DUNE_API_KEY_6", "G": "DUNE_API_KEY_7", "H": "DUNE_API_KEY_8", "I": "DUNE_API_KEY_9", "J": "DUNE_API_KEY_10", "K": "DUNE_API_KEY_11", "L": "DUNE_API_KEY_12"}
    env_name = env_map.get(worker)
    if not env_name:
        raise DuneQuotaOrAuth(f"unknown worker {worker!r}")
    key = (os.environ.get(env_name) or "").strip()
    if not key:
        raise DuneQuotaOrAuth(f"{env_name} missing")
    return key


def load_upload(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            mint = (row.get("mint") or "").strip()
            t0 = (row.get("t0_ts") or "").strip()
            if mint and t0:
                rows.append({"mint": mint, "t0_ts": t0})
    return rows


def build_sql(pack: str, rows: list[dict[str, str]], *, batch_num: int, batch_total_hint: int) -> str:
    cfg = PACKS[pack]
    text = cfg["sql_template"].read_text()
    marker = cfg["sample_marker"]
    if marker not in text:
        raise RuntimeError(f"{pack}: sample marker not found in SQL template")
    parts: list[str] = []
    for i, row in enumerate(rows):
        mint = str(row["mint"]).strip()
        t0 = _normalize_t0(row["t0_ts"])
        line = f"SELECT '{mint}' AS mint, CAST('{t0}' AS TIMESTAMP) AS t0_ts"
        parts.append(line if i == 0 else f"UNION ALL\n{line}")
    sample_body = "\n".join(parts)
    replacement = f"  -- batch {batch_num}/{batch_total_hint} n={len(rows)}\n{sample_body}"
    # Indent UNION body inside WITH sample AS (
    indented = "\n".join(
        ("  " + ln if ln and not ln.startswith(" ") else ln) for ln in replacement.splitlines()
    )
    # Simpler: put sample body without weird indent
    replacement = f"-- batch {batch_num}/{batch_total_hint} n={len(rows)}\n" + "\n".join(parts)
    sql = text.replace(marker, replacement)
    header = f"-- Q5 {pack} batch {batch_num}/{batch_total_hint} ({len(rows)} mints)\n"
    return header + sql


def done_mints(batch_dir: Path) -> set[str]:
    done: set[str] = set()
    if not batch_dir.exists():
        return done
    for path in batch_dir.glob("q5*.csv"):
        try:
            for row in csv.DictReader(path.open()):
                if row.get("mint"):
                    done.add(row["mint"].strip())
        except Exception:
            continue
    return done


def next_batch_path(batch_dir: Path, worker: str, pack: str) -> Path:
    pat = re.compile(rf"{pack}_w{worker}_b(\d+)\.csv$")
    nums: list[int] = []
    for p in batch_dir.glob(f"{pack}_w{worker}_b*.csv"):
        m = pat.search(p.name)
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return batch_dir / f"{pack}_w{worker}_b{n:03d}.csv"


def save_batch(path: Path, rows: list[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        # still write empty header-less? write empty file with mint,t0_ts
        pd.DataFrame(columns=["mint", "t0_ts"]).to_csv(path, index=False)
        return 0
    df = pd.DataFrame(rows)
    # stable-ish order
    cols = ["mint", "t0_ts"] + [c for c in df.columns if c not in ("mint", "t0_ts")]
    df[cols].to_csv(path, index=False)
    return len(df)


def merge_batches(pack: str) -> pd.DataFrame:
    cfg = PACKS[pack]
    batch_dir: Path = cfg["batch_dir"]
    frames: list[pd.DataFrame] = []
    for path in sorted(batch_dir.glob("q5*.csv")):
        try:
            df = pd.read_csv(path)
            if len(df):
                df["__src"] = path.name
                frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=["mint", "t0_ts"])
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["mint"], keep="last")
    return merged.drop(columns=["__src"], errors="ignore")


def qa_features(df: pd.DataFrame, pack: str) -> dict[str, Any]:
    leak = [c for c in df.columns if _LEAK_COL_RE.search(c)]
    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "pack": pack,
        "feature_set_version": PACKS[pack]["feature_set_version"],
        "n_rows": int(len(df)),
        "n_cols": int(len(df.columns)),
        "columns": list(df.columns),
        "leak_cols_found": leak,
        "ok": len(leak) == 0,
        "null_rates": {
            c: float(df[c].isna().mean()) for c in df.columns if c not in ("mint", "t0_ts", "creator_pubkey", "create_ts", "token_name", "token_symbol")
        }
        if len(df)
        else {},
    }


def add_cohort_creator_priors(df: pd.DataFrame) -> pd.DataFrame:
    """Causal prior-launch counts from the pulled cohort itself (create_ts < t0).

    Underestimates true priors (misses out-of-cohort creates) but is ≤T0 and
    avoids a second heavy Dune self-join. Documented caveat in catalog.
    """
    if df.empty or "creator_pubkey" not in df.columns:
        return df
    out = df.copy()
    create_dt = pd.to_datetime(out["create_ts"], utc=True, errors="coerce") if "create_ts" in out.columns else pd.Series(pd.NaT, index=out.index)
    t0_dt = pd.to_datetime(out["t0_ts"], utc=True, errors="coerce")
    # force UTC tz-aware
    if create_dt.dt.tz is None:
        create_dt = create_dt.dt.tz_localize("UTC")
    if t0_dt.dt.tz is None:
        t0_dt = t0_dt.dt.tz_localize("UTC")
    event_ts = create_dt.fillna(t0_dt)
    out["creator_prior_mints_7d"] = 0
    out["creator_prior_mints_30d"] = 0
    out["creator_prior_mints_cohort"] = 0
    for creator, grp in out.groupby(out["creator_pubkey"], dropna=True):
        if not isinstance(creator, str) or not creator:
            continue
        order = event_ts.loc[grp.index].sort_values()
        idxs = list(order.index)
        times = list(order.values)
        for i, idx in enumerate(idxs):
            ts = times[i]
            if pd.isna(ts):
                continue
            out.at[idx, "creator_prior_mints_cohort"] = int(i)
            if i == 0:
                continue
            ts_pd = pd.Timestamp(ts)
            if ts_pd.tzinfo is None:
                ts_pd = ts_pd.tz_localize("UTC")
            prev = pd.to_datetime(pd.Series(times[:i]), utc=True)
            delta = ts_pd - prev
            out.at[idx, "creator_prior_mints_7d"] = int((delta <= pd.Timedelta(days=7)).sum())
            out.at[idx, "creator_prior_mints_30d"] = int((delta <= pd.Timedelta(days=30)).sum())
    return out


def do_merge(pack: str, worker: str = "merge") -> dict[str, Any]:
    cfg = PACKS[pack]
    flow = merge_batches(pack)
    if pack == "q5b" and len(flow):
        flow = add_cohort_creator_priors(flow)
    flow.to_csv(cfg["merged_out"], index=False)
    qa = qa_features(flow, pack)
    qa_path = OUT_DIR / f"qa_dune_{pack}_features.json"
    qa_path.write_text(json.dumps(qa, indent=2) + "\n")
    meta = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "merged_by": worker,
        "pack": pack,
        "feature_set_version": cfg["feature_set_version"],
        "n_rows": int(len(flow)),
        "n_batch_files": len(list(cfg["batch_dir"].glob("q5*.csv"))),
        "qa_ok": qa["ok"],
        "paths": {
            "merged": str(cfg["merged_out"].relative_to(ROOT)),
            "batches": str(cfg["batch_dir"].relative_to(ROOT)),
            "qa": str(qa_path.relative_to(ROOT)),
        },
    }
    cfg["meta_out"].write_text(json.dumps(meta, indent=2) + "\n")
    _log(f"{pack}/{worker}", f"merge n={len(flow)} qa_ok={qa['ok']}")
    return meta


# ---- claim queue (per pack) ----

def _paths(pack: str) -> tuple[Path, Path, Path, Path]:
    batch_dir = PACKS[pack]["batch_dir"]
    batch_dir.mkdir(parents=True, exist_ok=True)
    return (
        batch_dir,
        batch_dir / "claim_queue.jsonl",
        batch_dir / "claim.lock",
        batch_dir / "inflight",
    )


def init_claim_queue(pack: str, upload_rows: list[dict[str, str]], *, force: bool = False) -> int:
    batch_dir, queue_path, _, inflight = _paths(pack)
    inflight.mkdir(parents=True, exist_ok=True)
    if queue_path.exists() and not force and queue_path.stat().st_size > 0:
        return sum(1 for _ in queue_path.open() if _.strip())
    done = done_mints(batch_dir)
    remaining = [r for r in upload_rows if r["mint"] not in done]
    with queue_path.open("w") as f:
        for r in remaining:
            f.write(json.dumps(r) + "\n")
    return len(remaining)


def _with_lock(lock_path: Path, fn):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def claim_batch(pack: str, worker: str, n: int) -> list[dict[str, str]]:
    batch_dir, queue_path, lock_path, inflight_dir = _paths(pack)
    inflight_dir.mkdir(parents=True, exist_ok=True)

    def _claim() -> list[dict[str, str]]:
        done = done_mints(batch_dir)
        inflight: set[str] = set()
        for p in inflight_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                for m in data.get("mints") or []:
                    inflight.add(str(m))
            except Exception:
                continue
        if not queue_path.exists():
            return []
        lines = queue_path.read_text().splitlines()
        keep: list[str] = []
        claimed: list[dict[str, str]] = []
        for line in lines:
            if not line.strip():
                continue
            row = json.loads(line)
            mint = str(row["mint"]).strip()
            if mint in done or mint in inflight:
                continue
            if len(claimed) < n:
                claimed.append({"mint": mint, "t0_ts": str(row["t0_ts"])})
            else:
                keep.append(json.dumps({"mint": mint, "t0_ts": str(row["t0_ts"])}))
        queue_path.write_text("\n".join(keep) + ("\n" if keep else ""))
        if claimed:
            (inflight_dir / f"{worker}.json").write_text(
                json.dumps(
                    {
                        "worker": worker,
                        "claimed_at": datetime.now().astimezone().isoformat(),
                        "mints": [c["mint"] for c in claimed],
                        "rows": claimed,
                    }
                )
                + "\n"
            )
        return claimed

    return _with_lock(lock_path, _claim)


def release_inflight(pack: str, worker: str, *, requeue: list[dict[str, str]] | None = None) -> None:
    batch_dir, queue_path, lock_path, inflight_dir = _paths(pack)

    def _rel() -> None:
        path = inflight_dir / f"{worker}.json"
        if path.exists():
            path.unlink()
        if requeue:
            existing = queue_path.read_text() if queue_path.exists() else ""
            prepend = "\n".join(json.dumps(r) for r in requeue) + ("\n" if requeue else "")
            queue_path.write_text(prepend + existing)

    _with_lock(lock_path, _rel)


def queue_remaining(pack: str) -> int:
    _, queue_path, _, _ = _paths(pack)
    if not queue_path.exists():
        return 0
    return sum(1 for line in queue_path.open() if line.strip())


def run_one_batch(
    client: DuneClient,
    pack: str,
    rows: list[dict[str, str]],
    *,
    batch_num: int,
    batch_total_hint: int,
    performance: str,
) -> tuple[list[dict[str, Any]], str]:
    sql = build_sql(pack, rows, batch_num=batch_num, batch_total_hint=batch_total_hint)
    eid = execute_sql_with_fallback(client, sql, performance=performance)
    _log(pack, f"batch b{batch_num}: eid={eid} n={len(rows)}")
    body = client.wait_results(eid, max_wait_s=MAX_WAIT_S, poll_s=POLL_S)
    state = (body.get("state") or "").upper()
    if "COMPLETED" not in state:
        err = json.dumps(body)[:800]
        raise RuntimeError(f"{pack} batch b{batch_num} not completed: state={state} body={err}")
    result = body.get("result") or {}
    out_rows = list(result.get("rows") or [])
    return out_rows, eid


def smoke(pack: str, *, n: int = 10, performance: str = "medium", worker: str = "A") -> dict[str, Any]:
    """Run a small smoke batch and write dune_q5{a|b}_smoke.csv."""
    cfg = PACKS[pack]
    if SMOKE_UPLOAD.exists():
        rows = load_upload(SMOKE_UPLOAD)[:n]
    else:
        rows = load_upload(UPLOAD)[:n]
    key = _key_for_worker(worker)
    client = DuneClient(api_key=key, timeout_s=180.0)
    tag = f"{pack}/smoke"
    try:
        _log(tag, f"smoke n={len(rows)} performance={performance}")
        out_rows, eid = run_one_batch(
            client, pack, rows, batch_num=0, batch_total_hint=0, performance=performance
        )
        smoke_path = OUT_DIR / f"dune_{pack}_smoke.csv"
        n_saved = save_batch(smoke_path, out_rows)
        # also stash under batch dir for consistency
        cfg["batch_dir"].mkdir(parents=True, exist_ok=True)
        save_batch(cfg["batch_dir"] / f"{pack}_smoke.csv", out_rows)
        qa = qa_features(pd.DataFrame(out_rows) if out_rows else pd.DataFrame(), pack)
        meta = {
            "smoke": True,
            "pack": pack,
            "n_requested": len(rows),
            "n_returned": n_saved,
            "execution_id": eid,
            "qa_ok": qa["ok"],
            "columns": qa["columns"],
            "path": str(smoke_path.relative_to(ROOT)),
            "finished_at": datetime.now().astimezone().isoformat(),
        }
        (OUT_DIR / f"dune_{pack}_smoke_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
        _log(tag, f"OK returned={n_saved}/{len(rows)} cols={len(qa['columns'])} → {smoke_path.name}")
        return meta
    finally:
        client.close()


def worker_loop(
    pack: str,
    worker: str,
    *,
    batch_size: int = BATCH_SIZE,
    sleep_s: float = SLEEP_S,
    performance: str = "medium",
    max_batches: int | None = None,
) -> dict[str, Any]:
    cfg = PACKS[pack]
    key = _key_for_worker(worker)
    client = DuneClient(api_key=key, timeout_s=180.0)
    batches_ok = 0
    failures: list[dict[str, Any]] = []
    credit_stop = False
    fetched = 0
    t0 = time.time()
    tag = f"{pack}/w{worker}"

    try:
        while True:
            if max_batches is not None and batches_ok >= max_batches:
                _log(tag, f"max_batches={max_batches}")
                break
            rem = queue_remaining(pack)
            if rem <= 0:
                _, _, _, inflight_dir = _paths(pack)
                if not list(inflight_dir.glob("*.json")):
                    _log(tag, "queue empty — done")
                    break
                mine = inflight_dir / f"{worker}.json"
                if mine.exists():
                    release_inflight(pack, worker)
                time.sleep(3)
                continue

            chunk = claim_batch(pack, worker, batch_size)
            if not chunk:
                time.sleep(2)
                continue
            out_path = next_batch_path(cfg["batch_dir"], worker, pack)
            _log(tag, f"claimed {len(chunk)} → {out_path.name} queue_left≈{queue_remaining(pack)}")
            try:
                rows, eid = run_one_batch(
                    client,
                    pack,
                    chunk,
                    batch_num=batches_ok + 1,
                    batch_total_hint=max(1, (queue_remaining(pack) // batch_size) + batches_ok + 1),
                    performance=performance,
                )
                n_saved = save_batch(out_path, rows)
                release_inflight(pack, worker)
                batches_ok += 1
                fetched += len(chunk)
                elapsed = max(time.time() - t0, 1.0)
                rate = fetched / elapsed * 3600
                left = queue_remaining(pack)
                eta_h = (left / (fetched / elapsed)) / 3600 if fetched else float("inf")
                _log(
                    tag,
                    f"saved {out_path.name} rows={n_saved}/{len(chunk)} eid={eid} "
                    f"fetched={fetched} left={left} rate={rate:.0f}/h ETA~{eta_h:.2f}h",
                )
                if batches_ok % MERGE_EVERY_N == 0:
                    try:
                        do_merge(pack, worker)
                    except Exception as merge_exc:
                        _log(tag, f"merge warning (non-fatal): {type(merge_exc).__name__}: {merge_exc}"[:300])
                if left > 0 and sleep_s > 0:
                    time.sleep(sleep_s)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                _log(tag, f"FAIL size={len(chunk)}: {err[:350]}")
                failures.append({"error": err[:500], "n": len(chunk), "worker": worker, "batch_size": batch_size})
                is_credit = (
                    isinstance(exc, DuneQuotaOrAuth)
                    or any(tok in err for tok in ("HTTP 402", "HTTP 429", "HTTP 401", "HTTP 403"))
                )
                if is_credit:
                    release_inflight(pack, worker, requeue=chunk)
                    credit_stop = True
                    _log(tag, "credit/rate hard-stop")
                    break
                release_inflight(pack, worker, requeue=chunk)
                if batch_size > 100:
                    batch_size = 100
                    _log(tag, "exec fail — shrink batch_size → 100")
                elif batch_size > 50:
                    batch_size = 50
                    _log(tag, "exec fail — shrink batch_size → 50")
                elif batch_size > 25:
                    batch_size = 25
                    _log(tag, "exec fail — shrink batch_size → 25")
                else:
                    _log(tag, "exec fail at min batch — will retry same size after sleep")
                time.sleep(max(sleep_s, 5.0))
    finally:
        client.close()

    meta = do_merge(pack, worker)
    meta.update(
        {
            "worker": worker,
            "pack": pack,
            "batches_ok": batches_ok,
            "fetched": fetched,
            "failures": failures,
            "credit_stop": credit_stop,
            "finished_at": datetime.now().astimezone().isoformat(),
        }
    )
    (cfg["batch_dir"] / f"worker_{worker}_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pack", choices=["q5a", "q5b", "both"], default="q5a")
    p.add_argument("--worker", choices=["A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "init", "smoke", "merge"], required=True)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--sleep", type=float, default=SLEEP_S)
    p.add_argument("--performance", default="medium")
    p.add_argument("--max-batches", type=int, default=None)
    p.add_argument("--smoke-n", type=int, default=10)
    p.add_argument("--force-reinit-queue", action="store_true")
    p.add_argument("--upload", type=str, default=str(UPLOAD))
    args = p.parse_args(argv)

    packs = ["q5a", "q5b"] if args.pack == "both" else [args.pack]
    upload_rows = load_upload(Path(args.upload))

    if args.worker == "smoke":
        results = {}
        for pack in packs:
            results[pack] = smoke(pack, n=args.smoke_n, performance=args.performance, worker="A")
        print(json.dumps(results, indent=2))
        return 0 if all(r.get("n_returned", 0) >= 0 and r.get("qa_ok") for r in results.values()) else 2

    if args.worker == "merge":
        metas = {pack: do_merge(pack) for pack in packs}
        print(json.dumps(metas, indent=2))
        return 0

    if args.worker == "init":
        out = {}
        for pack in packs:
            n = init_claim_queue(pack, upload_rows, force=args.force_reinit_queue)
            out[pack] = {"n_remaining": n, "queue": str(PACKS[pack]["batch_dir"] / "claim_queue.jsonl")}
            _log("init", f"{pack} queue n={n}")
        print(json.dumps(out, indent=2))
        return 0

    # worker A/B/C — one pack at a time (caller chooses --pack)
    pack = packs[0]
    if args.pack == "both":
        _log(args.worker, "worker mode uses single pack; defaulting to q5a (run twice for both)")
        pack = "q5a"
    _, queue_path, _, _ = _paths(pack)
    if not queue_path.exists() or queue_path.stat().st_size == 0:
        n = init_claim_queue(pack, upload_rows, force=True)
        _log(f"{pack}/{args.worker}", f"initialized queue n={n}")

    meta = worker_loop(
        pack,
        args.worker,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        performance=args.performance,
        max_batches=args.max_batches,
    )
    print(
        json.dumps(
            {
                "pack": pack,
                "worker": args.worker,
                "batches_ok": meta.get("batches_ok"),
                "fetched": meta.get("fetched"),
                "n_rows": meta.get("n_rows"),
                "queue_remaining": queue_remaining(pack),
                "credit_stop": meta.get("credit_stop"),
                "n_failures": len(meta.get("failures") or []),
            },
            indent=2,
        )
    )
    return 0 if not meta.get("credit_stop") else 2


if __name__ == "__main__":
    raise SystemExit(main())
