"""Ultra-select paper entry gate — align live with paper-trade-v1 theory.

Chosen rule (default): **Entrada A — train quantile (top 1%)** on histgb_q5b
fold-5 train scores, plus a rolling **max_per_hour** capacity cap.

Why this matches theory (and rejects top-20-every-batch)
-------------------------------------------------------
Offline paper-trade-v1 (cycle0/paper-trade-v1.md) shows P@top ≈ 100% only in the
ultra-select tail:

* Entrada A ``+q5b_trainQ_top1%``: n=708, hit 100%, ~48.7 trades/day
* Entrada B ``+q5b_topK_100``: n=500, hit 100%, ~34.4 trades/day

Those rates are **global** over OOS folds, not "top-20 of every ~10s poll".
A live top-K-per-batch rule would admit ~thousands/day and destroy the
selectivity that produced theoretical P@top≈100%.

Live proxy
----------
1. Primary: ``score >= train_quantile(fold-5 train scores, 1 - top_frac)``
   (default top_frac=0.01 → threshold ≈ 0.999807). Threshold from TRAIN only /
   exported calibration — never from live OOS labels.
2. Capacity: ``max_per_hour`` default 2 → ~48/day, matching trainQ_top1% rate
   (and in the same ballpark as topK_100 ≈ 34/day).
3. ``top_k`` remains a **within-batch safety** after the two gates above; it is
   no longer the primary selector.

Legacy ``entry_rule=topk_batch`` restores the old top-K-per-batch behaviour for
smoke / debug only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from paper_live.config import MODEL_Q5B_PATH, ROOT

# Fold-5 histgb_q5b train quantiles (computed on export; also in calibration JSON).
# Kept as fallbacks if calibration artifact is missing.
FOLD5_TRAINQ_TOP1 = 0.9998068280570067
FOLD5_TRAINQ_TOP5 = 0.9997995037737603

DEFAULT_ENTRY_RULE = "train_quantile"  # train_quantile | topk_batch | off
DEFAULT_TRAIN_TOP_FRAC = 0.01
DEFAULT_MAX_PER_HOUR = 2

CALIBRATION_PATH = ROOT / "data" / "paper_live" / "models" / "q5b_calibration.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def load_calibration(path: Path | None = None) -> dict[str, Any] | None:
    p = path or CALIBRATION_PATH
    if not p.is_file():
        # Try joblib blob
        if MODEL_Q5B_PATH.is_file():
            try:
                import joblib

                blob = joblib.load(MODEL_Q5B_PATH)
                cal = blob.get("calibration")
                if isinstance(cal, dict) and cal.get("train_top_frac_thresholds"):
                    return {
                        "thresholds": {
                            str(k): float(v)
                            for k, v in cal["train_top_frac_thresholds"].items()
                        },
                        "fold": cal.get("fold"),
                        "train_n": cal.get("train_n"),
                        "source": f"joblib:{MODEL_Q5B_PATH.name}",
                    }
            except Exception:  # noqa: BLE001
                return None
        return None
    try:
        data = json.loads(p.read_text())
        th = data.get("thresholds") or {}
        return {
            "thresholds": {str(k): float(v) for k, v in th.items()},
            "fold": data.get("fold"),
            "train_n": data.get("train_n"),
            "source": str(p),
            "why": data.get("why"),
            "rule": data.get("rule"),
        }
    except Exception:  # noqa: BLE001
        return None


def train_quantile_threshold(
    train_top_frac: float,
    calibration: dict[str, Any] | None = None,
) -> float:
    """Absolute trainQ floor for ``train_top_frac`` (fold-5 / calibration)."""
    cal = calibration if calibration is not None else load_calibration()
    key = f"{train_top_frac:g}"
    candidates = (
        key,
        f"{train_top_frac:.2f}",
        f"{train_top_frac:.3f}",
        str(train_top_frac),
    )
    if cal and cal.get("thresholds"):
        th = cal["thresholds"]
        for k in candidates:
            if k in th:
                return float(th[k])
        try:
            fracs = sorted(float(k) for k in th)
            nearest = min(fracs, key=lambda f: abs(f - train_top_frac))
            nk = f"{nearest:g}" if f"{nearest:g}" in th else str(nearest)
            return float(th[nk])
        except Exception:  # noqa: BLE001
            pass
    if abs(train_top_frac - 0.01) < 1e-9:
        return FOLD5_TRAINQ_TOP1
    if abs(train_top_frac - 0.05) < 1e-9:
        return FOLD5_TRAINQ_TOP5
    return FOLD5_TRAINQ_TOP1 if train_top_frac <= 0.01 else FOLD5_TRAINQ_TOP5


def resolve_score_threshold(
    *,
    score_threshold: float | None,
    train_top_frac: float,
    score_mode: str,
    calibration: dict[str, Any] | None = None,
    allow_non_train_threshold: bool = False,
) -> float | None:
    """Return absolute score floor, or None if threshold gate should not apply.

    * If ``score_threshold`` is set explicitly → **return it** (no raise).
      Sinck product may use absolute 0.99; that is allowed.
    * If omitted and score_mode is histgb_* → default = trainQ from calibration
      (fold-5 top_frac, Entrada A).
    * Non-histgb without explicit threshold → None (no score floor).

    ``allow_non_train_threshold`` is kept for CLI compatibility (harmless / no-op
    on the raise path, which was removed).
    """
    _ = allow_non_train_threshold  # retained for API / CLI compatibility
    if score_threshold is not None:
        return float(score_threshold)
    if not score_mode.startswith("histgb"):
        return None
    return train_quantile_threshold(train_top_frac, calibration)


@dataclass
class EntryDecision:
    accept: bool
    reason: str  # enter | skip_below_threshold | skip_capacity | skip_topk


@dataclass
class EntryGate:
    """Stateful within-process capacity counter; also consults journal history."""

    entry_rule: str = DEFAULT_ENTRY_RULE
    score_threshold: float | None = None
    train_top_frac: float = DEFAULT_TRAIN_TOP_FRAC
    max_per_hour: int = DEFAULT_MAX_PER_HOUR
    top_k: int = 50
    score_mode: str = "histgb_q5b"
    calibration: dict[str, Any] | None = None
    allow_non_train_threshold: bool = False  # retained; no longer blocks explicit thresholds

    def __post_init__(self) -> None:
        if self.calibration is None:
            self.calibration = load_calibration()
        self._resolved_threshold = resolve_score_threshold(
            score_threshold=self.score_threshold,
            train_top_frac=self.train_top_frac,
            score_mode=self.score_mode,
            calibration=self.calibration,
            allow_non_train_threshold=self.allow_non_train_threshold,
        )
        # Soft note vs live_entry_config (Sinck product 0.99): no hard-raise.
        # Explicit thresholds (incl. 0.99) and omitted→trainQ are both allowed.
        # verification.live_parity still reports drift for QA.
        self._threshold_config_notes: list[str] = []
        if self.score_mode.startswith("histgb") and self._resolved_threshold is not None:
            try:
                from verification.live_parity import assert_threshold_matches_config

                self._threshold_config_notes = list(
                    assert_threshold_matches_config(float(self._resolved_threshold))
                    or []
                )
            except Exception:  # noqa: BLE001
                self._threshold_config_notes = []

    @property
    def resolved_threshold(self) -> float | None:
        return self._resolved_threshold

    def describe(self) -> dict[str, Any]:
        return {
            "entry_rule": self.entry_rule,
            "train_top_frac": self.train_top_frac,
            "score_threshold": self._resolved_threshold,
            "score_threshold_explicit": self.score_threshold,
            "max_per_hour": self.max_per_hour,
            "top_k_batch_safety": self.top_k,
            "score_mode": self.score_mode,
            "calibration_source": (self.calibration or {}).get("source"),
            "threshold_config_notes": list(getattr(self, "_threshold_config_notes", []) or []),
            "theory": (
                "omit threshold → Entrada A trainQ; explicit e.g. 0.99 = Sinck product; "
                "NOT top-K every poll batch"
            ),
        }

    def count_recent_enters(
        self,
        *,
        journal_entered_at: list[str] | None = None,
        now: datetime | None = None,
        window_s: float = 3600.0,
    ) -> int:
        """Count paper enters in the rolling window from journal timestamps only."""
        now = now or _utcnow()
        cutoff = now - timedelta(seconds=window_s)
        n = 0
        for raw in journal_entered_at or []:
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt.astimezone(timezone.utc) >= cutoff:
                    n += 1
            except Exception:  # noqa: BLE001
                continue
        return n

    def filter_scored_batch(
        self,
        scored: list[tuple[float, Any, dict[str, Any], Any]],
        *,
        journal_entered_at: list[str] | None = None,
        now: datetime | None = None,
    ) -> tuple[list[tuple[float, Any, dict[str, Any], Any]], dict[str, int]]:
        """Apply entry gates. scored already sorted by (-score, t0, mint).

        Returns (accepted_rows, counters).
        """
        now = now or _utcnow()
        counters = {
            "n_scored": len(scored),
            "n_skip_below_threshold": 0,
            "n_skip_capacity": 0,
            "n_skip_topk": 0,
            "n_accepted": 0,
        }
        rule = self.entry_rule

        if rule == "off":
            # no gates — still respect top_k as hard batch cap for safety
            accepted = scored[: self.top_k]
            counters["n_skip_topk"] = max(0, len(scored) - len(accepted))
            counters["n_accepted"] = len(accepted)
            return accepted, counters

        if rule == "topk_batch":
            accepted = scored[: self.top_k]
            counters["n_skip_topk"] = max(0, len(scored) - len(accepted))
            counters["n_accepted"] = len(accepted)
            return accepted, counters

        # train_quantile (default)
        thr = self._resolved_threshold
        passed: list[tuple[float, Any, dict[str, Any], Any]] = []
        for row in scored:
            score = row[0]
            if thr is not None and score < thr:
                counters["n_skip_below_threshold"] += 1
                continue
            passed.append(row)

        # capacity over rolling hour (journal + this session)
        already = self.count_recent_enters(
            journal_entered_at=journal_entered_at, now=now, window_s=3600.0
        )
        room = max(0, int(self.max_per_hour) - already) if self.max_per_hour >= 0 else len(passed)
        if self.max_per_hour == 0:
            room = 0

        capacity_ok = passed[:room]
        counters["n_skip_capacity"] = max(0, len(passed) - len(capacity_ok))

        accepted = capacity_ok[: self.top_k]
        counters["n_skip_topk"] = max(0, len(capacity_ok) - len(accepted))
        counters["n_accepted"] = len(accepted)
        return accepted, counters


def backtest_scores_against_threshold(
    scores: list[float],
    *,
    threshold: float,
) -> dict[str, Any]:
    """How many historical scores would pass the new gate (no capacity)."""
    n = len(scores)
    n_pass = sum(1 for s in scores if s is not None and float(s) >= threshold)
    return {
        "n_scores": n,
        "threshold": threshold,
        "n_pass": n_pass,
        "n_fail": n - n_pass,
        "pass_rate": (n_pass / n) if n else 0.0,
        "score_max": max(scores) if scores else None,
        "score_median": float(sorted(scores)[n // 2]) if scores else None,
    }
