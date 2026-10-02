"""BondingCurve PDA + decode (layout Pump Anchor). Única implementación (V5)."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any

from solders.pubkey import Pubkey

from ingestion.helius_rpc import HeliusRpc
from ingestion.pump_constants import (
    GLOBAL_PDA,
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    PUMP_PROGRAM_ID,
    TOKEN_TOTAL_SUPPLY,
)

PUMP_PROGRAM = Pubkey.from_string(PUMP_PROGRAM_ID)
BONDING_CURVE_SEED = b"bonding-curve"

# Anchor discriminator (8) + 5×u64 + bool(+pad) — campos core documentados
_CORE_FMT = "<5Q?"  # after 8-byte disc
_CORE_SIZE = 8 + struct.calcsize(_CORE_FMT)  # 8 + 40 + 1 = 49; bool may pad


@dataclass(frozen=True)
class BondingCurveState:
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool
    raw_len: int
    # opcionales post-upgrade (si caben en la cuenta)
    creator: str | None = None
    quote_mint: str | None = None


@dataclass(frozen=True)
class GlobalState:
    initialized: bool
    initial_virtual_token_reserves: int
    initial_virtual_sol_reserves: int
    initial_real_token_reserves: int
    token_total_supply: int
    fee_basis_points: int
    raw_len: int


def bonding_curve_pda(mint: str | Pubkey) -> Pubkey:
    mint_pk = mint if isinstance(mint, Pubkey) else Pubkey.from_string(mint)
    pda, _bump = Pubkey.find_program_address([BONDING_CURVE_SEED, bytes(mint_pk)], PUMP_PROGRAM)
    return pda


def decode_bonding_curve(data: bytes) -> BondingCurveState:
    if len(data) < 8 + 40 + 1:
        raise ValueError(f"BondingCurve data demasiado corta: {len(data)}")
    body = data[8:]  # skip Anchor discriminator
    vt, vs, rt, rs, supply = struct.unpack_from("<5Q", body, 0)
    complete = bool(body[40])
    creator = None
    quote_mint = None
    # creator pubkey @ offset 41 (after bool; Anchor typically packs bool as 1 byte)
    if len(body) >= 41 + 32:
        creator = str(Pubkey.from_bytes(body[41:73]))
    # quote_mint appears after later bools in newer layouts — best-effort if long enough
    # Layout after creator: is_mayhem(1) is_cashback(1) quote_mint(32) ...
    if len(body) >= 41 + 32 + 1 + 1 + 32:
        quote_mint = str(Pubkey.from_bytes(body[41 + 32 + 2 : 41 + 32 + 2 + 32]))
    return BondingCurveState(
        virtual_token_reserves=vt,
        virtual_sol_reserves=vs,
        real_token_reserves=rt,
        real_sol_reserves=rs,
        token_total_supply=supply,
        complete=complete,
        raw_len=len(data),
        creator=creator,
        quote_mint=quote_mint,
    )


def decode_global(data: bytes) -> GlobalState:
    """Decode parcial de Global (campos iniciales documentados)."""
    if len(data) < 8 + 1 + 32 + 32 + 32:  # disc + bool + 3 pubkeys min rough
        raise ValueError(f"Global data demasiado corta: {len(data)}")
    body = data[8:]
    initialized = bool(body[0])
    # After bool(1) + authority(32) + fee_recipient(32) = offset 65
    off = 1 + 32 + 32
    ivt, ivs, irt, supply, fee_bps = struct.unpack_from("<5Q", body, off)
    return GlobalState(
        initialized=initialized,
        initial_virtual_token_reserves=ivt,
        initial_virtual_sol_reserves=ivs,
        initial_real_token_reserves=irt,
        token_total_supply=supply,
        fee_basis_points=fee_bps,
        raw_len=len(data),
    )


def _account_data_b64(info: dict[str, Any] | None) -> bytes:
    if not info or info.get("value") is None:
        raise RuntimeError("cuenta no encontrada")
    data_field = info["value"]["data"]
    if isinstance(data_field, list):
        import base64

        return base64.b64decode(data_field[0])
    raise RuntimeError(f"encoding no soportado: {type(data_field)}")


def fetch_bonding_curve(mint: str, rpc: HeliusRpc | None = None) -> BondingCurveState:
    owns = rpc is None
    rpc = rpc or HeliusRpc()
    try:
        pda = bonding_curve_pda(mint)
        info = rpc.get_account_info(str(pda))
        return decode_bonding_curve(_account_data_b64(info))
    finally:
        if owns:
            rpc.close()


def fetch_global(rpc: HeliusRpc | None = None) -> GlobalState:
    owns = rpc is None
    rpc = rpc or HeliusRpc()
    try:
        info = rpc.get_account_info(GLOBAL_PDA)
        g = decode_global(_account_data_b64(info))
        # sanity vs constants documentadas (no mutar; aviso soft)
        _ = (
            INITIAL_VIRTUAL_SOL_RESERVES,
            INITIAL_VIRTUAL_TOKEN_RESERVES,
            INITIAL_REAL_TOKEN_RESERVES,
            TOKEN_TOTAL_SUPPLY,
        )
        return g
    finally:
        if owns:
            rpc.close()
