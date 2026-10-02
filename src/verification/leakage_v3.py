"""V3 — label leakage: features ∩ labels = ∅; whitelist train."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from verification.errors import LeakageError

# Prefijos / nombres que nunca pueden entrar al feature matrix
LABEL_LIKE_PREFIXES: tuple[str, ...] = (
    "hit_10x",
    "max_mc_",
    "max_multiple",
    "time_to_10x",
    "time_to_migration",
    "migrated",
    "label_",
)

def _default_label_columns() -> frozenset[str]:
    """Usa LABEL_COLUMNS de labeling (incluye hit_10x_30d); fallback si no hay paquete."""
    try:
        from labeling.horizons import LABEL_COLUMNS

        return frozenset(LABEL_COLUMNS) | {"hit_10x"}
    except ImportError:
        return frozenset(
            {
                "hit_10x",
                "hit_10x_1h",
                "hit_10x_6h",
                "hit_10x_24h",
                "hit_10x_7d",
                "hit_10x_30d",
                "max_mc_24h",
                "max_mc_30d",
                "max_multiple_24h",
                "max_multiple_30d",
                "time_to_10x",
                "migrated",
                "migrated_24h",
                "rug_class",
                "dump_class",
                "organic_class",
            }
        )


DEFAULT_LABEL_COLUMNS: frozenset[str] = _default_label_columns()


def assert_feature_label_column_disjoint(
    feature_columns: Iterable[str],
    label_columns: Iterable[str] | None = None,
) -> None:
    feats = set(feature_columns)
    labels = set(label_columns) if label_columns is not None else set(DEFAULT_LABEL_COLUMNS)
    overlap = sorted(feats & labels)
    if overlap:
        raise LeakageError(f"columnas en features y labels: {overlap}")


def fail_if_label_like_in_features(feature_columns: Iterable[str]) -> None:
    """Test adversario: cualquier nombre label-like en features → fail."""
    bad = sorted(
        c
        for c in feature_columns
        if c in DEFAULT_LABEL_COLUMNS or any(c.startswith(p) for p in LABEL_LIKE_PREFIXES)
    )
    if bad:
        raise LeakageError(f"label-like en feature frame: {bad}")


def assert_train_columns_whitelisted(
    train_columns: Iterable[str],
    whitelist: Iterable[str],
) -> None:
    allowed = set(whitelist)
    unexpected = sorted(set(train_columns) - allowed)
    if unexpected:
        raise LeakageError(f"columnas train fuera de whitelist P0/P1: {unexpected}")


def assert_label_window_strictly_after_t0(
    label_price_timestamps: Sequence[Any],
    *,
    t0: Any,
) -> None:
    """Todos los precios usados para label deben tener ts > t0."""
    if isinstance(t0, datetime):
        t0_dt = t0 if t0.tzinfo else t0.replace(tzinfo=timezone.utc)
    else:
        t0_dt = datetime.fromisoformat(str(t0).replace("Z", "+00:00"))
        if t0_dt.tzinfo is None:
            raise LeakageError("t0 debe ser timezone-aware")
    t0_dt = t0_dt.astimezone(timezone.utc)

    bad: list[str] = []
    for raw in label_price_timestamps:
        if isinstance(raw, datetime):
            ts = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            raise LeakageError("label price ts sin timezone")
        ts = ts.astimezone(timezone.utc)
        if ts <= t0_dt:
            bad.append(ts.isoformat())
    if bad:
        raise LeakageError(f"precios de label con ts ≤ t0: {bad}")
