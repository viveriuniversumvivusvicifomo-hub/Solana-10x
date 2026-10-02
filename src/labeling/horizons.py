"""Horizontes de label (Cycle 0).

PRIMARY_HORIZON frozen por Sinck = 30d (hit_10x_30d).
Secundarias: 1h / 6h / 24h / 7d.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

# Nombre corto -> timedelta (PRIMARY + secundarias)
LABEL_HORIZONS: Final[dict[str, timedelta]] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}

PRIMARY_HORIZON: Final[str] = "30d"  # FROZEN Sinck 2026-09-29

HIT_10X_MULTIPLE: Final[float] = 10.0

LABEL_SCHEMA_VERSION: Final[str] = "labels.v0.1"

SECONDARY_HORIZONS: Final[tuple[str, ...]] = ("1h", "6h", "24h", "7d")


def hit_10x_column(horizon: str) -> str:
    if horizon not in LABEL_HORIZONS:
        raise KeyError(f"horizonte desconocido: {horizon!r}; válidos={sorted(LABEL_HORIZONS)}")
    return f"hit_10x_{horizon}"


def max_multiple_column(horizon: str) -> str:
    if horizon not in LABEL_HORIZONS:
        raise KeyError(f"horizonte desconocido: {horizon!r}")
    return f"max_multiple_{horizon}"


def max_mc_column(horizon: str) -> str:
    if horizon not in LABEL_HORIZONS:
        raise KeyError(f"horizonte desconocido: {horizon!r}")
    return f"max_mc_{horizon}"


def all_hit_10x_columns() -> tuple[str, ...]:
    return tuple(hit_10x_column(h) for h in LABEL_HORIZONS)


# Columnas de la tabla labels.v0.1 (separada del feature store)
LABEL_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        *all_hit_10x_columns(),
        *(max_multiple_column(h) for h in LABEL_HORIZONS),
        *(max_mc_column(h) for h in LABEL_HORIZONS),
        "time_to_10x",
        "time_to_migration",
        "migrated",
        "migrated_24h",
        "rug_class",
        "dump_class",
        "organic_class",
    }
)
