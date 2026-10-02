"""Re-score replay features with live joblib — train recipe parity.

Use after SolDatos fixes (oracle USD, Helius pagination ≤T0, exact T0):

  PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay \\
    --features-csv path/to/rebuild_features.csv \\
    --compare-oos data/samples/wf_post_q5_oos_predictions.csv

Without --features-csv: rescores train store rows for sample_mints (sanity = Δ≈0).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from features.post_q5_sets import FEATURE_SETS
from paper_live.config import MODEL_Q5B_PATH, ROOT
from paper_live.recipe_parity import (
    LIVE_SCORE_SET,
    TRAIN_RECIPE_COLS,
    assert_recipe_matches_joblib,
    vector_for_score,
)
from paper_live.score import PaperScorer

DEFAULT_SAMPLE = ROOT / "cycle0/artifacts/sample_mints.csv"
DEFAULT_OOS = ROOT / "data/samples/wf_post_q5_oos_predictions.csv"
DEFAULT_STORE = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
OUT_DIR = ROOT / "cycle0/artifacts"


def _utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _score_frame(df: pd.DataFrame, *, feature_names: list[str]) -> pd.Series:
    scorer = PaperScorer(mode="histgb_q5b")
    if scorer._model is None:
        raise FileNotFoundError(f"no model at {MODEL_Q5B_PATH}")
    # Prefer joblib names (must match recipe)
    names = scorer._feature_names or feature_names
    scores = []
    for _, row in df.iterrows():
        feats = {c: (None if pd.isna(row.get(c)) else row.get(c)) for c in names}
        # also pass through any extras for completeness checks
        for c in df.columns:
            if c not in feats:
                v = row.get(c)
                feats[c] = None if (isinstance(v, float) and np.isnan(v)) or pd.isna(v) else v
        res = scorer.score(feats)
        scores.append(float("nan") if res.skipped else res.score)
    return pd.Series(scores, index=df.index, name="rescore")


def load_oos_q5b(path: Path) -> pd.DataFrame:
    oos = pd.read_csv(path)
    if "set" in oos.columns:
        oos = oos[oos["set"] == "+q5b"].copy()
    return oos


def run(
    *,
    features_csv: Path | None,
    sample_csv: Path,
    oos_csv: Path,
    store_csv: Path,
    out_prefix: str,
) -> dict[str, Any]:
    parity = assert_recipe_matches_joblib()
    if not parity.ok:
        raise AssertionError(parity.detail)

    sample = pd.read_csv(sample_csv)
    mint_col = "mint" if "mint" in sample.columns else sample.columns[0]
    mints = set(sample[mint_col].astype(str))

    oos = load_oos_q5b(oos_csv)
    oos_by = oos.drop_duplicates("mint").set_index("mint")

    if features_csv is not None:
        feat = pd.read_csv(features_csv)
        source = str(features_csv)
        mode = "rebuild"
    else:
        feat = pd.read_csv(store_csv)
        source = str(store_csv)
        mode = "train_store_sanity"

    feat = feat[feat["mint"].astype(str).isin(mints)].copy()
    missing_cols = [c for c in TRAIN_RECIPE_COLS if c not in feat.columns]
    if missing_cols:
        raise KeyError(f"features missing recipe cols: {missing_cols[:10]}… ({len(missing_cols)})")

    scores = _score_frame(feat, feature_names=list(TRAIN_RECIPE_COLS))
    feat = feat.reset_index(drop=True)
    feat["rescore"] = scores.values

    rows = []
    for _, r in feat.iterrows():
        mint = str(r["mint"])
        oos_score = float(oos_by.loc[mint, "score"]) if mint in oos_by.index else float("nan")
        # column name variants
        if mint in oos_by.index and "score" not in oos_by.columns:
            for cand in ("oos_score", "pred", "y_score"):
                if cand in oos_by.columns:
                    oos_score = float(oos_by.loc[mint, cand])
                    break
        rows.append(
            {
                "mint": mint,
                "t0_ts": r.get("t0_ts"),
                "oos_score": oos_score,
                "rescore": float(r["rescore"]) if pd.notna(r["rescore"]) else None,
                "delta_oos_minus_rescore": (
                    (oos_score - float(r["rescore"]))
                    if pd.notna(r["rescore"]) and oos_score == oos_score
                    else None
                ),
                "buy_vol_usd_60s": r.get("buy_vol_usd_60s"),
                "n_recipe_cols_present": int(
                    sum(1 for c in TRAIN_RECIPE_COLS if c in r.index and pd.notna(r.get(c)))
                ),
            }
        )
    out_df = pd.DataFrame(rows)
    deltas = out_df["delta_oos_minus_rescore"].dropna()
    high = out_df[out_df["oos_score"] >= 0.99] if out_df["oos_score"].notna().any() else out_df.iloc[0:0]

    report = {
        "kind": "live_train_rescore_replay",
        "generated_at": _utcnow(),
        "mode": mode,
        "features_source": source,
        "recipe_set": LIVE_SCORE_SET,
        "n_recipe_cols": len(TRAIN_RECIPE_COLS),
        "parity": parity.as_dict(),
        "n_scored": int(len(out_df)),
        "n_high_oos_ge_0.99": int(len(high)),
        "delta_abs_median": float(deltas.abs().median()) if len(deltas) else None,
        "delta_abs_max": float(deltas.abs().max()) if len(deltas) else None,
        "high_pct_rescore_ge_0.99": (
            float((high["rescore"] >= 0.99).mean()) if len(high) and high["rescore"].notna().any() else None
        ),
        "high_pct_rescore_ge_0.89": (
            float((high["rescore"] >= 0.89).mean()) if len(high) and high["rescore"].notna().any() else None
        ),
        "note": (
            "train_store_sanity expects Δ≈0 on fold-5 OOS mints; "
            "rebuild mode expects Δ shrink after SolDatos USD/pagination/T0 fixes"
        ),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"{out_prefix}.csv"
    json_path = OUT_DIR / f"{out_prefix}_report.json"
    out_df.to_csv(csv_path, index=False)
    report["paths"] = {"csv": str(csv_path.relative_to(ROOT)), "report": str(json_path.relative_to(ROOT))}
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def run_journal(
    *,
    journal_path: Path | None = None,
    limit: int = 200,
    since: str | None = None,
    score_mode: str = "histgb_q5b",
    out_prefix: str = "live_journal_rescore",
) -> dict[str, Any]:
    """Re-score sightings.features_json through q5b_last.joblib; compare to journal score.

    Bypasses PaperScorer live gates so Δ isolates recipe/X fidelity (Δ≈0 expected).
    """
    import sqlite3

    from paper_live.config import SQLITE_PATH
    from paper_live.features_t0 import feature_vector_for_set, required_q5b_present

    parity = assert_recipe_matches_joblib()
    if not parity.ok:
        raise AssertionError(parity.detail)

    db = journal_path or SQLITE_PATH
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    q = "SELECT mint, t0_ts, created_at, score, score_mode, features_json FROM sightings WHERE score_mode=?"
    params: list[Any] = [score_mode]
    if since:
        q += " AND created_at >= ?"
        params.append(since)
    q += " ORDER BY created_at DESC LIMIT ?"
    params.append(int(limit))
    rows = con.execute(q, params).fetchall()

    scorer = PaperScorer(mode="histgb_q5b")
    if scorer._model is None:
        raise FileNotFoundError(f"no model at {MODEL_Q5B_PATH}")
    names = scorer._feature_names or list(TRAIN_RECIPE_COLS)

    out_rows = []
    for r in rows:
        feats = json.loads(r["features_json"]) if r["features_json"] else {}
        journal_score = float(r["score"]) if r["score"] is not None else float("nan")
        prior = feats.get("creator_prior_source")
        prior_s = "<ABSENT>" if prior is None else str(prior)
        complete = required_q5b_present(feats)
        rec: dict[str, Any] = {
            "mint": r["mint"],
            "created_at": r["created_at"],
            "t0_ts": r["t0_ts"],
            "journal_score": journal_score if journal_score == journal_score else None,
            "rescore": None,
            "delta_journal_minus_rescore": None,
            "abs_delta": None,
            "complete_x": complete,
            "creator_prior_source": prior_s,
            "sol_usd_source": feats.get("sol_usd_source"),
            "n_recipe_nonnull": int(sum(1 for c in TRAIN_RECIPE_COLS if feats.get(c) is not None)),
        }
        if not complete:
            out_rows.append(rec)
            continue
        vec = feature_vector_for_set(feats, "+q5b")
        row = np.array([[(np.nan if vec.get(n) is None else vec.get(n)) for n in names]], dtype=float)
        proba = float(scorer._model.predict_proba(row)[0, 1])
        rec["rescore"] = proba
        if journal_score == journal_score:
            d = journal_score - proba
            rec["delta_journal_minus_rescore"] = d
            rec["abs_delta"] = abs(d)
        out_rows.append(rec)

    out_df = pd.DataFrame(out_rows)
    scored = out_df[out_df["rescore"].notna()]
    deltas = scored["abs_delta"].dropna()
    prior_dist = out_df["creator_prior_source"].value_counts().to_dict() if len(out_df) else {}

    report: dict[str, Any] = {
        "kind": "live_journal_rescore",
        "generated_at": _utcnow(),
        "journal": str(db),
        "score_mode": score_mode,
        "since": since,
        "limit": limit,
        "parity": parity.as_dict(),
        "n_rows": int(len(out_df)),
        "n_rescored": int(len(scored)),
        "n_incomplete": int((~out_df["complete_x"]).sum()) if len(out_df) else 0,
        "max_abs_delta": float(deltas.max()) if len(deltas) else None,
        "p50_abs_delta": float(deltas.median()) if len(deltas) else None,
        "p95_abs_delta": float(deltas.quantile(0.95)) if len(deltas) else None,
        "n_abs_delta_gt_1e-6": int((deltas > 1e-6).sum()) if len(deltas) else 0,
        "n_abs_delta_gt_1e-4": int((deltas > 1e-4).sum()) if len(deltas) else 0,
        "prior_source_dist": prior_dist,
        "note": "Δ≈0 means journal X + joblib recipe path OK; does not validate enrich/gates",
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_DIR / f"{out_prefix}.csv"
    json_path = OUT_DIR / f"{out_prefix}_report.json"
    out_df.to_csv(csv_path, index=False)
    report["paths"] = {"csv": str(csv_path.relative_to(ROOT)), "report": str(json_path.relative_to(ROOT))}
    # slim parity for json
    report["parity"] = {k: report["parity"][k] for k in ("ok", "detail", "n_recipe", "n_joblib", "order_match")}
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--features-csv", type=Path, default=None, help="Rebuild ≤T0 features (full +q5b cols)")
    p.add_argument("--sample-csv", type=Path, default=DEFAULT_SAMPLE)
    p.add_argument("--oos-csv", type=Path, default=DEFAULT_OOS)
    p.add_argument("--store-csv", type=Path, default=DEFAULT_STORE)
    p.add_argument("--out-prefix", default="rescore_replay")
    p.add_argument("--journal", action="store_true", help="Rescore paper_journal histgb_q5b features_json")
    p.add_argument("--journal-path", type=Path, default=None)
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--since", type=str, default=None, help="ISO created_at lower bound (journal mode)")
    p.add_argument("--score-mode", default="histgb_q5b")
    args = p.parse_args(argv)
    if args.journal:
        report = run_journal(
            journal_path=args.journal_path,
            limit=args.limit,
            since=args.since,
            score_mode=args.score_mode,
            out_prefix=args.out_prefix if args.out_prefix != "rescore_replay" else "live_journal_rescore",
        )
        print(json.dumps({k: report[k] for k in report if k != "parity"}, indent=2))
        print("parity", report["parity"]["detail"])
        return 0
    report = run(
        features_csv=args.features_csv,
        sample_csv=args.sample_csv,
        oos_csv=args.oos_csv,
        store_csv=args.store_csv,
        out_prefix=args.out_prefix,
    )
    print(json.dumps({k: report[k] for k in report if k != "parity"}, indent=2))
    print("parity", report["parity"]["detail"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
