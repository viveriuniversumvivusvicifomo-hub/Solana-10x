from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backtest import (
    CURVE_FEE_BPS,
    CaptureRef,
    build_single_fold,
    default_embargo,
    fill_price_after_fee,
    purge_train_overlapping_val,
)
from labeling import PRIMARY_HORIZON
from verification.errors import WalkForwardError


def _c(i: int, day: int, month: int = 1, mint: str | None = None) -> CaptureRef:
    return CaptureRef(
        capture_id=f"c{i}",
        mint=mint or f"m{i}",
        t0=datetime(2024, month, day, 12, 0, 0, tzinfo=timezone.utc),
    )


def test_default_embargo_is_30d():
    assert PRIMARY_HORIZON == "30d"
    assert default_embargo() == timedelta(days=30)


def test_build_fold_primary_30d():
    # train ene; val marzo (gap > 30d); test mayo
    caps = [
        _c(1, 1),
        _c(2, 5),
        _c(3, 10, month=3),
        _c(4, 15, month=3),
        _c(5, 20, month=5),
    ]
    fold = build_single_fold(
        caps,
        train_end=datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc),
        val_end=datetime(2024, 3, 20, 0, 0, 0, tzinfo=timezone.utc),
        test_end=datetime(2024, 5, 25, 0, 0, 0, tzinfo=timezone.utc),
        # default label_horizon = PRIMARY = 30d
    )
    assert fold.label_horizon == "30d"
    assert fold.embargo == timedelta(days=30)
    assert {c.capture_id for c in fold.train} == {"c1", "c2"}
    assert {c.capture_id for c in fold.val} == {"c3", "c4"}
    assert {c.capture_id for c in fold.test} == {"c5"}


def test_build_fold_secondary_24h():
    caps = [
        _c(1, 1),
        _c(2, 2),
        _c(3, 5),
        _c(4, 6),
        _c(5, 10),
    ]
    fold = build_single_fold(
        caps,
        train_end=datetime(2024, 1, 2, 23, 0, 0, tzinfo=timezone.utc),
        val_end=datetime(2024, 1, 7, 0, 0, 0, tzinfo=timezone.utc),
        test_end=datetime(2024, 1, 12, 0, 0, 0, tzinfo=timezone.utc),
        label_horizon="24h",
    )
    assert fold.embargo == timedelta(hours=24)
    assert {c.capture_id for c in fold.train} == {"c1", "c2"}
    assert {c.capture_id for c in fold.val} == {"c3", "c4"}
    assert {c.capture_id for c in fold.test} == {"c5"}


def test_purge_removes_overlapping_label_window():
    train = [
        _c(1, 1),
        CaptureRef("near", "mx", datetime(2024, 1, 4, 18, 0, 0, tzinfo=timezone.utc)),
    ]
    val_start = datetime(2024, 1, 5, 12, 0, 0, tzinfo=timezone.utc)
    kept = purge_train_overlapping_val(
        train, val_start=val_start, label_horizon=timedelta(hours=24)
    )
    assert {c.capture_id for c in kept} == {"c1"}


def test_mint_cannot_cross_splits():
    caps = [
        CaptureRef("c1", "SAME", datetime(2024, 1, 1, tzinfo=timezone.utc)),
        CaptureRef("c2", "SAME", datetime(2024, 3, 5, tzinfo=timezone.utc)),
    ]
    with pytest.raises(WalkForwardError, match="splits"):
        build_single_fold(
            caps,
            train_end=datetime(2024, 1, 2, tzinfo=timezone.utc),
            val_end=datetime(2024, 3, 10, tzinfo=timezone.utc),
        )


def test_fill_fee():
    assert fill_price_after_fee(100.0) == pytest.approx(100.0 * (1 + CURVE_FEE_BPS / 10_000))
