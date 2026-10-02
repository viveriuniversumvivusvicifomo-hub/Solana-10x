"""Ablation + threshold analysis for expand-v2 walk-forward (hit_200k proxy).

Reuses fold logic from walk_forward_expand_v2.py:
  expanding time-quantile folds, max(train.t0) < min(test.t0).

Runs hist_gb OOS for:
  A) full 18-col feature set
  B) buy_vol_usd_60s only; buy_vol_usd_60s + buy_vol_usd_5m
  C) full WITHOUT buy_vol_usd_60s / buy_vol_usd_5m
  D) engineered ≤T0 features (from existing cols only)
  E) buy_vol baseline + derived; full + derived; derived without raw buy_vol

Anti-lookahead: features ≤T0 only; labels never in X; t0 monotonic QA.
Label caveat: hit_200k proxy, NOT full hit_10x_30d.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    average_precision_score,
    precision_recall_curve,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline

# Reuse fold / load / metrics helpers from the existing WF script
import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
from walk_forward_expand_v2 import (  # type: ignore
    FEATURES_PATH,
    LABEL_COL,
    LABELS_PATH,
    N_FOLDS,
    ID_COLS,
    LEAK_COL_RE,
    assert_no_leak_columns,
    load_joined,
    make_expanding_folds,
    metrics_for_scores,
    precision_at_k,
    recall_at_k,
    select_feature_columns,
)

ROOT = Path(__file__).resolve().parents[2]
REPORT_JSON = ROOT / "data/samples/wf_ablation_v2_report.json"
REPORT_MD = ROOT / "data/samples/wf_ablation_v2_report.md"
PREDS_PATH = ROOT / "data/samples/wf_ablation_v2_oos_predictions.csv"

# Percentile bands for paper-trading threshold analysis (top fractions)
TOP_FRACS = (0.001, 0.005, 0.01, 0.02, 0.05, 0.10)
# Absolute top-K for estimated hits
TOP_KS = (25, 50, 100, 200, 500)

BUY_VOL_COLS = ("buy_vol_usd_60s", "buy_vol_usd_5m")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_hist_gb() -> Pipeline:
    return Pipeline(
        [
            ("imputer", SimpleImputer(strategy="median")),
            (
                "clf",
                HistGradientBoostingClassifier(
                    max_depth=4,
                    learning_rate=0.08,
                    max_iter=200,
                    min_samples_leaf=40,
                    l2_regularization=0.1,
                    random_state=42,
                    class_weight="balanced",
                ),
            ),
        ]
    )


def derive_engineered(df: pd.DataFrame) -> pd.DataFrame:
    """Derive ≤T0 engineered features from existing columns only. No new pulls."""
    out = df.copy()
    eps = 1e-9

    # Volume ratios / shares (60s)
    buy60 = out["buy_vol_usd_60s"].astype(float)
    sell60 = out["sell_vol_usd_60s"].astype(float)
    out["buy_sell_vol_ratio_60s"] = buy60 / (sell60 + eps)
    out["buy_share_60s"] = buy60 / (buy60 + sell60 + eps)
    out["sell_pressure_60s"] = sell60 / (buy60 + sell60 + eps)
    out["log1p_buy_vol_60s"] = np.log1p(buy60.clip(lower=0))
    out["log1p_sell_vol_60s"] = np.log1p(sell60.clip(lower=0))
    out["net_buy_vol_60s"] = buy60 - sell60
    out["log1p_net_buy_vol_60s"] = np.sign(out["net_buy_vol_60s"]) * np.log1p(
        np.abs(out["net_buy_vol_60s"])
    )

    # Volume ratios / shares (5m)
    buy5m = out["buy_vol_usd_5m"].astype(float)
    sell5m = out["sell_vol_usd_5m"].astype(float)
    out["buy_sell_vol_ratio_5m"] = buy5m / (sell5m + eps)
    out["buy_share_5m"] = buy5m / (buy5m + sell5m + eps)
    out["sell_pressure_5m"] = sell5m / (buy5m + sell5m + eps)
    out["log1p_buy_vol_5m"] = np.log1p(buy5m.clip(lower=0))
    out["net_buy_vol_5m"] = buy5m - sell5m

    # Count ratios
    bc60 = out["buy_count_60s"].astype(float)
    sc60 = out["sell_count_60s"].astype(float)
    out["buy_sell_count_ratio_60s"] = bc60 / (sc60 + eps)
    out["buy_count_share_60s"] = bc60 / (bc60 + sc60 + eps)

    # Trader intensity
    trades = out["trade_count_total"].astype(float).clip(lower=0)
    ut = out["unique_traders_total"].astype(float)
    ut60 = out["unique_traders_60s"].astype(float)
    out["unique_traders_per_trade"] = ut / (trades + eps)
    out["trades_per_unique_trader"] = trades / (ut + eps)
    out["buy_vol_per_trader_60s"] = buy60 / (ut60 + eps)
    out["buy_vol_per_buy_count_60s"] = buy60 / (bc60 + eps)

    # Momentum: 60s vs 5m buy volume concentration
    out["buy_vol_60s_over_5m"] = buy60 / (buy5m + eps)
    out["buy_count_60s_over_5m"] = bc60 / (out["buy_count_5m"].astype(float) + eps)

    # Age / intensity
    age = out["time_since_first_trade_s"].astype(float).clip(lower=0)
    out["log1p_time_since_first_trade_s"] = np.log1p(age)
    out["buy_vol_per_age_60s"] = buy60 / (age + 1.0)

    # MC band interactions (still ≤T0)
    out["buy_vol_x_mc_band"] = buy60 * out["mc_band_pos"].astype(float)
    out["log_buy_vol_x_log_mc"] = out["log1p_buy_vol_60s"] * out["log1p_mc_usd_t0"].astype(
        float
    )

    return out


DERIVED_FEATURE_NAMES = [
    "buy_sell_vol_ratio_60s",
    "buy_share_60s",
    "sell_pressure_60s",
    "log1p_buy_vol_60s",
    "log1p_sell_vol_60s",
    "net_buy_vol_60s",
    "log1p_net_buy_vol_60s",
    "buy_sell_vol_ratio_5m",
    "buy_share_5m",
    "sell_pressure_5m",
    "log1p_buy_vol_5m",
    "net_buy_vol_5m",
    "buy_sell_count_ratio_60s",
    "buy_count_share_60s",
    "unique_traders_per_trade",
    "trades_per_unique_trader",
    "buy_vol_per_trader_60s",
    "buy_vol_per_buy_count_60s",
    "buy_vol_60s_over_5m",
    "buy_count_60s_over_5m",
    "log1p_time_since_first_trade_s",
    "buy_vol_per_age_60s",
    "buy_vol_x_mc_band",
    "log_buy_vol_x_log_mc",
]

# Derived features that do NOT encode raw buy_vol magnitude directly
# (used for "derived without raw buy_vol" residual test — still may correlate)
DERIVED_NO_RAW_BUY_VOL = [
    "buy_sell_vol_ratio_60s",
    "buy_share_60s",
    "sell_pressure_60s",
    "buy_sell_vol_ratio_5m",
    "buy_share_5m",
    "sell_pressure_5m",
    "buy_sell_count_ratio_60s",
    "buy_count_share_60s",
    "unique_traders_per_trade",
    "trades_per_unique_trader",
    "buy_vol_60s_over_5m",
    "buy_count_60s_over_5m",
    "log1p_time_since_first_trade_s",
]


def threshold_metrics(y_true: np.ndarray, scores: np.ndarray) -> dict[str, Any]:
    """Precision/recall/F1/lift at score percentiles and fixed top-K."""
    base = float(np.mean(y_true))
    n = len(y_true)
    n_pos = int(y_true.sum())
    out: dict[str, Any] = {
        "n": int(n),
        "n_pos": n_pos,
        "base_rate": base,
    }
    if len(np.unique(y_true)) < 2:
        out["auc"] = None
        out["ap"] = None
        return out

    out["auc"] = float(roc_auc_score(y_true, scores))
    out["ap"] = float(average_precision_score(y_true, scores))

    # Top-fraction bands
    bands: list[dict[str, Any]] = []
    for frac in TOP_FRACS:
        k = max(1, int(round(frac * n)))
        p = precision_at_k(y_true, scores, k)
        r = recall_at_k(y_true, scores, k)
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        lift = (p / base) if base > 0 else float("nan")
        hits = int(round(p * k))  # estimated hits in top-K
        bands.append(
            {
                "band": f"top_{frac:.1%}",
                "frac": frac,
                "k": k,
                "precision": p,
                "recall": r,
                "f1": float(f1),
                "lift_vs_base": float(lift),
                "estimated_hits": hits,
            }
        )
    out["percentile_bands"] = bands

    # Absolute top-K
    topk: list[dict[str, Any]] = []
    for k in TOP_KS:
        if k > n:
            continue
        p = precision_at_k(y_true, scores, k)
        r = recall_at_k(y_true, scores, k)
        f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
        lift = (p / base) if base > 0 else float("nan")
        topk.append(
            {
                "k": k,
                "precision": p,
                "recall": r,
                "f1": float(f1),
                "lift_vs_base": float(lift),
                "estimated_hits": int(round(p * k)),
            }
        )
    out["topk"] = topk

    # Best F1 threshold (diagnostic)
    prec, rec, thr = precision_recall_curve(y_true, scores)
    f1 = np.where((prec + rec) > 0, 2 * prec * rec / (prec + rec), 0.0)
    best = int(np.argmax(f1))
    out["best_f1"] = float(f1[best])
    out["best_f1_precision"] = float(prec[best])
    out["best_f1_recall"] = float(rec[best])
    # thr has len = len(prec)-1; guard
    if best < len(thr):
        out["best_f1_threshold"] = float(thr[best])
    else:
        out["best_f1_threshold"] = None

    # Natural-rate threshold
    k_nat = max(1, int(round(base * n)))
    out["precision_at_natural_rate"] = precision_at_k(y_true, scores, k_nat)
    out["recall_at_natural_rate"] = recall_at_k(y_true, scores, k_nat)
    out["k_natural"] = k_nat

    return out


def run_wf_for_features(
    df: pd.DataFrame,
    feature_cols: list[str],
    folds: list[dict[str, Any]],
    *,
    model_label: str,
) -> dict[str, Any]:
    """Walk-forward hist_gb on a given feature set; return OOS metrics + preds."""
    assert_no_leak_columns(feature_cols)
    for lc in ("hit_200k", "max_mc_after_t0", "label_primary_hint"):
        if lc in feature_cols:
            raise AssertionError(f"label col in features: {lc}")

    X_all = df[feature_cols].to_numpy(dtype=float)
    y_all = df[LABEL_COL].to_numpy(dtype=int)
    proto = build_hist_gb()

    fold_metrics: list[dict[str, Any]] = []
    oos_scores = np.full(len(df), np.nan, dtype=float)
    oos_fold = np.full(len(df), -1, dtype=int)

    for fold in folds:
        tr, te = fold["train_idx"], fold["test_idx"]
        pipe = clone(proto)
        pipe.fit(X_all[tr], y_all[tr])
        scores = pipe.predict_proba(X_all[te])[:, 1]
        oos_scores[te] = scores
        oos_fold[te] = fold["fold"]
        m = metrics_for_scores(y_all[te], scores)
        m.update(
            {
                "fold": fold["fold"],
                "train_n": fold["train_n"],
                "test_t0_min": fold["test_t0_min"],
                "test_t0_max": fold["test_t0_max"],
                "train_pos_rate": fold["train_pos_rate"],
            }
        )
        fold_metrics.append(m)

    mask = ~np.isnan(oos_scores)
    y_oos = y_all[mask]
    s_oos = oos_scores[mask]
    overall = threshold_metrics(y_oos, s_oos)
    # Also keep mean fold AUC/AP
    aucs = [f["auc"] for f in fold_metrics if f.get("auc") is not None]
    aps = [f["ap"] for f in fold_metrics if f.get("ap") is not None]
    overall["mean_fold_auc"] = float(np.mean(aucs)) if aucs else None
    overall["mean_fold_ap"] = float(np.mean(aps)) if aps else None
    overall["n_folds"] = len(fold_metrics)

    preds = pd.DataFrame(
        {
            "mint": df.loc[mask, "mint"].to_numpy(),
            "t0_ts": df.loc[mask, "t0_ts"].to_numpy(),
            "fold": oos_fold[mask],
            "y_true": y_oos,
            "score": s_oos,
            "model": model_label,
        }
    )

    return {
        "model_label": model_label,
        "n_features": len(feature_cols),
        "feature_columns": feature_cols,
        "folds": fold_metrics,
        "overall_oos": overall,
        "preds": preds,
    }


def feature_sets(base_cols: list[str], df: pd.DataFrame) -> dict[str, list[str]]:
    """Define ablation feature sets. All must exist in df."""
    buy60 = "buy_vol_usd_60s"
    buy5m = "buy_vol_usd_5m"
    no_buy = [c for c in base_cols if c not in BUY_VOL_COLS]
    derived = [c for c in DERIVED_FEATURE_NAMES if c in df.columns]
    derived_no_raw = [c for c in DERIVED_NO_RAW_BUY_VOL if c in df.columns]
    # Non-vol residual base (no buy_vol raw) + ratio-style derived
    residual_plus_ratios = list(dict.fromkeys(no_buy + derived_no_raw))
    # buy_vol only + derived that add structure without duplicating raw magnitude too hard
    buy_plus_derived = list(
        dict.fromkeys(
            [buy60]
            + [
                c
                for c in derived
                if c
                not in (
                    "log1p_buy_vol_60s",  # near-duplicate of buy60
                )
            ]
        )
    )
    full_plus_derived = list(dict.fromkeys(base_cols + derived))
    # Derived WITHOUT raw buy_vol columns (test incremental / residual)
    derived_wo_raw_buy = [
        c
        for c in derived
        if c
        not in (
            "log1p_buy_vol_60s",
            "log1p_buy_vol_5m",
            "net_buy_vol_60s",
            "net_buy_vol_5m",
            "log1p_net_buy_vol_60s",
            "buy_vol_per_trader_60s",
            "buy_vol_per_buy_count_60s",
            "buy_vol_per_age_60s",
            "buy_vol_x_mc_band",
            # keep log_buy_vol_x_log_mc out too — encodes buy vol
            "log_buy_vol_x_log_mc",
        )
    ]

    sets = {
        "A_full": list(base_cols),
        "B_buy_vol_60s_only": [buy60],
        "B_buy_vol_60s_plus_5m": [buy60, buy5m],
        "C_no_buy_vol": no_buy,
        "D_derived_only": derived,
        "D_derived_wo_raw_buy_vol": derived_wo_raw_buy,
        "E_buy60_plus_derived": buy_plus_derived,
        "E_full_plus_derived": full_plus_derived,
        "E_no_buy_plus_ratio_derived": residual_plus_ratios,
    }
    # Validate all columns present
    for name, cols in sets.items():
        missing = [c for c in cols if c not in df.columns]
        if missing:
            raise KeyError(f"{name} missing columns: {missing}")
        if not cols:
            raise ValueError(f"{name} has empty feature list")
    return sets


def recommend_threshold(overall: dict[str, Any]) -> dict[str, Any]:
    """Pick a practical paper-trading band: high precision, useful hit count."""
    bands = overall.get("percentile_bands") or []
    if not bands:
        return {"recommendation": None, "reason": "no bands"}

    # Prefer bands with precision ≥ 0.85 and at least ~20 estimated hits;
    # else fall back to best lift among bands with k≥50.
    candidates = [b for b in bands if b["precision"] >= 0.85 and b["estimated_hits"] >= 20]
    if candidates:
        # Among high-precision, prefer highest estimated hits (wider band)
        best = max(candidates, key=lambda b: (b["estimated_hits"], b["precision"]))
        reason = (
            f"precision≥0.85 with max hits among qualifying bands "
            f"(P={best['precision']:.3f}, hits≈{best['estimated_hits']}, "
            f"lift={best['lift_vs_base']:.1f}x)"
        )
        return {"recommendation": best, "reason": reason, "policy": "precision>=0.85_max_hits"}

    candidates = [b for b in bands if b["k"] >= 50]
    if not candidates:
        candidates = bands
    best = max(candidates, key=lambda b: (b["precision"], b["estimated_hits"]))
    reason = (
        f"no band met precision≥0.85 with ≥20 hits; chose best precision "
        f"among k≥50 (P={best['precision']:.3f}, lift={best['lift_vs_base']:.1f}x)"
    )
    return {"recommendation": best, "reason": reason, "policy": "fallback_best_precision_k50"}


def run() -> dict[str, Any]:
    df, base_cols = load_joined()
    # Derive engineered features (≤T0, from existing cols)
    df = derive_engineered(df)
    # Re-assert chronological order after derive
    if not df["t0"].is_monotonic_increasing:
        raise AssertionError("t0 order broken after feature engineering")

    folds = make_expanding_folds(df, N_FOLDS)
    sets = feature_sets(base_cols, df)

    results: dict[str, Any] = {}
    all_preds: list[pd.DataFrame] = []

    for name, cols in sets.items():
        print(f"Running WF: {name} ({len(cols)} features)...", flush=True)
        block = run_wf_for_features(df, cols, folds, model_label=name)
        preds = block.pop("preds")
        all_preds.append(preds)
        results[name] = block
        ov = block["overall_oos"]
        print(
            f"  OOS AUC={ov['auc']:.4f} AP={ov['ap']:.4f} "
            f"mean_fold_AUC={ov['mean_fold_auc']:.4f} mean_fold_AP={ov['mean_fold_ap']:.4f}",
            flush=True,
        )

    # Concat OOS preds
    preds_df = pd.concat(all_preds, ignore_index=True)
    preds_df.to_csv(PREDS_PATH, index=False)

    # Lift deltas vs buy_vol-only baseline
    baseline_key = "B_buy_vol_60s_only"
    base_auc = results[baseline_key]["overall_oos"]["auc"]
    base_ap = results[baseline_key]["overall_oos"]["ap"]
    deltas: dict[str, Any] = {}
    for name, block in results.items():
        ov = block["overall_oos"]
        deltas[name] = {
            "delta_auc_vs_buy60": float(ov["auc"] - base_auc) if ov.get("auc") is not None else None,
            "delta_ap_vs_buy60": float(ov["ap"] - base_ap) if ov.get("ap") is not None else None,
            "auc": ov.get("auc"),
            "ap": ov.get("ap"),
        }

    # Recommendation from full model and buy_vol-only
    rec_full = recommend_threshold(results["A_full"]["overall_oos"])
    rec_buy = recommend_threshold(results["B_buy_vol_60s_only"]["overall_oos"])
    # Prefer simpler model if delta AUC < 0.005 and delta AP < 0.005
    use_simple = (
        abs(deltas["A_full"]["delta_auc_vs_buy60"]) < 0.005
        and abs(deltas["A_full"]["delta_ap_vs_buy60"]) < 0.005
    )
    practical = {
        "preferred_model": "B_buy_vol_60s_only" if use_simple else "A_full",
        "reason": (
            "full vs buy_vol-only delta AUC/AP both < 0.005 → prefer simpler buy_vol_60s_only"
            if use_simple
            else "full model adds meaningful lift over buy_vol-only"
        ),
        "threshold_buy_vol_only": rec_buy,
        "threshold_full": rec_full,
    }

    # QA block
    qa = {
        "n_rows": int(len(df)),
        "n_base_features": len(base_cols),
        "base_feature_columns": base_cols,
        "derived_feature_columns": [c for c in DERIVED_FEATURE_NAMES if c in df.columns],
        "label_col": LABEL_COL,
        "labels_in_X": False,
        "leak_cols_found": [],
        "t0_monotonic": bool(df["t0"].is_monotonic_increasing),
        "t0_min": df["t0"].min().isoformat(),
        "t0_max": df["t0"].max().isoformat(),
        "overall_base_rate": float(df[LABEL_COL].mean()),
        "oos_base_rate": float(results["A_full"]["overall_oos"]["base_rate"]),
        "n_folds_used": len(folds),
        "fold_scheme": "expanding_time_quantile_40pct_warmup",
        "embargo": "max(train.t0) < min(test.t0); 30d label-horizon embargo not feasible (~23d span)",
        "anti_lookahead": (
            "All features are ≤T0 columns from features_dune_p0_flow_expand_v2.csv "
            "or deterministic transforms of those columns. No post-T0 fields. "
            "Labels (hit_200k, max_mc_after_t0, label_primary_hint) never enter X. "
            "LEAK_COL_RE blocks max_mc/hit_/label_/after_t0/primary_ready."
        ),
        "fold_qa": [
            {
                "fold": f["fold"],
                "train_n": f["train_n"],
                "test_n": f["test_n"],
                "train_t0_max": f["train_t0_max"],
                "test_t0_min": f["test_t0_min"],
                "train_max_lt_test_min": True,
            }
            for f in folds
        ],
    }

    # Suggested next external features if local lift small
    max_delta_ap = max(
        abs(d["delta_ap_vs_buy60"] or 0.0)
        for k, d in deltas.items()
        if k != baseline_key
    )
    local_lift_small = max_delta_ap < 0.02
    next_external = []
    if local_lift_small:
        next_external = [
            "holder_concentration / top10_pct_supply at T0 (wallet distribution)",
            "sniper / bundler flags in first 60s (same-block multi-buy patterns)",
            "dev wallet funding age + prior launch outcome rate",
            "social: twitter/telegram creation lag vs mint; follower velocity ≤T0",
            "cross-mint copycat / ticker-clone density in prior 1h",
            "liquidity migration / bonding-curve progress fraction at T0",
            "unique_buyer_quality: fraction of buyers with prior profitable exits (needs wallet hist ≤T0)",
            "label upgrade: train/eval on full hit_10x_30d once horizon embargo is feasible",
        ]

    report: dict[str, Any] = {
        "kind": "walk_forward_ablation_v2",
        "generated_at": _utcnow_iso(),
        "label_caveat": (
            "Label is hit_200k as proxy for PRIMARY / primary_ready. "
            "This is NOT full hit_10x_30d."
        ),
        "model_family": "hist_gb (same hyperparams as walk_forward_expand_v2)",
        "qa": qa,
        "ablations": {
            k: {
                "n_features": v["n_features"],
                "feature_columns": v["feature_columns"],
                "overall_oos": v["overall_oos"],
                "folds": v["folds"],
            }
            for k, v in results.items()
        },
        "lift_deltas_vs_buy_vol_60s_only": deltas,
        "local_lift_small": local_lift_small,
        "max_abs_delta_ap_vs_buy60": float(max_delta_ap),
        "practical_recommendation": practical,
        "recommended_next_external_features": next_external,
        "paths": {
            "script": "src/models/walk_forward_ablation_v2.py",
            "report_json": str(REPORT_JSON.relative_to(ROOT)),
            "report_md": str(REPORT_MD.relative_to(ROOT)),
            "oos_predictions": str(PREDS_PATH.relative_to(ROOT)),
            "features": str(FEATURES_PATH.relative_to(ROOT)),
            "labels": str(LABELS_PATH.relative_to(ROOT)),
            "baseline_wf": "src/models/walk_forward_expand_v2.py",
        },
    }
    return report


def _fmt(x: Any, nd: int = 4) -> str:
    if x is None:
        return "n/a"
    try:
        return f"{float(x):.{nd}f}"
    except (TypeError, ValueError):
        return str(x)


def write_markdown(report: dict[str, Any]) -> str:
    qa = report["qa"]
    lines: list[str] = []
    lines.append("# Walk-forward ablation v2 report")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Label: `{qa['label_col']}` — **{report['label_caveat']}**")
    lines.append(f"- Model family: `{report['model_family']}`")
    lines.append(
        f"- Rows: {qa['n_rows']:,} | base features: {qa['n_base_features']} | "
        f"derived: {len(qa['derived_feature_columns'])} | folds: {qa['n_folds_used']}"
    )
    lines.append(
        f"- Base rate (all): {qa['overall_base_rate']:.4f} | OOS base rate: {qa['oos_base_rate']:.4f}"
    )
    lines.append(f"- t0 range: {qa['t0_min']} → {qa['t0_max']}")
    lines.append(f"- Embargo: {qa['embargo']}")
    lines.append("")
    lines.append("## Anti-lookahead / QA")
    lines.append("")
    lines.append(f"- {qa['anti_lookahead']}")
    lines.append(
        f"- labels_in_X={qa['labels_in_X']}, leak_cols={qa['leak_cols_found']}, "
        f"t0_monotonic={qa['t0_monotonic']}"
    )
    lines.append("- Fold temporal QA (train_max < test_min):")
    for f in qa["fold_qa"]:
        lines.append(
            f"  - fold {f['fold']}: train_n={f['train_n']}, test_n={f['test_n']}, "
            f"train_t0_max={f['train_t0_max'][:19]} < test_t0_min={f['test_t0_min'][:19]}"
        )
    lines.append("")

    lines.append("## Ablation summary (OOS pooled)")
    lines.append("")
    lines.append(
        "| set | n_feat | mean_fold_AUC | mean_fold_AP | OOS AUC | OOS AP | "
        "ΔAUC vs buy60 | ΔAP vs buy60 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    deltas = report["lift_deltas_vs_buy_vol_60s_only"]
    for name, block in report["ablations"].items():
        ov = block["overall_oos"]
        d = deltas[name]
        lines.append(
            f"| `{name}` | {block['n_features']} | {_fmt(ov.get('mean_fold_auc'))} | "
            f"{_fmt(ov.get('mean_fold_ap'))} | {_fmt(ov.get('auc'))} | {_fmt(ov.get('ap'))} | "
            f"{_fmt(d.get('delta_auc_vs_buy60'))} | {_fmt(d.get('delta_ap_vs_buy60'))} |"
        )
    lines.append("")

    lines.append("## Threshold bands (precision / recall / lift)")
    lines.append("")
    for key in (
        "A_full",
        "B_buy_vol_60s_only",
        "B_buy_vol_60s_plus_5m",
        "C_no_buy_vol",
        "E_buy60_plus_derived",
        "E_full_plus_derived",
        "D_derived_wo_raw_buy_vol",
    ):
        if key not in report["ablations"]:
            continue
        ov = report["ablations"][key]["overall_oos"]
        lines.append(f"### `{key}` (AUC={_fmt(ov.get('auc'))}, AP={_fmt(ov.get('ap'))})")
        lines.append("")
        lines.append("| band | k | precision | recall | F1 | lift | est. hits |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for b in ov.get("percentile_bands") or []:
            lines.append(
                f"| {b['band']} | {b['k']} | {_fmt(b['precision'])} | {_fmt(b['recall'])} | "
                f"{_fmt(b['f1'])} | {_fmt(b['lift_vs_base'], 2)}x | {b['estimated_hits']} |"
            )
        lines.append("")
        lines.append("| top-K | precision | recall | F1 | lift | est. hits |")
        lines.append("|---:|---:|---:|---:|---:|---:|")
        for b in ov.get("topk") or []:
            lines.append(
                f"| {b['k']} | {_fmt(b['precision'])} | {_fmt(b['recall'])} | "
                f"{_fmt(b['f1'])} | {_fmt(b['lift_vs_base'], 2)}x | {b['estimated_hits']} |"
            )
        lines.append("")

    prac = report["practical_recommendation"]
    lines.append("## Practical recommendation (paper trading)")
    lines.append("")
    lines.append(f"- **Preferred model:** `{prac['preferred_model']}`")
    lines.append(f"- Reason: {prac['reason']}")
    for label, rec in (
        ("buy_vol_60s_only", prac["threshold_buy_vol_only"]),
        ("full", prac["threshold_full"]),
    ):
        r = rec.get("recommendation") or {}
        lines.append(
            f"- Threshold ({label}): band=`{r.get('band')}`, k={r.get('k')}, "
            f"P={_fmt(r.get('precision'))}, R={_fmt(r.get('recall'))}, "
            f"lift={_fmt(r.get('lift_vs_base'), 2)}x, hits≈{r.get('estimated_hits')} "
            f"— {rec.get('reason')}"
        )
    lines.append("")

    lines.append("## Local lift assessment")
    lines.append("")
    lines.append(
        f"- max |ΔAP| vs buy_vol_60s_only: {_fmt(report['max_abs_delta_ap_vs_buy60'])}"
    )
    lines.append(f"- local_lift_small: **{report['local_lift_small']}**")
    if report["recommended_next_external_features"]:
        lines.append("- Recommended next **external** features (local engineering lift small):")
        for item in report["recommended_next_external_features"]:
            lines.append(f"  - {item}")
    else:
        lines.append("- Local engineered / multi-feature sets add meaningful lift; prioritize those.")
    lines.append("")

    lines.append("## Feature columns")
    lines.append("")
    lines.append("### Base (18)")
    lines.append(", ".join(f"`{c}`" for c in qa["base_feature_columns"]))
    lines.append("")
    lines.append("### Derived")
    lines.append(", ".join(f"`{c}`" for c in qa["derived_feature_columns"]))
    lines.append("")

    lines.append("## Paths")
    lines.append("")
    for k, v in report["paths"].items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    report = run()
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    md = write_markdown(report)
    REPORT_MD.write_text(md, encoding="utf-8")
    print(md)
    print(f"\nWrote {REPORT_JSON}")
    print(f"Wrote {REPORT_MD}")
    print(f"Wrote {PREDS_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
