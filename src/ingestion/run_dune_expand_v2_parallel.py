"""Two-worker parallel Q4 expand with claim queue + dual API keys.

Worker A: DUNE_API_KEY  Worker B: DUNE_API_KEY_2
Claim disjoint mints via flock on data/samples/dune_q4_batches_v2/claim.lock
Queue file: claim_queue.jsonl  (mint,t0_ts JSON lines)
Never logs API keys.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.dune import DuneClient, DuneQuotaOrAuth
from ingestion.env import load_dotenv
from ingestion.run_dune_expand_v2 import (
    BATCH_DIR,
    COHORT,
    FLOW_V1,
    FLOW_OUT,
    FEATURES_Q3,
    FEATURES_FLOW,
    LABELS_OUT,
    META_OUT,
    QA_OUT,
    FEATURE_SET_FLOW,
    FLOW_COLS,
    filter_primary_ready_with_mc,
    interleave_stratified_queue,
    join_features,
    merge_flow,
    prepare_expand_artifacts,
    write_gaps_doc,
)
from ingestion.run_dune_q4_api import (
    _is_credit_or_rate,
    run_one_batch,
    save_batch_csv,
)
import ingestion.run_dune_q4_api as q4mod

ROOT = Path(__file__).resolve().parents[2]
CLAIM_QUEUE = BATCH_DIR / "claim_queue.jsonl"
CLAIM_LOCK = BATCH_DIR / "claim.lock"
CLAIM_LOG = BATCH_DIR / "claims.jsonl"
INFLIGHT_DIR = BATCH_DIR / "inflight"
MERGE_EVERY_N = 3
BATCH_SIZE = 300
SLEEP_S = 2.0


def _log(worker: str, msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}][{worker}] {msg}", flush=True)


def _key_for_worker(worker: str) -> str:
    load_dotenv()
    env_name = "DUNE_API_KEY" if worker == "A" else "DUNE_API_KEY_2"
    key = (os.environ.get(env_name) or "").strip()
    if not key:
        raise DuneQuotaOrAuth(f"{env_name} missing")
    return key


def load_all_done_mints() -> set[str]:
    done: set[str] = set()
    if FLOW_V1.exists():
        for row in pd.read_csv(FLOW_V1, usecols=["mint"])["mint"].astype(str):
            done.add(row.strip())
    for path in BATCH_DIR.glob("q4_*.csv"):
        try:
            for row in pd.read_csv(path, usecols=["mint"])["mint"].astype(str):
                done.add(row.strip())
        except Exception:
            continue
    return done


def init_claim_queue(*, force: bool = False) -> int:
    """Build claim_queue.jsonl from remaining primary_ready mints (stratified order)."""
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    INFLIGHT_DIR.mkdir(parents=True, exist_ok=True)
    if CLAIM_QUEUE.exists() and not force and CLAIM_QUEUE.stat().st_size > 0:
        n = sum(1 for _ in CLAIM_QUEUE.open())
        return n

    cohort = pd.read_csv(COHORT)
    pool = filter_primary_ready_with_mc(cohort)
    prepare_expand_artifacts(pool)
    write_gaps_doc()
    done = load_all_done_mints()
    queue = [r for r in interleave_stratified_queue(pool) if r["mint"] not in done]
    with CLAIM_QUEUE.open("w") as f:
        for r in queue:
            f.write(json.dumps({"mint": r["mint"], "t0_ts": r["t0_ts"]}) + "\n")
    return len(queue)


def _with_lock(fn):
    CLAIM_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with CLAIM_LOCK.open("a+") as lockf:
        fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)


def claim_batch(worker: str, n: int) -> list[dict[str, str]]:
    """Atomically claim up to n mints from the queue (skip already-done)."""

    def _claim() -> list[dict[str, str]]:
        done = load_all_done_mints()
        # also skip other workers' inflight
        inflight: set[str] = set()
        for p in INFLIGHT_DIR.glob("*.json"):
            try:
                data = json.loads(p.read_text())
                for m in data.get("mints") or []:
                    inflight.add(str(m))
            except Exception:
                continue

        if not CLAIM_QUEUE.exists():
            return []
        lines = CLAIM_QUEUE.read_text().splitlines()
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
        # rewrite queue without claimed (and without already-done)
        CLAIM_QUEUE.write_text("\n".join(keep) + ("\n" if keep else ""))
        if claimed:
            inflight_path = INFLIGHT_DIR / f"{worker}.json"
            inflight_path.write_text(
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
            with CLAIM_LOG.open("a") as cf:
                cf.write(
                    json.dumps(
                        {
                            "ts": datetime.now().astimezone().isoformat(),
                            "worker": worker,
                            "n": len(claimed),
                            "first": claimed[0]["mint"],
                            "last": claimed[-1]["mint"],
                        }
                    )
                    + "\n"
                )
        return claimed

    return _with_lock(_claim)


def release_inflight(worker: str, *, requeue: list[dict[str, str]] | None = None) -> None:
    def _rel() -> None:
        path = INFLIGHT_DIR / f"{worker}.json"
        if path.exists():
            path.unlink()
        if requeue:
            # prepend failed mints back
            existing = CLAIM_QUEUE.read_text() if CLAIM_QUEUE.exists() else ""
            prepend = "\n".join(json.dumps(r) for r in requeue) + ("\n" if requeue else "")
            CLAIM_QUEUE.write_text(prepend + existing)

    _with_lock(_rel)


def next_batch_path(worker: str) -> Path:
    """Unique batch filename per worker: q4_wA_b001.csv / q4_wB_b001.csv"""
    pat = re.compile(rf"q4_w{worker}_b(\d+)\.csv$")
    nums = []
    for p in BATCH_DIR.glob(f"q4_w{worker}_b*.csv"):
        m = pat.search(p.name)
        if m:
            nums.append(int(m.group(1)))
    # also allow continuing legacy q4_bNN for worker A only — use high watermark across both
    n = (max(nums) + 1) if nums else 1
    return BATCH_DIR / f"q4_w{worker}_b{n:03d}.csv"


def queue_remaining() -> int:
    if not CLAIM_QUEUE.exists():
        return 0
    return sum(1 for line in CLAIM_QUEUE.open() if line.strip())


def _merge_all_flow() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if FLOW_V1.exists():
        v1 = pd.read_csv(FLOW_V1)
        v1["__src"] = "v1"
        frames.append(v1)
    for path in sorted(BATCH_DIR.glob("q4_*.csv")):
        df = pd.read_csv(path)
        df["__src"] = path.name
        frames.append(df)
    if not frames:
        from ingestion.run_dune_q4_api import FLOW_COLS as FC
        return pd.DataFrame(columns=["mint", "t0_ts", *FC])
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(subset=["mint"], keep="last")
    return merged.drop(columns=["__src"], errors="ignore")


def do_merge(worker: str) -> dict[str, Any]:
    flow = _merge_all_flow()
    cols = ["mint", "t0_ts"] + [c for c in FLOW_COLS if c in flow.columns]
    extra = [c for c in flow.columns if c not in cols]
    flow[cols + extra].to_csv(FLOW_OUT, index=False)
    q3 = pd.read_csv(FEATURES_Q3)
    features, qa = join_features(flow, q3)
    features.to_csv(FEATURES_FLOW, index=False)
    QA_OUT.write_text(json.dumps(qa, indent=2) + "\n")
    meta = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "merged_by": worker,
        "n_flow_rows": int(len(flow)),
        "n_with_flow": qa.get("n_with_flow"),
        "n_feature_rows": int(len(features)),
        "queue_remaining": queue_remaining(),
        "feature_set_version": FEATURE_SET_FLOW,
        "qa_ok": qa.get("ok"),
        "paths": {
            "flow": str(FLOW_OUT.relative_to(ROOT)),
            "features_flow": str(FEATURES_FLOW.relative_to(ROOT)),
            "labels": str(LABELS_OUT.relative_to(ROOT)),
            "qa": str(QA_OUT.relative_to(ROOT)),
            "batches_dir": str(BATCH_DIR.relative_to(ROOT)),
        },
    }
    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    _log(worker, f"merge n_flow={len(flow)} n_with_flow={qa.get('n_with_flow')} queue_left={meta['queue_remaining']}")
    return meta


def worker_loop(
    worker: str,
    *,
    batch_size: int = BATCH_SIZE,
    sleep_s: float = SLEEP_S,
    performance: str = "medium",
) -> dict[str, Any]:
    key = _key_for_worker(worker)
    q4mod.POLL_S = 2.0
    client = DuneClient(api_key=key, timeout_s=180.0)
    batches_ok = 0
    failures: list[dict[str, Any]] = []
    credit_stop = False
    t0 = time.time()
    fetched = 0

    try:
        while True:
            remaining = queue_remaining()
            if remaining <= 0:
                # check inflight empty for both
                inflight_left = list(INFLIGHT_DIR.glob("*.json"))
                if not inflight_left:
                    _log(worker, "queue empty — done")
                    break
                _log(worker, f"queue empty but inflight={len(inflight_left)}; waiting")
                time.sleep(5)
                # if only our own stale inflight, clear
                mine = INFLIGHT_DIR / f"{worker}.json"
                if mine.exists() and remaining <= 0:
                    release_inflight(worker)
                continue

            chunk = claim_batch(worker, batch_size)
            if not chunk:
                _log(worker, "claim returned empty — recheck")
                time.sleep(2)
                if queue_remaining() <= 0:
                    break
                continue

            out_path = next_batch_path(worker)
            _log(worker, f"claimed {len(chunk)} → {out_path.name} queue_left≈{queue_remaining()}")
            try:
                rows, eid = run_one_batch(
                    client,
                    chunk,
                    batch_num=batches_ok + 1,
                    batch_total_hint=max(1, (queue_remaining() // batch_size) + batches_ok + 1),
                    performance=performance,
                )
                n_saved = save_batch_csv(out_path, rows)
                release_inflight(worker)
                batches_ok += 1
                fetched += len(chunk)
                elapsed = max(time.time() - t0, 1.0)
                rate = fetched / elapsed * 3600
                left = queue_remaining()
                eta_h = (left / (fetched / elapsed)) / 3600 if fetched else float("inf")
                _log(
                    worker,
                    f"saved {out_path.name} rows={n_saved}/{len(chunk)} eid={eid} "
                    f"fetched={fetched} left={left} rate={rate:.0f}/h ETA~{eta_h:.2f}h"
                )
                if batches_ok % MERGE_EVERY_N == 0:
                    do_merge(worker)
                if left > 0 and sleep_s > 0:
                    time.sleep(sleep_s)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                _log(worker, f"FAIL size={len(chunk)}: {err[:350]}")
                failures.append({"error": err[:500], "n": len(chunk), "worker": worker})
                # requeue on non-credit; on credit stop this worker
                if _is_credit_or_rate(exc) or "402" in err or "429" in err or "quota" in err.lower():
                    release_inflight(worker, requeue=chunk)
                    credit_stop = True
                    _log(worker, "credit/rate hard-stop for this worker")
                    break
                # exec fail: requeue and continue (maybe smaller next time — keep 300 per user)
                release_inflight(worker, requeue=chunk)
                time.sleep(max(sleep_s, 5.0))
    finally:
        client.close()

    meta = do_merge(worker)
    meta.update(
        {
            "worker": worker,
            "batches_ok": batches_ok,
            "fetched": fetched,
            "failures": failures,
            "credit_stop": credit_stop,
            "finished_at": datetime.now().astimezone().isoformat(),
        }
    )
    (BATCH_DIR / f"worker_{worker}_meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--worker", choices=["A", "B", "init"], required=True)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    p.add_argument("--sleep", type=float, default=SLEEP_S)
    p.add_argument("--performance", default="medium")
    p.add_argument("--force-reinit-queue", action="store_true")
    args = p.parse_args(argv)

    if args.worker == "init":
        n = init_claim_queue(force=args.force_reinit_queue)
        print(json.dumps({"queue_initialized": True, "n_remaining": n, "path": str(CLAIM_QUEUE)}))
        return 0

    # ensure queue exists
    if not CLAIM_QUEUE.exists() or CLAIM_QUEUE.stat().st_size == 0:
        n = init_claim_queue(force=True)
        _log(args.worker, f"initialized queue n={n}")

    meta = worker_loop(
        args.worker,
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        performance=args.performance,
    )
    print(
        json.dumps(
            {
                "worker": args.worker,
                "batches_ok": meta.get("batches_ok"),
                "fetched": meta.get("fetched"),
                "n_with_flow": meta.get("n_with_flow"),
                "queue_remaining": meta.get("queue_remaining"),
                "credit_stop": meta.get("credit_stop"),
                "n_failures": len(meta.get("failures") or []),
            },
            indent=2,
        )
    )
    return 0 if not meta.get("credit_stop") else 2


if __name__ == "__main__":
    raise SystemExit(main())
