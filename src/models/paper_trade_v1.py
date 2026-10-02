"""Paper-trading simulation v1 on walk-forward OOS scores (PRIMARY hit_10x_30d).

Anti look-ahead:
  - Retrain HistGB per expanding fold (same recipe as walk_forward_post_q5).
  - Entry A: score >= train-score quantile (1 - top_frac); threshold from TRAIN only.
  - Entry B: take top-k absolute rows by OOS score within each test fold
    (fixed capacity; no threshold tuned on OOS labels).

Sizing: equal weight / 1R notional unit.
Exit / PnL:
  - Primary: take-profit at 10× from T0 MC if reached; else mark at observed max multiple
    (capped at 10× for this path) → R_tp10 = clip(mult,0,10) - 1 - cost_rt.
  - Secondary binary: +9R on hit_10x_30d, -1R on miss, minus cost_rt.
  - Oracle peak (diagnostic): clip(mult,0,20) - 1 - cost_rt (unrealizable max).

Usage:
  PYTHONPATH=src .venv/bin/python -m models.paper_trade_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import clone

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import (  # noqa: E402
    DROP_FROM_X,
    FEATURE_SETS,
    PRIMARY_LABEL,
    resolve_label_column,
)
from models.walk_forward_expand_v2 import make_expanding_folds  # noqa: E402
from models.walk_forward_post_q5 import build_hist_gb  # noqa: E402

FEATURES_PATH = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
LABELS_PATH = ROOT / "data/samples/labels_dune_expand_v2.csv"
OUT_JSON = ROOT / "data/samples/paper_trade_v1_report.json"
OUT_TRADES = ROOT / "data/samples/paper_trade_v1_trades.csv"
OUT_MD = ROOT / "cycle0/paper-trade-v1.md"

DEFAULT_TOP_FRACS = (0.05, 0.01)
DEFAULT_TOP_KS = (50, 100, 200, 500, 1000, 1400)
TP_MULTIPLE = 10.0
ORACLE_CAP = 20.0
BINARY_WIN_R = 9.0
BINARY_LOSS_R = -1.0
DEFAULT_COST_RT = 0.015
COST_SENSITIVITY = (0.01, 0.015, 0.02)
RANDOM_SEEDS = (0, 1, 2, 3, 4)
PRIMARY_SET = "+q5b"
BASELINE_SET = "buy60"
SETS = (PRIMARY_SET, BASELINE_SET)


def _utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm_t0(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def load_frame() -> pd.DataFrame:
    feat = pd.read_csv(FEATURES_PATH)
    lab = pd.read_csv(LABELS_PATH)
    label_col, is_primary = resolve_label_column(lab.columns)
    if not is_primary:
        raise RuntimeError(f"expected PRIMARY {PRIMARY_LABEL}, got {label_col}")
    need_lab = [
        "mint",
        label_col,
        "max_mc_after_t0",
        "max_multiple_30d",
        "followup_days_available",
        "primary_ready",
    ]
    missing = [c for c in need_lab if c not in lab.columns]
    if missing:
        raise KeyError(f"labels missing: {missing}")
    if "mc_usd_t0" not in feat.columns:
        raise KeyError("mc_usd_t0 missing from features")
    overlap = set(feat.columns) & set(lab.columns) - {"mint"}
    if overlap:
        raise AssertionError(f"feature/label overlap: {sorted(overlap)}")
    df = feat.merge(lab[need_lab], on="mint", how="inner", validate="one_to_one")
    df["t0"] = _norm_t0(df["t0_ts"])
    df = df.sort_values("t0", kind="mergesort").reset_index(drop=True)
    df[label_col] = df[label_col].astype(int)
    mc0 = df["mc_usd_t0"].astype(float)
    mx = df["max_mc_after_t0"].astype(float)
    mult = np.where(mc0 > 0, mx / mc0, np.nan)
    df["mc_multiple"] = np.where(
        df["max_multiple_30d"].notna(),
        df["max_multiple_30d"].astype(float),
        mult,
    )
    if df["t0"].isna().any():
        raise AssertionError("null t0")
    if not df["t0"].is_monotonic_increasing:
        raise AssertionError("t0 not sorted")
    df.attrs["label_col"] = label_col
    return df


def available_cols(df: pd.DataFrame, wanted: tuple[str, ...]) -> list[str]:
    cols = [c for c in wanted if c in df.columns]
    if "creator_pubkey" in cols or set(cols) & DROP_FROM_X:
        raise AssertionError("leak into X")
    return cols


def train_quantile_threshold(train_scores: np.ndarray, top_frac: float) -> float:
    if not (0.0 < top_frac < 1.0):
        raise ValueError(top_frac)
    return float(np.quantile(train_scores, 1.0 - top_frac))


def r_tp10(multiple: float, cost_rt: float) -> float:
    """Exit at 10× TP if reached; else mark at observed multiple (≤10)."""
    if multiple is None or (isinstance(multiple, float) and np.isnan(multiple)):
        return float("nan")
    m = float(np.clip(multiple, 0.0, TP_MULTIPLE))
    return (m - 1.0) - cost_rt


def r_oracle_peak(multiple: float, cost_rt: float, cap: float = ORACLE_CAP) -> float:
    if multiple is None or (isinstance(multiple, float) and np.isnan(multiple)):
        return float("nan")
    m = float(np.clip(multiple, 0.0, cap))
    return (m - 1.0) - cost_rt


def r_binary(hit: int, cost_rt: float) -> float:
    base = BINARY_WIN_R if int(hit) == 1 else BINARY_LOSS_R
    return base - cost_rt


def max_drawdown(cum: np.ndarray) -> float:
    if len(cum) == 0:
        return 0.0
    peak = np.maximum.accumulate(cum)
    return float((cum - peak).min())


def _score_rs(multiples: np.ndarray, hits: np.ndarray, cost_rt: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    r_tp = np.array([r_tp10(m, cost_rt) for m in multiples])
    r_bin = np.array([r_binary(h, cost_rt) for h in hits])
    r_or = np.array([r_oracle_peak(m, cost_rt) for m in multiples])
    return r_tp, r_bin, r_or


def summarize_trades(trades: pd.DataFrame, *, cost_rt: float, label: str) -> dict[str, Any]:
    empty = {
        "n_trades": 0,
        "hit_rate": None,
        "precision_at_selected": None,
        "n_hits": 0,
        "cum_r_tp10": 0.0,
        "cum_r_binary": 0.0,
        "cum_r_oracle20": 0.0,
        "mean_r_tp10": None,
        "mean_r_binary": None,
        "mean_r_oracle20": None,
        "max_dd_tp10": 0.0,
        "max_dd_binary": 0.0,
        "max_dd_oracle20": 0.0,
        "trades_per_fold": {},
        "trades_per_day": None,
        "cost_rt": cost_rt,
        "label": label,
    }
    if trades.empty:
        return empty
    t = trades.sort_values("t0", kind="mergesort").reset_index(drop=True)
    # Recompute R at requested cost (trades may have been stored at default)
    r_tp, r_bin, r_or = _score_rs(
        t["mc_multiple"].to_numpy(dtype=float),
        t["y"].to_numpy(dtype=int),
        cost_rt,
    )
    order = np.arange(len(t))
    cum_tp = np.nancumsum(r_tp)
    cum_bin = np.nancumsum(r_bin)
    cum_or = np.nancumsum(r_or)
    hits = t["y"].to_numpy(dtype=int)
    t0 = pd.to_datetime(t["t0"], utc=True)
    span_days = max((t0.max() - t0.min()).total_seconds() / 86400.0, 1e-9)
    per_fold = t.groupby("fold").size().astype(int).to_dict()
    mult = t["mc_multiple"].to_numpy(dtype=float)
    return {
        "n_trades": int(len(t)),
        "hit_rate": float(hits.mean()),
        "precision_at_selected": float(hits.mean()),
        "n_hits": int(hits.sum()),
        "cum_r_tp10": float(cum_tp[-1]),
        "cum_r_binary": float(cum_bin[-1]),
        "cum_r_oracle20": float(cum_or[-1]),
        "mean_r_tp10": float(np.nanmean(r_tp)),
        "mean_r_binary": float(np.nanmean(r_bin)),
        "mean_r_oracle20": float(np.nanmean(r_or)),
        "max_dd_tp10": max_drawdown(cum_tp),
        "max_dd_binary": max_drawdown(cum_bin),
        "max_dd_oracle20": max_drawdown(cum_or),
        "trades_per_fold": {str(k): int(v) for k, v in per_fold.items()},
        "trades_per_day": float(len(t) / span_days),
        "oos_span_days": float(span_days),
        "median_followup_days": float(t["followup_days_available"].median()),
        "frac_followup_ge_14d": float((t["followup_days_available"] >= 14).mean()),
        "frac_followup_ge_30d": float((t["followup_days_available"] >= 30).mean()),
        "mean_mc_multiple": float(np.nanmean(mult)),
        "median_mc_multiple": float(np.nanmedian(mult)),
        "frac_mult_ge_10": float(np.nanmean(mult >= 10.0)),
        "frac_mult_ge_20": float(np.nanmean(mult >= 20.0)),
        "cost_rt": cost_rt,
        "label": label,
        "_order_unused": int(order[-1]) if len(order) else 0,
    }


def _rows_to_trades(
    df: pd.DataFrame,
    idx: np.ndarray,
    *,
    fold: int,
    set_name: str,
    rule: str,
    rule_param: float,
    threshold: float | None,
    scores: np.ndarray,
    cost_rt: float,
) -> pd.DataFrame:
    label_col = df.attrs["label_col"]
    sub = df.loc[idx]
    y = sub[label_col].to_numpy(dtype=int)
    mult = sub["mc_multiple"].to_numpy(dtype=float)
    r_tp, r_bin, r_or = _score_rs(mult, y, cost_rt)
    return pd.DataFrame(
        {
            "mint": sub["mint"].to_numpy(),
            "t0": sub["t0"].to_numpy(),
            "t0_ts": sub["t0_ts"].to_numpy(),
            "fold": np.full(len(sub), fold, dtype=int),
            "set": set_name,
            "rule": rule,
            "rule_param": rule_param,
            "threshold_train": threshold if threshold is not None else np.nan,
            "score": np.asarray(scores, dtype=float),
            "y": y,
            "mc_usd_t0": sub["mc_usd_t0"].to_numpy(dtype=float),
            "max_mc_after_t0": sub["max_mc_after_t0"].to_numpy(dtype=float),
            "mc_multiple": mult,
            "followup_days_available": sub["followup_days_available"].to_numpy(dtype=float),
            "r_tp10": r_tp,
            "r_binary": r_bin,
            "r_oracle20": r_or,
            "cost_rt": cost_rt,
        }
    )


def random_matched(
    test_idx: np.ndarray,
    df: pd.DataFrame,
    n_trades: int,
    fold: int,
    set_name: str,
    rule: str,
    rule_param: float,
    cost_rt: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    if n_trades <= 0 or len(test_idx) == 0:
        return pd.DataFrame()
    n = min(n_trades, len(test_idx))
    chosen = rng.choice(test_idx, size=n, replace=False)
    return _rows_to_trades(
        df,
        chosen,
        fold=fold,
        set_name=f"random:{set_name}",
        rule=rule,
        rule_param=rule_param,
        threshold=None,
        scores=np.full(n, np.nan),
        cost_rt=cost_rt,
    )


def run_paper(
    df: pd.DataFrame,
    folds: list[dict[str, Any]],
    *,
    top_fracs: tuple[float, ...],
    top_ks: tuple[int, ...],
    cost_rt: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    label_col = df.attrs["label_col"]
    all_trades: list[pd.DataFrame] = []
    fold_meta: dict[str, Any] = {}

    # Cache per-set fold scores so top_frac and top_k share one train per fold
    score_cache: dict[str, dict[int, dict[str, np.ndarray]]] = {}

    for set_name in SETS:
        cols = available_cols(df, FEATURE_SETS[set_name])
        if not cols:
            raise RuntimeError(f"no cols for {set_name}")
        fold_meta[set_name] = {"n_features": len(cols), "feature_columns": cols}
        score_cache[set_name] = {}

        for f in folds:
            tr, te = f["train_idx"], f["test_idx"]
            Xtr = df.loc[tr, cols].to_numpy(dtype=float)
            Xte = df.loc[te, cols].to_numpy(dtype=float)
            ytr = df.loc[tr, label_col].to_numpy()
            model = clone(build_hist_gb())
            model.fit(Xtr, ytr)
            train_scores = model.predict_proba(Xtr)[:, 1]
            test_scores = model.predict_proba(Xte)[:, 1]
            score_cache[set_name][f["fold"]] = {
                "train_scores": train_scores,
                "test_scores": test_scores,
                "test_idx": te,
            }

        for top_frac in top_fracs:
            key = f"{set_name}|train_q_top{top_frac:.0%}"
            fold_meta[key] = {"folds": [], "rule": "train_quantile", "top_frac": top_frac}
            for f in folds:
                cached = score_cache[set_name][f["fold"]]
                thr = train_quantile_threshold(cached["train_scores"], top_frac)
                te = cached["test_idx"]
                test_scores = cached["test_scores"]
                enter_mask = test_scores >= thr
                enter_idx = te[enter_mask]
                trades = _rows_to_trades(
                    df,
                    enter_idx,
                    fold=f["fold"],
                    set_name=set_name,
                    rule="train_quantile",
                    rule_param=top_frac,
                    threshold=thr,
                    scores=test_scores[enter_mask],
                    cost_rt=cost_rt,
                )
                all_trades.append(trades)
                fold_meta[key]["folds"].append(
                    {
                        "fold": f["fold"],
                        "threshold_train": thr,
                        "n_enter": int(enter_mask.sum()),
                        "enter_frac_of_test": float(enter_mask.mean()),
                        "n_unique_train_scores": int(np.unique(np.round(cached["train_scores"], 8)).size),
                        "hit_rate_enter": (
                            float(df.loc[enter_idx, label_col].mean()) if len(enter_idx) else None
                        ),
                    }
                )

        for k in top_ks:
            key = f"{set_name}|topk_{k}"
            fold_meta[key] = {"folds": [], "rule": "topk_per_fold", "k": k}
            for f in folds:
                cached = score_cache[set_name][f["fold"]]
                te = cached["test_idx"]
                test_scores = cached["test_scores"]
                kk = min(k, len(te))
                # Stable: highest score first; ties broken by earlier t0 (already time-sorted idx)
                order = np.argsort(-test_scores, kind="mergesort")
                pick = order[:kk]
                enter_idx = te[pick]
                trades = _rows_to_trades(
                    df,
                    enter_idx,
                    fold=f["fold"],
                    set_name=set_name,
                    rule="topk_per_fold",
                    rule_param=float(k),
                    threshold=None,
                    scores=test_scores[pick],
                    cost_rt=cost_rt,
                )
                all_trades.append(trades)
                fold_meta[key]["folds"].append(
                    {
                        "fold": f["fold"],
                        "k": kk,
                        "n_enter": int(kk),
                        "score_min_selected": float(test_scores[pick].min()) if kk else None,
                        "hit_rate_enter": (
                            float(df.loc[enter_idx, label_col].mean()) if kk else None
                        ),
                    }
                )

    trades_df = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    return trades_df, fold_meta


def _strategy_key(set_name: str, rule: str, param: float) -> str:
    if rule == "train_quantile":
        return f"{set_name}_trainQ_top{param:.0%}"
    return f"{set_name}_topK_{int(param)}"


def aggregate_report(
    trades_df: pd.DataFrame,
    fold_meta: dict[str, Any],
    folds: list[dict[str, Any]],
    df: pd.DataFrame,
    *,
    top_fracs: tuple[float, ...],
    top_ks: tuple[int, ...],
    cost_rt: float,
) -> dict[str, Any]:
    label_col = df.attrs["label_col"]
    strategies: dict[str, Any] = {}
    rule_specs: list[tuple[str, str, float, str]] = []
    # (set, rule, param, fold_meta_key)
    for set_name in SETS:
        for tf in top_fracs:
            rule_specs.append(
                (set_name, "train_quantile", tf, f"{set_name}|train_q_top{tf:.0%}")
            )
        for k in top_ks:
            rule_specs.append((set_name, "topk_per_fold", float(k), f"{set_name}|topk_{k}"))

    all_test = np.concatenate([f["test_idx"] for f in folds])
    oos_base = float(df.loc[all_test, label_col].mean())

    for set_name, rule, param, meta_key in rule_specs:
        mask = (
            (trades_df["set"] == set_name)
            & (trades_df["rule"] == rule)
            & np.isclose(trades_df["rule_param"].to_numpy(dtype=float), param)
        )
        sub = trades_df.loc[mask].copy()
        name = _strategy_key(set_name, rule, param)
        summ = summarize_trades(sub, cost_rt=cost_rt, label=name)
        summ.pop("_order_unused", None)

        sens = {}
        for c in COST_SENSITIVITY:
            sc = summarize_trades(sub, cost_rt=c, label=name)
            sens[f"{c:.1%}"] = {
                "cum_r_tp10": sc["cum_r_tp10"],
                "cum_r_binary": sc["cum_r_binary"],
                "cum_r_oracle20": sc["cum_r_oracle20"],
                "mean_r_tp10": sc["mean_r_tp10"],
                "max_dd_tp10": sc["max_dd_tp10"],
            }
        summ["cost_sensitivity"] = sens

        rand_summaries = []
        for seed in RANDOM_SEEDS:
            rng = np.random.default_rng(seed)
            parts = []
            for frow in fold_meta[meta_key]["folds"]:
                fold_id = frow["fold"]
                f = next(x for x in folds if x["fold"] == fold_id)
                part = random_matched(
                    f["test_idx"],
                    df,
                    frow["n_enter"],
                    fold_id,
                    set_name,
                    rule,
                    param,
                    cost_rt,
                    rng,
                )
                if not part.empty:
                    parts.append(part)
            if parts:
                rt = pd.concat(parts, ignore_index=True)
                rs = summarize_trades(rt, cost_rt=cost_rt, label=f"random_s{seed}")
                rs.pop("_order_unused", None)
                rand_summaries.append(rs)
        if rand_summaries:
            summ["random_baseline"] = {
                "n_seeds": len(rand_summaries),
                "mean_hit_rate": float(np.mean([r["hit_rate"] for r in rand_summaries])),
                "mean_cum_r_tp10": float(np.mean([r["cum_r_tp10"] for r in rand_summaries])),
                "mean_cum_r_binary": float(np.mean([r["cum_r_binary"] for r in rand_summaries])),
                "mean_n_trades": float(np.mean([r["n_trades"] for r in rand_summaries])),
                "std_cum_r_tp10": float(np.std([r["cum_r_tp10"] for r in rand_summaries])),
            }
        else:
            summ["random_baseline"] = None

        summ["oos_base_rate"] = oos_base
        summ["lift_vs_base"] = (
            (summ["hit_rate"] / oos_base) if summ["hit_rate"] is not None and oos_base else None
        )
        summ["rule"] = rule
        summ["rule_param"] = param
        summ["set"] = set_name
        strategies[name] = summ

    comparisons: dict[str, Any] = {}
    for tf in top_fracs:
        a = strategies[_strategy_key(PRIMARY_SET, "train_quantile", tf)]
        b = strategies[_strategy_key(BASELINE_SET, "train_quantile", tf)]
        comparisons[f"trainQ_top{tf:.0%}"] = _cmp(a, b)
    for k in top_ks:
        a = strategies[_strategy_key(PRIMARY_SET, "topk_per_fold", float(k))]
        b = strategies[_strategy_key(BASELINE_SET, "topk_per_fold", float(k))]
        comparisons[f"topK_{k}"] = _cmp(a, b)

    return {
        "kind": "paper_trade_v1_report",
        "generated_at": _utcnow(),
        "label": label_col,
        "primary_set": PRIMARY_SET,
        "baseline_set": BASELINE_SET,
        "oos_base_rate": oos_base,
        "rules": {
            "entry_train_quantile": (
                "score >= quantile(train_scores, 1-top_frac); threshold from TRAIN only "
                "(note: buy60 scores pile near 1.0 → top1%≈top5% via ties)"
            ),
            "entry_topk_per_fold": (
                "within each OOS fold, take top-k by model score (fixed capacity; "
                "no label peek; ties broken by earlier t0)"
            ),
            "sizing": "equal weight / fixed 1R notional unit per trade",
            "exit_horizon": (
                "hold until hit_10x OR end of available followup (right-censored)"
            ),
            "pnl_tp10_primary": (
                f"R = clip(mc_multiple, 0, {TP_MULTIPLE}) - 1 - cost_rt  "
                "(take-profit at 10×; do not assume catching the peak)"
            ),
            "pnl_binary": f"+{BINARY_WIN_R}R on hit, {BINARY_LOSS_R}R on miss, minus cost_rt",
            "pnl_oracle20_diag": (
                f"R = clip(mc_multiple, 0, {ORACLE_CAP}) - 1 - cost_rt "
                "(diagnostic upper bound only)"
            ),
            "cost_rt_default": cost_rt,
            "cost_sensitivity": list(COST_SENSITIVITY),
            "top_fracs": list(top_fracs),
            "top_ks": list(top_ks),
            "no_lookahead": True,
        },
        "censor": {
            "note": (
                "Label/PnL use max MC in observed post-T0 window (cohort ≥7d gate; "
                "~0.6% have ≥30d). False negatives possible for short followup. "
                "Do not invent prices."
            ),
        },
        "folds": [
            {
                "fold": f["fold"],
                "train_n": f["train_n"],
                "test_n": f["test_n"],
                "train_t0_max": f["train_t0_max"],
                "test_t0_min": f["test_t0_min"],
                "test_t0_max": f["test_t0_max"],
            }
            for f in folds
        ],
        "fold_meta": {k: v for k, v in fold_meta.items() if "|" in k},
        "strategies": strategies,
        "comparisons": comparisons,
        "paths": {
            "features": str(FEATURES_PATH.relative_to(ROOT)),
            "labels": str(LABELS_PATH.relative_to(ROOT)),
            "trades_csv": str(OUT_TRADES.relative_to(ROOT)),
            "report_json": str(OUT_JSON.relative_to(ROOT)),
            "report_md": str(OUT_MD.relative_to(ROOT)),
        },
    }


def _cmp(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    def d(key: str) -> float | None:
        if a.get(key) is None or b.get(key) is None:
            return None
        return a[key] - b[key]

    return {
        "delta_hit_rate_q5b_minus_buy60": d("hit_rate"),
        "delta_cum_r_tp10": d("cum_r_tp10"),
        "delta_cum_r_binary": d("cum_r_binary"),
        "delta_cum_r_oracle20": d("cum_r_oracle20"),
        "n_trades_q5b": a["n_trades"],
        "n_trades_buy60": b["n_trades"],
        "hit_q5b": a["hit_rate"],
        "hit_buy60": b["hit_rate"],
    }


def _fmt_pct(x: float | None) -> str:
    return "—" if x is None else f"{100.0 * x:.2f}%"


def _fmt_f(x: float | None, nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def write_markdown(report: dict[str, Any]) -> None:
    rules = report["rules"]
    lines: list[str] = [
        "# Paper-trading v1 — OOS simulación (PRIMARY `hit_10x_30d`)",
        "",
        f"**Fecha:** {report['generated_at']} (Europe/Madrid)  ",
        f"**Modelo candidato:** `{report['primary_set']}` (buy60+Q5a+Q5b) vs baseline `{report['baseline_set']}`  ",
        f"**Label:** `{report['label']}` · OOS base rate ≈ {_fmt_pct(report['oos_base_rate'])}  ",
        "**Anti look-ahead:** umbrales/capacidad sin mirar labels OOS; train cuantiles solo en train.",
        "",
        "## Reglas v1 (decisiones)",
        "",
        "| Pieza | Regla |",
        "|-------|-------|",
        f"| Entrada A | {rules['entry_train_quantile']} |",
        f"| Entrada B | {rules['entry_topk_per_fold']} |",
        f"| Sizing | {rules['sizing']} |",
        f"| Salida / horizonte | {rules['exit_horizon']} |",
        f"| PnL principal (TP10) | `{rules['pnl_tp10_primary']}` |",
        f"| PnL binario | `{rules['pnl_binary']}` |",
        f"| PnL oracle20 (diag) | `{rules['pnl_oracle20_diag']}` |",
        f"| Costes RT default | `{rules['cost_rt_default']:.1%}` (sens {', '.join(f"{c:.1%}" for c in rules["cost_sensitivity"])}) |",
        f"| Top-fracs (A) | {', '.join(f'{t:.0%}' for t in rules['top_fracs'])} |",
        f"| Top-K / fold (B) | {', '.join(str(k) for k in rules['top_ks'])} |",
        "",
        "### Censor / followup",
        "",
        report["censor"]["note"],
        "",
        "Esto es un **proxy de investigación**, no equity real: sin fills, MEV ni impacto de pool.",
        "",
        "## Folds (expanding WF = post-Q5)",
        "",
        "| fold | train_n | test_n | train_t0_max | test_t0_min |",
        "|------|---------|--------|--------------|-------------|",
    ]
    for f in report["folds"]:
        lines.append(
            f"| {f['fold']} | {f['train_n']} | {f['test_n']} | `{f['train_t0_max']}` | `{f['test_t0_min']}` |"
        )

    lines.extend(
        [
            "",
            "## Resultados OOS — Entrada B preferida (top-K / fold)",
            "",
            "Top-K evita el colapso por empates de score en `buy60` (scores ~1.0).",
            "",
            "| strategy | n | hit rate | lift | cum R TP10 | mean R TP10 | max DD TP10 | cum R bin | max DD bin | trades/day |",
            "|----------|---|----------|------|------------|-------------|-------------|-----------|------------|------------|",
        ]
    )
    for name, s in report["strategies"].items():
        if s["rule"] != "topk_per_fold":
            continue
        lines.append(_row(name, s))

    lines.extend(
        [
            "",
            "## Resultados OOS — Entrada A (train quantile)",
            "",
            "| strategy | n | hit rate | lift | cum R TP10 | mean R TP10 | max DD TP10 | cum R bin | max DD bin | trades/day |",
            "|----------|---|----------|------|------------|-------------|-------------|-----------|------------|------------|",
        ]
    )
    for name, s in report["strategies"].items():
        if s["rule"] != "train_quantile":
            continue
        lines.append(_row(name, s))

    lines.extend(["", "### Trades por fold (todas las strategies)", ""])
    for name, s in report["strategies"].items():
        tpf = s.get("trades_per_fold") or {}
        lines.append(
            f"- `{name}`: "
            + ", ".join(f"f{k}={v}" for k, v in sorted(tpf.items(), key=lambda x: int(x[0])))
        )

    lines.extend(
        [
            "",
            "## Comparación `+q5b` vs `buy60`",
            "",
            "| rule | hit q5b | hit buy60 | Δ hit | Δ cum R TP10 | Δ cum R bin | n q5b | n buy60 |",
            "|------|---------|-----------|-------|--------------|-------------|-------|---------|",
        ]
    )
    for k, c in report["comparisons"].items():
        lines.append(
            f"| {k} | {_fmt_pct(c['hit_q5b'])} | {_fmt_pct(c['hit_buy60'])} | "
            f"{_fmt_pct(c['delta_hit_rate_q5b_minus_buy60'])} | "
            f"{_fmt_f(c['delta_cum_r_tp10'], 1)} | {_fmt_f(c['delta_cum_r_binary'], 1)} | "
            f"{c['n_trades_q5b']} | {c['n_trades_buy60']} |"
        )

    lines.extend(
        [
            "",
            "## vs random (mismo n por fold, 5 seeds)",
            "",
            "| strategy | model hit | random hit | model cum R TP10 | random cum R TP10 |",
            "|----------|-----------|------------|------------------|-------------------|",
        ]
    )
    for name, s in report["strategies"].items():
        rb = s.get("random_baseline") or {}
        lines.append(
            f"| `{name}` | {_fmt_pct(s['hit_rate'])} | {_fmt_pct(rb.get('mean_hit_rate'))} | "
            f"{_fmt_f(s['cum_r_tp10'], 1)} | {_fmt_f(rb.get('mean_cum_r_tp10'), 1)} |"
        )

    lines.extend(
        [
            "",
            "## Sensibilidad a costes (cum R TP10)",
            "",
            "| strategy | 1.0% | 1.5% | 2.0% |",
            "|----------|------|------|------|",
        ]
    )
    for name, s in report["strategies"].items():
        if s["rule"] != "topk_per_fold":
            continue
        sens = s.get("cost_sensitivity") or {}
        lines.append(
            f"| `{name}` | {_fmt_f((sens.get('1.0%') or {}).get('cum_r_tp10'), 1)} | "
            f"{_fmt_f((sens.get('1.5%') or {}).get('cum_r_tp10'), 1)} | "
            f"{_fmt_f((sens.get('2.0%') or {}).get('cum_r_tp10'), 1)} |"
        )

    lines.extend(["", "## Umbrales train (Entrada A) — `+q5b`", ""])
    for tf in rules["top_fracs"]:
        key = f"{PRIMARY_SET}|train_q_top{tf:.0%}"
        fm = report["fold_meta"].get(key, {}).get("folds", [])
        lines.append(f"### top {tf:.0%}")
        lines.append("")
        lines.append("| fold | threshold | n_enter | enter_frac | hit_rate | n_unique_train_scores |")
        lines.append("|------|-----------|---------|------------|----------|----------------------|")
        for row in fm:
            lines.append(
                f"| {row['fold']} | {row['threshold_train']:.6f} | {row['n_enter']} | "
                f"{_fmt_pct(row['enter_frac_of_test'])} | {_fmt_pct(row['hit_rate_enter'])} | "
                f"{row['n_unique_train_scores']} |"
            )
        lines.append("")

    lines.extend(["", "## Top-K hit rates por fold — `+q5b`", ""])
    for k in rules["top_ks"]:
        key = f"{PRIMARY_SET}|topk_{k}"
        fm = report["fold_meta"].get(key, {}).get("folds", [])
        lines.append(f"### K={k}")
        lines.append("")
        lines.append("| fold | n | hit_rate | score_min_selected |")
        lines.append("|------|---|----------|--------------------|")
        for row in fm:
            lines.append(
                f"| {row['fold']} | {row['n_enter']} | {_fmt_pct(row['hit_rate_enter'])} | "
                f"{_fmt_f(row.get('score_min_selected'), 6)} |"
            )
        lines.append("")

    # Key takeaways from primary topK 100
    lines.extend(["## Lectura rápida", ""])
    for k_label, k in [("cola saturada", 100), ("cerca tasa natural (~14%)", 1400)]:
        pref = report["strategies"].get(f"{PRIMARY_SET}_topK_{k}")
        base = report["strategies"].get(f"{BASELINE_SET}_topK_{k}")
        if not pref or not base:
            continue
        rb = pref.get("random_baseline") or {}
        lines.extend(
            [
                f"### topK={k} ({k_label})",
                "",
                f"- `+q5b`: **n={pref['n_trades']}**, hit **{_fmt_pct(pref['hit_rate'])}** "
                f"(lift {_fmt_f(pref['lift_vs_base'], 2)}×), "
                f"cum R TP10 **{_fmt_f(pref['cum_r_tp10'], 1)}**, "
                f"max DD TP10 **{_fmt_f(pref['max_dd_tp10'], 1)}**, "
                f"trades/day ≈ {_fmt_f(pref.get('trades_per_day'), 1)}.",
                f"- `buy60`: hit **{_fmt_pct(base['hit_rate'])}**, "
                f"cum R TP10 **{_fmt_f(base['cum_r_tp10'], 1)}**, "
                f"max DD TP10 **{_fmt_f(base['max_dd_tp10'], 1)}**.",
                f"- Random matched: hit ≈ {_fmt_pct(rb.get('mean_hit_rate'))}, "
                f"cum R TP10 ≈ {_fmt_f(rb.get('mean_cum_r_tp10'), 1)}.",
                f"- Δ(`+q5b`−`buy60`) hit={_fmt_pct(pref['hit_rate']-base['hit_rate'])}, "
                f"Δ cum R TP10={_fmt_f(pref['cum_r_tp10']-base['cum_r_tp10'], 1)}.",
                "",
            ]
        )
    lines.extend(
        [
            "**Nota:** hasta ~K=500/fold la precisión OOS satura en 100% para ambos modelos "
            "(coherente con P@top5%=1.0 del WF). La diferenciación `+q5b` vs `buy60` aparece "
            "al profundizar la cola (K≈1000–1400). El valor de Q5 sigue siendo de ranking/AUC; "
            "en paper-trade ultra-selectivo ambos ya capturan casi solo hits.",
            "",
        ]
    )

    lines.extend(
        [
            "## Artefactos",
            "",
            "| Artifact | Path |",
            "|----------|------|",
            "| Script | `src/models/paper_trade_v1.py` |",
            f"| Trades CSV | `{report['paths']['trades_csv']}` |",
            f"| Report JSON | `{report['paths']['report_json']}` |",
            f"| Este MD | `{report['paths']['report_md']}` |",
            f"| Features | `{report['paths']['features']}` |",
            f"| Labels | `{report['paths']['labels']}` |",
            "",
            "## Cómo reproducir",
            "",
            "```bash",
            "cd /workspace/solana-10x",
            "PYTHONPATH=src .venv/bin/python -m models.paper_trade_v1",
            "PYTHONPATH=src .venv/bin/python -m models.paper_trade_v1 \\",
            "  --top-frac 0.05 --top-frac 0.01 --top-k 50 --top-k 100 --top-k 200 --cost-rt 0.015",
            "```",
            "",
            "## Limitaciones",
            "",
            "1. Proxy ≠ P&L real (sin ejecución / slippage de pool / capacidad).",
            "2. Right-censor: pocos mints con ≥30d followup; FN posibles.",
            "3. TP10 asume que se puede salir a 10×; en la práctica el path importa.",
            "4. `buy60` train-quantile colapsa por empates de score≈1; preferir top-K.",
            "5. Sin embargo de horizonte 30d entre folds (span t0 corto); solo `train_t0 < test_t0`.",
            "6. Oracle20 satura en la cola seleccionada — informativo, no operable.",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(lines) + "\n")


def _row(name: str, s: dict[str, Any]) -> str:
    return (
        "| `{name}` | {n} | {hr} | {lift} | {crm} | {mrm} | {ddm} | {crb} | {ddb} | {tpd} |".format(
            name=name,
            n=s["n_trades"],
            hr=_fmt_pct(s["hit_rate"]),
            lift=_fmt_f(s.get("lift_vs_base"), 2) if s.get("lift_vs_base") is not None else "—",
            crm=_fmt_f(s["cum_r_tp10"], 1),
            mrm=_fmt_f(s["mean_r_tp10"], 3),
            ddm=_fmt_f(s["max_dd_tp10"], 1),
            crb=_fmt_f(s["cum_r_binary"], 1),
            ddb=_fmt_f(s["max_dd_binary"], 1),
            tpd=_fmt_f(s.get("trades_per_day"), 1),
        )
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top-frac", action="append", type=float, default=None)
    p.add_argument("--top-k", action="append", type=int, default=None)
    p.add_argument("--cost-rt", type=float, default=DEFAULT_COST_RT)
    args = p.parse_args(argv)
    top_fracs = tuple(args.top_frac) if args.top_frac else DEFAULT_TOP_FRACS
    top_ks = tuple(args.top_k) if args.top_k else DEFAULT_TOP_KS

    df = load_frame()
    label_col = df.attrs["label_col"]

    from models import walk_forward_expand_v2 as wf

    old = wf.LABEL_COL
    wf.LABEL_COL = label_col
    try:
        folds = make_expanding_folds(df)
    finally:
        wf.LABEL_COL = old

    trades_df, fold_meta = run_paper(
        df, folds, top_fracs=top_fracs, top_ks=top_ks, cost_rt=args.cost_rt
    )
    report = aggregate_report(
        trades_df,
        fold_meta,
        folds,
        df,
        top_fracs=top_fracs,
        top_ks=top_ks,
        cost_rt=args.cost_rt,
    )
    OUT_TRADES.parent.mkdir(parents=True, exist_ok=True)
    trades_df.to_csv(OUT_TRADES, index=False)
    OUT_JSON.write_text(json.dumps(report, indent=2) + "\n")
    write_markdown(report)

    # Compact summary for parent
    keys = [
        f"{PRIMARY_SET}_topK_50",
        f"{PRIMARY_SET}_topK_100",
        f"{PRIMARY_SET}_topK_200",
        f"{PRIMARY_SET}_topK_500",
        f"{PRIMARY_SET}_topK_1000",
        f"{PRIMARY_SET}_topK_1400",
        f"{BASELINE_SET}_topK_100",
        f"{BASELINE_SET}_topK_1400",
        f"{PRIMARY_SET}_trainQ_top5%",
    ]
    slim = {k: report["strategies"][k] for k in keys if k in report["strategies"]}
    print(
        json.dumps(
            {
                "wrote_md": str(OUT_MD),
                "wrote_json": str(OUT_JSON),
                "wrote_trades": str(OUT_TRADES),
                "n_trade_rows": len(trades_df),
                "highlights": {
                    k: {
                        "n": v["n_trades"],
                        "hit_rate": v["hit_rate"],
                        "cum_r_tp10": v["cum_r_tp10"],
                        "max_dd_tp10": v["max_dd_tp10"],
                        "cum_r_binary": v["cum_r_binary"],
                        "random_hit": (v.get("random_baseline") or {}).get("mean_hit_rate"),
                        "random_cum_r_tp10": (v.get("random_baseline") or {}).get(
                            "mean_cum_r_tp10"
                        ),
                    }
                    for k, v in slim.items()
                },
                "comparisons": report["comparisons"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
