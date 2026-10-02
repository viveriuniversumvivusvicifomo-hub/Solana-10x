"""Lite logistic + multi-scorer skeleton tests (no Dune / no live network)."""

from __future__ import annotations

from features.post_q5_sets import FEATURE_SETS, LITE_COLS
from paper_live.multi_score import MultiPaperScorer
from paper_live.score_lite import LiteScorer, phi_lite, required_lite_present


def test_lite_cols_in_feature_sets():
    assert "lite" in FEATURE_SETS
    assert list(FEATURE_SETS["lite"]) == list(LITE_COLS)
    assert len(LITE_COLS) == 9


def test_lite_skips_missing_buy_vol():
    sc = LiteScorer()
    r = sc.score({"sniper_vol_share_5s": 0.2})
    assert r.skipped
    assert r.mode == "skip_missing_buy_vol"


def test_lite_logistic_in_unit_interval():
    feats = {
        "buy_vol_usd_60s": 2500.0,
        "sniper_vol_share_5s": 0.15,
        "top1_buyer_vol_share": 0.2,
        "top5_buyer_vol_share": 0.45,
        "age_s": 120.0,
        "progress_curve_proxy": 0.3,
        "net_sol_curve": 20.0,
        "creator_prior_mints_7d": 0,
        "creator_prior_mints_30d": 1,
    }
    assert required_lite_present(feats)
    phi = phi_lite(feats)
    assert set(phi) == set(LITE_COLS)
    r = LiteScorer().score(feats)
    assert not r.skipped
    assert r.mode == "lite_logistic_v0"
    assert 0.0 <= r.score <= 1.0


def test_multi_scorer_runs_histgb_and_lite_lanes():
    feats = {
        "buy_vol_usd_60s": 1000.0,
        "sniper_vol_share_5s": 0.1,
        "top1_buyer_vol_share": 0.1,
        "top5_buyer_vol_share": 0.2,
        "age_s": 60.0,
        "progress_curve_proxy": 0.1,
        "net_sol_curve": 5.0,
        "creator_prior_mints_7d": 0,
        "creator_prior_mints_30d": 0,
        # histgb will skip incomplete +q5b — that is expected
        "buy_count_total": None,
    }
    ms = MultiPaperScorer(
        "histgb_q5b,lite",
        primary_lane="histgb_q5b",
        thresholds={"histgb_q5b": 0.9, "lite": 0.55},
    )
    out = ms.score_all(feats)
    assert "histgb_q5b" in out.lanes
    assert "lite" in out.lanes
    assert out.lanes["lite"].skipped is False
    assert out.lanes["histgb_q5b"].skipped is True  # incomplete q5b
    doc = out.as_scores_json()
    assert doc["lite"]["pass"] in (True, False)
    assert doc["histgb_q5b"]["skipped"] is True


def test_multi_primary_only_default():
    ms = MultiPaperScorer("rule_buy60", thresholds={"rule_buy60": None})
    out = ms.score_all({"buy_vol_usd_60s": 42.0})
    assert list(out.lanes) == ["rule_buy60"]
    assert out.lanes["rule_buy60"].score == 42.0
