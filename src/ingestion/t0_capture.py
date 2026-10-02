"""Exact T0 capture C1–C6 (definicion-captura-v0.md) — SolDatos shared helper.

No dependency on ``paper_live``. Callers pass trade legs with ``.ts``, ``.side``,
``.sol_amt`` (Protocol). Prefer ``sol_usd`` from ``sol_usd_oracle.fetch_sol_usd_asof(t*)``.

paper_live should re-export / delegate to this module (BOSS owns paper_live wiring).
See ``cycle0/live-t0-capture-exact.md`` and ``cycle0/live-parity-fixes-soldatos-20261001.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence, runtime_checkable

from capture.math import market_cap_usd
from ingestion.pump_constants import (
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    MC_HI_USD,
    MC_LO_USD,
    TOKEN_TOTAL_SUPPLY,
    TRADEABLE_N_S,
)


@runtime_checkable
class TradeLeg(Protocol):
    """Minimal trade shape for MC path (buy/sell SOL legs)."""

    ts: datetime
    side: str  # "buy" | "sell"
    sol_amt: float


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class CaptureT0:
    t0: datetime
    mc_usd: float
    capture_quality: str  # HIGH | MED | LOW | REJECT
    sol_usd: float
    sol_usd_source: str
    n_trades_at_t0_window: int
    tradeable_s: float
    definition: str = "c1_c6_v0.3"
    refined: bool = False
    detail: str = ""


def _mc_at_reserves(vs: int, vt: int, sol_usd: float) -> float:
    if vt <= 0 or vs <= 0:
        return 0.0
    return float(
        market_cap_usd(
            virtual_sol_reserves=vs,
            virtual_token_reserves=vt,
            token_total_supply=TOKEN_TOTAL_SUPPLY,
            sol_usd=sol_usd,
        )
    )


def evolve_curve_mc_series(
    trades: Sequence[TradeLeg],
    *,
    sol_usd: float,
    vs0: int = INITIAL_VIRTUAL_SOL_RESERVES,
    vt0: int = INITIAL_VIRTUAL_TOKEN_RESERVES,
) -> list[tuple[datetime, float, float, str]]:
    """Return [(ts, mc_usd, net_sol_curve, side), ...] after each trade (chronological)."""
    vs = int(vs0)
    vt = int(vt0)
    k = vs * vt
    net_sol = 0.0
    out: list[tuple[datetime, float, float, str]] = []
    for tr in sorted(trades, key=lambda t: _aware(t.ts)):
        dsol = float(tr.sol_amt or 0.0)
        if dsol <= 0:
            continue
        d_lamports = int(round(dsol * 1_000_000_000))
        if d_lamports <= 0:
            continue
        if tr.side == "buy":
            vs_new = vs + d_lamports
            if vs_new <= 0:
                continue
            vt_new = k // vs_new if vs_new else vt
            vs, vt = vs_new, max(1, vt_new)
            k = vs * vt
            net_sol += dsol
        elif tr.side == "sell":
            if d_lamports >= vs:
                continue
            vs_new = vs - d_lamports
            if vs_new <= 0:
                continue
            vt_new = k // vs_new if vs_new else vt
            vs, vt = vs_new, max(1, vt_new)
            k = vs * vt
            net_sol -= dsol
        else:
            continue
        mc = _mc_at_reserves(vs, vt, sol_usd)
        out.append((_aware(tr.ts), mc, net_sol, tr.side))
    return out


def _tradeable_ok(
    t_star: datetime,
    *,
    create_ts: datetime | None,
    first_trade_ts: datetime | None,
    n_s: float = TRADEABLE_N_S,
) -> tuple[bool, float]:
    t_star = _aware(t_star)
    age_create = None
    if create_ts is not None:
        age_create = (t_star - _aware(create_ts)).total_seconds()
        if age_create >= n_s:
            return True, float(age_create)
    if first_trade_ts is not None:
        lead = (t_star - _aware(first_trade_ts)).total_seconds()
        if lead >= n_s:
            return True, float(age_create if age_create is not None else lead)
    return False, float(age_create if age_create is not None else 0.0)


def _trades_in_window(
    trades: Sequence[TradeLeg],
    t_star: datetime,
    *,
    n_s: float = TRADEABLE_N_S,
) -> int:
    t_star = _aware(t_star)
    lo = t_star - timedelta(seconds=n_s)
    n = 0
    for tr in trades:
        ts = _aware(tr.ts)
        if lo <= ts <= t_star:
            n += 1
    return n


def _quality_for_source(sol_usd_source: str) -> str:
    src = (sol_usd_source or "").lower()
    if src in ("pyth", "pyth_asof"):
        return "HIGH"
    if src in ("jupiter", "coingecko", "coingecko_asof", "explicit"):
        return "MED"
    return "MED"


def find_t0_c1_c6(
    trades: Sequence[TradeLeg],
    *,
    sighting_t0: datetime,
    sighting_mc: float,
    sol_usd: float,
    sol_usd_source: str = "pyth",
    create_ts: datetime | None = None,
    complete_false: bool = True,
    mc_lo: float = MC_LO_USD,
    mc_hi: float = MC_HI_USD,
    n_s: float = TRADEABLE_N_S,
) -> CaptureT0:
    """First chronological t* satisfying C2–C5; else provisional first-sight LOW.

    C1 assumed by caller (Pump bonding-curve mint). C6 = journal idempotency (caller).
    """
    sighting_t0 = _aware(sighting_t0)
    if not complete_false:
        return CaptureT0(
            t0=sighting_t0,
            mc_usd=float(sighting_mc),
            capture_quality="REJECT",
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=0,
            tradeable_s=0.0,
            refined=False,
            detail="complete=true at sighting",
        )

    series = evolve_curve_mc_series(trades, sol_usd=sol_usd)
    first_trade_ts = series[0][0] if series else None

    for ts, mc, _net, _side in series:
        if not (mc_lo <= mc <= mc_hi):
            continue
        ok_tradeable, tradeable_s = _tradeable_ok(
            ts, create_ts=create_ts, first_trade_ts=first_trade_ts, n_s=n_s
        )
        if not ok_tradeable:
            continue
        n_win = _trades_in_window(trades, ts, n_s=n_s)
        if n_win < 1:
            continue
        quality = _quality_for_source(sol_usd_source)
        if create_ts is not None and first_trade_ts is not None:
            gap = (_aware(first_trade_ts) - _aware(create_ts)).total_seconds()
            if gap > 3600:
                quality = "LOW"
        return CaptureT0(
            t0=ts,
            mc_usd=float(mc),
            capture_quality=quality,
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=n_win,
            tradeable_s=float(tradeable_s),
            refined=True,
            detail=f"first_band_cross mc={mc:.1f}",
        )

    n_win = _trades_in_window(trades, sighting_t0, n_s=n_s)
    ok_t, tradeable_s = _tradeable_ok(
        sighting_t0, create_ts=create_ts, first_trade_ts=first_trade_ts, n_s=n_s
    )
    detail = "first_sight_provisional"
    quality = "LOW"
    if not series:
        detail += ";no_trade_mc_path"
    elif not ok_t:
        detail += ";c4_tradeable_fail"
    elif n_win < 1:
        detail += ";c5_no_trade_in_window"
    else:
        detail += ";band_cross_not_in_history"
        if mc_lo <= float(sighting_mc) <= mc_hi:
            detail += ";c4_c5_ok_at_sighting"
            quality = _quality_for_source(sol_usd_source)
            if quality == "HIGH" and not str(sol_usd_source).startswith("pyth"):
                quality = "MED"
    return CaptureT0(
        t0=sighting_t0,
        mc_usd=float(sighting_mc),
        capture_quality=quality,
        sol_usd=float(sol_usd),
        sol_usd_source=sol_usd_source,
        n_trades_at_t0_window=n_win,
        tradeable_s=float(tradeable_s),
        refined=False,
        detail=detail,
    )


@runtime_checkable
class TradeLegWithTok(TradeLeg, Protocol):
    """TradeLeg + tok_amt/amount_usd for Dune Q3 trade-implied MC."""

    tok_amt: float
    amount_usd: float


def trade_implied_mc_usd(amount_usd: float, tok_amt: float) -> float:
    """Dune Q3: mc_usd = (amount_usd / tok_amt) * 1e9."""
    if tok_amt is None or amount_usd is None:
        return 0.0
    try:
        ta = float(tok_amt)
        ua = float(amount_usd)
    except (TypeError, ValueError):
        return 0.0
    if ta <= 0 or ua <= 0:
        return 0.0
    return (ua / ta) * 1e9


def find_t0_dune_q3(
    trades: Sequence[TradeLegWithTok],
    *,
    sighting_t0: datetime | None = None,
    sol_usd: float,
    sol_usd_source: str = "pyth",
    mc_lo: float = MC_LO_USD,
    mc_hi: float = MC_HI_USD,
) -> CaptureT0:
    """Train-parity T0: first chronological trade with trade-implied MC ∈ [8k,20k].

    Matches ``cycle0/dune-q3-mc-at-t0.sql`` (NOT reserve-path C1–C6).
    Use this when scoring against HistGB trained on Dune Q3 labels / features.
    Product captura HIGH still requires ``find_t0_c1_c6`` + Pyth.
    """
    ordered = sorted(trades, key=lambda t: _aware(t.ts))
    for tr in ordered:
        mc = trade_implied_mc_usd(
            float(getattr(tr, "amount_usd", 0) or 0),
            float(getattr(tr, "tok_amt", 0) or 0),
        )
        if not (mc_lo <= mc <= mc_hi):
            continue
        ts = _aware(tr.ts)
        quality = _quality_for_source(sol_usd_source)
        return CaptureT0(
            t0=ts,
            mc_usd=float(mc),
            capture_quality=quality,
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=1,
            tradeable_s=0.0,
            definition="dune_q3_first_mc_band",
            refined=True,
            detail=f"dune_q3_first_band mc={mc:.1f}",
        )
    # Fallback: sighting or last resort
    t0 = _aware(sighting_t0) if sighting_t0 is not None else (
        _aware(ordered[-1].ts) if ordered else datetime.now(timezone.utc)
    )
    return CaptureT0(
        t0=t0,
        mc_usd=0.0,
        capture_quality="LOW",
        sol_usd=float(sol_usd),
        sol_usd_source=sol_usd_source,
        n_trades_at_t0_window=0,
        tradeable_s=0.0,
        definition="dune_q3_first_mc_band",
        refined=False,
        detail="dune_q3_no_band_trade",
    )


def find_t0_c1_c6_train_aligned(
    trades: Sequence[TradeLeg],
    *,
    sighting_t0: datetime,
    sighting_mc: float,
    sol_usd: float,
    sol_usd_source: str = "pyth",
    create_ts: datetime | None = None,
    complete_false: bool = True,
    mc_lo: float = MC_LO_USD,
    mc_hi: float = MC_HI_USD,
    n_s: float = TRADEABLE_N_S,
) -> CaptureT0:
    """C1–C6 with train-aligned C4 for age≈0 snipers.

    Train Q3 labels include age_s=0 (create≈T0) which fail product C4 (tradeable≥30s).
    When create→first_band span < n_s, treat C4 as satisfied with tradeable_s=age
    so refine can lock the same first-band timestamp the cohort uses.
    Prefer ``find_t0_dune_q3`` when trades carry tok_amt/amount_usd for exact Q3 MC.
    """
    sighting_t0 = _aware(sighting_t0)
    if not complete_false:
        return find_t0_c1_c6(
            trades,
            sighting_t0=sighting_t0,
            sighting_mc=sighting_mc,
            sol_usd=sol_usd,
            sol_usd_source=sol_usd_source,
            create_ts=create_ts,
            complete_false=False,
            mc_lo=mc_lo,
            mc_hi=mc_hi,
            n_s=n_s,
        )

    series = evolve_curve_mc_series(trades, sol_usd=sol_usd)
    first_trade_ts = series[0][0] if series else None

    for ts, mc, _net, _side in series:
        if not (mc_lo <= mc <= mc_hi):
            continue
        ok_tradeable, tradeable_s = _tradeable_ok(
            ts, create_ts=create_ts, first_trade_ts=first_trade_ts, n_s=n_s
        )
        # Train-aligned: allow band cross before N seconds when create is recent
        if not ok_tradeable and create_ts is not None:
            age_c = (ts - _aware(create_ts)).total_seconds()
            if 0 <= age_c < n_s:
                ok_tradeable = True
                tradeable_s = float(age_c)
        if not ok_tradeable:
            continue
        n_win = _trades_in_window(trades, ts, n_s=n_s)
        if n_win < 1:
            continue
        quality = _quality_for_source(sol_usd_source)
        return CaptureT0(
            t0=ts,
            mc_usd=float(mc),
            capture_quality=quality,
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=n_win,
            tradeable_s=float(tradeable_s),
            definition="c1_c6_v0.3_train_aligned_c4",
            refined=True,
            detail=f"train_aligned_band_cross mc={mc:.1f}",
        )

    # Fallback to strict product path provisional
    return find_t0_c1_c6(
        trades,
        sighting_t0=sighting_t0,
        sighting_mc=sighting_mc,
        sol_usd=sol_usd,
        sol_usd_source=sol_usd_source,
        create_ts=create_ts,
        complete_false=True,
        mc_lo=mc_lo,
        mc_hi=mc_hi,
        n_s=n_s,
    )


def is_scoreable_capture(
    cap: CaptureT0,
    *,
    require_pyth: bool = True,
    allow_med: bool = False,
) -> bool:
    """C1–C6 scoring gate: refuse LOW / unrefined (and non-Pyth when required).

    Product: only refined captures with quality HIGH (Pyth) enter HistGB X.
    If allow_med=True, MED (CoinGecko/Jupiter) may pass — default False per Sinck
    force-Pyth policy.
    """
    if not cap.refined:
        return False
    q = (cap.capture_quality or "").upper()
    if q == "REJECT" or q == "LOW":
        return False
    if q == "MED" and not allow_med:
        return False
    if q not in ("HIGH", "MED"):
        return False
    if require_pyth:
        src = (cap.sol_usd_source or "").lower()
        if src not in ("pyth", "pyth_asof"):
            return False
    return True


def score_reject_reason(
    cap: CaptureT0,
    *,
    require_pyth: bool = True,
    allow_med: bool = False,
) -> str | None:
    """None if scoreable; else short machine reason for journal gaps."""
    if is_scoreable_capture(cap, require_pyth=require_pyth, allow_med=allow_med):
        return None
    if not cap.refined:
        return f"t0_unrefined:{cap.detail or 'provisional'}"
    q = (cap.capture_quality or "").upper()
    if q in ("LOW", "REJECT"):
        return f"capture_quality_{q.lower()}"
    if q == "MED" and not allow_med:
        return "capture_quality_med_pyth_required"
    if require_pyth:
        src = (cap.sol_usd_source or "").lower()
        if src not in ("pyth", "pyth_asof"):
            return f"sol_usd_not_pyth:{cap.sol_usd_source}"
    return "not_scoreable"


def require_scoreable_capture(
    cap: CaptureT0,
    *,
    require_pyth: bool = True,
    allow_med: bool = False,
) -> CaptureT0:
    """Return cap if scoreable else raise ``ValueError`` with reason."""
    reason = score_reject_reason(cap, require_pyth=require_pyth, allow_med=allow_med)
    if reason:
        raise ValueError(f"capture_not_scoreable:{reason}")
    return cap



# --- Path A live (Sinck 2026-10-02): Pump MC band sighting — no Helius trade series ---

PUMP_MC_SIGHTING_DEF = "pump_mc_band_sighting_v1"


def find_t0_pump_mc_sighting(
    *,
    sighting_t0: datetime,
    sighting_mc: float,
    create_ts: datetime | None = None,
    complete: bool = False,
    sol_usd: float = 0.0,
    sol_usd_source: str = "pump_frontend",
    mc_lo: float = MC_LO_USD,
    mc_hi: float = MC_HI_USD,
    max_age_s: float = 86_400.0,
) -> CaptureT0:
    """T0 = Pump frontend first sighting with MC ∈ [mc_lo, mc_hi].

    Does **not** require a Helius/trade MC path. Tradeable window uses create→T0
    age (C4 soft): age ≥ TRADEABLE_N_S preferred; age in [0, max_age_s] still
    scoreable for train-aligned snipers (age≈0).
    """
    sighting_t0 = _aware(sighting_t0)
    mc = float(sighting_mc)
    if complete:
        return CaptureT0(
            t0=sighting_t0,
            mc_usd=mc,
            capture_quality="REJECT",
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=0,
            tradeable_s=0.0,
            definition=PUMP_MC_SIGHTING_DEF,
            refined=False,
            detail="complete=true_graduated",
        )
    if not (mc_lo <= mc <= mc_hi):
        return CaptureT0(
            t0=sighting_t0,
            mc_usd=mc,
            capture_quality="REJECT",
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=0,
            tradeable_s=0.0,
            definition=PUMP_MC_SIGHTING_DEF,
            refined=False,
            detail=f"mc_out_of_band:{mc:.1f}",
        )
    tradeable_s = 0.0
    if create_ts is not None:
        age = (sighting_t0 - _aware(create_ts)).total_seconds()
        if age < 0:
            return CaptureT0(
                t0=sighting_t0,
                mc_usd=mc,
                capture_quality="REJECT",
                sol_usd=float(sol_usd),
                sol_usd_source=sol_usd_source,
                n_trades_at_t0_window=0,
                tradeable_s=float(age),
                definition=PUMP_MC_SIGHTING_DEF,
                refined=False,
                detail="create_after_t0",
            )
        if age > float(max_age_s):
            return CaptureT0(
                t0=sighting_t0,
                mc_usd=mc,
                capture_quality="LOW",
                sol_usd=float(sol_usd),
                sol_usd_source=sol_usd_source,
                n_trades_at_t0_window=0,
                tradeable_s=float(age),
                definition=PUMP_MC_SIGHTING_DEF,
                refined=False,
                detail=f"age_gt_max_{int(max_age_s)}s",
            )
        tradeable_s = float(age)
    else:
        return CaptureT0(
            t0=sighting_t0,
            mc_usd=mc,
            capture_quality="LOW",
            sol_usd=float(sol_usd),
            sol_usd_source=sol_usd_source,
            n_trades_at_t0_window=0,
            tradeable_s=0.0,
            definition=PUMP_MC_SIGHTING_DEF,
            refined=False,
            detail="missing_create_ts",
        )
    quality = "MED"  # Pump MC snapshot (not Pyth-backed trade MC)
    detail = f"pump_mc_band mc={mc:.1f} age_s={tradeable_s:.1f}"
    return CaptureT0(
        t0=sighting_t0,
        mc_usd=mc,
        capture_quality=quality,
        sol_usd=float(sol_usd),
        sol_usd_source=sol_usd_source,
        n_trades_at_t0_window=0,
        tradeable_s=tradeable_s,
        definition=PUMP_MC_SIGHTING_DEF,
        refined=True,
        detail=detail,
    )


def is_scoreable_pump_capture(
    cap: CaptureT0,
    *,
    allow_med: bool = True,
) -> bool:
    """Path A Pump gate: refined Pump MC sighting; MED OK (no Helius/Pyth required)."""
    if (cap.definition or "") != PUMP_MC_SIGHTING_DEF and not str(cap.definition or "").startswith(
        "pump_mc_band"
    ):
        # Fall back to product gate for non-Pump captures
        return is_scoreable_capture(cap, require_pyth=False, allow_med=allow_med)
    if not cap.refined:
        return False
    q = (cap.capture_quality or "").upper()
    if q in ("REJECT", "LOW"):
        return False
    if q == "MED" and not allow_med:
        return False
    if q not in ("HIGH", "MED"):
        return False
    if not (MC_LO_USD <= float(cap.mc_usd) <= MC_HI_USD):
        return False
    return True


def score_reject_reason_pump(cap: CaptureT0, *, allow_med: bool = True) -> str | None:
    if is_scoreable_pump_capture(cap, allow_med=allow_med):
        return None
    if not cap.refined:
        return f"t0_unrefined:{cap.detail or 'provisional'}"
    q = (cap.capture_quality or "").upper()
    if q in ("LOW", "REJECT"):
        return f"capture_quality_{q.lower()}:{cap.detail or ''}"
    if q == "MED" and not allow_med:
        return "capture_quality_med_not_allowed"
    if not (MC_LO_USD <= float(cap.mc_usd) <= MC_HI_USD):
        return f"mc_out_of_band:{cap.mc_usd}"
    return "not_scoreable_pump"
