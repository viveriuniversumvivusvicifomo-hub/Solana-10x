"""Enriquece candidatas Bitquery → filas con t0/p0/prices_after_t0 (N mínimo, 1 call).

IMPORTANTE
----------
T0 aquí es **provisional**: primer trade observado en la ventana de la query
(no el detector captura v0 completo: C1–C6 + BondingCurve).
``capture_quality`` = LOW. Suficiente para desbloquear labels / gate V2 en Cycle 1.
PRIMARY 30d quedará mayormente null si la ventana post-T0 es corta — no inventamos.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion.bitquery import (
    BITQUERY_GRAPHQL_URL,
    BitqueryClient,
    QuotaExceeded,
)
from ingestion.pump_constants import DEFINITION_VERSION, PUMP_PROGRAM_ID, SOL_USD_SOURCE

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_IN = ROOT / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json"
SAMPLE_OUT = ROOT / "data" / "samples" / "bitquery_enriched_capture_sample.json"

DEFAULT_N_MINTS = 5
DEFAULT_HOURS_AGO = 24
DEFAULT_TRADE_LIMIT = 200

QUERY_TRADES_MULTI = """
query PumpTradesForMints($mints: [String!], $hoursAgo: Int!, $limit: Int!, $program: String!) {
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
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
      }
    ) {
      Block { Time }
      Trade {
        Currency { MintAddress Symbol }
        PriceInUSD
        Price
      }
      Transaction { Signature }
    }
  }
}
"""


def _pick_mints(sample: dict[str, Any], n: int) -> list[dict[str, Any]]:
    rows = [r for r in (sample.get("rows") or []) if r.get("mint") and r.get("price_mean")]
    # prefer MC near mid-band for diversity
    rows.sort(key=lambda r: abs(float(r.get("mc_usd") or 0) - 14_000))
    return rows[:n]


def _capture_id(mint: str, t0_iso: str, sig0: str) -> str:
    raw = f"{mint}|{t0_iso}|{sig0}|{DEFINITION_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def enrich_from_trades(
    *,
    n_mints: int = DEFAULT_N_MINTS,
    hours_ago: int = DEFAULT_HOURS_AGO,
    trade_limit: int = DEFAULT_TRADE_LIMIT,
    sample_in: Path = SAMPLE_IN,
    sample_out: Path = SAMPLE_OUT,
) -> dict[str, Any]:
    sample = json.loads(sample_in.read_text())
    picked = _pick_mints(sample, n_mints)
    mints = [r["mint"] for r in picked]
    meta: dict[str, Any] = {
        "endpoint": BITQUERY_GRAPHQL_URL,
        "auth": "Authorization: Bearer <BITQUERY_TOKEN>",
        "source_sample": str(sample_in),
        "n_mints_requested": n_mints,
        "mints": mints,
        "hours_ago": hours_ago,
        "trade_limit": trade_limit,
        "program": PUMP_PROGRAM_ID,
        "definition_version": DEFINITION_VERSION,
        "sol_usd_source": SOL_USD_SOURCE,
        "t0_policy": "provisional_first_trade_in_window",
        "capture_quality": "LOW",
        "note": "T0 provisional (no C1–C6 detector). Labels 30d pueden ser null si ventana corta.",
    }

    client = BitqueryClient(max_calls=1)
    try:
        body = client.graphql(
            QUERY_TRADES_MULTI,
            {
                "mints": mints,
                "hoursAgo": hours_ago,
                "limit": trade_limit,
                "program": PUMP_PROGRAM_ID,
            },
        )
        trades = (((body.get("data") or {}).get("Solana") or {}).get("DEXTradeByTokens")) or []
        by_mint: dict[str, list[dict[str, Any]]] = {m: [] for m in mints}
        for tr in trades:
            mint = ((tr.get("Trade") or {}).get("Currency") or {}).get("MintAddress")
            ts = (tr.get("Block") or {}).get("Time")
            px = (tr.get("Trade") or {}).get("PriceInUSD")
            sig = ((tr.get("Transaction") or {}).get("Signature")) or ""
            if mint in by_mint and ts and px is not None and float(px) > 0:
                by_mint[mint].append({"ts": ts, "px": float(px), "sig": sig})

        enriched: list[dict[str, Any]] = []
        for base in picked:
            mint = base["mint"]
            series = sorted(by_mint.get(mint, []), key=lambda x: x["ts"])
            if len(series) < 2:
                continue  # need ≥1 price strictly after t0
            t0_raw = series[0]["ts"]
            # normalize to iso with tz
            t0_dt = datetime.fromisoformat(str(t0_raw).replace("Z", "+00:00"))
            if t0_dt.tzinfo is None:
                t0_dt = t0_dt.replace(tzinfo=timezone.utc)
            t0_iso = t0_dt.isoformat()
            p0 = float(series[0]["px"])
            sig0 = series[0]["sig"] or "unknown"
            prices_after = []
            for pt in series[1:]:
                ts_dt = datetime.fromisoformat(str(pt["ts"]).replace("Z", "+00:00"))
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                if ts_dt > t0_dt and pt["px"] > 0:
                    prices_after.append([ts_dt.isoformat(), pt["px"]])
            if not prices_after:
                continue
            enriched.append(
                {
                    "capture_id": _capture_id(mint, t0_iso, sig0),
                    "mint": mint,
                    "name": base.get("name"),
                    "symbol": base.get("symbol"),
                    "t0": t0_iso,
                    "p0": p0,
                    "sig0": sig0,
                    "mc0_snapshot": base.get("mc_usd"),
                    "price_mean_snapshot": base.get("price_mean"),
                    "prices_after_t0": prices_after,
                    "price_source": "bitquery.DEXTradeByTokens",
                    "sol_usd_source": SOL_USD_SOURCE,
                    "definition_version": DEFINITION_VERSION,
                    "capture_quality": "LOW",
                    "t0_policy": "provisional_first_trade_in_window",
                }
            )

        meta["status"] = "ok"
        meta["n_enriched"] = len(enriched)
        meta["n_trades_raw"] = len(trades)
        meta["call_log"] = client.log.to_dict()
        payload = {"meta": meta, "rows": enriched}
        sample_out.parent.mkdir(parents=True, exist_ok=True)
        sample_out.write_text(json.dumps(payload, indent=2))
        meta["snapshot"] = str(sample_out)
        return meta
    except QuotaExceeded as e:
        meta["status"] = "stopped_quota"
        meta["error"] = str(e)
        meta["call_log"] = client.log.to_dict()
        path = SAMPLE_OUT.with_name("bitquery_enriched_stopped.json")
        path.write_text(json.dumps(meta, indent=2))
        meta["snapshot"] = str(path)
        return meta
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = str(e)[:800]
        meta["call_log"] = client.log.to_dict()
        path = SAMPLE_OUT.with_name("bitquery_enriched_error.json")
        path.write_text(json.dumps(meta, indent=2))
        meta["snapshot"] = str(path)
        return meta
    finally:
        client.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--n-mints", type=int, default=DEFAULT_N_MINTS)
    p.add_argument("--hours-ago", type=int, default=DEFAULT_HOURS_AGO)
    p.add_argument("--trade-limit", type=int, default=DEFAULT_TRADE_LIMIT)
    args = p.parse_args()
    print(json.dumps(enrich_from_trades(n_mints=args.n_mints, hours_ago=args.hours_ago, trade_limit=args.trade_limit), indent=2))
