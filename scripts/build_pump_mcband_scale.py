#!/usr/bin/env python3
"""ORPHAN / DEPRECATED — Pump MC-band *n-scale* recipe (NOT the 6.6× USD scale).

Status 2026-10-02: INCOMPLETE / ORPHAN / QUARANTINED (D-07)
  - Quarantine: archive/quarantine/mcband_scale_20261002/  (see NO-GO_INCOMPLETE.md)
  - Incomplete fetch (~1.3k/2.8k); no features matrix / usable slice
  - Superseded for train by: build_pump_path_a_livelike.py (live-like geometry)
  - Default ordered_cache_dirs EXCLUDES scale; opt-in --reuse-orphan-scale only

CLI: this script REFUSES by default (exit 2). Pass --force-orphan to run legacy body.
USD 6.6× remains OFF forever (orthogonal naming collision).

Original intent (historical):
  Scale Pump MC-band recipe to ~2–3k mints → features_pump_path_a_mcband_scale_*.
  Frozen recipe identical to build_pump_mcband_pilot.py (pump_mc_band_from_trades_v1).
  Hard constraints: 0 Dune · Lite OFF · USD scale OFF · expand_create_proxy OFF
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS  # noqa: E402
from ingestion.pump_constants import MC_HI_USD, MC_LO_USD  # noqa: E402
from ingestion.t0_capture import (  # noqa: E402
    PUMP_MC_SIGHTING_DEF,
    find_t0_pump_mc_sighting,
    is_scoreable_pump_capture,
)

# Reuse frozen helpers from pilot
from build_pump_mcband_pilot import (  # noqa: E402
    EXPAND_T0_SLACK,
    HIT_MULTIPLE,
    LABEL_HORIZON,
    MAX_DEEP_PAGES,
    T0_POLICY,
    UI_SUPPLY,
    _aware_dt,
    _load_json,
    _save_json,
    _trade_ts_mc,
    _utcnow,
    deep_fetch_trades,
    find_band_t0,
    relabel_hit_10x,
    series_from_raw,
)

STAMP_DEFAULT = datetime.now().strftime("%Y%m%d")
MIN_INTERVAL_S = 1.0
MAX_HTTP_BUDGET_FETCH = 10000  # initial missing-mint fetch
MAX_HTTP_BUDGET_DEEP = 3500
MAX_DEEP_MINTS = 350
MAX_FETCH_PAGES = 10  # until band / expand t0 (throughput)
MAX_FAIL_FRAC = 0.25
MAX_CONSEC_HARD_FAIL = 15
MAX_429_RETRIES_TOTAL = 60  # abort if rate-limited badly (prefer 0×429)


def build_scale_sample(
    feat_path: Path,
    lab_path: Path,
    pilot_sample_path: Path,
    *,
    n_target: int = 2800,
    seed: int = 42,
    n_neg_min: int = 1200,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Pilot500 ∪ oversampled non-pilot positives ∪ negatives → n_target."""
    header = pd.read_csv(feat_path, nrows=0).columns.tolist()
    usecols = ["mint", "t0_ts", "mc_usd_t0", "create_ts", "creator_pubkey"] + [
        c for c in FEATURE_SETS["+q5b"] if c in header
    ]
    cols = [c for c in usecols if c in header]
    feat = pd.read_csv(feat_path, usecols=cols)
    lab = pd.read_csv(lab_path)
    lab_cols = [c for c in ["mint", "hit_10x_30d", "hit_200k", "max_mc_after_t0", "max_multiple_30d", "followup_days_available"] if c in lab.columns]
    df = feat.merge(lab[lab_cols], on="mint", how="inner")
    df["hit_10x_30d"] = df["hit_10x_30d"].astype(int)
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["t0"]).copy()

    pilot = pd.read_csv(pilot_sample_path)
    pilot_mints = set(pilot["mint"].astype(str))
    # Align pilot rows from full expand (fresher cols + labels)
    pilot_rows = df[df["mint"].isin(pilot_mints)].copy()
    pilot_rows["in_pilot500"] = 1

    rest = df[~df["mint"].isin(pilot_mints)].copy()
    rest = rest[rest["create_ts"].notna()].copy()
    rest["in_pilot500"] = 0

    n_remain = max(0, n_target - len(pilot_rows))
    # Keep ≥ n_neg_min negatives overall (floor for class diversity under HTTP cap)
    pilot_neg = int((pilot_rows["hit_10x_30d"] == 0).sum())
    need_neg = max(0, n_neg_min - pilot_neg)
    need_neg = min(need_neg, n_remain)
    n_new_pos_budget = n_remain - need_neg

    pos = rest[rest["hit_10x_30d"] == 1]
    neg = rest[rest["hit_10x_30d"] == 0]
    rng = np.random.default_rng(seed)

    def _pick(sub: pd.DataFrame, k: int) -> pd.DataFrame:
        if k <= 0 or len(sub) == 0:
            return sub.iloc[0:0].copy()
        if k >= len(sub):
            return sub.copy()
        sub = sub.sort_values("t0", ascending=False).reset_index(drop=True)
        mid = max(1, len(sub) // 2)
        recent, older = sub.iloc[:mid], sub.iloc[mid:]
        k_r = min(int(round(k * 0.7)), len(recent))
        k_o = min(k - k_r, len(older))
        k_r = min(k - k_o, len(recent))
        parts = [recent.iloc[rng.choice(len(recent), size=k_r, replace=False)]]
        if k_o > 0:
            parts.append(older.iloc[rng.choice(len(older), size=k_o, replace=False)])
        out = pd.concat(parts, ignore_index=True)
        if len(out) < k:
            left = sub[~sub["mint"].isin(out["mint"])]
            need = k - len(out)
            if len(left):
                idx = rng.choice(len(left), size=min(need, len(left)), replace=False)
                out = pd.concat([out, left.iloc[idx]], ignore_index=True)
        return out

    new_pos = _pick(pos, min(n_new_pos_budget, len(pos)))
    slots_left = n_remain - len(new_pos)
    new_neg = _pick(neg, min(slots_left, len(neg)))
    # If still short (pos/neg exhaustion), top up from leftover rest
    picked_extra = pd.concat([new_pos, new_neg], ignore_index=True)
    if len(pilot_rows) + len(picked_extra) < n_target:
        left = rest[~rest["mint"].isin(picked_extra["mint"])]
        need = n_target - len(pilot_rows) - len(picked_extra)
        if len(left) and need > 0:
            picked_extra = pd.concat([picked_extra, _pick(left, need)], ignore_index=True)

    out = pd.concat([pilot_rows, picked_extra], ignore_index=True)
    out = out.drop_duplicates(subset=["mint"]).reset_index(drop=True)
    if len(out) > n_target:
        # keep all pilot; trim extras
        extra = out[out["in_pilot500"] == 0]
        keep_extra = extra.sample(n=n_target - len(pilot_rows), random_state=seed) if len(extra) > n_target - len(pilot_rows) else extra
        out = pd.concat([pilot_rows, keep_extra], ignore_index=True).drop_duplicates("mint")

    meta = {
        "sample_rule": (
            "pilot500 ∪ non-pilot expand positives(create_ts) first "
            f"then negatives → n_target={n_target}; n_neg_min={n_neg_min}; "
            "NOT all ~11k expand positives (HTTP / TOTAL cap)"
        ),
        "n_target": n_target,
        "n_sampled": int(len(out)),
        "n_pilot500": int((out["in_pilot500"] == 1).sum()),
        "n_new": int((out["in_pilot500"] == 0).sum()),
        "n_pos_expand": int((out["hit_10x_30d"] == 1).sum()),
        "n_neg_expand": int((out["hit_10x_30d"] == 0).sum()),
        "expand_label_rate": float(out["hit_10x_30d"].mean()),
        "n_with_create_ts": int(out["create_ts"].notna().sum()),
        "seed": seed,
        "n_neg_min": n_neg_min,
        "universe_pos_non_pilot_with_create": int(len(pos)),
        "note_all_pos_infeasible": (
            f"expand non-pilot positives with create_ts={len(pos)}; "
            "taking all would exceed 2.5–3.5k TOTAL — capped under n_target"
        ),
    }
    return out, meta



# Shared cache/fetch helpers — canonical home is pump_path_a_common (ORPHAN re-export).
from pump_path_a_common import (  # noqa: E402
    _load_json,
    _load_raw,
    _resolve_trades_path,
    _save_json,
    _utcnow,
    fetch_missing_band_aware,
    path_a_invariants,
)

ORPHAN_STATUS = path_a_invariants()["orphan_scripts"]["build_pump_mcband_scale.py"]

QUARANTINE_DIR = ROOT / "archive/quarantine/mcband_scale_20261002"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--force-orphan",
        action="store_true",
        help="Bypass ORPHAN refuse (legacy incomplete recipe; not for train/WF/paper)",
    )
    # Pre-parse force flag so refuse happens before heavy work / other required paths
    pre, _unknown = ap.parse_known_args()
    if not pre.force_orphan:
        print(
            json.dumps(
                {
                    "status": "refused_orphan",
                    "orphan": ORPHAN_STATUS,
                    "quarantine": str(QUARANTINE_DIR.relative_to(ROOT)),
                    "readme": str((QUARANTINE_DIR / "NO-GO_INCOMPLETE.md").relative_to(ROOT))
                    if (QUARANTINE_DIR / "NO-GO_INCOMPLETE.md").is_file()
                    else None,
                    "hint": "use build_pump_path_a_livelike / build_pump_path_a.py livelike; "
                    "pass --force-orphan only for forensic legacy runs",
                },
                indent=2,
            ),
            flush=True,
        )
        return 2
    print(
        json.dumps(
            {
                "orphan_warning": ORPHAN_STATUS,
                "quarantine": str(QUARANTINE_DIR.relative_to(ROOT)),
                "hint": "prefer build_pump_path_a_livelike / build_pump_path_a.py",
            },
            indent=2,
        ),
        flush=True,
    )
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--pilot-stamp", default="20261002")
    ap.add_argument("--n-target", type=int, default=2800)
    ap.add_argument("--n-neg-min", type=int, default=1200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample-only", action="store_true")
    ap.add_argument("--build-only", action="store_true", help="Skip fetch; matrix from caches")
    ap.add_argument("--no-deep-fetch", action="store_false", dest="deep_fetch")
    ap.add_argument("--deep-fetch", action="store_true", default=True)
    ap.add_argument("--max-deep-mints", type=int, default=MAX_DEEP_MINTS)
    ap.add_argument("--max-deep-pages", type=int, default=MAX_DEEP_PAGES)
    ap.add_argument("--max-fetch-pages", type=int, default=MAX_FETCH_PAGES)
    ap.add_argument("--max-http-fetch", type=int, default=MAX_HTTP_BUDGET_FETCH)
    ap.add_argument("--max-http-deep", type=int, default=MAX_HTTP_BUDGET_DEEP)
    ap.add_argument("--min-interval-s", type=float, default=MIN_INTERVAL_S)
    ap.add_argument("--allow-expand-proxy", action="store_true", default=False)
    args = ap.parse_args()

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    pilot_sample = ROOT / f"data/samples/pump_pilot500_sample_{args.pilot_stamp}.csv"
    pilot_trades = ROOT / f"data/samples/pump_pilot500_trades_{args.pilot_stamp}"
    mcband_extra = ROOT / f"data/samples/pump_mcband_trades_extra_{args.pilot_stamp}"

    out_sample_universe = ROOT / f"data/samples/pump_mcband_scale_sample_{args.stamp}.csv"
    out_matrix = ROOT / f"data/samples/features_pump_path_a_mcband_scale_{args.stamp}.csv"
    out_usable = ROOT / f"data/samples/pump_mcband_scale_usable_{args.stamp}.csv"
    out_t0 = ROOT / f"cycle0/artifacts/pump_mcband_scale_t0_recon_{args.stamp}.csv"
    out_meta = ROOT / f"cycle0/artifacts/pump_mcband_scale_build_meta_{args.stamp}.json"
    fetch_ck = ROOT / f"cycle0/checkpoints/pump_mcband_scale_fetch_{args.stamp}.json"
    deep_ck = ROOT / f"cycle0/checkpoints/pump_mcband_scale_deep_{args.stamp}.json"
    scale_trades = ROOT / f"data/samples/pump_mcband_scale_trades_{args.stamp}"
    scale_deep = ROOT / f"data/samples/pump_mcband_scale_trades_deep_{args.stamp}"

    sample, sample_meta = build_scale_sample(
        feat_path,
        lab_path,
        pilot_sample,
        n_target=args.n_target,
        seed=args.seed,
        n_neg_min=args.n_neg_min,
    )
    # Persist sample with expand label renamed for clarity
    sample = sample.rename(columns={"hit_10x_30d": "hit_10x_30d_expand"})
    sample.to_csv(out_sample_universe, index=False)
    print(json.dumps({"sample": sample_meta, "path": str(out_sample_universe)}, indent=2))
    if args.sample_only:
        _save_json(out_meta, {"kind": "pump_mcband_scale_sample_only", "sample": sample_meta, "generated_at": _utcnow()})
        return 0

    cache_dirs = [scale_deep, scale_trades, mcband_extra, pilot_trades]
    t0_expand = {}
    for _, sr in sample.iterrows():
        t0_expand[str(sr["mint"])] = _aware_dt(sr.get("t0_ts"))

    fetch_stats: dict[str, Any] = {"skipped": True}
    if not args.build_only:
        mints = [str(m) for m in sample["mint"].tolist()]
        # Prioritize: missing cache first, then positives
        def _priority(m: str) -> tuple[int, int]:
            has = 0 if _resolve_trades_path(m, cache_dirs) else 1
            row = sample[sample["mint"] == m].iloc[0]
            pos = 0 if int(row.get("hit_10x_30d_expand") or 0) == 1 else 1
            return (has, pos)

        mints_sorted = sorted(mints, key=_priority)
        ck = fetch_missing_band_aware(
            mints_sorted,
            t0_expand_by_mint=t0_expand,
            trades_dir=scale_trades,
            checkpoint=fetch_ck,
            cache_dirs=cache_dirs,
            max_pages=args.max_fetch_pages,
            max_http=args.max_http_fetch,
            min_interval_s=args.min_interval_s,
        )
        fetch_stats = ck.get("stats") or {}
        fetch_stats["stopped"] = ck.get("stopped")
        fetch_stats["stop_reason"] = ck.get("stop_reason")
        print(json.dumps({"fetch_done": fetch_stats}, indent=2))
        if ck.get("stopped") and "429" in str(ck.get("stop_reason") or ""):
            print(json.dumps({"status": "abort_rate_limited", "reason": ck.get("stop_reason")}))
            # continue to build whatever we have if usable may still be ≥1000

    # Pass 1: recon from caches
    recon_rows: list[dict[str, Any]] = []
    need_deep: list[str] = []
    trades_by_mint: dict[str, list[dict[str, Any]]] = {}
    for _, sr in sample.iterrows():
        mint = str(sr["mint"])
        path = _resolve_trades_path(mint, cache_dirs)
        raw = _load_raw(path)
        trades_by_mint[mint] = raw
        series = series_from_raw(raw)
        expand_t0 = _aware_dt(sr.get("t0_ts"))
        create_ts = _aware_dt(sr.get("create_ts"))
        expand_mc = float(sr["mc_usd_t0"]) if pd.notna(sr.get("mc_usd_t0")) else None
        band = find_band_t0(series) if series else None
        row: dict[str, Any] = {
            "mint": mint,
            "expand_t0_ts": expand_t0.isoformat() if expand_t0 else None,
            "expand_mc_usd_t0": expand_mc,
            "create_ts": create_ts.isoformat() if create_ts else None,
            "cache_path": str(path) if path else None,
            "n_raw_cache": len(raw),
            "hit_10x_30d_expand": int(sr["hit_10x_30d_expand"]) if pd.notna(sr.get("hit_10x_30d_expand")) else None,
            "in_pilot500": int(sr.get("in_pilot500") or 0),
        }
        if band:
            t0, mc, px, method = band
            row.update(
                {
                    "reconstructable": 1,
                    "reconstruct_method": method,
                    "t0_ts": t0.isoformat(),
                    "mc_usd_t0": mc,
                    "price_usd_t0": px,
                    "needs_deep": 0,
                }
            )
        else:
            row.update(
                {
                    "reconstructable": 0,
                    "reconstruct_method": "none",
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "price_usd_t0": None,
                    "needs_deep": 1,
                }
            )
            need_deep.append(mint)
        recon_rows.append(row)

    deep_stats: dict[str, Any] = {"attempted": 0, "ok": 0, "found_band": 0, "http_calls": 0, "skipped": 0}
    deep_done = _load_json(deep_ck)
    deep_done.setdefault("done", {})
    deep_stats["found_band"] = sum(
        1 for v in (deep_done.get("done") or {}).values() if v.get("ok") and v.get("found_band")
    )
    deep_stats["ok"] = sum(1 for v in (deep_done.get("done") or {}).values() if v.get("ok"))

    if args.deep_fetch and need_deep and not args.build_only:
        from ingestion.pump_frontend import PumpFrontendClient

        scale_deep.mkdir(parents=True, exist_ok=True)
        client = PumpFrontendClient(min_interval_s=args.min_interval_s, max_retries_429=5)
        try:
            for mint in need_deep[: args.max_deep_mints]:
                if client.log.n_calls >= args.max_http_deep:
                    deep_stats["stopped"] = "http_budget"
                    break
                if client.log.n_retries_429 >= MAX_429_RETRIES_TOTAL:
                    deep_stats["stopped"] = "429_retries"
                    break
                prev = deep_done["done"].get(mint)
                if prev and prev.get("ok"):
                    deep_stats["skipped"] += 1
                    continue
                sr = sample[sample["mint"] == mint].iloc[0]
                expand_t0 = _aware_dt(sr.get("t0_ts"))
                deep_stats["attempted"] += 1
                try:
                    raw, fmeta = deep_fetch_trades(
                        mint, client=client, target_ts=expand_t0, max_pages=args.max_deep_pages,
                        pre_band_s=120.0,
                    )
                    out_path = scale_deep / f"{mint}.json"
                    out_path.write_text(
                        json.dumps(
                            {
                                "mint": mint,
                                "n_raw": len(raw),
                                "fetch_meta": fmeta,
                                "fetched_at": _utcnow(),
                                "trades": raw,
                            }
                        )
                    )
                    deep_done["done"][mint] = {
                        "ok": True,
                        "found_band": bool(fmeta.get("found_band")),
                        "n_raw": len(raw),
                        "n_pages": fmeta.get("n_pages"),
                        "path": str(out_path.relative_to(ROOT)),
                    }
                    deep_stats["ok"] += 1
                    if fmeta.get("found_band"):
                        deep_stats["found_band"] += 1
                except Exception as e:  # noqa: BLE001
                    deep_done["done"][mint] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300]}
                deep_stats["http_calls"] = client.log.n_calls
                deep_stats["n_retries_429"] = client.log.n_retries_429
                deep_done["stats"] = deep_stats
                deep_done["updated_at"] = _utcnow()
                _save_json(deep_ck, deep_done)
                if deep_stats["attempted"] % 10 == 0:
                    print(json.dumps({"deep_progress": deep_stats}), flush=True)
        finally:
            client.close()
            deep_stats["http_calls"] = client.log.n_calls
            deep_stats["n_retries_429"] = client.log.n_retries_429
            deep_done["stats"] = deep_stats
            deep_done["finished_at"] = _utcnow()
            _save_json(deep_ck, deep_done)

    # Merge deep into trades + recon
    recon_by_mint = {r["mint"]: r for r in recon_rows}
    for mint, r in recon_by_mint.items():
        path = _resolve_trades_path(mint, cache_dirs)
        raw = _load_raw(path)
        dprev = (deep_done.get("done") or {}).get(mint)
        if dprev and dprev.get("ok"):
            dpath = ROOT / dprev["path"] if not Path(dprev["path"]).is_absolute() else Path(dprev["path"])
            draw = _load_raw(dpath)
            if len(draw) >= len(raw):
                raw = draw
                path = dpath
        trades_by_mint[mint] = raw
        series = series_from_raw(raw)
        cache_band = find_band_t0(series_from_raw(_load_raw(_resolve_trades_path(mint, [pilot_trades, mcband_extra, scale_trades]))))
        band = find_band_t0(series)
        if band:
            t0, mc, px, _ = band
            # deep if only found after deep file
            method = "pump_trade_mc_band"
            if dprev and dprev.get("ok") and dprev.get("found_band") and not cache_band:
                method = "pump_trade_mc_band_deep"
            elif path and "deep" in str(path):
                method = "pump_trade_mc_band_deep"
            r.update(
                {
                    "reconstructable": 1,
                    "reconstruct_method": method,
                    "t0_ts": t0.isoformat(),
                    "mc_usd_t0": mc,
                    "price_usd_t0": px,
                    "needs_deep": 0,
                    "n_raw_final": len(raw),
                    "cache_path": str(path) if path else None,
                }
            )
        elif args.allow_expand_proxy:
            expand_t0 = _aware_dt(r.get("expand_t0_ts"))
            expand_mc = r.get("expand_mc_usd_t0")
            create_ts = _aware_dt(r.get("create_ts"))
            if (
                expand_t0
                and expand_mc is not None
                and MC_LO_USD <= float(expand_mc) <= MC_HI_USD
                and create_ts is not None
            ):
                r.update(
                    {
                        "reconstructable": 1,
                        "reconstruct_method": "expand_create_proxy",
                        "t0_ts": expand_t0.isoformat(),
                        "mc_usd_t0": float(expand_mc),
                        "price_usd_t0": float(expand_mc) / UI_SUPPLY,
                        "n_raw_final": len(raw),
                    }
                )
            else:
                r.update(
                    {
                        "reconstructable": 0,
                        "reconstruct_method": "unreconstructable",
                        "t0_ts": None,
                        "mc_usd_t0": None,
                        "n_raw_final": len(raw),
                    }
                )
        else:
            reason = "no_trades" if not raw else "never_in_band"
            r.update(
                {
                    "reconstructable": 0,
                    "reconstruct_method": reason,
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "n_raw_final": len(raw),
                }
            )

    # Features + labels
    from paper_live.pump_enrich import buy_vol_60s_from_trades, parse_pump_frontend_trades
    from paper_live.q5a_agg import aggregate_q5a_for_mint

    matrix_rows: list[dict[str, Any]] = []
    for _, sr in sample.iterrows():
        mint = str(sr["mint"])
        r = recon_by_mint[mint]
        create_ts = _aware_dt(sr.get("create_ts"))
        expand_t0 = _aware_dt(sr.get("t0_ts"))
        expand_max = float(sr["max_mc_after_t0"]) if pd.notna(sr.get("max_mc_after_t0")) else None
        raw = trades_by_mint.get(mint) or []
        series = series_from_raw(raw)

        base: dict[str, Any] = {
            "mint": mint,
            "t0_policy": T0_POLICY,
            "t0_definition": PUMP_MC_SIGHTING_DEF,
            "reconstruct_method": r.get("reconstruct_method"),
            "reconstructable": int(r.get("reconstructable") or 0),
            "hit_10x_30d_expand": r.get("hit_10x_30d_expand"),
            "expand_t0_ts": r.get("expand_t0_ts"),
            "expand_mc_usd_t0": r.get("expand_mc_usd_t0"),
            "sol_usd_source": "pump_frontend",
            "feature_overlay": "pump_trades_q5a_buy60",
            "in_pilot500": int(sr.get("in_pilot500") or 0),
            "label_source": None,
        }
        for c in Q5B_COLS:
            base[c] = sr[c] if c in sr.index else None

        if not r.get("reconstructable"):
            base.update(
                {
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "hit_10x_30d": None,
                    "fetch_ok": 0,
                    "n_trades_pre_t0": 0,
                    "capture_scoreable": False,
                }
            )
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None
            matrix_rows.append(base)
            r["hit_10x_30d"] = None
            r["capture_scoreable"] = 0
            continue

        t0 = _aware_dt(r["t0_ts"])
        mc0 = float(r["mc_usd_t0"])
        assert t0 is not None
        cap = find_t0_pump_mc_sighting(
            sighting_t0=t0,
            sighting_mc=mc0,
            create_ts=create_ts,
            complete=False,
            sol_usd=0.0,
            sol_usd_source="pump_frontend",
        )
        scoreable = is_scoreable_pump_capture(cap, allow_med=True)
        lab_info = relabel_hit_10x(
            t0=t0,
            mc0=mc0,
            series=series,
            expand_t0=expand_t0,
            expand_max_mc=expand_max,
        )
        if create_ts is not None:
            age_s = (t0 - create_ts).total_seconds()
            base["age_s"] = age_s
            base["age_min"] = age_s / 60.0

        base.update(
            {
                "t0_ts": t0.isoformat(),
                "mc_usd_t0": mc0,
                "price_usd_t0": r.get("price_usd_t0"),
                "capture_scoreable": bool(scoreable),
                "capture_quality": cap.capture_quality,
                "capture_detail": cap.detail,
                "hit_10x_30d": lab_info["hit_10x_30d"],
                "hit_200k": (
                    int(lab_info["hit_10x_30d"])
                    if lab_info.get("max_mc_after_t0_combined")
                    and lab_info["max_mc_after_t0_combined"] >= 200_000
                    else int(sr["hit_200k"])
                    if pd.notna(sr.get("hit_200k"))
                    else int(lab_info["hit_10x_30d"])
                ),
                "max_mc_after_t0_local": lab_info["max_mc_after_t0_local"],
                "max_mc_after_t0_combined": lab_info["max_mc_after_t0_combined"],
                "max_multiple_30d": lab_info["max_multiple_30d"],
                "label_used_expand_max": lab_info["label_used_expand_max"],
                "label_source": lab_info["label_source"],
                "n_trades_post_t0_30d": lab_info["n_trades_post_t0_30d"],
            }
        )
        try:
            trades = parse_pump_frontend_trades(raw, mint=mint, t0=t0, sol_usd=0.0)
            q5a = aggregate_q5a_for_mint(trades, t0) if trades else {c: None for c in Q5A_COLS}
            buy60, buy_n = buy_vol_60s_from_trades(trades, t0) if trades else (None, None)
            for c in Q5A_COLS:
                base[c] = q5a.get(c)
            base["buy_vol_usd_60s"] = buy60
            base["buy_count_60s"] = buy_n
            base["n_trades_pre_t0"] = len(trades)
            base["n_raw_trades"] = len(raw)
            base["fetch_ok"] = 1
        except Exception as e:  # noqa: BLE001
            base["fetch_ok"] = 0
            base["fetch_error"] = f"{type(e).__name__}:{e}"[:300]
            base["n_trades_pre_t0"] = 0
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None

        matrix_rows.append(base)
        r.update(
            {
                "hit_10x_30d": lab_info["hit_10x_30d"],
                "max_multiple_30d": lab_info["max_multiple_30d"],
                "label_source": lab_info["label_source"],
                "capture_scoreable": int(scoreable),
                "n_trades_pre_t0": base.get("n_trades_pre_t0"),
                "dt_vs_expand_h": ((t0 - expand_t0).total_seconds() / 3600.0 if expand_t0 else None),
            }
        )

    recon_df = pd.DataFrame(list(recon_by_mint.values()))
    mat = pd.DataFrame(matrix_rows)
    for c in FEATURE_SETS["+q5b"]:
        if c not in mat.columns:
            mat[c] = np.nan

    usable = mat[
        (mat["reconstructable"] == 1)
        & (mat["capture_scoreable"] == True)  # noqa: E712
        & (mat["fetch_ok"] == 1)
        & (mat["hit_10x_30d"].notna())
    ].copy()

    n_recon = int((recon_df["reconstructable"] == 1).sum())
    n_exact = int(
        recon_df["reconstruct_method"].isin(["pump_trade_mc_band", "pump_trade_mc_band_deep"]).sum()
    )
    label_rate = float(usable["hit_10x_30d"].mean()) if len(usable) else None
    empty_pre = int((usable["n_trades_pre_t0"].fillna(0) <= 0).sum()) if len(usable) else 0

    out_usable_df = usable[["mint", "t0_ts", "mc_usd_t0", "hit_10x_30d", "reconstruct_method"]].copy()
    out_usable_df.to_csv(out_usable, index=False)
    mat.to_csv(out_matrix, index=False)
    recon_df.to_csv(out_t0, index=False)

    meta = {
        "kind": "pump_mcband_scale_build",
        "generated_at": _utcnow(),
        "t0_policy": T0_POLICY,
        "t0_definition": PUMP_MC_SIGHTING_DEF,
        "t0_recipe": {
            "implied_mc": "priceUsd * 1e9",
            "band": [MC_LO_USD, MC_HI_USD],
            "t0": "first chronological Pump trade with MC in band",
            "proxies": {"deep_fetch": True, "expand_create_proxy": bool(args.allow_expand_proxy)},
            "non_reconstructable": "never_in_band or no_trades after deep fetch",
        },
        "label_recipe": {
            "hit": "max_mc_after_t0 >= 10 * mc_t0 within 30d",
            "local_trades": "implied MC from Pump trades (t0, t0+30d]",
            "expand_max": (
                "labels_dune_expand_v2.max_mc_after_t0 when expand_t0>=new_t0 "
                f"or |Δ|<= {EXPAND_T0_SLACK}"
            ),
            "dune_api": 0,
        },
        "sample": sample_meta,
        "n_sample": int(len(sample)),
        "n_reconstructable": n_recon,
        "n_reconstructable_trade_band": n_exact,
        "n_unreconstructable": int((recon_df["reconstructable"] == 0).sum()),
        "reconstruct_method_counts": recon_df["reconstruct_method"].value_counts().to_dict(),
        "n_matrix_rows": int(len(mat)),
        "n_usable_wf": int(len(usable)),
        "label_rate_usable": label_rate,
        "n_empty_pre_t0_usable": empty_pre,
        "frac_empty_pre_t0_usable": float(empty_pre / len(usable)) if len(usable) else None,
        "fetch": fetch_stats,
        "deep_fetch": deep_stats,
        "paths": {
            "matrix": str(out_matrix),
            "sample_universe": str(out_sample_universe),
            "sample_usable": str(out_usable),
            "t0_recon": str(out_t0),
            "trades_reused": [str(pilot_trades), str(mcband_extra)],
            "trades_new": str(scale_trades),
            "trades_deep": str(scale_deep),
        },
        "dune_api_calls": 0,
        "lite": False,
        "usd_scale": False,
        "allow_expand_proxy": bool(args.allow_expand_proxy),
        "workstream_a_note": (
            "feature diag: scale-n alone will NOT fix live score mass — "
            "mcband overfits few positives with outlier geometry "
            "(unique_sellers_total POS med~400 vs live~18; net_sol_curve POS≪0 vs live~17)"
        ),
    }
    _save_json(out_meta, meta)
    print(json.dumps(meta, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
