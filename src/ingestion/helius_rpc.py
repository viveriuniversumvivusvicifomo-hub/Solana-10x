"""Cliente RPC Helius mínimo (lectura). Rate-limit conservador para plan free.

No streams hasta presupuesto OK. No loguear la API key.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from ingestion.env import require_helius_api_key

# Free plan: 10 RPS — nos quedamos muy por debajo
DEFAULT_MIN_INTERVAL_S = 0.15  # ~6.6 RPS max


@dataclass
class RpcResult:
    result: Any
    latency_ms: float


class HeliusRpc:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        timeout_s: float = 30.0,
    ) -> None:
        self._api_key = api_key or require_helius_api_key()
        self._url = f"https://mainnet.helius-rpc.com/?api-key={self._api_key}"
        self._min_interval_s = min_interval_s
        self._last_call = 0.0
        self._client = httpx.Client(timeout=timeout_s)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HeliusRpc:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def call(self, method: str, params: list[Any] | None = None) -> RpcResult:
        self._throttle()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or []}
        t0 = time.monotonic()
        resp = self._client.post(self._url, json=payload)
        latency_ms = (time.monotonic() - t0) * 1000
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"RPC {method} error: {body['error']}")
        return RpcResult(result=body.get("result"), latency_ms=latency_ms)

    def get_health(self) -> str:
        """getHealth → 'ok' en nodos sanos."""
        r = self.call("getHealth")
        return str(r.result)

    def get_account_info(
        self,
        pubkey: str,
        *,
        encoding: str = "base64",
        commitment: str = "confirmed",
    ) -> dict[str, Any] | None:
        r = self.call(
            "getAccountInfo",
            [pubkey, {"encoding": encoding, "commitment": commitment}],
        )
        return r.result

    def get_slot(self, *, commitment: str = "confirmed") -> int:
        r = self.call("getSlot", [{"commitment": commitment}])
        return int(r.result)

    def get_signatures_for_address(
        self,
        address: str,
        *,
        limit: int = 1000,
        before: str | None = None,
        until: str | None = None,
    ) -> list[dict[str, Any]]:
        """Newest-first signature page (Solana JSON-RPC)."""
        opts: dict[str, Any] = {"limit": max(1, min(int(limit), 1000))}
        if before:
            opts["before"] = before
        if until:
            opts["until"] = until
        r = self.call("getSignaturesForAddress", [address, opts])
        return list(r.result or [])

    def collect_signatures_in_window(
        self,
        address: str,
        *,
        max_block_time: int,
        min_block_time: int | None = None,
        max_pages: int = 40,
        page_limit: int = 1000,
    ) -> tuple[list[dict[str, Any]], str]:
        """Paginate newest→oldest until ``blockTime < min_block_time`` or pages exhausted.

        Returns (sigs with blockTime in [min_block_time, max_block_time], reason).
        Used to reach create→T0 when Enhanced mint history is buried under post-T0 spam.
        """
        out: list[dict[str, Any]] = []
        before: str | None = None
        reason = "ok"
        lo = int(min_block_time) if min_block_time is not None else None
        hi = int(max_block_time)
        for page_i in range(max(1, max_pages)):
            try:
                page = self.get_signatures_for_address(
                    address, limit=page_limit, before=before
                )
            except RuntimeError as e:
                reason = f"rpc_error@{page_i}:{str(e)[:80]}"
                break
            if not page:
                reason = f"empty@{page_i}"
                break
            oldest_bt: int | None = None
            for s in page:
                bt = s.get("blockTime")
                if bt is None:
                    continue
                try:
                    bti = int(bt)
                except (TypeError, ValueError):
                    continue
                oldest_bt = bti if oldest_bt is None else min(oldest_bt, bti)
                if bti <= hi and (lo is None or bti >= lo):
                    out.append(s)
            before = str(page[-1].get("signature") or "") or None
            if not before:
                reason = f"no_sig@{page_i}"
                break
            if oldest_bt is not None and lo is not None and oldest_bt < lo:
                reason = f"reached_floor@page{page_i + 1}"
                break
            if oldest_bt is not None and oldest_bt <= hi and len(page) < page_limit:
                reason = f"short_reached@page{page_i + 1}"
                break
            if len(page) < page_limit:
                reason = f"short@page{page_i + 1}"
                break
        else:
            reason = f"max_pages={max_pages}"
        return out, reason



    def get_block_signatures(
        self,
        slot: int,
        *,
        max_supported_transaction_version: int = 0,
    ) -> list[str] | None:
        """Signatures in a confirmed block (None if block missing)."""
        try:
            r = self.call(
                "getBlock",
                [
                    int(slot),
                    {
                        "encoding": "json",
                        "transactionDetails": "signatures",
                        "rewards": False,
                        "maxSupportedTransactionVersion": int(
                            max_supported_transaction_version
                        ),
                    },
                ],
            )
        except RuntimeError:
            return None
        if not r.result:
            return None
        return [str(s) for s in (r.result.get("signatures") or []) if s]


def collect_signatures_around_slot(
    rpc: "HeliusRpc",
    *,
    center_slot: int,
    slot_radius: int = 1,
) -> tuple[list[str], list[str]]:
    """Collect tx signatures from ``center_slot±slot_radius`` via getBlock.

    Age≈0 / migrated_pre_t0 snipers: create→T0 fits in 1–2 slots; mint-address
    pagination cannot reach that window under post-T0 spam.
    Returns (signatures, gaps).
    """
    gaps: list[str] = []
    out: list[str] = []
    seen: set[str] = set()
    lo = max(0, int(center_slot) - max(0, int(slot_radius)))
    hi = int(center_slot) + max(0, int(slot_radius))
    for slot in range(lo, hi + 1):
        sigs = rpc.get_block_signatures(slot)
        if sigs is None:
            gaps.append(f"getBlock_{slot}_null_or_err")
            continue
        n_new = 0
        for sg in sigs:
            if sg not in seen:
                seen.add(sg)
                out.append(sg)
                n_new += 1
        gaps.append(f"getBlock_{slot}_n={len(sigs)}_new={n_new}")
    return out, gaps



def smoke_health() -> dict[str, Any]:
    """1–2 llamadas: health + slot. Uso: verificar key sin gastar créditos."""
    with HeliusRpc() as rpc:
        health = rpc.get_health()
        slot = rpc.get_slot()
    return {"health": health, "slot": slot, "rpc": "helius-mainnet"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Helius RPC smoke (cuidado con créditos)")
    parser.add_argument("--health", action="store_true", help="getHealth + getSlot")
    parser.add_argument("--global-account", action="store_true", help="lee Global PDA Pump (1 call extra)")
    args = parser.parse_args()
    if not args.health and not args.global_account:
        args.health = True

    out: dict[str, Any] = {}
    if args.health:
        out.update(smoke_health())
    if args.global_account:
        from ingestion.bonding_curve import fetch_global

        g = fetch_global()
        out["global"] = {
            "initialized": g.initialized,
            "initial_virtual_sol_reserves": g.initial_virtual_sol_reserves,
            "initial_virtual_token_reserves": g.initial_virtual_token_reserves,
            "initial_real_token_reserves": g.initial_real_token_reserves,
            "token_total_supply": g.token_total_supply,
            "fee_basis_points": g.fee_basis_points,
        }
    print(json.dumps(out, indent=2))

