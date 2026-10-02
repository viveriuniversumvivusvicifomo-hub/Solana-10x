"""Score hook paper-live v0 — WF parity (buy60 / +q5b HistGB).

Modos
-----
- ``rule_buy60``: score = buy_vol_usd_60s. Missing → skip.
- ``histgb_buy60``: joblib; cols = FEATURE_SETS['buy60']. Missing buy_vol → skip.
- ``histgb_q5b`` (default): joblib; cols = FEATURE_SETS['+q5b'].
  Missing any required col → skip (no imputer-as-substitute for absent packs).

``allow_q5b_fallback`` is DEBUG-only and off by default.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from features.post_q5_sets import FEATURE_SETS
from paper_live.config import MODEL_BUY60_PATH, MODEL_Q5B_PATH
from paper_live.features_t0 import (
    feature_vector_for_set,
    required_buy60_present,
    required_q5b_present,
)


@dataclass
class ScoreResult:
    score: float
    mode: str
    set_name: str
    detail: str

    @property
    def skipped(self) -> bool:
        return self.score == float("-inf") or self.mode.startswith("skip_")


def _skip(mode: str, set_name: str, detail: str) -> ScoreResult:
    return ScoreResult(score=float("-inf"), mode=mode, set_name=set_name, detail=detail)


def _q5b_partial_score_debug(feats: dict[str, Any]) -> ScoreResult:
    """DEBUG ONLY — not WF-comparable. Gated by allow_q5b_fallback."""
    name_len = float(feats.get("name_len") or 0.0)
    sym_len = float(feats.get("symbol_len") or 0.0)
    missing = float(feats.get("name_missing") or 0.0) + float(feats.get("symbol_missing") or 0.0)
    score = (name_len + sym_len) - 50.0 * missing
    return ScoreResult(
        score=score,
        mode="rule_q5b_partial_fallback_DEBUG",
        set_name="+q5b",
        detail="DEBUG ONLY — not WF parity; do not trust for live decisions",
    )


class PaperScorer:
    def __init__(
        self,
        mode: str = "histgb_q5b",
        *,
        allow_q5b_fallback: bool = False,
        require_t0_refined: bool = True,
        max_age_s: float = 86_400.0,
        require_pyth_when_key: bool = True,
    ) -> None:
        self.mode = mode
        self.allow_q5b_fallback = allow_q5b_fallback
        self.require_t0_refined = require_t0_refined
        self.max_age_s = float(max_age_s)
        self.require_pyth_when_key = require_pyth_when_key
        self._model = None
        self._feature_names: list[str] = []
        self._loaded_path: Path | None = None
        if mode.startswith("histgb"):
            self._try_load(mode)

    def _try_load(self, mode: str) -> None:
        path = MODEL_Q5B_PATH if "q5b" in mode else MODEL_BUY60_PATH
        if not path.is_file():
            return
        import joblib

        blob = joblib.load(path)
        self._model = blob["pipeline"]
        self._feature_names = list(blob["feature_names"])
        self._loaded_path = path

    def _parity_skip(self, feats: dict[str, Any], set_name: str) -> ScoreResult | None:
        """Path A gates: is_scoreable_capture + age_s_from_create + Pyth + dune priors."""
        # Enrich already ran is_scoreable_capture — honor when present
        if feats.get("capture_scoreable") is False:
            reason = feats.get("score_reject_reason") or "capture_not_scoreable"
            return _skip("skip_capture_not_scoreable", set_name, str(reason))
        if feats.get("age_from_create_ok") is False:
            reason = feats.get("age_from_create_reason") or "age_from_create_failed"
            return _skip("skip_age_anomaly", set_name, str(reason))
        if self.require_t0_refined and feats.get("t0_refined") is False:
            # Path A Pump: capture_scoreable already encodes Pump MC+age gate.
            # Helius C1–C6 refine is optional — do not block when Pump scoreable.
            if feats.get("capture_scoreable") is True and str(
                feats.get("t0_definition") or ""
            ).startswith("pump_mc_band"):
                pass
            else:
                return _skip(
                    "skip_t0_not_refined",
                    set_name,
                    "t0_refined=False — require captura refine before score",
                )
        from ingestion.q5b_age import filter_anomalous_age_features

        _, age_ok, age_reason = filter_anomalous_age_features(
            feats, max_age_s=self.max_age_s
        )
        if feats.get("age_s") is not None and not age_ok:
            return _skip("skip_age_anomaly", set_name, age_reason)
        # Path A Pump MC sighting: frontend usd_market_cap is already USD —
        # do not require sol×pyth (Helius trade-MC path). Helius/hybrid still does.
        t0_def = str(feats.get("t0_definition") or "")
        if t0_def.startswith("pump_mc_band") and feats.get("capture_scoreable") is True:
            return None
        src = str(feats.get("sol_usd_source") or "")
        if src and src not in ("pyth", "pyth_asof", "explicit", "pump_frontend"):
            if feats.get("pyth_scoring_ok") is False or (
                self.require_pyth_when_key
                and __import__("ingestion.sol_usd_oracle", fromlist=["_optional_pyth_key"])._optional_pyth_key()
            ):
                return _skip(
                    "skip_sol_usd_not_pyth",
                    set_name,
                    f"sol_usd_source={src} — Path A Helius path requires pyth_asof",
                )
        return None

    def score(self, feats: dict[str, Any]) -> ScoreResult:
        if self.mode == "rule_buy60":
            if not required_buy60_present(feats):
                if self.allow_q5b_fallback:
                    return _q5b_partial_score_debug(feats)
                return _skip("skip_missing_buy_vol", "buy60", "buy_vol_usd_60s unavailable")
            return self._rule_buy60(feats)

        if self.mode == "histgb_buy60":
            if not required_buy60_present(feats):
                if self.allow_q5b_fallback:
                    return _q5b_partial_score_debug(feats)
                return _skip("skip_missing_buy_vol", "buy60", "buy_vol_usd_60s unavailable")
            if self._model is None:
                return _skip("skip_missing_model", "buy60", f"no joblib at {MODEL_BUY60_PATH.name}")
            return self._histgb(feats, "buy60")

        # histgb_q5b (default trained recipe)
        parity = self._parity_skip(feats, "+q5b")
        if parity is not None:
            return parity
        if not required_q5b_present(feats):
            if self.allow_q5b_fallback:
                return _q5b_partial_score_debug(feats)
            if not required_buy60_present(feats):
                return _skip("skip_missing_buy_vol", "+q5b", "buy_vol_usd_60s unavailable")
            return _skip(
                "skip_incomplete_q5b",
                "+q5b",
                "FEATURE_SETS['+q5b'] incomplete — hold (no substitutes)",
            )
        # Hard gate once recipe complete: prior must be dune_cohort_* (missing = fail)
        from verification.live_parity import prior_source_is_train

        if not prior_source_is_train(feats.get("creator_prior_source")):
            return _skip(
                "skip_prior_not_train",
                "+q5b",
                f"creator_prior_source={feats.get('creator_prior_source')!r} ≠ dune_cohort_* (train)",
            )
        if self._model is None:
            return _skip("skip_missing_model", "+q5b", f"no joblib at {MODEL_Q5B_PATH.name}")
        return self._histgb(feats, "+q5b")

    def _rule_buy60(self, feats: dict[str, Any]) -> ScoreResult:
        bv = feats.get("buy_vol_usd_60s")
        assert bv is not None
        return ScoreResult(
            score=float(bv),
            mode="rule_buy60",
            set_name="buy60",
            detail="score=buy_vol_usd_60s (WF buy60 feature)",
        )

    def _histgb(self, feats: dict[str, Any], set_name: str) -> ScoreResult:
        assert self._model is not None
        vec = feature_vector_for_set(feats, set_name)
        names = self._feature_names or list(FEATURE_SETS[set_name])
        # np.nan for None so SimpleImputer in trained pipeline matches WF
        row = np.array([[(np.nan if vec.get(n) is None else vec.get(n)) for n in names]], dtype=float)
        proba = float(self._model.predict_proba(row)[0, 1])
        return ScoreResult(
            score=proba,
            mode=self.mode,
            set_name=set_name,
            detail=f"histgb:{self._loaded_path.name if self._loaded_path else '?'} cols={len(names)}",
        )


def export_last_fold_model(
    *,
    set_name: str = "+q5b",
    out_path: Path | None = None,
    max_train_rows: int = 80_000,
) -> dict[str, Any]:
    """Entrena HistGB en el último fold expanding y guarda joblib (opcional offline)."""
    import joblib
    import pandas as pd

    from features.post_q5_sets import FEATURE_SETS, PRIMARY_LABEL, resolve_label_column
    from models.walk_forward_expand_v2 import make_expanding_folds
    from models.walk_forward_post_q5 import build_hist_gb
    from paper_live.config import MODEL_BUY60_PATH, MODEL_DIR, MODEL_Q5B_PATH, ROOT

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    if not feat_path.is_file() or not lab_path.is_file():
        return {"status": "missing_artifacts", "feat": str(feat_path), "lab": str(lab_path)}

    feat = pd.read_csv(feat_path)
    lab = pd.read_csv(lab_path)
    label_col, _ = resolve_label_column(lab.columns)
    if label_col != PRIMARY_LABEL:
        return {"status": "label_not_primary", "label_col": label_col}

    cols_wanted = FEATURE_SETS[set_name]
    cols = [c for c in cols_wanted if c in feat.columns]
    # make_expanding_folds requires LABEL_COL=hit_200k for class balance checks;
    # train still uses PRIMARY label_col when present.
    merge_cols = ["mint", label_col]
    if "hit_200k" in lab.columns and "hit_200k" not in merge_cols:
        merge_cols.append("hit_200k")
    df = feat.merge(lab[merge_cols], on="mint", how="inner", validate="one_to_one")
    if "hit_200k" not in df.columns:
        df["hit_200k"] = df[label_col]
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.sort_values("t0", kind="mergesort").reset_index(drop=True)
    folds = make_expanding_folds(df)
    last = folds[-1]
    tr = last["train_idx"]
    if len(tr) > max_train_rows:
        tr = tr[-max_train_rows:]
    X = df.loc[tr, cols].to_numpy(dtype=float)
    y = df.loc[tr, label_col].astype(int).to_numpy()
    pipe = build_hist_gb()
    pipe.fit(X, y)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    out = out_path or (MODEL_Q5B_PATH if set_name == "+q5b" else MODEL_BUY60_PATH)
    # Train-score quantiles for live ultra-select entry (paper-trade-v1 Entrada A)
    train_proba = pipe.predict_proba(X)[:, 1]
    thr_top1 = float(np.quantile(train_proba, 0.99))
    thr_top5 = float(np.quantile(train_proba, 0.95))
    calibration = {
        "train_top_frac_thresholds": {"0.01": thr_top1, "0.05": thr_top5},
        "train_n": int(len(tr)),
        "fold": last.get("fold"),
        "train_t0_max": str(df.loc[tr, "t0"].max()),
        "rule": "score >= quantile(train_scores, 1-top_frac); TRAIN only",
    }
    joblib.dump(
        {
            "pipeline": pipe,
            "feature_names": cols,
            "set_name": set_name,
            "label": label_col,
            "train_n": int(len(tr)),
            "fold": last.get("fold"),
            "train_t0_max": str(df.loc[tr, "t0"].max()),
            "calibration": calibration,
        },
        out,
    )
    # Sidecar JSON for histgb_q5b (readable without joblib)
    if set_name == "+q5b":
        from datetime import datetime, timezone
        from paper_live.config import CALIBRATION_Q5B_PATH
        import json

        calib_doc = {
            "kind": "paper_live_train_quantile_calibration",
            "set_name": set_name,
            "score_mode": "histgb_q5b",
            "model_path": out.name,
            "fold": last.get("fold"),
            "train_n": int(len(tr)),
            "train_t0_max": str(df.loc[tr, "t0"].max()),
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "rule": calibration["rule"],
            "why": (
                "Matches WF ultra-select (P@top≈100% for trainQ top1%/top5%). "
                "Live must NOT use top-K every ~10s batch. Default top_frac=0.01 + max_per_hour≈2."
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
        }
        CALIBRATION_Q5B_PATH.parent.mkdir(parents=True, exist_ok=True)
        CALIBRATION_Q5B_PATH.write_text(json.dumps(calib_doc, indent=2))
    return {
        "status": "ok",
        "path": str(out),
        "set_name": set_name,
        "n_features": len(cols),
        "train_n": int(len(tr)),
        "fold": last.get("fold"),
        "calibration": calibration,
    }
