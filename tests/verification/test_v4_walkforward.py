from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from verification.errors import WalkForwardError
from verification.walkforward_v4 import assert_mint_single_split, assert_walk_forward_order


def test_order_and_embargo():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    train = [t0, t0 + timedelta(hours=1)]
    val = [t0 + timedelta(hours=5)]
    assert_walk_forward_order(train_t0s=train, val_t0s=val, embargo=timedelta(hours=2))
    with pytest.raises(WalkForwardError, match="embargo"):
        assert_walk_forward_order(
            train_t0s=train,
            val_t0s=[t0 + timedelta(hours=2)],
            embargo=timedelta(hours=2),
        )


def test_mint_single_split():
    assert_mint_single_split(
        [{"mint": "a", "split": "train"}, {"mint": "b", "split": "val"}]
    )
    with pytest.raises(WalkForwardError, match="splits"):
        assert_mint_single_split(
            [{"mint": "a", "split": "train"}, {"mint": "a", "split": "val"}]
        )
