"""Constantes Pump.fun (Global on-chain). Única fuente — no duplicar (V5).

Fuente: https://github.com/pump-fun/pump-public-docs (PUMP_PROGRAM_README.md)
Verificar on-chain Global PDA antes de producción; valores pueden actualizarse
vía set_params.
"""

PUMP_PROGRAM_ID = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMPSWAP_PROGRAM_ID = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
GLOBAL_PDA = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"

# Reservas iniciales (u64 raw) según Global documentado
INITIAL_VIRTUAL_TOKEN_RESERVES = 1_073_000_000_000_000
INITIAL_VIRTUAL_SOL_RESERVES = 30_000_000_000  # 30 SOL en lamports
INITIAL_REAL_TOKEN_RESERVES = 793_100_000_000_000
TOKEN_TOTAL_SUPPLY = 1_000_000_000_000_000  # 1B UI @ 6 decimals
TOKEN_DECIMALS = 6

DEFINITION_VERSION = "v0.3"

# Oracle SOL/USD frozen (Sinck 2026-09-29)
SOL_USD_SOURCE = "pyth"
SOL_USD_SOURCE_FROZEN = True
# fee_basis_points on-chain Global puede diferir del README (smoke 2026-09-29: 95 vs 100 docs).
# Leer siempre de Global en runtime; no hardcodear fees aquí.

# Captura v0 band (Sinck frozen 2026-09-29) — single source for T0 C3
MC_LO_USD = 8_000.0
MC_HI_USD = 20_000.0
TRADEABLE_N_S = 30.0

