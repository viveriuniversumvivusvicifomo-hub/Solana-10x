"""Feed de candidatos MC ∈ [8k,20k]: Pump.fun frontend (default) | Bitquery | sample dry-run.

Default live path: ``ingestion.pump_frontend.fetch_pump_mc_band`` (frontend-api-v3).
Bitquery optional via ``--feed bitquery`` (often 402/429 on FREE).
Helius streams OFF.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from paper_live.config import MC_HI, MC_LO, SAMPLE_BITQUERY, SAMPLE_PUMP


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class MintSighting:
    """Snapshot al primer avistamiento en banda (T0 provisional paper-live)."""

    mint: str
    mc_usd: float
    name: str | None
    symbol: str | None
    price_mean: float | None
    total_supply: float | None
    market_address: str | None
    source: str
    seen_at: datetime
    raw: dict[str, Any]

    @property
    def t0_iso(self) -> str:
        return self.seen_at.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _row_to_sighting(row: dict[str, Any], *, seen_at: datetime, source: str) -> MintSighting | None:
    mint = row.get("mint")
    mc = row.get("mc_usd")
    if mc is None:
        mc = row.get("usd_market_cap")
    if not mint or mc is None:
        return None
    try:
        mc_f = float(mc)
    except (TypeError, ValueError):
        return None
    if not (MC_LO <= mc_f <= MC_HI):
        return None
    price = row.get("price_mean")
    supply = row.get("total_supply")
    return MintSighting(
        mint=str(mint),
        mc_usd=mc_f,
        name=row.get("name"),
        symbol=row.get("symbol"),
        price_mean=float(price) if price is not None else None,
        total_supply=float(supply) if supply is not None else None,
        market_address=row.get("market_address") or row.get("bonding_curve"),
        source=source,
        seen_at=seen_at,
        raw=dict(row),
    )


def load_sample_rows(path: Path | None = None) -> list[dict[str, Any]]:
    p = path or SAMPLE_BITQUERY
    data = json.loads(p.read_text())
    return list(data.get("rows") or [])


def poll_sample(
    path: Path | None = None,
    *,
    seen_at: datetime | None = None,
    offset: int = 0,
    batch: int = 10,
    source: str = "dry_run.sample",
) -> list[MintSighting]:
    """Dry-run: entrega un batch del sample como si fueran mints nuevos."""
    rows = load_sample_rows(path)
    ts = seen_at or _utcnow()
    out: list[MintSighting] = []
    for row in rows[offset : offset + batch]:
        s = _row_to_sighting(row, seen_at=ts, source=source)
        if s:
            out.append(s)
    return out


def poll_bitquery(
    *,
    limit: int = 50,
    hours_ago: int = 2,
    mc_lo: float = MC_LO,
    mc_hi: float = MC_HI,
    client: Any = None,
) -> tuple[list[MintSighting], Any]:
    """1 poll live vía Bitquery Trading.Pairs (misma query cycle0)."""
    from ingestion.bitquery import BitqueryClient, fetch_pump_mc_candidates

    owns = client is None
    client = client or BitqueryClient(max_calls=1)
    try:
        rows, log = fetch_pump_mc_candidates(
            limit=limit,
            hours_ago=hours_ago,
            mc_lo=mc_lo,
            mc_hi=mc_hi,
            client=client,
        )
        ts = _utcnow()
        sightings = [
            s
            for s in (
                _row_to_sighting(r, seen_at=ts, source="bitquery.Trading.Pairs") for r in rows
            )
            if s is not None
        ]
        return sightings, log
    finally:
        if owns:
            client.close()


def poll_pump(
    *,
    mc_lo: float = MC_LO,
    mc_hi: float = MC_HI,
    limit: int = 50,
    max_pages: int = 2,
    client: Any = None,
) -> tuple[list[MintSighting], Any]:
    """1 poll live vía frontend-api-v3.pump.fun /coins + client MC filter."""
    from ingestion.pump_frontend import PumpFrontendClient, fetch_pump_mc_band

    owns = client is None
    client = client or PumpFrontendClient()
    try:
        rows, log = fetch_pump_mc_band(
            mc_lo=mc_lo,
            mc_hi=mc_hi,
            limit=limit,
            max_pages=max_pages,
            client=client,
        )
        ts = _utcnow()
        sightings = [
            s
            for s in (
                _row_to_sighting(r, seen_at=ts, source="pump.frontend-api-v3") for r in rows
            )
            if s is not None
        ]
        return sightings, log
    finally:
        if owns:
            client.close()


def iter_dry_batches(
    path: Path | None = None,
    *,
    batch: int = 10,
) -> Iterator[list[MintSighting]]:
    rows = load_sample_rows(path)
    for i in range(0, len(rows), batch):
        yield poll_sample(path, offset=i, batch=batch)
