"""Path A live enrich: Pump.fun MC + T0 + trades (no Helius Enhanced gate).

Sinck 2026-10-02 binding
------------------------
- Captura / score gate: Pump ``usd_market_cap`` ∈ [8k,20k] + create age OK.
  ``capture_scoreable`` is True **without** Helius ``t0_refined`` / trade MC path.
- T0 = sighting ``seen_at`` (first Pump poll in band).
- Trades / buy_vol / Q5a: Pump frontend ``GET /trades/{chainId}/{mint}``
  (cursor-paginated). Legacy ``/trades/all/{mint|chainId}`` stays broken;
  leave buy_vol/Q5a null only if the new route fails (honest — do not invent).
- Helius remains optional via ``--enrich-via helius``; not the live Path A gate.

Q5b (age/creator/name) from Pump coin; creator prior *counts* from local
Dune cohort store (exact → recompute → empty), stamped as ``creator_prior_source``.
Pump ``/coins?creator=`` remains diagnostic/gap only (not model features).

Q5a curve / age_proxy (2026-10-02 Path A)
-----------------------------------------
When pre-T0 trades exist, keep ``progress_curve_proxy`` / ``net_sol_curve`` /
``age_proxy_s`` from ``q5a_agg`` (train recipe). Do **not** overwrite with Pump
coin bonding proxies or create→T0 ``age_s``. Coin overlay is gap-fill only when
trades are empty; stamp ``q5a_curve_age_source`` (``q5a_trades`` |
``pump_coin_gapfill``). Gate ``age_s`` remains create→T0 via ``age_s_from_create``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS
from ingestion.pump_frontend import (
    PumpFrontendClient,
    created_dt,
    curve_progress_proxy,
    fetch_creator_coins,
    fetch_trades_for_mint,
    net_sol_curve_proxy,
)
from ingestion.q5b_age import AGE_MAX_SCOREABLE_S, age_s_from_create
from ingestion.t0_capture import (
    PUMP_MC_SIGHTING_DEF,
    find_t0_pump_mc_sighting,
    is_scoreable_pump_capture,
    score_reject_reason_pump,
)
from paper_live.buy_vol import WINDOW_S
from paper_live.creator_priors import (
    CREATOR_PRIOR_SOURCE_EMPTY,
    CREATOR_PRIOR_SOURCE_EXACT,
    CREATOR_PRIOR_SOURCE_NONE,
    CREATOR_PRIOR_SOURCE_RECOMPUTE,
    CREATOR_PRIOR_SOURCE_TRAIN,
    load_creator_prior_index,
    resolve_creator_priors,
)
from paper_live.feed import MintSighting
from paper_live.q5a_agg import TradeRow, aggregate_q5a_for_mint
from paper_live.q5b_agg import (
    CreateRow,
    prefer_sighting_meta_name_symbol,
    fill_meta_from_dune_store_exact,
    q5b_from_create,
)

# Legacy gap string (kept for journal grep). Prefer working
# ``/trades/{chainId}/{mint}`` — only append this when that route fails too.
PUMP_TRADES_API_GAP = (
    "pump_trades_api_gap:fetch_failed "
    "(legacy /trades/all broken; working path is /trades/{chainId}/{mint})"
)


@dataclass
class PumpEnrichResult:
    mint: str
    features: dict[str, Any] = field(default_factory=dict)
    buy_vol_usd_60s: float | None = None
    buy_count_60s: int | None = None
    q5a_ok: bool = False
    q5b_ok: bool = False
    complete_q5b: bool = False
    source: str = "pump.frontend-api-v3"
    detail: str = ""
    gaps: list[str] = field(default_factory=list)
    n_trades_pre_t0: int = 0
    t0_iso: str | None = None
    mc_usd_t0: float | None = None
    capture_quality: str | None = None
    t0_refined: bool = False
    capture_scoreable: bool = False
    score_reject: str | None = None

    @property
    def complete_q5b_pack(self) -> bool:
        return self.complete_q5b


def _t0(s: MintSighting) -> datetime:
    return s.seen_at if s.seen_at.tzinfo else s.seen_at.replace(tzinfo=timezone.utc)


def _create_from_sighting(s: MintSighting) -> CreateRow | None:
    raw = s.raw or {}
    cts = created_dt(raw) or created_dt({"created_timestamp": raw.get("created_timestamp")})
    if cts is None and raw.get("created_timestamp") is None:
        nested = raw.get("raw_coin") if isinstance(raw.get("raw_coin"), dict) else {}
        cts = created_dt(nested) if nested else None
    if cts is None:
        return None
    creator = raw.get("creator") or (raw.get("raw_coin") or {}).get("creator")
    return CreateRow(
        mint=s.mint,
        creator_pubkey=str(creator) if creator else None,
        create_ts=cts,
        token_name=s.name,
        token_symbol=s.symbol,
    )


def _prior_creates_for_creator(
    creator: str,
    *,
    this_mint: str,
    client: PumpFrontendClient,
    limit: int = 50,
    window_days: int = 30,
    as_of: datetime | None = None,
    max_pages: int = 20,
) -> list[CreateRow]:
    coins = fetch_creator_coins(
        creator,
        limit=limit,
        client=client,
        window_days=window_days,
        max_pages=max_pages,
        as_of=as_of,
    )
    out: list[CreateRow] = []
    for c in coins:
        mint = c.get("mint")
        if not mint or mint == this_mint:
            continue
        cts = created_dt(c)
        if cts is None:
            continue
        out.append(
            CreateRow(
                mint=str(mint),
                creator_pubkey=str(c.get("creator") or creator),
                create_ts=cts,
                token_name=c.get("name"),
                token_symbol=c.get("symbol"),
            )
        )
    return out


def _coin_complete_flag(s: MintSighting) -> bool:
    raw = s.raw or {}
    nested = raw.get("raw_coin") if isinstance(raw.get("raw_coin"), dict) else raw
    return bool(nested.get("complete") is True or raw.get("complete") is True)


def parse_pump_frontend_trades(
    rows: list[dict[str, Any]],
    *,
    mint: str,
    t0: datetime,
    sol_usd: float = 0.0,
) -> list[TradeRow]:
    """Map Pump frontend trade JSON → TradeRow ≤T0.

    Supports:
    - Legacy flat rows (``timestamp`` / ``is_buy`` / ``amount_usd`` / ``sol_amount``)
    - 2026-10 indexed route (``blockTimeMs``, ``side``, ``valueUsd``, ``valueNative``,
      nested ``trader.address``, ``baseAmount``/``quoteAmount`` ``{raw,decimals}``)
    """
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)

    def _num(v: Any) -> float | None:
        if v is None:
            return None
        if isinstance(v, dict):
            # {raw, decimals} amount object
            raw, dec = v.get("raw"), v.get("decimals")
            try:
                if raw is None:
                    return None
                d = int(dec) if dec is not None else 0
                return float(raw) / (10 ** d if d >= 0 else 1)
            except (TypeError, ValueError, OverflowError):
                return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _ts(row: dict[str, Any]) -> datetime | None:
        ts_raw = (
            row.get("blockTimeMs")
            or row.get("timestamp")
            or row.get("block_time")
            or row.get("blockTime")
            or row.get("created_timestamp")
            or row.get("slot_time")
        )
        if ts_raw is None:
            return None
        try:
            if isinstance(ts_raw, (int, float)):
                v = float(ts_raw)
                if v >= 1e12:
                    v /= 1000.0
                return datetime.fromtimestamp(v, tz=timezone.utc)
            ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except (TypeError, ValueError, OSError):
            return None

    def _side(row: dict[str, Any]) -> str | None:
        side_raw = row.get("side")
        if side_raw is None:
            side_raw = row.get("type") if row.get("type") is not None else row.get("is_buy")
        if isinstance(side_raw, bool):
            return "buy" if side_raw else "sell"
        s = str(side_raw or "").lower()
        if s in ("buy", "true", "1"):
            return "buy"
        if s in ("sell", "false", "0"):
            return "sell"
        if row.get("is_buy") is True:
            return "buy"
        if row.get("is_buy") is False:
            return "sell"
        return None

    def _trader(row: dict[str, Any]) -> str | None:
        trader = (
            row.get("user")
            or row.get("trader_id")
            or row.get("wallet")
            or row.get("signer")
        )
        if trader is None:
            trader = row.get("trader")
        if isinstance(trader, dict):
            trader = trader.get("address") or trader.get("pubkey") or trader.get("id")
        return str(trader) if trader else None

    out: list[TradeRow] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ts = _ts(row)
        if ts is None or ts > t0:
            continue
        side = _side(row)
        if side is None:
            continue
        usd = _num(
            row.get("valueUsd")
            if row.get("valueUsd") is not None
            else (
                row.get("amount_usd")
                or row.get("usd_amount")
                or row.get("amountInUSD")
            )
        )
        sol = _num(
            row.get("valueNative")
            if row.get("valueNative") is not None
            else (
                row.get("sol_amount")
                or row.get("solAmount")
                or row.get("quote_amount")
                or row.get("quoteAmount")
            )
        )
        # Prefer SOL quote amount when quote is native SOL (lamports object)
        quote_id = None
        q = row.get("quote")
        if isinstance(q, dict):
            quote_id = q.get("id") or q.get("mint")
        if quote_id in (None, "11111111111111111111111111111111", "So11111111111111111111111111111111111111112"):
            qa = _num(row.get("quoteAmount"))
            if qa is not None and qa > 0:
                sol = qa if sol is None else sol
        tok = _num(
            row.get("baseAmount")
            if row.get("baseAmount") is not None
            else (row.get("token_amount") or row.get("base_amount") or row.get("tokenAmount"))
        )
        amount_usd = usd
        sol_amt = float(sol) if sol is not None else 0.0
        if amount_usd is None and sol_amt and sol_usd > 0:
            amount_usd = sol_amt * float(sol_usd)
        if amount_usd is None:
            amount_usd = 0.0
        tok_amt = float(tok) if tok is not None else 0.0
        out.append(
            TradeRow(
                mint=mint,
                ts=ts,
                side=side,
                amount_usd=float(amount_usd),
                trader_id=_trader(row),
                tok_amt=float(tok_amt),
                sol_amt=float(sol_amt),
                project="pumpdotfun",
            )
        )
    out.sort(key=lambda t: t.ts)
    return out



def buy_vol_60s_from_trades(trades: list[TradeRow], t0: datetime) -> tuple[float, int]:
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    lo = t0.timestamp() - float(WINDOW_S)
    hi = t0.timestamp()
    vol = 0.0
    n = 0
    for tr in trades:
        if tr.side != "buy":
            continue
        ts = tr.ts if tr.ts.tzinfo else tr.ts.replace(tzinfo=timezone.utc)
        u = ts.timestamp()
        if lo - 1e-9 <= u <= hi + 1e-9:
            vol += float(tr.amount_usd or 0.0)
            n += 1
    return float(vol), int(n)


def load_pump_trades_fixture(path: Path | None) -> dict[str, list[dict[str, Any]]]:
    if path is None or not path.is_file():
        return {}
    data = json.loads(path.read_text())
    if isinstance(data, dict) and "by_mint" in data:
        return {str(k): list(v or []) for k, v in (data.get("by_mint") or {}).items()}
    if isinstance(data, dict):
        # {mint: [trades]} or {meta, rows}
        out: dict[str, list[dict[str, Any]]] = {}
        for k, v in data.items():
            if k in ("meta", "gaps", "note"):
                continue
            if isinstance(v, list):
                out[str(k)] = list(v)
        return out
    return {}


def _try_fetch_pump_trades(
    mint: str,
    *,
    client: PumpFrontendClient | None,
    fixture: dict[str, list[dict[str, Any]]] | None,
    gaps: list[str],
) -> list[dict[str, Any]]:
    if fixture is not None and mint in fixture:
        return list(fixture[mint])
    if client is None:
        gaps.append("pump_trades_skipped:no_client")
        return []
    try:
        rows = fetch_trades_for_mint(mint, limit=200, client=client, max_pages=5)
        if isinstance(rows, list):
            if not rows:
                gaps.append("pump_trades_empty:0_rows")
            return rows
        gaps.append("pump_trades_unexpected_payload")
        return []
    except Exception as e:  # noqa: BLE001
        msg = str(e)[:160]
        gaps.append(PUMP_TRADES_API_GAP)
        gaps.append(f"pump_trades_fetch_failed:{msg}")
        return []


def enrich_pump_for_sightings(
    sightings: list[MintSighting],
    *,
    client: PumpFrontendClient | None = None,
    fetch_priors: bool = True,
    prior_limit: int = 50,
    fetch_trades: bool = True,
    trades_fixture_path: Path | None = None,
    sol_usd: float = 0.0,
    dry_run: bool = False,
) -> dict[str, PumpEnrichResult]:
    """Path A Pump enrich: scoreable from Pump MC+age; trades optional."""
    from datetime import timedelta

    owns = False
    # Priors resolve from local Dune store; only trades/diag need network
    need_net = fetch_trades and not dry_run and trades_fixture_path is None
    if need_net and client is None:
        client = PumpFrontendClient()
        owns = True
    fixture = load_pump_trades_fixture(trades_fixture_path) if trades_fixture_path else None
    if dry_run and fixture is None:
        fetch_trades = False  # no invented live trades in dry without fixture

    results: dict[str, PumpEnrichResult] = {}
    try:
        for s in sightings:
            gaps: list[str] = []
            t0 = _t0(s)
            create = _create_from_sighting(s)
            complete = _coin_complete_flag(s)
            # Frozen samples: create≪utcnow → rebase T0 to create+120s so age gate
            # matches live captura (young MC-band coins). Live never hits this.
            if dry_run and create is not None:
                age_live = (t0 - create.create_ts).total_seconds()
                if age_live > AGE_MAX_SCOREABLE_S:
                    t0 = create.create_ts + timedelta(seconds=120)
                    gaps.append("dry_sample_t0_rebased_to_create+120s")

            cap = find_t0_pump_mc_sighting(
                sighting_t0=t0,
                sighting_mc=float(s.mc_usd),
                create_ts=create.create_ts if create else None,
                complete=complete,
                sol_usd=float(sol_usd),
                sol_usd_source="pump_frontend",
            )
            t0_use = cap.t0
            mc_use = float(cap.mc_usd)

            # --- Q5b (Dune-cohort priors like helius_enrich; Pump fetch = diagnostic) ---
            priors: list[CreateRow] | None = []
            prior_src = None
            prior_overlay = None
            if create and not create.creator_pubkey:
                gaps.append("no creator on coin — priors skipped")
            if fetch_priors and create and create.creator_pubkey:
                try:
                    # Model features: exact → dune_cohort_recompute → dune_cohort_empty
                    # (Pump /coins?creator= NOT used for counts — allow_pump=False)
                    resolved = resolve_creator_priors(
                        mint=s.mint,
                        creator=create.creator_pubkey,
                        create_ts=create.create_ts,
                        pump_client=None,
                        allow_pump=False,
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
                    # Diagnostic only: Pump creator list when store miss/empty
                    # (does NOT overwrite model prior counts / source stamp)
                    if (
                        prior_src
                        in (
                            CREATOR_PRIOR_SOURCE_EMPTY,
                            CREATOR_PRIOR_SOURCE_NONE,
                        )
                        and client is not None
                        and not dry_run
                    ):
                        try:
                            pump_priors = _prior_creates_for_creator(
                                create.creator_pubkey,
                                this_mint=s.mint,
                                client=client,
                                limit=prior_limit,
                                window_days=30,
                                as_of=create.create_ts,
                            )
                            gaps.append(
                                f"pump_creator_diag_n={len(pump_priors)} "
                                "(gap_only; model uses dune_cohort_*)"
                            )
                        except Exception as e:  # noqa: BLE001
                            gaps.append(
                                f"pump_creator_diag_failed: {str(e)[:80]}"
                            )
                except Exception as e:  # noqa: BLE001
                    gaps.append(f"creator_priors_resolve_failed: {str(e)[:120]}")
                    priors = []
                    prior_src = CREATOR_PRIOR_SOURCE_NONE
                    prior_overlay = None
                    gaps.append("creator_priors_incomplete=none")
            elif fetch_priors:
                prior_src = CREATOR_PRIOR_SOURCE_NONE
                priors = [] if create else None
                gaps.append("creator_priors_incomplete=none")
            else:
                # Explicit skip (tests / dry without priors): leave none + incomplete
                prior_src = CREATOR_PRIOR_SOURCE_NONE
                priors = [] if create else None

            q5b = q5b_from_create(create, t0_use, prior_creates=priors)
            if prior_overlay:
                q5b.update(prior_overlay)
            q5b = prefer_sighting_meta_name_symbol(q5b, name=s.name, symbol=s.symbol)
            try:
                q5b = fill_meta_from_dune_store_exact(
                    q5b, load_creator_prior_index().exact_meta_for_mint(s.mint)
                )
            except Exception as e:  # noqa: BLE001
                gaps.append(f"meta_store_lookup_failed:{str(e)[:80]}")
            if q5b.get("meta_source"):
                gaps.append(f"meta_source={q5b['meta_source']}")

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

            # --- Trades (prefer Pump; fixture for dry) ---
            raw_trades: list[dict[str, Any]] = []
            if fetch_trades or fixture is not None:
                raw_trades = _try_fetch_pump_trades(
                    s.mint, client=client if fetch_trades else None, fixture=fixture, gaps=gaps
                )
            else:
                gaps.append("pump_trades_skipped:fetch_trades_false")

            trades = parse_pump_frontend_trades(
                raw_trades, mint=s.mint, t0=t0_use, sol_usd=float(sol_usd)
            )
            q5a = aggregate_q5a_for_mint(trades, t0_use) if trades else {c: None for c in Q5A_COLS}
            if trades:
                # empty-valid: also OK; aggregate handles empty
                buy60, buy_n = buy_vol_60s_from_trades(trades, t0_use)
                q5a_ok = True
            else:
                buy60, buy_n = None, None
                q5a_ok = False
                # Ensure Q5a cols explicitly null
                for col in Q5A_COLS:
                    q5a.setdefault(col, None)

            feats: dict[str, Any] = {}
            for col in Q5B_COLS:
                feats[col] = q5b.get(col)
            feats["creator_pubkey"] = q5b.get("creator_pubkey")
            feats["create_ts"] = q5b.get("create_ts")
            if q5b.get("meta_source"):
                feats["meta_source"] = q5b["meta_source"]
            for col in Q5A_COLS:
                feats[col] = q5a.get(col)

            # Curve / age_proxy: trade Q5a wins when pre-T0 trades present
            # (match Helius — no frontend coin overwrite of train recipe).
            # Coin overlay only gap-fills when trades empty. age_s stays
            # create→T0 for the scoreable gate; age_proxy_s stays t0−first_trade.
            raw = s.raw or {}
            nested = raw.get("raw_coin") if isinstance(raw.get("raw_coin"), dict) else raw
            if trades:
                feats["q5a_curve_age_source"] = "q5a_trades"
            else:
                prog = curve_progress_proxy(nested)
                net_sol = net_sol_curve_proxy(nested)
                if prog is not None and feats.get("progress_curve_proxy") is None:
                    feats["progress_curve_proxy"] = prog
                if net_sol is not None and feats.get("net_sol_curve") is None:
                    feats["net_sol_curve"] = net_sol
                    feats.setdefault("net_sol_total", net_sol)
                if feats.get("age_proxy_s") is None and q5b.get("age_s") is not None:
                    feats["age_proxy_s"] = q5b["age_s"]
                feats["q5a_curve_age_source"] = "pump_coin_gapfill"

            feats["buy_vol_usd_60s"] = float(buy60) if buy60 is not None else None
            feats["sol_usd_t0"] = float(sol_usd) if sol_usd else None
            feats["sol_usd_source"] = "pump_frontend"
            feats["capture_quality"] = cap.capture_quality
            feats["t0_refined"] = bool(cap.refined)
            feats["t0_definition"] = cap.definition or PUMP_MC_SIGHTING_DEF
            feats["mc_usd_t0_capture"] = mc_use
            feats["n_trades_pre_t0"] = len(trades)
            feats["age_from_create_ok"] = bool(age_info.ok)
            feats["age_from_create_reason"] = age_info.reason
            # Path A Pump: Helius trade-refine / no_trade_mc_path are NOT gates
            feats["helius_trade_refine_required"] = False
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

            scoreable = is_scoreable_pump_capture(cap, allow_med=True)
            reject = score_reject_reason_pump(cap, allow_med=True)
            if scoreable and not age_info.ok:
                # age anomaly still blocks (old re-band)
                scoreable = False
                reject = (reject + ";" if reject else "") + f"age:{age_info.reason}"
            if reject:
                gaps.append(f"score_reject:{reject}")
            # Never attach no_trade_mc_path — Pump MC path does not need trades
            feats["capture_scoreable"] = bool(scoreable)
            feats["score_reject_reason"] = reject

            q5b_ok = bool(q5b.get("q5b_complete")) and age_info.ok
            required = FEATURE_SETS["+q5b"]
            complete = (
                q5b_ok
                and buy60 is not None
                and all(
                    feats.get(c) is not None
                    for c in required
                    if c != "creator_prior_mints_all_in_window"
                )
            )

            src = (
                "dry_run.pump_fixture+pump_coin"
                if fixture is not None and client is None
                else "pump.frontend-api-v3.mc+coin(+trades)"
            )
            detail = (
                f"def={cap.definition} mc={mc_use:.1f} t0_refined={cap.refined} "
                f"scoreable={scoreable} n_trades_pre_t0={len(trades)} "
                f"buy60={'None' if buy60 is None else f'{buy60:.2f}'}"
            )
            results[s.mint] = PumpEnrichResult(
                mint=s.mint,
                features=feats,
                buy_vol_usd_60s=float(buy60) if buy60 is not None else None,
                buy_count_60s=int(buy_n) if buy_n is not None else None,
                q5a_ok=q5a_ok,
                q5b_ok=q5b_ok,
                complete_q5b=complete,
                source=src,
                detail=detail,
                gaps=gaps,
                n_trades_pre_t0=len(trades),
                t0_iso=t0_use.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
                mc_usd_t0=mc_use,
                capture_quality=cap.capture_quality,
                t0_refined=bool(cap.refined),
                capture_scoreable=bool(scoreable),
                score_reject=reject,
            )
        return results
    finally:
        if owns and client is not None:
            client.close()


# Back-compat alias used by helius_enrich import
__all__ = [
    "PumpEnrichResult",
    "enrich_pump_for_sightings",
    "parse_pump_frontend_trades",
    "buy_vol_60s_from_trades",
    "PUMP_TRADES_API_GAP",
    "_create_from_sighting",
]
