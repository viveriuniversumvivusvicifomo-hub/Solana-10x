"""Helius Enhanced Transactions (legacy REST) — read-only trade history.

Used by paper_live hybrid enrich (Pump discover + Helius ≤T0 trades).
Streams / Parsed Events remain OFF. Never log the API key.

Pagination (pre-T0): newest→oldest until blockTime < floor, create signature
found, or empty page. Cap with a high safe max_pages but stop early past T0.
Retry/backoff on 429; do not drop partial pages silently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx

from ingestion.env import require_helius_api_key

# Free plan: stay well under Enhanced RPS (DAS/Enhanced column is tighter than RPC)
DEFAULT_MIN_INTERVAL_S = 0.25
DEFAULT_LIMIT = 100
DEFAULT_MAX_PAGES_PRE_T0 = 80
BASE_API = "https://api.helius.xyz"


class HeliusDeadlineExceeded(RuntimeError):
    """Raised when a live wall-clock deadline is hit mid-pagination / before a call."""


@dataclass
class HeliusEnhancedLog:
    n_calls: int = 0
    n_retries_429: int = 0
    status_codes: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_calls": self.n_calls,
            "n_retries_429": self.n_retries_429,
            "status_codes": list(self.status_codes)[-20:],
        }


@dataclass
class TxPageFetch:
    """Result of paginating Enhanced history (may be partial after 429 exhaustion)."""

    txs: list[dict[str, Any]]
    pages: int = 0
    stopped_reason: str = ""
    reached_floor: bool = False
    found_create_sig: bool = False
    partial: bool = False
    address: str = ""


class HeliusEnhanced:
    """GET /v0/addresses/{address}/transactions (Enhanced Transactions history)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: float = 45.0,
        max_calls: int | None = None,
        max_retries_429: int = 10,
        max_backoff_s: float = 60.0,
    ) -> None:
        self._api_key = api_key or require_helius_api_key()
        self._min_interval_s = min_interval_s
        self._max_calls = max_calls
        self._max_retries_429 = max_retries_429
        self._max_backoff_s = float(max_backoff_s)
        self._last_call = 0.0
        self._client = httpx.Client(timeout=timeout_s)
        self.log = HeliusEnhancedLog()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HeliusEnhanced:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def n_calls(self) -> int:
        return self.log.n_calls

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _budget(self) -> None:
        if self._max_calls is not None and self.log.n_calls >= self._max_calls:
            raise RuntimeError(
                f"Helius Enhanced max_calls={self._max_calls} reached (paper_live budget)"
            )

    def _check_deadline(self, deadline_mono: float | None) -> None:
        if deadline_mono is not None and time.monotonic() >= float(deadline_mono):
            raise HeliusDeadlineExceeded("Helius Enhanced live mint deadline exceeded")

    def _sleep_backoff(self, sleep_s: float, *, deadline_mono: float | None = None) -> None:
        """Sleep capped by max_backoff_s; abort early if deadline hits."""
        sleep_s = min(float(sleep_s), self._max_backoff_s)
        if sleep_s <= 0:
            return
        if deadline_mono is None:
            time.sleep(sleep_s)
            return
        end = time.monotonic() + sleep_s
        while True:
            self._check_deadline(deadline_mono)
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.25, remaining))

    def get_transactions_for_address(
        self,
        address: str,
        *,
        limit: int = DEFAULT_LIMIT,
        before_signature: str | None = None,
        type_filter: str | None = None,
        deadline_mono: float | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first page of Enhanced txs for an address (mint or bonding curve).

        Retries on HTTP 429 with exponential backoff. Raises after retries exhausted.
        ``deadline_mono`` (time.monotonic) aborts before call / during backoff.
        """
        self._check_deadline(deadline_mono)
        self._budget()
        params: dict[str, Any] = {
            "api-key": self._api_key,
            "limit": max(1, min(int(limit), 100)),
        }
        if before_signature:
            params["before-signature"] = before_signature
        if type_filter:
            params["type"] = type_filter
        path = f"{BASE_API}/v0/addresses/{quote(address, safe='')}/transactions"
        last_err: Exception | None = None
        for attempt in range(max(1, self._max_retries_429)):
            self._check_deadline(deadline_mono)
            self._throttle()
            resp = self._client.get(path, params=params)
            self.log.n_calls += 1
            self.log.status_codes.append(resp.status_code)
            if resp.status_code == 429:
                self.log.n_retries_429 += 1
                ra = resp.headers.get("Retry-After")
                try:
                    sleep_s = float(ra) if ra is not None else min(60.0, 1.0 * (2**attempt))
                except ValueError:
                    sleep_s = min(30.0, 0.75 * (2**attempt))
                self._sleep_backoff(max(1.0, sleep_s), deadline_mono=deadline_mono)
                last_err = RuntimeError("Helius Enhanced HTTP 429")
                continue
            if resp.status_code == 404:
                # No events in search window — empty page (not fatal)
                return []
            if resp.status_code >= 500:
                self._sleep_backoff(min(10.0, 0.5 * (2**attempt)), deadline_mono=deadline_mono)
                last_err = RuntimeError(f"Helius Enhanced HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            body = resp.json()
            if not isinstance(body, list):
                raise RuntimeError(
                    f"Unexpected Enhanced response type: {type(body).__name__}"
                )
            return body
        raise last_err or RuntimeError("Helius Enhanced failed after retries")


    def get_transactions_by_signatures(
        self,
        signatures: list[str],
        *,
        chunk_size: int = 100,
        deadline_mono: float | None = None,
    ) -> list[dict[str, Any]]:
        """POST /v0/transactions — parse Enhanced txs by signature list (RPC window recovery)."""
        out: list[dict[str, Any]] = []
        url = f"{BASE_API}/v0/transactions/"
        for i in range(0, len(signatures), max(1, chunk_size)):
            chunk = [str(s) for s in signatures[i : i + chunk_size] if s]
            if not chunk:
                continue
            last_err: Exception | None = None
            for attempt in range(max(1, self._max_retries_429)):
                self._check_deadline(deadline_mono)
                self._budget()
                self._throttle()
                resp = self._client.post(url, params={"api-key": self._api_key}, json={"transactions": chunk})
                self.log.n_calls += 1
                self.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    self.log.n_retries_429 += 1
                    ra = resp.headers.get("Retry-After")
                    try:
                        sleep_s = float(ra) if ra is not None else min(60.0, 1.0 * (2**attempt))
                    except ValueError:
                        sleep_s = min(30.0, 0.75 * (2**attempt))
                    self._sleep_backoff(max(1.0, sleep_s), deadline_mono=deadline_mono)
                    last_err = RuntimeError("Helius Enhanced parse-by-sig HTTP 429")
                    continue
                if resp.status_code >= 500:
                    self._sleep_backoff(
                        min(10.0, 0.5 * (2**attempt)), deadline_mono=deadline_mono
                    )
                    last_err = RuntimeError(f"Helius Enhanced parse-by-sig HTTP {resp.status_code}")
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, list):
                    out.extend(body)
                break
            else:
                raise last_err or RuntimeError("Helius Enhanced parse-by-sig failed")
        return out

    def fetch_transactions_until(
        self,
        address: str,
        *,
        min_timestamp: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES_PRE_T0,
        limit: int = DEFAULT_LIMIT,
        type_filter: str | None = None,
        stop_signature: str | None = None,
        keep_partial_on_error: bool = True,
        deadline_mono: float | None = None,
    ) -> TxPageFetch:
        """Paginate newest→oldest until timestamp < min_timestamp, create sig,
        empty page, or pages exhausted.

        ``min_timestamp`` is unix seconds (inclusive floor — stop when page txs
        are older). On 429 exhaustion mid-pagination, returns partial pages when
        ``keep_partial_on_error`` (does not silently drop to empty).
        ``deadline_mono`` stops pagination early (partial kept when available).
        """
        out: list[dict[str, Any]] = []
        before: str | None = None
        pages = 0
        reached_floor = False
        found_create = False
        stopped = "max_pages"
        stop_sig = (stop_signature or "").strip() or None
        for _ in range(max(1, int(max_pages))):
            try:
                self._check_deadline(deadline_mono)
                page = self.get_transactions_for_address(
                    address,
                    limit=limit,
                    before_signature=before,
                    type_filter=type_filter,
                    deadline_mono=deadline_mono,
                )
            except HeliusDeadlineExceeded:
                if keep_partial_on_error and out:
                    return TxPageFetch(
                        txs=out,
                        pages=pages,
                        stopped_reason="deadline",
                        reached_floor=reached_floor,
                        found_create_sig=found_create,
                        partial=True,
                        address=address,
                    )
                raise
            except Exception:
                if keep_partial_on_error and out:
                    return TxPageFetch(
                        txs=out,
                        pages=pages,
                        stopped_reason="partial_429",
                        reached_floor=reached_floor,
                        found_create_sig=found_create,
                        partial=True,
                        address=address,
                    )
                raise
            pages += 1
            if not page:
                stopped = "empty"
                break
            out.extend(page)
            oldest_ts = None
            for tx in page:
                if stop_sig and str(tx.get("signature") or "") == stop_sig:
                    found_create = True
                ts = tx.get("timestamp")
                if ts is None:
                    continue
                try:
                    tsi = int(ts)
                except (TypeError, ValueError):
                    continue
                oldest_ts = tsi if oldest_ts is None else min(oldest_ts, tsi)
            if found_create:
                stopped = "create_sig"
                break
            last_sig = page[-1].get("signature")
            if not last_sig:
                stopped = "empty"
                break
            before = str(last_sig)
            if (
                min_timestamp is not None
                and oldest_ts is not None
                and oldest_ts < int(min_timestamp)
            ):
                reached_floor = True
                stopped = "floor"
                break
            if len(page) < limit:
                stopped = "short_page"
                break
        return TxPageFetch(
            txs=out,
            pages=pages,
            stopped_reason=stopped,
            reached_floor=reached_floor,
            found_create_sig=found_create,
            partial=False,
            address=address,
        )

    def iter_transactions_until(
        self,
        address: str,
        *,
        min_timestamp: int | None = None,
        max_pages: int = DEFAULT_MAX_PAGES_PRE_T0,
        limit: int = DEFAULT_LIMIT,
        type_filter: str | None = None,
        stop_signature: str | None = None,
        keep_partial_on_error: bool = True,
        deadline_mono: float | None = None,
    ) -> list[dict[str, Any]]:
        """Paginate newest→oldest until floor / create / empty / max_pages.

        Backward-compatible list return. Prefer ``fetch_transactions_until`` for
        stop-reason / partial metadata.
        """
        result = self.fetch_transactions_until(
            address,
            min_timestamp=min_timestamp,
            max_pages=max_pages,
            limit=limit,
            type_filter=type_filter,
            stop_signature=stop_signature,
            keep_partial_on_error=keep_partial_on_error,
            deadline_mono=deadline_mono,
        )
        return result.txs


def merge_tx_lists(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe Enhanced txs by signature (first wins); stable newest-first approx."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for lst in lists:
        for tx in lst:
            sig = str(tx.get("signature") or "")
            if not sig or sig in seen:
                continue
            seen.add(sig)
            out.append(tx)
    return out


def min_ts_floor_pre_t0(t0: datetime, create_ts: datetime | None) -> int:
    """Unix floor for Enhanced pagination (create−5s, else T0−48h)."""
    if create_ts is not None:
        cts = create_ts if create_ts.tzinfo else create_ts.replace(tzinfo=timezone.utc)
        return int(cts.timestamp()) - 5
    t0a = t0 if t0.tzinfo else t0.replace(tzinfo=timezone.utc)
    return int(t0a.timestamp()) - 172800


def filter_txs_le_t0(txs: list[dict[str, Any]], t0: datetime) -> list[dict[str, Any]]:
    """Anti look-ahead: keep Enhanced txs with timestamp ≤ t0."""
    t0a = t0 if t0.tzinfo else t0.replace(tzinfo=timezone.utc)
    t0_ts = int(t0a.timestamp())
    kept: list[dict[str, Any]] = []
    for tx in txs:
        ts = tx.get("timestamp")
        if ts is None:
            continue
        try:
            if int(ts) <= t0_ts:
                kept.append(tx)
        except (TypeError, ValueError):
            continue
    return kept


def fetch_pre_t0_enhanced_txs(
    client: HeliusEnhanced,
    mint: str,
    *,
    t0: datetime,
    create_ts: datetime | None = None,
    bonding_curve: str | None = None,
    max_pages: int = DEFAULT_MAX_PAGES_PRE_T0,
    limit: int = DEFAULT_LIMIT,
    create_signature: str | None = None,
    deadline_mono: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect ALL Enhanced txs with block_time ≤ t0 (mint + bonding-curve merge).

    SolDatos canonical helper for paper_live enrich / historical replay.

    - Prefer bonding-curve PDA first (Pump pre-grad trades live on the curve).
    - Paginate newest→oldest until floor / create sig / empty (max_pages = safety cap).
    - Retry/backoff on 429 inside ``client``; keep partial pages (do not silent-empty).
    - Filter strictly ``timestamp ≤ t0`` (anti look-ahead).

    Returns ``(txs_le_t0, gaps)`` diagnostic strings (no secrets).
    """
    gaps: list[str] = []
    min_ts = min_ts_floor_pre_t0(t0, create_ts)
    bc_pages = max(3, min(int(max_pages), 20))
    mint_pages = max(3, int(max_pages))
    lists: list[list[dict[str, Any]]] = []

    def _one(address: str, pages: int, label: str) -> None:
        if not address:
            return
        try:
            res = client.fetch_transactions_until(
                address,
                min_timestamp=min_ts,
                max_pages=pages,
                limit=limit,
                stop_signature=create_signature,
                keep_partial_on_error=True,
                deadline_mono=deadline_mono,
            )
            lists.append(list(res.txs))
            gaps.append(
                f"helius_{label}:pages={res.pages} stop={res.stopped_reason}"
                f"{' partial' if res.partial else ''}"
            )
            if res.partial:
                gaps.append(f"helius_{label}_partial_kept n={len(res.txs)}")
        except HeliusDeadlineExceeded as e:
            gaps.append(f"helius_{label}_deadline: {str(e)[:80]}")
        except Exception as e:  # noqa: BLE001
            gaps.append(f"helius_{label}_fetch_failed: {str(e)[:120]}")

    if bonding_curve:
        _one(str(bonding_curve), bc_pages, "bc")
    _one(mint, mint_pages, "mint")

    merged = merge_tx_lists(*lists) if lists else []
    kept = filter_txs_le_t0(merged, t0)
    gaps.append(f"helius_merged n={len(merged)} le_t0={len(kept)} floor={min_ts}")
    return kept, gaps


def smoke_one_page(address: str, *, limit: int = 3) -> dict[str, Any]:
    """1 Enhanced call for health — returns counts only (no key)."""
    with HeliusEnhanced(max_calls=1) as client:
        page = client.get_transactions_for_address(address, limit=limit)
    sources: dict[str, int] = {}
    types: dict[str, int] = {}
    for tx in page:
        s = str(tx.get("source") or "?")
        t = str(tx.get("type") or "?")
        sources[s] = sources.get(s, 0) + 1
        types[t] = types.get(t, 0) + 1
    return {
        "n": len(page),
        "sources": sources,
        "types": types,
        "api": "helius.enhanced.v0.addresses.transactions",
    }



def _tx_involves_mint(tx: dict[str, Any], mint: str) -> bool:
    """True if Enhanced tx touches ``mint`` (token transfer or balance change)."""
    for t in tx.get("tokenTransfers") or []:
        if str(t.get("mint") or "") == mint:
            return True
    for ad in tx.get("accountData") or []:
        if ad.get("account") == mint:
            return True
        for c in ad.get("tokenBalanceChanges") or []:
            if str(c.get("mint") or "") == mint:
                return True
    return False


def fetch_create_to_t0_txs(
    client: HeliusEnhanced,
    mint: str,
    *,
    t0: datetime,
    create_ts: datetime | None = None,
    bonding_curve: str | None = None,
    rpc: Any | None = None,
    max_pages_enhanced: int = DEFAULT_MAX_PAGES_PRE_T0,
    max_pages_rpc: int = 120,
    prefer_rpc_when_age_s: float = 120.0,
    deadline_mono: float | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Create→T0 recovery: BC Enhanced + optional RPC sig-window (mint then BC).

    Historical age≈0 snipers bury create under post-T0 spam on the mint address.
    Prefer bonding-curve Enhanced (few txs) and RPC ``getSignaturesForAddress``
    on **bonding_curve first**, then mint, for [create−5s, t0].
    """
    gaps: list[str] = []
    t0a = t0 if t0.tzinfo else t0.replace(tzinfo=timezone.utc)
    create_a = None
    if create_ts is not None:
        create_a = create_ts if create_ts.tzinfo else create_ts.replace(tzinfo=timezone.utc)

    age_s = (t0a - create_a).total_seconds() if create_a is not None else None
    # Enhanced: always BC-first; for tiny age use modest mint pages (RPC will fill)
    enh_pages = int(max_pages_enhanced)
    if age_s is not None and age_s <= prefer_rpc_when_age_s:
        enh_pages = max(5, min(enh_pages, 20))

    txs, egaps = fetch_pre_t0_enhanced_txs(
        client,
        mint,
        t0=t0a,
        create_ts=create_a,
        bonding_curve=bonding_curve,
        max_pages=enh_pages,
        deadline_mono=deadline_mono,
    )
    gaps.extend(egaps)
    mode = "enhanced_pre_t0"

    if deadline_mono is not None and time.monotonic() >= float(deadline_mono):
        gaps.append("create_to_t0_deadline_before_rpc")
        kept = filter_txs_le_t0(txs, t0a)
        gaps.append(f"create_to_t0 mode={mode} n_raw={len(txs)} le_t0={len(kept)}")
        return kept, gaps

    need_rpc = rpc is not None and create_a is not None and (
        len(txs) < 5 or (age_s is not None and age_s <= prefer_rpc_when_age_s)
    )
    if need_rpc:
        hi = int(t0a.timestamp())
        lo = int(create_a.timestamp()) - 5
        seen = {str(t.get("signature") or "") for t in txs}
        for label, addr in (("bc", bonding_curve), ("mint", mint)):
            if not addr:
                continue
            try:
                sigs, reason = rpc.collect_signatures_in_window(
                    str(addr),
                    max_block_time=hi,
                    min_block_time=lo,
                    max_pages=int(max_pages_rpc),
                    page_limit=1000,
                )
            except Exception as e:  # noqa: BLE001
                gaps.append(f"rpc_{label}_failed:{str(e)[:100]}")
                continue
            if not sigs:
                gaps.append(f"rpc_{label}_empty:{reason}")
                continue
            sig_list = [str(s["signature"]) for s in sigs if s.get("signature")]
            try:
                extra = client.get_transactions_by_signatures(sig_list, deadline_mono=deadline_mono)
            except Exception as e:  # noqa: BLE001
                gaps.append(f"rpc_{label}_parse_failed:{str(e)[:100]}")
                continue
            n_new = 0
            for t in extra:
                sig = str(t.get("signature") or "")
                if sig and sig not in seen:
                    txs.append(t)
                    seen.add(sig)
                    n_new += 1
            gaps.append(f"rpc_{label}_window n_sigs={len(sig_list)} new={n_new} pages_reason={reason}")
            mode = "enhanced+rpc_sig_window"
            # Always also try mint after BC (BZof/4M3g: BC short_page alone under-recovers)

    # Age≈0 snipers: jump via create signature slot (±radius) — mint pagination
    # cannot reach create under post-T0 spam; BC alone misses post-grad AMM buys.
    if deadline_mono is not None and time.monotonic() >= float(deadline_mono):
        gaps.append("create_to_t0_deadline_before_slot")
        kept = filter_txs_le_t0(txs, t0a)
        gaps.append(f"create_to_t0 mode={mode} n_raw={len(txs)} le_t0={len(kept)}")
        return kept, gaps

    need_slot = (
        rpc is not None
        and create_a is not None
        and age_s is not None
        and age_s <= prefer_rpc_when_age_s
    )
    if need_slot:
        create_sig_for_slot = None
        # Prefer an already-fetched CREATE tx signature involving this mint
        for t in txs:
            if str(t.get("type") or "").upper() == "CREATE" and t.get("signature"):
                create_sig_for_slot = str(t.get("signature"))
                break
        if create_sig_for_slot is None:
            # fall back: any le_t0 sig we already have
            for t in txs:
                if t.get("signature"):
                    create_sig_for_slot = str(t.get("signature"))
                    break
        if create_sig_for_slot:
            try:
                from ingestion.helius_rpc import collect_signatures_around_slot

                txr = rpc.call(
                    "getTransaction",
                    [
                        create_sig_for_slot,
                        {
                            "encoding": "json",
                            "maxSupportedTransactionVersion": 0,
                        },
                    ],
                )
                slot = (txr.result or {}).get("slot") if txr.result else None
            except Exception as e:  # noqa: BLE001
                gaps.append(f"slot_anchor_failed:{str(e)[:100]}")
                slot = None
            if slot is not None:
                try:
                    sig_list, sgaps = collect_signatures_around_slot(
                        rpc, center_slot=int(slot), slot_radius=1
                    )
                    gaps.extend(sgaps)
                except Exception as e:  # noqa: BLE001
                    gaps.append(f"slot_window_failed:{str(e)[:100]}")
                    sig_list = []
                if sig_list:
                    # Filter to mint-related via Enhanced parse (chunked)
                    try:
                        extra = client.get_transactions_by_signatures(sig_list, deadline_mono=deadline_mono)
                    except Exception as e:  # noqa: BLE001
                        gaps.append(f"slot_parse_failed:{str(e)[:100]}")
                        extra = []
                    seen = {str(t.get("signature") or "") for t in txs}
                    n_new = 0
                    for t in extra:
                        if not _tx_involves_mint(t, mint):
                            continue
                        sig = str(t.get("signature") or "")
                        if sig and sig not in seen:
                            txs.append(t)
                            seen.add(sig)
                            n_new += 1
                    gaps.append(
                        f"slot_window slot={slot} n_sigs={len(sig_list)} mint_new={n_new}"
                    )
                    mode = "enhanced+rpc_sig_window+slot"

    kept = filter_txs_le_t0(txs, t0a)
    gaps.append(f"create_to_t0 mode={mode} n_raw={len(txs)} le_t0={len(kept)}")
    return kept, gaps

