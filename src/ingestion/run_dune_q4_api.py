"""Run Dune Q4 pre-T0 flow features via API for the 2000-mint sample.

- Reads upload CSV; skips mints already present in data/samples/dune_q4_batches/q4_bXX.csv
- Batches of 100 with the same UNION ALL SQL pattern as cycle0/q4_batches/dune-q4-b05of20.sql
- Prefer POST /api/v1/sql/execute; fallback create-query + execute
- Never logs or writes DUNE_API_KEY

HYGIENE 2026-10-01: SQL template raw_sample filters tok_amt > 0 (Q5a parity).
Do NOT spend Dune credits on full expand re-export without BOSS approval;
for local parity use scripts/patch_q4_buy_vol_from_q5a_overlay_20261001.py.
See cycle0/diagnostics/usd-q4-q5a-parity-anchor-20261001.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.dune import DuneClient, DuneQuotaOrAuth, require_dune_api_key

ROOT = Path(__file__).resolve().parents[2]
UPLOAD_CSV = ROOT / "data/samples/dune_sample_primary_ready_v1_upload.csv"
BATCH_DIR = ROOT / "data/samples/dune_q4_batches"
SQL_TEMPLATE = ROOT / "cycle0/q4_batches/dune-q4-b05of20.sql"
FLOW_OUT = ROOT / "data/samples/dune_q4_flow_sample_v1.csv"
FEATURES_Q3 = ROOT / "data/samples/features_dune_p0_q3_sample_v1.csv"
FEATURES_FLOW = ROOT / "data/samples/features_dune_p0_flow_sample_v1.csv"
META_OUT = ROOT / "data/samples/dune_q4_flow_sample_v1_meta.json"
QA_OUT = ROOT / "data/samples/qa_features_dune_p0_flow_sample_v1.json"

FEATURE_SET_VERSION = "features.dune.p0.flow.v1"
BATCH_SIZE_DEFAULT = 100
SLEEP_BETWEEN_S = 12.0
POLL_S = 5.0
MAX_WAIT_S = 900.0
_LEAK_COL_RE = re.compile(r"(max_mc|hit_|label_|after_t0)", re.IGNORECASE)

FLOW_COLS = [
    "buy_count_60s",
    "sell_count_60s",
    "buy_vol_usd_60s",
    "sell_vol_usd_60s",
    "unique_traders_60s",
    "buy_count_5m",
    "sell_count_5m",
    "buy_vol_usd_5m",
    "sell_vol_usd_5m",
    "unique_traders_5m",
    "trade_count_total",
    "unique_traders_total",
    "time_since_first_trade_s",
]


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _normalize_t0(raw: str) -> str:
    """Upload: '2026-09-22 15:02:36.000 UTC' → '2026-09-22 15:02:36' for CAST."""
    s = str(raw).strip()
    s = s.replace(" UTC", "").replace("Z", "").strip()
    if "." in s:
        s = s.split(".", 1)[0]
    return s


def _load_sql_suffix() -> str:
    text = SQL_TEMPLATE.read_text()
    marker = "),\nbounds AS ("
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError(f"Could not find bounds CTE in {SQL_TEMPLATE}")
    # Keep leading newline + "bounds AS (...)"
    return text[idx + 2 :]


def build_batch_sql(rows: list[dict[str, str]], *, batch_num: int, batch_total_hint: int) -> str:
    suffix = _load_sql_suffix()
    parts: list[str] = []
    for i, row in enumerate(rows):
        mint = str(row["mint"]).strip()
        t0 = _normalize_t0(row["t0_ts"])
        line = f"SELECT '{mint}' AS mint, CAST('{t0}' AS TIMESTAMP) AS t0_ts"
        parts.append(line if i == 0 else f"UNION ALL\n{line}")
    sample_body = "\n".join(parts)
    header = (
        f"-- Q4 flow batch {batch_num}/{batch_total_hint} ({len(rows)} mints) "
        f"— Dune-safe UNION ALL, no ORDER BY\n"
    )
    return f"{header}WITH sample AS (\n{sample_body}\n),\n{suffix}"


def existing_batch_paths() -> list[Path]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(BATCH_DIR.glob("q4_b*.csv"))


def load_done_mints() -> set[str]:
    done: set[str] = set()
    for path in existing_batch_paths():
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("mint"):
                    done.add(row["mint"].strip())
    return done


def next_batch_num() -> int:
    nums: list[int] = []
    for path in existing_batch_paths():
        m = re.search(r"q4_b(\d+)\.csv$", path.name)
        if m:
            nums.append(int(m.group(1)))
    return (max(nums) + 1) if nums else 1


def rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["mint", "t0_ts", *FLOW_COLS])
    return pd.DataFrame(rows)


def save_batch_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    df = rows_to_dataframe(rows)
    # Stable column order when present
    cols = ["mint", "t0_ts"] + [c for c in FLOW_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in cols]
    df = df[cols + extra]
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def _is_credit_or_rate(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(
        tok in text
        for tok in ("402", "429", "403", "quota", "credit", "rate limit", "too many")
    )


def _is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in str(exc).lower() or "timed out" in str(exc).lower()


def execute_sql_with_fallback(client: DuneClient, sql: str, *, performance: str = "medium") -> str:
    """Return execution_id. Prefer /sql/execute; fallback create query + execute."""
    try:
        body = client.execute_sql(sql, performance=performance)
        eid = body.get("execution_id")
        if not eid:
            raise RuntimeError(f"sql/execute missing execution_id keys={sorted(body.keys())}")
        return str(eid)
    except DuneQuotaOrAuth:
        raise
    except Exception as first_err:
        _log(f"sql/execute failed ({type(first_err).__name__}); trying create-query fallback")
        # Fallback: POST /api/v1/query then execute
        http = client._http  # noqa: SLF001 — shared client
        name = f"q4_flow_api_{int(time.time())}"
        cr = http.post(
            "https://api.dune.com/api/v1/query",
            json={"name": name, "query_sql": sql, "is_private": True},
        )
        if cr.status_code in (401, 403, 402, 429):
            raise DuneQuotaOrAuth(f"Dune create query HTTP {cr.status_code}: {cr.text[:300]}") from first_err
        cr.raise_for_status()
        qid = cr.json().get("query_id") or cr.json().get("queryId")
        if qid is None:
            raise RuntimeError(f"create query missing id: {sorted(cr.json().keys())}") from first_err
        er = http.post(
            f"https://api.dune.com/api/v1/query/{qid}/execute",
            json={"performance": performance},
        )
        if er.status_code in (401, 403, 402, 429):
            raise DuneQuotaOrAuth(f"Dune execute query HTTP {er.status_code}: {er.text[:300]}") from first_err
        er.raise_for_status()
        eid = er.json().get("execution_id")
        if not eid:
            raise RuntimeError(f"query execute missing execution_id: {sorted(er.json().keys())}") from first_err
        return str(eid)


def run_one_batch(
    client: DuneClient,
    rows: list[dict[str, str]],
    *,
    batch_num: int,
    batch_total_hint: int,
    performance: str,
) -> tuple[list[dict[str, Any]], str]:
    sql = build_batch_sql(rows, batch_num=batch_num, batch_total_hint=batch_total_hint)
    eid = execute_sql_with_fallback(client, sql, performance=performance)
    _log(f"batch b{batch_num:02d}: execution_id={eid} (n_mints={len(rows)})")
    body = client.wait_results(eid, max_wait_s=MAX_WAIT_S, poll_s=POLL_S)
    state = (body.get("state") or "").upper()
    if "COMPLETED" not in state:
        raise RuntimeError(f"batch b{batch_num:02d} not completed: state={state}")
    result = body.get("result") or {}
    out_rows = list(result.get("rows") or [])
    return out_rows, eid


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def merge_all_batches() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in existing_batch_paths():
        df = pd.read_csv(path)
        df["__batch_file"] = path.name
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["mint", "t0_ts", *FLOW_COLS])
    merged = pd.concat(frames, ignore_index=True)
    # Prefer first occurrence if duplicates
    merged = merged.drop_duplicates(subset=["mint"], keep="first")
    return merged.drop(columns=["__batch_file"], errors="ignore")


def join_features(flow: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    q3 = pd.read_csv(FEATURES_Q3)
    flow_keep = flow[["mint"] + [c for c in FLOW_COLS if c in flow.columns]].copy()
    # numeric fill for missing flow after left join
    out = q3.merge(flow_keep, on="mint", how="left", suffixes=("", "_flowdup"))
    for c in FLOW_COLS:
        if c not in out.columns:
            out[c] = 0
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["feature_set_version"] = FEATURE_SET_VERSION
    leak = [c for c in out.columns if _LEAK_COL_RE.search(c)]
    qa = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "ok": len(leak) == 0,
        "n_q3_features": int(len(q3)),
        "n_flow_rows": int(len(flow)),
        "n_joined": int(len(out)),
        "n_flow_matched": int(out["trade_count_total"].ne(0).sum()) if "trade_count_total" in out.columns else None,
        "leak_col_regex": _LEAK_COL_RE.pattern,
        "leak_cols_found": leak,
        "feature_columns": list(out.columns),
        "assertions": {
            "no_leak_columns": len(leak) == 0,
            "n_rows_match_q3": int(len(out)) == int(len(q3)),
        },
        "paths": {
            "features_q3": str(FEATURES_Q3.relative_to(ROOT)),
            "flow_sample": str(FLOW_OUT.relative_to(ROOT)),
            "features_flow": str(FEATURES_FLOW.relative_to(ROOT)),
        },
    }
    return out, qa


def run(
    *,
    batch_size: int = BATCH_SIZE_DEFAULT,
    sleep_s: float = SLEEP_BETWEEN_S,
    performance: str = "medium",
    dry_run: bool = False,
    max_batches: int | None = None,
) -> dict[str, Any]:
    # Ensure key loads without echoing
    require_dune_api_key()

    upload = list(csv.DictReader(UPLOAD_CSV.open(newline="")))
    done = load_done_mints()
    remaining = [r for r in upload if r["mint"].strip() not in done]
    start_num = next_batch_num()
    total_hint = start_num + (len(remaining) + batch_size - 1) // batch_size - 1 if remaining else start_num - 1

    _log(
        f"upload={len(upload)} done_mints={len(done)} remaining={len(remaining)} "
        f"next_batch=b{start_num:02d} batch_size={batch_size}"
    )

    meta: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "feature_set_version": FEATURE_SET_VERSION,
        "upload_csv": str(UPLOAD_CSV.relative_to(ROOT)),
        "n_upload": len(upload),
        "n_done_before": len(done),
        "n_remaining_before": len(remaining),
        "batch_size_requested": batch_size,
        "performance": performance,
        "batches": [],
        "failures": [],
        "execution_ids": [],
    }

    if dry_run:
        batches = chunked(remaining, batch_size)
        meta["dry_run"] = True
        meta["planned_batches"] = [
            {"batch": start_num + i, "n": len(b), "first_mint": b[0]["mint"] if b else None}
            for i, b in enumerate(batches)
        ]
        META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
        _log(f"dry-run planned {len(batches)} batches → wrote {META_OUT}")
        return meta

    client = DuneClient(timeout_s=180.0)
    batch_num = start_num
    queue = list(remaining)
    batches_run = 0

    try:
        while queue:
            if max_batches is not None and batches_run >= max_batches:
                _log(f"stopping after max_batches={max_batches}")
                break

            size = min(batch_size, len(queue))
            # Adaptive shrink path if prior failure requested smaller size via queue tagging — use size as-is
            chunk = queue[:size]
            out_path = BATCH_DIR / f"q4_b{batch_num:02d}.csv"

            if out_path.exists():
                _log(f"skip existing {out_path.name}")
                # still remove those mints from queue if present
                existing_mints = {r["mint"] for r in csv.DictReader(out_path.open())}
                queue = [r for r in queue if r["mint"] not in existing_mints]
                batch_num += 1
                continue

            try:
                rows, eid = run_one_batch(
                    client,
                    chunk,
                    batch_num=batch_num,
                    batch_total_hint=max(total_hint, batch_num),
                    performance=performance,
                )
                n_saved = save_batch_csv(out_path, rows)
                meta["batches"].append(
                    {
                        "batch": batch_num,
                        "file": out_path.name,
                        "n_mints_requested": len(chunk),
                        "n_rows_returned": n_saved,
                        "execution_id": eid,
                        "ok": True,
                    }
                )
                meta["execution_ids"].append(eid)
                _log(f"saved {out_path.name} rows={n_saved}/{len(chunk)}")
                # Drop requested mints from queue (even if some missing from results)
                req = {r["mint"] for r in chunk}
                queue = [r for r in queue if r["mint"] not in req]
                batch_num += 1
                batches_run += 1
                if queue:
                    _log(f"sleep {sleep_s}s before next execute")
                    time.sleep(sleep_s)
            except (DuneQuotaOrAuth, TimeoutError, RuntimeError, Exception) as exc:
                err_s = f"{type(exc).__name__}: {exc}"
                # Never include env/key — truncate body already in dune.py
                _log(f"batch b{batch_num:02d} FAILED size={size}: {err_s[:400]}")
                meta["failures"].append(
                    {"batch": batch_num, "size": size, "error": err_s[:500], "first_mint": chunk[0]["mint"]}
                )
                if _is_credit_or_rate(exc) or _is_timeout(exc):
                    if size > 25:
                        new_size = max(25, size // 2)
                        _log(f"shrinking batch_size {size} → {new_size} and retrying same mints")
                        batch_size = new_size
                        time.sleep(sleep_s * 2)
                        continue
                    if size > 10:
                        batch_size = 10
                        _log("shrinking batch_size → 10")
                        time.sleep(sleep_s * 2)
                        continue
                    _log("credit/timeout at min size — stopping remaining executes")
                    break
                # Non-quota error: skip this chunk and continue
                req = {r["mint"] for r in chunk}
                queue = [r for r in queue if r["mint"] not in req]
                batch_num += 1
                batches_run += 1
                time.sleep(sleep_s)
    finally:
        client.close()

    # Merge + join even with partial success
    flow = merge_all_batches()
    flow_cols_ordered = ["mint", "t0_ts"] + [c for c in FLOW_COLS if c in flow.columns]
    extra = [c for c in flow.columns if c not in flow_cols_ordered]
    flow[flow_cols_ordered + extra].to_csv(FLOW_OUT, index=False)
    _log(f"merged flow rows={len(flow)} → {FLOW_OUT}")

    features, qa = join_features(flow)
    features.to_csv(FEATURES_FLOW, index=False)
    QA_OUT.write_text(json.dumps(qa, indent=2) + "\n")
    _log(f"joined features rows={len(features)} leak_ok={qa['ok']} → {FEATURES_FLOW}")

    meta.update(
        {
            "n_flow_rows": int(len(flow)),
            "n_feature_rows": int(len(features)),
            "n_batches_on_disk": len(existing_batch_paths()),
            "batch_files": [p.name for p in existing_batch_paths()],
            "paths": {
                "batches_dir": str(BATCH_DIR.relative_to(ROOT)),
                "flow_sample": str(FLOW_OUT.relative_to(ROOT)),
                "features_flow": str(FEATURES_FLOW.relative_to(ROOT)),
                "qa": str(QA_OUT.relative_to(ROOT)),
            },
            "qa_ok": qa["ok"],
            "finished_at": datetime.now().astimezone().isoformat(),
        }
    )
    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    _log(f"meta → {META_OUT}")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    p.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_S)
    p.add_argument("--performance", default="medium", choices=["medium", "large", "free"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-batches", type=int, default=None)
    args = p.parse_args(argv)
    meta = run(
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        performance=args.performance,
        dry_run=args.dry_run,
        max_batches=args.max_batches,
    )
    print(
        json.dumps(
            {
                "n_flow_rows": meta.get("n_flow_rows"),
                "n_feature_rows": meta.get("n_feature_rows"),
                "n_batches": len(meta.get("batches") or []),
                "n_failures": len(meta.get("failures") or []),
                "qa_ok": meta.get("qa_ok"),
                "paths": meta.get("paths"),
            },
            indent=2,
        )
    )
    return 0 if not meta.get("failures") else 2


if __name__ == "__main__":
    raise SystemExit(main())
