"""Live ↔ train parity anti look-ahead gates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from features.post_q5_sets import FEATURE_SETS
from verification.live_parity import (
    assert_recipe_columns,
    assert_trades_leq_t0,
    assert_window_bounds,
    run_live_parity_qa,
)


def test_recipe_plus_q5b_clean() -> None:
    cols = list(FEATURE_SETS["+q5b"])
    assert len(cols) == 51
    assert assert_recipe_columns(cols) == []
    assert "migrated_pre_t0" not in cols


def test_trades_leq_t0() -> None:
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    assert assert_trades_leq_t0([{"ts": t0}, {"ts": t0 - timedelta(seconds=1)}], t0=t0) == []
    bad = assert_trades_leq_t0([{"ts": t0 + timedelta(seconds=1)}], t0=t0)
    assert len(bad) == 1


def test_window_bounds() -> None:
    t0 = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    assert assert_window_bounds([{"ts": t0.timestamp() - 10}], t0=t0, window_s=60) == []
    assert assert_window_bounds([{"ts": t0.timestamp() + 1}], t0=t0, window_s=60)


def test_run_live_parity_qa() -> None:
    r = run_live_parity_qa(write_report=True)
    assert r["n_train_cols"] == 51
    assert "q5a_agg.filters_post_t0" not in r["hard_fails"]


def test_prior_t0_umbral_gates() -> None:
    from verification.live_parity import (
        assert_prior_source_train,
        assert_t0_refined,
        assert_threshold_matches_config,
        audit_score_row_gates,
        load_live_entry_config,
        prior_source_is_train,
    )

    assert prior_source_is_train("dune_cohort_exact")
    assert prior_source_is_train("dune_cohort_recompute")
    assert prior_source_is_train("train_store_v1")
    assert not prior_source_is_train("pump_frontend_30d")
    assert not prior_source_is_train(None)
    assert assert_prior_source_train("pump_frontend_30d")
    assert not assert_t0_refined(True)
    assert assert_t0_refined(False)
    cfg = load_live_entry_config()
    assert cfg.get("score_threshold") == 0.99
    assert not assert_threshold_matches_config(0.99, config=cfg)
    assert assert_threshold_matches_config(0.999807, config=cfg)
    bad = audit_score_row_gates({"creator_prior_source": "pump_frontend_30d", "t0_refined": False})
    assert len(bad) >= 2
    ok = audit_score_row_gates({"creator_prior_source": "dune_cohort_exact", "t0_refined": True})
    assert ok == []


def test_scorer_skips_bad_prior_and_unrefined() -> None:
    from features.post_q5_sets import FEATURE_SETS
    from paper_live.score import PaperScorer

    # Optional Helius-style refine gate (opt-in flag) — Pump path sets refined itself
    sc = PaperScorer(mode="histgb_q5b", require_t0_refined=True)
    r = sc.score({"t0_refined": False, "creator_prior_source": "dune_cohort_exact"})
    assert r.mode == "skip_t0_not_refined"
    # Pump scoreable bypass when definition is pump_mc_band*
    r_pump = sc.score(
        {
            "t0_refined": False,
            "capture_scoreable": True,
            "t0_definition": "pump_mc_band_sighting_v1",
            "creator_prior_source": "dune_cohort_exact",
        }
    )
    assert r_pump.mode != "skip_t0_not_refined"
    feats = {c: 0.0 for c in FEATURE_SETS["+q5b"]}
    feats["t0_refined"] = True
    feats["capture_scoreable"] = True
    feats["creator_prior_source"] = "pump_frontend_30d"
    feats["buy_vol_usd_60s"] = 1.0
    r2 = sc.score(feats)
    assert r2.mode == "skip_prior_not_train"

