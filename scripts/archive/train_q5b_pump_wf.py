#!/usr/bin/env python3
"""Offline WF → q5b_pump_YYYYMMDD.joblib (0 Dune, never overwrite q5b_last).

Train-on-store with Pump-path column set (+q5b). Live Path A Pump (2026-10-02)
fills all +q5b cols except creator_prior_mints_all_in_window (always None).
True Pump-trade feature rebuild is impossible without network; this artifact is
explicitly ``train_on_store_with_Pump_path_column_set`` — Dune-store Q5a/Q5b
values under the same column recipe live Pump scores with after dune_cohort
prior stamp. Do NOT swap paper to this model without Sinck GO.


ARCHIVED / NO-GO — use scripts/train_q5b_path_a_candidate_wf.py instead.
See scripts/archive/README.md and cycle0/quarantine-q5b-pump-joblibs-20261002.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[2]  # scripts/archive/ → repo root
sys.path.insert(0, str(ROOT / "src"))

sys.path.insert(0, str(ROOT / "scripts"))
from train_q5b_path_a_common import archive_refuse_or_continue  # noqa: E402

from features.post_q5_sets import FEATURE_SETS, PRIMARY_LABEL, resolve_label_column  # noqa: E402
from models.walk_forward_expand_v2 import make_expanding_folds, metrics_for_scores  # noqa: E402
from models.walk_forward_post_q5 import build_hist_gb  # noqa: E402

# Column taxonomy for Path A Pump vs Dune-store train
PUMP_LIKE_COLS = [
    # Q5b / age / name — live from Pump coin + dune_cohort priors (post A stamp)
    "age_s",
    "age_min",
    "age_proxy_s",
    "has_creator",
    "name_len",
    "name_missing",
    "symbol_len",
    "symbol_missing",
    "creator_prior_mints_7d",
    "creator_prior_mints_30d",
    "creator_prior_mints_cohort",
    "creator_prior_mints_all_in_window",  # always null both sides
]
# Live Pump fills these from frontend trades ≤T0; train still uses Dune Q5a
# (structure match; USD/source distribution may differ).
DUNE_TRADE_IMPLIED_COLS = [
    c
    for c in FEATURE_SETS["+q5b"]
    if c not in PUMP_LIKE_COLS
]

# Soft Pump-gap mask: force all_in_window NaN (train parity); optionally null
# nothing else because live Pump now fills Q5a/buy60 (journal 0-null on 50 rows).
PUMP_GAP_FORCE_NULL = ["creator_prior_mints_all_in_window"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def apply_pump_gap_mask(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in PUMP_GAP_FORCE_NULL:
        if c in out.columns:
            out[c] = np.nan
    return out


def main() -> int:
    _arc = archive_refuse_or_continue()
    if _arc is not None:
        return _arc

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--stamp",
        default=datetime.now().strftime("%Y%m%d"),
        help="YYYYMMDD suffix for q5b_pump_<stamp>.joblib",
    )
    ap.add_argument("--max-train-rows", type=int, default=80_000)
    args = ap.parse_args()

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    model_dir = ROOT / "data/paper_live/models"
    # Also accept data/models/ alias if present; primary is paper_live/models
    out_joblib = model_dir / f"q5b_pump_{args.stamp}.joblib"
    out_calib = model_dir / f"q5b_pump_{args.stamp}_calibration.json"
    out_metrics = ROOT / "cycle0/artifacts" / f"q5b_pump_{args.stamp}_wf_metrics.json"
    q5b_last = model_dir / "q5b_last.joblib"

    if out_joblib.resolve() == q5b_last.resolve():
        print("REFUSE: would overwrite q5b_last")
        return 2
    if not feat_path.is_file() or not lab_path.is_file():
        print("missing features/labels")
        return 1

    feat = pd.read_csv(feat_path)
    lab = pd.read_csv(lab_path)
    label_col, _ = resolve_label_column(lab.columns)
    if label_col != PRIMARY_LABEL:
        print(json.dumps({"status": "label_not_primary", "label_col": label_col}))
        return 1

    cols_wanted = list(FEATURE_SETS["+q5b"])
    cols = [c for c in cols_wanted if c in feat.columns]
    merge_cols = ["mint", label_col]
    if "hit_200k" in lab.columns and "hit_200k" not in merge_cols:
        merge_cols.append("hit_200k")
    df = feat.merge(lab[merge_cols], on="mint", how="inner", validate="one_to_one")
    if "hit_200k" not in df.columns:
        df["hit_200k"] = df[label_col]
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.sort_values("t0", kind="mergesort").reset_index(drop=True)
    df = apply_pump_gap_mask(df)

    folds = make_expanding_folds(df)
    last = folds[-1]
    tr = last["train_idx"]
    te = last["test_idx"]
    if len(tr) > args.max_train_rows:
        tr = tr[-args.max_train_rows :]

    Xtr = df.loc[tr, cols].to_numpy(dtype=float)
    ytr = df.loc[tr, label_col].astype(int).to_numpy()
    Xte = df.loc[te, cols].to_numpy(dtype=float)
    yte = df.loc[te, label_col].astype(int).to_numpy()

    pipe = build_hist_gb()
    pipe.fit(Xtr, ytr)
    train_proba = pipe.predict_proba(Xtr)[:, 1]
    test_proba = pipe.predict_proba(Xte)[:, 1]

    thr_top1 = float(np.quantile(train_proba, 0.99))
    thr_top5 = float(np.quantile(train_proba, 0.95))
    # Also propose thr at frac≈ train top1% pass rate on OOS (do NOT change live)
    frac_ge_09 = float((test_proba >= 0.9).mean())
    frac_ge_top1 = float((test_proba >= thr_top1).mean())

    try:
        auc = float(roc_auc_score(yte, test_proba))
    except ValueError:
        auc = None
    try:
        ap = float(average_precision_score(yte, test_proba))
    except ValueError:
        ap = None

    try:
        oos_m = metrics_for_scores(yte, test_proba)
    except Exception:
        oos_m = {"auc": auc, "ap": ap, "n": int(len(te))}

    # Baseline: score same OOS with q5b_last (read-only)
    baseline: dict[str, Any] = {"available": False}
    if q5b_last.is_file():
        blob_last = joblib.load(q5b_last)
        pipe_last = blob_last["pipeline"]
        names_last = list(blob_last["feature_names"])
        Xl = df.loc[te].reindex(columns=names_last).to_numpy(dtype=float)
        proba_last = pipe_last.predict_proba(Xl)[:, 1]
        try:
            auc_l = float(roc_auc_score(yte, proba_last))
        except ValueError:
            auc_l = None
        try:
            ap_l = float(average_precision_score(yte, proba_last))
        except ValueError:
            ap_l = None
        baseline = {
            "available": True,
            "path": str(q5b_last),
            "auc": auc_l,
            "ap": ap_l,
            "frac_ge_0.9": float((proba_last >= 0.9).mean()),
            "median": float(np.median(proba_last)),
            "max": float(proba_last.max()),
            "train_n": blob_last.get("train_n"),
            "fold": blob_last.get("fold"),
            "train_t0_max": blob_last.get("train_t0_max"),
        }

    calibration = {
        "train_top_frac_thresholds": {"0.01": thr_top1, "0.05": thr_top5},
        "train_n": int(len(tr)),
        "fold": last.get("fold"),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "rule": "score >= quantile(train_scores, 1-top_frac); TRAIN only",
        "proposed_live_thr_note": (
            "Do NOT change live thr. Proposed thr_top1 below is trainQ only; "
            "live CLI currently 0.9."
        ),
        "proposed_thr_top1": thr_top1,
        "proposed_thr_0.9_reference": 0.9,
    }

    meta = {
        "kind": "q5b_pump_wf_artifact",
        "recipe": "train_on_store_with_Pump_path_column_set",
        "stamp": args.stamp,
        "generated_at": _utcnow(),
        "dune_api_calls": 0,
        "overwrote_q5b_last": False,
        "apply_dune_helius_usd_scale": False,
        "column_taxonomy": {
            "pump_like_q5b_age_name_priors": PUMP_LIKE_COLS,
            "dune_trade_implied_q5a_buy60_curve": DUNE_TRADE_IMPLIED_COLS,
            "pump_gap_force_null": PUMP_GAP_FORCE_NULL,
            "note": (
                "Live Pump (PID journal) fills all +q5b except all_in_window. "
                "Train values for Q5a/buy60/curve remain Dune-store (no Pump trade "
                "rebuild offline). Artifact is store-trained under Pump column recipe."
            ),
        },
        "set_name": "+q5b",
        "label": label_col,
        "n_features": len(cols),
        "feature_names": cols,
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "test_n": int(len(te)),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "test_t0_min": str(df.loc[te, "t0"].min()),
        "test_t0_max": str(df.loc[te, "t0"].max()),
    }

    model_dir.mkdir(parents=True, exist_ok=True)
    # Safety: refuse if somehow pointing at q5b_last
    assert out_joblib.name != "q5b_last.joblib"
    assert out_joblib.resolve() != q5b_last.resolve()

    joblib.dump(
        {
            "pipeline": pipe,
            "feature_names": cols,
            "set_name": "+q5b",
            "label": label_col,
            "train_n": int(len(tr)),
            "fold": last.get("fold"),
            "train_t0_max": str(df.loc[tr, "t0"].max()),
            "calibration": calibration,
            "meta": meta,
        },
        out_joblib,
    )

    calib_doc = {
        "kind": "paper_live_train_quantile_calibration",
        "set_name": "+q5b",
        "score_mode": "histgb_q5b",
        "model_path": out_joblib.name,
        "recipe": meta["recipe"],
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "generated_at": _utcnow(),
        "rule": calibration["rule"],
        "why": (
            "Pump-path companion model (store-trained). "
            "NOT a live swap candidate without Sinck GO. "
            "USD scale OFF. 0 Dune API."
        ),
        "thresholds": calibration["train_top_frac_thresholds"],
        "train_score_stats": {
            "min": float(train_proba.min()),
            "median": float(np.median(train_proba)),
            "p99": thr_top1,
            "p95": thr_top5,
            "max": float(train_proba.max()),
            "n_ge_top1pct": int((train_proba >= thr_top1).sum()),
            "n_ge_top5pct": int((train_proba >= thr_top5).sum()),
        },
        "oos_held_out": {
            "n": int(len(te)),
            "auc": auc,
            "ap": ap,
            "frac_ge_0.9": frac_ge_09,
            "frac_ge_train_top1": frac_ge_top1,
            "median": float(np.median(test_proba)),
            "max": float(test_proba.max()),
            "base_rate": float(yte.mean()),
        },
        "baseline_q5b_last_same_oos": baseline,
        "column_taxonomy": meta["column_taxonomy"],
        "go_nogo_default": "NO-GO",
    }
    out_calib.write_text(json.dumps(calib_doc, indent=2) + "\n")

    metrics_doc = {
        **calib_doc["oos_held_out"],
        "proposed_thr_top1": thr_top1,
        "proposed_thr_top5": thr_top5,
        "live_thr_unchanged": 0.9,
        "baseline_q5b_last": baseline,
        "joblib": str(out_joblib),
        "calibration_json": str(out_calib),
        "recipe": meta["recipe"],
        "dune_api_calls": 0,
        "generated_at": _utcnow(),
        "metrics_for_scores": {
            k: (float(v) if isinstance(v, (float, np.floating, int, np.integer)) else v)
            for k, v in (oos_m or {}).items()
            if k in ("auc", "ap", "precision_at_100", "recall_at_100", "base_rate", "n")
            or True
        },
    }
    # sanitize metrics_for_scores (may contain numpy)
    def _jsonable(o: Any) -> Any:
        if isinstance(o, dict):
            return {k: _jsonable(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_jsonable(x) for x in o]
        if isinstance(o, (np.floating, float)):
            return float(o)
        if isinstance(o, (np.integer, int)):
            return int(o)
        if isinstance(o, np.ndarray):
            return o.tolist()
        return o

    out_metrics.parent.mkdir(parents=True, exist_ok=True)
    out_metrics.write_text(json.dumps(_jsonable(metrics_doc), indent=2) + "\n")

    # Verify q5b_last untouched
    assert q5b_last.is_file()
    print(
        json.dumps(
            {
                "status": "ok",
                "joblib": str(out_joblib),
                "calibration": str(out_calib),
                "metrics": str(out_metrics),
                "oos_auc": auc,
                "oos_ap": ap,
                "oos_frac_ge_0.9": frac_ge_09,
                "proposed_thr_top1": thr_top1,
                "baseline_frac_ge_0.9": baseline.get("frac_ge_0.9"),
                "q5b_last_untouched": True,
                "dune_api_calls": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
