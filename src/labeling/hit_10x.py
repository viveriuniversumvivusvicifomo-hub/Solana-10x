"""Cálculo puro de hit_10x_* a partir de series de precio post-T0.

Sin I/O de APIs. Cycle 1+ cableará Bitquery/Birdeye → esta función.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from labeling.horizons import (
    HIT_10X_MULTIPLE,
    LABEL_HORIZONS,
    PRIMARY_HORIZON,
)
from labeling.schema import LabelRecord
from verification.leakage_v3 import assert_label_window_strictly_after_t0


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps de label deben ser timezone-aware UTC")
    return value.astimezone(timezone.utc)


def compute_hit_10x_for_horizon(
    *,
    t0: datetime,
    p0: float,
    horizon: timedelta,
    prices: Sequence[tuple[datetime, float]],
    multiple: float = HIT_10X_MULTIPLE,
) -> tuple[bool | None, float | None, float | None]:
    """Devuelve (hit, max_multiple, time_to_10x_s) en ventana (t0, t0+H].

    ``prices``: (ts, price_usd) con ts > t0. Si la serie está vacía → (None, None, None).
    """
    if p0 <= 0:
        raise ValueError("p0 must be > 0")
    t0_utc = _as_utc(t0)
    end = t0_utc + horizon

    # Gate V3: todos los puntos deben ser > t0 (también descarta == t0)
    if prices:
        assert_label_window_strictly_after_t0([ts for ts, _ in prices], t0=t0_utc)

    in_window: list[tuple[datetime, float]] = []
    for ts, px in prices:
        ts_u = _as_utc(ts)
        if t0_utc < ts_u <= end:
            if px <= 0:
                raise ValueError(f"precio no positivo en {ts_u.isoformat()}")
            in_window.append((ts_u, px))

    if not in_window:
        return None, None, None

    max_px = max(px for _, px in in_window)
    max_mult = max_px / p0
    hit = max_mult >= multiple
    time_to: float | None = None
    if hit:
        target = multiple * p0
        for ts_u, px in sorted(in_window, key=lambda x: x[0]):
            if px >= target:
                time_to = (ts_u - t0_utc).total_seconds()
                break
    return hit, max_mult, time_to


def materialize_label_record(
    *,
    capture_id: str,
    mint: str,
    t0: datetime,
    p0: float,
    prices: Sequence[tuple[datetime, float]],
    mc_series: Sequence[tuple[datetime, float]] | None = None,
    horizons: dict[str, timedelta] | None = None,
    primary_horizon: str = PRIMARY_HORIZON,
    price_source: str = "fixture",
) -> LabelRecord:
    """Materializa LabelRecord para todos los horizontes (sin datos live)."""
    hs = horizons or LABEL_HORIZONS
    hit_map: dict[str, bool | None] = {}
    mult_map: dict[str, float | None] = {}
    mc_map: dict[str, float | None] = {}
    time_to_primary: float | None = None

    for name, delta in hs.items():
        hit, mult, tto = compute_hit_10x_for_horizon(
            t0=t0, p0=p0, horizon=delta, prices=prices
        )
        hit_map[name] = hit
        mult_map[name] = mult
        if name == primary_horizon:
            time_to_primary = tto

        if mc_series:
            t0_utc = _as_utc(t0)
            end = t0_utc + delta
            mcs = [
                mc
                for ts, mc in mc_series
                if t0_utc < _as_utc(ts) <= end
            ]
            mc_map[name] = max(mcs) if mcs else None
        else:
            mc_map[name] = None

    return LabelRecord(
        capture_id=capture_id,
        mint=mint,
        t0=_as_utc(t0),
        p0=p0,
        primary_horizon=primary_horizon,
        hit_10x=hit_map,
        max_multiple=mult_map,
        max_mc=mc_map,
        time_to_10x_s=time_to_primary,
        price_source=price_source,
    )
