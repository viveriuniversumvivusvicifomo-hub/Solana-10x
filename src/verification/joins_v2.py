"""V2 — auditoría de join temporal: rechazar cualquier feature > T0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping, Sequence

from verification.errors import LookAheadError

AsofDirection = Literal["backward", "forward", "nearest"]

# max_staleness v0 (protocolos-verificacion.md)
MAX_STALENESS_CURVE_TRADES = timedelta(seconds=15)
MAX_STALENESS_HOLDERS = timedelta(seconds=60)


def _as_utc(value: Any, *, field: str) -> datetime:
    if value is None:
        raise LookAheadError(f"{field} ausente (sin timestamp → rechazo L2)")
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        # unix seconds
        dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise LookAheadError(f"{field} tipo inválido: {type(value)!r}")
    if dt.tzinfo is None:
        raise LookAheadError(f"{field} debe ser timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def assert_feature_rows_have_ts(
    rows: Sequence[Mapping[str, Any]],
    *,
    ts_key: str = "feature_ts",
) -> None:
    """Rechaza filas 'latest' sin timestamp (V2 L2)."""
    for i, row in enumerate(rows):
        if ts_key not in row or row[ts_key] is None:
            raise LookAheadError(f"fila[{i}] sin {ts_key} (snapshot latest prohibido)")


def assert_all_feature_ts_leq_t0(
    rows: Sequence[Mapping[str, Any]],
    *,
    t0: Any,
    ts_key: str = "feature_ts",
    slot_key: str = "slot_feature",
    slot0: int | None = None,
) -> None:
    """Falla si alguna feature tiene ts > t0 o slot > slot0.

    Esta es la gate dura anti look-ahead del feature store.
    """
    t0_dt = _as_utc(t0, field="t0")
    offenders: list[str] = []
    for i, row in enumerate(rows):
        if ts_key in row and row[ts_key] is not None:
            fts = _as_utc(row[ts_key], field=f"rows[{i}].{ts_key}")
            if fts > t0_dt:
                offenders.append(f"rows[{i}].{ts_key}={fts.isoformat()} > t0={t0_dt.isoformat()}")
        elif slot_key in row and row[slot_key] is not None and slot0 is not None:
            if int(row[slot_key]) > int(slot0):
                offenders.append(f"rows[{i}].{slot_key}={row[slot_key]} > slot0={slot0}")
        else:
            raise LookAheadError(
                f"rows[{i}] sin {ts_key} ni ({slot_key}+slot0); no se puede auditar join"
            )
    if offenders:
        raise LookAheadError("join > T0 rechazado: " + "; ".join(offenders))


def assert_asof_backward_only(direction: AsofDirection) -> None:
    if direction != "backward":
        raise LookAheadError(
            f"asof_join direction={direction!r} prohibido; solo 'backward'"
        )


def assert_staleness(
    rows: Sequence[Mapping[str, Any]],
    *,
    t0: Any,
    ts_key: str = "feature_ts",
    max_staleness: timedelta = MAX_STALENESS_CURVE_TRADES,
    max_stale_fraction: float = 0.05,
) -> dict[str, float]:
    """Audita staleness; falla si fracción stale > umbral.

    Returns dict con n, n_stale, fraction_stale.
    """
    t0_dt = _as_utc(t0, field="t0")
    n = len(rows)
    if n == 0:
        return {"n": 0.0, "n_stale": 0.0, "fraction_stale": 0.0}
    n_stale = 0
    for i, row in enumerate(rows):
        fts = _as_utc(row.get(ts_key), field=f"rows[{i}].{ts_key}")
        if fts > t0_dt:
            raise LookAheadError(f"rows[{i}] feature_ts > t0 durante staleness check")
        if (t0_dt - fts) > max_staleness:
            n_stale += 1
    frac = n_stale / n
    if frac > max_stale_fraction:
        raise LookAheadError(
            f"fracción stale {frac:.3f} > {max_stale_fraction} "
            f"(max_staleness={max_staleness})"
        )
    return {"n": float(n), "n_stale": float(n_stale), "fraction_stale": frac}
