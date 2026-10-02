"""Labeling — outcomes calculados solo con precios/trades estrictamente > T0.

Contrato
--------
- Tabla ``labels`` separada del feature store.
- Horizontes: PRIMARY frozen = 30d; secundarias 1h/6h/24h/7d.
- Nunca merge automático hacia X_train.
- ``hit_10x_*`` vía ``materialize_label_record`` / ``compute_hit_10x_for_horizon``.

Verification hooks
------------------
- ``assert_label_window_strictly_after_t0`` (V3)
- ``assert_feature_label_column_disjoint`` (V3)
"""

from labeling.hit_10x import compute_hit_10x_for_horizon, materialize_label_record
from labeling.from_sample import LabelBatchReport, write_report_from_sample
from labeling.horizons import (
    HIT_10X_MULTIPLE,
    LABEL_COLUMNS,
    LABEL_HORIZONS,
    LABEL_SCHEMA_VERSION,
    PRIMARY_HORIZON,
    SECONDARY_HORIZONS,
    all_hit_10x_columns,
    hit_10x_column,
    max_mc_column,
    max_multiple_column,
)
from labeling.schema import LabelRecord

__all__ = [
    "HIT_10X_MULTIPLE",
    "LABEL_COLUMNS",
    "LABEL_HORIZONS",
    "LABEL_SCHEMA_VERSION",
    "PRIMARY_HORIZON",
    "SECONDARY_HORIZONS",
    "LabelRecord",
    "all_hit_10x_columns",
    "compute_hit_10x_for_horizon",
    "hit_10x_column",
    "materialize_label_record",
    "LabelBatchReport",
    "write_report_from_sample",
    "max_mc_column",
    "max_multiple_column",
]
