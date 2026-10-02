"""Hybrid enrich: Pump.fun Q5b (age/creator/name) + Helius Enhanced ≤T0 trades → Q5a + buy60.

Train parity target: ``FEATURE_SETS['+q5b']`` for ``histgb_q5b``.

Discovery stays on Pump frontend (MC 8k–20k). Helius fills the trades gap that
frontend ``/trades/all/{mint}`` cannot (chainId schema) and Bitquery FREE often
blocks (402). Streams Helius remain OFF — pull Enhanced history only.

Anti look-ahead: discard txs with timestamp > mint T0; buy60 window [t0−60s, t0].
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS
from ingestion.helius_trade_parse import (
    ParsedTrade,
    parse_helius_enhanced_txs as _ingestion_parse_helius,
)
from ingestion.helius_enhanced import (
    DEFAULT_MAX_PAGES_PRE_T0,
    fetch_create_to_t0_txs,
    fetch_pre_t0_enhanced_txs,
)
from ingestion.q5b_age import AGE_MAX_SCOREABLE_S, age_s_from_create
from ingestion.sol_usd_oracle import (
    DEFAULT_SOL_USD_REF,
    USD_RECALIB_PLAN,
    _optional_pyth_key,
    apply_dune_helius_usd_scale_enabled,
    dune_helius_usd_scale_factor,
    maybe_scale_usd,
    resolve_sol_usd,
    resolve_sol_usd_for_scoring,
)
from ingestion.t0_capture import (
    _quality_for_source,
    find_t0_c1_c6,
    find_t0_c1_c6_train_aligned,
    find_t0_dune_q3,
    is_scoreable_capture,
    score_reject_reason,
)
from paper_live.buy_vol import WINDOW_S
from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE
from paper_live.creator_priors import (
    CREATOR_PRIOR_SOURCE_EMPTY,
    CREATOR_PRIOR_SOURCE_EXACT,
    CREATOR_PRIOR_SOURCE_NONE,
    CREATOR_PRIOR_SOURCE_RECOMPUTE,
    CREATOR_PRIOR_SOURCE_TRAIN,
    allow_pump_frontend_priors,
    resolve_creator_priors,
)
from paper_live.feed import MintSighting
from paper_live.pump_enrich import (
    _create_from_sighting,
)
from paper_live.q5a_agg import TradeRow, aggregate_q5a_for_mint
from paper_live.q5b_agg import (
    CreateRow,
    prefer_sighting_meta_name_symbol,
    fill_meta_from_dune_store_exact,
    q5b_from_create,
)

# Enhanced ``source`` values we map to Dune-style project labels.
# Train Dune Q5a/Q4: project IN ('pumpdotfun','pumpswap') ONLY — drop everything else.
_PUMP_SOURCES = frozenset({"PUMP_FUN", "PUMP.FUN", "PUMPFUN"})
# PUMP_AMM = post-grad Pump AMM (Helius) ≈ Dune pumpswap. Do NOT map RAYDIUM/Jupiter/OKX.
_PUMPSWAP_SOURCES = frozenset({"PUMP_SWAP", "PUMPSWAP", "PUMP_AMM"})


@dataclass
class HeliusEnrichResult:
    mint: str
    features: dict[str, Any] = field(default_factory=dict)
    buy_vol_usd_60s: float | None = None
    buy_count_60s: int | None = None
    q5a_ok: bool = False
    q5b_ok: bool = False
    source: str = "hybrid.pump+helius"
    detail: str = ""
    gaps: list[str] = field(default_factory=list)
    n_txs_fetched: int = 0
    n_trades_pre_t0: int = 0
    t0_iso: str | None = None
    mc_usd_t0: float | None = None
    capture_quality: str | None = None
    sol_usd: float | None = None
    sol_usd_source: str | None = None
    t0_refined: bool = False
    capture_scoreable: bool = False
    score_reject: str | None = None

    @property
    def complete_q5b(self) -> bool:
        if not (self.q5a_ok and self.q5b_ok and self.buy_vol_usd_60s is not None):
            return False
        for c in FEATURE_SETS["+q5b"]:
            if c == "creator_prior_mints_all_in_window":
                continue
            if self.features.get(c) is None:
                if c.endswith("_share") or c.endswith("_pct_proxy") or c in (
                    "max_buy_share",
                    "max_buy_sol",
                    "max_buy_usd",
                    "sniper_vol_share_5s",
                    "first5_buy_vol_share",
                ):
                    if float(self.features.get("buy_count_total") or 0) == 0:
                        continue
                return False
        return True


def _t0(s: MintSighting) -> datetime:
    return s.seen_at if s.seen_at.tzinfo else s.seen_at.replace(tzinfo=timezone.utc)


def _bonding_curve_for(s: MintSighting) -> str | None:
    raw = s.raw or {}
    bc = raw.get("bonding_curve") or s.market_address
    if bc:
        return str(bc)
    nested = raw.get("raw_coin") if isinstance(raw.get("raw_coin"), dict) else {}
    if nested.get("bonding_curve"):
        return str(nested["bonding_curve"])
    try:
        from ingestion.bonding_curve import bonding_curve_pda

        return str(bonding_curve_pda(s.mint))
    except Exception:  # noqa: BLE001
        return None


def _project_from_source(source: str | None) -> str:
    src = (source or "").upper()
    if src in _PUMP_SOURCES:
        return "pumpdotfun"
    if src in _PUMPSWAP_SOURCES or "PUMPSWAP" in src:
        return "pumpswap"
    return "other"


def parse_helius_enhanced_txs(
    txs: list[dict[str, Any]],
    *,
    mint: str,
    bonding_curve: str | None,
    sol_usd: float = DEFAULT_SOL_USD_REF,
    min_amount_usd: float = 1.0,
    t0: datetime | None = None,
) -> list[TradeRow]:
    """Parse Enhanced → TradeRow. Canonical logic: ``ingestion.helius_trade_parse``."""
    parsed = _ingestion_parse_helius(
        txs,
        mint=mint,
        bonding_curve=bonding_curve,
        sol_usd=sol_usd,
        min_amount_usd=min_amount_usd,
        t0=t0,
        dune_project_only=True,
    )
    return [
        TradeRow(
            mint=r.mint,
            ts=r.ts,
            side=r.side,
            amount_usd=r.amount_usd,
            trader_id=r.trader_id,
            tok_amt=r.tok_amt,
            sol_amt=r.sol_amt,
            project=r.project,
        )
        for r in parsed
    ]



def _sol_amt_from_tx(
    tx: dict[str, Any],
    *,
    bonding_curve: str | None,
    fee_payer: str,
    side: str,
) -> float:
    """SOL UI amount for the trade (absolute). Prefer bonding-curve balance change."""
    if bonding_curve:
        for ad in tx.get("accountData") or []:
            if ad.get("account") != bonding_curve:
                continue
            try:
                ch = int(ad.get("nativeBalanceChange") or 0)
            except (TypeError, ValueError):
                ch = 0
            if ch != 0:
                return abs(ch) / 1e9
        # nativeTransfers involving curve
        nts = tx.get("nativeTransfers") or []
        if side == "buy":
            into = sum(
                int(n.get("amount") or 0)
                for n in nts
                if n.get("toUserAccount") == bonding_curve
            )
            if into > 0:
                return into / 1e9
        else:
            out = sum(
                int(n.get("amount") or 0)
                for n in nts
                if n.get("fromUserAccount") == bonding_curve
            )
            if out > 0:
                return out / 1e9

    nts = tx.get("nativeTransfers") or []
    if side == "buy":
        out = sum(int(n.get("amount") or 0) for n in nts if n.get("fromUserAccount") == fee_payer)
        # subtract tiny rent/fees heuristic: take largest single transfer if many small
        amounts = sorted(
            (int(n.get("amount") or 0) for n in nts if n.get("fromUserAccount") == fee_payer),
            reverse=True,
        )
        if amounts:
            return amounts[0] / 1e9
        if out > 0:
            return out / 1e9
    else:
        amounts = sorted(
            (int(n.get("amount") or 0) for n in nts if n.get("toUserAccount") == fee_payer),
            reverse=True,
        )
        if amounts:
            return amounts[0] / 1e9
    return 0.0


def buy_vol_60s_from_trades(
    trades: list[TradeRow],
    t0: datetime,
    *,
    window_s: int = WINDOW_S,
) -> tuple[float, int]:
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    lo = t0.timestamp() - window_s
    hi = t0.timestamp()
    vol = 0.0
    n = 0
    for tr in trades:
        if tr.side != "buy":
            continue
        ts = tr.ts.timestamp()
        if lo <= ts <= hi:
            vol += tr.amount_usd
            n += 1
    return vol, n


def load_helius_tx_fixture(path: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    p = path or SAMPLE_HELIUS_TX_FIXTURE
    data = json.loads(p.read_text())
    by_mint = data.get("by_mint") or {}
    return {str(k): list(v) for k, v in by_mint.items()}



def enrich_helius_for_sightings(
    sightings: list[MintSighting],
    *,
    client: Any | None = None,
    pump_client: Any | None = None,
    dry_run: bool = False,
    fixture_path: Path | None = None,
    fetch_priors: bool = True,
    sol_usd: float | None = None,
    max_pages_per_mint: int = DEFAULT_MAX_PAGES_PRE_T0,
    page_limit: int = 100,
    refine_t0: bool = True,
    sol_usd_as_of_t0: bool = True,
    mint_timeout_s: float | None = None,
    heartbeat: bool = False,
) -> dict[str, HeliusEnrichResult]:
    """Hybrid: Q5b from Pump coin fields (+ optional creator priors); Q5a/buy60 from Helius.

    Path A (SolDatos MUST-FIX wire):
      - USD: ``resolve_sol_usd_for_scoring(..., require_pyth=bool(PYTH/HERMES key))``
        → with key: sol×pyth_asof (strict); without key: Pyth if reachable else
        CG as-of / Jupiter live / ref (MED OK; Sinck any-oracle)
      - Trades: ``fetch_create_to_t0_txs`` (BC Enhanced + RPC create→T0)
      - Age: ``age_s_from_create`` (not Q5a age_proxy_s)
      - Gate: ``is_scoreable_capture`` refuses LOW/unrefined; non-Pyth only when key set
    Explicit ``sol_usd`` still wins (tests). Scale flag default OFF (not Path A).
    """
    owns_helius = False
    owns_pump = False
    fixture: dict[str, list[dict[str, Any]]] | None = None

    if dry_run or client is None:
        fixture = load_helius_tx_fixture(fixture_path)
        dry_run = True
    else:
        # live client provided
        pass

    # Pump client only when ALLOW_PUMP_FRONTEND_PRIORS=1 (non-parity fallback)
    if (
        fetch_priors
        and not dry_run
        and pump_client is None
        and allow_pump_frontend_priors()
    ):
        from ingestion.pump_frontend import PumpFrontendClient

        pump_client = PumpFrontendClient()
        owns_pump = True

    # Path A oracle: explicit (tests) else require Pyth only when PYTH/HERMES key set.
    # Without key: Jupiter/CG/as-of fallbacks are scoreable (MED + allow_med).
    as_of_batch = None
    if sol_usd is None and sol_usd_as_of_t0 and sightings:
        as_of_batch = _t0(sightings[0])
    batch_gaps: list[str] = []
    require_pyth = bool(_optional_pyth_key())
    if not require_pyth:
        batch_gaps.append("PYTH_API_KEY_missing")
    pyth_scoring_ok = False
    if sol_usd is not None and float(sol_usd) > 0:
        quote = resolve_sol_usd(sol_usd, allow_network=False)
        pyth_scoring_ok = True  # explicit test bypass
    elif dry_run:
        quote = resolve_sol_usd(
            None,
            allow_network=False,
            fallback=DEFAULT_SOL_USD_REF,
            as_of=None,
        )
        pyth_scoring_ok = False
    else:
        q_score, reason = resolve_sol_usd_for_scoring(
            as_of_batch,
            allow_network=True,
            require_pyth=require_pyth,
        )
        if q_score is not None:
            quote = q_score
            # scoring oracle OK (pyth when required; else any preferred fallback)
            pyth_scoring_ok = True
        else:
            batch_gaps.append(f"pyth_asof_unavailable:{reason}")
            quote = resolve_sol_usd(
                None,
                allow_network=True,
                fallback=DEFAULT_SOL_USD_REF,
                as_of=as_of_batch,
            )
            pyth_scoring_ok = False
    sol_px = float(quote.price)
    sol_src = quote.source
    scale_on = apply_dune_helius_usd_scale_enabled()
    scale_factor = dune_helius_usd_scale_factor() if scale_on else 1.0
    if scale_on:
        batch_gaps.append(f"dune_helius_usd_scale_ON={scale_factor:g}_NOT_path_A")

    results: dict[str, HeliusEnrichResult] = {}
    n_sight = len(sightings)
    enrich_t0_mono = time.monotonic()
    try:
        for mint_i, s in enumerate(sightings, start=1):
            gaps: list[str] = list(batch_gaps)
            mint_pyth_ok = bool(pyth_scoring_ok)
            t0 = _t0(s)
            create = _create_from_sighting(s)
            bc = _bonding_curve_for(s)
            if heartbeat or mint_timeout_s is not None:
                elapsed = time.monotonic() - enrich_t0_mono
                print(
                    f"[paper-live] enrich {mint_i}/{n_sight} mint={s.mint[:12]}… "
                    f"elapsed={elapsed:.1f}s",
                    flush=True,
                )

            # --- Q5b (Pump + train-store creator priors when available) ---
            priors: list[CreateRow] | None = []
            prior_src = None
            prior_overlay = None
            if create and not create.creator_pubkey:
                gaps.append("no creator on coin — priors skipped")
                if not dry_run and client is not None:
                    creator = _creator_from_bonding_curve(s.mint, bc)
                    if creator and create:
                        create = CreateRow(
                            mint=create.mint,
                            creator_pubkey=creator,
                            create_ts=create.create_ts,
                            token_name=create.token_name,
                            token_symbol=create.token_symbol,
                        )
                        gaps.append("creator_from_bonding_curve")
            prior_overlay = None
            if fetch_priors and create and create.creator_pubkey:
                try:
                    resolved = resolve_creator_priors(
                        mint=s.mint,
                        creator=create.creator_pubkey,
                        create_ts=create.create_ts,
                        pump_client=pump_client,
                    )
                    prior_src = resolved.source
                    priors = list(resolved.prior_creates)
                    prior_overlay = resolved.exact_overlay
                    n_priors = (
                        "exact"
                        if prior_overlay is not None
                        else str(len(priors))
                    )
                    gaps.append(
                        f"creator_priors={prior_src} n={n_priors}"
                        + (f" path={resolved.path}" if resolved.path else "")
                    )
                    if prior_src not in (
                        CREATOR_PRIOR_SOURCE_EXACT,
                        CREATOR_PRIOR_SOURCE_RECOMPUTE,
                        CREATOR_PRIOR_SOURCE_EMPTY,
                        CREATOR_PRIOR_SOURCE_TRAIN,
                    ):
                        gaps.append(f"creator_priors_incomplete={prior_src}")
                except Exception as e:  # noqa: BLE001
                    gaps.append(f"creator_priors_resolve_failed: {str(e)[:120]}")
                    priors = []
                    prior_src = CREATOR_PRIOR_SOURCE_NONE
                    prior_overlay = None
                    gaps.append("creator_priors_incomplete=none")
            elif fetch_priors:
                prior_src = CREATOR_PRIOR_SOURCE_NONE
                gaps.append("creator_priors_incomplete=none")

            # --- Helius Enhanced txs (≤ sighting first; may refine T0) ---
            txs: list[dict[str, Any]] = []
            n_fetched = 0
            try:
                if dry_run:
                    txs = list(fixture.get(s.mint) or []) if fixture else []
                    if not txs:
                        gaps.append("helius_fixture_missing_mint")
                    n_fetched = len(txs)
                else:
                    assert client is not None
                    create_ts = create.create_ts if create else None
                    raw = s.raw or {}
                    create_sig = raw.get("create_signature") or raw.get("signature")
                    if isinstance(create_sig, str) and not create_sig:
                        create_sig = None
                    deadline_mono = None
                    if mint_timeout_s is not None and float(mint_timeout_s) > 0:
                        deadline_mono = time.monotonic() + float(mint_timeout_s)

                    def _do_fetch(
                        _deadline=deadline_mono,
                        _create_ts=create_ts,
                        _bc=bc,
                        _t0=t0,
                    ):
                        return fetch_create_to_t0_txs(
                            client,
                            s.mint,
                            t0=_t0,
                            create_ts=_create_ts,
                            bonding_curve=_bc,
                            max_pages_enhanced=max_pages_per_mint,
                            deadline_mono=_deadline,
                        )

                    if mint_timeout_s is not None and float(mint_timeout_s) > 0:
                        # Hard wall: skip mint if fetch exceeds timeout (fail-soft).
                        # wait=False so a stuck HTTP call cannot stall the cycle.
                        pool = ThreadPoolExecutor(max_workers=1)
                        try:
                            fut = pool.submit(_do_fetch)
                            try:
                                txs, fetch_gaps = fut.result(
                                    timeout=float(mint_timeout_s) + 1.0
                                )
                            except FuturesTimeoutError:
                                gaps.append(
                                    f"helius_mint_timeout>{float(mint_timeout_s):g}s"
                                )
                                txs, fetch_gaps = [], [
                                    f"helius_mint_timeout>{float(mint_timeout_s):g}s"
                                ]
                        finally:
                            pool.shutdown(wait=False, cancel_futures=True)
                    else:
                        txs, fetch_gaps = _do_fetch()
                    if create_sig:
                        gaps.append(f"create_sig_hint={str(create_sig)[:16]}")
                    gaps.extend(fetch_gaps)
                    n_fetched = len(txs)
            except Exception as e:  # noqa: BLE001
                gaps.append(f"helius_tx_fetch_failed: {str(e)[:160]}")
                txs = []

            # Parse with sighting T0 ceiling first (no look-ahead past poll)
            trades_all = parse_helius_enhanced_txs(
                txs,
                mint=s.mint,
                bonding_curve=bc,
                sol_usd=sol_px,
                t0=t0,
            )

            cap = None
            t0_use = t0
            mc_use = float(s.mc_usd)
            if refine_t0:
                complete_false = True
                raw = s.raw or {}
                nested = raw.get("raw_coin") if isinstance(raw.get("raw_coin"), dict) else raw
                if nested.get("complete") is True or raw.get("complete") is True:
                    complete_false = False
                # Train-aligned C4: age≈0 snipers (Q3 labels) fail product tradeable≥30s
                cap = find_t0_c1_c6_train_aligned(
                    trades_all,
                    sighting_t0=t0,
                    sighting_mc=float(s.mc_usd),
                    sol_usd=sol_px,
                    sol_usd_source=sol_src,
                    create_ts=create.create_ts if create else None,
                    complete_false=complete_false,
                )
                t0_use = cap.t0
                mc_use = float(cap.mc_usd)
                if cap.refined:
                    gaps.append(f"t0_refined_c1c6:{cap.detail}")
                else:
                    gaps.append(f"t0_provisional:{cap.detail}")
                if not str(sol_src).startswith("pyth"):
                    gaps.append(f"sol_usd_source={sol_src}")
                    if _optional_pyth_key():
                        gaps.append("sol_usd_pyth_key_present_but_source_not_pyth")

            # Path A: re-resolve SOL/USD as-of refined T0 (strict Pyth only when key set)
            mint_pyth_ok = pyth_scoring_ok
            if sol_usd is None and sol_usd_as_of_t0 and not dry_run:
                q2, reason2 = resolve_sol_usd_for_scoring(
                    t0_use,
                    allow_network=True,
                    require_pyth=require_pyth,
                )
                if q2 is not None:
                    sol_px = float(q2.price)
                    sol_src = q2.source
                    mint_pyth_ok = True
                    trades_all = parse_helius_enhanced_txs(
                        txs,
                        mint=s.mint,
                        bonding_curve=bc,
                        sol_usd=sol_px,
                        t0=t0_use,
                    )
                    if cap is not None:
                        # keep CaptureT0 source/quality aligned for is_scoreable_capture
                        from dataclasses import replace

                        try:
                            cap = replace(
                                cap,
                                sol_usd=sol_px,
                                sol_usd_source=sol_src,
                                capture_quality=_quality_for_source(sol_src),
                            )
                        except TypeError:
                            pass
                else:
                    mint_pyth_ok = False
                    gaps.append(f"pyth_asof_unavailable_refined:{reason2}")
                    # fallback enrich-only (journal); not scoreable when Pyth required
                    q_fb = resolve_sol_usd(
                        None,
                        allow_network=True,
                        fallback=DEFAULT_SOL_USD_REF,
                        as_of=t0_use,
                    )
                    sol_px = float(q_fb.price)
                    sol_src = q_fb.source
                    trades_all = parse_helius_enhanced_txs(
                        txs,
                        mint=s.mint,
                        bonding_curve=bc,
                        sol_usd=sol_px,
                        t0=t0_use,
                    )

            # Re-parse / filter ≤ refined T0
            trades = [tr for tr in trades_all if tr.ts <= t0_use]
            # Q5b at refined T0 (age/priors causal); exact store overlay when mint in CSV
            q5b = q5b_from_create(create, t0_use, prior_creates=priors)
            if prior_overlay:
                q5b.update(prior_overlay)
            q5b = prefer_sighting_meta_name_symbol(q5b, name=s.name, symbol=s.symbol)
            # Train-store meta fill when create/sighting still lack name/symbol (ge10 parity)
            try:
                from paper_live.creator_priors import load_creator_prior_index

                _meta = load_creator_prior_index().exact_meta_for_mint(s.mint)
                q5b = fill_meta_from_dune_store_exact(q5b, _meta)
            except Exception as e:  # noqa: BLE001
                gaps.append(f"meta_store_lookup_failed:{str(e)[:80]}")
            if q5b.get("meta_source"):
                gaps.append(f"meta_source={q5b['meta_source']}")
            q5b_ok = bool(q5b.get("q5b_complete"))

            q5a = aggregate_q5a_for_mint(trades, t0_use)
            buy60, buy_n = buy_vol_60s_from_trades(trades, t0_use)
            q5a_ok = True  # empty trades ≤T0 is a valid observation
            if scale_on:
                buy60 = maybe_scale_usd(buy60)
                for usd_col in (
                    "buy_vol_usd_total",
                    "buy_vol_usd_15m",
                    "buy_vol_usd_30s",
                    "first5_buy_vol_usd",
                    "first10_buy_vol_usd",
                    "max_buy_usd",
                    "max_buy_sol",  # leave SOL legs unscaled
                ):
                    if usd_col.endswith("_sol"):
                        continue
                    if q5a.get(usd_col) is not None:
                        q5a[usd_col] = maybe_scale_usd(float(q5a[usd_col]))
                gaps.append(f"dune_helius_usd_scale={scale_factor:g}")

            # Path A age: Dune Q5b create→t0 via age_s_from_create (not Q5a age_proxy)
            age_info = age_s_from_create(
                create.create_ts if create else None,
                t0_use,
                max_age_s=AGE_MAX_SCOREABLE_S,
            )
            q5b["age_s"] = age_info.age_s
            q5b["age_min"] = age_info.age_min
            q5b["age_from_create_ok"] = age_info.ok
            q5b["age_from_create_reason"] = age_info.reason
            if not age_info.ok:
                gaps.append(f"age_s_from_create:{age_info.reason}")
                q5b_ok = False

            feats: dict[str, Any] = {}
            for col in Q5B_COLS:
                feats[col] = q5b.get(col)
            feats["creator_pubkey"] = q5b.get("creator_pubkey")
            feats["create_ts"] = q5b.get("create_ts")
            if q5b.get("meta_source"):
                feats["meta_source"] = q5b["meta_source"]
            for col in Q5A_COLS:
                feats[col] = q5a.get(col)
            feats["buy_vol_usd_60s"] = float(buy60)
            feats["sol_usd_t0"] = sol_px
            feats["sol_usd_source"] = sol_src
            feats["dune_helius_usd_scale_applied"] = bool(scale_on)
            feats["dune_helius_usd_scale_factor"] = float(scale_factor) if scale_on else None
            feats["capture_quality"] = cap.capture_quality if cap else "LOW"
            feats["t0_refined"] = bool(cap.refined) if cap else False
            feats["mc_usd_t0_capture"] = mc_use
            feats["creator_prior_source"] = prior_src or CREATOR_PRIOR_SOURCE_NONE
            # Incomplete = not Dune-cohort exact/recompute/empty (train-parity family)
            _parity_sources = (
                CREATOR_PRIOR_SOURCE_EXACT,
                CREATOR_PRIOR_SOURCE_RECOMPUTE,
                CREATOR_PRIOR_SOURCE_EMPTY,
                CREATOR_PRIOR_SOURCE_TRAIN,  # legacy alias
            )
            feats["creator_priors_incomplete"] = (
                prior_src or CREATOR_PRIOR_SOURCE_NONE
            ) not in _parity_sources
            feats["n_trades_pre_t0"] = len(trades)
            feats["age_from_create_ok"] = bool(age_info.ok)
            feats["age_from_create_reason"] = age_info.reason
            feats["usd_recalib_plan"] = USD_RECALIB_PLAN.get("chosen")
            feats["pyth_scoring_ok"] = bool(mint_pyth_ok)

            # Path A scoring gate (C1–C6 refined; Pyth HIGH only when key set)
            scoreable = False
            reject = "no_capture"
            if cap is not None:
                # Dry/explicit or no Pyth key: allow MED (Jupiter/CG) for scoring
                gate_require_pyth = (
                    not dry_run and sol_usd is None and bool(_optional_pyth_key())
                )
                gate_allow_med = (
                    dry_run or sol_usd is not None or not bool(_optional_pyth_key())
                )
                scoreable = is_scoreable_capture(
                    cap, require_pyth=gate_require_pyth, allow_med=gate_allow_med
                )
                reject = score_reject_reason(
                    cap, require_pyth=gate_require_pyth, allow_med=gate_allow_med
                )
            if not age_info.ok:
                scoreable = False
                reject = (reject + ";" if reject else "") + f"age:{age_info.reason}"
            if not mint_pyth_ok and not dry_run and sol_usd is None:
                scoreable = False
                reject = (reject + ";" if reject else "") + "pyth_asof_unavailable"
            if reject:
                gaps.append(f"score_reject:{reject}")
            feats["capture_scoreable"] = bool(scoreable)
            feats["score_reject_reason"] = reject

            # Train parity: empty ≤T0 trades → Q5a zeros/nulls from aggregate_q5a_for_mint.
            # Do NOT overlay Pump frontend reserve proxies (diverges from Dune trade-only path).

            src = (
                "dry_run.helius_fixture+pump_coin"
                if dry_run
                else "hybrid.pump.frontend+helius.enhanced"
            )
            detail = (
                f"n_txs={n_fetched} n_trades_pre_t0={len(trades)} buy60_n={buy_n} "
                f"sol_usd={sol_px:.4f}({sol_src}) t0_refined={bool(cap and cap.refined)} "
                f"scoreable={scoreable}"
            )
            results[s.mint] = HeliusEnrichResult(
                mint=s.mint,
                features=feats,
                buy_vol_usd_60s=float(buy60),
                buy_count_60s=int(buy_n),
                q5a_ok=q5a_ok,
                q5b_ok=q5b_ok,
                source=src,
                detail=detail,
                gaps=gaps,
                n_txs_fetched=n_fetched,
                n_trades_pre_t0=len(trades),
                t0_iso=t0_use.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
                mc_usd_t0=mc_use,
                capture_quality=cap.capture_quality if cap else "LOW",
                sol_usd=sol_px,
                sol_usd_source=sol_src,
                t0_refined=bool(cap.refined) if cap else False,
                capture_scoreable=bool(scoreable),
                score_reject=reject,
            )
        return results
    finally:
        if owns_helius and client is not None:
            client.close()
        if owns_pump and pump_client is not None:
            pump_client.close()


def _creator_from_bonding_curve(mint: str, bonding_curve: str | None) -> str | None:
    """Best-effort creator pubkey from BondingCurve account (1 Helius RPC call)."""
    try:
        from ingestion.bonding_curve import fetch_bonding_curve

        st = fetch_bonding_curve(mint)
        return st.creator
    except Exception:  # noqa: BLE001
        return None

