#!/usr/bin/env python3
"""Build Pump-true Path A matrix with LIVE-LIKE positive/neg geometry.

Why prior pilots failed (encoded):
  mcband n=467/34pos: train POS had outlier geometry (unique_sellers_total med~400,
  net_sol_curve≪0, huge sell vols) vs live (sellers~18–21, net_sol~14–17).
  Scale-n alone does NOT help — must filter POS to live-like bands.

Recipe (frozen):
  T0 = first Pump trade MC∈[8k,20k]; label 10× from that T0; features ≤T0;
  expand_create_proxy OFF; 0 Dune; Lite OFF; USD scale OFF.

Live target: Path A journal scoreable with q5a_curve_age_source=q5a_trades
(post curve/age restart) — fallback all Path A scoreable if n_q5a_trades < 30.

Hard constraints:
  - Never touch paper_live PID
  - Never overwrite q5b_last / q5b_calibration / prior pump joblibs
  - Reuse pump_pilot500 / mcband / scale trade caches
  - Cap HTTP; prefer ≥400 usable (target ≥800) over chasing 82k
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime
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
from build_pump_mcband_pilot import (  # noqa: E402
    EXPAND_T0_SLACK,
    HIT_MULTIPLE,
    LABEL_HORIZON,
    T0_POLICY,
    UI_SUPPLY,
    _aware_dt,
    _load_json,
    _save_json,
    _utcnow,
    deep_fetch_trades,
    find_band_t0,
    relabel_hit_10x,
    series_from_raw,
)
from pump_path_a_common import (  # noqa: E402
    _load_raw,
    _resolve_trades_path,
    fetch_missing_band_aware,
    ordered_cache_dirs,
    resolve_scale_sample_csv,
)

STAMP_DEFAULT = datetime.now().strftime("%Y%m%d")
MIN_INTERVAL_S = 1.0
MAX_HTTP_BUDGET = 4500
MAX_FETCH_PAGES = 10
MAX_429_RETRIES_TOTAL = 60

# Killer-outlier hard reject (from path-a-mcband-feat-diag-20261002.md)
HARD_REJECT = {
    "unique_sellers_total": (None, 100.0),  # live p95~65; mcband POS med~400
    "net_sol_curve": (-20.0, None),  # live p05~-1.6; mcband POS med~-108
    "sell_vol_usd_30s": (None, 15000.0),  # live p95~6k; mcband POS~12k+
    "sell_vol_usd_total": (None, 25000.0),  # live p95~6k; mcband POS~22k
    "n_trades_pre_t0": (5.0, 450.0),  # live med~118; reject mega-pre / empty
    "age_proxy_s": (None, 3600.0),  # early curve
}

# Soft live bands (approx live p05..p95 widened) — documented in note
SOFT_BANDS = {
    "unique_sellers_total": (1.0, 90.0),
    "net_sol_curve": (-5.0, 45.0),
    "sell_vol_usd_30s": (0.0, 12000.0),
    "sell_vol_usd_total": (0.0, 15000.0),
    "buy_vol_usd_60s": (20.0, 20000.0),
    "age_proxy_s": (0.0, 2000.0),
    "progress_curve_proxy": (0.0, 0.60),
    "n_trades_pre_t0": (10.0, 350.0),
    "unique_buyers_total": (2.0, 180.0),
}

LIVE_SOFT_KEYS = [
    "unique_sellers_total",
    "net_sol_curve",
    "sell_vol_usd_30s",
    "sell_vol_usd_total",
    "buy_vol_usd_60s",
    "n_trades_pre_t0",
]


def compute_live_target(journal: Path) -> dict[str, Any]:
    """Path A scoreable distributions — prefer q5a_trades post curve/age restart."""
    keys = list(SOFT_BANDS.keys()) + ["age_s", "buy_vol_usd_30s"]
    con = sqlite3.connect(str(journal))
    rows = list(
        con.execute(
            "SELECT mint, score, features_json, created_at FROM sightings "
            "WHERE features_json IS NOT NULL"
        )
    )
    con.close()
    vecs: list[dict[str, Any]] = []
    for mint, score, fj, created_at in rows:
        try:
            feats = json.loads(fj)
        except json.JSONDecodeError:
            continue
        if feats.get("t0_definition") != "pump_mc_band_sighting_v1":
            continue
        if not feats.get("capture_scoreable"):
            continue
        row = {k: feats.get(k) for k in keys}
        row["mint"] = mint
        row["score"] = score
        row["created_at"] = created_at
        row["q5a_curve_age_source"] = feats.get("q5a_curve_age_source")
        vecs.append(row)
    df = pd.DataFrame(vecs)
    n_all = len(df)
    pref = df[df["q5a_curve_age_source"] == "q5a_trades"] if n_all else df
    use = pref if len(pref) >= 30 else df
    source = "q5a_trades" if len(pref) >= 30 else "all_path_a_scoreable"

    def _q(s: pd.Series) -> dict[str, float]:
        s = pd.to_numeric(s, errors="coerce")
        return {
            "n": int(s.notna().sum()),
            "p05": float(s.quantile(0.05)),
            "p10": float(s.quantile(0.10)),
            "p25": float(s.quantile(0.25)),
            "p50": float(s.quantile(0.50)),
            "p75": float(s.quantile(0.75)),
            "p90": float(s.quantile(0.90)),
            "p95": float(s.quantile(0.95)),
            "mean": float(s.mean()) if s.notna().any() else float("nan"),
        }

    stats = {k: _q(use[k]) for k in keys if k in use.columns}
    med = {k: stats[k]["p50"] for k in LIVE_SOFT_KEYS if k in stats}
    scale = {}
    for k in LIVE_SOFT_KEYS:
        if k not in stats:
            continue
        iqr = max(1e-6, stats[k]["p75"] - stats[k]["p25"])
        scale[k] = float(iqr / 1.35)  # ~robust sigma
    return {
        "source": source,
        "n_all_path_a_scoreable": n_all,
        "n_q5a_trades": int(len(pref)) if n_all else 0,
        "n_used": int(len(use)),
        "stats": stats,
        "live_medians": med,
        "live_scales": scale,
        "hard_reject": {k: list(v) for k, v in HARD_REJECT.items()},
        "soft_bands": {k: list(v) for k, v in SOFT_BANDS.items()},
        "why_prior_failed": (
            "mcband POS unique_sellers_total med~400 / net_sol_curve≪0 / huge sell vols "
            "vs live sellers~18–21 / net_sol~14–17; scale-n alone NO"
        ),
    }


def _in_range(v: Any, lo: float | None, hi: float | None) -> bool:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return False
    fv = float(v)
    if lo is not None and fv < lo:
        return False
    if hi is not None and fv > hi:
        return False
    return True


def passes_hard(feats: dict[str, Any]) -> bool:
    for k, (lo, hi) in HARD_REJECT.items():
        v = feats.get(k)
        if k == "n_trades_pre_t0":
            if not _in_range(v, lo, hi):
                return False
            continue
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue  # allow null on optional killers
        if lo is not None and float(v) < lo:
            return False
        if hi is not None and float(v) > hi:
            return False
    return True


def passes_soft(feats: dict[str, Any]) -> bool:
    for k, (lo, hi) in SOFT_BANDS.items():
        v = feats.get(k)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            # progress / age optional-ish; require core activity keys
            if k in (
                "unique_sellers_total",
                "net_sol_curve",
                "buy_vol_usd_60s",
                "n_trades_pre_t0",
            ):
                return False
            continue
        if not _in_range(v, lo, hi):
            return False
    return True


def soft_dist(feats: dict[str, Any], live_med: dict[str, float], live_scale: dict[str, float]) -> float:
    zs = []
    for k in LIVE_SOFT_KEYS:
        v = feats.get(k)
        med = live_med.get(k)
        sc = live_scale.get(k) or 1.0
        if med is None:
            continue
        if v is None or (isinstance(v, float) and np.isnan(v)):
            zs.append(3.0)
            continue
        zs.append(abs(float(v) - float(med)) / max(sc, 1e-6))
    return float(np.mean(zs)) if zs else 99.0


def build_candidate_universe(
    feat_path: Path,
    lab_path: Path,
    scale_sample_path: Path,
    *,
    n_extra_pos: int = 2500,
    n_extra_neg: int = 800,
    seed: int = 42,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """scale sample ∪ extra expand positives (create_ts) ∪ stratified negs."""
    scale = pd.read_csv(scale_sample_path)
    if "hit_10x_30d_expand" not in scale.columns and "hit_10x_30d" in scale.columns:
        scale = scale.rename(columns={"hit_10x_30d": "hit_10x_30d_expand"})
    scale["in_scale_sample"] = 1
    scale_mints = set(scale["mint"].astype(str))

    header = pd.read_csv(feat_path, nrows=0).columns.tolist()
    usecols = ["mint", "t0_ts", "mc_usd_t0", "create_ts", "creator_pubkey"] + [
        c for c in FEATURE_SETS["+q5b"] if c in header
    ]
    cols = [c for c in usecols if c in header]
    feat = pd.read_csv(feat_path, usecols=cols)
    lab = pd.read_csv(lab_path)
    lab_cols = [
        c
        for c in [
            "mint",
            "hit_10x_30d",
            "hit_200k",
            "max_mc_after_t0",
            "max_multiple_30d",
            "followup_days_available",
        ]
        if c in lab.columns
    ]
    df = feat.merge(lab[lab_cols], on="mint", how="inner")
    df["hit_10x_30d_expand"] = df["hit_10x_30d"].astype(int)
    df = df[~df["mint"].astype(str).isin(scale_mints)].copy()
    df = df[df["create_ts"].notna()].copy()
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["t0"]).copy()
    df["in_scale_sample"] = 0
    df["in_pilot500"] = 0

    rng = np.random.default_rng(seed)
    pos = df[df["hit_10x_30d_expand"] == 1].sort_values("t0", ascending=False)
    neg = df[df["hit_10x_30d_expand"] == 0].sort_values("t0", ascending=False)

    def _pick(sub: pd.DataFrame, k: int) -> pd.DataFrame:
        if k <= 0 or len(sub) == 0:
            return sub.iloc[0:0].copy()
        if k >= len(sub):
            return sub.copy()
        mid = max(1, len(sub) // 2)
        recent, older = sub.iloc[:mid], sub.iloc[mid:]
        k_r = min(int(round(k * 0.75)), len(recent))
        k_o = min(k - k_r, len(older))
        k_r = min(k - k_o, len(recent))
        parts = [recent.iloc[rng.choice(len(recent), size=k_r, replace=False)]]
        if k_o > 0:
            parts.append(older.iloc[rng.choice(len(older), size=k_o, replace=False)])
        return pd.concat(parts, ignore_index=True)

    extra_pos = _pick(pos, n_extra_pos)
    extra_neg = _pick(neg, n_extra_neg)

    # Align scale columns
    keep_cols = [
        c
        for c in [
            "mint",
            "t0_ts",
            "mc_usd_t0",
            "create_ts",
            "creator_pubkey",
            "hit_10x_30d_expand",
            "hit_200k",
            "max_mc_after_t0",
            "max_multiple_30d",
            "followup_days_available",
            "in_pilot500",
            "in_scale_sample",
        ]
        + list(Q5B_COLS)
        if c in scale.columns or c in extra_pos.columns or c in ["in_scale_sample"]
    ]
    # Ensure Q5b on scale from feat if missing
    for c in Q5B_COLS:
        if c not in scale.columns and c in feat.columns:
            # merge once
            pass
    if any(c not in scale.columns for c in Q5B_COLS if c in feat.columns):
        need = ["mint"] + [c for c in Q5B_COLS if c in feat.columns and c not in scale.columns]
        scale = scale.drop(columns=[c for c in need if c != "mint" and c in scale.columns], errors="ignore")
        scale = scale.merge(feat[need], on="mint", how="left")

    frames = [scale]
    if len(extra_pos):
        frames.append(extra_pos)
    if len(extra_neg):
        frames.append(extra_neg)
    # union columns
    all_cols = sorted(set().union(*[set(f.columns) for f in frames]))
    aligned = []
    for f in frames:
        for c in all_cols:
            if c not in f.columns:
                f[c] = np.nan
        aligned.append(f[all_cols])
    out = pd.concat(aligned, ignore_index=True).drop_duplicates("mint").reset_index(drop=True)
    meta = {
        "n_scale": int(len(scale)),
        "n_extra_pos": int(len(extra_pos)),
        "n_extra_neg": int(len(extra_neg)),
        "n_universe": int(len(out)),
        "n_pos_expand": int((out["hit_10x_30d_expand"] == 1).sum()),
        "n_neg_expand": int((out["hit_10x_30d_expand"] == 0).sum()),
        "seed": seed,
        "n_extra_pos_requested": n_extra_pos,
        "n_extra_neg_requested": n_extra_neg,
    }
    return out, meta


def reconstruct_row(
    *,
    mint: str,
    sr: pd.Series,
    raw: list[dict[str, Any]],
    live_med: dict[str, float],
    live_scale: dict[str, float],
) -> dict[str, Any] | None:
    from paper_live.pump_enrich import buy_vol_60s_from_trades, parse_pump_frontend_trades
    from paper_live.q5a_agg import aggregate_q5a_for_mint

    series = series_from_raw(raw)
    band = find_band_t0(series) if series else None
    create_ts = _aware_dt(sr.get("create_ts"))
    expand_t0 = _aware_dt(sr.get("t0_ts"))
    expand_mc = float(sr["mc_usd_t0"]) if pd.notna(sr.get("mc_usd_t0")) else None
    expand_max = float(sr["max_mc_after_t0"]) if pd.notna(sr.get("max_mc_after_t0")) else None

    base: dict[str, Any] = {
        "mint": mint,
        "t0_policy": T0_POLICY,
        "t0_definition": PUMP_MC_SIGHTING_DEF,
        "sol_usd_source": "pump_frontend",
        "feature_overlay": "pump_trades_q5a_buy60",
        "expand_create_proxy": 0,
        "hit_10x_30d_expand": int(sr["hit_10x_30d_expand"])
        if pd.notna(sr.get("hit_10x_30d_expand"))
        else None,
        "expand_t0_ts": expand_t0.isoformat() if expand_t0 else None,
        "expand_mc_usd_t0": expand_mc,
        "create_ts": create_ts.isoformat() if create_ts else None,
        "in_scale_sample": int(sr.get("in_scale_sample") or 0),
        "in_pilot500": int(sr.get("in_pilot500") or 0),
        "n_raw_trades": len(raw),
    }
    for c in Q5B_COLS:
        base[c] = sr[c] if c in sr.index else None

    if not band:
        base.update(
            {
                "reconstructable": 0,
                "reconstruct_method": "no_trades" if not raw else "never_in_band",
                "capture_scoreable": False,
                "fetch_ok": 0,
                "hit_10x_30d": None,
            }
        )
        return base

    t0, mc0, px, method = band
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
        t0=t0, mc0=mc0, series=series, expand_t0=expand_t0, expand_max_mc=expand_max
    )
    base.update(
        {
            "reconstructable": 1,
            "reconstruct_method": method,
            "t0_ts": t0.isoformat(),
            "mc_usd_t0": mc0,
            "price_usd_t0": px,
            "capture_scoreable": bool(scoreable),
            "capture_quality": cap.capture_quality,
            "capture_detail": cap.detail,
            "hit_10x_30d": lab_info["hit_10x_30d"],
            "max_mc_after_t0_local": lab_info["max_mc_after_t0_local"],
            "max_mc_after_t0_combined": lab_info["max_mc_after_t0_combined"],
            "max_multiple_30d": lab_info["max_multiple_30d"],
            "label_used_expand_max": lab_info["label_used_expand_max"],
            "label_source": lab_info["label_source"],
            "n_trades_post_t0_30d": lab_info["n_trades_post_t0_30d"],
        }
    )
    if create_ts is not None:
        age_s = (t0 - create_ts).total_seconds()
        base["age_s"] = age_s
        base["age_min"] = age_s / 60.0

    try:
        trades = parse_pump_frontend_trades(raw, mint=mint, t0=t0, sol_usd=0.0)
        q5a = aggregate_q5a_for_mint(trades, t0) if trades else {c: None for c in Q5A_COLS}
        buy60, buy_n = buy_vol_60s_from_trades(trades, t0) if trades else (None, None)
        for c in Q5A_COLS:
            base[c] = q5a.get(c)
        base["buy_vol_usd_60s"] = buy60
        base["buy_count_60s"] = buy_n
        base["n_trades_pre_t0"] = len(trades)
        base["fetch_ok"] = 1
        # age_proxy from q5a (t0−first_trade); do NOT overwrite with age_s
        if base.get("age_proxy_s") is None and trades:
            # aggregate should set it; leave null if not
            pass
    except Exception as e:  # noqa: BLE001
        base["fetch_ok"] = 0
        base["fetch_error"] = f"{type(e).__name__}:{e}"[:300]
        base["n_trades_pre_t0"] = 0
        for c in Q5A_COLS:
            base[c] = None
        base["buy_vol_usd_60s"] = None

    # livelike flags
    feats_for_filter = {k: base.get(k) for k in list(HARD_REJECT) + list(SOFT_BANDS)}
    base["livelike_hard_ok"] = int(passes_hard(feats_for_filter))
    base["livelike_soft_ok"] = int(passes_soft(feats_for_filter))
    base["livelike_ok"] = int(base["livelike_hard_ok"] and base["livelike_soft_ok"])
    base["livelike_soft_dist"] = soft_dist(feats_for_filter, live_med, live_scale)
    return base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--pilot-stamp", default="20261002")
    ap.add_argument("--build-only", action="store_true", help="Skip HTTP; caches only")
    ap.add_argument("--max-http", type=int, default=MAX_HTTP_BUDGET)
    ap.add_argument("--n-extra-pos", type=int, default=2500)
    ap.add_argument("--n-extra-neg", type=int, default=800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-usable", type=int, default=400)
    ap.add_argument("--target-usable", type=int, default=800)
    ap.add_argument("--soft-dist-max", type=float, default=2.5,
                    help="Additional soft_dist cap within livelike_ok (None=disable via <0)")
    ap.add_argument("--min-interval-s", type=float, default=MIN_INTERVAL_S)
    ap.add_argument(
        "--reuse-orphan-scale",
        action="store_true",
        help="Include quarantined mcband_scale trade caches in lookup (D-07 opt-in)",
    )
    args = ap.parse_args()

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    scale_sample = resolve_scale_sample_csv(args.pilot_stamp) or (
        ROOT / f"data/samples/pump_mcband_scale_sample_{args.pilot_stamp}.csv"
    )
    journal = ROOT / "data/paper_live/paper_journal.sqlite"

    # Trade caches: default excludes D-07 quarantine; --reuse-orphan-scale to include
    livelike_trades = ROOT / f"data/samples/pump_livelike_trades_{args.stamp}"

    out_universe = ROOT / f"data/samples/pump_livelike_universe_{args.stamp}.csv"
    out_matrix = ROOT / f"data/samples/features_pump_path_a_livelike_{args.stamp}.csv"
    out_usable = ROOT / f"data/samples/pump_livelike_usable_{args.stamp}.csv"
    out_meta = ROOT / f"cycle0/npz/pump_livelike_build_meta_{args.stamp}.json"
    out_live = ROOT / f"cycle0/npz/pump_livelike_live_target_{args.stamp}.json"
    fetch_ck = ROOT / f"cycle0/checkpoints/pump_livelike_fetch_{args.stamp}.json"

    live_target = compute_live_target(journal)
    _save_json(out_live, live_target)
    live_med = live_target["live_medians"]
    live_scale = live_target["live_scales"]
    print(json.dumps({"live_target": {
        "source": live_target["source"],
        "n_used": live_target["n_used"],
        "medians": live_med,
    }}, indent=2))

    if not scale_sample.is_file():
        print(json.dumps({"status": "missing_scale_sample", "path": str(scale_sample)}))
        return 1

    universe, uni_meta = build_candidate_universe(
        feat_path,
        lab_path,
        scale_sample,
        n_extra_pos=args.n_extra_pos,
        n_extra_neg=args.n_extra_neg,
        seed=args.seed,
    )
    universe.to_csv(out_universe, index=False)
    print(json.dumps({"universe": uni_meta}, indent=2))

    # Unified cache priority (default: livelike → mcband_extra → pilot500; scale opt-in)
    # stamp for reuse layers = pilot_stamp; livelike write dir uses args.stamp
    cache_dirs = ordered_cache_dirs(
        args.pilot_stamp, reuse_orphan_scale=bool(args.reuse_orphan_scale)
    )
    if args.stamp != args.pilot_stamp:
        # ensure current stamp livelike dir is first when stamps differ
        livelike_trades_stamp = ROOT / f"data/samples/pump_livelike_trades_{args.stamp}"
        cache_dirs = [livelike_trades_stamp] + [d for d in cache_dirs if d.resolve() != livelike_trades_stamp.resolve()]


    fetch_stats: dict[str, Any] = {"skipped": True}
    if not args.build_only:
        livelike_trades.mkdir(parents=True, exist_ok=True)
        t0_expand = {str(sr["mint"]): _aware_dt(sr.get("t0_ts")) for _, sr in universe.iterrows()}
        mints = [str(m) for m in universe["mint"].tolist()]

        def _priority(m: str) -> tuple[int, int, int]:
            has = 0 if _resolve_trades_path(m, cache_dirs) else 1
            row = universe[universe["mint"] == m].iloc[0]
            pos = 0 if int(row.get("hit_10x_30d_expand") or 0) == 1 else 1
            # prefer recent (already sorted in universe extras); scale first via has
            return (has, pos, 0)

        mints_sorted = sorted(mints, key=_priority)
        ck = fetch_missing_band_aware(
            mints_sorted,
            t0_expand_by_mint=t0_expand,
            trades_dir=livelike_trades,
            checkpoint=fetch_ck,
            cache_dirs=cache_dirs,
            max_pages=MAX_FETCH_PAGES,
            max_http=args.max_http,
            min_interval_s=args.min_interval_s,
        )
        fetch_stats = ck.get("stats") or {}
        fetch_stats["stopped"] = ck.get("stopped")
        fetch_stats["stop_reason"] = ck.get("stop_reason")
        print(json.dumps({"fetch_done": fetch_stats}, indent=2))
        if ck.get("stopped") and "429" in str(ck.get("stop_reason") or ""):
            print(json.dumps({"status": "abort_rate_limited", "reason": ck.get("stop_reason")}))

    # Reconstruct all with cache
    matrix_rows: list[dict[str, Any]] = []
    n_cache = 0
    for i, sr in universe.iterrows():
        mint = str(sr["mint"])
        path = _resolve_trades_path(mint, cache_dirs)
        raw = _load_raw(path)
        if path is not None:
            n_cache += 1
        row = reconstruct_row(
            mint=mint, sr=sr, raw=raw, live_med=live_med, live_scale=live_scale
        )
        if row:
            matrix_rows.append(row)
        if (len(matrix_rows) % 200) == 0 and len(matrix_rows):
            print(json.dumps({"recon_progress": len(matrix_rows), "n_cache_hit": n_cache}), flush=True)

    mat = pd.DataFrame(matrix_rows)
    for c in FEATURE_SETS["+q5b"]:
        if c not in mat.columns:
            mat[c] = np.nan

    # Usable WF: reconstructable + scoreable + fetch_ok + label + livelike_ok
    usable = mat[
        (mat["reconstructable"] == 1)
        & (mat["capture_scoreable"].astype(str).str.lower().isin(["true", "1"]))
        & (mat["fetch_ok"] == 1)
        & (mat["hit_10x_30d"].notna())
        & (mat["livelike_ok"] == 1)
    ].copy()
    if args.soft_dist_max >= 0:
        usable = usable[usable["livelike_soft_dist"] <= args.soft_dist_max].copy()

    # If below min_usable, fall back to hard_ok only (documented)
    fallback = False
    if len(usable) < args.min_usable:
        hard_only = mat[
            (mat["reconstructable"] == 1)
            & (mat["capture_scoreable"].astype(str).str.lower().isin(["true", "1"]))
            & (mat["fetch_ok"] == 1)
            & (mat["hit_10x_30d"].notna())
            & (mat["livelike_hard_ok"] == 1)
        ].copy()
        if len(hard_only) >= args.min_usable or len(hard_only) > len(usable):
            usable = hard_only
            fallback = True

    # Geometry summary pos vs live
    pos = usable[usable["hit_10x_30d"] == 1]
    neg = usable[usable["hit_10x_30d"] == 0]
    geom = {}
    for k in LIVE_SOFT_KEYS + ["progress_curve_proxy", "age_proxy_s"]:
        geom[k] = {
            "live_med": live_med.get(k) or (live_target["stats"].get(k, {}) or {}).get("p50"),
            "pos_med": float(pos[k].median()) if k in pos.columns and len(pos) else None,
            "neg_med": float(neg[k].median()) if k in neg.columns and len(neg) else None,
            "pos_n": int(pos[k].notna().sum()) if k in pos.columns else 0,
        }

    mat.to_csv(out_matrix, index=False)
    usable.to_csv(out_usable, index=False)

    meta = {
        "kind": "pump_path_a_livelike_build",
        "generated_at": _utcnow(),
        "t0_policy": T0_POLICY,
        "t0_definition": PUMP_MC_SIGHTING_DEF,
        "expand_create_proxy": False,
        "dune_api_calls": 0,
        "lite": False,
        "usd_scale": False,
        "live_target_path": str(out_live),
        "live_target_source": live_target["source"],
        "live_target_n": live_target["n_used"],
        "universe": uni_meta,
        "fetch": fetch_stats,
        "n_cache_hit": n_cache,
        "n_matrix": int(len(mat)),
        "n_reconstructable": int((mat["reconstructable"] == 1).sum()) if len(mat) else 0,
        "n_livelike_hard_ok": int((mat["livelike_hard_ok"] == 1).sum()) if len(mat) else 0,
        "n_livelike_soft_ok": int((mat["livelike_soft_ok"] == 1).sum()) if len(mat) else 0,
        "n_livelike_ok": int((mat["livelike_ok"] == 1).sum()) if len(mat) else 0,
        "n_usable_wf": int(len(usable)),
        "n_pos_usable": int((usable["hit_10x_30d"] == 1).sum()) if len(usable) else 0,
        "n_neg_usable": int((usable["hit_10x_30d"] == 0).sum()) if len(usable) else 0,
        "label_rate_usable": float(usable["hit_10x_30d"].mean()) if len(usable) else None,
        "fallback_hard_only": fallback,
        "soft_dist_max": args.soft_dist_max,
        "min_usable": args.min_usable,
        "target_usable": args.target_usable,
        "geometry_pos_neg_vs_live": geom,
        "hard_reject": {k: list(v) for k, v in HARD_REJECT.items()},
        "soft_bands": {k: list(v) for k, v in SOFT_BANDS.items()},
        "paths": {
            "matrix": str(out_matrix),
            "usable": str(out_usable),
            "universe": str(out_universe),
            "live_target": str(out_live),
        },
        "coverage_note": (
            f"usable={len(usable)} (target≥{args.target_usable}, min≥{args.min_usable}); "
            "HTTP-capped; not full 82k expand"
        ),
        "abort_toward_82k": True,
    }
    _save_json(out_meta, meta)
    print(json.dumps(meta, indent=2, default=str))

    if len(usable) < args.min_usable:
        print(json.dumps({
            "status": "below_min_usable",
            "n_usable": len(usable),
            "min_usable": args.min_usable,
            "hint": "re-run without --build-only to fetch more, or lower --min-usable",
        }))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
