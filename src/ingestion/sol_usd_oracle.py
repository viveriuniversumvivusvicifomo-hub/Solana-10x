"""SOL/USD oracle for live paper / capture (FROZEN preference = Pyth).

Order (live / as-of T0):
  1. Pyth Hermes — latest ``/v2/updates/price/latest`` or historical
     ``/v2/updates/price/{publish_time}`` when ``PYTH_API_KEY`` / ``HERMES_API_KEY``
     set (or Hermes is reachable without key). Product: ``SOL_USD_SOURCE=pyth``.
  2. CoinGecko — live simple/price, or ``/coins/solana/history?date=DD-MM-YYYY``
     for as-of (best-effort; daily granularity; quality ≤ MED).
  3. Jupiter Price API v3 (public) — live only (no as-of); MED quality.
  4. ``DEFAULT_SOL_USD_REF`` (train median ratio ≈103.11) — last resort.

USD parity target (Sinck): live ``amount_usd = sol_amt × asof_oracle`` MUST match
train feature scale. Evidence 2026-10-01: ``max_buy_usd/max_buy_sol`` median ≈117
(= real SOL/USD) — Dune amount_usd is NOT universally 6.6× inflated.
The diag ``buy60/net_sol≈681`` compares a 60s volume sum to a curve-capped ~85 SOL
net — NOT an oracle multiplier. Residual score gaps on incomplete recovery
(BZof/4M3g: 1 trade) are trade-count gaps, not an oracle bug.

Dune ``amount_usd`` vs live ``sol×oracle`` gap — options (hunt 2026-10-01):
  A) Re-train HistGB on Helius-scale USD features (SolModelos).
  B) Rebuild train USD legs with ``sol_amt × pyth_asof`` and re-fit (SolModelos).
  C) Documented factor ``APPLY_DUNE_HELIUS_USD_SCALE`` (DEFAULT OFF, ~6.6) —
     diagnostic escape hatch only; NOT ground truth; do not treat as parity.

Best match this turn (no retrain / no threshold change): prefer **Pyth as-of T0**
when ``PYTH_API_KEY``/``HERMES_API_KEY`` available; keep C OFF; score skip when
key present and source not pyth. Residual economic gap → A or B.

Capture protocol: ``sol_usd_source=="pyth"`` for HIGH; fallback ⇒ quality ≤ MED
(see cycle0/definicion-captura-v0.md). Never print API keys.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ingestion.env import load_dotenv
from ingestion.pump_constants import SOL_USD_SOURCE

# Train-median USD/SOL ratio used when all live oracles fail
DEFAULT_SOL_USD_REF = 103.11

# Diagnostics 2026-10-01: buy60/net_sol OOS≥0.99 median ≈681 vs train ref ~103 → ~6.6×
# Documented calibration only — OFF unless APPLY_DUNE_HELIUS_USD_SCALE=1
DUNE_HELIUS_USD_SCALE_FACTOR = 6.6

PYTH_SOL_USD_FEED_ID = "0xef0d8b6fda2ceba41da15d4095d1da392a0d2f8ed0c6c7bc0f4cfac8c280b56d"
HERMES_LATEST = "https://hermes.pyth.network/v2/updates/price/latest"
HERMES_AT = "https://hermes.pyth.network/v2/updates/price/{publish_time}"
JUPITER_PRICE_V3 = "https://api.jup.ag/price/v3"
COINGECKO_SIMPLE = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_HISTORY = "https://api.coingecko.com/api/v3/coins/solana/history"
WSOL_MINT = "So11111111111111111111111111111111111111112"

_CACHE: dict[str, Any] = {"price": None, "source": None, "fetched_at": 0.0}
_CACHE_TTL_S = 30.0
_ASOF_CACHE: dict[int, SolUsdQuote] = {}
_ASOF_CACHE_MAX = 256


@dataclass(frozen=True)
class SolUsdQuote:
    price: float
    source: str  # pyth | pyth_asof | jupiter | coingecko | coingecko_asof | ref_fallback | explicit
    publish_time: int | None = None

    @property
    def is_pyth(self) -> bool:
        return self.source in (SOL_USD_SOURCE, "pyth", "pyth_asof")


def _optional_pyth_key() -> str | None:
    load_dotenv()
    for key in ("PYTH_API_KEY", "HERMES_API_KEY"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return None


def prefer_pyth_source() -> bool:
    """Product frozen = Pyth. Env ``SOL_USD_SOURCE`` may override preference label only."""
    load_dotenv()
    src = (os.environ.get("SOL_USD_SOURCE") or SOL_USD_SOURCE).strip().lower()
    return src == "pyth" or src == SOL_USD_SOURCE


def apply_dune_helius_usd_scale_enabled() -> bool:
    """Opt-in Dune↔Helius USD multiplier. Default OFF — prefer oracle + trade recovery."""
    load_dotenv()
    raw = (os.environ.get("APPLY_DUNE_HELIUS_USD_SCALE") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def dune_helius_usd_scale_factor() -> float:
    """Calibration factor from diagnostics (~6.6). Override via ``DUNE_HELIUS_USD_SCALE``."""
    load_dotenv()
    raw = (os.environ.get("DUNE_HELIUS_USD_SCALE") or "").strip()
    if raw:
        try:
            v = float(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return float(DUNE_HELIUS_USD_SCALE_FACTOR)


def maybe_scale_usd(usd: float) -> float:
    """Apply Dune↔Helius scale only when flag ON; else identity."""
    if not apply_dune_helius_usd_scale_enabled():
        return float(usd)
    return float(usd) * dune_helius_usd_scale_factor()


def amount_usd_from_sol(sol_amt: float, sol_usd: float) -> float:
    """Live/train-oracle USD: ``sol_amt * sol_usd`` (parity target vs Dune amount_usd)."""
    return float(sol_amt) * float(sol_usd)


def _parse_pyth_parsed(body: dict[str, Any], *, source: str) -> SolUsdQuote | None:
    try:
        parsed = (body.get("parsed") or [None])[0]
        if not parsed:
            return None
        p = parsed.get("price") or {}
        raw = float(p["price"])
        expo = int(p.get("expo") if p.get("expo") is not None else -8)
        price = raw * (10 ** expo)
        if price <= 0:
            return None
        pub = p.get("publish_time")
        return SolUsdQuote(
            price=float(price),
            source=source,
            publish_time=int(pub) if pub is not None else None,
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def _from_pyth(client: httpx.Client, api_key: str | None) -> SolUsdQuote | None:
    headers = {"Accept": "application/json"}
    if api_key:
        # Hermes accepts Bearer on some tenants; X-API-KEY on others
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-KEY"] = api_key
    try:
        resp = client.get(
            HERMES_LATEST,
            params={"ids[]": PYTH_SOL_USD_FEED_ID},
            headers=headers,
            timeout=15.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        return _parse_pyth_parsed(resp.json(), source="pyth")
    except ValueError:
        return None


def _from_pyth_asof(
    client: httpx.Client,
    api_key: str | None,
    publish_time: int,
) -> SolUsdQuote | None:
    """Pyth Hermes historical: first update with publish_time >= requested unix s."""
    headers = {"Accept": "application/json"}
    if api_key:
        # Hermes accepts Bearer on some tenants; X-API-KEY on others
        headers["Authorization"] = f"Bearer {api_key}"
        headers["X-API-KEY"] = api_key
    url = HERMES_AT.format(publish_time=int(publish_time))
    try:
        resp = client.get(
            url,
            params={"ids[]": PYTH_SOL_USD_FEED_ID},
            headers=headers,
            timeout=20.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        return _parse_pyth_parsed(resp.json(), source="pyth_asof")
    except ValueError:
        return None


def _from_jupiter(client: httpx.Client) -> SolUsdQuote | None:
    try:
        resp = client.get(JUPITER_PRICE_V3, params={"ids": WSOL_MINT}, timeout=15.0)
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        body = resp.json()
        row = body.get(WSOL_MINT) or {}
        px = float(row["usdPrice"])
        if px <= 0:
            return None
        return SolUsdQuote(price=px, source="jupiter")
    except (KeyError, TypeError, ValueError):
        return None


def _from_coingecko(client: httpx.Client) -> SolUsdQuote | None:
    try:
        resp = client.get(
            COINGECKO_SIMPLE,
            params={"ids": "solana", "vs_currencies": "usd"},
            timeout=15.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        px = float((resp.json().get("solana") or {})["usd"])
        if px <= 0:
            return None
        return SolUsdQuote(price=px, source="coingecko")
    except (KeyError, TypeError, ValueError):
        return None


def _from_coingecko_asof(client: httpx.Client, publish_time: int) -> SolUsdQuote | None:
    """Daily as-of via CoinGecko history (UTC date of ``publish_time``). Best effort."""
    dt = datetime.fromtimestamp(int(publish_time), tz=timezone.utc)
    date_s = dt.strftime("%d-%m-%Y")
    try:
        resp = client.get(
            COINGECKO_HISTORY,
            params={"date": date_s, "localization": "false"},
            timeout=25.0,
        )
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    try:
        md = resp.json().get("market_data") or {}
        px = float((md.get("current_price") or {})["usd"])
        if px <= 0:
            return None
        return SolUsdQuote(
            price=px,
            source="coingecko_asof",
            publish_time=int(publish_time),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _ts_unix(as_of: datetime | int | float) -> int:
    if isinstance(as_of, datetime):
        dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        return int(dt.astimezone(timezone.utc).timestamp())
    return int(as_of)


def fetch_sol_usd(
    *,
    force_refresh: bool = False,
    allow_network: bool = True,
    fallback: float = DEFAULT_SOL_USD_REF,
) -> SolUsdQuote:
    """Resolve live SOL/USD. Cached ``_CACHE_TTL_S``. Never raises on network failure.

    Prefers Pyth (product frozen). Jupiter/CoinGecko are MED-quality fallbacks when
    Hermes is unreachable (e.g. 401 without API key from some egress IPs).
    """
    now = time.monotonic()
    if (
        not force_refresh
        and _CACHE["price"] is not None
        and (now - float(_CACHE["fetched_at"])) < _CACHE_TTL_S
    ):
        return SolUsdQuote(
            price=float(_CACHE["price"]),
            source=str(_CACHE["source"]),
            publish_time=_CACHE.get("publish_time"),
        )

    quote: SolUsdQuote | None = None
    if allow_network:
        with httpx.Client() as client:
            key = _optional_pyth_key()
            # Always try Pyth first when prefer_pyth (product)
            if prefer_pyth_source():
                quote = _from_pyth(client, key)
            # Live fallbacks: CoinGecko before Jupiter so as-of path can share CG;
            # but for live, Jupiter is often fresher — keep Jupiter then CG (legacy).
            if quote is None:
                quote = _from_jupiter(client)
            if quote is None:
                quote = _from_coingecko(client)
            # If prefer_pyth was False somehow, still attempt Pyth last
            if quote is None and not prefer_pyth_source():
                quote = _from_pyth(client, key)

    if quote is None:
        quote = SolUsdQuote(price=float(fallback), source="ref_fallback")

    _CACHE["price"] = quote.price
    _CACHE["source"] = quote.source
    _CACHE["publish_time"] = quote.publish_time
    _CACHE["fetched_at"] = now
    return quote


def fetch_sol_usd_asof(
    as_of: datetime | int | float,
    *,
    allow_network: bool = True,
    fallback: float = DEFAULT_SOL_USD_REF,
    max_skew_s: int = 86400,
) -> SolUsdQuote:
    """SOL/USD as-of ``as_of`` (unix s or aware datetime) for historical T0 parity.

    Prefer Pyth Hermes historical; else CoinGecko daily history; else live oracle
    (tagged non-asof — caller should treat quality ≤ MED) or ``fallback``.
    """
    ts = _ts_unix(as_of)
    cached = _ASOF_CACHE.get(ts)
    if cached is not None:
        return cached

    quote: SolUsdQuote | None = None
    if allow_network:
        with httpx.Client() as client:
            key = _optional_pyth_key()
            quote = _from_pyth_asof(client, key, ts)
            if quote is not None and quote.publish_time is not None:
                skew = abs(int(quote.publish_time) - ts)
                if skew > max_skew_s:
                    # Too far from requested T0 — treat as miss
                    quote = None
            if quote is None:
                quote = _from_coingecko_asof(client, ts)

    if quote is None:
        # Best effort: live price is wrong for historical T0; tag clearly
        live = fetch_sol_usd(allow_network=allow_network, fallback=fallback)
        quote = SolUsdQuote(
            price=float(live.price),
            source=f"{live.source}_live_not_asof",
            publish_time=live.publish_time,
        )

    if len(_ASOF_CACHE) >= _ASOF_CACHE_MAX:
        # drop an arbitrary old entry
        _ASOF_CACHE.pop(next(iter(_ASOF_CACHE)), None)
    _ASOF_CACHE[ts] = quote
    return quote


def resolve_sol_usd(
    explicit: float | None = None,
    *,
    allow_network: bool = True,
    fallback: float = DEFAULT_SOL_USD_REF,
    as_of: datetime | int | float | None = None,
) -> SolUsdQuote:
    """If ``explicit`` > 0 use it as ``explicit`` source; else as-of or live oracle chain."""
    if explicit is not None and float(explicit) > 0:
        # Caller-forced (tests / dry fixtures) — tag as explicit, not pyth
        return SolUsdQuote(price=float(explicit), source="explicit")
    if as_of is not None:
        return fetch_sol_usd_asof(
            as_of, allow_network=allow_network, fallback=fallback
        )
    return fetch_sol_usd(allow_network=allow_network, fallback=fallback)


def clear_sol_usd_cache() -> None:
    _CACHE["price"] = None
    _CACHE["source"] = None
    _CACHE["publish_time"] = None
    _CACHE["fetched_at"] = 0.0
    _ASOF_CACHE.clear()


def is_pyth_source(source: str | None) -> bool:
    src = (source or "").strip().lower()
    return src in ("pyth", "pyth_asof", SOL_USD_SOURCE)


def require_pyth_asof(
    as_of: datetime | int | float,
    *,
    allow_network: bool = True,
) -> SolUsdQuote | None:
    """Force Pyth Hermes as-of for scoring USD legs.

    Returns None when Hermes unavailable (caller → capture_quality MED/LOW + skip score).
    Does **not** fall through to CoinGecko/Jupiter — product HIGH requires Pyth.
    """
    if not allow_network:
        return None
    load_dotenv()
    ts = _ts_unix(as_of)
    key = _optional_pyth_key()
    with httpx.Client() as client:
        q = _from_pyth_asof(client, key, ts)
        if q is not None and q.price > 0:
            return q
        # One retry without key if key path 401'd, or with key if public failed
        if key:
            q2 = _from_pyth_asof(client, None, ts)
            if q2 is not None and q2.price > 0:
                return q2
    return None


def resolve_sol_usd_for_scoring(
    as_of: datetime | int | float | None,
    *,
    allow_network: bool = True,
    require_pyth: bool = True,
) -> tuple[SolUsdQuote | None, str]:
    """USD quote for feature reconstruction / paper scoring.

    Path A (live≡train fastest without blind 6.6×):
      amount_usd = sol_amt × pyth_asof(t0)
    which matches Dune ``amount_usd`` when Dune sol_amt is true SOL and
    amount_usd ≈ sol × spot (evidence: max_buy_usd/max_buy_sol ≈ 117).

    When require_pyth=True and Hermes fails → (None, reason) — do not score.

    When require_pyth=False (no PYTH/HERMES key): prefer pyth_asof if reachable,
    then CoinGecko as-of, then Jupiter live (tagged ``*_live_not_asof``), then ref.
    """
    if as_of is None:
        if require_pyth:
            return None, "missing_as_of_for_pyth"
        q = fetch_sol_usd(allow_network=allow_network)
        return q, q.source
    if require_pyth:
        q = require_pyth_asof(as_of, allow_network=allow_network)
        if q is None:
            return None, "pyth_asof_unavailable"
        return q, q.source
    q = fetch_sol_usd_asof(as_of, allow_network=allow_network)
    return q, q.source


def amount_usd_dune_compatible(sol_amt: float, sol_usd: float) -> float:
    """Dune-compatible USD leg: sol_amt × oracle (Pyth as-of at T0).

    Same formula as train when Dune amount_usd/sol_amt ≈ spot. Not a 6.6× scale.
    """
    return float(sol_amt) * float(sol_usd)


# Recalib plan (SolDatos → SolModelos). Path A implemented in live reconstruct.
USD_RECALIB_PLAN = {
    "chosen": "A_live_sol_x_pyth_asof_match_dune_semantics",
    "A": "Live/reconstruct: amount_usd=sol_amt*pyth_asof; firmas compare vs Dune amount_usd",
    "B": "SolModelos: rebuild train USD legs with sol*pyth_asof + re-fit HistGB",
    "C": "Documented per-mint factor (NOT blind 6.6×) — last resort",
    "rejected": "APPLY_DUNE_HELIUS_USD_SCALE blind 6.6×",
}

