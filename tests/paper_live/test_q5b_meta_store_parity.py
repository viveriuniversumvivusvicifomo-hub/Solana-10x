"""Q5b name/symbol meta: empty create → exact lengths from Dune train store."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from paper_live.creator_priors import clear_creator_prior_cache, load_creator_prior_index
from paper_live.q5b_agg import (
    META_SOURCE_DUNE_STORE_EXACT,
    META_SOURCE_SIGHTING,
    CreateRow,
    fill_meta_from_dune_store_exact,
    prefer_sighting_meta_name_symbol,
    q5b_from_create,
)

EXPAND_V2 = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "samples"
    / "features_dune_p0_q5_expand_v2.csv"
)

MINT_2HCEWY = "2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump"


@pytest.fixture(autouse=True)
def _clear_prior_cache():
    clear_creator_prior_cache()
    yield
    clear_creator_prior_cache()


def test_fill_meta_from_store_dict_when_create_name_empty():
    """Unit: empty create name/symbol + store lengths → store exact meta."""
    t0 = datetime(2026, 9, 22, 1, 41, 6, tzinfo=timezone.utc)
    create = CreateRow(
        mint="MintTest1111111111111111111111111111111",
        creator_pubkey="CreatorTest1111111111111111111111111111",
        create_ts=t0,
        token_name=None,
        token_symbol=None,
    )
    q5b = q5b_from_create(create, t0)
    assert q5b["name_missing"] == 1.0
    assert q5b["symbol_missing"] == 1.0
    assert q5b["name_len"] == 0.0
    assert q5b["symbol_len"] == 0.0

    store = {
        "name_len": 7.0,
        "name_missing": 0.0,
        "symbol_len": 7.0,
        "symbol_missing": 0.0,
    }
    out = fill_meta_from_dune_store_exact(q5b, store)
    assert out["name_len"] == 7.0
    assert out["symbol_len"] == 7.0
    assert out["name_missing"] == 0.0
    assert out["symbol_missing"] == 0.0
    assert out["meta_source"] == META_SOURCE_DUNE_STORE_EXACT


def test_sighting_meta_preferred_over_store():
    """Live sighting name/symbol wins; store fill must not overwrite."""
    t0 = datetime(2026, 9, 22, 1, 41, 6, tzinfo=timezone.utc)
    create = CreateRow(
        mint="MintTest2222222222222222222222222222222",
        creator_pubkey="CreatorTest2222222222222222222222222222",
        create_ts=t0,
        token_name=None,
        token_symbol=None,
    )
    q5b = q5b_from_create(create, t0)
    q5b = prefer_sighting_meta_name_symbol(q5b, name="ABC", symbol="XYZ")
    assert q5b["name_len"] == 3.0
    assert q5b["symbol_len"] == 3.0
    assert q5b["meta_source"] == META_SOURCE_SIGHTING

    store = {
        "name_len": 99.0,
        "name_missing": 0.0,
        "symbol_len": 99.0,
        "symbol_missing": 0.0,
    }
    out = fill_meta_from_dune_store_exact(q5b, store)
    assert out["name_len"] == 3.0
    assert out["symbol_len"] == 3.0
    assert out["meta_source"] == META_SOURCE_SIGHTING


@pytest.mark.skipif(not EXPAND_V2.is_file(), reason="expand_v2 CSV missing")
def test_2hCEWY_empty_create_gets_store_lengths():
    """2hCEWY: empty create → train store name_len=7 / symbol_len=7."""
    idx = load_creator_prior_index()
    store = idx.exact_meta_for_mint(MINT_2HCEWY)
    assert store is not None
    assert store["name_len"] == 7.0
    assert store["symbol_len"] == 7.0
    assert store["name_missing"] == 0.0
    assert store["symbol_missing"] == 0.0

    t0 = datetime(2026, 9, 22, 1, 41, 6, tzinfo=timezone.utc)
    create = CreateRow(
        mint=MINT_2HCEWY,
        creator_pubkey="7Lb4qXuBeQ4qwKBa8uo6gYdfJYvDFKakBs3NoPN6rLZy",
        create_ts=t0,
        token_name=None,
        token_symbol=None,
    )
    q5b = q5b_from_create(create, t0)
    q5b = prefer_sighting_meta_name_symbol(q5b, name=None, symbol=None)
    q5b = fill_meta_from_dune_store_exact(q5b, store)
    assert q5b["name_len"] == 7.0
    assert q5b["symbol_len"] == 7.0
    assert q5b["name_missing"] == 0.0
    assert q5b["symbol_missing"] == 0.0
    assert q5b["meta_source"] == META_SOURCE_DUNE_STORE_EXACT
