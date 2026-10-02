"""Creator prior index for live Q5b parity with Dune train feature store.

Train definition (``add_cohort_creator_priors`` in ``run_dune_q5_api.py``):
  - Counts earlier creates by same creator **in the Dune cohort CSV**
    (create_ts causal, no 30d cap on the cohort list).
  - ``creator_prior_mints_cohort`` = rank among earlier cohort creates.
  - 7d / 30d = windows relative to this mint's create_ts among those earlier creates.
  - ``creator_prior_mints_all_in_window`` is ~99.99% NULL in train — stay None.

Live resolution order (histgb train-parity path):
  1. ``dune_cohort_exact`` — mint row in expand_v2 / q5b CSV → copy prior cols.
  2. ``dune_cohort_recompute`` — same cohort index, ``priors_for(window_days=None)``
     then ``q5b_from_create`` applies 7d/30d/cohort.
  3. ``none`` / ``dune_cohort_empty`` — store missing or no earlier creates → counts 0.
  4. ``pump_frontend_30d`` — **only** if ``ALLOW_PUMP_FRONTEND_PRIORS=1`` (non-parity).

Legacy alias ``train_store_v1`` maps to the dune_cohort_* family for auditors.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from paper_live.config import ROOT
from paper_live.q5b_agg import META_FEATURE_COLS as META_NAME_SYMBOL_COLS, CreateRow

log = logging.getLogger(__name__)

# Canonical live sources (persist on features as creator_prior_source)
CREATOR_PRIOR_SOURCE_EXACT = "dune_cohort_exact"
CREATOR_PRIOR_SOURCE_RECOMPUTE = "dune_cohort_recompute"
CREATOR_PRIOR_SOURCE_NONE = "none"
CREATOR_PRIOR_SOURCE_EMPTY = "dune_cohort_empty"
CREATOR_PRIOR_SOURCE_PUMP = "pump_frontend_30d"
# Backward-compatible alias (maps conceptually to dune_cohort_*)
CREATOR_PRIOR_SOURCE_TRAIN = "train_store_v1"

PRIOR_FEATURE_COLS = (
    "creator_prior_mints_7d",
    "creator_prior_mints_30d",
    "creator_prior_mints_cohort",
    "creator_prior_mints_all_in_window",
)

# Prefer expand_v2 (same as train FEATURE_SETS expand) over q5b-only merge.
_DEFAULT_STORE_CANDIDATES = (
    ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv",
    ROOT / "data" / "samples" / "dune_q5b_features.csv",
)


def allow_pump_frontend_priors() -> bool:
    """Opt-in non-parity pump frontend priors (default OFF)."""
    return os.environ.get("ALLOW_PUMP_FRONTEND_PRIORS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_ts(raw: Any) -> datetime | None:
    if raw is None or (isinstance(raw, float) and raw != raw):
        return None
    if isinstance(raw, datetime):
        return _aware(raw)
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    s = s.replace(" UTC", "+00:00").replace("Z", "+00:00")
    try:
        return _aware(datetime.fromisoformat(s))
    except ValueError:
        return None


def _nan_to_none(v: Any) -> float | None:
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
        # pandas NA / string nan
        if str(v).strip().lower() in ("", "nan", "none", "<na>"):
            return None
        f = float(v)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


@dataclass
class CreatorPriorIndex:
    """In-memory creator → sorted create rows + optional per-mint exact priors."""

    by_creator: dict[str, list[CreateRow]] = field(default_factory=dict)
    by_mint_priors: dict[str, dict[str, float | None]] = field(default_factory=dict)
    by_mint_meta: dict[str, dict[str, float | None]] = field(default_factory=dict)
    n_rows: int = 0
    source: str = CREATOR_PRIOR_SOURCE_NONE
    path: str | None = None

    def exact_priors_for_mint(self, mint: str) -> dict[str, float | None] | None:
        """Return store prior feature dict for mint, or None if mint not in store."""
        row = self.by_mint_priors.get(mint)
        if row is None:
            return None
        return dict(row)

    def exact_meta_for_mint(self, mint: str) -> dict[str, float | None] | None:
        """Return store name_len/symbol_* for mint, or None if mint not in store."""
        row = self.by_mint_meta.get(mint)
        if row is None:
            return None
        return dict(row)

    def priors_for(
        self,
        creator: str,
        *,
        this_mint: str,
        as_of: datetime,
        window_days: int | None = None,
    ) -> list[CreateRow]:
        """Creates by ``creator`` with create_ts < as_of.

        ``window_days=None`` (train-equivalent): no time cap — cohort = all earlier
        cohort creates. ``q5b_from_create`` then applies 7d/30d windows.
        When ``window_days`` is an int, also require create_ts >= as_of - window.
        """
        as_of = _aware(as_of)
        lo = as_of - timedelta(days=window_days) if window_days is not None else None
        out: list[CreateRow] = []
        for row in self.by_creator.get(creator, []):
            if row.mint == this_mint:
                continue
            cts = _aware(row.create_ts)
            if cts >= as_of:
                continue
            if lo is not None and cts < lo:
                continue
            out.append(row)
        return out


_CACHE: CreatorPriorIndex | None = None


def load_creator_prior_index(
    path: Path | None = None,
    *,
    force_reload: bool = False,
) -> CreatorPriorIndex:
    """Load Dune cohort creator×create index + exact prior cols (cached)."""
    global _CACHE
    if _CACHE is not None and not force_reload and path is None:
        return _CACHE

    candidates: list[Path] = []
    if path is not None:
        candidates.append(path)
    candidates.extend(_DEFAULT_STORE_CANDIDATES)

    chosen: Path | None = None
    for p in candidates:
        if p.is_file():
            chosen = p
            break
    if chosen is None:
        idx = CreatorPriorIndex(source=CREATOR_PRIOR_SOURCE_NONE)
        if path is None:
            _CACHE = idx
        return idx

    try:
        import pandas as pd
    except ImportError:
        log.warning("pandas missing — creator prior index unavailable")
        idx = CreatorPriorIndex(source=CREATOR_PRIOR_SOURCE_NONE)
        if path is None:
            _CACHE = idx
        return idx

    usecols = ["mint", "creator_pubkey", "create_ts", *PRIOR_FEATURE_COLS, *META_NAME_SYMBOL_COLS]
    try:
        df = pd.read_csv(chosen, usecols=lambda c: c in usecols)
    except (ValueError, KeyError):
        df = pd.read_csv(chosen)
        keep = [c for c in usecols if c in df.columns]
        df = df[keep]

    by: dict[str, list[CreateRow]] = {}
    by_mint: dict[str, dict[str, float | None]] = {}
    by_mint_meta: dict[str, dict[str, float | None]] = {}
    n = 0
    has_prior_cols = all(c in df.columns for c in PRIOR_FEATURE_COLS)
    has_meta_cols = all(c in df.columns for c in META_NAME_SYMBOL_COLS)
    for row in df.itertuples(index=False):
        mint = getattr(row, "mint", None)
        creator = getattr(row, "creator_pubkey", None)
        cts = _parse_ts(getattr(row, "create_ts", None))
        if not mint or not creator or cts is None:
            continue
        mint_s = str(mint)
        creator_s = str(creator)
        by.setdefault(creator_s, []).append(
            CreateRow(
                mint=mint_s,
                creator_pubkey=creator_s,
                create_ts=cts,
            )
        )
        if has_prior_cols:
            by_mint[mint_s] = {
                col: _nan_to_none(getattr(row, col, None)) for col in PRIOR_FEATURE_COLS
            }
            # Train parity: all_in_window must stay None even if CSV has 0.0 rare fill
            # Keep CSV value when non-null rare; hunt says ~100% null — NaN→None already.
        if has_meta_cols:
            by_mint_meta[mint_s] = {
                col: _nan_to_none(getattr(row, col, None)) for col in META_NAME_SYMBOL_COLS
            }
        n += 1
    for rows in by.values():
        rows.sort(key=lambda r: _aware(r.create_ts))

    # Index source alias: train_store_v1 for backward compat; callers use dune_cohort_*.
    idx = CreatorPriorIndex(
        by_creator=by,
        by_mint_priors=by_mint,
        by_mint_meta=by_mint_meta,
        n_rows=n,
        source=CREATOR_PRIOR_SOURCE_TRAIN,
        path=str(chosen),
    )
    if path is None:
        _CACHE = idx
    log.info(
        "creator_prior_index source=%s path=%s n_rows=%s n_creators=%s n_exact=%s n_meta=%s",
        idx.source,
        idx.path,
        idx.n_rows,
        len(idx.by_creator),
        len(idx.by_mint_priors),
        len(idx.by_mint_meta),
    )
    return idx


@dataclass
class ResolvedCreatorPriors:
    """Result of live prior resolution for one mint."""

    source: str
    # When source=exact: feature overlay to apply after q5b_from_create
    exact_overlay: dict[str, float | None] | None = None
    # When recompute/pump/none: list passed to q5b_from_create(prior_creates=...)
    prior_creates: list[CreateRow] = field(default_factory=list)
    path: str | None = None


def resolve_creator_priors(
    *,
    mint: str,
    creator: str | None,
    create_ts: datetime,
    index: CreatorPriorIndex | None = None,
    pump_client: Any | None = None,
    allow_pump: bool | None = None,
) -> ResolvedCreatorPriors:
    """Resolve creator priors for histgb train-parity (exact → recompute → none).

    Pump frontend is **off by default**; set ``ALLOW_PUMP_FRONTEND_PRIORS=1`` or
    pass ``allow_pump=True`` to re-enable (non-parity).
    """
    if not creator:
        return ResolvedCreatorPriors(source=CREATOR_PRIOR_SOURCE_NONE, prior_creates=[])

    idx = index if index is not None else load_creator_prior_index()
    use_pump = allow_pump_frontend_priors() if allow_pump is None else bool(allow_pump)

    # A) Exact row lookup from Dune feature store
    if idx.n_rows > 0 and idx.by_mint_priors:
        exact = idx.exact_priors_for_mint(mint)
        if exact is not None:
            # Force all_in_window None when store NaN (already); keep rare non-null as-is
            # but train expects None ~always — if value is 0.0 from dirty CSV, still None
            # for parity with q5b_agg (always None). Hunt: must stay None.
            overlay = dict(exact)
            overlay["creator_prior_mints_all_in_window"] = None
            return ResolvedCreatorPriors(
                source=CREATOR_PRIOR_SOURCE_EXACT,
                exact_overlay=overlay,
                prior_creates=[],
                path=idx.path,
            )

    # B) Recompute from uncapped cohort index
    if idx.n_rows > 0:
        priors = idx.priors_for(
            creator,
            this_mint=mint,
            as_of=create_ts,
            window_days=None,
        )
        src = (
            CREATOR_PRIOR_SOURCE_RECOMPUTE
            if priors
            else CREATOR_PRIOR_SOURCE_EMPTY
        )
        return ResolvedCreatorPriors(
            source=src,
            exact_overlay=None,
            prior_creates=priors,
            path=idx.path,
        )

    # C) Optional pump (non-parity)
    if use_pump and pump_client is not None:
        from paper_live.pump_enrich import _prior_creates_for_creator

        priors = _prior_creates_for_creator(
            creator,
            this_mint=mint,
            client=pump_client,
            window_days=30,
            as_of=create_ts,
        )
        return ResolvedCreatorPriors(
            source=CREATOR_PRIOR_SOURCE_PUMP,
            exact_overlay=None,
            prior_creates=list(priors or []),
            path=None,
        )

    # D) Store missing/empty → counts 0 via empty prior list
    return ResolvedCreatorPriors(
        source=CREATOR_PRIOR_SOURCE_NONE,
        exact_overlay=None,
        prior_creates=[],
        path=idx.path,
    )


def clear_creator_prior_cache() -> None:
    global _CACHE
    _CACHE = None


def creator_prior_index_status(path: Path | None = None) -> dict[str, Any]:
    """Audit: train cohort on disk → ready; else closest fallback + incomplete flag."""
    idx = load_creator_prior_index(path=path)
    incomplete = idx.source != CREATOR_PRIOR_SOURCE_TRAIN or idx.n_rows <= 0
    return {
        "source": idx.source,
        "path": idx.path,
        "n_rows": idx.n_rows,
        "n_creators": len(idx.by_creator),
        "incomplete": incomplete,
        "note": (
            "train_store_v1 from Dune q5b/expand_v2 on disk"
            if not incomplete
            else "missing Dune cohort CSV — pump_frontend_30d/none is closest; flag incomplete"
        ),
    }

def exact_meta_for_mint(
    mint: str,
    *,
    index: CreatorPriorIndex | None = None,
) -> dict[str, float | None] | None:
    """Lookup train-store name/symbol meta for ``mint`` (None if not in store)."""
    idx = index if index is not None else load_creator_prior_index()
    return idx.exact_meta_for_mint(mint)

