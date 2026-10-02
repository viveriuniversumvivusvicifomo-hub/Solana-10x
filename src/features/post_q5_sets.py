"""Feature-set packs for post-Q5 walk-forward (expand v2 + Q5a/Q5b).

Sets (BOSS 2026-09-30):
  buy60 | buy60+q5a | q5a_only | +q5b | full

Rules:
  - labels never in X
  - creator_pubkey / create_ts are join-only (never in X)
  - leak-like names rejected
  - PRIMARY preferred when present: hit_10x_30d; else proxy hit_200k
"""

from __future__ import annotations

import re
from typing import Iterable

LEAK_COL_RE = re.compile(r"(max_mc|hit_|label_|after_t0|primary_ready)", re.I)

# Join / meta — never train features
# Explicitly banned from X even if present in Q5 packs (SolQA/SolDatos 2026-09-30)
DROP_FROM_X = frozenset(
    {
        "migrated_pre_t0",  # pumpswap≤T0 ≠ bonding graduation; rate ~0.68 spurious
    }
)

JOIN_ONLY = frozenset(
    {
        "mint",
        "t0_ts",
        "t0",
        "feature_set_version",
        "create_ts",
        "creator_pubkey",  # join only — SolQA / BOSS
        "token_name",
        "token_symbol",
    }
)

LABEL_CANDIDATES = ("hit_10x_30d", "hit_200k")  # PRIMARY first when exists
PROXY_LABEL = "hit_200k"
PRIMARY_LABEL = "hit_10x_30d"

# Expand v2 baseline flow (numeric train cols from features_dune_p0_flow_expand_v2)
EXPAND_FLOW_COLS = (
    "mc_usd_t0",
    "price_usd_t0",
    "mc_band_pos",
    "log1p_mc_usd_t0",
    "is_pumpdotfun",
    "buy_count_60s",
    "sell_count_60s",
    "buy_vol_usd_60s",
    "sell_vol_usd_60s",
    "unique_traders_60s",
    "buy_count_5m",
    "sell_count_5m",
    "buy_vol_usd_5m",
    "sell_vol_usd_5m",
    "unique_traders_5m",
    "trade_count_total",
    "unique_traders_total",
    "time_since_first_trade_s",
)

BUY60_COLS = ("buy_vol_usd_60s",)

# Q5a numeric from dune_q5a_features.csv (excl join keys)
Q5A_COLS = (
    "age_proxy_s",
    "buy_count_15m",
    "buy_count_30s",
    "buy_count_total",
    "buy_vol_first_10s",
    "buy_vol_first_5s",
    "buy_vol_usd_15m",
    "buy_vol_usd_30s",
    "buy_vol_usd_total",
    "first10_buy_vol_usd",
    "first5_buy_vol_share",
    "first5_buy_vol_usd",
    "first_buy_usd",
    "max_buy_share",
    "max_buy_sol",
    "max_buy_usd",
    "n_holders_proxy",
    "net_sol_curve",
    "net_sol_total",
    "progress_curve_proxy",
    "sell_count_15m",
    "sell_count_30s",
    "sell_count_total",
    "sell_vol_usd_15m",
    "sell_vol_usd_30s",
    "sell_vol_usd_total",
    "sniper_vol_share_5s",
    "top10_buyer_vol_share",
    "top10_holder_pct_proxy",
    "top1_buyer_vol_share",
    "top1_holder_pct_proxy",
    "top5_buyer_vol_share",
    "top5_holder_pct_proxy",
    "unique_buyers_first5",
    "unique_buyers_first_5s",
    "unique_buyers_total",
    "unique_sellers_total",
    "unique_traders_15m",
    "unique_traders_30s",
)

# Q5b numeric / boolean — creator_pubkey OUT
Q5B_COLS = (
    "age_s",
    "age_min",
    "has_creator",
    "name_len",
    "name_missing",
    "symbol_len",
    "symbol_missing",
    "creator_prior_mints_7d",
    "creator_prior_mints_30d",
    "creator_prior_mints_cohort",
    "creator_prior_mints_all_in_window",
)

SET_ORDER = ("buy60", "buy60+q5a", "q5a_only", "+q5b", "full")


def _uniq(cols: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for c in cols:
        if c in JOIN_ONLY or c in DROP_FROM_X:
            continue
        if LEAK_COL_RE.search(c):
            raise AssertionError(f"leak-like column in feature pack: {c}")
        if c not in seen:
            seen.add(c)
            out.append(c)
    return tuple(out)


FEATURE_SETS: dict[str, tuple[str, ...]] = {
    "buy60": _uniq(BUY60_COLS),
    "buy60+q5a": _uniq([*BUY60_COLS, *Q5A_COLS]),
    "q5a_only": _uniq(Q5A_COLS),
    "+q5b": _uniq([*BUY60_COLS, *Q5A_COLS, *Q5B_COLS]),  # buy60+q5a+q5b
    "full": _uniq([*EXPAND_FLOW_COLS, *Q5A_COLS, *Q5B_COLS]),
}


def assert_sets_safe() -> None:
    for name, cols in FEATURE_SETS.items():
        assert "creator_pubkey" not in cols, name
        assert "create_ts" not in cols, name
        for lc in LABEL_CANDIDATES:
            assert lc not in cols, (name, lc)
        bad = [c for c in cols if LEAK_COL_RE.search(c)]
        assert not bad, (name, bad)


def resolve_label_column(columns: Iterable[str]) -> tuple[str, bool]:
    """Return (label_col, is_primary). Prefer hit_10x_30d when present."""
    cols = set(columns)
    if PRIMARY_LABEL in cols:
        return PRIMARY_LABEL, True
    if PROXY_LABEL in cols:
        return PROXY_LABEL, False
    raise KeyError(f"no label among {LABEL_CANDIDATES}; have {sorted(cols)}")


assert_sets_safe()


# Lite product pack (cycle0 2026-10-02) — seconds-budget Pump+RPC subset.
# NOT Path A / histgb parity. See cycle0/score-mode-lite-cycle0-20261002.md.
LITE_COLS = (
    "buy_vol_usd_60s",
    "sniper_vol_share_5s",
    "top1_buyer_vol_share",
    "top5_buyer_vol_share",
    "age_s",
    "progress_curve_proxy",
    "net_sol_curve",
    "creator_prior_mints_7d",
    "creator_prior_mints_30d",
)

FEATURE_SETS["lite"] = _uniq(LITE_COLS)
SET_ORDER = (*SET_ORDER, "lite")
assert_sets_safe()
