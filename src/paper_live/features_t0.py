"""Feature vector ≤T0 for paper-live (production live path).

Formerly ``features_stub.py`` — renamed 2026-10-02: this is **not** a stub.
It is the live scoring feature builder used by ``loop``, ``score``,
``rescore_replay``, and ``recipe_parity``. Aligned with ``features.post_q5_sets``.

Contract
--------
- ``features_at_t0``: build ≤T0 feature dict from sighting + enrich extras.
- ``feature_vector_for_set``: numeric subset for FEATURE_SETS (buy60 / +q5b / lite).
- ``required_*_present``: completeness gates; missing pack → scorer skips.
- ``assert_no_lookahead_keys``: reject label / post-T0 keys.

Anti look-ahead
---------------
- Snapshot at first-sight (T0 provisional) only.
- ``buy_vol_usd_60s`` + Q5a/Q5b from enrich (Bitquery ≤T0 or dry fixture).
- Never invent substitutes. Missing required pack → incomplete → scorer skips.
- Creator pubkey / create_ts are join-only (not in X).
"""

from __future__ import annotations

from typing import Any

from features.post_q5_sets import BUY60_COLS, DROP_FROM_X, FEATURE_SETS, Q5A_COLS, Q5B_COLS
from paper_live.feed import MintSighting

# Train nearly always null — allowed missing for histgb_q5b completeness gate
NULL_OK_Q5B = frozenset({"creator_prior_mints_all_in_window"})

# Share / concentration null when buy_count_total==0 (train parity)
NULL_OK_WHEN_NO_BUYS = frozenset(
    {
        "first5_buy_vol_share",
        "sniper_vol_share_5s",
        "max_buy_share",
        "max_buy_sol",
        "max_buy_usd",
        "top1_buyer_vol_share",
        "top5_buyer_vol_share",
        "top10_buyer_vol_share",
        "top1_holder_pct_proxy",
        "top5_holder_pct_proxy",
        "top10_holder_pct_proxy",
    }
)


def features_at_t0(
    sighting: MintSighting,
    *,
    dry_run: bool = False,
    buy_vol_usd_60s: float | None = None,
    buy_vol_source: str | None = None,
    buy_count_60s: int | None = None,
    q5_extras: dict[str, Any] | None = None,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Vector ≤T0. Required packs missing → completeness flags False (caller skips)."""
    name = sighting.name or ""
    symbol = sighting.symbol or ""
    feats: dict[str, Any] = {
        "mint": sighting.mint,
        "t0_ts": sighting.t0_iso,
        "mc_usd_t0": sighting.mc_usd,
        "price_usd_t0": sighting.price_mean,
        # buy60
        "buy_vol_usd_60s": buy_vol_usd_60s,
        "buy_count_60s": buy_count_60s,
        # Q5b name/symbol from sighting as fallback (overwrite if enrich provides)
        "name_len": float(len(name)) if name else 0.0,
        "name_missing": 1.0 if not name else 0.0,
        "symbol_len": float(len(symbol)) if symbol else 0.0,
        "symbol_missing": 1.0 if not symbol else 0.0,
        "has_creator": None,
        "age_s": None,
        "age_min": None,
        "creator_prior_mints_7d": None,
        "creator_prior_mints_30d": None,
        "creator_prior_mints_cohort": None,
        "creator_prior_mints_all_in_window": None,
        "feature_set_version": "paper_live_v0_+q5b",
        "features_complete_buy60": False,
        "features_complete_q5b": False,
    }
    # Null-init all Q5a
    for c in Q5A_COLS:
        feats.setdefault(c, None)

    if q5_extras:
        banned = ("max_mc", "hit_", "label_", "after_t0", "primary_ready")
        for k, v in q5_extras.items():
            lk = k.lower()
            if any(b in lk for b in banned):
                continue
            if k in ("creator_pubkey", "create_ts") or k in DROP_FROM_X:
                feats[k] = v  # join-only / dropped-from-X, journal only
                continue
            feats[k] = v

    if buy_vol_usd_60s is not None:
        feats["buy_vol_usd_60s"] = buy_vol_usd_60s
        feats["buy_vol_source"] = buy_vol_source or ("dry_run.fixture" if dry_run else "provided")
    else:
        feats["buy_vol_source"] = buy_vol_source or "unavailable"

    feats["features_complete_buy60"] = feats.get("buy_vol_usd_60s") is not None
    feats["features_complete_q5b"] = required_q5b_present(feats)

    if extras:
        banned = ("max_mc", "hit_", "label_", "after_t0", "primary_ready")
        for k, v in extras.items():
            lk = k.lower()
            if any(b in lk for b in banned):
                continue
            feats[k] = v
        feats["features_complete_q5b"] = required_q5b_present(feats)
    return feats


def feature_vector_for_set(feats: dict[str, Any], set_name: str) -> dict[str, float | None]:
    """Subset numérico alineado con ``FEATURE_SETS`` (WF / paper_trade_v1)."""
    if set_name == "buy60":
        cols = FEATURE_SETS["buy60"]
    elif set_name in ("+q5b", "q5b"):
        cols = FEATURE_SETS["+q5b"]
    elif set_name == "lite":
        cols = FEATURE_SETS["lite"]
    else:
        raise ValueError(f"set desconocido para paper-live: {set_name}")
    if any(c in DROP_FROM_X for c in cols):
        raise AssertionError("DROP_FROM_X leaked into feature_vector_for_set")
    return {c: feats.get(c) for c in cols}


def required_buy60_present(feats: dict[str, Any]) -> bool:
    return feats.get("buy_vol_usd_60s") is not None


def required_q5b_present(feats: dict[str, Any]) -> bool:
    """Full FEATURE_SETS['+q5b'] present (train-parity null exceptions)."""
    if not required_buy60_present(feats):
        return False
    no_buys = float(feats.get("buy_count_total") or 0) == 0 and feats.get("buy_count_total") is not None
    for c in FEATURE_SETS["+q5b"]:
        if c in NULL_OK_Q5B:
            continue
        v = feats.get(c)
        if v is None:
            if no_buys and c in NULL_OK_WHEN_NO_BUYS:
                continue
            # buy_count_total itself must be present for Q5a pack
            return False
    return True


def assert_no_lookahead_keys(feats: dict[str, Any]) -> None:
    """Gate ligero: ninguna key de label / post-T0 en el dict de features."""
    for k in feats:
        lk = k.lower()
        if any(b in lk for b in ("max_mc", "hit_10x", "label_", "after_t0", "primary_ready")):
            raise AssertionError(f"look-ahead key en features ≤T0: {k}")


__all__ = [
    "BUY60_COLS",
    "Q5A_COLS",
    "Q5B_COLS",
    "FEATURE_SETS",
    "NULL_OK_Q5B",
    "features_at_t0",
    "feature_vector_for_set",
    "required_buy60_present",
    "required_q5b_present",
    "assert_no_lookahead_keys",
]
