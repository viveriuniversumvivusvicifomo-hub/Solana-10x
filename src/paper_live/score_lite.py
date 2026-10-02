"""Lite product scorer — logistic on 5–10 WF-inspired features (Pump+RPC fast).

NOT Path A / histgb_q5b parity. See ``cycle0/score-mode-lite-cycle0-20261002.md``.
Missing soft features default; only ``buy_vol_usd_60s`` is required.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from features.post_q5_sets import LITE_COLS
from paper_live.config import LITE_CALIBRATION_PATH
from paper_live.score import ScoreResult, _skip

# Heuristic weights from WF ranking (buy60 >> Q5a sniper/conc >> Q5b priors).
# Recalibrate offline into lite_calibration.json — do not invent Dune pulls.
DEFAULT_WEIGHTS: dict[str, float] = {
    "buy_vol_usd_60s": 2.40,
    "sniper_vol_share_5s": 0.80,
    "top1_buyer_vol_share": 0.50,
    "top5_buyer_vol_share": 0.35,
    "age_s": -0.25,
    "progress_curve_proxy": 0.20,
    "net_sol_curve": 0.30,
    "creator_prior_mints_7d": -0.40,
    "creator_prior_mints_30d": -0.25,
}
DEFAULT_BIAS = -1.20
DEFAULT_AGE_FILL_S = 60.0


def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _f(v: Any, default: float) -> float:
    if v is None:
        return default
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if x != x:  # NaN
        return default
    return x


def phi_lite(feats: dict[str, Any], *, age_fill_s: float = DEFAULT_AGE_FILL_S) -> dict[str, float]:
    """Feature transforms φ(x) for lite logistic. Soft defaults for non-buy_vol."""
    buy = _f(feats.get("buy_vol_usd_60s"), float("nan"))
    if buy != buy:
        raise ValueError("buy_vol_usd_60s required")
    age = feats.get("age_s")
    age_v = _f(age, age_fill_s) if age is not None else age_fill_s
    return {
        "buy_vol_usd_60s": math.log1p(_clip(buy, 0.0, 1e7)) / 10.0,
        "sniper_vol_share_5s": _clip(_f(feats.get("sniper_vol_share_5s"), 0.0), 0.0, 1.0),
        "top1_buyer_vol_share": _clip(_f(feats.get("top1_buyer_vol_share"), 0.0), 0.0, 1.0),
        "top5_buyer_vol_share": _clip(_f(feats.get("top5_buyer_vol_share"), 0.0), 0.0, 1.0),
        "age_s": math.log1p(_clip(age_v, 0.0, 86_400.0)) / 10.0,
        "progress_curve_proxy": _clip(_f(feats.get("progress_curve_proxy"), 0.0), 0.0, 1.0),
        "net_sol_curve": _clip(_f(feats.get("net_sol_curve"), 0.0), -85.0, 85.0) / 85.0,
        "creator_prior_mints_7d": math.log1p(_clip(_f(feats.get("creator_prior_mints_7d"), 0.0), 0.0, 100.0))
        / 5.0,
        "creator_prior_mints_30d": math.log1p(
            _clip(_f(feats.get("creator_prior_mints_30d"), 0.0), 0.0, 300.0)
        )
        / 5.0,
    }


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def load_lite_calibration(path: Path | None = None) -> dict[str, Any]:
    p = path or LITE_CALIBRATION_PATH
    if not p.is_file():
        return {
            "kind": "lite_calibration_stub",
            "weights": dict(DEFAULT_WEIGHTS),
            "bias": DEFAULT_BIAS,
            "threshold_default": 0.55,
            "source": "defaults",
        }
    data = json.loads(p.read_text())
    weights = dict(DEFAULT_WEIGHTS)
    weights.update({k: float(v) for k, v in (data.get("weights") or {}).items() if k in weights})
    return {
        "kind": data.get("kind") or "lite_calibration",
        "weights": weights,
        "bias": float(data.get("bias", DEFAULT_BIAS)),
        "threshold_default": float(data.get("threshold_default", 0.55)),
        "temperature": float(data.get("temperature", 1.0)),
        "source": str(p),
        "note": data.get("note"),
    }


@dataclass
class LiteScorer:
    """Tiny logistic / rules scorer for the explore lane."""

    mode: str = "lite"  # lite | lite_logistic_v0 | lite_rules_v0
    calibration_path: Path | None = None

    def __post_init__(self) -> None:
        self.cal = load_lite_calibration(self.calibration_path)
        self.weights: dict[str, float] = dict(self.cal["weights"])
        self.bias: float = float(self.cal["bias"])
        self.temperature: float = float(self.cal.get("temperature") or 1.0)

    @property
    def set_name(self) -> str:
        return "lite"

    def score(self, feats: dict[str, Any]) -> ScoreResult:
        if feats.get("buy_vol_usd_60s") is None:
            return _skip("skip_missing_buy_vol", "lite", "buy_vol_usd_60s unavailable")
        if self.mode in ("lite_rules_v0",):
            return self._rules(feats)
        return self._logistic(feats)

    def _logistic(self, feats: dict[str, Any]) -> ScoreResult:
        try:
            phi = phi_lite(feats)
        except ValueError as e:
            return _skip("skip_missing_buy_vol", "lite", str(e))
        z = self.bias
        for name in LITE_COLS:
            z += self.weights.get(name, 0.0) * phi.get(name, 0.0)
        if self.temperature > 0:
            z = z / self.temperature
        p = _sigmoid(z)
        return ScoreResult(
            score=float(p),
            mode="lite_logistic_v0" if self.mode == "lite" else self.mode,
            set_name="lite",
            detail=(
                f"lite logistic v0 z={z:.4f} src={self.cal.get('source')}; "
                "NOT histgb/Path A parity"
            ),
        )

    def _rules(self, feats: dict[str, Any]) -> ScoreResult:
        """Stub gate stack → soft score in {0.1, 0.5, 0.9} (not for live thr yet)."""
        buy = _f(feats.get("buy_vol_usd_60s"), 0.0)
        sniper = _f(feats.get("sniper_vol_share_5s"), 0.0)
        prior7 = _f(feats.get("creator_prior_mints_7d"), 0.0)
        hits = 0
        if buy >= 500.0:
            hits += 1
        if 0.05 <= sniper <= 0.85:
            hits += 1
        if prior7 <= 5:
            hits += 1
        score = {0: 0.1, 1: 0.35, 2: 0.65, 3: 0.9}[hits]
        return ScoreResult(
            score=float(score),
            mode="lite_rules_v0",
            set_name="lite",
            detail="stub rules — calibrate before live thr",
        )


def required_lite_present(feats: dict[str, Any]) -> bool:
    return feats.get("buy_vol_usd_60s") is not None


def feature_vector_lite(feats: dict[str, Any]) -> dict[str, float | None]:
    return {c: feats.get(c) for c in LITE_COLS}


__all__ = [
    "DEFAULT_WEIGHTS",
    "DEFAULT_BIAS",
    "LiteScorer",
    "phi_lite",
    "load_lite_calibration",
    "required_lite_present",
    "feature_vector_lite",
    "LITE_COLS",
]
