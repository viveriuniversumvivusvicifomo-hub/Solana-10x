"""Positivos ≥10x vía MC≥200k (Sinck): listar Pump hit≥200k + reconstruir T0 = primer cruce 8k–20k.

Política FREE: máx 2 calls Bitquery; parar en 402/429 → evaluar Dune.
Streams Helius OFF.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.bitquery import BITQUERY_GRAPHQL_URL, BitqueryClient, QuotaExceeded
from ingestion.pump_constants import DEFINITION_VERSION, PUMP_PROGRAM_ID, SOL_USD_SOURCE

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "samples" / "positives_mc200k_t0.json"
LOG = ROOT / "data" / "samples" / "positives_mc200k_call_log.json"

MC_HIT = 200_000.0
MC_LO = 8_000.0
MC_HI = 20_000.0
DEFAULT_LIST_LIMIT = 30
DEFAULT_HOURS_AGO_LIST = 48
DEFAULT_DAYS_AGO_TRADES = 14
DEFAULT_TRADE_LIMIT = 500

# Call 1: tokens currently/recently with MC ≥ 200k on Pump bonding program
QUERY_HIT_200K = """
query PumpHit200k($mcHit: Float!, $limit: Int!, $hoursAgo: Int!, $program: String!) {
  Trading {
    Pairs(
      limit: { count: $limit }
      limitBy: { by: Token_Address, count: 1 }
      orderBy: { descending: Supply_MarketCap }
      where: {
        Market: { Program: { is: $program } }
        Token: { Network: { is: "Solana" } }
        Supply: { MarketCap: { ge: $mcHit } }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
        Interval: { Time: { Duration: { eq: 60 } } }
      }
    ) {
      Token { Address Name Symbol }
      Supply { MarketCap TotalSupply }
      Market { Address Program }
      Price { Average { Mean } }
    }
  }
}
"""

# Call 2: trades ascending for those mints → reconstruct first MC in [8k,20k]
QUERY_TRADES = """
query PumpTradesAsc($mints: [String!], $daysAgo: Int!, $limit: Int!, $program: String!) {
  Solana {
    DEXTradeByTokens(
      limit: { count: $limit }
      orderBy: { ascending: Block_Time }
      where: {
        Trade: {
          Currency: { MintAddress: { in: $mints } }
          Dex: { ProgramAddress: { is: $program } }
          PriceInUSD: { gt: 0 }
        }
        Transaction: { Result: { Success: true } }
        Block: { Time: { since_relative: { days_ago: $daysAgo } } }
      }
    ) {
      Block { Time }
      Trade {
        Currency { MintAddress }
        PriceInUSD
      }
      Transaction { Signature }
    }
  }
}
"""


def _cid(mint: str, t0: str, sig: str) -> str:
    return hashlib.sha256(f"{mint}|{t0}|{sig}|{DEFINITION_VERSION}".encode()).hexdigest()[:32]


def _mc_from_price(price_usd: float, total_supply_ui: float) -> float:
    """MC ≈ price_usd * supply UI (Pump típ. 1e9)."""
    return price_usd * total_supply_ui


def run(
    *,
    list_limit: int = DEFAULT_LIST_LIMIT,
    hours_ago_list: int = DEFAULT_HOURS_AGO_LIST,
    days_ago_trades: int = DEFAULT_DAYS_AGO_TRADES,
    trade_limit: int = DEFAULT_TRADE_LIMIT,
    max_mints_for_t0: int = 10,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "endpoint": BITQUERY_GRAPHQL_URL,
        "auth": "Authorization: Bearer <BITQUERY_TOKEN>",
        "mc_hit": MC_HIT,
        "mc_band_t0": [MC_LO, MC_HI],
        "list_limit": list_limit,
        "hours_ago_list": hours_ago_list,
        "days_ago_trades": days_ago_trades,
        "program": PUMP_PROGRAM_ID,
        "definition_version": DEFINITION_VERSION,
        "method": "positives_via_mc_ge_200k_then_first_band_cross",
        "note": (
            "Positivos Sinck: hit MC≥200k ⇒ ≥10x desde captura 8k–20k. "
            "T0 = primer trade con MC∈[8k,20k] en serie (aprox supply×price)."
        ),
    }
    client = BitqueryClient(max_calls=2, min_interval_s=1.5, timeout_s=90.0)
    try:
        # --- Call 1: lista hit ≥200k ---
        body = client.graphql(
            QUERY_HIT_200K,
            {
                "mcHit": MC_HIT,
                "limit": list_limit,
                "hoursAgo": hours_ago_list,
                "program": PUMP_PROGRAM_ID,
            },
        )
        pairs = (((body.get("data") or {}).get("Trading") or {}).get("Pairs")) or []
        hit_rows = []
        for p in pairs:
            tok = p.get("Token") or {}
            sup = p.get("Supply") or {}
            mc = sup.get("MarketCap")
            supply = sup.get("TotalSupply") or 1_000_000_000
            if not tok.get("Address") or mc is None:
                continue
            hit_rows.append(
                {
                    "mint": tok["Address"],
                    "name": tok.get("Name"),
                    "symbol": tok.get("Symbol"),
                    "mc_usd_observed": float(mc),
                    "total_supply": float(supply),
                    "price_mean": ((p.get("Price") or {}).get("Average") or {}).get("Mean"),
                    "market_address": (p.get("Market") or {}).get("Address"),
                                    }
            )
        meta["n_hit_200k"] = len(hit_rows)
        meta["call1_ok"] = True

        if not hit_rows:
            meta["status"] = "ok_empty"
            meta["n"] = 0
            meta["call_log"] = client.log.to_dict()
            OUT.write_text(json.dumps({"meta": meta, "hit_200k": [], "rows": []}, indent=2))
            LOG.write_text(json.dumps(client.log.to_dict(), indent=2))
            meta["snapshot"] = str(OUT)
            return meta

        # --- Call 2: trades para reconstruir T0 (N pequeño) ---
        subset = hit_rows[:max_mints_for_t0]
        mints = [r["mint"] for r in subset]
        supply_by = {r["mint"]: r["total_supply"] for r in subset}
        body2 = client.graphql(
            QUERY_TRADES,
            {
                "mints": mints,
                "daysAgo": days_ago_trades,
                "limit": trade_limit,
                "program": PUMP_PROGRAM_ID,
            },
        )
        trades = (((body2.get("data") or {}).get("Solana") or {}).get("DEXTradeByTokens")) or []
        by_mint: dict[str, list[dict[str, Any]]] = {m: [] for m in mints}
        for tr in trades:
            mint = ((tr.get("Trade") or {}).get("Currency") or {}).get("MintAddress")
            ts = (tr.get("Block") or {}).get("Time")
            px = (tr.get("Trade") or {}).get("PriceInUSD")
            sig = ((tr.get("Transaction") or {}).get("Signature")) or ""
            if mint in by_mint and ts and px and float(px) > 0:
                by_mint[mint].append({"ts": ts, "px": float(px), "sig": sig})

        rows: list[dict[str, Any]] = []
        for base in subset:
            mint = base["mint"]
            series = sorted(by_mint.get(mint, []), key=lambda x: x["ts"])
            supply = supply_by[mint] or 1_000_000_000
            t0_pt = None
            for pt in series:
                mc = _mc_from_price(pt["px"], supply)
                if MC_LO <= mc <= MC_HI:
                    t0_pt = pt
                    t0_mc = mc
                    break
            if t0_pt is None:
                continue
            t0_dt = datetime.fromisoformat(str(t0_pt["ts"]).replace("Z", "+00:00"))
            if t0_dt.tzinfo is None:
                t0_dt = t0_dt.replace(tzinfo=timezone.utc)
            t0_iso = t0_dt.isoformat()
            p0 = float(t0_pt["px"])
            # prices strictly after T0 (for labels); include later high-MC evidence
            prices_after = []
            max_mc_after = t0_mc
            for pt in series:
                ts_dt = datetime.fromisoformat(str(pt["ts"]).replace("Z", "+00:00"))
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                if ts_dt > t0_dt:
                    prices_after.append([ts_dt.isoformat(), pt["px"]])
                    max_mc_after = max(max_mc_after, _mc_from_price(pt["px"], supply))
            rows.append(
                {
                    "capture_id": _cid(mint, t0_iso, t0_pt["sig"] or "unknown"),
                    "mint": mint,
                    "name": base.get("name"),
                    "symbol": base.get("symbol"),
                    "t0": t0_iso,
                    "p0": p0,
                    "mc0": t0_mc,
                    "sig0": t0_pt["sig"] or "unknown",
                    "total_supply": supply,
                    "mc_usd_hit_observed": base["mc_usd_observed"],
                    "max_mc_after_t0_in_sample": max_mc_after,
                    "positive_rule": "mc_hit_ge_200k",
                    "label_primary_hint": 1,  # hit ≥200k ⇒ ≥10x from ≤20k band
                    "prices_after_t0": prices_after,
                    "price_source": "bitquery.DEXTradeByTokens",
                    "sol_usd_source": SOL_USD_SOURCE,
                    "definition_version": DEFINITION_VERSION,
                    "capture_quality": "MED",  # band cross from trades, not full on-chain C1–C6
                    "t0_policy": "first_trade_mc_in_8k_20k_after_hit200k_universe",
                }
            )

        meta["status"] = "ok"
        meta["n"] = len(rows)
        meta["n_hit_200k_listed"] = len(hit_rows)
        meta["n_mints_trades_queried"] = len(mints)
        meta["n_trades_raw"] = len(trades)
        meta["call_log"] = client.log.to_dict()
        payload = {"meta": meta, "hit_200k": hit_rows, "rows": rows}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(payload, indent=2))
        LOG.write_text(json.dumps(client.log.to_dict(), indent=2))
        meta["snapshot"] = str(OUT)
        return meta
    except QuotaExceeded as e:
        meta["status"] = "stopped_quota"
        meta["error"] = str(e)
        meta["call_log"] = client.log.to_dict()
        meta["next"] = "pivot Dune (u otra gratis) antes de gastar"
        path = OUT.with_name("positives_mc200k_stopped.json")
        path.write_text(json.dumps(meta, indent=2))
        LOG.write_text(json.dumps(client.log.to_dict(), indent=2))
        meta["snapshot"] = str(path)
        return meta
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = str(e)[:800]
        meta["call_log"] = client.log.to_dict()
        path = OUT.with_name("positives_mc200k_error.json")
        path.write_text(json.dumps({"meta": meta}, indent=2))
        LOG.write_text(json.dumps(client.log.to_dict(), indent=2))
        meta["snapshot"] = str(path)
        return meta
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--list-limit", type=int, default=DEFAULT_LIST_LIMIT)
    ap.add_argument("--hours-ago-list", type=int, default=DEFAULT_HOURS_AGO_LIST)
    ap.add_argument("--days-ago-trades", type=int, default=DEFAULT_DAYS_AGO_TRADES)
    ap.add_argument("--trade-limit", type=int, default=DEFAULT_TRADE_LIMIT)
    ap.add_argument("--max-mints", type=int, default=10)
    args = ap.parse_args()
    print(
        json.dumps(
            run(
                list_limit=args.list_limit,
                hours_ago_list=args.hours_ago_list,
                days_ago_trades=args.days_ago_trades,
                trade_limit=args.trade_limit,
                max_mints_for_t0=args.max_mints,
            ),
            indent=2,
        )
    )
