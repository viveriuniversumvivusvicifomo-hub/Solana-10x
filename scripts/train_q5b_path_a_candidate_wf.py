#!/usr/bin/env python3
"""CANONICAL Path A q5b candidate walk-forward trainer (SolModelos).

Follows:
  cycle0/recipe-path-a-train-canonical-20261002.md
  cycle0/go-criterion-q5b-candidate-vs-last-20261002.md
  cycle0/go-before-coding-gate-20261002.md (D-02: requires --go-card)

Default / export paths are **candidate only**:
  data/paper_live/models/q5b_path_a_candidate_*.joblib
NEVER writes q5b_last.joblib / q5b_calibration.json.
Hard-refuses if --out resolves to those producción artifacts (exit 2).

Profiles (feature defaults / filters; export stays candidate_*):
  livelike  — CANONICAL train matrix (SolDatos: build_pump_path_a.py livelike)
  pilot500  — historical expand_t0 pilot matrix
  mcband    — historical MC-band pilot matrix
  twin      — store twin (Dune-store X under Pump column recipe) — historical

Build matrices: SolDatos owns caches via scripts/build_pump_path_a.py
(do not break that CLI). This script is train-only.

Constraints: 0 Dune API · USD scale OFF · paper untouched · no q5b_last overwrite.
Train refuses without a filled --go-card (cycle0/templates/GO_CARD.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from features.post_q5_sets import FEATURE_SETS, PRIMARY_LABEL  # noqa: E402
from models.walk_forward_expand_v2 import make_expanding_folds, metrics_for_scores  # noqa: E402
from models.walk_forward_post_q5 import build_hist_gb  # noqa: E402
from train_q5b_path_a_common import (  # noqa: E402
    MODEL_DIR,
    Q5B_CALIB,
    Q5B_LAST,
    default_candidate_joblib,
    jsonable,
    refuse_if_q5b_last,
    rescore_journal_pump,
    utcnow,
)
from check_go_gate import refuse_unless_go_card  # noqa: E402

PROFILES = ("livelike", "pilot500", "mcband", "twin")
RECIPE_DOC = "cycle0/recipe-path-a-train-canonical-20261002.md"
GO_DOC = "cycle0/go-criterion-q5b-candidate-vs-last-20261002.md"
GO_GATE_DOC = "cycle0/go-before-coding-gate-20261002.md"
GO_CARD_TEMPLATE = "cycle0/templates/GO_CARD.md"
BUILD_ENTRY = "scripts/build_pump_path_a.py"


def _resolve_features(profile: str, stamp: str, features: Path | None, usable_only: bool) -> Path:
    if features is not None:
        return features
    if profile == "livelike":
        usable = ROOT / f"data/samples/pump_livelike_usable_{stamp}.csv"
        default = ROOT / f"data/samples/features_pump_path_a_livelike_{stamp}.csv"
        if usable_only and usable.is_file():
            return usable
        return default
    if profile == "pilot500":
        return ROOT / f"data/samples/features_pump_path_a_pilot500_{stamp}.csv"
    if profile == "mcband":
        return ROOT / f"data/samples/features_pump_path_a_mcband_{stamp}.csv"
    # twin: Dune-store expand matrix (historical)
    return ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"


def _filter_matrix(df: pd.DataFrame, profile: str, args: argparse.Namespace, label_col: str) -> pd.DataFrame:
    out = df
    if "reconstructable" in out.columns:
        out = out[out["reconstructable"] == 1].copy()
    if "capture_scoreable" in out.columns and profile in ("livelike", "mcband"):
        out = out[out["capture_scoreable"].astype(str).str.lower().isin(["true", "1"])].copy()
    if "fetch_ok" in out.columns and profile != "twin":
        out = out[out["fetch_ok"] == 1].copy()
    if profile == "livelike" and args.require_livelike and "livelike_ok" in out.columns:
        if (out.get("livelike_ok", pd.Series(dtype=int)) == 1).any():
            soft = out[out["livelike_ok"] == 1]
            if len(soft) >= 80:
                out = soft.copy()
            elif "livelike_hard_ok" in out.columns:
                out = out[out["livelike_hard_ok"] == 1].copy()
        elif "livelike_hard_ok" in out.columns:
            out = out[out["livelike_hard_ok"] == 1].copy()
    out = out[out[label_col].notna()].copy()
    min_trades = getattr(args, "min_pre_t0_trades", 0) or 0
    if min_trades > 0 and "n_trades_pre_t0" in out.columns:
        out = out[out["n_trades_pre_t0"].fillna(0) >= min_trades].copy()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--profile",
        choices=PROFILES,
        default="livelike",
        help="Feature/filter profile (default livelike = canonical Path A)",
    )
    ap.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Candidate joblib path (default q5b_path_a_candidate[_profile]_STAMP.joblib). "
        "REFUSE if resolves to q5b_last.joblib",
    )
    ap.add_argument("--features", type=Path, default=None)
    ap.add_argument(
        "--usable-only",
        action="store_true",
        default=True,
        help="Prefer pump_livelike_usable_*.csv when profile=livelike",
    )
    ap.add_argument("--no-usable-only", action="store_false", dest="usable_only")
    ap.add_argument("--require-livelike", action="store_true", default=True)
    ap.add_argument("--no-require-livelike", action="store_false", dest="require_livelike")
    ap.add_argument("--min-pre-t0-trades", type=int, default=5)
    ap.add_argument("--journal-limit", type=int, default=400)
    ap.add_argument(
        "--go-card",
        type=Path,
        default=None,
        help=(
            "Filled GO_CARD (cycle0/templates/GO_CARD.md). Required for real train "
            f"(D-02 / {GO_GATE_DOC}). Not required for --dry-path-check."
        ),
    )
    ap.add_argument(
        "--dry-path-check",
        action="store_true",
        help="Only validate --out refuse policy and print resolved paths; exit 0/2 (no train)",
    )
    args = ap.parse_args(argv)

    profile = args.profile
    if args.out is not None:
        out_joblib = Path(args.out).expanduser()
        if not out_joblib.is_absolute():
            # bare filename → models dir; otherwise relative to ROOT
            if out_joblib.parent == Path("."):
                out_joblib = MODEL_DIR / out_joblib.name
            else:
                out_joblib = (ROOT / out_joblib).resolve()
        else:
            out_joblib = out_joblib.resolve()
    else:
        out_joblib = default_candidate_joblib(
            args.stamp, profile=None if profile == "livelike" else profile
        )

    out_calib = out_joblib.with_name(out_joblib.stem + "_calibration.json")
    tag = "candidate" if profile == "livelike" else f"candidate_{profile}"
    out_metrics = ROOT / f"cycle0/npz/q5b_path_a_{tag}_{args.stamp}_wf_metrics.json"

    # Hard refuse before any train I/O
    for label, path in (("--out", out_joblib), ("calibration", out_calib)):
        code = refuse_if_q5b_last(path, label=label)
        if code is not None:
            return code
    if "q5b_last" in out_joblib.name.lower():
        return refuse_if_q5b_last(out_joblib, label="--out") or 2
    if not out_joblib.name.startswith("q5b_path_a_candidate"):
        print(
            json.dumps(
                {
                    "status": "REFUSE",
                    "reason": "out_must_be_q5b_path_a_candidate_prefix",
                    "path": str(out_joblib),
                    "message": (
                        "REFUSE: --out basename must start with q5b_path_a_candidate "
                        f"(got {out_joblib.name}). See {RECIPE_DOC}."
                    ),
                },
                indent=2,
            )
        )
        return 2

    feat_path = _resolve_features(profile, args.stamp, args.features, args.usable_only)

    if args.dry_path_check:
        print(
            json.dumps(
                {
                    "status": "ok_path_check",
                    "profile": profile,
                    "out_joblib": str(out_joblib),
                    "out_calib": str(out_calib),
                    "out_metrics": str(out_metrics),
                    "features": str(feat_path),
                    "recipe": RECIPE_DOC,
                    "go_criterion": GO_DOC,
                    "go_gate": GO_GATE_DOC,
                    "go_card_template": GO_CARD_TEMPLATE,
                    "go_card_required_for_train": True,
                    "build_entry": BUILD_ENTRY,
                    "refuses_q5b_last": True,
                },
                indent=2,
            )
        )
        return 0

    # D-02: hard GO-before-coding gate (filled card required for any real train)
    go_code = refuse_unless_go_card(args.go_card, expect_action="train", print_json=True)
    if go_code is not None:
        return go_code

    # --- twin historical path uses label merge (store) ---
    if profile == "twin":
        return _run_twin(args, out_joblib, out_calib, out_metrics)

    if not feat_path.is_file():
        print(
            json.dumps(
                {
                    "status": "missing_features",
                    "path": str(feat_path),
                    "hint": f"Build via: python {BUILD_ENTRY} {profile} --stamp {args.stamp}",
                }
            )
        )
        return 1

    df = pd.read_csv(feat_path)
    label_col = "hit_10x_30d" if "hit_10x_30d" in df.columns else PRIMARY_LABEL
    n_before = len(df)
    df = _filter_matrix(df, profile, args, label_col)

    print(
        json.dumps(
            {
                "n_before": n_before,
                "n_after_filters": len(df),
                "label_rate": float(df[label_col].mean()) if len(df) else None,
                "n_pos": int((df[label_col] == 1).sum()) if len(df) else 0,
                "features_path": str(feat_path),
                "profile": profile,
                "recipe": RECIPE_DOC,
                "go_criterion": GO_DOC,
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
    if Q5B_LAST.is_file():
        blob_last = joblib.load(Q5B_LAST)
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
            "path": str(Q5B_LAST),
            "auc": auc_l,
            "ap": ap_l,
            "frac_ge_0.9": float((proba_last >= 0.9).mean()),
            "median": float(np.median(proba_last)),
            "max": float(proba_last.max()),
        }

    live_rescore = rescore_journal_pump(
        pipe,
        cols,
        journal=ROOT / "data/paper_live/paper_journal.sqlite",
        since="2026-10-02",
        limit=args.journal_limit,
    )

    absurd_oos = bool(
        (auc is not None and auc < 0.45)
        or (ap is not None and ap < 0.02 and float(yte.mean()) > 0.05)
        or frac_ge_09 > 0.85
    )

    # GO uses full criterion doc (max+med+frac≥0.9); record provisional legs here
    go = "NO-GO"
    go_reason = "default_no_go"
    if live_rescore.get("available") and live_rescore.get("q5b_last"):
        lift_max = live_rescore.get("lift_max")
        lift_med = live_rescore.get("lift_median")
        lift_frac = live_rescore.get("lift_frac_ge_0.9")
        live_max = live_rescore["pilot"]["max"]
        last_max = live_rescore["q5b_last"]["max"]
        live_med = live_rescore["pilot"]["median"]
        last_med = live_rescore["q5b_last"]["median"]
        live_frac = live_rescore["pilot"]["frac_ge_0.9"]
        last_frac = live_rescore["q5b_last"]["frac_ge_0.9"]
        improved = (
            lift_max is not None
            and lift_med is not None
            and lift_frac is not None
            and live_max > last_max
            and live_med > last_med
            and live_frac >= last_frac
        )
        if improved and not absurd_oos:
            go = "GO"
            go_reason = "live_max_med_and_frac_ge_0.9_improved_vs_q5b_last_oos_ok"
        elif improved and absurd_oos:
            go = "NO-GO"
            go_reason = "live_lift_but_absurd_oos"
        else:
            go = "NO-GO"
            go_reason = (
                f"no_full_lift max {live_max:.4f} vs {last_max:.4f}; "
                f"med {live_med:.4f} vs {last_med:.4f}; "
                f"frac {live_frac:.4f} vs {last_frac:.4f} "
                f"(see {GO_DOC})"
            )

    calibration = {
        "train_top_frac_thresholds": {"0.01": thr_top1, "0.05": thr_top5},
        "train_n": int(len(tr)),
        "fold": last.get("fold"),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "rule": "score >= quantile(train_scores, 1-top_frac); TRAIN only",
        "proposed_thr_top1": thr_top1,
        "proposed_thr_0.9_reference": 0.9,
        "product_thr_0.99": 0.99,
    }

    meta = {
        "kind": "q5b_path_a_candidate_wf_artifact",
        "recipe_doc": RECIPE_DOC,
        "go_criterion_doc": GO_DOC,
        "profile": profile,
        "recipe": "pump_path_a_candidate_v1",
        "t0_policy": "pump_mc_band_from_trades_v1",
        "t0_definition": "pump_mc_band_sighting_v1",
        "stamp": args.stamp,
        "generated_at": utcnow(),
        "dune_api_calls": 0,
        "overwrote_q5b_last": False,
        "overwrote_q5b_calibration": False,
        "apply_dune_helius_usd_scale": False,
        "lite": False,
        "features_path": str(feat_path),
        "build_entry": BUILD_ENTRY,
        "set_name": "+q5b",
        "label": label_col,
        "n_features": len(cols),
        "feature_names": cols,
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "test_n": int(len(te)),
        "n_matrix_rows_used": int(len(df)),
        "n_pos": int((df[label_col] == 1).sum()),
        "filter_n_before": n_before,
        "min_pre_t0_trades": args.min_pre_t0_trades,
    }

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # Final refuse gate immediately before write
    for label, path in (("--out", out_joblib), ("calibration", out_calib)):
        code = refuse_if_q5b_last(path, label=label)
        if code is not None:
            return code

    q5b_last_md5_before = (
        hashlib.md5(Q5B_LAST.read_bytes()).hexdigest() if Q5B_LAST.is_file() else None
    )

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
        "recipe_doc": RECIPE_DOC,
        "go_criterion_doc": GO_DOC,
        "profile": profile,
        "t0_policy": meta["t0_policy"],
        "fold": last.get("fold"),
        "train_n": int(len(tr)),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "generated_at": utcnow(),
        "rule": calibration["rule"],
        "why": (
            "Path A candidate export only. NOT a live swap without Sinck GO + "
            f"{GO_DOC} PASS."
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
            "median": float(np.median(test_proba)),
            "max": float(test_proba.max()),
            "base_rate": float(yte.mean()),
            "absurd_oos": absurd_oos,
        },
        "baseline_q5b_last_same_oos": baseline,
        "live_journal_rescore": live_rescore,
        "go_nogo": go,
        "go_reason": go_reason,
    }
    out_calib.write_text(json.dumps(jsonable(calib_doc), indent=2) + "\n")

    metrics_doc = {
        **calib_doc["oos_held_out"],
        "proposed_thr_top1": thr_top1,
        "proposed_thr_top5": thr_top5,
        "live_thr_unchanged": 0.9,
        "product_thr_0.99": 0.99,
        "baseline_q5b_last": baseline,
        "live_journal_rescore": live_rescore,
        "joblib": str(out_joblib),
        "calibration_json": str(out_calib),
        "recipe": meta["recipe"],
        "recipe_doc": RECIPE_DOC,
        "go_criterion_doc": GO_DOC,
        "profile": profile,
        "features_path": str(feat_path),
        "n_matrix_rows_used": int(len(df)),
        "n_pos": int((df[label_col] == 1).sum()),
        "dune_api_calls": 0,
        "generated_at": utcnow(),
        "metrics_for_scores": jsonable(oos_m),
        "go_nogo": go,
        "go_reason": go_reason,
        "q5b_last_md5_before": q5b_last_md5_before,
        "q5b_last_md5_after": hashlib.md5(Q5B_LAST.read_bytes()).hexdigest()
        if Q5B_LAST.is_file()
        else None,
    }
    out_metrics.parent.mkdir(parents=True, exist_ok=True)
    out_metrics.write_text(json.dumps(jsonable(metrics_doc), indent=2) + "\n")

    assert Q5B_LAST.is_file()
    assert metrics_doc["q5b_last_md5_before"] == metrics_doc["q5b_last_md5_after"]
    assert out_joblib.resolve() != Q5B_LAST.resolve()
    assert out_calib.resolve() != Q5B_CALIB.resolve()

    print(
        json.dumps(
            {
                "status": "ok",
                "joblib": str(out_joblib),
                "calibration": str(out_calib),
                "metrics": str(out_metrics),
                "n": int(len(df)),
                "n_pos": int((df[label_col] == 1).sum()),
                "oos_auc": auc,
                "oos_ap": ap,
                "oos_frac_ge_0.9": frac_ge_09,
                "oos_median": float(np.median(test_proba)),
                "oos_max": float(test_proba.max()),
                "absurd_oos": absurd_oos,
                "live_rescore": live_rescore,
                "q5b_last_untouched": True,
                "dune_api_calls": 0,
                "go_nogo": go,
                "go_reason": go_reason,
                "profile": profile,
                "recipe": RECIPE_DOC,
                "go_criterion": GO_DOC,
            },
            indent=2,
        )
    )
    return 0


def _run_twin(args: argparse.Namespace, out_joblib: Path, out_calib: Path, out_metrics: Path) -> int:
    """Historical store-twin profile under candidate export naming."""
    from features.post_q5_sets import resolve_label_column

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    if not feat_path.is_file() or not lab_path.is_file():
        print(json.dumps({"status": "missing_features", "path": str(feat_path)}))
        return 1

    code = refuse_if_q5b_last(out_joblib, label="--out")
    if code is not None:
        return code

    feat = pd.read_csv(feat_path)
    lab = pd.read_csv(lab_path)
    label_col, _ = resolve_label_column(lab.columns)
    cols = [c for c in FEATURE_SETS["+q5b"] if c in feat.columns]
    merge_cols = ["mint", label_col]
    if "hit_200k" in lab.columns:
        merge_cols.append("hit_200k")
    df = feat.merge(lab[merge_cols], on="mint", how="inner", validate="one_to_one")
    if "creator_prior_mints_all_in_window" in df.columns:
        df["creator_prior_mints_all_in_window"] = np.nan
    if "hit_200k" not in df.columns:
        df["hit_200k"] = df[label_col]
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.sort_values("t0", kind="mergesort").reset_index(drop=True)

    folds = make_expanding_folds(df)
    last = folds[-1]
    tr = last["train_idx"]
    te = last["test_idx"]
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
    try:
        auc = float(roc_auc_score(yte, test_proba))
    except ValueError:
        auc = None
    try:
        ap = float(average_precision_score(yte, test_proba))
    except ValueError:
        ap = None

    q5b_last_md5_before = (
        hashlib.md5(Q5B_LAST.read_bytes()).hexdigest() if Q5B_LAST.is_file() else None
    )
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    code = refuse_if_q5b_last(out_joblib, label="--out")
    if code is not None:
        return code

    meta = {
        "kind": "q5b_path_a_candidate_wf_artifact",
        "profile": "twin",
        "recipe": "train_on_store_with_Pump_path_column_set",
        "recipe_doc": RECIPE_DOC,
        "go_criterion_doc": GO_DOC,
        "note": "Historical twin under candidate export name; default NO-GO for paper swap",
        "stamp": args.stamp,
        "generated_at": utcnow(),
        "dune_api_calls": 0,
        "overwrote_q5b_last": False,
        "apply_dune_helius_usd_scale": False,
    }
    joblib.dump(
        {
            "pipeline": pipe,
            "feature_names": cols,
            "set_name": "+q5b",
            "label": label_col,
            "train_n": int(len(tr)),
            "fold": last.get("fold"),
            "train_t0_max": str(df.loc[tr, "t0"].max()),
            "calibration": {
                "train_top_frac_thresholds": {"0.01": thr_top1, "0.05": thr_top5},
            },
            "meta": meta,
        },
        out_joblib,
    )
    calib_doc = {
        "kind": "paper_live_train_quantile_calibration",
        "model_path": out_joblib.name,
        "profile": "twin",
        "recipe_doc": RECIPE_DOC,
        "go_criterion_doc": GO_DOC,
        "go_nogo": "NO-GO",
        "go_reason": "twin_store_not_path_a_hermes_default",
        "generated_at": utcnow(),
        "oos_held_out": {
            "n": int(len(te)),
            "auc": auc,
            "ap": ap,
            "frac_ge_0.9": float((test_proba >= 0.9).mean()),
            "median": float(np.median(test_proba)),
            "max": float(test_proba.max()),
        },
    }
    out_calib.write_text(json.dumps(jsonable(calib_doc), indent=2) + "\n")
    metrics_doc = {
        **calib_doc["oos_held_out"],
        "joblib": str(out_joblib),
        "profile": "twin",
        "q5b_last_md5_before": q5b_last_md5_before,
        "q5b_last_md5_after": hashlib.md5(Q5B_LAST.read_bytes()).hexdigest()
        if Q5B_LAST.is_file()
        else None,
        "go_nogo": "NO-GO",
        "generated_at": utcnow(),
    }
    out_metrics.parent.mkdir(parents=True, exist_ok=True)
    out_metrics.write_text(json.dumps(jsonable(metrics_doc), indent=2) + "\n")
    print(json.dumps({"status": "ok", "profile": "twin", "joblib": str(out_joblib), **metrics_doc}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
