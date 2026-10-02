#!/usr/bin/env python3
"""Offline audit: null Q5a/buy60 like live Pump gap → HistGB score behavior (no Dune).

Reads local expand features + q5b_last.joblib. Does not overwrite models.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

Q5A_LIKE = [
    "buy_vol_usd_60s",
    "sniper_vol_share_5s",
    "top1_buyer_vol_share",
    "top5_buyer_vol_share",
    "buy_vol_usd_total",
    "buy_count_total",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-rows", type=int, default=5000)
    ap.add_argument(
        "-o",
        type=Path,
        default=ROOT / "cycle0/artifacts/pump_feature_mask_audit_20261002.json",
    )
    args = ap.parse_args()
    import pandas as pd
    import joblib
    from features.post_q5_sets import FEATURE_SETS

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    model_path = ROOT / "data/paper_live/models/q5b_last.joblib"
    if not feat_path.is_file() or not model_path.is_file():
        print("missing features or model")
        return 1
    cols = list(FEATURE_SETS["+q5b"])
    df = pd.read_csv(feat_path, usecols=lambda c: c in set(cols) | {"mint", "t0_ts"})
    df = df.tail(args.max_rows).reset_index(drop=True)
    blob = joblib.load(model_path)
    pipe = blob["pipeline"]
    names = list(blob["feature_names"])
    # baseline
    X = df.reindex(columns=names)
    proba = pipe.predict_proba(X.to_numpy(dtype=float))[:, 1]
    # masked: null Q5a/buy60 cols present in names
    Xm = X.copy()
    masked = [c for c in Q5A_LIKE if c in Xm.columns]
    for c in masked:
        Xm[c] = np.nan
    proba_m = pipe.predict_proba(Xm.to_numpy(dtype=float))[:, 1]
    out = {
        "n": int(len(df)),
        "masked_cols": masked,
        "baseline_score": {
            "median": float(np.median(proba)),
            "p95": float(np.quantile(proba, 0.95)),
            "frac_ge_0.9": float((proba >= 0.9).mean()),
        },
        "masked_score": {
            "median": float(np.median(proba_m)),
            "p95": float(np.quantile(proba_m, 0.95)),
            "frac_ge_0.9": float((proba_m >= 0.9).mean()),
        },
        "mean_abs_delta": float(np.mean(np.abs(proba - proba_m))),
        "dune_calls": 0,
        "note": "Imputer fills NaN — live Path A currently SKIPS on missing buy_vol (stricter than this audit).",
    }
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
