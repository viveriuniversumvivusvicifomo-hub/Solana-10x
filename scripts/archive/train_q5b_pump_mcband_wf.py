#!/usr/bin/env python3
"""WF on Pump MC-band pilot matrix → q5b_pump_mcband_YYYYMMDD.joblib.

Never overwrites q5b_last.joblib or q5b_calibration.json.
Never touches paper_live. 0 Dune. Lite OFF. USD scale OFF.
Distinct from q5b_pump_pilot500_* and q5b_pump_20261002 (twin).


ARCHIVED / NO-GO — use scripts/train_q5b_path_a_candidate_wf.py instead.
See scripts/archive/README.md and cycle0/quarantine-q5b-pump-joblibs-20261002.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
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

from features.post_q5_sets import FEATURE_SETS, PRIMARY_LABEL  # noqa: E402
from models.walk_forward_expand_v2 import make_expanding_folds, metrics_for_scores  # noqa: E402
from models.walk_forward_post_q5 import build_hist_gb  # noqa: E402

# reuse journal rescore helper
sys.path.insert(0, str(ROOT / "scripts"))
from train_q5b_path_a_common import rescore_journal_pump  # noqa: E402


def _utcnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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
    if o is None or isinstance(o, (str, bool)):
        return o
    return str(o)


def main() -> int:
    _arc = archive_refuse_or_continue()
    if _arc is not None:
        return _arc

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument(
        "--artifact-tag",
        default="",
        help="Optional tag inserted before stamp, e.g. 'scale' → q5b_pump_mcband_scale_YYYYMMDD",
    )
    ap.add_argument("--features", type=Path, default=None)
    ap.add_argument("--require-scoreable", action="store_true", default=True)
    ap.add_argument("--min-pre-t0-trades", type=int, default=1,
                    help="Drop rows with fewer pre-T0 trades (anti empty-pre bias)")
    args = ap.parse_args()

    tag = (args.artifact_tag or "").strip("_")
    name_mid = f"mcband_{tag}" if tag else "mcband"
    feat_default = (
        ROOT / f"data/samples/features_pump_path_a_mcband_{tag}_{args.stamp}.csv"
        if tag
        else ROOT / f"data/samples/features_pump_path_a_mcband_{args.stamp}.csv"
    )
    feat_path = args.features or feat_default
    model_dir = ROOT / "data/paper_live/models"
    out_joblib = model_dir / f"q5b_pump_{name_mid}_{args.stamp}.joblib"
    out_calib = model_dir / f"q5b_pump_{name_mid}_{args.stamp}_calibration.json"
    out_metrics = ROOT / f"cycle0/npz/q5b_pump_{name_mid}_{args.stamp}_wf_metrics.json"
    q5b_last = model_dir / "q5b_last.joblib"
    q5b_calib = model_dir / "q5b_calibration.json"

    forbidden = {
        q5b_last.resolve(),
        q5b_calib.resolve(),
        (model_dir / "q5b_pump_pilot500_20261002.joblib").resolve(),
        (model_dir / "q5b_pump_20261002.joblib").resolve(),
        (model_dir / "q5b_pump_mcband_20261002.joblib").resolve(),
        (model_dir / "q5b_pump_mcband_20261002_calibration.json").resolve(),
    }
    assert out_joblib.resolve() not in forbidden
    assert out_calib.resolve() not in forbidden
    assert out_joblib.name != "q5b_last.joblib"
    assert "mcband" in out_joblib.name
    if tag:
        assert tag in out_joblib.name

    if not feat_path.is_file():
        print(json.dumps({"status": "missing_features", "path": str(feat_path)}))
        return 1

    df = pd.read_csv(feat_path)
    label_col = "hit_10x_30d" if "hit_10x_30d" in df.columns else PRIMARY_LABEL

    n_before = len(df)
    if "reconstructable" in df.columns:
        df = df[df["reconstructable"] == 1].copy()
    if args.require_scoreable and "capture_scoreable" in df.columns:
        df = df[df["capture_scoreable"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "fetch_ok" in df.columns:
        df = df[df["fetch_ok"] == 1].copy()
    df = df[df[label_col].notna()].copy()
    if args.min_pre_t0_trades > 0 and "n_trades_pre_t0" in df.columns:
        df = df[df["n_trades_pre_t0"].fillna(0) >= args.min_pre_t0_trades].copy()

    print(
        json.dumps(
            {
                "n_before": n_before,
                "n_after_filters": len(df),
                "label_rate": float(df[label_col].mean()) if len(df) else None,
                "min_pre_t0_trades": args.min_pre_t0_trades,
            }
        )
    )

    cols = [c for c in FEATURE_SETS["+q5b"] if c in df.columns]
    if "creator_prior_mints_all_in_window" in df.columns:
        df["creator_prior_mints_all_in_window"] = np.nan

    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["t0"]).sort_values("t0", kind="mergesort").reset_index(drop=True)
    df[label_col] = df[label_col].astype(int)

    if len(df) < 80:
        print(json.dumps({"status": "too_few_rows", "n": len(df)}))
        return 1

    _hit200k_orig = df["hit_200k"].copy() if "hit_200k" in df.columns else None
    df["hit_200k"] = df[label_col].astype(int)
    try:
        folds = make_expanding_folds(df)
    except RuntimeError as exc:
        print(json.dumps({"folds_fallback": True, "reason": str(exc)}))
        folds = []
    if _hit200k_orig is not None:
        df["hit_200k"] = _hit200k_orig
    if not folds:
        cut = int(len(df) * 0.7)
        y = df[label_col].astype(int).to_numpy()
        for cut_try in range(cut, max(cut - 40, len(df) // 2), -1):
            if (
                y[:cut_try].sum() >= 1
                and y[cut_try:].sum() >= 1
                and len(set(y[:cut_try].tolist())) >= 2
                and len(set(y[cut_try:].tolist())) >= 2
            ):
                cut = cut_try
                break
        folds = [{"fold": 1, "train_idx": np.arange(0, cut), "test_idx": np.arange(cut, len(df))}]

    last = folds[-1]
    tr = np.asarray(last["train_idx"])
    te = np.asarray(last["test_idx"])

    Xtr = df.loc[tr, cols].to_numpy(dtype=float)
    ytr = df.loc[tr, label_col].astype(int).to_numpy()
    Xte = df.loc[te, cols].to_numpy(dtype=float)
    yte = df.loc[te, label_col].astype(int).to_numpy()

    pipe = build_hist_gb()
    if len(tr) < 200:
        from sklearn.ensemble import HistGradientBoostingClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline

        pipe = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median")),
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        max_depth=3,
                        learning_rate=0.08,
                        max_iter=150,
                        min_samples_leaf=max(5, len(tr) // 20),
                        l2_regularization=0.1,
                        random_state=42,
                        class_weight="balanced",
                    ),
                ),
            ]
        )

    pipe.fit(Xtr, ytr)
    train_proba = pipe.predict_proba(Xtr)[:, 1]
    test_proba = pipe.predict_proba(Xte)[:, 1]
    thr_top1 = float(np.quantile(train_proba, 0.99)) if len(train_proba) else 0.9
    thr_top5 = float(np.quantile(train_proba, 0.95)) if len(train_proba) else 0.9
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
        }

    live_rescore = rescore_journal_pump(
        pipe, cols, journal=ROOT / "data/paper_live/paper_journal.sqlite"
    )

    calibration = {
        "train_top_frac_thresholds": {"0.01": thr_top1, "0.05": thr_top5},
        "train_n": int(len(tr)),
        "fold": last.get("fold"),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "rule": "score >= quantile(train_scores, 1-top_frac); TRAIN only",
        "proposed_thr_top1": thr_top1,
        "proposed_thr_0.9_reference": 0.9,
    }

    meta = {
        "kind": "q5b_pump_mcband_wf_artifact",
        "recipe": "pump_mc_band_from_trades_v1",
        "t0_policy": "pump_mc_band_from_trades_v1",
        "t0_definition": "pump_mc_band_sighting_v1",
        "stamp": args.stamp,
        "generated_at": _utcnow(),
        "dune_api_calls": 0,
        "overwrote_q5b_last": False,
        "overwrote_q5b_calibration": False,
        "apply_dune_helius_usd_scale": False,
        "lite": False,
        "features_path": str(feat_path),
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
        "n_matrix_rows_used": int(len(df)),
        "filter_n_before": n_before,
        "min_pre_t0_trades": args.min_pre_t0_trades,
    }

    model_dir.mkdir(parents=True, exist_ok=True)
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

    go = "NO-GO"
    if live_rescore.get("available"):
        lift_max = live_rescore.get("lift_max")
        lift_med = live_rescore.get("lift_median")
        lift_frac = live_rescore.get("lift_frac_ge_0.9")
        if (
            lift_max is not None
            and lift_med is not None
            and lift_frac is not None
            and lift_max >= 0
            and lift_med >= 0
            and lift_frac >= 0
        ):
            go = "CONDITIONAL-GO"  # still default NO-GO paper unless Sinck; note positive lift

    calib_doc = {
        "kind": "paper_live_train_quantile_calibration",
        "set_name": "+q5b",
        "score_mode": "histgb_q5b",
        "model_path": out_joblib.name,
        "recipe": meta["recipe"],
        "t0_policy": meta["t0_policy"],
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "generated_at": _utcnow(),
        "rule": calibration["rule"],
        "why": (
            "Pump MC-band pilot: T0=first Pump trade MC∈[8k,20k]; "
            "hit_10x relabeled from that T0; Q5a/buy60 ≤T0; Q5b from expand. "
            "NOT a live swap without Sinck GO + non-negative live lift."
        ),
        "thresholds": calibration["train_top_frac_thresholds"],
        "train_score_stats": {
            "min": float(train_proba.min()),
            "median": float(np.median(train_proba)),
            "p99": thr_top1,
            "p95": thr_top5,
            "max": float(train_proba.max()),
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
        "live_journal_rescore": live_rescore,
        "go_nogo_default": "NO-GO",
        "go_nogo_observed": go,
    }
    out_calib.write_text(json.dumps(_jsonable(calib_doc), indent=2) + "\n")

    metrics_doc = {
        **calib_doc["oos_held_out"],
        "proposed_thr_top1": thr_top1,
        "proposed_thr_top5": thr_top5,
        "live_thr_unchanged": 0.9,
        "baseline_q5b_last": baseline,
        "live_journal_rescore": live_rescore,
        "joblib": str(out_joblib),
        "calibration_json": str(out_calib),
        "recipe": meta["recipe"],
        "t0_policy": meta["t0_policy"],
        "features_path": str(feat_path),
        "n_matrix_rows_used": int(len(df)),
        "dune_api_calls": 0,
        "generated_at": _utcnow(),
        "metrics_for_scores": _jsonable(oos_m),
        "go_nogo_default": "NO-GO",
        "go_nogo_observed": go,
    }
    out_metrics.parent.mkdir(parents=True, exist_ok=True)
    out_metrics.write_text(json.dumps(_jsonable(metrics_doc), indent=2) + "\n")

    assert q5b_last.is_file()
    assert q5b_calib.is_file()

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
                "oos_median": float(np.median(test_proba)),
                "oos_max": float(test_proba.max()),
                "baseline_auc": baseline.get("auc"),
                "live_rescore": live_rescore,
                "q5b_last_untouched": True,
                "dune_api_calls": 0,
                "go_nogo_default": "NO-GO",
                "go_nogo_observed": go,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
