from __future__ import annotations

from features import P0_FEATURE_NAMES
from labeling import LABEL_COLUMNS
from verification.leakage_v3 import assert_feature_label_column_disjoint, fail_if_label_like_in_features


def test_p0_disjoint_from_labels():
    assert_feature_label_column_disjoint(P0_FEATURE_NAMES, LABEL_COLUMNS)
    fail_if_label_like_in_features(P0_FEATURE_NAMES)


def test_p0_has_core_mvp():
    for name in (
        "mc_usd_t0",
        "price_usd_t0",
        "age_s",
        "holder_count",
        "buy_count_60s",
        "net_flow_sol_5m",
        "mint_authority_none",
        "creator_prior_mints_7d",
    ):
        assert name in P0_FEATURE_NAMES
