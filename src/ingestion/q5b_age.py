"""Q5b age_s / age_min — Dune-parity from create_ts (SolDatos).

Train (cycle0/q5_sql/dune-q5b-creator-age-pre-t0.sql):
  age_s = date_diff('second', create_ts, t0_ts)  with create_ts <= t0_ts

NOT age_proxy_s from first trade (Q5a). Anomalous ages (re-sighted old mints,
bad create resolution) must be filtered before scoring — train OOS≥0.99 snipers
have age_s ≈ 0.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Captura band is early-curve; >1d age at "T0" is almost never a train-like sniper
AGE_MAX_SCOREABLE_S = 86_400.0  # 1 day
# Soft warn / clip diagnostics
AGE_WARN_S = 3_600.0  # 1 hour


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class AgeFromCreate:
    age_s: float | None
    age_min: float | None
    ok: bool
    reason: str
    create_ts: datetime | None
    t0: datetime | None

    def as_feature_dict(self) -> dict[str, Any]:
        return {
            "age_s": self.age_s,
            "age_min": self.age_min,
            "age_from_create_ok": self.ok,
            "age_from_create_reason": self.reason,
        }


def age_s_from_create(
    create_ts: datetime | None,
    t0: datetime,
    *,
    max_age_s: float = AGE_MAX_SCOREABLE_S,
) -> AgeFromCreate:
    """Dune Q5b age: seconds from on-chain/createevent create_ts to T0.

    Returns ok=False when create missing, create>t0, or age exceeds max_age_s
    (anomalous re-sight / bad create). Callers must not score when ok=False.
    """
    t0a = _aware(t0)
    if create_ts is None:
        return AgeFromCreate(
            age_s=None,
            age_min=None,
            ok=False,
            reason="missing_create_ts",
            create_ts=None,
            t0=t0a,
        )
    cts = _aware(create_ts)
    if cts > t0a:
        return AgeFromCreate(
            age_s=None,
            age_min=None,
            ok=False,
            reason="create_after_t0",
            create_ts=cts,
            t0=t0a,
        )
    age = (t0a - cts).total_seconds()
    if age < 0:
        return AgeFromCreate(
            None, None, False, "negative_age", cts, t0a
        )
    if max_age_s is not None and age > float(max_age_s):
        return AgeFromCreate(
            age_s=float(age),
            age_min=float(age) / 60.0,
            ok=False,
            reason=f"age_gt_max_{int(max_age_s)}s",
            create_ts=cts,
            t0=t0a,
        )
    reason = "ok"
    if age > AGE_WARN_S:
        reason = "ok_but_age_gt_1h"
    return AgeFromCreate(
        age_s=float(age),
        age_min=float(age) / 60.0,
        ok=True,
        reason=reason,
        create_ts=cts,
        t0=t0a,
    )


def filter_anomalous_age_features(
    feats: dict[str, Any],
    *,
    max_age_s: float = AGE_MAX_SCOREABLE_S,
) -> tuple[dict[str, Any], bool, str]:
    """If feats already have age_s, validate; strip scoreability on anomaly.

    Does not invent create_ts — use ``age_s_from_create`` when create known.
    """
    out = dict(feats)
    raw = out.get("age_s")
    if raw is None:
        return out, False, "missing_age_s"
    try:
        age = float(raw)
    except (TypeError, ValueError):
        return out, False, "non_numeric_age_s"
    if age < 0:
        return out, False, "negative_age_s"
    if age > float(max_age_s):
        return out, False, f"age_gt_max_{int(max_age_s)}s"
    return out, True, "ok"
