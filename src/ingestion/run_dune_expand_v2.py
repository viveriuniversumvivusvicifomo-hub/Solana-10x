"""Expand Dune P0 flow+features to ALL primary_ready+mc via Q4 API.

1) Sample = all primary_ready with mc_usd_t0 (~82k); thrift only if API fails
2) Q3 P0 features (no labels) + separate labels
3) Q4 flow batches of 100 → data/samples/dune_q4_batches_v2/
   Skip mints already in dune_q4_flow_sample_v1.csv
4) Merge flow → dune_q4_flow_expand_v2.csv; join → features_dune_p0_flow_expand_v2.csv
5) time_since_first_trade already in Q4; holders skipped (no clean free table)
6) Credit/rate errors: stop gracefully, keep partial CSVs

Never logs or writes DUNE_API_KEY.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion.dune import DuneClient, DuneQuotaOrAuth, require_dune_api_key

# Reuse Q4 helpers from the v1 runner
from ingestion.run_dune_q4_api import (
    FLOW_COLS,
    MAX_WAIT_S,
    POLL_S,
    _is_credit_or_rate as _q4_is_credit_or_rate,
    _is_timeout as _q4_is_timeout,
    _normalize_t0,
    build_batch_sql,
    execute_sql_with_fallback,
    run_one_batch,
    save_batch_csv,
    rows_to_dataframe,
)


def _is_credit_or_rate(exc: BaseException) -> bool:
    return _q4_is_credit_or_rate(exc)


def _is_timeout(exc: BaseException) -> bool:
    if _q4_is_timeout(exc):
        return True
    text = str(exc).lower()
    return any(
        tok in text
        for tok in (
            "query_state_failed",
            "execution_failed",
            "failed_type_execution",
            "eof",
            "memory",
            "too large",
            "statement timeout",
        )
    )


def _is_heavy_or_retryable(exc: BaseException) -> bool:
    return _is_credit_or_rate(exc) or _is_timeout(exc)

ROOT = Path(__file__).resolve().parents[2]
COHORT = ROOT / "data/samples/dune_cohort_v1_labels_with_t0_mc.csv"
FLOW_V1 = ROOT / "data/samples/dune_q4_flow_sample_v1.csv"
BATCH_DIR = ROOT / "data/samples/dune_q4_batches_v2"
OUT_DIR = ROOT / "data/samples"

SAMPLE_OUT = OUT_DIR / "dune_sample_primary_ready_expand_v2.csv"
UPLOAD_OUT = OUT_DIR / "dune_sample_primary_ready_expand_v2_upload.csv"
FEATURES_Q3 = OUT_DIR / "features_dune_p0_q3_expand_v2.csv"
FEATURES_Q3_META = OUT_DIR / "features_dune_p0_q3_expand_v2.json"
LABELS_OUT = OUT_DIR / "labels_dune_expand_v2.csv"
FLOW_OUT = OUT_DIR / "dune_q4_flow_expand_v2.csv"
FEATURES_FLOW = OUT_DIR / "features_dune_p0_flow_expand_v2.csv"
META_OUT = OUT_DIR / "dune_q4_flow_expand_v2_meta.json"
QA_OUT = OUT_DIR / "qa_features_dune_p0_flow_expand_v2.json"
GAPS_OUT = OUT_DIR / "dune_expand_v2_gaps.md"

FEATURE_SET_Q3 = "features.dune.p0.q3.v1"
FEATURE_SET_FLOW = "features.dune.p0.flow.expand.v2"
DEFINITION_VERSION = "dune_cohort_v1"
MC_LO, MC_HI = 8000.0, 20000.0
BATCH_SIZE_DEFAULT = 300
SLEEP_BETWEEN_S = 2.0
POLL_S_FAST = 2.0
SEED = 42
_LEAK_COL_RE = re.compile(r"(max_mc|hit_|label_|after_t0)", re.IGNORECASE)

# Thrift caps if we need to re-scope the *fetch* queue (still prefer ALL)
THRIFT_CAPS = [20_000, 10_000, 5_000]


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _parse_t0(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def filter_primary_ready_with_mc(df: pd.DataFrame) -> pd.DataFrame:
    pr = df["primary_ready"]
    if pr.dtype == object:
        pr_ok = pr.astype(str).str.lower().isin(["true", "1", "1.0"])
    else:
        pr_ok = pr.astype(bool)
    has_mc = df["mc_usd_t0"].notna() & df["price_usd_t0"].notna()
    out = df.loc[pr_ok & has_mc].copy()
    out["hit_200k"] = out["hit_200k"].astype(int)
    out["t0_dt"] = _parse_t0(out["t0_ts"])
    out["t0_week"] = out["t0_dt"].dt.tz_convert("UTC").dt.strftime("%Y-W%W")
    return out.reset_index(drop=True)


def build_features(sample: pd.DataFrame) -> pd.DataFrame:
    mc = sample["mc_usd_t0"].astype(float)
    price = sample["price_usd_t0"].astype(float)
    proj = sample["project_at_t0"].astype(str).str.lower()
    return pd.DataFrame(
        {
            "mint": sample["mint"].astype(str),
            "t0_ts": sample["t0_ts"],
            "mc_usd_t0": mc,
            "price_usd_t0": price,
            "mc_band_pos": (mc - MC_LO) / (MC_HI - MC_LO),
            "log1p_mc_usd_t0": mc.map(lambda x: math.log1p(float(x))),
            "is_pumpdotfun": (proj == "pumpdotfun").astype(int),
            "feature_set_version": FEATURE_SET_Q3,
        }
    )


def build_labels(sample: pd.DataFrame) -> pd.DataFrame:
    hint = sample["label_primary_hint"]
    if hint.isna().any():
        hint = sample["hit_200k"]
    return pd.DataFrame(
        {
            "mint": sample["mint"].astype(str),
            "hit_200k": sample["hit_200k"].astype(int),
            "max_mc_after_t0": sample["max_mc_after_t0"].astype(float),
            "label_primary_hint": hint.fillna(sample["hit_200k"]).astype(int),
        }
    )


def stratified_cap(pool: pd.DataFrame, n_total: int, *, seed: int = SEED) -> pd.DataFrame:
    """Balanced pos/neg by week up to n_total (approx half/half when possible)."""
    pos = pool.loc[pool["hit_200k"] == 1]
    neg = pool.loc[pool["hit_200k"] == 0]
    n_pos = min(len(pos), n_total // 2)
    n_neg = min(len(neg), n_total - n_pos)
    # If neg short, give remainder to pos
    if n_pos + n_neg < n_total:
        n_pos = min(len(pos), n_total - n_neg)

    def _by_week(frame: pd.DataFrame, n: int) -> pd.DataFrame:
        if n <= 0 or frame.empty:
            return frame.iloc[0:0].copy()
        weeks = frame["t0_week"].value_counts().sort_index()
        raw = (weeks / weeks.sum() * n).astype(float)
        base = raw.astype(int)
        rem = n - int(base.sum())
        frac = (raw - base).sort_values(ascending=False)
        for w in frac.index[:rem]:
            base[w] += 1
        parts = []
        rng = seed
        for w, k in base.items():
            k = int(k)
            if k <= 0:
                continue
            sub = frame.loc[frame["t0_week"] == w]
            parts.append(sub.sample(n=min(k, len(sub)), random_state=rng))
            rng += 1
        out = pd.concat(parts, ignore_index=True) if parts else frame.iloc[0:0].copy()
        if len(out) < n:
            used = set(out["mint"].astype(str))
            leftover = frame.loc[~frame["mint"].astype(str).isin(used)]
            need = n - len(out)
            if need > 0 and not leftover.empty:
                out = pd.concat(
                    [out, leftover.sample(n=min(need, len(leftover)), random_state=seed)],
                    ignore_index=True,
                )
        return out

    sample = pd.concat([_by_week(pos, n_pos), _by_week(neg, n_neg)], ignore_index=True)
    return sample.sample(frac=1.0, random_state=seed).reset_index(drop=True)


def interleave_stratified_queue(pool: pd.DataFrame, *, seed: int = SEED) -> list[dict[str, str]]:
    """Order ALL mints so early batches are week-balanced pos/neg (round-robin)."""
    rng = pool.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    buckets: dict[tuple[str, int], list[dict[str, str]]] = {}
    for _, r in rng.iterrows():
        key = (str(r["t0_week"]), int(r["hit_200k"]))
        buckets.setdefault(key, []).append({"mint": str(r["mint"]), "t0_ts": str(r["t0_ts"])})
    keys = sorted(buckets.keys())
    queue: list[dict[str, str]] = []
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                queue.append(buckets[k].pop())
    return queue


def existing_batch_paths() -> list[Path]:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    # legacy q4_bNN.csv + parallel q4_wA_bNNN.csv / q4_wB_bNNN.csv
    paths = set(BATCH_DIR.glob("q4_b*.csv")) | set(BATCH_DIR.glob("q4_w*_b*.csv"))
    return sorted(paths)


def load_done_mints_v2() -> set[str]:
    done: set[str] = set()
    for path in existing_batch_paths():
        with path.open(newline="") as f:
            for row in csv.DictReader(f):
                if row.get("mint"):
                    done.add(row["mint"].strip())
    return done


def load_flow_v1_mints() -> set[str]:
    if not FLOW_V1.exists():
        return set()
    done: set[str] = set()
    with FLOW_V1.open(newline="") as f:
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


def write_gaps_doc() -> None:
    GAPS_OUT.write_text(
        """# Dune expand v2 — gaps / deferred

- **time_since_first_trade_s**: already returned by Q4 flow SQL (`MAX(secs_before_t0)`). No extra query.
- **holders / concentration**: skipped — no clean free Dune table for pre-T0 holder counts without a heavy scan or paid dataset. Documented gap; do not invent.
- **sol_usd_t0 Pyth as-of T0**: still pending (not Dune Q4).
- **true hit_10x_30d**: label still proxy via `hit_200k` / `label_primary_hint` until full 30d follow-up.
"""
    )


def prepare_expand_artifacts(pool: pd.DataFrame) -> dict[str, Any]:
    """Write sample, upload, Q3 features, labels for the expand target set."""
    sample_cols = [
        "mint",
        "t0_ts",
        "hit_200k",
        "mc_usd_t0",
        "price_usd_t0",
        "primary_ready",
        "project_at_t0",
        "tx_id_t0",
    ]
    sample = pool[[c for c in sample_cols if c in pool.columns]].copy()
    sample["hit_200k"] = sample["hit_200k"].astype(int)
    sample["primary_ready"] = True
    sample.to_csv(SAMPLE_OUT, index=False)

    upload = sample[["mint", "t0_ts"]].copy()
    upload.to_csv(UPLOAD_OUT, index=False)

    features = build_features(pool)
    features.to_csv(FEATURES_Q3, index=False)
    labels = build_labels(pool)
    labels.to_csv(LABELS_OUT, index=False)

    week_hit = pool.groupby(["t0_week", "hit_200k"]).size().unstack(fill_value=0)
    week_counts: dict[str, Any] = {}
    for hit_val in week_hit.columns:
        week_counts[str(int(hit_val))] = {
            str(w): int(week_hit.loc[w, hit_val]) for w in week_hit.index
        }

    meta = {
        "feature_set_version": FEATURE_SET_Q3,
        "definition_version": DEFINITION_VERSION,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "expand": "v2_all_primary_ready_with_mc",
        "n_sample": int(len(sample)),
        "n_pos": int((sample["hit_200k"] == 1).sum()),
        "n_neg": int((sample["hit_200k"] == 0).sum()),
        "week_counts_by_hit200k": week_counts,
        "labels_excluded_from_features": True,
        "no_lookahead": True,
        "outputs": {
            "sample": str(SAMPLE_OUT.relative_to(ROOT)),
            "upload": str(UPLOAD_OUT.relative_to(ROOT)),
            "features_q3": str(FEATURES_Q3.relative_to(ROOT)),
            "labels": str(LABELS_OUT.relative_to(ROOT)),
        },
    }
    FEATURES_Q3_META.write_text(json.dumps(meta, indent=2) + "\n")
    write_gaps_doc()
    _log(
        f"prepared expand sample n={len(sample)} pos={meta['n_pos']} neg={meta['n_neg']} "
        f"→ {SAMPLE_OUT.name}"
    )
    return meta


def merge_flow(include_v1: bool = True) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    if include_v1 and FLOW_V1.exists():
        v1 = pd.read_csv(FLOW_V1)
        v1["__src"] = "v1"
        frames.append(v1)
    for path in existing_batch_paths():
        df = pd.read_csv(path)
        df["__src"] = path.name
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["mint", "t0_ts", *FLOW_COLS])
    merged = pd.concat(frames, ignore_index=True)
    # Prefer v2 batch over v1 if duplicate (shouldn't happen if we skip)
    merged = merged.drop_duplicates(subset=["mint"], keep="last")
    return merged.drop(columns=["__src"], errors="ignore")


def join_features(flow: pd.DataFrame, q3: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    flow_keep = flow[["mint"] + [c for c in FLOW_COLS if c in flow.columns]].copy()
    out = q3.merge(flow_keep, on="mint", how="left", suffixes=("", "_flowdup"))
    matched = out["trade_count_total"].notna() if "trade_count_total" in out.columns else pd.Series([False] * len(out))
    for c in FLOW_COLS:
        if c not in out.columns:
            out[c] = 0
        else:
            out[c] = pd.to_numeric(out[c], errors="coerce").fillna(0)
    out["feature_set_version"] = FEATURE_SET_FLOW
    leak = [c for c in out.columns if _LEAK_COL_RE.search(c)]
    n_with_flow = int(matched.sum())
    qa = {
        "generated_at": datetime.now().astimezone().isoformat(),
        "ok": len(leak) == 0,
        "n_q3_features": int(len(q3)),
        "n_flow_rows": int(len(flow)),
        "n_joined": int(len(out)),
        "n_with_flow": n_with_flow,
        "n_flow_matched_nonzero_trades": int(out["trade_count_total"].ne(0).sum())
        if "trade_count_total" in out.columns
        else None,
        "leak_col_regex": _LEAK_COL_RE.pattern,
        "leak_cols_found": leak,
        "feature_columns": list(out.columns),
        "assertions": {
            "no_leak_columns": len(leak) == 0,
            "n_rows_match_q3": int(len(out)) == int(len(q3)),
        },
        "paths": {
            "features_q3": str(FEATURES_Q3.relative_to(ROOT)),
            "flow": str(FLOW_OUT.relative_to(ROOT)),
            "features_flow": str(FEATURES_FLOW.relative_to(ROOT)),
            "labels": str(LABELS_OUT.relative_to(ROOT)),
        },
        "gaps": {
            "holders": "skipped — no clean free pre-T0 holders table",
            "time_since_first_trade_s": "included in Q4 FLOW_COLS",
        },
    }
    return out, qa


def finalize(meta: dict[str, Any]) -> dict[str, Any]:
    flow = merge_flow(include_v1=True)
    flow_cols_ordered = ["mint", "t0_ts"] + [c for c in FLOW_COLS if c in flow.columns]
    extra = [c for c in flow.columns if c not in flow_cols_ordered]
    flow[flow_cols_ordered + extra].to_csv(FLOW_OUT, index=False)
    _log(f"merged flow rows={len(flow)} → {FLOW_OUT}")

    q3 = pd.read_csv(FEATURES_Q3)
    features, qa = join_features(flow, q3)
    features.to_csv(FEATURES_FLOW, index=False)
    QA_OUT.write_text(json.dumps(qa, indent=2) + "\n")
    _log(f"joined features rows={len(features)} n_with_flow={qa['n_with_flow']} leak_ok={qa['ok']}")

    meta.update(
        {
            "n_flow_rows": int(len(flow)),
            "n_with_flow": qa["n_with_flow"],
            "n_feature_rows": int(len(features)),
            "n_batches_on_disk": len(existing_batch_paths()),
            "batch_files": [p.name for p in existing_batch_paths()],
            "n_failed_batches": len(meta.get("failures") or []),
            "paths": {
                "batches_dir": str(BATCH_DIR.relative_to(ROOT)),
                "sample": str(SAMPLE_OUT.relative_to(ROOT)),
                "features_q3": str(FEATURES_Q3.relative_to(ROOT)),
                "flow": str(FLOW_OUT.relative_to(ROOT)),
                "features_flow": str(FEATURES_FLOW.relative_to(ROOT)),
                "labels": str(LABELS_OUT.relative_to(ROOT)),
                "qa": str(QA_OUT.relative_to(ROOT)),
                "gaps": str(GAPS_OUT.relative_to(ROOT)),
            },
            "qa_ok": qa["ok"],
            "finished_at": datetime.now().astimezone().isoformat(),
        }
    )
    META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
    _log(f"meta → {META_OUT}")
    return meta


def run(
    *,
    batch_size: int = BATCH_SIZE_DEFAULT,
    sleep_s: float = SLEEP_BETWEEN_S,
    performance: str = "medium",
    dry_run: bool = False,
    max_batches: int | None = None,
    cap: int | None = None,
    prepare_only: bool = False,
) -> dict[str, Any]:
    require_dune_api_key()

    cohort = pd.read_csv(COHORT)
    pool = filter_primary_ready_with_mc(cohort)
    n_full = len(pool)
    _log(f"pool primary_ready+mc = {n_full} (pos={(pool['hit_200k']==1).sum()} neg={(pool['hit_200k']==0).sum()})")

    if cap is not None and cap < n_full:
        _log(f"applying thrift cap={cap} (stratified pos/neg by week)")
        pool = stratified_cap(pool, cap, seed=SEED)
        _log(f"capped pool n={len(pool)} pos={(pool['hit_200k']==1).sum()} neg={(pool['hit_200k']==0).sum()}")

    prep = prepare_expand_artifacts(pool)
    n_target = len(pool)

    if prepare_only:
        meta = {
            "created_at": datetime.now().astimezone().isoformat(),
            "feature_set_version": FEATURE_SET_FLOW,
            "n_target": n_target,
            "prepare_only": True,
            "prep": prep,
        }
        return finalize(meta)

    v1_done = load_flow_v1_mints()
    v2_done = load_done_mints_v2()
    skip = v1_done | v2_done

    # Stratified interleave so early partial is balanced
    queue_all = interleave_stratified_queue(pool, seed=SEED)
    remaining = [r for r in queue_all if r["mint"] not in skip]
    start_num = next_batch_num()
    total_hint = (
        start_num + (len(remaining) + batch_size - 1) // batch_size - 1 if remaining else start_num - 1
    )

    _log(
        f"n_target={n_target} v1_skip={len(v1_done)} v2_done={len(v2_done)} "
        f"remaining={len(remaining)} next_batch=b{start_num:02d} batch_size={batch_size}"
    )

    meta: dict[str, Any] = {
        "created_at": datetime.now().astimezone().isoformat(),
        "feature_set_version": FEATURE_SET_FLOW,
        "n_target": n_target,
        "n_full_pool": n_full,
        "cap_applied": cap,
        "n_v1_skip": len(v1_done),
        "n_v2_done_before": len(v2_done),
        "n_remaining_before": len(remaining),
        "batch_size_requested": batch_size,
        "performance": performance,
        "batches": [],
        "failures": [],
        "execution_ids": [],
        "credit_errors": [],
        "stopped_reason": None,
        "prep": prep,
    }

    if dry_run:
        meta["dry_run"] = True
        meta["planned_n_batches"] = (len(remaining) + batch_size - 1) // batch_size if remaining else 0
        META_OUT.write_text(json.dumps(meta, indent=2) + "\n")
        _log(f"dry-run planned {meta['planned_n_batches']} batches")
        return meta

    client = DuneClient(timeout_s=180.0)
    # Faster status polls for large batches
    import ingestion.run_dune_q4_api as q4mod
    q4mod.POLL_S = 2.0
    batch_num = start_num
    t_run0 = time.time()
    mints_fetched_this_run = 0
    queue = list(remaining)
    batches_run = 0
    consecutive_credit = 0

    try:
        while queue:
            if max_batches is not None and batches_run >= max_batches:
                meta["stopped_reason"] = f"max_batches={max_batches}"
                _log(meta["stopped_reason"])
                break

            size = min(batch_size, len(queue))
            chunk = queue[:size]
            out_path = BATCH_DIR / f"q4_b{batch_num:02d}.csv"

            if out_path.exists():
                _log(f"skip existing {out_path.name}")
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
                _log(f"saved {out_path.name} rows={n_saved}/{len(chunk)} batch_size={size}")
                req = {r["mint"] for r in chunk}
                queue = [r for r in queue if r["mint"] not in req]
                batch_num += 1
                batches_run += 1
                mints_fetched_this_run += len(chunk)
                consecutive_credit = 0
                elapsed = max(time.time() - t_run0, 1.0)
                rate = mints_fetched_this_run / elapsed  # mints/sec
                eta_s = len(queue) / rate if rate > 0 else float("inf")
                eta_h = eta_s / 3600.0
                _log(
                    f"progress fetched_this_run={mints_fetched_this_run} remaining={len(queue)} "
                    f"rate={rate*3600:.0f} mints/h ETA~{eta_h:.1f}h ({eta_s/60:.0f}m)"
                )
                if queue:
                    if sleep_s > 0:
                        _log(f"sleep {sleep_s}s before next execute")
                        time.sleep(sleep_s)
            except (DuneQuotaOrAuth, TimeoutError, RuntimeError, Exception) as exc:
                err_s = f"{type(exc).__name__}: {exc}"
                _log(f"batch b{batch_num:02d} FAILED size={size}: {err_s[:400]}")
                fail_rec = {
                    "batch": batch_num,
                    "size": size,
                    "error": err_s[:500],
                    "first_mint": chunk[0]["mint"],
                }
                meta["failures"].append(fail_rec)
                if _is_heavy_or_retryable(exc):
                    if _is_credit_or_rate(exc):
                        meta["credit_errors"].append(fail_rec)
                    consecutive_credit += 1
                    kind = "credit/rate" if _is_credit_or_rate(exc) else "timeout/exec_fail"
                    # Ladder: 1000 → 500 → 300 → 200 → 100
                    if size > 500:
                        batch_size = 500
                        _log(f"{kind} — shrink batch_size → 500, retry")
                        time.sleep(max(sleep_s, 3.0))
                        continue
                    if size > 300:
                        batch_size = 300
                        _log(f"{kind} — shrink batch_size → 300, retry")
                        time.sleep(max(sleep_s, 3.0))
                        continue
                    if size > 200:
                        batch_size = 200
                        _log(f"{kind} — shrink batch_size → 200, retry")
                        time.sleep(max(sleep_s, 3.0))
                        continue
                    if size > 100:
                        batch_size = 100
                        _log(f"{kind} — shrink batch_size → 100, retry")
                        time.sleep(max(sleep_s, 3.0))
                        continue
                    meta["stopped_reason"] = (
                        "credit_or_rate_at_min_batch" if _is_credit_or_rate(exc) else "timeout_at_min_batch"
                    )
                    _log(f"{meta['stopped_reason']} — stopping gracefully")
                    break
                # Non-quota: skip chunk, continue
                req = {r["mint"] for r in chunk}
                queue = [r for r in queue if r["mint"] not in req]
                batch_num += 1
                batches_run += 1
                time.sleep(sleep_s)
        else:
            meta["stopped_reason"] = "queue_exhausted"
    finally:
        client.close()

    return finalize(meta)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE_DEFAULT)
    p.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_S)
    p.add_argument("--performance", default="medium", choices=["medium", "large", "free"])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-batches", type=int, default=None)
    p.add_argument("--cap", type=int, default=None, help="Optional thrift cap on expand set")
    p.add_argument("--prepare-only", action="store_true")
    args = p.parse_args(argv)
    meta = run(
        batch_size=args.batch_size,
        sleep_s=args.sleep,
        performance=args.performance,
        dry_run=args.dry_run,
        max_batches=args.max_batches,
        cap=args.cap,
        prepare_only=args.prepare_only,
    )
    summary = {
        "n_target": meta.get("n_target"),
        "n_with_flow": meta.get("n_with_flow"),
        "n_flow_rows": meta.get("n_flow_rows"),
        "n_feature_rows": meta.get("n_feature_rows"),
        "n_batches": len(meta.get("batches") or []),
        "n_failed_batches": meta.get("n_failed_batches"),
        "n_credit_errors": len(meta.get("credit_errors") or []),
        "stopped_reason": meta.get("stopped_reason"),
        "qa_ok": meta.get("qa_ok"),
        "paths": meta.get("paths"),
    }
    print(json.dumps(summary, indent=2))
    return 0 if not meta.get("credit_errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
