"""Pure ≤T0 Q5a aggregation (parity with cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql).

Input trades: list of dicts with keys:
  mint, ts (datetime UTC), side ('buy'|'sell'), amount_usd, trader_id,
  tok_amt, sol_amt, project ('pumpdotfun'|'pumpswap'|other)

No look-ahead: caller must pass only trades with ts ≤ mint T0.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


CURVE_GRAD_SOL = 85.0


def _f(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


@dataclass
class TradeRow:
    mint: str
    ts: datetime
    side: str
    amount_usd: float
    trader_id: str
    tok_amt: float
    sol_amt: float
    project: str


def aggregate_q5a_for_mint(trades: list[TradeRow], t0: datetime) -> dict[str, float | None]:
    """Compute Q5A_COLS for one mint. Empty trades → zeros / null shares (enrich ok)."""
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    joined = [tr for tr in trades if tr.ts <= t0]
    if not joined:
        return _empty_q5a()

    first_trade_ts = min(tr.ts for tr in joined)
    age_proxy_s = (t0 - first_trade_ts).total_seconds()

    buy_count_30s = sell_count_30s = 0
    buy_vol_30s = sell_vol_30s = 0.0
    traders_30s: set[str] = set()
    buy_count_15m = sell_count_15m = 0
    buy_vol_15m = sell_vol_15m = 0.0
    traders_15m: set[str] = set()
    buyers: set[str] = set()
    sellers: set[str] = set()
    buy_count_total = sell_count_total = 0
    buy_vol_total = sell_vol_total = 0.0
    net_sol_total = 0.0
    net_sol_curve = 0.0
    migrated = 0
    max_buy_usd = 0.0
    max_buy_sol = 0.0

    buys: list[TradeRow] = []
    for tr in joined:
        secs_before = (t0 - tr.ts).total_seconds()
        if tr.project == "pumpswap":
            migrated = 1
        signed_sol = tr.sol_amt if tr.side == "buy" else -tr.sol_amt
        net_sol_total += signed_sol
        if tr.project == "pumpdotfun":
            net_sol_curve += signed_sol
        if tr.side == "buy":
            buys.append(tr)
            buyers.add(tr.trader_id)
            buy_count_total += 1
            buy_vol_total += tr.amount_usd
            if tr.amount_usd > max_buy_usd:
                max_buy_usd = tr.amount_usd
            if tr.sol_amt > max_buy_sol:
                max_buy_sol = tr.sol_amt
            if 0 <= secs_before <= 30:
                buy_count_30s += 1
                buy_vol_30s += tr.amount_usd
                traders_30s.add(tr.trader_id)
            if 0 <= secs_before <= 900:
                buy_count_15m += 1
                buy_vol_15m += tr.amount_usd
                traders_15m.add(tr.trader_id)
        elif tr.side == "sell":
            sellers.add(tr.trader_id)
            sell_count_total += 1
            sell_vol_total += tr.amount_usd
            if 0 <= secs_before <= 30:
                sell_count_30s += 1
                sell_vol_30s += tr.amount_usd
                traders_30s.add(tr.trader_id)
            if 0 <= secs_before <= 900:
                sell_count_15m += 1
                sell_vol_15m += tr.amount_usd
                traders_15m.add(tr.trader_id)

    # Sniper / first-N buys (order by time ASC, amount DESC)
    buys_sorted = sorted(buys, key=lambda b: (b.ts, -b.amount_usd))
    first5_buy_vol = sum(b.amount_usd for b in buys_sorted[:5])
    first10_buy_vol = sum(b.amount_usd for b in buys_sorted[:10])
    buy_vol_first_5s = 0.0
    buy_vol_first_10s = 0.0
    unique_buyers_first5: set[str] = set()
    unique_buyers_first_5s: set[str] = set()
    first_buy_usd = buys_sorted[0].amount_usd if buys_sorted else 0.0
    for i, b in enumerate(buys_sorted):
        secs_after = (b.ts - first_trade_ts).total_seconds()
        if i < 5:
            unique_buyers_first5.add(b.trader_id)
        if 0 <= secs_after <= 5:
            buy_vol_first_5s += b.amount_usd
            unique_buyers_first_5s.add(b.trader_id)
        if 0 <= secs_after <= 10:
            buy_vol_first_10s += b.amount_usd

    # Trader concentration
    buy_by_trader: dict[str, float] = defaultdict(float)
    net_tok: dict[str, float] = defaultdict(float)
    for tr in joined:
        if tr.side == "buy":
            buy_by_trader[tr.trader_id] += tr.amount_usd
            net_tok[tr.trader_id] += tr.tok_amt
        else:
            net_tok[tr.trader_id] -= tr.tok_amt

    buy_ranked = sorted(buy_by_trader.values(), reverse=True)
    sum_buyer = sum(buy_ranked)
    top1_b = buy_ranked[0] if buy_ranked else 0.0
    top5_b = sum(buy_ranked[:5])
    top10_b = sum(buy_ranked[:10])

    pos_holders = [(tid, nt) for tid, nt in net_tok.items() if nt > 0]
    pos_holders.sort(key=lambda x: -x[1])
    sum_pos = sum(nt for _, nt in pos_holders)
    top1_h = pos_holders[0][1] if pos_holders else 0.0
    top5_h = sum(nt for _, nt in pos_holders[:5])
    top10_h = sum(nt for _, nt in pos_holders[:10])

    def _share(num: float, den: float) -> float | None:
        if den <= 0:
            return None
        return num / den

    progress = None
    if True:
        progress = min(max(net_sol_curve / CURVE_GRAD_SOL, 0.0), 2.0)

    return {
        "age_proxy_s": float(age_proxy_s),
        "buy_count_15m": float(buy_count_15m),
        "buy_count_30s": float(buy_count_30s),
        "buy_count_total": float(buy_count_total),
        "buy_vol_first_10s": float(buy_vol_first_10s),
        "buy_vol_first_5s": float(buy_vol_first_5s),
        "buy_vol_usd_15m": float(buy_vol_15m),
        "buy_vol_usd_30s": float(buy_vol_30s),
        "buy_vol_usd_total": float(buy_vol_total),
        "first10_buy_vol_usd": float(first10_buy_vol),
        "first5_buy_vol_share": _share(first5_buy_vol, buy_vol_total),
        "first5_buy_vol_usd": float(first5_buy_vol),
        "first_buy_usd": float(first_buy_usd),
        "max_buy_share": _share(max_buy_usd, buy_vol_total),
        "max_buy_sol": float(max_buy_sol) if buy_count_total else None,
        "max_buy_usd": float(max_buy_usd) if buy_count_total else None,
        "n_holders_proxy": float(len(pos_holders)),
        "net_sol_curve": float(net_sol_curve),
        "net_sol_total": float(net_sol_total),
        "progress_curve_proxy": float(progress) if progress is not None else None,
        "sell_count_15m": float(sell_count_15m),
        "sell_count_30s": float(sell_count_30s),
        "sell_count_total": float(sell_count_total),
        "sell_vol_usd_15m": float(sell_vol_15m),
        "sell_vol_usd_30s": float(sell_vol_30s),
        "sell_vol_usd_total": float(sell_vol_total),
        "sniper_vol_share_5s": _share(buy_vol_first_5s, buy_vol_total),
        "top10_buyer_vol_share": _share(top10_b, sum_buyer),
        "top10_holder_pct_proxy": _share(top10_h, sum_pos),
        "top1_buyer_vol_share": _share(top1_b, sum_buyer),
        "top1_holder_pct_proxy": _share(top1_h, sum_pos),
        "top5_buyer_vol_share": _share(top5_b, sum_buyer),
        "top5_holder_pct_proxy": _share(top5_h, sum_pos),
        "unique_buyers_first5": float(len(unique_buyers_first5)),
        "unique_buyers_first_5s": float(len(unique_buyers_first_5s)),
        "unique_buyers_total": float(len(buyers)),
        "unique_sellers_total": float(len(sellers)),
        "unique_traders_15m": float(len(traders_15m)),
        "unique_traders_30s": float(len(traders_30s)),
        # join-only / dropped from X but useful for debug
        "migrated_pre_t0": float(migrated),
    }


def _empty_q5a() -> dict[str, float | None]:
    """Successful enrich with zero trades ≤T0 (valid observation)."""
    zeros = {
        "age_proxy_s": 0.0,
        "buy_count_15m": 0.0,
        "buy_count_30s": 0.0,
        "buy_count_total": 0.0,
        "buy_vol_first_10s": 0.0,
        "buy_vol_first_5s": 0.0,
        "buy_vol_usd_15m": 0.0,
        "buy_vol_usd_30s": 0.0,
        "buy_vol_usd_total": 0.0,
        "first10_buy_vol_usd": 0.0,
        "first5_buy_vol_share": None,
        "first5_buy_vol_usd": 0.0,
        "first_buy_usd": 0.0,
        "max_buy_share": None,
        "max_buy_sol": None,
        "max_buy_usd": None,
        "n_holders_proxy": 0.0,
        "net_sol_curve": 0.0,
        "net_sol_total": 0.0,
        "progress_curve_proxy": 0.0,
        "sell_count_15m": 0.0,
        "sell_count_30s": 0.0,
        "sell_count_total": 0.0,
        "sell_vol_usd_15m": 0.0,
        "sell_vol_usd_30s": 0.0,
        "sell_vol_usd_total": 0.0,
        "sniper_vol_share_5s": None,
        "top10_buyer_vol_share": None,
        "top10_holder_pct_proxy": None,
        "top1_buyer_vol_share": None,
        "top1_holder_pct_proxy": None,
        "top5_buyer_vol_share": None,
        "top5_holder_pct_proxy": None,
        "unique_buyers_first5": 0.0,
        "unique_buyers_first_5s": 0.0,
        "unique_buyers_total": 0.0,
        "unique_sellers_total": 0.0,
        "unique_traders_15m": 0.0,
        "unique_traders_30s": 0.0,
        "migrated_pre_t0": 0.0,
    }
    return zeros


def aggregate_q5a_batch(
    trades_by_mint: dict[str, list[TradeRow]],
    mint_t0: dict[str, datetime],
) -> dict[str, dict[str, float | None]]:
    return {m: aggregate_q5a_for_mint(trades_by_mint.get(m, []), t0) for m, t0 in mint_t0.items()}
