"""SolDatos parity hooks: Pyth gate, scoreable T0, age_from_create, trade parse."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ingestion.helius_trade_parse import parse_helius_enhanced_txs, trade_implied_mc_usd
from ingestion.q5b_age import AGE_MAX_SCOREABLE_S, age_s_from_create, filter_anomalous_age_features
from ingestion.sol_usd_oracle import (
    USD_RECALIB_PLAN,
    amount_usd_dune_compatible,
    is_pyth_source,
)
from ingestion.t0_capture import (
    CaptureT0,
    is_scoreable_capture,
    score_reject_reason,
)


def test_usd_recalib_plan_rejects_blind_scale():
    assert "6.6" in USD_RECALIB_PLAN["rejected"] or "6.6" in str(USD_RECALIB_PLAN)
    assert USD_RECALIB_PLAN["chosen"].startswith("A_")


def test_amount_usd_dune_compatible():
    assert amount_usd_dune_compatible(2.0, 100.0) == pytest.approx(200.0)


def test_is_pyth_source():
    assert is_pyth_source("pyth_asof")
    assert not is_pyth_source("jupiter")


def test_scoreable_capture_refuses_low_unrefined():
    t0 = datetime(2026, 9, 22, tzinfo=timezone.utc)
    low = CaptureT0(
        t0=t0,
        mc_usd=12000,
        capture_quality="LOW",
        sol_usd=118.0,
        sol_usd_source="coingecko_asof",
        n_trades_at_t0_window=0,
        tradeable_s=0.0,
        refined=False,
        detail="provisional",
    )
    assert is_scoreable_capture(low) is False
    assert score_reject_reason(low) is not None

    high = CaptureT0(
        t0=t0,
        mc_usd=12000,
        capture_quality="HIGH",
        sol_usd=118.0,
        sol_usd_source="pyth_asof",
        n_trades_at_t0_window=2,
        tradeable_s=30.0,
        refined=True,
        detail="ok",
    )
    assert is_scoreable_capture(high) is True
    assert score_reject_reason(high) is None

    med_jup = CaptureT0(
        t0=t0,
        mc_usd=12000,
        capture_quality="MED",
        sol_usd=118.0,
        sol_usd_source="jupiter",
        n_trades_at_t0_window=2,
        tradeable_s=30.0,
        refined=True,
        detail="ok",
    )
    assert is_scoreable_capture(med_jup, require_pyth=True) is False
    # Without Pyth key policy: MED + Jupiter is scoreable
    assert is_scoreable_capture(med_jup, require_pyth=False, allow_med=True) is True
    assert score_reject_reason(med_jup, require_pyth=False, allow_med=True) is None
    # Key/strict Path A: even with allow_med, non-pyth source still rejected
    assert is_scoreable_capture(med_jup, require_pyth=True, allow_med=True) is False
    assert "sol_usd_not_pyth" in (score_reject_reason(med_jup, require_pyth=True, allow_med=True) or "")


def test_resolve_sol_usd_for_scoring_require_pyth_false_prefers_chain(monkeypatch):
    """require_pyth=False must not hard-fail; prefer pyth→CG→jupiter→ref."""
    from datetime import datetime, timezone

    from ingestion import sol_usd_oracle as oro

    as_of = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(oro, "_optional_pyth_key", lambda: None)

    # Simulate no network pyth/cg → live jupiter via fetch_sol_usd_asof fallback
    jup = oro.SolUsdQuote(price=117.5, source="jupiter", publish_time=int(as_of.timestamp()))

    def _fake_asof(as_of_, *, allow_network=True, fallback=oro.DEFAULT_SOL_USD_REF, max_skew_s=86400):
        return oro.SolUsdQuote(
            price=float(jup.price),
            source="jupiter_live_not_asof",
            publish_time=jup.publish_time,
        )

    monkeypatch.setattr(oro, "fetch_sol_usd_asof", _fake_asof)
    q, reason = oro.resolve_sol_usd_for_scoring(as_of, require_pyth=False, allow_network=True)
    assert q is not None
    assert q.price == pytest.approx(117.5)
    assert "jupiter" in q.source
    assert reason == q.source

    # With require_pyth=True and no Hermes → None
    monkeypatch.setattr(oro, "require_pyth_asof", lambda *a, **k: None)
    q2, reason2 = oro.resolve_sol_usd_for_scoring(as_of, require_pyth=True, allow_network=True)
    assert q2 is None
    assert reason2 == "pyth_asof_unavailable"


def test_age_s_from_create_q5b():
    t0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    create = t0 - timedelta(seconds=5)
    a = age_s_from_create(create, t0)
    assert a.ok and a.age_s == pytest.approx(5.0)

    old = t0 - timedelta(days=10)
    b = age_s_from_create(old, t0)
    assert b.ok is False
    assert "age_gt_max" in b.reason

    feats, ok, reason = filter_anomalous_age_features({"age_s": 2e7})
    assert ok is False


def test_trade_implied_mc_dune_q3():
    # amount_usd/tok * 1e9
    mc = trade_implied_mc_usd(100.0, 1e7)
    assert mc == pytest.approx(10_000.0)


def test_parse_helius_buy_sell_min_usd():
    mint = "Mint1111111111111111111111111111111111111"
    bc = "Curve111111111111111111111111111111111111"
    fee = "Trader11111111111111111111111111111111111"
    t0 = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    tx = {
        "timestamp": int(t0.timestamp()) - 1,
        "source": "PUMP_FUN",
        "type": "SWAP",
        "feePayer": fee,
        "tokenTransfers": [
            {"mint": mint, "tokenAmount": 1_000_000, "toUserAccount": fee, "fromUserAccount": bc}
        ],
        "accountData": [{"account": bc, "nativeBalanceChange": 1_000_000_000}],  # 1 SOL
        "nativeTransfers": [],
    }
    rows = parse_helius_enhanced_txs([tx], mint=mint, bonding_curve=bc, sol_usd=100.0, t0=t0)
    assert len(rows) == 1
    assert rows[0].side == "buy"
    assert rows[0].amount_usd == pytest.approx(100.0)
    assert rows[0].project == "pumpdotfun"


def test_parse_helius_multileg_wsol_buys():
    """Bundled Pump AMM: multi-trader + multi-hop legs; skip CREATE_POOL; WSOL sol_amt."""
    from ingestion.helius_trade_parse import WSOL_MINT

    mint = "Mint2222222222222222222222222222222222222"
    bc = "Curve222222222222222222222222222222222222"
    pool = "Pool2222222222222222222222222222222222222"
    t0 = datetime(2026, 9, 22, 15, 29, 59, tzinfo=timezone.utc)
    ts = int(t0.timestamp())
    creator = "Creator222222222222222222222222222222222"
    small = "Small22222222222222222222222222222222222"
    whale = "Whale222222222222222222222222222222222222"
    create = {
        "timestamp": ts,
        "source": "PUMP_FUN",
        "type": "CREATE",
        "feePayer": creator,
        "tokenTransfers": [
            {
                "mint": mint,
                "tokenAmount": 1e8,
                "fromUserAccount": bc,
                "toUserAccount": creator,
            }
        ],
        "accountData": [{"account": bc, "nativeBalanceChange": 85_000_000_000}],
        "nativeTransfers": [],
    }
    bundled = {
        "timestamp": ts,
        "source": "PUMP_AMM",
        "type": "SWAP",
        "feePayer": small,
        "tokenTransfers": [
            {"mint": WSOL_MINT, "tokenAmount": 1.0, "fromUserAccount": small, "toUserAccount": pool},
            {"mint": mint, "tokenAmount": 1e6, "fromUserAccount": pool, "toUserAccount": small},
            {"mint": WSOL_MINT, "tokenAmount": 160.0, "fromUserAccount": whale, "toUserAccount": pool},
            {"mint": mint, "tokenAmount": 1e8, "fromUserAccount": pool, "toUserAccount": whale},
        ],
        "accountData": [],
        "nativeTransfers": [],
    }
    create_pool = {
        "timestamp": ts,
        "source": "PUMP_AMM",
        "type": "CREATE_POOL",
        "feePayer": creator,
        "tokenTransfers": [
            {"mint": mint, "tokenAmount": 1e8, "fromUserAccount": bc, "toUserAccount": pool},
            {"mint": WSOL_MINT, "tokenAmount": 17.0, "fromUserAccount": creator, "toUserAccount": pool},
        ],
        "accountData": [],
        "nativeTransfers": [],
    }
    rows = parse_helius_enhanced_txs(
        [create, bundled, create_pool],
        mint=mint,
        bonding_curve=bc,
        sol_usd=100.0,
        t0=t0,
    )
    buys = [r for r in rows if r.side == "buy"]
    assert len(buys) == 3
    by_trader = {r.trader_id: r for r in buys}
    assert by_trader[creator].sol_amt == pytest.approx(85.0)
    assert by_trader[small].sol_amt == pytest.approx(1.0)
    assert by_trader[whale].sol_amt == pytest.approx(160.0)


def test_parse_helius_multibuyer_bc_native_buys():
    """Bundled Pump.fun SWAP: two buyers → BC native; one trade row each."""
    mint = "Mint3333333333333333333333333333333333333"
    bc = "Curve333333333333333333333333333333333333"
    t0 = datetime(2026, 9, 22, 1, 41, 6, tzinfo=timezone.utc)
    ts = int(t0.timestamp())
    a = "BuyerA33333333333333333333333333333333333"
    b = "BuyerB33333333333333333333333333333333333"
    tx = {
        "timestamp": ts,
        "source": "PUMP_FUN",
        "type": "SWAP",
        "feePayer": a,
        "tokenTransfers": [
            {"mint": mint, "tokenAmount": 1e8, "fromUserAccount": bc, "toUserAccount": a},
            {"mint": mint, "tokenAmount": 5e7, "fromUserAccount": bc, "toUserAccount": b},
        ],
        "accountData": [{"account": bc, "nativeBalanceChange": 54_388_075_111}],
        "nativeTransfers": [
            {"fromUserAccount": a, "toUserAccount": bc, "amount": 29_629_630_000},
            {"fromUserAccount": b, "toUserAccount": bc, "amount": 24_758_445_111},
        ],
    }
    rows = parse_helius_enhanced_txs([tx], mint=mint, bonding_curve=bc, sol_usd=100.0, t0=t0)
    buys = [r for r in rows if r.side == "buy"]
    assert len(buys) == 2
    by = {r.trader_id: r for r in buys}
    assert by[a].sol_amt == pytest.approx(29.62963)
    assert by[b].sol_amt == pytest.approx(24.758445111)
