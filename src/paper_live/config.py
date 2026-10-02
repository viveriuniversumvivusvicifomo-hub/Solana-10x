"""Configuración paper-live v0 (banda MC, poll, ultra-select entry, paths)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ingestion.sol_usd_oracle import DEFAULT_SOL_USD_REF

ROOT = Path(__file__).resolve().parents[2]

# Frozen captura v0 (Sinck)
MC_LO = 8_000.0
MC_HI = 20_000.0
HIT_10X_MC_USD = 80_000.0  # 10× mid-band proxy floor; real label uses mc0 * 10
HIT_10X_MULTIPLE = 10.0

DEFAULT_POLL_INTERVAL_S = 10.0
# top_k is batch SAFETY after threshold+capacity — NOT the primary ultra-select.
# Primary gate: trainQ top1% + max_per_hour (see entry.py / paper-live-v0.md).
DEFAULT_TOP_K = 50
DEFAULT_HOURS_AGO = 2  # poll MC window (short; less noise / quota)
# Q5a trade lookback must cover create→T0 (Dune uses up to 7d). Do NOT reuse poll hours.
DEFAULT_Q5A_HOURS_AGO = 48
DEFAULT_FOLLOWUP_INTERVAL_S = 60.0
# Live: poll(1) + q5a trades(1) + q5b create(1) + q5b priors(1) ≈ 4 calls/cycle with new mints
DEFAULT_MAX_CALLS_LIVE = 8
DEFAULT_BUY_VOL_TRADE_LIMIT = 500
DEFAULT_Q5A_TRADE_LIMIT = 2000
# DEFAULT_SOL_USD_REF: last-resort when live oracle fails (train median ≈103.11); prefer Pyth/Jupiter

# Ultra-select entry (paper-trade-v1 Entrada A default)
DEFAULT_ENTRY_RULE = "train_quantile"  # train_quantile | topk_batch | off
DEFAULT_TRAIN_TOP_FRAC = 0.01  # top 1% of fold-5 train scores
DEFAULT_MAX_PER_HOUR = 2  # ~48/day ≈ trainQ_top1% OOS rate (~48.7/day)

SAMPLE_BITQUERY = ROOT / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json"
SAMPLE_PUMP = ROOT / "data" / "samples" / "pump_frontend_mc_8k_20k_sample.json"
DEFAULT_FEED = "pump"  # pump | bitquery
SAMPLE_BUY_VOL_FIXTURE = ROOT / "data" / "samples" / "buy_vol_usd_60s_fixture.json"
SAMPLE_Q5_FIXTURE = ROOT / "data" / "samples" / "q5_live_fixture.json"
SAMPLE_HELIUS_TX_FIXTURE = ROOT / "data" / "samples" / "helius_enhanced_txs_fixture.json"
DEFAULT_ENRICH_VIA = "pump"  # Path A live: Pump MC+T0+trades (Helius optional via --enrich-via helius)
# Enhanced pagination cap for ≤T0 (early-stop on create/floor; BC-first merge)
# Offline / parity recovery may use up to 80 pages.
DEFAULT_HELIUS_MAX_PAGES_PRE_T0 = 80
# Live paper: FAST enrich (Sinck 2026-10-01) — seconds not minutes. Recovery-heavy
# create→T0 stays for offline ge10/n200; live uses a tight page budget.
DEFAULT_HELIUS_MAX_PAGES_LIVE = 5
# Soft session cap for Enhanced RPC in live FAST (not Bitquery).
# Prior soft≈100 killed the daemon after ~2 cycles; continuous paper needs days of headroom.
DEFAULT_HELIUS_MAX_CALLS_LIVE = 100_000
# Live FAST fail-soft: one mint must not stall the daemon (429/backoff storms).
DEFAULT_HELIUS_MINT_TIMEOUT_S_LIVE = 25.0  # wall-clock per mint enrich fetch
DEFAULT_HELIUS_HTTP_TIMEOUT_S_LIVE = 10.0  # httpx (vs 45s offline)
DEFAULT_HELIUS_MAX_RETRIES_429_LIVE = 2  # vs 10 offline recovery
DEFAULT_HELIUS_MAX_BACKOFF_S_LIVE = 5.0  # cap 429/5xx sleep in live
DATA_DIR = ROOT / "data" / "paper_live"
STATE_PATH = DATA_DIR / "state.json"
SQLITE_PATH = DATA_DIR / "paper_journal.sqlite"
CANDIDATES_CSV = DATA_DIR / "candidates.csv"
FOLLOWUP_CSV = DATA_DIR / "followup.csv"
SIGHTINGS_CSV = DATA_DIR / "sightings.csv"
MODEL_DIR = DATA_DIR / "models"
MODEL_BUY60_PATH = MODEL_DIR / "buy60_last.joblib"
MODEL_Q5B_PATH = MODEL_DIR / "q5b_last.joblib"
CALIBRATION_Q5B_PATH = MODEL_DIR / "q5b_calibration.json"
LITE_CALIBRATION_PATH = MODEL_DIR / "lite_calibration.json"
CANDIDATES_LITE_CSV = DATA_DIR / "candidates_lite.csv"

# Default scorer = trained WF recipe (+q5b)
DEFAULT_SCORE_MODE = "histgb_q5b"


@dataclass
class PaperLiveConfig:
    """Parámetros del tracker. Defaults: dry-run + histgb_q5b + trainQ top1% entry."""

    mc_lo: float = MC_LO
    mc_hi: float = MC_HI
    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    followup_interval_s: float = DEFAULT_FOLLOWUP_INTERVAL_S
    top_k: int = DEFAULT_TOP_K
    hours_ago: int = DEFAULT_HOURS_AGO
    q5a_hours_ago: int = DEFAULT_Q5A_HOURS_AGO
    sol_usd_ref: float = DEFAULT_SOL_USD_REF
    max_calls_live: int = DEFAULT_MAX_CALLS_LIVE
    dry_run: bool = True
    live: bool = False
    feed: str = DEFAULT_FEED  # pump | bitquery
    enrich_via: str = DEFAULT_ENRICH_VIA  # helius | pump | bitquery | auto
    score_mode: str = DEFAULT_SCORE_MODE  # histgb_q5b | histgb_buy60 | rule_buy60
    cycles: int = 0  # 0 = infinite until Ctrl-C / max_calls
    data_dir: Path = field(default_factory=lambda: DATA_DIR)
    sample_path: Path = field(default_factory=lambda: SAMPLE_PUMP)
    buy_vol_fixture_path: Path = field(default_factory=lambda: SAMPLE_BUY_VOL_FIXTURE)
    q5_fixture_path: Path = field(default_factory=lambda: SAMPLE_Q5_FIXTURE)
    state_path: Path = field(default_factory=lambda: STATE_PATH)
    sqlite_path: Path = field(default_factory=lambda: SQLITE_PATH)
    backfill: bool = True  # al arrancar, marcar sample/live rows ya vistas sin paper-enter
    enrich_buy_vol: bool = True  # legacy: buy_vol alone (used if enrich_q5 False)
    enrich_q5: bool = True  # full +q5b ≤T0 (Q5a+Q5b+buy60 via Helius/Bitquery/fixture)
    enrich_q5a: bool = True
    enrich_q5b: bool = True
    allow_q5b_fallback: bool = False  # DEBUG only — never invent score when features missing
    buy_vol_trade_limit: int = DEFAULT_BUY_VOL_TRADE_LIMIT
    q5a_trade_limit: int = DEFAULT_Q5A_TRADE_LIMIT
    skip_missing_buy_vol: bool = True  # skip paper-enter if buy_vol unavailable
    skip_incomplete_q5b: bool = True  # histgb_q5b: skip unless full FEATURE_SETS['+q5b']
    # Live↔train parity gates (ZERO tolerance MUST-FIX 2026-10-01)
    require_t0_refined: bool = False  # Path A Pump sets t0_refined on MC sighting; Helius C1–C6 optional
    max_age_s: float = 86_400.0  # skip age_s >1d (old mint re-band / bad create_ts)
    require_pyth_when_key: bool = True  # if PYTH/HERMES key set, skip non-pyth SOL/USD
    # Ultra-select entry (theory-aligned)
    entry_rule: str = DEFAULT_ENTRY_RULE
    train_top_frac: float = DEFAULT_TRAIN_TOP_FRAC
    score_threshold: float | None = 0.99  # Sinck product 2026-10-01 (live_entry_config.json)
    allow_non_train_threshold: bool = False  # retained no-op; explicit --score-threshold allowed
    max_per_hour: int = DEFAULT_MAX_PER_HOUR
    # Multi-scorer (opt-in): comma modes or list; default single histgb lane.
    parallel_score_modes: str = ""  # e.g. "histgb_q5b,lite" — empty = score_mode only
    score_threshold_lite: float | None = 0.55  # explore lane stub thr
    max_per_hour_lite: int = DEFAULT_MAX_PER_HOUR
    enable_lite_lane: bool = False  # convenience: append lite to parallel modes

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "models").mkdir(parents=True, exist_ok=True)
