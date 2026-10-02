"""SolModelos MUST-FIX: Dune cohort priors exact/recompute + score threshold 0.99."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from paper_live.creator_priors import (
    CREATOR_PRIOR_SOURCE_EMPTY,
    CREATOR_PRIOR_SOURCE_EXACT,
    CREATOR_PRIOR_SOURCE_NONE,
    CREATOR_PRIOR_SOURCE_PUMP,
    CREATOR_PRIOR_SOURCE_RECOMPUTE,
    CREATOR_PRIOR_SOURCE_TRAIN,
    CreatorPriorIndex,
    allow_pump_frontend_priors,
    clear_creator_prior_cache,
    load_creator_prior_index,
    resolve_creator_priors,
)
from paper_live.entry import FOLD5_TRAINQ_TOP1, resolve_score_threshold
from paper_live.q5b_agg import CreateRow, q5b_from_create


EXPAND_V2 = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "samples"
    / "features_dune_p0_q5_expand_v2.csv"
)


@pytest.fixture(autouse=True)
def _clear_prior_cache():
    clear_creator_prior_cache()
    yield
    clear_creator_prior_cache()


def test_resolve_score_threshold_0_99_does_not_raise():
    thr = resolve_score_threshold(
        score_threshold=0.99,
        train_top_frac=0.01,
        score_mode="histgb_q5b",
        calibration={"thresholds": {"0.01": FOLD5_TRAINQ_TOP1}, "source": "test"},
        allow_non_train_threshold=False,
    )
    assert thr == 0.99


def test_resolve_score_threshold_none_defaults_to_trainq():
    thr = resolve_score_threshold(
        score_threshold=None,
        train_top_frac=0.01,
        score_mode="histgb_q5b",
        calibration={"thresholds": {"0.01": FOLD5_TRAINQ_TOP1}, "source": "test"},
    )
    assert thr == FOLD5_TRAINQ_TOP1


def test_allow_pump_frontend_priors_off_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_PUMP_FRONTEND_PRIORS", raising=False)
    assert allow_pump_frontend_priors() is False
    monkeypatch.setenv("ALLOW_PUMP_FRONTEND_PRIORS", "1")
    assert allow_pump_frontend_priors() is True


def test_priors_for_uncapped_cohort_includes_beyond_30d():
    """window_days=None must keep creates older than 30d (train cohort rank)."""
    creator = "CreatorTest1111111111111111111111111111111"
    as_of = datetime(2026, 9, 1, 19, 23, 15, tzinfo=timezone.utc)
    rows = [
        CreateRow(
            mint=f"old{i}",
            creator_pubkey=creator,
            create_ts=as_of - timedelta(days=d),
        )
        for i, d in enumerate([40, 35, 20, 10, 5])  # 2 beyond 30d
    ]
    idx = CreatorPriorIndex(by_creator={creator: rows}, n_rows=len(rows), source="test")
    capped = idx.priors_for(creator, this_mint="new", as_of=as_of, window_days=30)
    uncapped = idx.priors_for(creator, this_mint="new", as_of=as_of, window_days=None)
    assert len(capped) == 3
    assert len(uncapped) == 5
    q5b = q5b_from_create(
        CreateRow(mint="new", creator_pubkey=creator, create_ts=as_of),
        as_of + timedelta(seconds=1),
        prior_creates=uncapped,
    )
    assert q5b["creator_prior_mints_cohort"] == 5.0
    assert q5b["creator_prior_mints_30d"] == 3.0
    assert q5b["creator_prior_mints_7d"] == 1.0
    assert q5b["creator_prior_mints_all_in_window"] is None


@pytest.mark.skipif(not EXPAND_V2.is_file(), reason="expand_v2 CSV missing")
def test_exact_mint_lookup_matches_csv():
    import pandas as pd

    mint = "B1AXzSHRDv1nUP1dmcxdKD4MGxdkph4JzuWDP1fDpump"
    df = pd.read_csv(
        EXPAND_V2,
        usecols=[
            "mint",
            "creator_pubkey",
            "create_ts",
            "creator_prior_mints_7d",
            "creator_prior_mints_30d",
            "creator_prior_mints_cohort",
            "creator_prior_mints_all_in_window",
        ],
    )
    row = df.loc[df["mint"] == mint].iloc[0]
    idx = load_creator_prior_index(EXPAND_V2, force_reload=True)
    assert mint in idx.by_mint_priors
    # Prefer expand_v2 path when loading default candidates too
    exact = idx.exact_priors_for_mint(mint)
    assert exact is not None
    assert exact["creator_prior_mints_7d"] == float(row["creator_prior_mints_7d"])
    assert exact["creator_prior_mints_30d"] == float(row["creator_prior_mints_30d"])
    assert exact["creator_prior_mints_cohort"] == float(row["creator_prior_mints_cohort"])

    resolved = resolve_creator_priors(
        mint=mint,
        creator=str(row["creator_pubkey"]),
        create_ts=datetime(2026, 9, 1, 19, 23, 15, tzinfo=timezone.utc),
        index=idx,
        allow_pump=False,
    )
    assert resolved.source == CREATOR_PRIOR_SOURCE_EXACT
    assert resolved.exact_overlay is not None
    assert resolved.exact_overlay["creator_prior_mints_cohort"] == float(
        row["creator_prior_mints_cohort"]
    )
    # all_in_window forced None for train parity
    assert resolved.exact_overlay["creator_prior_mints_all_in_window"] is None


@pytest.mark.skipif(not EXPAND_V2.is_file(), reason="expand_v2 CSV missing")
def test_recompute_uncapped_when_mint_not_in_store():
    """Synthetic mint for known creator → recompute; cohort > 30d-capped count."""
    creator = "96hq1rUo5qQk26NAP7wK6VtcnZXPKbkHpdVsdGwe3Cda"
    as_of = datetime(2026, 9, 1, 19, 23, 15, tzinfo=timezone.utc)
    idx = load_creator_prior_index(EXPAND_V2, force_reload=True)
    fake_mint = "FakeMintNotInStore1111111111111111111111111"
    assert idx.exact_priors_for_mint(fake_mint) is None

    resolved = resolve_creator_priors(
        mint=fake_mint,
        creator=creator,
        create_ts=as_of,
        index=idx,
        allow_pump=False,
    )
    assert resolved.source in (
        CREATOR_PRIOR_SOURCE_RECOMPUTE,
        CREATOR_PRIOR_SOURCE_EMPTY,
    )
    capped = idx.priors_for(
        creator, this_mint=fake_mint, as_of=as_of, window_days=30
    )
    uncapped = resolved.prior_creates
    assert len(uncapped) >= len(capped)
    # Real CSV row for this creator@as_of had cohort=11 > 30d=10
    if uncapped:
        q5b = q5b_from_create(
            CreateRow(mint=fake_mint, creator_pubkey=creator, create_ts=as_of),
            as_of + timedelta(seconds=30),
            prior_creates=uncapped,
        )
        assert q5b["creator_prior_mints_cohort"] == float(len(uncapped))
        assert q5b["creator_prior_mints_cohort"] >= q5b["creator_prior_mints_30d"]


def test_pump_fallback_off_by_default_when_store_empty(monkeypatch):
    monkeypatch.delenv("ALLOW_PUMP_FRONTEND_PRIORS", raising=False)

    class _FakePump:
        def list_coins(self, **kwargs):
            raise AssertionError("pump must not be called when allow_pump=False")

    empty = CreatorPriorIndex(source=CREATOR_PRIOR_SOURCE_NONE, n_rows=0)
    resolved = resolve_creator_priors(
        mint="m",
        creator="c",
        create_ts=datetime(2026, 10, 1, tzinfo=timezone.utc),
        index=empty,
        pump_client=_FakePump(),
        allow_pump=False,
    )
    assert resolved.source == CREATOR_PRIOR_SOURCE_NONE
    assert resolved.prior_creates == []


def test_pump_fallback_when_env_enabled(monkeypatch):
    monkeypatch.setenv("ALLOW_PUMP_FRONTEND_PRIORS", "1")

    class _FakePump:
        def list_coins(self, **kwargs):
            return []

    empty = CreatorPriorIndex(source=CREATOR_PRIOR_SOURCE_NONE, n_rows=0)
    # allow_pump=None → reads env
    resolved = resolve_creator_priors(
        mint="m",
        creator="Creator1111111111111111111111111111111111111",
        create_ts=datetime(2026, 10, 1, tzinfo=timezone.utc),
        index=empty,
        pump_client=_FakePump(),
        allow_pump=None,
    )
    assert resolved.source == CREATOR_PRIOR_SOURCE_PUMP


def test_pump_enrich_stamps_dune_cohort_recompute_or_empty(monkeypatch):
    """Path A pump_enrich must stamp creator_prior_source in train family (not Pump)."""
    from paper_live.feed import MintSighting
    from paper_live.pump_enrich import enrich_pump_for_sightings

    creator = "CreatorPumpPriorStamp1111111111111111111111"
    as_of = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    # Store has creator history but not this mint → recompute (or empty if none)
    prior_rows = [
        CreateRow(
            mint=f"prior{i}",
            creator_pubkey=creator,
            create_ts=as_of - timedelta(days=d),
        )
        for i, d in enumerate([10, 5, 2])
    ]
    idx = CreatorPriorIndex(
        by_creator={creator: prior_rows},
        by_mint_priors={},
        n_rows=len(prior_rows),
        source=CREATOR_PRIOR_SOURCE_TRAIN,
        path="/fake/expand.csv",
    )
    monkeypatch.setattr(
        "paper_live.pump_enrich.load_creator_prior_index", lambda *a, **k: idx
    )
    monkeypatch.setattr(
        "paper_live.creator_priors.load_creator_prior_index", lambda *a, **k: idx
    )

    mint = "FakePumpMintNotInStore22222222222222222222222"
    t0 = as_of + timedelta(seconds=90)
    sighting = MintSighting(
        mint=mint,
        mc_usd=12_000.0,
        name="TestCoin",
        symbol="TST",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw={
            "creator": creator,
            "created_timestamp": int(as_of.timestamp() * 1000),
            "usd_market_cap": 12_000.0,
            "complete": False,
        },
    )
    results = enrich_pump_for_sightings(
        [sighting],
        fetch_priors=True,
        fetch_trades=False,
        dry_run=True,
        client=None,
    )
    vr = results[mint]
    src = vr.features.get("creator_prior_source")
    assert src in (
        CREATOR_PRIOR_SOURCE_RECOMPUTE,
        CREATOR_PRIOR_SOURCE_EMPTY,
        CREATOR_PRIOR_SOURCE_EXACT,
    ), src
    assert vr.features.get("creator_priors_incomplete") is False
    assert vr.features.get("creator_prior_mints_cohort") == 3.0
    # Score gate: train-family source must not skip_prior_not_train
    from paper_live.score import PaperScorer
    from verification.live_parity import prior_source_is_train

    assert prior_source_is_train(src)
    # Inject buy_vol so we pass missing-buy_vol; model may still be missing
    feats = dict(vr.features)
    feats["buy_vol_usd_60s"] = 100.0
    sc = PaperScorer(mode="histgb_q5b", require_t0_refined=False)
    r = sc.score(feats)
    assert r.mode != "skip_prior_not_train", r


def test_pump_enrich_stamps_dune_cohort_exact(monkeypatch):
    from paper_live.feed import MintSighting
    from paper_live.pump_enrich import enrich_pump_for_sightings

    creator = "CreatorExactStamp11111111111111111111111111"
    mint = "ExactMintStamp3333333333333333333333333333"
    as_of = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    overlay = {
        "creator_prior_mints_7d": 1.0,
        "creator_prior_mints_30d": 2.0,
        "creator_prior_mints_cohort": 4.0,
        "creator_prior_mints_all_in_window": None,
    }
    idx = CreatorPriorIndex(
        by_creator={creator: []},
        by_mint_priors={mint: dict(overlay)},
        n_rows=1,
        source=CREATOR_PRIOR_SOURCE_TRAIN,
        path="/fake/expand.csv",
    )
    monkeypatch.setattr(
        "paper_live.pump_enrich.load_creator_prior_index", lambda *a, **k: idx
    )
    monkeypatch.setattr(
        "paper_live.creator_priors.load_creator_prior_index", lambda *a, **k: idx
    )
    t0 = as_of + timedelta(seconds=60)
    sighting = MintSighting(
        mint=mint,
        mc_usd=15_000.0,
        name="ExactCoin",
        symbol="EXC",
        price_mean=None,
        total_supply=None,
        market_address=None,
        source="test",
        seen_at=t0,
        raw={
            "creator": creator,
            "created_timestamp": int(as_of.timestamp() * 1000),
            "usd_market_cap": 15_000.0,
            "complete": False,
        },
    )
    results = enrich_pump_for_sightings(
        [sighting], fetch_priors=True, fetch_trades=False, dry_run=True
    )
    vr = results[mint]
    assert vr.features["creator_prior_source"] == CREATOR_PRIOR_SOURCE_EXACT
    assert vr.features["creator_priors_incomplete"] is False
    assert vr.features["creator_prior_mints_cohort"] == 4.0
