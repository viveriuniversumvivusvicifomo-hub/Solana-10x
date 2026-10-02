"""Cliente Bitquery GraphQL (histórico Pump). Cuota baja; sin streams.

Auth
----
- Endpoint: ``https://streaming.bitquery.io/graphql``
- Header: ``Authorization: Bearer <BITQUERY_TOKEN>``
- Token solo desde env / ``.env`` (nunca en código ni logs).

Política FREE
-------------
- Parar ante HTTP 402 / 429 / mensajes de límite.
- ``max_calls`` por proceso; default 3.
- Streams desactivados (usar RPC Helius streams.py aparte, también OFF).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from ingestion.env import require_bitquery_token
from ingestion.pump_constants import PUMP_PROGRAM_ID

BITQUERY_GRAPHQL_URL = "https://streaming.bitquery.io/graphql"
# Alternativa documentada (legacy): https://graphql.bitquery.io — preferir streaming.

# Candidatos MC captura v0
MC_LO = 8_000.0
MC_HI = 20_000.0

DEFAULT_LIMIT = 50  # Sinck: N pequeño ≤50–100
DEFAULT_HOURS_AGO = 6  # ventana reciente acotada
DEFAULT_MAX_CALLS = 3

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "samples"


@dataclass
class BitqueryCallLog:
    calls: list[dict[str, Any]] = field(default_factory=list)
    stopped_reason: str | None = None

    def record(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.calls, "stopped_reason": self.stopped_reason, "n_calls": len(self.calls)}


class QuotaExceeded(RuntimeError):
    """402/429 o límite de créditos — parar y evaluar Dune/otra gratis."""


class BitqueryClient:
    def __init__(
        self,
        token: str | None = None,
        *,
        max_calls: int = DEFAULT_MAX_CALLS,
        min_interval_s: float = 1.0,
        timeout_s: float = 60.0,
    ) -> None:
        self._token = token or require_bitquery_token()
        self._max_calls = max_calls
        self._min_interval_s = min_interval_s
        self._last = 0.0
        self._client = httpx.Client(timeout=timeout_s)
        self.log = BitqueryCallLog()
        self._n = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BitqueryClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._n >= self._max_calls:
            self.log.stopped_reason = f"max_calls={self._max_calls}"
            raise QuotaExceeded(self.log.stopped_reason)
        self._throttle()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        payload = {"query": query, "variables": variables or {}}
        t0 = time.monotonic()
        resp = self._client.post(BITQUERY_GRAPHQL_URL, headers=headers, json=payload)
        latency_ms = (time.monotonic() - t0) * 1000
        self._n += 1
        entry: dict[str, Any] = {
            "n": self._n,
            "status": resp.status_code,
            "latency_ms": round(latency_ms, 1),
            "bytes": len(resp.content),
        }
        # Never log Authorization / token
        if resp.status_code in (402, 429):
            entry["error"] = resp.text[:300]
            self.log.record(**entry)
            self.log.stopped_reason = f"HTTP {resp.status_code}"
            raise QuotaExceeded(f"HTTP {resp.status_code}: parar — evaluar Dune u otra gratis")
        if resp.status_code >= 400:
            entry["error"] = resp.text[:500]
            self.log.record(**entry)
            raise RuntimeError(f"Bitquery HTTP {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        if "errors" in body:
            msgs = "; ".join(
                e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in body["errors"]
            )[:500]
            entry["graphql_errors"] = msgs
            self.log.record(**entry)
            low = msgs.lower()
            if any(x in low for x in ("quota", "credit", "limit", "payment", "402", "429")):
                self.log.stopped_reason = "quota/limit in graphql errors"
                raise QuotaExceeded(msgs)
            raise RuntimeError(f"Bitquery GraphQL errors: {msgs}")
        # points/cost headers if present
        for h in ("X-Bitquery-Points", "X-Bitquery-Query-Cost", "x-query-cost"):
            if h in resp.headers:
                entry[h] = resp.headers[h]
        entry["ok"] = True
        self.log.record(**entry)
        return body


# Trading API — pares Pump con MC en banda (1 punto de datos por token)
QUERY_PUMP_MC_CANDIDATES = """
query PumpMcCandidates($mcLo: Float!, $mcHi: Float!, $limit: Int!, $hoursAgo: Int!, $program: String!) {
  Trading {
    Pairs(
      limit: { count: $limit }
      limitBy: { by: Token_Address, count: 1 }
      orderBy: { descending: Block_Time }
      where: {
        Market: { Program: { is: $program } }
        Token: { Network: { is: "Solana" } }
        Supply: { MarketCap: { ge: $mcLo, le: $mcHi } }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
        Interval: { Time: { Duration: { eq: 1 } } }
      }
    ) {
      Token { Address Name Symbol }
      Supply { MarketCap TotalSupply }
      Market { Address Program Name }
      Price { Average { Mean } }
    }
  }
}
"""


def fetch_pump_mc_candidates(
    *,
    limit: int = DEFAULT_LIMIT,
    hours_ago: int = DEFAULT_HOURS_AGO,
    mc_lo: float = MC_LO,
    mc_hi: float = MC_HI,
    client: BitqueryClient | None = None,
) -> tuple[list[dict[str, Any]], BitqueryCallLog]:
    """1ª pasada histórica: candidatos Pump MC ∈ [mc_lo, mc_hi], ventana hours_ago."""
    owns = client is None
    client = client or BitqueryClient(max_calls=1)
    try:
        data = client.graphql(
            QUERY_PUMP_MC_CANDIDATES,
            {
                "mcLo": mc_lo,
                "mcHi": mc_hi,
                "limit": limit,
                "hoursAgo": hours_ago,
                "program": PUMP_PROGRAM_ID,
            },
        )
        pairs = (((data.get("data") or {}).get("Trading") or {}).get("Pairs")) or []
        rows: list[dict[str, Any]] = []
        for p in pairs:
            tok = p.get("Token") or {}
            sup = p.get("Supply") or {}
            mkt = p.get("Market") or {}
            price = ((p.get("Price") or {}).get("Average") or {}).get("Mean")
            rows.append(
                {
                    "mint": tok.get("Address"),
                    "name": tok.get("Name"),
                    "symbol": tok.get("Symbol"),
                    "mc_usd": sup.get("MarketCap"),
                    "total_supply": sup.get("TotalSupply"),
                    "market_address": mkt.get("Address"),
                    "program": mkt.get("Program"),
                    "price_mean": price,
                    "source": "bitquery.Trading.Pairs",
                    "mc_band": [mc_lo, mc_hi],
                    "hours_ago": hours_ago,
                }
            )
        return rows, client.log
    finally:
        if owns:
            client.close()


def run_first_sample(
    *,
    limit: int = DEFAULT_LIMIT,
    hours_ago: int = DEFAULT_HOURS_AGO,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Ejecuta 1 query, escribe snapshot + log de llamadas. Para si 402/429."""
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "endpoint": BITQUERY_GRAPHQL_URL,
        "auth": "Authorization: Bearer <BITQUERY_TOKEN>",
        "limit": limit,
        "hours_ago": hours_ago,
        "mc_lo": MC_LO,
        "mc_hi": MC_HI,
        "program": PUMP_PROGRAM_ID,
    }
    client = BitqueryClient(max_calls=1)
    try:
        rows, log = fetch_pump_mc_candidates(
            limit=limit, hours_ago=hours_ago, client=client
        )
        meta["status"] = "ok"
        meta["n"] = len(rows)
        meta["call_log"] = log.to_dict()
        snap = out_dir / "bitquery_pump_mc_8k_20k_sample.json"
        # meta without nested call_log duplication in file header
        payload_meta = {k: v for k, v in meta.items()}
        snap.write_text(json.dumps({"meta": payload_meta, "rows": rows}, indent=2))
        meta["snapshot"] = str(snap)
        (out_dir / "bitquery_call_log.json").write_text(json.dumps(log.to_dict(), indent=2))
        return meta
    except QuotaExceeded as e:
        meta["status"] = "stopped_quota"
        meta["error"] = str(e)
        meta["call_log"] = client.log.to_dict()
        path = out_dir / "bitquery_stopped.json"
        path.write_text(json.dumps(meta, indent=2))
        meta["snapshot"] = str(path)
        return meta
    except Exception as e:
        meta["status"] = "error"
        meta["error"] = str(e)[:800]
        meta["call_log"] = client.log.to_dict()
        path = out_dir / "bitquery_error.json"
        path.write_text(json.dumps(meta, indent=2))
        meta["snapshot"] = str(path)
        return meta
    finally:
        client.close()


def client_log_safe(_exc: Exception) -> dict[str, Any]:
    return {"note": "see bitquery_stopped / exception message; token never logged"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Bitquery Pump MC sample (cuota baja)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--hours-ago", type=int, default=DEFAULT_HOURS_AGO)
    args = parser.parse_args()
    result = run_first_sample(limit=args.limit, hours_ago=args.hours_ago)
    # redact nothing sensitive — meta has no token
    print(json.dumps(result, indent=2))
