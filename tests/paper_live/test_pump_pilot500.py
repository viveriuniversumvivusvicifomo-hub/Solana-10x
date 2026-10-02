"""Unit tests for Pump Path A pilot500 helpers (no network)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "build_pump_path_a_pilot500",
        ROOT / "scripts/build_pump_path_a_pilot500.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_sample_expand_mints_stratified(tmp_path: Path):
    mod = _load()
    # tiny synthetic expand+labels
    n = 200
    rows = []
    for i in range(n):
        rows.append(
            {
                "mint": f"Mint{i:04d}pumpxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump",
                "t0_ts": f"2026-09-{(i % 20) + 1:02d}T12:00:00+00:00",
                "mc_usd_t0": 10000.0,
                "create_ts": f"2026-09-{(i % 20) + 1:02d}T11:59:00+00:00",
                "creator_pubkey": f"C{i}",
                "buy_vol_usd_60s": float(i),
                "age_s": 60.0,
                "age_min": 1.0,
                "age_proxy_s": 60.0,
                "has_creator": 1,
                "name_len": 4,
                "name_missing": 0,
                "symbol_len": 3,
                "symbol_missing": 0,
                "creator_prior_mints_7d": 0,
                "creator_prior_mints_30d": 0,
                "creator_prior_mints_cohort": 0,
                "creator_prior_mints_all_in_window": None,
            }
        )
    feat = pd.DataFrame(rows)
    # fill remaining +q5b zeros
    from features.post_q5_sets import FEATURE_SETS

    for c in FEATURE_SETS["+q5b"]:
        if c not in feat.columns:
            feat[c] = 0.0
    lab = pd.DataFrame(
        {
            "mint": feat["mint"],
            "hit_10x_30d": [1 if i % 7 == 0 else 0 for i in range(n)],
            "hit_200k": [1 if i % 7 == 0 else 0 for i in range(n)],
        }
    )
    fp = tmp_path / "f.csv"
    lp = tmp_path / "l.csv"
    feat.to_csv(fp, index=False)
    lab.to_csv(lp, index=False)
    sample = mod.sample_expand_mints(fp, lp, n=40, t0_min="2026-09-01", seed=0)
    assert len(sample) == 40
    assert abs(sample["hit_10x_30d"].mean() - lab["hit_10x_30d"].mean()) < 0.08
    meta = sample.attrs["sample_meta"]
    assert meta["t0_policy"] == "expand_t0_ts"
    assert meta["n_sampled"] == 40


def test_fetch_trades_until_t0_stops_on_pre_t0_coverage():
    mod = _load()

    class FakeClient:
        def __init__(self):
            self.n = 0
            self.log = type("L", (), {"n_calls": 0, "n_retries_429": 0, "to_dict": lambda self: {}})()

        def get_json(self, path, params=None):
            self.n += 1
            self.log.n_calls += 1
            # page1: all after t0; page2: straddles; page3: 20m before t0
            t0_ms = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc).timestamp() * 1000
            if self.n == 1:
                trades = [
                    {"blockTimeMs": t0_ms + 60_000, "side": "buy", "valueUsd": 1},
                    {"blockTimeMs": t0_ms + 30_000, "side": "buy", "valueUsd": 1},
                ]
                return {"trades": trades, "cursor": "c1"}
            if self.n == 2:
                trades = [
                    {"blockTimeMs": t0_ms + 5_000, "side": "buy", "valueUsd": 1},
                    {"blockTimeMs": t0_ms - 5_000, "side": "buy", "valueUsd": 1},
                ]
                return {"trades": trades, "cursor": "c2"}
            trades = [
                {"blockTimeMs": t0_ms - 20 * 60_000, "side": "buy", "valueUsd": 1},
                {"blockTimeMs": t0_ms - 25 * 60_000, "side": "buy", "valueUsd": 1},
            ]
            return {"trades": trades, "cursor": "c3"}

    client = FakeClient()
    t0 = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    raw, meta = mod.fetch_trades_until_t0("MintX", t0, client=client, max_pages=10)
    assert meta["reached_t0"] is True
    assert meta["n_pages"] == 3
    assert len(raw) == 6
