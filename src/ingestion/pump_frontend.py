"""Cliente Pump.fun frontend-api-v3 (listado coins / MC band).

Endpoint ya usado en cycle0 (`pump_frontend_mc200k_current.json`,
`universo-current-vs-30d.md`):

  GET https://frontend-api-v3.pump.fun/coins
    ?offset=&limit=&sort=last_trade_timestamp|created_timestamp
    &order=DESC&includeNsfw=false&complete=false

Auth: ninguna para listado público. Opcional ``PUMP_JWT`` / ``PUMP_API_TOKEN``
(Bearer) si el usuario lo pone en ``.env`` — útil si trades vuelven a abrir.

Rate limit: 429 con ``retryAfterMs`` → backoff. Streams Helius OFF.
Trading: False (solo lectura).
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.env import load_dotenv
from ingestion.pump_constants import INITIAL_REAL_TOKEN_RESERVES

PUMP_FRONTEND_BASE = "https://frontend-api-v3.pump.fun"
SOLANA_MAINNET_CHAIN_ID = "solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"

# Conservative poll defaults (frontend rate-limits aggressively)
DEFAULT_MIN_INTERVAL_S = 0.8
DEFAULT_LIMIT = 50
DEFAULT_MAX_PAGES = 2


def optional_pump_jwt() -> str | None:
    load_dotenv()
    for key in ("PUMP_JWT", "PUMP_API_TOKEN", "PUMP_TOKEN"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


@dataclass
class PumpFrontendCallLog:
    n_calls: int = 0
    status_codes: list[int] = field(default_factory=list)
    n_retries_429: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_calls": self.n_calls,
            "status_codes": list(self.status_codes),
            "n_retries_429": self.n_retries_429,
        }


class PumpFrontendClient:
    """HTTP client for frontend-api-v3.pump.fun (read-only)."""

    def __init__(
        self,
        *,
        jwt: str | None = None,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: float = 30.0,
        max_retries_429: int = 5,
    ) -> None:
        self._jwt = jwt if jwt is not None else optional_pump_jwt()
        self._min_interval_s = min_interval_s
        self._max_retries_429 = max_retries_429
        self._last_call = 0.0
        headers = {
            "User-Agent": "solana-10x-paper-live/0.1 (research; no trading)",
            "Accept": "application/json",
        }
        if self._jwt:
            headers["Authorization"] = f"Bearer {self._jwt}"
        self._client = httpx.Client(timeout=timeout_s, headers=headers)
        self.log = PumpFrontendCallLog()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PumpFrontendClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = path if path.startswith("http") else f"{PUMP_FRONTEND_BASE}{path}"
        last_err: Exception | None = None
        for attempt in range(self._max_retries_429 + 1):
            self._throttle()
            resp = self._client.get(url, params=params)
            self.log.n_calls += 1
            self.log.status_codes.append(resp.status_code)
            if resp.status_code == 429:
                self.log.n_retries_429 += 1
                try:
                    body = resp.json()
                    retry_ms = float(body.get("retryAfterMs") or 200)
                except Exception:
                    retry_ms = 200.0
                time.sleep(retry_ms / 1000.0 + 0.5 + attempt * 0.4)
                last_err = RuntimeError(f"Pump frontend 429 after retries on {path}")
                continue
            if resp.status_code >= 400:
                raise RuntimeError(
                    f"Pump frontend HTTP {resp.status_code}: {resp.text[:300]}"
                )
            return resp.json()
        raise last_err or RuntimeError("Pump frontend rate limited")

    def list_coins(
        self,
        *,
        offset: int = 0,
        limit: int = DEFAULT_LIMIT,
        sort: str = "last_trade_timestamp",
        order: str = "DESC",
        include_nsfw: bool = False,
        complete: bool | None = False,
        creator: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "offset": offset,
            "limit": limit,
            "sort": sort,
            "order": order,
            "includeNsfw": str(include_nsfw).lower(),
        }
        if complete is not None:
            params["complete"] = str(complete).lower()
        if creator:
            params["creator"] = creator
        data = self.get_json("/coins", params=params)
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected /coins payload: {type(data)}")
        return data


def usd_market_cap(coin: dict[str, Any]) -> float | None:
    for key in ("usd_market_cap", "market_cap_usd"):
        v = coin.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def created_dt(coin: dict[str, Any]) -> datetime | None:
    ts = coin.get("created_timestamp")
    if ts is None:
        return None
    try:
        raw = float(ts)
        # Pump frontend uses ms epoch (~1.7e12). Seconds (~1.7e9) also appear
        # on some paths — dividing seconds by 1000 yields 1970 → age_s ~1e9.
        if raw >= 1e12:
            raw = raw / 1000.0  # milliseconds
        elif raw >= 1e14:
            raw = raw / 1e6  # microseconds (defensive)
        return datetime.fromtimestamp(raw, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def curve_progress_proxy(coin: dict[str, Any]) -> float | None:
    """1 - real_token_reserves / INITIAL_REAL_TOKEN_RESERVES (bonding progress)."""
    rt = coin.get("real_token_reserves")
    if rt is None:
        return None
    try:
        rt_i = int(rt)
    except (TypeError, ValueError):
        return None
    if INITIAL_REAL_TOKEN_RESERVES <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - (rt_i / INITIAL_REAL_TOKEN_RESERVES)))


def net_sol_curve_proxy(coin: dict[str, Any]) -> float | None:
    """real_sol_reserves lamports → SOL (proxy for net SOL on curve)."""
    rs = coin.get("real_sol_reserves")
    if rs is None:
        return None
    try:
        return float(rs) / 1_000_000_000.0
    except (TypeError, ValueError):
        return None


def coin_to_candidate_row(coin: dict[str, Any]) -> dict[str, Any] | None:
    mint = coin.get("mint")
    mc = usd_market_cap(coin)
    if not mint or mc is None:
        return None
    return {
        "mint": str(mint),
        "mc_usd": mc,
        "name": coin.get("name"),
        "symbol": coin.get("symbol"),
        "creator": coin.get("creator"),
        "created_timestamp": coin.get("created_timestamp"),
        "complete": coin.get("complete"),
        "total_supply": coin.get("total_supply"),
        "price_mean": None,
        "market_address": coin.get("bonding_curve") or coin.get("pool_address"),
        "bonding_curve": coin.get("bonding_curve"),
        "virtual_sol_reserves": coin.get("virtual_sol_reserves"),
        "virtual_token_reserves": coin.get("virtual_token_reserves"),
        "real_sol_reserves": coin.get("real_sol_reserves"),
        "real_token_reserves": coin.get("real_token_reserves"),
        "chain_id": coin.get("chain_id") or SOLANA_MAINNET_CHAIN_ID,
        "source": "pump.frontend-api-v3",
        "raw_coin": {k: coin.get(k) for k in (
            "mint", "name", "symbol", "creator", "created_timestamp", "complete",
            "usd_market_cap", "market_cap", "real_sol_reserves", "real_token_reserves",
            "virtual_sol_reserves", "virtual_token_reserves", "total_supply",
            "bonding_curve", "chain_id",
        )},
    }


def fetch_pump_mc_band(
    *,
    mc_lo: float = 8_000.0,
    mc_hi: float = 20_000.0,
    limit: int = DEFAULT_LIMIT,
    max_pages: int = DEFAULT_MAX_PAGES,
    sorts: tuple[str, ...] = ("last_trade_timestamp", "created_timestamp"),
    incomplete_only: bool = True,
    client: PumpFrontendClient | None = None,
) -> tuple[list[dict[str, Any]], PumpFrontendCallLog]:
    """Poll recent Pump coins; client-side filter MC ∈ [mc_lo, mc_hi], not graduated.

    ``marketCapMin/Max`` query params are unreliable on v3 (observed out-of-band
    rows) — always filter on ``usd_market_cap`` client-side.
    """
    owns = client is None
    client = client or PumpFrontendClient()
    try:
        by_mint: dict[str, dict[str, Any]] = {}
        complete_flag: bool | None = False if incomplete_only else None
        for sort in sorts:
            for page in range(max_pages):
                coins = client.list_coins(
                    offset=page * limit,
                    limit=limit,
                    sort=sort,
                    order="DESC",
                    include_nsfw=False,
                    complete=complete_flag,
                )
                if not coins:
                    break
                for coin in coins:
                    if incomplete_only and coin.get("complete") is True:
                        continue
                    mc = usd_market_cap(coin)
                    if mc is None or not (mc_lo <= mc <= mc_hi):
                        continue
                    row = coin_to_candidate_row(coin)
                    if row:
                        by_mint[row["mint"]] = row
                if len(coins) < limit:
                    break
        return list(by_mint.values()), client.log
    finally:
        if owns:
            client.close()


def fetch_creator_coins(
    creator: str,
    *,
    limit: int = 50,
    client: PumpFrontendClient | None = None,
    window_days: int | None = 30,
    max_pages: int = 20,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Coins attributed to ``creator`` (frontend filter).

    When ``window_days`` is set (default **30**, train/Q5b parity), paginate
    ``created_timestamp DESC`` until the oldest coin is older than the window
    or ``max_pages`` is hit. Single-page ``limit`` alone undercounts prolific
    creators vs Dune (observed prior7==prior30 with limit=50).
    """
    owns = client is None
    client = client or PumpFrontendClient()
    try:
        if window_days is None or window_days <= 0:
            return client.list_coins(
                offset=0,
                limit=limit,
                sort="created_timestamp",
                order="DESC",
                include_nsfw=True,
                complete=None,
                creator=creator,
            )
        as_of_dt = as_of if as_of is not None else datetime.now(timezone.utc)
        if as_of_dt.tzinfo is None:
            as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
        cutoff = as_of_dt.timestamp() - float(window_days) * 86400.0
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        page_limit = max(1, min(int(limit), 50))
        for page in range(max(1, int(max_pages))):
            coins = client.list_coins(
                offset=page * page_limit,
                limit=page_limit,
                sort="created_timestamp",
                order="DESC",
                include_nsfw=True,
                complete=None,
                creator=creator,
            )
            if not coins:
                break
            oldest_ts = None
            for c in coins:
                mint = c.get("mint")
                if mint and mint in seen:
                    continue
                if mint:
                    seen.add(str(mint))
                out.append(c)
                cts = created_dt(c)
                if cts is not None:
                    ts = cts.timestamp()
                    oldest_ts = ts if oldest_ts is None else min(oldest_ts, ts)
            if oldest_ts is not None and oldest_ts < cutoff:
                break
            if len(coins) < page_limit:
                break
        # Drop coins strictly older than window (keep borderline for q5b_agg filter)
        trimmed: list[dict[str, Any]] = []
        for c in out:
            cts = created_dt(c)
            if cts is None:
                trimmed.append(c)
                continue
            # keep up to window_days + small slack; q5b_agg applies strict < create_ts
            if cts.timestamp() >= cutoff - 86400:
                trimmed.append(c)
        return trimmed
    finally:
        if owns:
            client.close()


# Working trades path (probed 2026-10-02):
#   GET /trades/{url-encoded chainId}/{mint}?limit=&cursor=
# ``/trades/all/{mint|chainId}`` still 400 (Nest colon / regex). Prefer the
# two-segment route. Response: ``{trades, aggregates, cursor, source}``.
# Max ``limit`` per page ≈ 100; paginate via ``cursor`` (offset is a no-op).
TRADES_PAGE_MAX = 100


def fetch_trades_for_mint(
    mint: str,
    *,
    limit: int = 200,
    offset: int = 0,  # kept for call-site compat; unused (API ignores offset)
    client: PumpFrontendClient | None = None,
    chain_id: str = SOLANA_MAINNET_CHAIN_ID,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    """Fetch Pump frontend trades for ``mint`` (newest first), cursor-paginated.

    Returns a flat list of trade dicts (unwrapped from ``{trades: [...]}``).
    Raises ``RuntimeError`` on HTTP errors (caller may treat as gap).
    """
    from urllib.parse import quote

    del offset  # API offset does not advance pages; cursor does.
    owns = client is None
    client = client or PumpFrontendClient()
    try:
        path = f"/trades/{quote(chain_id, safe='')}/{mint}"
        out: list[dict[str, Any]] = []
        cursor: str | None = None
        page_limit = max(1, min(int(limit), TRADES_PAGE_MAX))
        for _ in range(max(1, int(max_pages))):
            params: dict[str, Any] = {"limit": page_limit}
            if cursor:
                params["cursor"] = cursor
            data = client.get_json(path, params=params)
            if isinstance(data, list):
                rows = [r for r in data if isinstance(r, dict)]
                cursor = None
            elif isinstance(data, dict):
                raw_rows = data.get("trades") or []
                rows = [r for r in raw_rows if isinstance(r, dict)]
                nxt = data.get("cursor")
                cursor = str(nxt) if nxt else None
            else:
                raise RuntimeError(f"Unexpected /trades payload: {type(data)}")
            out.extend(rows)
            if len(out) >= int(limit) or not rows or not cursor:
                break
        return out[: int(limit)]
    finally:
        if owns:
            client.close()
