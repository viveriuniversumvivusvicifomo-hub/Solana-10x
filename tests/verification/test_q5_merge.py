"""Gates for Q5 merge protocol / anti look-ahead."""

from __future__ import annotations

from features.post_q5_sets import FEATURE_SETS, assert_sets_safe
from verification.q5_merge import assert_no_leak_columns, audit_feature_sets, run_q5_qa


def test_feature_sets_exclude_creator_and_labels() -> None:
    assert_sets_safe()
    for cols in FEATURE_SETS.values():
        assert "creator_pubkey" not in cols
        assert "create_ts" not in cols
        assert "hit_200k" not in cols
        assert "max_mc_after_t0" not in cols
        assert "migrated_pre_t0" not in cols


def test_leak_regex_on_labelish() -> None:
    assert assert_no_leak_columns(["buy_vol_usd_60s", "mc_usd_t0"], where="features:x") == []
    assert "hit_200k" in assert_no_leak_columns(["hit_200k"], where="features:x")
    assert "max_mc_after_t0" in assert_no_leak_columns(["max_mc_after_t0"], where="features:x")


def test_audit_sets_clean() -> None:
    info = audit_feature_sets()
    assert info["banned_hits"] == []


def test_run_q5_qa_smoke() -> None:
    # Partial Q5 may soft-fail coverage / migrated_rate; hard gates should hold on keys/leaks.
    r = run_q5_qa(write_report=True)
    assert "checks" in r
    assert r["merge_protocol"]["creator_pubkey_in_X"] is False
    hard = set(r.get("hard_fails") or [])
    # These must never hard-fail if files exist
    for name in (
        "feature_sets.safe",
        "expand.leak_cols",
    ):
        assert name not in hard
