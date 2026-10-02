#!/usr/bin/env python3
"""WF on Pump-true pilot500 matrix → q5b_pump_pilot500_YYYYMMDD.joblib.

Never overwrites q5b_last.joblib or q5b_calibration.json.
Never touches paper_live. 0 Dune. Lite OFF. USD scale OFF.


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

from features.post_q5_sets import FEATURE_SETS, PRIMARY_LABEL  # noqa: E402
from models.walk_forward_expand_v2 import make_expanding_folds, metrics_for_scores  # noqa: E402
from models.walk_forward_post_q5 import build_hist_gb  # noqa: E402


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


def rescore_journal_pump(
    pipe,
    feature_names: list[str],
    *,
    journal: Path,
    since: str = "2026-10-02",
    limit: int = 200,
) -> dict[str, Any]:
    """Score a small Path A Pump journal slice with candidate vs q5b_last."""
    import sqlite3

    con = sqlite3.connect(str(journal))
    con.row_factory = sqlite3.Row
    rows = list(
        con.execute(
            "SELECT mint, score, features_json, created_at FROM sightings "
            "WHERE created_at >= ? ORDER BY rowid DESC LIMIT ?",
            (since, limit * 3),
        )
    )
    con.close()
    vectors: list[dict[str, Any]] = []
    for r in rows:
        if not r["features_json"]:
            continue
        try:
            feats = json.loads(r["features_json"])
        except json.JSONDecodeError:
            continue
        if feats.get("t0_definition") != "pump_mc_band_sighting_v1":
            continue
        if not feats.get("capture_scoreable"):
            continue
        vectors.append(
            {
                "mint": r["mint"],
                "score_logged": r["score"],
                "created_at": r["created_at"],
                **{c: feats.get(c) for c in feature_names},
            }
        )
        if len(vectors) >= limit:
            break
    if not vectors:
        return {"available": False, "reason": "no_pump_scoreable_rows"}
    df = pd.DataFrame(vectors)
    X = df.reindex(columns=feature_names).to_numpy(dtype=float)
    proba = pipe.predict_proba(X)[:, 1]
    out: dict[str, Any] = {
        "available": True,
        "n": int(len(df)),
        "pilot": {
            "median": float(np.median(proba)),
            "mean": float(np.mean(proba)),
            "max": float(proba.max()),
            "min": float(proba.min()),
            "frac_ge_0.9": float((proba >= 0.9).mean()),
            "p90": float(np.quantile(proba, 0.9)),
            "p99": float(np.quantile(proba, 0.99)),
        },
    }
    q5b_last = ROOT / "data/paper_live/models/q5b_last.joblib"
    if q5b_last.is_file():
        blob = joblib.load(q5b_last)
        pipe_l = blob["pipeline"]
        names_l = list(blob["feature_names"])
        Xl = df.reindex(columns=names_l).to_numpy(dtype=float)
        pl = pipe_l.predict_proba(Xl)[:, 1]
        out["q5b_last"] = {
            "median": float(np.median(pl)),
            "mean": float(np.mean(pl)),
            "max": float(pl.max()),
            "min": float(pl.min()),
            "frac_ge_0.9": float((pl >= 0.9).mean()),
            "p90": float(np.quantile(pl, 0.9)),
            "p99": float(np.quantile(pl, 0.99)),
        }
        out["lift_max"] = float(proba.max() - pl.max())
        out["lift_median"] = float(np.median(proba) - np.median(pl))
        out["lift_frac_ge_0.9"] = float((proba >= 0.9).mean() - (pl >= 0.9).mean())
    return out


def main() -> int:
    _arc = archive_refuse_or_continue()
    if _arc is not None:
        return _arc

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument(
        "--features",
        type=Path,
        default=None,
        help="pilot matrix CSV (default features_pump_path_a_pilot500_<stamp>.csv)",
    )
    ap.add_argument("--require-fetch-ok", action="store_true", default=True)
    ap.add_argument("--no-require-fetch-ok", action="store_false", dest="require_fetch_ok")
    args = ap.parse_args()

    feat_path = args.features or (
        ROOT / f"data/samples/features_pump_path_a_pilot500_{args.stamp}.csv"
    )
    model_dir = ROOT / "data/paper_live/models"
    out_joblib = model_dir / f"q5b_pump_pilot500_{args.stamp}.joblib"
    out_calib = model_dir / f"q5b_pump_pilot500_{args.stamp}_calibration.json"
    out_metrics = ROOT / f"cycle0/artifacts/q5b_pump_pilot500_{args.stamp}_wf_metrics.json"
    q5b_last = model_dir / "q5b_last.joblib"
    q5b_calib = model_dir / "q5b_calibration.json"

    assert out_joblib.name != "q5b_last.joblib"
    assert out_joblib.resolve() != q5b_last.resolve()
    assert out_calib.resolve() != q5b_calib.resolve()

    if not feat_path.is_file():
        print(json.dumps({"status": "missing_features", "path": str(feat_path)}))
        return 1

    df = pd.read_csv(feat_path)
    label_col = "hit_10x_30d" if "hit_10x_30d" in df.columns else PRIMARY_LABEL
    if label_col not in df.columns:
        print(json.dumps({"status": "no_label"}))
        return 1

    if args.require_fetch_ok and "fetch_ok" in df.columns:
        n_before = len(df)
        df = df[df["fetch_ok"] == 1].copy()
        # Keep empty-pre-T0 rows: most hit_10x_30d positives have 0 Pump trades
        # under expand_t0_ts (T0 often precedes first frontend trade). Dropping
        # them collapses the label base-rate (~69→4) and kills WF viability.
        n_empty = int((df.get("n_trades_pre_t0", pd.Series(0, index=df.index)).fillna(0) <= 0).sum())
        print(
            json.dumps(
                {
                    "filter_fetch_ok": True,
                    "n_before": n_before,
                    "n_after": len(df),
                    "n_empty_pre_t0_kept": n_empty,
                    "label_rate_after": float(df[label_col].mean()) if label_col in df.columns else None,
                }
            )
        )

    cols = [c for c in FEATURE_SETS["+q5b"] if c in df.columns]
    # Force all_in_window null (live+train parity)
    if "creator_prior_mints_all_in_window" in df.columns:
        df["creator_prior_mints_all_in_window"] = np.nan

    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["t0"]).sort_values("t0", kind="mergesort").reset_index(drop=True)
    df[label_col] = df[label_col].astype(int)

    if len(df) < 80:
        print(json.dumps({"status": "too_few_rows", "n": len(df)}))
        return 1

    # walk_forward_expand_v2.make_expanding_folds checks class balance on
    # LABEL_COL=hit_200k (proxy). Pilot trains on hit_10x_30d; hit_200k is near
    # empty here, so temporarily alias primary → hit_200k for fold construction.
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
        # Fallback: 70/30 time split (both classes required on each side)
        cut = int(len(df) * 0.7)
        # nudge cut so train/test each have ≥1 pos if possible
        y = df[label_col].astype(int).to_numpy()
        for cut_try in range(cut, max(cut - 40, len(df) // 2), -1):
            if y[:cut_try].sum() >= 1 and y[cut_try:].sum() >= 1 and y[:cut_try].min() <= y[:cut_try].max():
                if len(set(y[:cut_try].tolist())) >= 2 and len(set(y[cut_try:].tolist())) >= 2:
                    cut = cut_try
                    break
        folds = [
            {
                "fold": 1,
                "train_idx": np.arange(0, cut),
                "test_idx": np.arange(cut, len(df)),
            }
        ]
    last = folds[-1]
    tr = np.asarray(last["train_idx"])
    te = np.asarray(last["test_idx"])

    Xtr = df.loc[tr, cols].to_numpy(dtype=float)
    ytr = df.loc[tr, label_col].astype(int).to_numpy()
    Xte = df.loc[te, cols].to_numpy(dtype=float)
    yte = df.loc[te, label_col].astype(int).to_numpy()

    pipe = build_hist_gb()
    # min_samples_leaf=40 may be harsh for small n — clone with softer leaf if needed
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
            "note": "q5b_last scored on pilot-matrix OOS rows (Pump-overlay X); column recipe match",
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
        "kind": "q5b_pump_pilot500_wf_artifact",
        "recipe": "pump_true_pilot500_expand_t0_overlay",
        "t0_policy": "expand_t0_ts",
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

    calib_doc = {
        "kind": "paper_live_train_quantile_calibration",
        "set_name": "+q5b",
        "score_mode": "histgb_q5b",
        "model_path": out_joblib.name,
        "recipe": meta["recipe"],
        "t0_policy": "expand_t0_ts",
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "generated_at": _utcnow(),
        "rule": calibration["rule"],
        "why": (
            "Pump-true pilot500: Q5a/buy60 from Pump frontend trades ≤ expand t0_ts; "
            "Q5b/priors from expand store. NOT a live swap without Sinck GO."
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
        "t0_policy": "expand_t0_ts",
        "features_path": str(feat_path),
        "n_matrix_rows_used": int(len(df)),
        "dune_api_calls": 0,
        "generated_at": _utcnow(),
        "metrics_for_scores": _jsonable(oos_m),
        "go_nogo_default": "NO-GO",
    }
    out_metrics.parent.mkdir(parents=True, exist_ok=True)
    out_metrics.write_text(json.dumps(_jsonable(metrics_doc), indent=2) + "\n")

    # Verify baselines untouched
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
                "baseline_auc": baseline.get("auc"),
                "baseline_frac_ge_0.9": baseline.get("frac_ge_0.9"),
                "live_rescore": live_rescore,
                "q5b_last_untouched": True,
                "dune_api_calls": 0,
                "go_nogo_default": "NO-GO",
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
