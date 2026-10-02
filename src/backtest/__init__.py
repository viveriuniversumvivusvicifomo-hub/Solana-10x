"""Backtest — esqueleto walk-forward.

Contrato
--------
- Split por tiempo de T0 + embargo ≥ horizonte de label (V4).
- Fills sin look-ahead (precio ≥ P0 / fee curva 1.25% documentado).
- ``build_single_fold`` + ``validate_fold``; sin datos live en C0.

Verification hooks
------------------
- ``assert_walk_forward_order`` (V4)
- ``assert_embargo`` / ``assert_mint_single_split`` (V4)
"""

from backtest.walk_forward import (
    CURVE_FEE_BPS,
    CaptureRef,
    WalkForwardFold,
    build_assignments,
    build_single_fold,
    default_embargo,
    fill_price_after_fee,
    purge_train_overlapping_val,
    validate_fold,
)

__all__ = [
    "CURVE_FEE_BPS",
    "CaptureRef",
    "WalkForwardFold",
    "build_assignments",
    "build_single_fold",
    "default_embargo",
    "fill_price_after_fee",
    "purge_train_overlapping_val",
    "validate_fold",
]
