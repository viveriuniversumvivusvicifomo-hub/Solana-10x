"""Whitelist P0 del feature matrix (cycle0/feature-set-mvp.md).

Train solo puede usar estas columnas (+ P1 cuando se activen).
"""

from __future__ import annotations

from typing import Final

FEATURE_SET_VERSION: Final[str] = "features.mvp.v0"

# Ventanas de flujo P0
_FLOW_WINDOWS: Final[tuple[str, ...]] = ("60s", "5m")
_FLOW_STEMS: Final[tuple[str, ...]] = (
    "buy_count",
    "sell_count",
    "buy_vol_sol",
    "sell_vol_sol",
    "unique_buyers",
    "unique_sellers",
    "buy_sell_ratio_vol",
    "net_flow_sol",
)

P0_FEATURE_NAMES: Final[frozenset[str]] = frozenset(
    {
        # A mercado
        "mc_usd_t0",
        "price_usd_t0",
        "mc_band_pos",
        "sol_usd_t0",
        "progress_curve",
        "virtual_sol",
        "real_sol",
        "virtual_token",
        "real_token",
        # B liquidez
        "liq_real_sol",
        "liq_virt_sol",
        "liq_real_over_mc",
        "complete_flag",
        # C edad
        "age_s",
        "age_slots",
        "time_since_first_trade_s",
        # D holders
        "holder_count",
        "top1_pct",
        "top5_pct",
        "top10_pct",
        "creator_holding_pct",
        "curve_holding_pct",
        # E flujo
        *(f"{stem}_{w}" for w in _FLOW_WINDOWS for stem in _FLOW_STEMS),
        "trade_count_total",
        # F authorities / T22
        "mint_authority_none",
        "freeze_authority_none",
        "is_token_2022",
        "t22_transfer_fee",
        "t22_permanent_delegate",
        "metadata_mutable",
        # G creator
        "creator_pubkey",
        "creator_prior_mints_7d",
        # H microestructura
        "buys_per_min",
        "unique_traders_total",
    }
)

# Meta columnas permitidas junto al vector (no son features de modelo)
FEATURE_META_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "capture_id",
        "mint",
        "t0",
        "slot0",
        "feature_set_version",
        "definition_version",
    }
)
