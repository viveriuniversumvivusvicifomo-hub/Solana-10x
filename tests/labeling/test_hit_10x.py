from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from labeling import (
    LABEL_COLUMNS,
    LABEL_HORIZONS,
    PRIMARY_HORIZON,
    compute_hit_10x_for_horizon,
    hit_10x_column,
    materialize_label_record,
)
from verification.errors import LeakageError
from verification.leakage_v3 import assert_feature_label_column_disjoint


def test_primary_frozen_30d():
    assert PRIMARY_HORIZON == "30d"
    assert "30d" in LABEL_HORIZONS
    assert hit_10x_column("30d") == "hit_10x_30d"


def test_hit_true_within_horizon():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    p0 = 1.0
    prices = [
        (t0 + timedelta(minutes=10), 2.0),
        (t0 + timedelta(hours=2), 12.0),
    ]
    hit, mult, tto = compute_hit_10x_for_horizon(
        t0=t0, p0=p0, horizon=timedelta(hours=6), prices=prices
    )
    assert hit is True
    assert mult == pytest.approx(12.0)
    assert tto == pytest.approx(2 * 3600)


def test_hit_false_and_empty():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    hit, mult, tto = compute_hit_10x_for_horizon(
        t0=t0,
        p0=1.0,
        horizon=timedelta(hours=1),
        prices=[(t0 + timedelta(minutes=30), 3.0)],
    )
    assert hit is False
    assert mult == pytest.approx(3.0)
    assert tto is None

    hit2, mult2, tto2 = compute_hit_10x_for_horizon(
        t0=t0, p0=1.0, horizon=timedelta(hours=1), prices=[]
    )
    assert hit2 is None and mult2 is None and tto2 is None


def test_rejects_price_at_or_before_t0():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(LeakageError):
        compute_hit_10x_for_horizon(
            t0=t0,
            p0=1.0,
            horizon=timedelta(hours=1),
            prices=[(t0, 20.0)],
        )


def test_materialize_primary_30d():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    rec = materialize_label_record(
        capture_id="c1",
        mint="Mint111",
        t0=t0,
        p0=0.5,
        prices=[(t0 + timedelta(hours=3), 6.0)],  # 12x dentro de 30d
    )
    flat = rec.flat_columns()
    assert rec.primary_horizon == "30d"
    assert flat[hit_10x_column(PRIMARY_HORIZON)] is True
    assert flat["hit_10x_1h"] is None  # fuera de ventana 1h
    assert flat["hit_10x_7d"] is True
    assert_feature_label_column_disjoint(["mc_usd_t0", "age_s"], LABEL_COLUMNS)
