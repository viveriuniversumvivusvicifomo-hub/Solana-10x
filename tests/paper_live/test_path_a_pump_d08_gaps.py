"""D-08 — remaining pump_enrich / score / journal invariant gaps.

Already covered elsewhere (do not duplicate):
  - trade curve/age vs coin gapfill
  - dune_cohort prior stamps

Remaining (this file):
  1. holders proxy on Pump trades path
  2. sol_usd_source=pump_frontend + score gate bypass
  3. post-restart journal invariant (q5a_curve_age_source / no skip_prior)
  4. regression: coin overlay never returns when n_trades_pre_t0>0
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paper_live.feed import MintSighting
from paper_live.legacy_candidates import path_a_post_restart_sighting_ok
from paper_live.pump_enrich import enrich_pump_for_sightings
from paper_live.score import PaperScorer


def _sighting(
    mint: str,
    *,
    t0: datetime,
    create_ts: datetime,
    coin_progress_rt: int | None = None,
    coin_sol_lamports: int | None = None,
) -> MintSighting:
    raw: dict = {
        "creator": "CreatorD08HoldersProxy11111111111111111111",
        "created_timestamp": int(create_ts.timestamp() * 1000),
        "usd_market_cap": 12_500.0,
        "complete": False,
    }
    if coin_progress_rt is not None:
        raw["real_token_reserves"] = coin_progress_rt
    if coin_sol_lamports is not None:
        raw["real_sol_reserves"] = coin_sol_lamports
    return MintSighting(
        mint=mint,
        mc_usd=12_500.0,
        name="D08",
        symbol="D08",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw=raw,
    )


def test_pump_enrich_holders_proxy_from_trades_path(tmp_path: Path):
    """Pump trades → q5a n_holders_proxy / top holder shares (not coin-only)."""
    from ingestion.pump_constants import INITIAL_REAL_TOKEN_RESERVES

    mint = "MintHoldersProxyD08xxxxxxxxxxxxxxxxxxxxxxxpump"
    create_ts = datetime(2026, 10, 2, 10, 0, 0, tzinfo=timezone.utc)
    t0 = create_ts + timedelta(seconds=120)
    t0_ms = int(t0.timestamp() * 1000)
    # Distinct traders with positive net tok → holders proxy ≥ 2
    fixture = {
        "by_mint": {
            mint: [
                {
                    "blockTimeMs": t0_ms - 40_000,
                    "side": "buy",
                    "valueUsd": "200",
                    "valueNative": "1.2",
                    "baseAmount": {"raw": str(1_000_000_000), "decimals": 6},
                    "trader": {"address": "HolderAAA1111111111111111111111111111111"},
                    "quote": {"id": "11111111111111111111111111111111"},
                },
                {
                    "blockTimeMs": t0_ms - 20_000,
                    "side": "buy",
                    "valueUsd": "80",
                    "valueNative": "0.5",
                    "baseAmount": {"raw": str(400_000_000), "decimals": 6},
                    "trader": {"address": "HolderBBB2222222222222222222222222222222"},
                    "quote": {"id": "11111111111111111111111111111111"},
                },
                {
                    "blockTimeMs": t0_ms - 10_000,
                    "side": "sell",
                    "valueUsd": "10",
                    "valueNative": "0.05",
                    # partial sell — still net positive for BBB
                    "baseAmount": {"raw": str(50_000_000), "decimals": 6},
                    "trader": {"address": "HolderBBB2222222222222222222222222222222"},
                    "quote": {"id": "11111111111111111111111111111111"},
                },
            ]
        }
    }
    fixture_path = tmp_path / "holders_trades.json"
    fixture_path.write_text(json.dumps(fixture))
    # Coin reserves deliberately different — holders must come from trades
    coin_rt = int(INITIAL_REAL_TOKEN_RESERVES * 0.9)
    sighting = _sighting(
        mint,
        t0=t0,
        create_ts=create_ts,
        coin_progress_rt=coin_rt,
        coin_sol_lamports=5 * 1_000_000_000,
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
    assert results[mint].n_trades_pre_t0 == 3
    assert feats["n_holders_proxy"] == pytest.approx(2.0)
    assert feats["unique_buyers_total"] == pytest.approx(2.0)
    assert feats.get("top1_holder_pct_proxy") is not None
    assert 0.0 < float(feats["top1_holder_pct_proxy"]) <= 1.0
    assert feats["q5a_curve_age_source"] == "q5a_trades"


def test_sol_usd_source_pump_frontend_score_gate_bypass():
    """Path A Pump: sol_usd_source=pump_frontend must not skip_sol_usd_not_pyth."""
    feats = {
        "capture_scoreable": True,
        "t0_definition": "pump_mc_band_sighting_v1",
        "t0_refined": True,
        "sol_usd_source": "pump_frontend",
        "sol_usd_t0": 150.0,
        "age_s": 90.0,
        "age_from_create_ok": True,
        "buy_vol_usd_60s": 100.0,
        "creator_prior_source": "dune_cohort_empty",
        # Minimal q5b-ish keys so we don't fail earlier gates unexpectedly;
        # we only assert the pyth/sol_usd skip is not raised.
    }
    sc = PaperScorer(mode="histgb_q5b", require_t0_refined=True, require_pyth_when_key=True)
    # Direct parity gate (where sol_usd check lives)
    parity = sc._parity_skip(feats, "+q5b")
    assert parity is None, parity
    r = sc.score(feats)
    assert r.mode != "skip_sol_usd_not_pyth", r


def test_post_restart_journal_invariant_curve_age_no_skip_prior():
    """Fixture rows mimicking post-12:13 PT Path A Pump journal stamps."""
    ok_row = {
        "score_mode": "histgb_q5b",
        "created_at": "2026-10-02T12:20:00+02:00",
        "features_json": json.dumps(
            {
                "q5a_curve_age_source": "q5a_trades",
                "creator_prior_source": "dune_cohort_empty",
                "n_trades_pre_t0": 42,
                "sol_usd_source": "pump_frontend",
            }
        ),
    }
    gapfill_row = {
        "score_mode": "histgb_q5b",
        "features_json": json.dumps(
            {
                "q5a_curve_age_source": "pump_coin_gapfill",
                "creator_prior_source": "dune_cohort_recompute",
                "n_trades_pre_t0": 0,
            }
        ),
    }
    bad_skip = {
        "score_mode": "skip_prior_not_train",
        "features_json": json.dumps(
            {
                "q5a_curve_age_source": "q5a_trades",
                "creator_prior_source": "none",
            }
        ),
    }
    bad_curve = {
        "score_mode": "histgb_q5b",
        "features_json": json.dumps(
            {
                "q5a_curve_age_source": None,
                "creator_prior_source": "dune_cohort_exact",
            }
        ),
    }
    assert path_a_post_restart_sighting_ok(ok_row)[0] is True
    assert path_a_post_restart_sighting_ok(gapfill_row)[0] is True
    ok_bad, fails_skip = path_a_post_restart_sighting_ok(bad_skip)
    assert ok_bad is False
    assert any("skip_prior_not_train" in f for f in fails_skip)
    ok_c, fails_c = path_a_post_restart_sighting_ok(bad_curve)
    assert ok_c is False
    assert any("q5a_curve_age_source" in f for f in fails_c)


def test_coin_overlay_never_returns_when_n_trades_pre_t0_gt_0(tmp_path: Path):
    """Regression: with trades present, coin bonding proxies must not overwrite Q5a."""
    from ingestion.pump_constants import INITIAL_REAL_TOKEN_RESERVES

    mint = "MintNoCoinOverlayD08xxxxxxxxxxxxxxxxxxxxxpump"
    create_ts = datetime(2026, 10, 2, 11, 0, 0, tzinfo=timezone.utc)
    t0 = create_ts + timedelta(seconds=100)
    t0_ms = int(t0.timestamp() * 1000)
    # Trade net_sol = 2.0 → progress 2/85 ≈ 0.0235
    fixture = {
        "by_mint": {
            mint: [
                {
                    "blockTimeMs": t0_ms - 30_000,
                    "side": "buy",
                    "valueUsd": "50",
                    "valueNative": "2.0",
                    "baseAmount": {"raw": str(500_000_000), "decimals": 6},
                    "trader": {"address": "TraderNoOverlay11111111111111111111111"},
                    "quote": {"id": "11111111111111111111111111111111"},
                }
            ]
        }
    }
    fixture_path = tmp_path / "no_overlay.json"
    fixture_path.write_text(json.dumps(fixture))
    # Coin would imply progress ≈ 0.5 and net_sol = 40 — must NOT win
    coin_rt = int(INITIAL_REAL_TOKEN_RESERVES * 0.5)
    sighting = _sighting(
        mint,
        t0=t0,
        create_ts=create_ts,
        coin_progress_rt=coin_rt,
        coin_sol_lamports=40 * 1_000_000_000,
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
    assert results[mint].n_trades_pre_t0 > 0
    assert feats["q5a_curve_age_source"] == "q5a_trades"
    assert feats["q5a_curve_age_source"] != "pump_coin_gapfill"
    assert feats["net_sol_curve"] == pytest.approx(2.0, rel=1e-3)
    assert feats["progress_curve_proxy"] == pytest.approx(2.0 / 85.0, rel=1e-3)
    # Explicit: coin overlay values must not appear
    assert feats["net_sol_curve"] != pytest.approx(40.0, abs=1.0)
    assert feats["progress_curve_proxy"] != pytest.approx(0.5, abs=0.05)
