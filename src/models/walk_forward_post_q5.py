"""Post-Q5 walk-forward pipeline (scaffold + optional train).

BOSS 2026-09-30: prepare sets buy60 | buy60+q5a | q5a_only | +q5b | full;
metrics top 1%/5%; slot for hit_10x_30d when present.
Default: --dry-run (no train) until Q5 merge complete; BOSS runs full WF then.

Usage:
  .venv/bin/python -m models.walk_forward_post_q5 --dry-run
  .venv/bin/python -m models.walk_forward_post_q5 --train --require-complete
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
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import (  # noqa: E402
    DROP_FROM_X,
    FEATURE_SETS,
    JOIN_ONLY,
    PRIMARY_LABEL,
    PROXY_LABEL,
    SET_ORDER,
    assert_sets_safe,
    resolve_label_column,
)
from models.walk_forward_expand_v2 import (  # noqa: E402
    make_expanding_folds,
    metrics_for_scores,
)

FEATURES_EXPAND = ROOT / "data/samples/features_dune_p0_flow_expand_v2.csv"
LABELS_PATH = ROOT / "data/samples/labels_dune_expand_v2.csv"
Q5A_PATH = ROOT / "data/samples/dune_q5a_features.csv"
Q5B_PATH = ROOT / "data/samples/dune_q5b_features.csv"
JOINED_OUT = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
MANIFEST_JSON = ROOT / "data/samples/wf_post_q5_sets_manifest.json"
REPORT_JSON = ROOT / "data/samples/wf_post_q5_report.json"
REPORT_MD = ROOT / "data/samples/wf_post_q5_report.md"
PREDS_PATH = ROOT / "data/samples/wf_post_q5_oos_predictions.csv"

# Completeness: Q5 coverage vs expand n (allow tiny float slack)
COMPLETE_FRAC = 0.995
TOP_FRACS = (0.01, 0.05)


def _utcnow() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _norm_t0(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, utc=True, errors="coerce")


def coverage(expand_n: int, q5_n: int) -> dict[str, Any]:
    return {
        "expand_n": expand_n,
        "q5_n": q5_n,
        "frac": float(q5_n / expand_n) if expand_n else 0.0,
        "complete": bool(q5_n >= COMPLETE_FRAC * expand_n),
    }


def load_expand_labels() -> tuple[pd.DataFrame, pd.DataFrame]:
    feat = pd.read_csv(FEATURES_EXPAND)
    lab = pd.read_csv(LABELS_PATH)
    return feat, lab


def merge_q5(
    expand: pd.DataFrame,
    q5a: pd.DataFrame | None,
    q5b: pd.DataFrame | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Left-join Q5 packs on mint; QA t0 when both sides have it."""
    df = expand.copy()
    df["_t0_expand"] = _norm_t0(df["t0_ts"])
    meta: dict[str, Any] = {"join_key": "mint", "t0_mismatch_dropped": 0}

    def _join(pack: pd.DataFrame, prefix: str) -> pd.DataFrame:
        p = pack.copy()
        # Drop join-only that would collide after rename — keep mint; strip creator from X later
        drop_from_pack = [c for c in ("feature_set_version",) if c in p.columns]
        p = p.drop(columns=drop_from_pack, errors="ignore")
        if "t0_ts" in p.columns:
            p["_t0_pack"] = _norm_t0(p["t0_ts"])
            p = p.drop(columns=["t0_ts"])
        before = len(df)
        merged = df.merge(p, on="mint", how="left", validate="one_to_one")
        if "_t0_pack" in merged.columns:
            # Allow ≤2s clock skew; else null out pack cols for mismatched rows
            mismatch = merged["_t0_pack"].notna() & (
                (merged["_t0_expand"] - merged["_t0_pack"]).abs() > pd.Timedelta(seconds=2)
            )
            n_bad = int(mismatch.sum())
            meta["t0_mismatch_dropped"] += n_bad
            if n_bad:
                pack_cols = [c for c in p.columns if c not in ("mint", "_t0_pack")]
                merged.loc[mismatch, pack_cols] = np.nan
            merged = merged.drop(columns=["_t0_pack"])
        assert len(merged) == before
        meta[f"{prefix}_cols_joined"] = [c for c in p.columns if c != "mint"]
        return merged

    nonlocal_df = df
    if q5a is not None:
        nonlocal_df = _join(q5a, "q5a")
        df = nonlocal_df
    if q5b is not None:
        df = _join(q5b, "q5b")

    # Hard ban on train leakage ids in matrix later; drop from convenience view optional
    meta["creator_pubkey_present"] = "creator_pubkey" in df.columns
    return df, meta


def available_cols(df: pd.DataFrame, wanted: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(c for c in wanted if c in df.columns)


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


def dry_run_manifest() -> dict[str, Any]:
    assert_sets_safe()
    expand, lab = load_expand_labels()
    expand_n = len(expand)
    q5a = pd.read_csv(Q5A_PATH) if Q5A_PATH.exists() else None
    q5b = pd.read_csv(Q5B_PATH) if Q5B_PATH.exists() else None
    cov_a = coverage(expand_n, 0 if q5a is None else q5a["mint"].nunique())
    cov_b = coverage(expand_n, 0 if q5b is None else q5b["mint"].nunique())

    label_cols = list(lab.columns)
    # Slot: if PRIMARY appears later in labels file, resolve_label_column picks it
    try:
        label_col, is_primary = resolve_label_column(label_cols)
    except KeyError:
        label_col, is_primary = PROXY_LABEL, False

    joined, merge_meta = merge_q5(expand, q5a, q5b)
    # Attach label for schema check only (not written into feature store by default)
    if "mint" in lab.columns and label_col in lab.columns:
        # labels_dune_expand_v2 is mint-keyed (no t0)
        overlap = set(joined.columns) & set(lab.columns) - {"mint"}
        if overlap:
            raise AssertionError(f"feature/label overlap: {sorted(overlap)}")

    sets_info = {}
    for name in SET_ORDER:
        wanted = FEATURE_SETS[name]
        have = available_cols(joined, wanted)
        missing = [c for c in wanted if c not in have]
        sets_info[name] = {
            "n_wanted": len(wanted),
            "n_available": len(have),
            "missing": missing,
            "ready": len(missing) == 0 and (
                (name in ("buy60",) and True)
                or (name in ("buy60+q5a", "q5a_only") and cov_a["complete"])
                or (name in ("+q5b", "full") and cov_a["complete"] and cov_b["complete"])
            ),
            "columns": list(have) if len(missing) == 0 else list(have),
            "columns_wanted": list(wanted),
        }

    # buy60 alone always ready from expand
    sets_info["buy60"]["ready"] = "buy_vol_usd_60s" in joined.columns

    manifest = {
        "kind": "wf_post_q5_sets_manifest",
        "generated_at": _utcnow(),
        "paths": {
            "expand_features": str(FEATURES_EXPAND.relative_to(ROOT)),
            "labels": str(LABELS_PATH.relative_to(ROOT)),
            "q5a": str(Q5A_PATH.relative_to(ROOT)) if Q5A_PATH.exists() else None,
            "q5b": str(Q5B_PATH.relative_to(ROOT)) if Q5B_PATH.exists() else None,
            "joined_target": str(JOINED_OUT.relative_to(ROOT)),
            "report_json": str(REPORT_JSON.relative_to(ROOT)),
        },
        "label": {
            "active": label_col,
            "is_primary": is_primary,
            "primary_slot": PRIMARY_LABEL,
            "proxy": PROXY_LABEL,
            "note": (
                "PRIMARY hit_10x_30d not in labels yet — using hit_200k proxy"
                if not is_primary
                else "using PRIMARY hit_10x_30d"
            ),
        },
        "coverage": {"q5a": cov_a, "q5b": cov_b, "complete_frac_threshold": COMPLETE_FRAC},
        "merge": merge_meta,
        "metrics_planned": {
            "auc": True,
            "ap": True,
            "precision_at_top_1pct": True,
            "precision_at_top_5pct": True,
            "top_fracs": list(TOP_FRACS),
        },
        "banned_from_X": sorted(JOIN_ONLY | DROP_FROM_X | {PRIMARY_LABEL, PROXY_LABEL, "max_mc_after_t0", "label_primary_hint"}),
        "feature_sets": sets_info,
        "train_gate": {
            "require_q5_complete_for_q5_sets": True,
            "default_mode": "dry-run until BOSS merge+WF when Q5 closes",
        },
        "set_order": list(SET_ORDER),
    }
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def run_train(*, require_complete: bool) -> dict[str, Any]:
    """Full multi-set WF; refuses Q5 sets if coverage incomplete unless require_complete=False."""
    manifest = dry_run_manifest()
    expand, lab = load_expand_labels()
    q5a = pd.read_csv(Q5A_PATH) if Q5A_PATH.exists() else None
    q5b = pd.read_csv(Q5B_PATH) if Q5B_PATH.exists() else None
    joined, _ = merge_q5(expand, q5a, q5b)
    label_col, is_primary = resolve_label_column(lab.columns)
    if set(joined.columns) & set(lab.columns) - {"mint"}:
        raise AssertionError("overlap")
    df = joined.merge(lab[["mint", label_col]], on="mint", how="inner", validate="one_to_one")
    df["t0"] = _norm_t0(df["t0_ts"])
    df = df.sort_values("t0", kind="mergesort").reset_index(drop=True)
    df[label_col] = df[label_col].astype(int)

    # Persist joined features (without labels) for BOSS/SolQA
    feat_out_cols = [c for c in joined.columns if c not in ("_t0_expand",)]
    joined[feat_out_cols].to_csv(JOINED_OUT, index=False)

    # Monkey-patch LABEL_COL usage: make_expanding_folds expects LABEL_COL global from expand_v2
    # We pass a frame that has the active label under a temp name matching expand helper.
    from models import walk_forward_expand_v2 as wf

    old_label = wf.LABEL_COL
    wf.LABEL_COL = label_col
    try:
        folds = make_expanding_folds(df)
    finally:
        wf.LABEL_COL = old_label

    results: dict[str, Any] = {
        "kind": "wf_post_q5_report",
        "generated_at": _utcnow(),
        "label": label_col,
        "is_primary": is_primary,
        "label_caveat": (
            None
            if is_primary
            else "hit_200k proxy — NOT full hit_10x_30d"
        ),
        "n_rows": len(df),
        "folds": [
            {
                "fold": f["fold"],
                "train_n": f["train_n"],
                "test_n": f["test_n"],
                "train_t0_max": f["train_t0_max"],
                "test_t0_min": f["test_t0_min"],
            }
            for f in folds
        ],
        "sets": {},
        "paths": {
            "joined": str(JOINED_OUT.relative_to(ROOT)),
            "preds": str(PREDS_PATH.relative_to(ROOT)),
            "manifest": str(MANIFEST_JSON.relative_to(ROOT)),
        },
    }

    pred_frames: list[pd.DataFrame] = []
    for set_name in SET_ORDER:
        info = manifest["feature_sets"][set_name]
        cols = available_cols(df, FEATURE_SETS[set_name])
        if require_complete and not info["ready"] and set_name != "buy60":
            results["sets"][set_name] = {
                "skipped": True,
                "reason": "q5_incomplete_or_missing_cols",
                "missing": info["missing"],
                "coverage": manifest["coverage"],
            }
            continue
        if not cols:
            results["sets"][set_name] = {"skipped": True, "reason": "no_columns"}
            continue
        if "creator_pubkey" in cols:
            raise AssertionError("creator_pubkey leaked into X")
        if set(cols) & DROP_FROM_X:
            raise AssertionError(f"DROP_FROM_X leaked into X: {set(cols) & DROP_FROM_X}")

        oos_scores = np.full(len(df), np.nan)
        fold_metrics = []
        for f in folds:
            tr, te = f["train_idx"], f["test_idx"]
            Xtr = df.loc[tr, list(cols)].to_numpy(dtype=float)
            Xte = df.loc[te, list(cols)].to_numpy(dtype=float)
            ytr = df.loc[tr, label_col].to_numpy()
            yte = df.loc[te, label_col].to_numpy()
            model = clone(build_hist_gb())
            model.fit(Xtr, ytr)
            scores = model.predict_proba(Xte)[:, 1]
            oos_scores[te] = scores
            m = metrics_for_scores(yte, scores)
            # Explicit top 1%/5%
            for frac in TOP_FRACS:
                k = max(1, int(round(frac * len(yte))))
                from models.walk_forward_expand_v2 import precision_at_k, recall_at_k

                m[f"precision_at_top_{frac:.0%}"] = precision_at_k(yte, scores, k)
                m[f"recall_at_top_{frac:.0%}"] = recall_at_k(yte, scores, k)
            fold_metrics.append({"fold": f["fold"], **m})

        mask = ~np.isnan(oos_scores)
        overall = metrics_for_scores(
            df.loc[mask, label_col].to_numpy(), oos_scores[mask]
        )
        results["sets"][set_name] = {
            "skipped": False,
            "n_features": len(cols),
            "feature_columns": list(cols),
            "overall_oos": overall,
            "folds": fold_metrics,
        }
        pred_frames.append(
            pd.DataFrame(
                {
                    "mint": df.loc[mask, "mint"].to_numpy(),
                    "t0_ts": df.loc[mask, "t0_ts"].to_numpy(),
                    "set": set_name,
                    "y": df.loc[mask, label_col].to_numpy(),
                    "score": oos_scores[mask],
                }
            )
        )

    if pred_frames:
        pd.concat(pred_frames, ignore_index=True).to_csv(PREDS_PATH, index=False)
    REPORT_JSON.write_text(json.dumps(results, indent=2) + "\n")
    _write_md(results)
    return results


def _write_md(results: dict[str, Any]) -> None:
    lines = [
        "# Walk-forward post-Q5 report",
        "",
        f"- Generated: `{results['generated_at']}`",
        f"- Label: `{results['label']}`"
        + (f" — **{results['label_caveat']}**" if results.get("label_caveat") else ""),
        f"- Rows: {results['n_rows']}",
        "",
        "## Sets (OOS pooled)",
        "",
        "| set | n_feat | AUC | AP | P@top1% | P@top5% | status |",
        "|-----|--------|-----|----|---------|---------|--------|",
    ]
    for name in SET_ORDER:
        s = results["sets"].get(name, {})
        if s.get("skipped"):
            lines.append(
                f"| `{name}` | — | — | — | — | — | skipped: {s.get('reason')} |"
            )
            continue
        o = s["overall_oos"]
        lines.append(
            "| `{name}` | {nf} | {auc:.4f} | {ap:.4f} | {p1} | {p5} | ok |".format(
                name=name,
                nf=s["n_features"],
                auc=o.get("auc") or float("nan"),
                ap=o.get("ap") or float("nan"),
                p1=o.get("precision_at_top_1%"),
                p5=o.get("precision_at_top_5%"),
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- `creator_pubkey` never in X (join only).",
            "- Train gate: Q5 sets skipped until coverage ≥ 99.5% unless forced.",
            "- When `hit_10x_30d` lands in labels, re-run; PRIMARY auto-selected.",
            "",
        ]
    )
    REPORT_MD.write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", default=False)
    p.add_argument("--train", action="store_true", default=False)
    p.add_argument(
        "--require-complete",
        action="store_true",
        default=True,
        help="Skip Q5 sets until Q5a/Q5b coverage complete (default on with --train)",
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help="Train Q5 sets even if coverage incomplete (debug only)",
    )
    args = p.parse_args(argv)
    if args.train:
        req = not args.allow_partial
        run_train(require_complete=req)
        print(f"wrote {REPORT_JSON}")
        return 0
    # default dry-run
    man = dry_run_manifest()
    print(json.dumps({
        "wrote": str(MANIFEST_JSON),
        "label": man["label"],
        "coverage": man["coverage"],
        "sets_ready": {k: v["ready"] for k, v in man["feature_sets"].items()},
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
