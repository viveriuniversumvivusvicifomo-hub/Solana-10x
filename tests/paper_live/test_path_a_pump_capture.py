"""Path A live captura = Pump MC band + age (no Helius trade-refine gate)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ingestion.t0_capture import (
    find_t0_pump_mc_sighting,
    is_scoreable_pump_capture,
    score_reject_reason_pump,
)
from paper_live.config import SAMPLE_PUMP, PaperLiveConfig
from paper_live.feed import MintSighting, poll_sample
from paper_live.pump_enrich import enrich_pump_for_sightings
from paper_live.score import PaperScorer


def test_pump_mc_sighting_scoreable_without_trades():
    t0 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    create = t0 - timedelta(seconds=90)
    cap = find_t0_pump_mc_sighting(
        sighting_t0=t0, sighting_mc=12_500.0, create_ts=create
    )
    assert cap.refined is True
    assert cap.definition.startswith("pump_mc_band")
    assert is_scoreable_pump_capture(cap) is True
    assert score_reject_reason_pump(cap) is None


def test_pump_mc_sighting_rejects_out_of_band_and_old_age():
    t0 = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    cap_hi = find_t0_pump_mc_sighting(
        sighting_t0=t0, sighting_mc=50_000.0, create_ts=t0 - timedelta(seconds=60)
    )
    assert is_scoreable_pump_capture(cap_hi) is False
    cap_old = find_t0_pump_mc_sighting(
        sighting_t0=t0,
        sighting_mc=12_000.0,
        create_ts=t0 - timedelta(days=3),
    )
    assert is_scoreable_pump_capture(cap_old) is False
    assert "age_gt_max" in (cap_old.detail or "")


def test_enrich_pump_sets_capture_scoreable_true_no_helius():
    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump sample missing")
    sightings = poll_sample(SAMPLE_PUMP, batch=2, source="dry_run.pump_sample")
    results = enrich_pump_for_sightings(
        sightings, fetch_priors=False, fetch_trades=False, dry_run=True
    )
    assert results
    for s in sightings:
        vr = results[s.mint]
        assert vr.capture_scoreable is True
        assert vr.features["capture_scoreable"] is True
        assert vr.t0_refined is True
        assert vr.features.get("helius_trade_refine_required") is False
        assert "no_trade_mc_path" not in str(vr.score_reject)
        assert "no_trade_mc_path" not in "".join(vr.gaps)


def test_scorer_does_not_skip_capture_not_scoreable_on_pump_enrich():
    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump sample missing")
    sightings = poll_sample(SAMPLE_PUMP, batch=1, source="dry_run.pump_sample")
    results = enrich_pump_for_sightings(
        sightings, fetch_priors=False, fetch_trades=False, dry_run=True
    )
    vr = results[sightings[0].mint]
    sc = PaperScorer(mode="histgb_q5b", require_t0_refined=False)
    r = sc.score(vr.features)
    assert r.mode != "skip_capture_not_scoreable"
    # May still skip_missing_buy_vol / incomplete_q5b — honest Pump trades gap
    assert r.mode in (
        "skip_missing_buy_vol",
        "skip_incomplete_q5b",
        "skip_prior_not_train",
        "skip_missing_model",
        "histgb_q5b",
    ), r.mode


def test_dry_run_pump_path_a_no_no_trade_mc_skip(tmp_path: Path):
    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump sample missing")
    from paper_live.loop import PaperLiveRunner

    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        feed="pump",
        enrich_via="pump",
        cycles=1,
        top_k=3,
        data_dir=tmp_path,
        sample_path=SAMPLE_PUMP,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="histgb_q5b",
        require_t0_refined=False,
        allow_q5b_fallback=False,
        entry_rule="topk_batch",
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["enrich_via"] == "pump"
    assert summary["cycles_run"] == 1
    # Ensure we did not gate on Helius no_trade_mc_path
    # (skip reasons may be missing buy_vol — OK)


def test_parse_pump_frontend_trades_indexed_schema():
    """2026-10 /trades/{chainId}/{mint} nested payload → TradeRow + buy_vol."""
    from paper_live.pump_enrich import buy_vol_60s_from_trades, parse_pump_frontend_trades

    t0 = datetime(2026, 10, 2, 6, 15, tzinfo=timezone.utc)
    t0_ms = int(t0.timestamp() * 1000)
    rows = [
        {
            "blockTimeMs": t0_ms - 10_000,
            "side": "buy",
            "valueUsd": "42.5",
            "valueNative": "0.35",
            "trader": {"address": "Buyer1111111111111111111111111111111111111"},
            "baseAmount": {"raw": "1000000", "decimals": 6},
            "quoteAmount": {"raw": "350000000", "decimals": 9},
            "quote": {"id": "11111111111111111111111111111111"},
        },
        {
            "blockTimeMs": t0_ms - 5_000,
            "side": "sell",
            "valueUsd": "10",
            "valueNative": "0.08",
            "trader": {"address": "Seller111111111111111111111111111111111111"},
            "baseAmount": {"raw": "2000000", "decimals": 6},
            "quoteAmount": {"raw": "80000000", "decimals": 9},
            "quote": {"id": "11111111111111111111111111111111"},
        },
        {
            "blockTimeMs": t0_ms + 1_000,  # post-T0 — drop
            "side": "buy",
            "valueUsd": "999",
            "valueNative": "8",
            "trader": {"address": "Late11111111111111111111111111111111111111"},
        },
    ]
    trades = parse_pump_frontend_trades(rows, mint="MintPumpxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump", t0=t0)
    assert len(trades) == 2
    assert trades[0].side == "buy"
    assert trades[0].amount_usd == 42.5
    assert abs(trades[0].sol_amt - 0.35) < 1e-9
    assert trades[0].trader_id.startswith("Buyer")
    assert trades[1].side == "sell"
    vol, n = buy_vol_60s_from_trades(trades, t0)
    assert n == 1
    assert abs(vol - 42.5) < 1e-9


def test_enrich_pump_stamps_creator_prior_source_when_fetch_priors(monkeypatch):
    """With local store, pump enrich stamps dune_cohort_* (train family) — not Pump."""
    from datetime import datetime, timedelta, timezone
    from paper_live.creator_priors import (
        CREATOR_PRIOR_SOURCE_EMPTY,
        CREATOR_PRIOR_SOURCE_EXACT,
        CREATOR_PRIOR_SOURCE_RECOMPUTE,
        CREATOR_PRIOR_SOURCE_TRAIN,
        CreatorPriorIndex,
    )
    from paper_live.feed import MintSighting
    from paper_live.q5b_agg import CreateRow
    from verification.live_parity import prior_source_is_train

    creator = "CreatorPathAPumpCapture1111111111111111111"
    as_of = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    idx = CreatorPriorIndex(
        by_creator={
            creator: [
                CreateRow(
                    mint="priorA",
                    creator_pubkey=creator,
                    create_ts=as_of - timedelta(days=3),
                )
            ]
        },
        n_rows=1,
        source=CREATOR_PRIOR_SOURCE_TRAIN,
        path="/fake",
    )
    monkeypatch.setattr(
        "paper_live.pump_enrich.load_creator_prior_index", lambda *a, **k: idx
    )
    monkeypatch.setattr(
        "paper_live.creator_priors.load_creator_prior_index", lambda *a, **k: idx
    )
    mint = "PathAPumpMintNotInStore444444444444444444444"
    t0 = as_of + timedelta(seconds=80)
    s = MintSighting(
        mint=mint,
        mc_usd=11_000.0,
        name="P",
        symbol="P",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw={
            "creator": creator,
            "created_timestamp": int(as_of.timestamp() * 1000),
            "usd_market_cap": 11_000.0,
            "complete": False,
        },
    )
    results = enrich_pump_for_sightings(
        [s], fetch_priors=True, fetch_trades=False, dry_run=True
    )
    src = results[mint].features["creator_prior_source"]
    assert src in (
        CREATOR_PRIOR_SOURCE_RECOMPUTE,
        CREATOR_PRIOR_SOURCE_EMPTY,
        CREATOR_PRIOR_SOURCE_EXACT,
    )
    assert results[mint].features["creator_priors_incomplete"] is False
    assert prior_source_is_train(src)


def test_pump_enrich_keeps_trade_curve_and_age_proxy_when_trades_present(tmp_path: Path):
    """Coin overlay must NOT overwrite q5a_agg curve / age_proxy when trades exist.

    Residual ranks #2/#3 (2026-10-02): live was overwriting progress_curve_proxy /
    net_sol_curve from Pump coin and age_proxy_s ← age_s (create→T0). Train Q5a
    uses trade net_sol/85 and t0−first_trade.
    """
    from ingestion.pump_constants import INITIAL_REAL_TOKEN_RESERVES
    from paper_live.feed import MintSighting
    from paper_live.pump_enrich import enrich_pump_for_sightings

    mint = "MintCurveAgePatchxxxxxxxxxxxxxxxxxxxxxxxxxxpump"
    create_ts = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    t0 = create_ts + timedelta(seconds=120)  # age_s = 120
    first_trade = t0 - timedelta(seconds=40)  # age_proxy_s should be 40
    t0_ms = int(t0.timestamp() * 1000)
    first_ms = int(first_trade.timestamp() * 1000)

    # Coin reserves imply progress≈0.5 and net_sol≈42 — must NOT win over trades
    coin_progress_rt = int(INITIAL_REAL_TOKEN_RESERVES * 0.5)
    coin_sol_lamports = 42 * 1_000_000_000

    fixture = {
        "by_mint": {
            mint: [
                {
                    "blockTimeMs": first_ms,
                    "side": "buy",
                    "valueUsd": "100",
                    "valueNative": "3.0",  # trade net_sol_curve = 3 → progress 3/85
                    "trader": {"address": "BuyerCurveAge11111111111111111111111111111"},
                    "quote": {"id": "11111111111111111111111111111111"},
                },
                {
                    "blockTimeMs": t0_ms - 5_000,
                    "side": "buy",
                    "valueUsd": "50",
                    "valueNative": "1.5",
                    "trader": {"address": "BuyerCurveAge22222222222222222222222222222"},
                    "quote": {"id": "11111111111111111111111111111111"},
                },
            ]
        }
    }
    fixture_path = tmp_path / "trades_fixture.json"
    fixture_path.write_text(__import__("json").dumps(fixture))

    sighting = MintSighting(
        mint=mint,
        mc_usd=12_500.0,
        name="CurveAge",
        symbol="CA",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw={
            "creator": "CreatorCurveAgePatch111111111111111111111",
            "created_timestamp": int(create_ts.timestamp() * 1000),
            "usd_market_cap": 12_500.0,
            "complete": False,
            "real_token_reserves": coin_progress_rt,
            "real_sol_reserves": coin_sol_lamports,
        },
    )
    results = enrich_pump_for_sightings(
        [sighting],
        fetch_priors=False,
        fetch_trades=True,
        trades_fixture_path=fixture_path,
        dry_run=True,
        sol_usd=150.0,
    )
    feats = results[mint].features
    age_s = feats.get("age_s")
    age_proxy = feats.get("age_proxy_s")
    assert age_s == pytest.approx(120.0, abs=1.0)
    # Trade-derived: t0 − first_trade = 40s — NOT create age
    assert age_proxy == pytest.approx(40.0, abs=1.0)
    assert age_proxy != pytest.approx(age_s, abs=1.0)
    # Trade net_sol = 3.0 + 1.5 = 4.5 (both pumpdotfun default)
    assert feats["net_sol_curve"] == pytest.approx(4.5, rel=1e-3)
    assert feats["progress_curve_proxy"] == pytest.approx(4.5 / 85.0, rel=1e-3)
    # Must not be coin overlay (~0.5 / 42)
    assert feats["progress_curve_proxy"] != pytest.approx(0.5, abs=0.05)
    assert feats["net_sol_curve"] != pytest.approx(42.0, abs=1.0)
    assert feats["q5a_curve_age_source"] == "q5a_trades"
    assert results[mint].n_trades_pre_t0 == 2


def test_pump_enrich_coin_overlay_gapfill_when_no_trades():
    """Without trades, coin curve + age_s→age_proxy gap-fill is allowed."""
    from ingestion.pump_constants import INITIAL_REAL_TOKEN_RESERVES
    from paper_live.feed import MintSighting
    from paper_live.pump_enrich import enrich_pump_for_sightings

    mint = "MintNoTradesGapfillxxxxxxxxxxxxxxxxxxxxxxxpump"
    create_ts = datetime(2026, 10, 2, 11, 0, 0, tzinfo=timezone.utc)
    t0 = create_ts + timedelta(seconds=90)
    coin_progress_rt = int(INITIAL_REAL_TOKEN_RESERVES * 0.25)  # progress ≈ 0.75
    coin_sol_lamports = 17 * 1_000_000_000

    sighting = MintSighting(
        mint=mint,
        mc_usd=10_000.0,
        name="NoTrades",
        symbol="NT",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw={
            "creator": "CreatorNoTradesGapfill11111111111111111111",
            "created_timestamp": int(create_ts.timestamp() * 1000),
            "usd_market_cap": 10_000.0,
            "complete": False,
            "real_token_reserves": coin_progress_rt,
            "real_sol_reserves": coin_sol_lamports,
        },
    )
    results = enrich_pump_for_sightings(
        [sighting], fetch_priors=False, fetch_trades=False, dry_run=True
    )
    feats = results[mint].features
    assert feats["q5a_curve_age_source"] == "pump_coin_gapfill"
    assert feats["progress_curve_proxy"] == pytest.approx(0.75, abs=0.01)
    assert feats["net_sol_curve"] == pytest.approx(17.0, abs=0.01)
    assert feats["age_proxy_s"] == pytest.approx(feats["age_s"], abs=1.0)
    assert results[mint].n_trades_pre_t0 == 0
