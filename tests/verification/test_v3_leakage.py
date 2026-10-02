from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from verification.errors import LeakageError
from verification.leakage_v3 import (
    assert_feature_label_column_disjoint,
    assert_label_window_strictly_after_t0,
    assert_train_columns_whitelisted,
    fail_if_label_like_in_features,
)


def test_disjoint_ok():
    assert_feature_label_column_disjoint(["mc0", "age_s"], ["hit_10x_24h"])


def test_disjoint_fail():
    with pytest.raises(LeakageError, match="columnas"):
        assert_feature_label_column_disjoint(["mc0", "hit_10x_24h"], ["hit_10x_24h"])


def test_adversarial_max_mc():
    with pytest.raises(LeakageError, match="label-like"):
        fail_if_label_like_in_features(["curve_progress", "max_mc_24h"])


def test_whitelist():
    with pytest.raises(LeakageError, match="whitelist"):
        assert_train_columns_whitelisted(["mc0", "sneaky"], ["mc0"])


def test_label_window():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert_label_window_strictly_after_t0([t0 + timedelta(seconds=1)], t0=t0)
    with pytest.raises(LeakageError, match="ts ≤ t0"):
        assert_label_window_strictly_after_t0([t0], t0=t0)
