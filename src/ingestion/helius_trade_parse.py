"""Helius Enhanced → trade legs with Dune Q4/Q5a parity filters (SolDatos).

Train (cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql, dune-q4-flow-pre-t0.sql):
  - project IN ('pumpdotfun','pumpswap')
  - WSOL pair only
  - amount_usd >= 1
  - BUY  = token_sold_mint = WSOL (WSOL sold → mint bought)
  - SELL = token_bought_mint = WSOL (mint sold → WSOL bought)
  - trader_id from Dune; live uses Enhanced feePayer / per-leg trader
  - amount_usd = dex_solana.trades.amount_usd (train)
  - live amount_usd = sol_amt × sol_usd_asof_t0  (product oracle; see sol_usd_oracle)

Live parse:
  - Prefer WSOL token transfer amounts for sol_amt (Pump AMM / pumpswap).
  - Fall back to bonding-curve nativeBalanceChange (pre-grad Pump CREATE/SWAP).
  - Emit one ParsedTrade per mint↔WSOL swap leg (multi-trader + multi-hop
    in one Enhanced tx), matching Dune dex_solana.trades row granularity.
  - Pre-grad BC: one buy per BC→trader mint receipt; SOL from trader→BC
    nativeTransfers (bundled multi-buyer Pump SWAP parity).
  - Skip CREATE_POOL (liquidity migrate, not a dex trade).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ingestion.pump_constants import PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID
from ingestion.sol_usd_oracle import DEFAULT_SOL_USD_REF, amount_usd_dune_compatible

WSOL_MINT = "So11111111111111111111111111111111111111112"
MIN_AMOUNT_USD_DUNE = 1.0

# Helius types that are liquidity / infrastructure, not dex_solana.trades rows
_SKIP_TYPES = frozenset(
    {
        "CREATE_POOL",
        "ADD_LIQUIDITY",
        "REMOVE_LIQUIDITY",
        "ASSOCIATED_TOKEN_ACCOUNT_CREATE",
        "TOKEN_MINT",
    }
)

_PUMP_SOURCES = frozenset({"PUMP_FUN", "PUMPFUN", "PUMP"})
_PUMPSWAP_SOURCES = frozenset({"PUMP_SWAP", "PUMPSWAP", "PUMP_AMM"})


@dataclass
class ParsedTrade:
    """Minimal trade row (TradeLeg + Q5a fields). paper_live maps to TradeRow."""

    mint: str
    ts: datetime
    side: str  # buy | sell
    amount_usd: float
    trader_id: str
    tok_amt: float
    sol_amt: float
    project: str  # pumpdotfun | pumpswap


def project_from_helius_source(source: str | None) -> str:
    src = (source or "").upper()
    if src in _PUMP_SOURCES or "PUMP_FUN" in src or src == "PUMP":
        return "pumpdotfun"
    if src in _PUMPSWAP_SOURCES or "PUMPSWAP" in src or "PUMP_AMM" in src:
        return "pumpswap"
    return "other"


def _sol_amt_from_tx(
    tx: dict[str, Any],
    *,
    bonding_curve: str | None,
    fee_payer: str,
    side: str,
) -> float:
    """SOL UI amount (absolute). Prefer WSOL, then per-user→BC native, then BC total."""
    wsol = _wsol_amt_for_user(tx, user=fee_payer, side=side)
    if wsol > 0:
        return wsol

    if bonding_curve:
        nts = tx.get("nativeTransfers") or []
        # Per-trader native into/out of BC (multi-buyer bundled Pump CREATE/SWAP)
        if side == "buy":
            into_user = sum(
                int(n.get("amount") or 0)
                for n in nts
                if n.get("toUserAccount") == bonding_curve
                and n.get("fromUserAccount") == fee_payer
            )
            if into_user > 0:
                return into_user / 1e9
        else:
            out_user = sum(
                int(n.get("amount") or 0)
                for n in nts
                if n.get("fromUserAccount") == bonding_curve
                and n.get("toUserAccount") == fee_payer
            )
            if out_user > 0:
                return out_user / 1e9
        for ad in tx.get("accountData") or []:
            if ad.get("account") != bonding_curve:
                continue
            try:
                ch = int(ad.get("nativeBalanceChange") or 0)
            except (TypeError, ValueError):
                ch = 0
            if ch != 0:
                return abs(ch) / 1e9
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
    # Ignore ATA-rent-sized dust (< 0.01 SOL) when scanning native fallbacks —
    # pumpswap wraps leave ~0.0015 SOL ATA creates that are not trade size.
    min_lamports = 10_000_000  # 0.01 SOL
    if side == "buy":
        amounts = sorted(
            (
                int(n.get("amount") or 0)
                for n in nts
                if n.get("fromUserAccount") == fee_payer
                and int(n.get("amount") or 0) >= min_lamports
            ),
            reverse=True,
        )
        if amounts:
            return amounts[0] / 1e9
    else:
        amounts = sorted(
            (
                int(n.get("amount") or 0)
                for n in nts
                if n.get("toUserAccount") == fee_payer
                and int(n.get("amount") or 0) >= min_lamports
            ),
            reverse=True,
        )
        if amounts:
            return amounts[0] / 1e9
    return 0.0


def _wsol_amt_for_user(tx: dict[str, Any], *, user: str, side: str) -> float:
    """Sum WSOL UI amount leaving (buy) or entering (sell) ``user``."""
    total = 0.0
    for t in tx.get("tokenTransfers") or []:
        if str(t.get("mint") or "") != WSOL_MINT:
            continue
        try:
            amt = float(t.get("tokenAmount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        if side == "buy" and t.get("fromUserAccount") == user:
            total += amt
        elif side == "sell" and t.get("toUserAccount") == user:
            total += amt
    return total


def _involves_wsol(tx: dict[str, Any]) -> bool:
    """Dune WSOL-pair filter: require WSOL token transfer or native SOL move."""
    for t in tx.get("tokenTransfers") or []:
        if str(t.get("mint") or "") == WSOL_MINT:
            return True
    if tx.get("nativeTransfers"):
        return True
    for ad in tx.get("accountData") or []:
        try:
            if int(ad.get("nativeBalanceChange") or 0) != 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _mint_swap_legs(
    tx: dict[str, Any],
    *,
    mint: str,
) -> list[tuple[str, str, float, float]]:
    """Extract (side, trader, tok_amt, sol_amt) legs from mint↔WSOL transfer pairs.

    Dune ``dex_solana.trades`` is one row per swap instruction. Bundled Pump AMM
    txs often contain multiple mint receipts (possibly multi-trader). Pair each
    mint transfer with the matching WSOL pool leg in appearance order.
    """
    transfers = list(tx.get("tokenTransfers") or [])
    # Pool vaults = accounts that send mint out (buys) or receive mint (sells)
    legs: list[tuple[str, str, float, float]] = []

    # Collect ordered mint buys (pool → trader) and sells (trader → pool)
    mint_buys: list[tuple[str, str, float]] = []  # (trader, pool, tok)
    mint_sells: list[tuple[str, str, float]] = []
    for t in transfers:
        if str(t.get("mint") or "") != mint:
            continue
        try:
            amt = float(t.get("tokenAmount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt <= 0:
            continue
        frm = t.get("fromUserAccount")
        to = t.get("toUserAccount")
        if to and frm:
            mint_buys.append((str(to), str(frm), amt))
            mint_sells.append((str(frm), str(to), amt))

    # WSOL from trader → pool (buy spend); WSOL pool → trader (sell proceeds)
    wsol_buy_spend: dict[str, list[float]] = {}
    wsol_sell_recv: dict[str, list[float]] = {}
    for t in transfers:
        if str(t.get("mint") or "") != WSOL_MINT:
            continue
        try:
            amt = float(t.get("tokenAmount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt <= 0:
            continue
        frm = t.get("fromUserAccount")
        to = t.get("toUserAccount")
        if not frm or not to:
            continue
        # Buy: trader sends WSOL to an account that also sent mint to someone
        # (pool vault). Match by pool set from mint_buys.
        pools_buy = {p for _, p, _ in mint_buys}
        pools_sell = {p for _, p, _ in mint_sells}
        if to in pools_buy and frm not in pools_buy:
            wsol_buy_spend.setdefault(str(frm), []).append(amt)
        if frm in pools_sell and to not in pools_sell:
            wsol_sell_recv.setdefault(str(to), []).append(amt)

    # Pair mint buys with WSOL spends per trader (FIFO)
    buy_idx: dict[str, int] = {}
    for trader, _pool, tok in mint_buys:
        # Skip pool-as-trader (liquidity side of CREATE_POOL already skipped by type)
        if trader in {p for _, p, _ in mint_buys}:
            continue
        spends = wsol_buy_spend.get(trader) or []
        i = buy_idx.get(trader, 0)
        sol = spends[i] if i < len(spends) else 0.0
        buy_idx[trader] = i + 1
        legs.append(("buy", trader, tok, sol))

    sell_idx: dict[str, int] = {}
    for trader, _pool, tok in mint_sells:
        if trader in {p for _, p, _ in mint_sells}:
            continue
        recvs = wsol_sell_recv.get(trader) or []
        i = sell_idx.get(trader, 0)
        sol = recvs[i] if i < len(recvs) else 0.0
        sell_idx[trader] = i + 1
        # Only emit sell if this trader actually sold (net): avoid double-counting
        # the pool→trader mint path inverted. mint_sells lists every mint send;
        # a buy's pool send would appear as sell(pool→…). Filter: trader must
        # not be a known pool vault from mint_buys fromUser.
        pools = {p for _, p, _ in mint_buys}
        if trader in pools:
            continue
        legs.append(("sell", trader, tok, sol))

    return legs



def _bc_native_buy_legs(
    tx: dict[str, Any],
    *,
    mint: str,
    bonding_curve: str | None,
) -> list[tuple[str, float, float]]:
    """One (trader, tok_amt, sol_amt) per BC→trader mint receipt.

    Bundled Pump.fun SWAPs put multiple buyers in one Enhanced tx. Dune emits
    one ``dex_solana.trades`` row per buyer; live must match. SOL per buyer =
    nativeTransfers trader→bonding_curve (falls back to pro-rata BC delta).
    """
    if not bonding_curve:
        return []
    recipients: list[tuple[str, float]] = []
    for t in tx.get("tokenTransfers") or []:
        if str(t.get("mint") or "") != mint:
            continue
        if t.get("fromUserAccount") != bonding_curve:
            continue
        to = t.get("toUserAccount")
        if not to or to == bonding_curve:
            continue
        try:
            amt = float(t.get("tokenAmount") or 0.0)
        except (TypeError, ValueError):
            amt = 0.0
        if amt <= 0:
            continue
        recipients.append((str(to), amt))
    if not recipients:
        return []

    nts = tx.get("nativeTransfers") or []
    sol_by: dict[str, float] = {}
    for n in nts:
        if n.get("toUserAccount") != bonding_curve:
            continue
        frm = n.get("fromUserAccount")
        if not frm:
            continue
        try:
            lamports = int(n.get("amount") or 0)
        except (TypeError, ValueError):
            lamports = 0
        if lamports <= 0:
            continue
        sol_by[str(frm)] = sol_by.get(str(frm), 0.0) + lamports / 1e9

    if not sol_by:
        # Single-buyer CREATE often has accountData BC delta but empty NTs
        bc_total = 0.0
        for ad in tx.get("accountData") or []:
            if ad.get("account") != bonding_curve:
                continue
            try:
                ch = int(ad.get("nativeBalanceChange") or 0)
            except (TypeError, ValueError):
                ch = 0
            if ch > 0:
                bc_total = ch / 1e9
                break
        if bc_total <= 0:
            return []
        if len(recipients) == 1:
            return [(recipients[0][0], recipients[0][1], bc_total)]
        tok_sum = sum(t for _, t in recipients) or 1.0
        return [
            (tr, tok, bc_total * (tok / tok_sum)) for tr, tok in recipients
        ]

    out: list[tuple[str, float, float]] = []
    for tr, tok in recipients:
        sol = float(sol_by.get(tr) or 0.0)
        if sol <= 0:
            continue
        out.append((tr, tok, sol))
    return out


def parse_helius_enhanced_txs(
    txs: list[dict[str, Any]],
    *,
    mint: str,
    bonding_curve: str | None,
    sol_usd: float = DEFAULT_SOL_USD_REF,
    min_amount_usd: float = MIN_AMOUNT_USD_DUNE,
    t0: datetime | None = None,
    dune_project_only: bool = True,
) -> list[ParsedTrade]:
    """Parse Enhanced txs → ParsedTrade (≤T0 if ``t0`` given).

    Multi-leg: one row per mint↔WSOL swap leg (Dune buy_count granularity).
    Filters: min USD, project∈{pumpdotfun,pumpswap}, skip CREATE_POOL.
    """
    if t0 is not None and t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    sol_px = float(sol_usd) if sol_usd and sol_usd > 0 else float(DEFAULT_SOL_USD_REF)
    rows: list[ParsedTrade] = []
    for tx in txs:
        if tx.get("transactionError"):
            continue
        tx_type = str(tx.get("type") or "").upper()
        if tx_type in _SKIP_TYPES:
            continue
        ts_raw = tx.get("timestamp")
        if ts_raw is None:
            continue
        try:
            ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            continue
        if t0 is not None and ts > t0:
            continue

        project = project_from_helius_source(str(tx.get("source") or "") or None)
        if dune_project_only and project == "other":
            if tx_type != "SWAP":
                continue

        if not _involves_wsol(tx):
            continue

        fee = tx.get("feePayer")
        tt_mint = [
            t
            for t in (tx.get("tokenTransfers") or [])
            if str(t.get("mint") or "") == mint
        ]
        if not tt_mint:
            continue

        legs = _mint_swap_legs(tx, mint=mint)
        # Pre-grad Pump CREATE/SWAP: mint↔BC with native SOL (no WSOL SPL).
        # Multi-buyer bundled txs → one Dune row per recipient (not feePayer-only).
        if not legs or all(sol <= 0 for _side, _tr, _tok, sol in legs):
            bc_buys = _bc_native_buy_legs(
                tx, mint=mint, bonding_curve=bonding_curve
            )
            if bc_buys:
                for trader, tok_amt, sol_amt in bc_buys:
                    usd = amount_usd_dune_compatible(sol_amt, sol_px)
                    if min_amount_usd > 0 and usd < min_amount_usd:
                        continue
                    rows.append(
                        ParsedTrade(
                            mint=mint,
                            ts=ts,
                            side="buy",
                            amount_usd=float(usd),
                            trader_id=str(trader),
                            tok_amt=float(tok_amt),
                            sol_amt=float(sol_amt),
                            project=project if project != "other" else "pumpdotfun",
                        )
                    )
                continue
            # Last resort: feePayer net (single-buyer / missing NTs)
            if not fee:
                continue
            net_tok = 0.0
            for t in tt_mint:
                try:
                    amt = float(t.get("tokenAmount") or 0.0)
                except (TypeError, ValueError):
                    amt = 0.0
                if t.get("toUserAccount") == fee:
                    net_tok += amt
                if t.get("fromUserAccount") == fee:
                    net_tok -= amt
            if net_tok > 0:
                side, tok_amt = "buy", net_tok
            elif net_tok < 0:
                side, tok_amt = "sell", -net_tok
            else:
                continue
            sol_amt = _sol_amt_from_tx(
                tx, bonding_curve=bonding_curve, fee_payer=str(fee), side=side
            )
            if sol_amt <= 0:
                continue
            usd = amount_usd_dune_compatible(sol_amt, sol_px)
            if min_amount_usd > 0 and usd < min_amount_usd:
                continue
            rows.append(
                ParsedTrade(
                    mint=mint,
                    ts=ts,
                    side=side,
                    amount_usd=float(usd),
                    trader_id=str(fee),
                    tok_amt=float(tok_amt),
                    sol_amt=float(sol_amt),
                    project=project if project != "other" else "pumpdotfun",
                )
            )
            continue

        for side, trader, tok_amt, sol_amt in legs:
            if side == "sell":
                # Avoid double-counting: buys already emitted; only keep sells
                # where trader sent mint (true sell). _mint_swap_legs already
                # filters pool vaults; still require sol or BC fallback.
                pass
            if sol_amt <= 0:
                # BC / native fallback for this trader
                sol_amt = _sol_amt_from_tx(
                    tx,
                    bonding_curve=bonding_curve,
                    fee_payer=trader,
                    side=side,
                )
            if sol_amt <= 0:
                continue
            usd = amount_usd_dune_compatible(sol_amt, sol_px)
            if min_amount_usd > 0 and usd < min_amount_usd:
                continue
            rows.append(
                ParsedTrade(
                    mint=mint,
                    ts=ts,
                    side=side,
                    amount_usd=float(usd),
                    trader_id=str(trader),
                    tok_amt=float(tok_amt),
                    sol_amt=float(sol_amt),
                    project=project if project != "other" else "pumpdotfun",
                )
            )
    return rows


def trade_implied_mc_usd(amount_usd: float, tok_amt: float) -> float:
    """Dune Q3 MC: (amount_usd / tok_amt) * 1e9 (Pump supply convention)."""
    if tok_amt <= 0 or amount_usd <= 0:
        return 0.0
    return float(amount_usd / tok_amt) * 1e9


# Silence unused import lint for program ids (documented parity anchors)
_ = (PUMP_PROGRAM_ID, PUMPSWAP_PROGRAM_ID)
