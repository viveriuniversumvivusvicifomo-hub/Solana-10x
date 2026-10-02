"""Live / dry enrich for ``buy_vol_usd_60s`` ≤T0 (parity with Dune Q4).

Window (same as ``cycle0/dune-q4-flow-pre-t0.sql``)
-----------------------------------------------------
For each mint with paper T0 = ``seen_at``:

    buy_vol_usd_60s = Σ amount_usd of *buys* with block_time ∈ [t0 − 60s, t0]

Buy side (Bitquery DEXTradeByTokens): ``Trade.Side.Type == buy``.
USD measure: prefer ``Trade.Side.AmountInUSD``, else ``Trade.AmountInUSD``.
No post-T0 trades. Never invents volume — query failure → None (caller skips).

Fetch strategy
--------------
Pull recent buys with ``since_relative: hours_ago`` + ``orderBy: descending Block_Time``
(so ``limit`` keeps the newest rows, not the oldest), then **filter client-side**
to each mint's ``[t0−60s, t0]``. Ascending+limit missed the 60s window on busy mints
(smoke 2026-10-01).

Cost
----
- Live: **1 Bitquery GraphQL call per batch** of new mints (``in: $mints``).
  FREE quota: treat as expensive as the MC poll; budget via ``max_calls``.
- Dry-run: local fixture ``data/samples/buy_vol_usd_60s_fixture.json`` (0 calls).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from paper_live.config import SAMPLE_BUY_VOL_FIXTURE

WINDOW_S = 60

# Relative window pull; client filters ≤ each mint T0.
QUERY_BUY_TRADES_PRE_T0 = """
query BuyVolTradesPreT0(
  $mints: [String!]
  $hoursAgo: Int!
  $limit: Int!
  $program: String!
) {
  Solana {
    DEXTradeByTokens(
      limit: { count: $limit }
      orderBy: { descending: Block_Time }
      where: {
        Trade: {
          Currency: { MintAddress: { in: $mints } }
          Dex: { ProgramAddress: { is: $program } }
          Side: { Type: { is: buy } }
        }
        Transaction: { Result: { Success: true } }
        Block: { Time: { since_relative: { hours_ago: $hoursAgo } } }
      }
    ) {
      Block { Time }
      Trade {
        Currency { MintAddress }
        Side { Type AmountInUSD }
        AmountInUSD
      }
    }
  }
}
"""


@dataclass(frozen=True)
class BuyVolResult:
    mint: str
    buy_vol_usd_60s: float | None
    buy_count_60s: int | None
    source: str
    window_s: int = WINDOW_S
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.buy_vol_usd_60s is not None


def _parse_ts(raw: str | datetime) -> datetime:
    if isinstance(raw, datetime):
        dt = raw
    else:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _usd_from_trade(tr: dict[str, Any]) -> float | None:
    trade = tr.get("Trade") or {}
    side = trade.get("Side") or {}
    for obj in (side, trade):
        v = obj.get("AmountInUSD") if isinstance(obj, dict) else None
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f) and f >= 0:
            return f
    return None


def aggregate_buy_vol_from_trades(
    trades: list[dict[str, Any]],
    mint_t0: dict[str, datetime],
    *,
    window_s: int = WINDOW_S,
    source: str = "bitquery.DEXTradeByTokens",
) -> dict[str, BuyVolResult]:
    """Σ buy USD in [t0−window_s, t0] per mint. No look-ahead past that mint's T0."""
    vols: dict[str, float] = {m: 0.0 for m in mint_t0}
    counts: dict[str, int] = {m: 0 for m in mint_t0}
    for tr in trades:
        mint = ((tr.get("Trade") or {}).get("Currency") or {}).get("MintAddress")
        if mint not in mint_t0:
            continue
        side = ((tr.get("Trade") or {}).get("Side") or {}).get("Type")
        if side is not None and str(side).lower() != "buy":
            continue
        ts_raw = (tr.get("Block") or {}).get("Time")
        if not ts_raw:
            continue
        ts = _parse_ts(ts_raw)
        t0 = mint_t0[mint]
        lo = t0 - timedelta(seconds=window_s)
        if ts < lo or ts > t0:
            continue
        usd = _usd_from_trade(tr)
        if usd is None:
            continue
        vols[mint] += usd
        counts[mint] += 1

    out: dict[str, BuyVolResult] = {}
    for mint in mint_t0:
        # 0.0 is a valid observation (no buys in window) when query succeeded
        out[mint] = BuyVolResult(
            mint=mint,
            buy_vol_usd_60s=float(vols[mint]),
            buy_count_60s=int(counts[mint]),
            source=source,
            window_s=window_s,
            detail=f"window=[{window_s}s≤T0] n_buys={counts[mint]}",
        )
    return out


def load_fixture(path: Path | None = None) -> dict[str, dict[str, Any]]:
    p = path or SAMPLE_BUY_VOL_FIXTURE
    data = json.loads(p.read_text())
    return dict(data.get("by_mint") or {})


def buy_vol_from_fixture(
    mints: list[str],
    *,
    path: Path | None = None,
) -> dict[str, BuyVolResult]:
    """Dry-run: populate from fixture. Missing mint → unavailable (None)."""
    by = load_fixture(path)
    out: dict[str, BuyVolResult] = {}
    for mint in mints:
        row = by.get(mint)
        if not row or row.get("buy_vol_usd_60s") is None:
            out[mint] = BuyVolResult(
                mint=mint,
                buy_vol_usd_60s=None,
                buy_count_60s=None,
                source="dry_run.fixture",
                detail="mint absent from fixture",
            )
            continue
        out[mint] = BuyVolResult(
            mint=mint,
            buy_vol_usd_60s=float(row["buy_vol_usd_60s"]),
            buy_count_60s=int(row.get("buy_count_60s") or 0),
            source="dry_run.fixture",
            detail="fixture",
        )
    return out


def _hours_ago_covering(mint_t0: dict[str, datetime], *, pad_hours: int = 1) -> int:
    """Relative lookback long enough to cover min(t0)−60s."""
    now = datetime.now(timezone.utc)
    oldest = min(mint_t0.values()) - timedelta(seconds=WINDOW_S)
    span_h = (now - oldest).total_seconds() / 3600.0
    return max(1, int(math.ceil(span_h)) + pad_hours)


def fetch_buy_vol_usd_60s(
    mint_t0: dict[str, datetime],
    *,
    client: Any,
    trade_limit: int = 500,
    window_s: int = WINDOW_S,
    hours_ago: int | None = None,
    program: str | None = None,
) -> dict[str, BuyVolResult]:
    """1 Bitquery call: buys for mints; filter ≤ each T0 client-side."""
    from ingestion.pump_constants import PUMP_PROGRAM_ID

    if not mint_t0:
        return {}
    prog = program or PUMP_PROGRAM_ID
    ha = hours_ago if hours_ago is not None else _hours_ago_covering(mint_t0)
    body = client.graphql(
        QUERY_BUY_TRADES_PRE_T0,
        {
            "mints": list(mint_t0.keys()),
            "hoursAgo": ha,
            "limit": trade_limit,
            "program": prog,
        },
    )
    trades = (((body.get("data") or {}).get("Solana") or {}).get("DEXTradeByTokens")) or []
    return aggregate_buy_vol_from_trades(
        trades,
        mint_t0,
        window_s=window_s,
        source="bitquery.DEXTradeByTokens",
    )


def enrich_buy_vol_for_sightings(
    sightings: list[Any],
    *,
    dry_run: bool,
    client: Any | None = None,
    fixture_path: Path | None = None,
    trade_limit: int = 500,
    hours_ago: int | None = None,
) -> dict[str, BuyVolResult]:
    """Batch enrich. Dry → fixture; live → Bitquery (requires client)."""
    if not sightings:
        return {}
    mints = [s.mint for s in sightings]
    if dry_run or client is None:
        return buy_vol_from_fixture(mints, path=fixture_path)
    mint_t0 = {
        s.mint: s.seen_at if hasattr(s, "seen_at") else _parse_ts(s.t0_iso) for s in sightings
    }
    mint_t0 = {m: _parse_ts(t) for m, t in mint_t0.items()}
    return fetch_buy_vol_usd_60s(
        mint_t0,
        client=client,
        trade_limit=trade_limit,
        hours_ago=hours_ago,
    )
