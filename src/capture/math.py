"""Fórmulas de precio y market cap en bonding curve (única implementación).

MC_sol = (virtual_sol_reserves * token_total_supply) / virtual_token_reserves
MC_usd = MC_sol_in_SOL * sol_usd

Oracle SOL/USD frozen: ``ingestion.pump_constants.SOL_USD_SOURCE == "pyth"``.
No implementar de nuevo en features/labeling.
"""

from __future__ import annotations

LAMPORTS_PER_SOL = 1_000_000_000


def spot_sol_per_raw_token(virtual_sol_reserves: int, virtual_token_reserves: int) -> float:
    """Precio marginal approx: vs/vt (SOL lamports por token raw)."""
    if virtual_token_reserves <= 0:
        raise ValueError("virtual_token_reserves must be > 0")
    return virtual_sol_reserves / virtual_token_reserves


def market_cap_usd(
    virtual_sol_reserves: int,
    virtual_token_reserves: int,
    token_total_supply: int,
    sol_usd: float,
) -> float:
    """Market cap USD convención v0 (indexadores Pump)."""
    if virtual_token_reserves <= 0:
        raise ValueError("virtual_token_reserves must be > 0")
    if sol_usd <= 0:
        raise ValueError("sol_usd must be > 0")
    mc_lamports = (virtual_sol_reserves * token_total_supply) / virtual_token_reserves
    mc_sol = mc_lamports / LAMPORTS_PER_SOL
    return mc_sol * sol_usd


def curve_progress(real_token_reserves: int, initial_real_token_reserves: int) -> float:
    if initial_real_token_reserves <= 0:
        raise ValueError("initial_real_token_reserves must be > 0")
    return 1.0 - (real_token_reserves / initial_real_token_reserves)
