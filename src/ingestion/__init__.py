"""Ingestion — normaliza creates, trades, snapshots BondingCurve y oracle SOL.

Contrato
--------
- Escribe tablas raw particionadas; no decide T0.
- Toda fila lleva slot, block_time (UTC), signature, source.
- Filtro obligatorio: program Pump ``6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P``.

Wire Cycle 1 (parcial)
----------------------
- ``helius_rpc.HeliusRpc``: getHealth / getAccountInfo (throttle free-plan).
- ``helius_enhanced.HeliusEnhanced``: Enhanced tx history for paper_live Q5a/buy60.
- ``bonding_curve``: PDA + decode BondingCurve / Global.
- Streams Helius: OFF. Bitquery: optional (often 402 FREE).

Verification hooks
------------------
- ``verify_unique_sigs``: PK (sig, ix_index)
- ``verify_program_filter``
- ``manifest_sha256``: hash de particiones leídas (V7)
"""

from .pump_constants import (
    DEFINITION_VERSION,
    PUMP_PROGRAM_ID,
    PUMPSWAP_PROGRAM_ID,
    SOL_USD_SOURCE,
)

__all__ = [
    "PUMP_PROGRAM_ID",
    "PUMPSWAP_PROGRAM_ID",
    "DEFINITION_VERSION",
    "SOL_USD_SOURCE",
]
