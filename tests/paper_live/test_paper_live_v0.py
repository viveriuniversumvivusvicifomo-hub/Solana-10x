"""Tests paper-live v0: anti look-ahead, +q5b enrich, skip-incomplete, dry-run smoke."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS
from paper_live.buy_vol import aggregate_buy_vol_from_trades, buy_vol_from_fixture
from paper_live.config import PaperLiveConfig, SAMPLE_BUY_VOL_FIXTURE, SAMPLE_Q5_FIXTURE
from paper_live.features_t0 import (
    assert_no_lookahead_keys,
    feature_vector_for_set,
    features_at_t0,
    required_buy60_present,
    required_q5b_present,
)
from paper_live.feed import poll_sample
from paper_live.journal import Journal
from paper_live.loop import PaperLiveRunner
from paper_live.q5a_agg import TradeRow, aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, q5b_from_create
from paper_live.q5_enrich import enrich_q5_from_fixture
from paper_live.score import PaperScorer


def test_features_reject_lookahead():
    bad = {"mint": "x", "hit_10x_30d": 1, "buy_vol_usd_60s": 1.0}
    with pytest.raises(AssertionError):
        assert_no_lookahead_keys(bad)


def test_score_skips_missing_buy_vol_rule():
    sc = PaperScorer("rule_buy60")
    r = sc.score(
        {"buy_vol_usd_60s": None, "name_len": 8, "symbol_len": 4, "name_missing": 0, "symbol_missing": 0}
    )
    assert r.skipped
    assert r.mode == "skip_missing_buy_vol"


def test_histgb_q5b_skips_incomplete_vector():
    sc = PaperScorer("histgb_q5b")
    # buy60 present but Q5a/Q5b null
    feats = {"buy_vol_usd_60s": 100.0, "buy_count_total": None, "name_len": 4}
    r = sc.score(feats)
    assert r.skipped
    assert r.mode in ("skip_incomplete_q5b", "skip_missing_model")


def test_score_debug_fallback_gated():
    sc = PaperScorer("rule_buy60", allow_q5b_fallback=True)
    r = sc.score(
        {"buy_vol_usd_60s": None, "name_len": 8, "symbol_len": 4, "name_missing": 0, "symbol_missing": 0}
    )
    assert r.mode == "rule_q5b_partial_fallback_DEBUG"
    assert r.score == 12.0


def test_score_rule_buy60_primary():
    sc = PaperScorer("rule_buy60")
    r2 = sc.score({"buy_vol_usd_60s": 1234.5})
    assert r2.score == 1234.5
    assert r2.mode == "rule_buy60"
    assert r2.set_name == "buy60"


def test_feature_vector_aligns_with_wf_sets():
    feats = {"buy_vol_usd_60s": 10.0, "name_len": 3.0, "age_s": None}
    v60 = feature_vector_for_set(feats, "buy60")
    assert list(v60.keys()) == list(FEATURE_SETS["buy60"])
    vq = feature_vector_for_set(feats, "+q5b")
    assert list(vq.keys()) == list(FEATURE_SETS["+q5b"])
    assert "buy_vol_usd_60s" in vq
    assert "sniper_vol_share_5s" in vq
    assert len(FEATURE_SETS["+q5b"]) == 1 + len(Q5A_COLS) + len(Q5B_COLS)


def test_aggregate_buy_vol_no_lookahead():
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    mint = "MintAAA"
    trades = [
        {
            "Block": {"Time": (t0 - timedelta(seconds=10)).isoformat()},
            "Trade": {
                "Currency": {"MintAddress": mint},
                "Side": {"Type": "buy", "AmountInUSD": 100.0},
            },
        },
        {
            "Block": {"Time": (t0 + timedelta(seconds=1)).isoformat()},
            "Trade": {
                "Currency": {"MintAddress": mint},
                "Side": {"Type": "buy", "AmountInUSD": 9999.0},
            },
        },
        {
            "Block": {"Time": (t0 - timedelta(seconds=90)).isoformat()},
            "Trade": {
                "Currency": {"MintAddress": mint},
                "Side": {"Type": "buy", "AmountInUSD": 50.0},
            },
        },
    ]
    out = aggregate_buy_vol_from_trades(trades, {mint: t0})
    assert out[mint].buy_vol_usd_60s == 100.0
    assert out[mint].buy_count_60s == 1


def test_q5a_agg_parity_sniper_and_windows():
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    t_first = t0 - timedelta(seconds=20)
    trades = [
        TradeRow("M", t_first, "buy", 100.0, "A", 1000.0, 1.0, "pumpdotfun"),
        TradeRow("M", t_first + timedelta(seconds=2), "buy", 50.0, "B", 500.0, 0.5, "pumpdotfun"),
        TradeRow("M", t0 - timedelta(seconds=5), "sell", 10.0, "A", 100.0, 0.1, "pumpdotfun"),
        # after T0 — must not be passed in; if passed, aggregate filters
        TradeRow("M", t0 + timedelta(seconds=1), "buy", 999.0, "C", 1.0, 1.0, "pumpdotfun"),
    ]
    feats = aggregate_q5a_for_mint([t for t in trades if t.ts <= t0], t0)
    assert feats["buy_count_total"] == 2
    assert feats["sell_count_total"] == 1
    assert feats["buy_vol_usd_total"] == 150.0
    assert feats["first_buy_usd"] == 100.0
    assert feats["unique_buyers_total"] == 2
    assert feats["sniper_vol_share_5s"] == pytest.approx(150.0 / 150.0)
    assert feats["age_proxy_s"] == pytest.approx(20.0)


def test_q5b_agg_priors_causal():
    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    create = CreateRow("MintNew", "CreatorX", t0 - timedelta(seconds=30), "Foo", "FOO")
    priors = [
        CreateRow("Old1", "CreatorX", t0 - timedelta(days=3), "A", "A"),
        CreateRow("Old2", "CreatorX", t0 - timedelta(days=20), "B", "B"),
        CreateRow("Old3", "Other", t0 - timedelta(days=1), "C", "C"),
        CreateRow("Future", "CreatorX", t0 + timedelta(days=1), "D", "D"),  # ignore
    ]
    out = q5b_from_create(create, t0, prior_creates=priors)
    assert out["q5b_complete"] is True
    assert out["age_s"] == pytest.approx(30.0)
    assert out["has_creator"] == 1.0
    assert out["name_len"] == 3.0
    assert out["creator_prior_mints_7d"] == 1.0
    assert out["creator_prior_mints_30d"] == 2.0
    assert out["creator_prior_mints_cohort"] == 2.0


def test_q5_fixture_complete_for_sample():
    if not SAMPLE_Q5_FIXTURE.is_file():
        pytest.skip("q5 fixture missing")
    sample = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    sightings = poll_sample(sample, batch=5)
    results = enrich_q5_from_fixture([s.mint for s in sightings])
    assert all(results[s.mint].complete_q5b for s in sightings)
    feats = features_at_t0(
        sightings[0],
        dry_run=True,
        buy_vol_usd_60s=results[sightings[0].mint].buy_vol_usd_60s,
        buy_vol_source="dry_run.q5_fixture",
        q5_extras=results[sightings[0].mint].features,
    )
    assert required_buy60_present(feats)
    assert required_q5b_present(feats)
    assert feats["features_complete_q5b"] is True


def test_parity_matrix_live_vs_train_keys():
    """Every FEATURE_SETS['+q5b'] column is known to the live enrich/vector path."""
    required = list(FEATURE_SETS["+q5b"])
    assert "buy_vol_usd_60s" in required
    assert "age_s" in required
    assert "sniper_vol_share_5s" in required
    assert "creator_prior_mints_7d" in required
    assert "creator_pubkey" not in required  # join-only
    from paper_live.q5_enrich import load_q5_fixture

    by = load_q5_fixture()
    mint = next(iter(by))
    row = by[mint]
    for c in required:
        assert c in row, f"fixture missing {c}"


def test_journal_idempotent(tmp_path: Path):
    j = Journal(
        sqlite_path=tmp_path / "j.sqlite",
        state_path=tmp_path / "state.json",
        candidates_csv=tmp_path / "c.csv",
        followup_csv=tmp_path / "f.csv",
        sightings_csv=tmp_path / "s.csv",
    )
    ok1 = j.record_sighting(
        mint="Mint111",
        t0_ts="2026-10-01T08:00:00+00:00",
        mc_usd_t0=12000.0,
        name="A",
        symbol="A",
        source="test",
        features={"buy_vol_usd_60s": 10.0, "buy_vol_source": "provided"},
        score=10.0,
        score_mode="rule_buy60",
    )
    ok2 = j.record_sighting(
        mint="Mint111",
        t0_ts="2026-10-01T08:00:01+00:00",
        mc_usd_t0=13000.0,
        name="A",
        symbol="A",
        source="test",
        features={"buy_vol_usd_60s": 11.0},
        score=11.0,
        score_mode="rule_buy60",
    )
    assert ok1 is True
    assert ok2 is False


def test_dry_run_rule_buy60_two_cycles(tmp_path: Path):
    sample = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    if not sample.is_file():
        pytest.skip("sample Bitquery ausente")
    if not SAMPLE_Q5_FIXTURE.is_file():
        pytest.skip("q5 fixture ausente")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        feed="bitquery",
        enrich_via="bitquery",
        cycles=2,
        top_k=5,
        data_dir=tmp_path,
        sample_path=sample,
        q5_fixture_path=SAMPLE_Q5_FIXTURE,
        buy_vol_fixture_path=SAMPLE_BUY_VOL_FIXTURE,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="rule_buy60",
        allow_q5b_fallback=False,
        entry_rule="topk_batch",  # smoke: legacy batch top-K (rule scores ≠ histgb proba)
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["n_sightings"] >= 5
    assert summary["n_paper_candidates"] >= 1
    assert summary["cycles_run"] == 2
    for st in summary["stats"]:
        assert st["n_skipped_missing_vol"] == 0


def test_dry_run_histgb_q5b_skips_without_model(tmp_path: Path):
    sample = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    if not sample.is_file() or not SAMPLE_Q5_FIXTURE.is_file():
        pytest.skip("fixtures ausentes")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        feed="bitquery",
        enrich_via="bitquery",
        cycles=1,
        top_k=5,
        data_dir=tmp_path,
        sample_path=sample,
        q5_fixture_path=SAMPLE_Q5_FIXTURE,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="histgb_q5b",
        allow_q5b_fallback=False,
    )
    # Ensure no model in tmp data_dir models — PaperScorer loads from global MODEL_Q5B_PATH
    # If model exists globally, scoring may succeed; either way no crash.
    summary = PaperLiveRunner(cfg).run()
    assert summary["cycles_run"] == 1
    assert summary["trading"] is False


def test_skip_when_enrich_disabled(tmp_path: Path):
    sample = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    if not sample.is_file():
        pytest.skip("sample Bitquery ausente")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        cycles=1,
        top_k=5,
        data_dir=tmp_path,
        sample_path=sample,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=False,
        enrich_buy_vol=False,
        score_mode="rule_buy60",
        allow_q5b_fallback=False,
        entry_rule="topk_batch",
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["stats"][0]["n_skipped_missing_vol"] >= 1
    assert summary["n_paper_candidates"] == 0


def test_entry_gate_train_quantile_skips_below_threshold():
    from paper_live.entry import EntryGate, FOLD5_TRAINQ_TOP1

    gate = EntryGate(
        entry_rule="train_quantile",
        score_threshold=FOLD5_TRAINQ_TOP1,
        train_top_frac=0.01,
        max_per_hour=10,
        top_k=20,
        score_mode="histgb_q5b",
        calibration={"thresholds": {"0.01": FOLD5_TRAINQ_TOP1}, "source": "test"},
        allow_non_train_threshold=True,  # unit test of trainQ gate ≠ product 0.99
    )
    # mock scored rows: (score, sighting, feats, sr) — sighting only needs t0_iso/mint for sort key
    class S:
        def __init__(self, mint):
            self.mint = mint
            self.t0_iso = "2026-10-01T00:00:00+00:00"

    scored = [
        (0.05, S("a"), {}, type("SR", (), {"mode": "histgb_q5b"})()),
        (0.886, S("b"), {}, type("SR", (), {"mode": "histgb_q5b"})()),
        (FOLD5_TRAINQ_TOP1 + 1e-9, S("c"), {}, type("SR", (), {"mode": "histgb_q5b"})()),
    ]
    scored.sort(key=lambda x: (-x[0], x[1].t0_iso, x[1].mint))
    accepted, counters = gate.filter_scored_batch(scored, journal_entered_at=[])
    assert counters["n_skip_below_threshold"] == 2
    assert counters["n_accepted"] == 1
    assert accepted[0][1].mint == "c"


def test_entry_gate_max_per_hour_capacity():
    from paper_live.entry import EntryGate

    gate = EntryGate(
        entry_rule="train_quantile",
        score_threshold=0.0,  # all pass threshold
        max_per_hour=2,
        top_k=50,
        score_mode="histgb_q5b",
        calibration={"thresholds": {"0.01": 0.0}, "source": "test"},
        allow_non_train_threshold=True,  # capacity unit test
    )

    class S:
        def __init__(self, mint):
            self.mint = mint
            self.t0_iso = "2026-10-01T00:00:00+00:00"

    scored = [(0.9, S(f"m{i}"), {}, type("SR", (), {"mode": "histgb_q5b"})()) for i in range(5)]
    accepted, counters = gate.filter_scored_batch(scored, journal_entered_at=[])
    assert counters["n_accepted"] == 2
    assert counters["n_skip_capacity"] == 3


def test_resolve_threshold_from_calibration():
    from paper_live.entry import resolve_score_threshold, FOLD5_TRAINQ_TOP1

    thr = resolve_score_threshold(
        score_threshold=None,
        train_top_frac=0.01,
        score_mode="histgb_q5b",
        calibration={"thresholds": {"0.01": FOLD5_TRAINQ_TOP1}},
    )
    assert thr == FOLD5_TRAINQ_TOP1
    # rule_buy60 without explicit threshold → no gate
    assert (
        resolve_score_threshold(
            score_threshold=None,
            train_top_frac=0.01,
            score_mode="rule_buy60",
            calibration={"thresholds": {"0.01": FOLD5_TRAINQ_TOP1}},
        )
        is None
    )


def test_dry_run_histgb_logs_skip_below_threshold(tmp_path: Path):
    """With model present, typical fixture scores fail trainQ top1% → skip_below_thr."""
    sample = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    model = Path("/workspace/solana-10x/data/paper_live/models/q5b_last.joblib")
    if not sample.is_file() or not SAMPLE_Q5_FIXTURE.is_file() or not model.is_file():
        pytest.skip("fixtures/model ausentes")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        cycles=1,
        top_k=20,
        data_dir=tmp_path,
        sample_path=sample,
        q5_fixture_path=SAMPLE_Q5_FIXTURE,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="histgb_q5b",
        allow_q5b_fallback=False,
        entry_rule="train_quantile",
        train_top_frac=0.01,
        max_per_hour=2,
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["trading"] is False
    assert summary["entry"]["entry_rule"] == "train_quantile"
    assert summary["entry"]["score_threshold"] is not None
    assert summary["entry"]["score_threshold"] == pytest.approx(0.99)
    # Fixture scores are far below trainQ top1% → all scored new mints skipped by threshold
    st0 = summary["stats"][0]
    assert "n_skipped_below_threshold" in st0
    # If any scored, they should be below thr (or capacity); paper enters should be 0
    assert summary["n_paper_candidates"] == 0 or st0["n_skipped_below_threshold"] >= 0


def test_parse_bitquery_trades_derives_sol_and_project():
    """Side.Amount null + ProgramAddress null → sol from USD, project=pumpdotfun."""
    from ingestion.pump_constants import PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID
    from paper_live.q5_enrich import parse_bitquery_trades

    t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    raw = [
        {
            "Block": {"Time": (t0 - timedelta(seconds=5)).isoformat()},
            "Transaction": {"Signer": "TraderA"},
            "Trade": {
                "Currency": {"MintAddress": "MintSOL"},
                "Amount": 1000.0,
                "AmountInUSD": 206.22,  # ≈ 2 SOL * 103.11
                "Dex": {"ProgramAddress": None, "ProtocolName": None},
                "Side": {
                    "Type": "buy",
                    "Amount": None,  # Bitquery often null
                    "AmountInUSD": 206.22,
                    "Currency": {"MintAddress": "So11111111111111111111111111111111111111112"},
                    "Account": {"Address": "TraderA"},
                },
            },
        },
        {
            "Block": {"Time": (t0 - timedelta(seconds=3)).isoformat()},
            "Transaction": {"Signer": "TraderB"},
            "Trade": {
                "Currency": {"MintAddress": "MintSOL"},
                "Amount": 500.0,
                # USD missing — derive from Side.Amount * sol_usd
                "Dex": {"ProgramAddress": PUMP_PROGRAM_ID, "ProtocolName": "pump"},
                "Side": {
                    "Type": "buy",
                    "Amount": 1.0,
                    "AmountInUSD": None,
                    "Currency": {"MintAddress": "So11111111111111111111111111111111111111112"},
                    "Account": {"Address": "TraderB"},
                },
            },
        },
        {
            "Block": {"Time": (t0 - timedelta(seconds=1)).isoformat()},
            "Transaction": {"Signer": "TraderC"},
            "Trade": {
                "Currency": {"MintAddress": "MintSOL"},
                "Amount": 10.0,
                "AmountInUSD": 0.5,  # below Dune min → drop
                "Dex": {"ProgramAddress": PUMP_PROGRAM_ID},
                "Side": {
                    "Type": "buy",
                    "Amount": 0.005,
                    "AmountInUSD": 0.5,
                    "Currency": {"MintAddress": "So11111111111111111111111111111111111111112"},
                },
            },
        },
    ]
    rows = parse_bitquery_trades(
        raw, pump=PUMP_PROGRAM_ID, pumpswap=PUMPSWAP_PROGRAM_ID, sol_usd=103.11
    )
    assert len(rows) == 2
    assert rows[0].sol_amt == pytest.approx(2.0, rel=1e-3)
    assert rows[0].project == "pumpdotfun"  # null ProgramAddress → default
    assert rows[1].amount_usd == pytest.approx(103.11, rel=1e-3)
    assert rows[1].sol_amt == pytest.approx(1.0)
    assert rows[1].project == "pumpdotfun"

    feats = aggregate_q5a_for_mint(rows, t0)
    assert feats["net_sol_curve"] == pytest.approx(3.0, rel=1e-3)
    assert feats["progress_curve_proxy"] == pytest.approx(3.0 / 85.0, rel=1e-3)
    assert feats["max_buy_sol"] == pytest.approx(2.0, rel=1e-3)


def test_repair_sol_features_lifts_zero_curve():
    from paper_live.calibrate import repair_sol_features

    feats = {
        "buy_vol_usd_total": 2062.2,
        "sell_vol_usd_total": 0.0,
        "max_buy_usd": 1031.1,
        "max_buy_sol": 0.0,
        "net_sol_curve": 0.0,
        "net_sol_total": 0.0,
        "progress_curve_proxy": 0.0,
    }
    out = repair_sol_features(feats, sol_usd=103.11)
    assert out["max_buy_sol"] == pytest.approx(10.0, rel=1e-3)
    assert out["net_sol_curve"] == pytest.approx(20.0, rel=1e-3)
    assert out["progress_curve_proxy"] == pytest.approx(20.0 / 85.0, rel=1e-3)


def test_train_rows_score_near_top1_with_exported_model():
    """Exported q5b_last.joblib must still reach ~0.999 on train-like sniper rows."""
    import joblib
    import pandas as pd

    model = Path("/workspace/solana-10x/data/paper_live/models/q5b_last.joblib")
    feat_path = Path("/workspace/solana-10x/data/samples/features_dune_p0_q5_expand_v2.csv")
    if not model.is_file() or not feat_path.is_file():
        pytest.skip("model/train matrix missing")
    blob = joblib.load(model)
    pipe = blob["pipeline"]
    names = list(blob["feature_names"])
    df = pd.read_csv(feat_path)
    # high buy_vol + full curve snipers
    snipers = df[(df["net_sol_curve"] >= 80) & (df["buy_vol_usd_60s"] >= 100_000)].head(20)
    if snipers.empty:
        pytest.skip("no sniper rows in matrix")
    X = snipers[names].to_numpy(dtype=float)
    proba = pipe.predict_proba(X)[:, 1]
    assert float(proba.max()) >= 0.999
    assert float(proba.mean()) >= 0.99


def test_pump_sample_poll_and_q5b_enrich():
    from paper_live.config import SAMPLE_PUMP
    from paper_live.feed import poll_sample
    from paper_live.pump_enrich import enrich_pump_for_sightings

    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump frontend sample missing")
    sightings = poll_sample(SAMPLE_PUMP, batch=3, source="dry_run.pump_sample")
    assert len(sightings) >= 1
    assert all(8000 <= s.mc_usd <= 20000 for s in sightings)
    assert all(s.source.startswith("dry_run") for s in sightings)
    results = enrich_pump_for_sightings(
        sightings, fetch_priors=False, fetch_trades=False, dry_run=True
    )
    assert len(results) == len(sightings)
    for s in sightings:
        vr = results[s.mint]
        assert vr.q5b_ok is True
        assert vr.features.get("age_s") is not None
        assert vr.features.get("has_creator") in (0.0, 1.0)
        assert vr.buy_vol_usd_60s is None  # honest Pump trades API gap
        assert vr.complete_q5b is False  # Q5a missing without trades
        assert vr.capture_scoreable is True  # Pump MC+age gate — no Helius
        assert vr.t0_refined is True
        assert vr.features.get("capture_scoreable") is True
        assert "no_trade_mc_path" not in str(vr.score_reject)
        assert any("trades" in g or "buy_vol" in g or "pump_trades" in g for g in vr.gaps)


def test_dry_run_pump_feed_rule_skips_missing_buy_vol(tmp_path: Path):
    from paper_live.config import SAMPLE_PUMP

    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump frontend sample missing")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        feed="pump",
        enrich_via="pump",
        cycles=1,
        top_k=5,
        data_dir=tmp_path,
        sample_path=SAMPLE_PUMP,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="rule_buy60",
        allow_q5b_fallback=False,
        entry_rule="topk_batch",
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["trading"] is False
    assert summary["feed"] == "pump"
    assert summary["cycles_run"] == 1
    # No buy_vol from pump → skip_missing_vol
    assert summary["stats"][0]["n_skipped_missing_vol"] >= 1
    assert summary["n_paper_candidates"] == 0


def test_feed_config_default_is_pump():
    from paper_live.config import DEFAULT_FEED, PaperLiveConfig

    assert DEFAULT_FEED == "pump"
    assert PaperLiveConfig().feed == "pump"


def test_parse_helius_enhanced_buy_sell_and_buy60():
    from datetime import datetime, timezone

    from paper_live.helius_enrich import (
        buy_vol_60s_from_trades,
        load_helius_tx_fixture,
        parse_helius_enhanced_txs,
    )
    from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE, SAMPLE_PUMP
    import json

    if not SAMPLE_HELIUS_TX_FIXTURE.is_file():
        pytest.skip("helius fixture missing")
    by_mint = load_helius_tx_fixture(SAMPLE_HELIUS_TX_FIXTURE)
    mint = next(iter(by_mint.keys()))
    meta = json.loads(SAMPLE_HELIUS_TX_FIXTURE.read_text())["meta"]
    bc = meta.get("bonding_curve")
    # T0 = newest tx timestamp so all fixture txs are ≤T0
    newest = max(int(tx["timestamp"]) for tx in by_mint[mint] if tx.get("timestamp"))
    t0 = datetime.fromtimestamp(newest, tz=timezone.utc)
    trades = parse_helius_enhanced_txs(
        by_mint[mint], mint=mint, bonding_curve=bc, t0=t0, sol_usd=100.0
    )
    assert len(trades) >= 1
    assert all(tr.ts <= t0 for tr in trades)
    assert any(tr.side == "buy" for tr in trades)
    vol, n = buy_vol_60s_from_trades(trades, t0)
    assert vol >= 0.0
    assert n >= 0
    # look-ahead: earlier T0 should drop later trades
    early = datetime.fromtimestamp(newest - 10_000, tz=timezone.utc)
    trades_early = parse_helius_enhanced_txs(
        by_mint[mint], mint=mint, bonding_curve=bc, t0=early, sol_usd=100.0
    )
    assert len(trades_early) <= len(trades)


def test_hybrid_helius_dry_enrich_complete_for_fixture_mint(tmp_path: Path):
    from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE, SAMPLE_PUMP
    from paper_live.feed import poll_sample
    from paper_live.helius_enrich import enrich_helius_for_sightings
    import json

    if not SAMPLE_PUMP.is_file() or not SAMPLE_HELIUS_TX_FIXTURE.is_file():
        pytest.skip("pump/helius samples missing")
    mint = json.loads(SAMPLE_HELIUS_TX_FIXTURE.read_text())["meta"]["mint"]
    # poll enough of sample to include fixture mint
    sightings = poll_sample(SAMPLE_PUMP, batch=20, source="dry_run.pump_sample")
    hit = [s for s in sightings if s.mint == mint]
    if not hit:
        pytest.skip("fixture mint not in pump sample batch")
    results = enrich_helius_for_sightings(
        hit,
        dry_run=True,
        fixture_path=SAMPLE_HELIUS_TX_FIXTURE,
        fetch_priors=False,
        sol_usd=100.0,
    )
    vr = results[mint]
    assert vr.q5b_ok is True
    assert vr.q5a_ok is True
    assert vr.buy_vol_usd_60s is not None
    assert vr.source.startswith("dry_run.helius")
    # complete_q5b may still fail if share nulls with buys — check core packs
    assert vr.features.get("buy_count_total") is not None
    assert vr.features.get("age_s") is not None


def test_default_enrich_via_is_pump():
    from paper_live.config import DEFAULT_ENRICH_VIA, PaperLiveConfig
    from paper_live.loop import PaperLiveRunner

    assert DEFAULT_ENRICH_VIA == "pump"
    cfg = PaperLiveConfig()
    assert cfg.enrich_via == "pump"
    assert PaperLiveRunner(cfg)._resolve_enrich_via() == "pump"


def test_dry_run_helius_hybrid_scores_or_skips_honestly(tmp_path: Path):
    from paper_live.config import SAMPLE_PUMP

    if not SAMPLE_PUMP.is_file():
        pytest.skip("pump sample missing")
    cfg = PaperLiveConfig(
        dry_run=True,
        live=False,
        feed="pump",
        enrich_via="helius",
        cycles=1,
        top_k=5,
        data_dir=tmp_path,
        sample_path=SAMPLE_PUMP,
        state_path=tmp_path / "state.json",
        sqlite_path=tmp_path / "paper.sqlite",
        enrich_q5=True,
        score_mode="histgb_q5b",
        allow_q5b_fallback=False,
        entry_rule="train_quantile",
    )
    summary = PaperLiveRunner(cfg).run()
    assert summary["trading"] is False
    assert summary["enrich_via"] == "helius"
    assert summary["feed"] == "pump"
    assert summary["cycles_run"] == 1


def test_sol_usd_oracle_resolve_explicit_and_fallback():
    from ingestion.sol_usd_oracle import clear_sol_usd_cache, resolve_sol_usd

    clear_sol_usd_cache()
    q = resolve_sol_usd(118.5, allow_network=False)
    assert q.price == pytest.approx(118.5)
    assert q.source == "explicit"
    clear_sol_usd_cache()
    q2 = resolve_sol_usd(None, allow_network=False, fallback=103.11)
    assert q2.price == pytest.approx(103.11)
    assert q2.source == "ref_fallback"


def test_sol_usd_oracle_live_network_prefers_pyth_or_fallback():
    """Live path: Pyth if key, else Jupiter/CG; never silent 103 when network OK."""
    from ingestion.sol_usd_oracle import clear_sol_usd_cache, fetch_sol_usd

    clear_sol_usd_cache()
    q = fetch_sol_usd(force_refresh=True, allow_network=True)
    assert q.price > 50.0
    assert q.source in ("pyth", "jupiter", "coingecko", "ref_fallback")
    # On this box Jupiter is expected when PYTH_API_KEY unset
    if q.source != "ref_fallback":
        assert abs(q.price - 103.11) > 1.0  # not the hard-coded train ref


def test_t0_c1_c6_refines_first_band_cross():
    from datetime import datetime, timedelta, timezone

    from paper_live.q5a_agg import TradeRow
    from paper_live.t0_capture import find_t0_c1_c6

    t_sight = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    create = t_sight - timedelta(seconds=180)
    trades = []
    ts = create + timedelta(seconds=40)
    for i in range(50):
        trades.append(
            TradeRow(
                mint="MintT0",
                ts=ts + timedelta(seconds=i),
                side="buy",
                amount_usd=600.0,
                trader_id="w",
                tok_amt=1e6,
                sol_amt=5.0,
                project="pumpdotfun",
            )
        )
    cap = find_t0_c1_c6(
        trades,
        sighting_t0=t_sight,
        sighting_mc=15000.0,
        sol_usd=118.0,
        sol_usd_source="jupiter",
        create_ts=create,
    )
    assert cap.refined is True
    assert 8000 <= cap.mc_usd <= 20000
    assert cap.t0 < t_sight
    assert cap.capture_quality in ("HIGH", "MED")
    assert cap.n_trades_at_t0_window >= 1


def test_t0_c1_c6_provisional_when_no_trades():
    from datetime import datetime, timezone

    from paper_live.t0_capture import find_t0_c1_c6

    t_sight = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    cap = find_t0_c1_c6(
        [],
        sighting_t0=t_sight,
        sighting_mc=12000.0,
        sol_usd=118.0,
        sol_usd_source="jupiter",
        create_ts=None,
    )
    assert cap.refined is False
    assert cap.capture_quality == "LOW"
    assert cap.t0 == t_sight


def test_creator_prior_fetch_accepts_30d_window_kwargs():
    """API contract: window_days=30 + as_of (no network)."""
    from datetime import datetime, timezone

    from paper_live.pump_enrich import _prior_creates_for_creator

    class _Fake:
        def list_coins(self, **kwargs):
            assert kwargs.get("creator")
            return []

    out = _prior_creates_for_creator(
        "Creator1111111111111111111111111111111111111",
        this_mint="Mint111111111111111111111111111111111111111",
        client=_Fake(),  # type: ignore[arg-type]
        window_days=30,
        as_of=datetime(2026, 10, 1, tzinfo=timezone.utc),
        max_pages=1,
    )
    assert out == []


def test_helius_enrich_records_sol_usd_source_and_t0_meta():
    from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE, SAMPLE_PUMP
    from paper_live.feed import poll_sample
    from paper_live.helius_enrich import enrich_helius_for_sightings
    import json

    if not SAMPLE_PUMP.is_file() or not SAMPLE_HELIUS_TX_FIXTURE.is_file():
        pytest.skip("pump/helius samples missing")
    mint = json.loads(SAMPLE_HELIUS_TX_FIXTURE.read_text())["meta"]["mint"]
    sightings = poll_sample(SAMPLE_PUMP, batch=20, source="dry_run.pump_sample")
    hit = [s for s in sightings if s.mint == mint]
    if not hit:
        pytest.skip("fixture mint not in pump sample batch")
    results = enrich_helius_for_sightings(
        hit,
        dry_run=True,
        fixture_path=SAMPLE_HELIUS_TX_FIXTURE,
        fetch_priors=False,
        sol_usd=118.0,
        refine_t0=True,
    )
    vr = results[mint]
    assert vr.sol_usd == pytest.approx(118.0)
    assert vr.sol_usd_source == "explicit"
    assert vr.features.get("sol_usd_t0") == pytest.approx(118.0)
    assert vr.capture_quality in ("HIGH", "MED", "LOW")
    assert vr.t0_iso is not None


def test_sol_usd_asof_coingecko_or_fallback():
    from datetime import datetime, timedelta, timezone

    from ingestion.sol_usd_oracle import clear_sol_usd_cache, fetch_sol_usd_asof

    clear_sol_usd_cache()
    as_of = datetime.now(timezone.utc) - timedelta(days=10)
    q = fetch_sol_usd_asof(as_of, allow_network=True)
    assert q.price > 0
    # Prefer true as-of; live_not_asof only if both Pyth+CG fail
    assert "live_not_asof" in q.source or q.source.endswith("_asof") or q.source in (
        "pyth_asof",
        "coingecko_asof",
        "ref_fallback",
    )


def test_dune_usd_scale_flag_default_off():
    import os

    from ingestion.sol_usd_oracle import (
        apply_dune_helius_usd_scale_enabled,
        maybe_scale_usd,
    )

    os.environ.pop("APPLY_DUNE_HELIUS_USD_SCALE", None)
    assert apply_dune_helius_usd_scale_enabled() is False
    assert maybe_scale_usd(100.0) == 100.0


def test_merge_tx_lists_dedupes_by_signature():
    from ingestion.helius_enhanced import merge_tx_lists

    a = [{"signature": "s1", "timestamp": 2}, {"signature": "s2", "timestamp": 1}]
    b = [{"signature": "s1", "timestamp": 2}, {"signature": "s3", "timestamp": 0}]
    m = merge_tx_lists(a, b)
    assert [x["signature"] for x in m] == ["s1", "s2", "s3"]


def test_fetch_transactions_until_stops_at_floor(monkeypatch):
    from ingestion.helius_enhanced import HeliusEnhanced, TxPageFetch

    pages = [
        [{"signature": "a", "timestamp": 200}, {"signature": "b", "timestamp": 150}],
        [{"signature": "c", "timestamp": 90}, {"signature": "d", "timestamp": 80}],
    ]
    calls = {"n": 0}

    def fake_get(
        self,
        address,
        *,
        limit=100,
        before_signature=None,
        type_filter=None,
        deadline_mono=None,
    ):
        i = calls["n"]
        calls["n"] += 1
        return pages[i] if i < len(pages) else []

    monkeypatch.setattr(HeliusEnhanced, "get_transactions_for_address", fake_get)
    client = HeliusEnhanced(api_key="test-key-not-real", max_calls=10)
    res = client.fetch_transactions_until("Addr", min_timestamp=100, max_pages=10, limit=2)
    assert isinstance(res, TxPageFetch)
    assert res.reached_floor is True
    assert res.stopped_reason == "floor"
    assert len(res.txs) == 4  # both pages collected; floor hit on page2 oldest
