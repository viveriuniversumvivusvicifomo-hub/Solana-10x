"""paper_live T0 capture — re-exports SolDatos ``ingestion.t0_capture``.

Canonical C1–C6 + Dune-Q3 train-parity finders live in ``ingestion.t0_capture``.
TradeRow from q5a_agg satisfies TradeLeg / TradeLegWithTok protocols.
"""

from __future__ import annotations

from ingestion.t0_capture import (  # noqa: F401
    is_scoreable_capture,
    score_reject_reason,
    require_scoreable_capture,
    TRADEABLE_N_S,
    CaptureT0,
    TradeLeg,
    TradeLegWithTok,
    evolve_curve_mc_series,
    find_t0_c1_c6,
    find_t0_c1_c6_train_aligned,
    find_t0_dune_q3,
    trade_implied_mc_usd,
    find_t0_pump_mc_sighting,
    is_scoreable_pump_capture,
    score_reject_reason_pump,
    PUMP_MC_SIGHTING_DEF,
)

__all__ = [
    "TRADEABLE_N_S",
    "CaptureT0",
    "TradeLeg",
    "TradeLegWithTok",
    "evolve_curve_mc_series",
    "find_t0_c1_c6",
    "find_t0_c1_c6_train_aligned",
    "find_t0_dune_q3",
    "trade_implied_mc_usd",
    "find_t0_pump_mc_sighting",
    "is_scoreable_pump_capture",
    "score_reject_reason_pump",
    "PUMP_MC_SIGHTING_DEF",
    "is_scoreable_capture",
    "score_reject_reason",
    "require_scoreable_capture",
]
