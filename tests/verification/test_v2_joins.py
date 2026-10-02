"""Gate dura: rechazar cualquier join / feature > T0."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from verification.errors import LookAheadError
from verification.joins_v2 import (
    assert_all_feature_ts_leq_t0,
    assert_asof_backward_only,
    assert_feature_rows_have_ts,
    assert_staleness,
)


T0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_accepts_feature_ts_leq_t0():
    rows = [
        {"feature_ts": T0 - timedelta(seconds=3)},
        {"feature_ts": T0},
    ]
    assert_all_feature_ts_leq_t0(rows, t0=T0)


def test_rejects_feature_ts_after_t0():
    rows = [{"feature_ts": T0 + timedelta(seconds=1)}]
    with pytest.raises(LookAheadError, match="join > T0"):
        assert_all_feature_ts_leq_t0(rows, t0=T0)


def test_rejects_slot_after_slot0():
    rows = [{"slot_feature": 101}]
    with pytest.raises(LookAheadError, match="slot"):
        assert_all_feature_ts_leq_t0(rows, t0=T0, slot0=100)


def test_rejects_latest_without_ts():
    with pytest.raises(LookAheadError, match="sin feature_ts"):
        assert_feature_rows_have_ts([{"holder_count": 10}])


def test_asof_forward_forbidden():
    with pytest.raises(LookAheadError, match="backward"):
        assert_asof_backward_only("forward")


def test_staleness_ok_and_fail():
    rows_ok = [{"feature_ts": T0 - timedelta(seconds=10)}]
    stats = assert_staleness(rows_ok, t0=T0, max_stale_fraction=0.5)
    assert stats["n"] == 1.0

    rows_stale = [{"feature_ts": T0 - timedelta(seconds=120)}]
    with pytest.raises(LookAheadError, match="stale"):
        assert_staleness(rows_stale, t0=T0, max_stale_fraction=0.0)
