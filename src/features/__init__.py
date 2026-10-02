"""Features — vector MVP estrictamente ≤ T0.

Contrato
--------
- 1 fila por ``capture_id``.
- Whitelist P0 según cycle0/feature-set-mvp.md (``P0_FEATURE_NAMES``).
- Joins solo asof backward; cada columna con feature_ts ≤ t0.
- Prohibido: columnas post-T0 y cualquier label-like.

Verification hooks
------------------
- ``assert_all_feature_ts_leq_t0`` (V2)
- ``assert_no_label_columns`` / ``fail_if_label_like_in_features`` (V3)
- ``assert_staleness`` (V2)
"""

from features.p0_min_from_export import materialize_cohort, materialize_row
from features.whitelist import (
    FEATURE_META_COLUMNS,
    FEATURE_SET_VERSION,
    P0_FEATURE_NAMES,
)

__all__ = [
    "FEATURE_META_COLUMNS",
    "FEATURE_SET_VERSION",
    "P0_FEATURE_NAMES",
    "materialize_cohort",
    "materialize_row",
]
