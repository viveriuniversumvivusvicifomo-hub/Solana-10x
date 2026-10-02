"""Decode + PDA sin red (no gasta Helius)."""

from __future__ import annotations

import struct

from solders.pubkey import Pubkey

from ingestion.bonding_curve import bonding_curve_pda, decode_bonding_curve, decode_global
from ingestion.pump_constants import (
    INITIAL_REAL_TOKEN_RESERVES,
    INITIAL_VIRTUAL_SOL_RESERVES,
    INITIAL_VIRTUAL_TOKEN_RESERVES,
    PUMP_PROGRAM_ID,
    TOKEN_TOTAL_SUPPLY,
)


def test_bonding_curve_pda_deterministic():
    mint = Pubkey.from_string("So11111111111111111111111111111111111111112")
    a = bonding_curve_pda(mint)
    b = bonding_curve_pda(str(mint))
    assert a == b
    assert str(a) != str(mint)


def test_decode_bonding_curve_core():
    disc = b"\x00" * 8
    body = struct.pack(
        "<5Q",
        1_072_999_999_992_855,
        30_000_000_013,
        793_099_999_992_855,
        13,
        TOKEN_TOTAL_SUPPLY,
    )
    body += b"\x00"  # complete=false
    state = decode_bonding_curve(disc + body)
    assert state.virtual_sol_reserves == 30_000_000_013
    assert state.complete is False
    assert state.token_total_supply == TOKEN_TOTAL_SUPPLY


def test_decode_global_core():
    disc = b"\x00" * 8
    body = b"\x01"  # initialized
    body += bytes(32)  # authority
    body += bytes(32)  # fee_recipient
    body += struct.pack(
        "<5Q",
        INITIAL_VIRTUAL_TOKEN_RESERVES,
        INITIAL_VIRTUAL_SOL_RESERVES,
        INITIAL_REAL_TOKEN_RESERVES,
        TOKEN_TOTAL_SUPPLY,
        100,
    )
    g = decode_global(disc + body)
    assert g.initialized is True
    assert g.initial_virtual_sol_reserves == INITIAL_VIRTUAL_SOL_RESERVES
    assert g.fee_basis_points == 100
    assert PUMP_PROGRAM_ID.startswith("6EF8")
