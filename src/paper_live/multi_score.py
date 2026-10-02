"""Multi-scorer — run histgb_q5b and lite (and future modes) in parallel lanes.

Primary live lane remains histgb_q5b. Lite is opt-in explore. Path A gates apply
ONLY to histgb_* modes (PaperScorer unchanged).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from paper_live.score import PaperScorer, ScoreResult
from paper_live.score_lite import LiteScorer


@dataclass
class LaneScore:
    lane: str  # logical name: histgb_q5b | lite | ...
    result: ScoreResult
    threshold: float | None = None

    @property
    def skipped(self) -> bool:
        return self.result.skipped

    @property
    def score(self) -> float:
        return self.result.score

    @property
    def passes_threshold(self) -> bool:
        if self.skipped:
            return False
        if self.threshold is None:
            return True
        return self.score >= float(self.threshold)


@dataclass
class MultiScoreResult:
    lanes: dict[str, LaneScore] = field(default_factory=dict)
    primary_lane: str = "histgb_q5b"

    @property
    def primary(self) -> LaneScore | None:
        return self.lanes.get(self.primary_lane)

    def as_scores_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, lane in self.lanes.items():
            out[name] = {
                "score": None if lane.skipped else lane.score,
                "mode": lane.result.mode,
                "set_name": lane.result.set_name,
                "detail": lane.result.detail,
                "threshold": lane.threshold,
                "pass": lane.passes_threshold,
                "skipped": lane.skipped,
            }
        return out


def _parse_modes(modes: str | Iterable[str] | None) -> list[str]:
    if modes is None:
        return ["histgb_q5b"]
    if isinstance(modes, str):
        parts = [p.strip() for p in modes.split(",") if p.strip()]
        return parts or ["histgb_q5b"]
    return [str(m).strip() for m in modes if str(m).strip()]


class MultiPaperScorer:
    """Score each sighting with one or more lanes; thr is per-lane metadata only."""

    def __init__(
        self,
        modes: str | Iterable[str] | None = None,
        *,
        primary_lane: str = "histgb_q5b",
        thresholds: dict[str, float | None] | None = None,
        allow_q5b_fallback: bool = False,
        require_t0_refined: bool = True,
        max_age_s: float = 86_400.0,
        require_pyth_when_key: bool = True,
        lite_mode: str = "lite",
    ) -> None:
        self.mode_names = _parse_modes(modes)
        self.primary_lane = primary_lane if primary_lane in self.mode_names else self.mode_names[0]
        self.thresholds = dict(thresholds or {})
        self._histgb: dict[str, PaperScorer] = {}
        self._lite: LiteScorer | None = None
        for m in self.mode_names:
            if m in ("lite", "lite_logistic_v0", "lite_rules_v0"):
                if self._lite is None:
                    self._lite = LiteScorer(mode="lite_rules_v0" if m == "lite_rules_v0" else lite_mode)
            elif m.startswith("histgb") or m == "rule_buy60":
                self._histgb[m] = PaperScorer(
                    m if m != "histgb_q5b" else "histgb_q5b",
                    allow_q5b_fallback=allow_q5b_fallback,
                    require_t0_refined=require_t0_refined,
                    max_age_s=max_age_s,
                    require_pyth_when_key=require_pyth_when_key,
                )
            else:
                raise ValueError(f"unknown parallel score mode: {m}")

    def score_all(self, feats: dict[str, Any]) -> MultiScoreResult:
        lanes: dict[str, LaneScore] = {}
        for m in self.mode_names:
            if m in ("lite", "lite_logistic_v0", "lite_rules_v0"):
                assert self._lite is not None
                # Rules variant uses dedicated LiteScorer mode
                if m == "lite_rules_v0" and self._lite.mode != "lite_rules_v0":
                    sr = LiteScorer(mode="lite_rules_v0").score(feats)
                else:
                    sr = self._lite.score(feats)
                lane_key = "lite"
            else:
                sr = self._histgb[m].score(feats)
                lane_key = m
            thr = self.thresholds.get(lane_key)
            if thr is None:
                thr = self.thresholds.get(m)
            lanes[lane_key] = LaneScore(lane=lane_key, result=sr, threshold=thr)
        return MultiScoreResult(lanes=lanes, primary_lane=self.primary_lane)


__all__ = [
    "LaneScore",
    "MultiScoreResult",
    "MultiPaperScorer",
]
