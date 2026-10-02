"""V1 — schema CaptureEvent + helpers de unit/idempotencia."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ingestion.pump_constants import DEFINITION_VERSION, SOL_USD_SOURCE, SOL_USD_SOURCE_FROZEN

from verification.errors import CaptureSchemaError

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "capture_id",
        "mint",
        "t0_iso",
        "slot0",
        "sig0",
        "mc0",
        "p0",
        "sol_usd",
        "sol_usd_source",
        "vs",
        "vt",
        "rs",
        "rt",
        "complete",
        "definition_version",
        "capture_quality",
        "snapshot_hash",
    }
)

MC_LO = 8_000.0
MC_HI = 20_000.0


def _parse_t0(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise CaptureSchemaError(f"t0_iso tipo inválido: {type(value)!r}")
    if dt.tzinfo is None:
        raise CaptureSchemaError("t0_iso debe ser timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def verify_capture_schema(event: Mapping[str, Any]) -> None:
    """Valida campos obligatorios y reglas duras de CaptureEvent aceptado."""
    missing = sorted(REQUIRED_FIELDS - set(event.keys()))
    if missing:
        raise CaptureSchemaError(f"faltan campos: {missing}")

    if event.get("complete") is not False:
        raise CaptureSchemaError("complete debe ser False en eventos aceptados")

    mc0 = float(event["mc0"])
    if not (MC_LO <= mc0 <= MC_HI):
        raise CaptureSchemaError(f"mc0 fuera de rango [{MC_LO}, {MC_HI}]: {mc0}")

    if event.get("definition_version") != DEFINITION_VERSION:
        raise CaptureSchemaError(
            f"definition_version esperada {DEFINITION_VERSION!r}, got {event.get('definition_version')!r}"
        )

    verify_sol_usd_source(event)

    _parse_t0(event["t0_iso"])


def verify_sol_usd_source(event: Mapping[str, Any]) -> None:
    """Oracle FROZEN = Pyth. HIGH exige sol_usd_source == pyth; fallback → quality ≤ MED."""
    source = event.get("sol_usd_source")
    if not isinstance(source, str) or not source:
        raise CaptureSchemaError("sol_usd_source ausente")
    quality = event.get("capture_quality")
    if quality == "HIGH" and source != SOL_USD_SOURCE:
        raise CaptureSchemaError(
            f"capture_quality=HIGH exige sol_usd_source={SOL_USD_SOURCE!r}, got {source!r}"
        )


def assert_oracle_frozen() -> None:
    """Constante única en pump_constants (V5): Pyth frozen."""
    if not SOL_USD_SOURCE_FROZEN or SOL_USD_SOURCE != "pyth":
        raise CaptureSchemaError(
            f"oracle no frozen: SOL_USD_SOURCE={SOL_USD_SOURCE!r} frozen={SOL_USD_SOURCE_FROZEN}"
        )


def verify_idempotent_capture_ids(capture_ids: Sequence[str]) -> None:
    seen: set[str] = set()
    dupes: list[str] = []
    for cid in capture_ids:
        if cid in seen:
            dupes.append(cid)
        seen.add(cid)
    if dupes:
        raise CaptureSchemaError(f"capture_id duplicados: {sorted(set(dupes))}")


def verify_no_future_reads(
    read_timestamps: Iterable[Any],
    t0: Any,
) -> None:
    """Assert todos los ts leídos por el detector son ≤ t0.

    Cycle 0: callable listo para mocks; Cycle 1 wire al detector real.
    """
    t0_dt = _parse_t0(t0)
    bad: list[str] = []
    for raw in read_timestamps:
        ts = _parse_t0(raw) if not isinstance(raw, datetime) else (
            raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        )
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts > t0_dt:
            bad.append(ts.isoformat())
    if bad:
        raise CaptureSchemaError(f"lecturas post-T0: {bad}")
