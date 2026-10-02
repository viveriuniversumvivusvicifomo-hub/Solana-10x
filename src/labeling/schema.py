"""Schema de la tabla labels.v0 — nunca merge automático a X_train."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping

from labeling.horizons import LABEL_SCHEMA_VERSION, PRIMARY_HORIZON


@dataclass(frozen=True, slots=True)
class LabelRecord:
    """Una fila de labels por capture_id.

    Campos hit_10x_* / max_multiple_* se rellenan por horizonte.
    Precios usados para calcular deben tener ts estrictamente > t0 (V3).
    """

    capture_id: str
    mint: str
    t0: datetime
    p0: float
    primary_horizon: str = PRIMARY_HORIZON
    schema_version: str = LABEL_SCHEMA_VERSION
    # Dict horizon_key -> bool|float|None (p.ej. {"30d": True})
    hit_10x: Mapping[str, bool | None] = field(default_factory=dict)
    max_multiple: Mapping[str, float | None] = field(default_factory=dict)
    max_mc: Mapping[str, float | None] = field(default_factory=dict)
    time_to_10x_s: float | None = None
    time_to_migration_s: float | None = None
    migrated: bool | None = None
    price_source: str = "unset"
    notes: str = ""

    def flat_columns(self) -> dict[str, Any]:
        """Columnas planas para parquet/CSV (sin merge a features)."""
        out: dict[str, Any] = {
            "capture_id": self.capture_id,
            "mint": self.mint,
            "t0": self.t0.isoformat(),
            "p0": self.p0,
            "primary_horizon": self.primary_horizon,
            "schema_version": self.schema_version,
            "time_to_10x": self.time_to_10x_s,
            "time_to_migration": self.time_to_migration_s,
            "migrated": self.migrated,
            "price_source": self.price_source,
        }
        for h, v in self.hit_10x.items():
            out[f"hit_10x_{h}"] = v
        for h, v in self.max_multiple.items():
            out[f"max_multiple_{h}"] = v
        for h, v in self.max_mc.items():
            out[f"max_mc_{h}"] = v
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["t0"] = self.t0.isoformat()
        return d
