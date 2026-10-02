"""Offline Pump-true feature builder — no network, no Dune."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_column_map_covers_q5b_recipe():
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    # load module by path
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_pump_true_features_offline",
        ROOT / "scripts/build_pump_true_features_offline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    from features.post_q5_sets import FEATURE_SETS

    colmap = mod.build_column_map()
    covered = set(colmap["coverage_check"]["identical_plus_remapped_plus_null"])
    missing = colmap["coverage_check"]["missing_from_taxonomy"]
    # buy_vol is identical; all recipe cols must be classified
    assert missing == [], missing
    assert set(FEATURE_SETS["+q5b"]) <= covered | {"buy_vol_usd_60s"} or set(
        FEATURE_SETS["+q5b"]
    ) <= covered
    # Explicit: all_in_window null-on-live
    assert "creator_prior_mints_all_in_window" in colmap["null_on_live"]
    # age_proxy remapped (overwrite)
    assert "age_proxy_s" in colmap["remapped"]


def test_extract_journal_pump_scoreable_roundtrip(tmp_path: Path):
    import importlib.util
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location(
        "build_pump_true_features_offline",
        ROOT / "scripts/build_pump_true_features_offline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    db = tmp_path / "j.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        """CREATE TABLE sightings (
        mint TEXT, t0_ts TEXT, mc_usd_t0 REAL, name TEXT, symbol TEXT, source TEXT,
        features_json TEXT, score REAL, score_mode TEXT, paper_candidate INTEGER,
        created_at TEXT, scores_json TEXT, score_lite REAL)"""
    )
    feats = {
        "t0_definition": "pump_mc_band_sighting_v1",
        "capture_scoreable": True,
        "buy_vol_usd_60s": 12.5,
        "age_s": 40.0,
        "age_min": 40.0 / 60.0,
        "age_proxy_s": 40.0,
        "has_creator": 1,
        "name_len": 4,
        "name_missing": 0,
        "symbol_len": 3,
        "symbol_missing": 0,
        "creator_prior_mints_7d": 0,
        "creator_prior_mints_30d": 0,
        "creator_prior_mints_cohort": 0,
        "creator_prior_mints_all_in_window": None,
        "sol_usd_source": "pump_frontend",
        "creator_prior_source": None,
    }
    # fill remaining +q5b with 0 so CSV write is happy
    from features.post_q5_sets import FEATURE_SETS

    for c in FEATURE_SETS["+q5b"]:
        feats.setdefault(c, 0 if c != "creator_prior_mints_all_in_window" else None)
    con.execute(
        "INSERT INTO sightings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "MintTestpumpxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump",
            "2026-10-02T08:00:00+00:00",
            9000.0,
            "T",
            "T",
            "pump",
            json.dumps(feats),
            0.1,
            "skip_prior_not_train",
            0,
            "2026-10-02T10:00:00+02:00",
            None,
            None,
        ),
    )
    con.commit()
    con.close()

    rows = mod.extract_journal_rows(db, scoreable_only=True, since="2026-10-02")
    assert len(rows) == 1
    assert rows[0]["mint"].startswith("MintTest")
    assert rows[0]["buy_vol_usd_60s"] == 12.5
    assert rows[0]["sol_usd_source"] == "pump_frontend"

    labels = {"MintTestpumpxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump": {"hit_10x_30d": "1", "hit_200k": "0"}}
    rows, stats = mod.join_labels(rows, labels)
    assert stats["n_label_join"] == 1
    out = tmp_path / "out.csv"
    mod.write_csv(out, rows)
    with out.open() as f:
        r = list(csv.DictReader(f))
    assert len(r) == 1
    assert r[0]["label_hit_10x_30d"] == "1"


def test_full_rebuild_plan_has_cost_fence():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "build_pump_true_features_offline",
        ROOT / "scripts/build_pump_true_features_offline.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    plan = mod.estimate_full_rebuild()
    assert plan["dune_credits"] == 0
    assert "STOP" in plan["cost_fence"]
    assert plan["estimated_http_requests"] > 0
