"""Pure ≤T0 Q5b aggregation (parity with dune-q5b-creator-age-pre-t0 + cohort priors).

Create row: create_ts ≤ t0. Priors: other creates by same creator with create_ts < t0
(strict), windowed to 7d / 30d / all_in_window / cohort rank.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


META_FEATURE_COLS = META_NAME_SYMBOL_COLS = (
    "name_len",
    "name_missing",
    "symbol_len",
    "symbol_missing",
)

META_SOURCE_CREATE = "create"
META_SOURCE_SIGHTING = "sighting"
META_SOURCE_DUNE_STORE_EXACT = "dune_store_exact"


@dataclass
class CreateRow:
    mint: str
    creator_pubkey: str | None
    create_ts: datetime
    token_name: str | None = None
    token_symbol: str | None = None


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def q5b_from_create(
    create: CreateRow | None,
    t0: datetime,
    *,
    prior_creates: list[CreateRow] | None = None,
) -> dict[str, Any]:
    """Build Q5B_COLS (+ join keys). Missing create → incomplete (caller skips)."""
    t0 = _aware(t0)
    if create is None:
        return {
            "age_s": None,
            "age_min": None,
            "has_creator": 0.0,
            "name_len": 0.0,
            "name_missing": 1.0,
            "symbol_len": 0.0,
            "symbol_missing": 1.0,
            "creator_prior_mints_7d": None,
            "creator_prior_mints_30d": None,
            "creator_prior_mints_cohort": None,
            "creator_prior_mints_all_in_window": None,
            "creator_pubkey": None,
            "create_ts": None,
            "q5b_complete": False,
        }

    cts = _aware(create.create_ts)
    if cts > t0:
        # look-ahead create — reject
        return q5b_from_create(None, t0)

    age_s = (t0 - cts).total_seconds()
    name = create.token_name or ""
    symbol = create.token_symbol or ""
    creator = create.creator_pubkey

    priors = prior_creates or []
    # only same creator, strictly before this create/t0
    prior_ts: list[datetime] = []
    for p in priors:
        if not creator or p.creator_pubkey != creator:
            continue
        if p.mint == create.mint:
            continue
        pts = _aware(p.create_ts)
        if pts < cts and pts <= t0:
            prior_ts.append(pts)

    prior_ts.sort()
    n7 = sum(1 for pts in prior_ts if (cts - pts) <= timedelta(days=7))
    n30 = sum(1 for pts in prior_ts if (cts - pts) <= timedelta(days=30))
    # cohort rank ≈ number of earlier creates (same as add_cohort_creator_priors)
    cohort = len(prior_ts)

    out: dict[str, Any] = {
        "age_s": float(age_s),
        "age_min": float(age_s) / 60.0,
        "has_creator": 1.0 if creator else 0.0,
        "name_len": float(len(name)) if name else 0.0,
        "name_missing": 0.0 if name else 1.0,
        "symbol_len": float(len(symbol)) if symbol else 0.0,
        "symbol_missing": 0.0 if symbol else 1.0,
        "creator_prior_mints_7d": float(n7),
        "creator_prior_mints_30d": float(n30),
        "creator_prior_mints_cohort": float(cohort),
        # Train store is ~100% NULL for this col (never populated in Dune merge).
        # Filling 0.0 when prior_creates=[] poisoned live X vs SimpleImputer median.
        "creator_prior_mints_all_in_window": None,
        "creator_pubkey": creator,
        "create_ts": cts.isoformat(timespec="milliseconds"),
        "q5b_complete": True,
    }
    if name or symbol:
        out["meta_source"] = META_SOURCE_CREATE
    return out


def prefer_sighting_meta_name_symbol(
    q5b: dict[str, Any],
    *,
    name: str | None,
    symbol: str | None,
) -> dict[str, Any]:
    """If create args lack name/symbol, fill from Pairs sighting (≤T0 meta)."""
    out = dict(q5b)
    filled = False
    if out.get("name_missing") and name:
        out["name_len"] = float(len(name))
        out["name_missing"] = 0.0
        filled = True
    if out.get("symbol_missing") and symbol:
        out["symbol_len"] = float(len(symbol))
        out["symbol_missing"] = 0.0
        filled = True
    if filled:
        out["meta_source"] = META_SOURCE_SIGHTING
    return out


def fill_meta_from_dune_store_exact(
    q5b: dict[str, Any],
    store_meta: dict[str, float | None] | None,
) -> dict[str, Any]:
    """Fill name/symbol length features from train store when still missing.

    Prefer CreateEvent / Pump / sighting meta first (caller order). When those
    leave ``name_missing`` / ``symbol_missing``, and ``mint`` has a row in the
    Dune train store, copy **exact** ``name_len`` / ``symbol_len`` /
    ``name_missing`` / ``symbol_missing`` for score parity.

    Does **not** invent token names — only numeric meta features.
    Stamps ``meta_source=dune_store_exact`` when any store fill is applied.
    """
    if not store_meta:
        return q5b
    out = dict(q5b)
    filled = False

    if out.get("name_missing"):
        if store_meta.get("name_len") is not None:
            out["name_len"] = float(store_meta["name_len"])
            filled = True
        if store_meta.get("name_missing") is not None:
            out["name_missing"] = float(store_meta["name_missing"])
            filled = True

    if out.get("symbol_missing"):
        if store_meta.get("symbol_len") is not None:
            out["symbol_len"] = float(store_meta["symbol_len"])
            filled = True
        if store_meta.get("symbol_missing") is not None:
            out["symbol_missing"] = float(store_meta["symbol_missing"])
            filled = True

    if filled:
        out["meta_source"] = META_SOURCE_DUNE_STORE_EXACT
    return out

# Alias — SolModelos call sites / BOSS naming
prefer_train_store_meta_name_symbol = fill_meta_from_dune_store_exact
