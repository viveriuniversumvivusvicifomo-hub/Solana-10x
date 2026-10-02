"""Focused Path A Pump pipeline tests (SolDatos).

Ownership: pipeline invariants + cache schema — NOT SolQA V1–V8 wholesale.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_common():
    spec = importlib.util.spec_from_file_location(
        "pump_path_a_common",
        ROOT / "scripts/pump_path_a_common.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_usd_scale_6_6_off_forever(monkeypatch):
    monkeypatch.delenv("APPLY_DUNE_HELIUS_USD_SCALE", raising=False)
    monkeypatch.delenv("DUNE_HELIUS_USD_SCALE", raising=False)
    common = _load_common()
    assert common.USD_SCALE_6_6_OFF_FOREVER is True
    assert common.APPLY_DUNE_HELIUS_USD_SCALE_DEFAULT is False
    common.assert_usd_scale_off()
    from ingestion.sol_usd_oracle import maybe_scale_usd, apply_dune_helius_usd_scale_enabled

    assert apply_dune_helius_usd_scale_enabled() is False
    assert maybe_scale_usd(123.45) == 123.45


def test_usd_scale_on_is_rejected(monkeypatch):
    monkeypatch.setenv("APPLY_DUNE_HELIUS_USD_SCALE", "1")
    # clear lru/dotenv caches if any by reimport path
    import ingestion.sol_usd_oracle as oracle

    assert oracle.apply_dune_helius_usd_scale_enabled() is True
    common = _load_common()
    with pytest.raises(RuntimeError, match="OFF forever"):
        common.assert_usd_scale_off()
    monkeypatch.delenv("APPLY_DUNE_HELIUS_USD_SCALE", raising=False)


def test_mcband_scale_marked_orphan():
    common = _load_common()
    inv = common.cache_inventory("20261002")
    orphan = inv["orphan_mcband_scale"]
    assert orphan["status"] == "ORPHAN_INCOMPLETE"
    assert orphan["do_not_train_on"] is True
    assert orphan["has_matrix"] is False
    assert orphan["has_usable"] is False
    assert orphan.get("quarantined") is True
    # sample lives in quarantine (historical seed for livelike universe)
    assert orphan["has_sample"] is True
    assert orphan["sample_path"] is not None
    assert "quarantine" in orphan["sample_path"]
    assert orphan["n_trades"] >= 0
    assert inv["default_cache_excludes_scale"] is True


def test_mcband_scale_quarantine_dir_and_readme():
    common = _load_common()
    q = common.quarantine_mcband_scale_dir(stamp="20261002")
    assert q.is_dir(), f"missing quarantine dir {q}"
    readme = q / "NO-GO_INCOMPLETE.md"
    assert readme.is_file()
    body = readme.read_text()
    assert "NO-GO" in body
    assert "incomplete" in body.lower() or "INCOMPLETE" in body
    # samples/ must not still hold live scale dirs
    assert not (ROOT / "data/samples/pump_mcband_scale_trades_20261002").exists()
    assert not (ROOT / "data/samples/pump_mcband_scale_sample_20261002.csv").exists()


def test_no_mcband_scale_in_canonical_invariants():
    common = _load_common()
    inv = common.path_a_invariants()
    assert "livelike" in inv["canonical_train_entry"]
    assert "build_pump_mcband_scale.py" in inv["orphan_scripts"]
    assert inv["orphan_scripts"]["build_pump_mcband_scale.py"].get("quarantined") is True
    assert inv["dune_api_allowed"] is False
    assert inv["usd_live"] == "sol_amt * pyth_asof"


def test_ordered_cache_dirs_excludes_scale_by_default():
    common = _load_common()
    dirs = common.ordered_cache_dirs("20261002")
    names = [p.name for p in dirs]
    assert names[0].startswith("pump_livelike_trades_")
    assert names[-1].startswith("pump_pilot500_trades_")
    assert not any("mcband_scale" in n for n in names)


def test_ordered_cache_dirs_reuse_orphan_scale_opt_in():
    common = _load_common()
    dirs = common.ordered_cache_dirs("20261002", reuse_orphan_scale=True)
    names = [p.name for p in dirs]
    assert names[0].startswith("pump_livelike_trades_")
    assert any(n.startswith("pump_mcband_scale_trades_20261002") and "deep" not in n for n in names)
    # quarantine path present
    assert any("quarantine" in str(p) for p in dirs if "mcband_scale_trades" in p.name)


def test_trade_cache_schema_on_disk():
    common = _load_common()
    stamp = "20261002"
    # pick first existing cache with files
    named = common.cache_dirs_for_stamp(stamp)
    checked = 0
    for kind, d in named.items():
        if not d.is_dir():
            continue
        files = sorted(d.glob("*.json"))[:2]
        for f in files:
            doc = json.loads(f.read_text())
            errs = common.validate_trade_cache_doc(doc)
            assert errs == [], f"{kind} {f.name}: {errs}"
            checked += 1
    if checked == 0:
        pytest.skip("no trade caches on disk")
    assert checked >= 1


def test_resolve_trades_across_unified_caches(tmp_path: Path):
    common = _load_common()
    pilot = tmp_path / "pilot"
    scale = tmp_path / "scale"
    live = tmp_path / "live"
    for d in (pilot, scale, live):
        d.mkdir()
    mint = "MintTestpumpxxxxxxxxxxxxxxxxxxxxxxxxxxxxpump"
    # only pilot has it
    (pilot / f"{mint}.json").write_text(
        json.dumps({"mint": mint, "trades": [{"blockTimeMs": 1, "valueUsd": 1.0, "side": "buy"}]})
    )
    got = common.resolve_trades_path(mint, [live, scale, pilot])
    assert got == pilot / f"{mint}.json"
    # livelike wins when present
    (live / f"{mint}.json").write_text(
        json.dumps({"mint": mint, "trades": [{"blockTimeMs": 2, "valueUsd": 2.0, "side": "buy"}]})
    )
    got2 = common.resolve_trades_path(mint, [live, scale, pilot])
    assert got2 == live / f"{mint}.json"
    raw = common.load_raw(got2)
    assert len(raw) == 1 and raw[0]["valueUsd"] == 2.0


def test_canonical_cli_inventory():
    spec = importlib.util.spec_from_file_location(
        "build_pump_path_a",
        ROOT / "scripts/build_pump_path_a.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # ensure env scale off
    os.environ.pop("APPLY_DUNE_HELIUS_USD_SCALE", None)
    spec.loader.exec_module(mod)
    rc = mod.main(["inventory", "--stamp", "20261002"])
    assert rc == 0


def test_canonical_cli_refuses_orphan_scale(capsys):
    spec = importlib.util.spec_from_file_location(
        "build_pump_path_a",
        ROOT / "scripts/build_pump_path_a.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    os.environ.pop("APPLY_DUNE_HELIUS_USD_SCALE", None)
    spec.loader.exec_module(mod)
    rc = mod.main(["scale"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "refused_orphan" in out


def test_build_pump_mcband_scale_script_refuses(capsys):
    spec = importlib.util.spec_from_file_location(
        "build_pump_mcband_scale",
        ROOT / "scripts/build_pump_mcband_scale.py",
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    os.environ.pop("APPLY_DUNE_HELIUS_USD_SCALE", None)
    # script parses sys.argv — keep only script name
    old = list(os.sys.argv)
    try:
        os.sys.argv = ["build_pump_mcband_scale.py"]
        spec.loader.exec_module(mod)
        rc = mod.main()
    finally:
        os.sys.argv = old
    assert rc == 2
    out = capsys.readouterr().out
    assert "refused_orphan" in out
    assert "quarantine" in out.lower() or "mcband_scale_20261002" in out


def test_paper_paths_and_q5b_last_untouched():
    q5b = ROOT / "data/paper_live/models/q5b_last.joblib"
    assert q5b.is_file()
    # quarantine must not have overwritten paper model
    assert not (ROOT / "archive/quarantine/mcband_scale_20261002/q5b_last.joblib").exists()
    # sample must not remain under data/samples (moved)
    assert not (ROOT / "data/samples/pump_mcband_scale_sample_20261002.csv").exists()


def test_livelike_no_longer_imports_scale_module():
    text = (ROOT / "scripts/build_pump_path_a_livelike.py").read_text()
    assert "from pump_path_a_common import" in text
    assert "from build_pump_mcband_scale import" not in text


def test_feature_matrices_have_buy_vol_schema():
    import pandas as pd

    for name in (
        "features_pump_path_a_pilot500_20261002.csv",
        "features_pump_path_a_mcband_20261002.csv",
        "features_pump_path_a_livelike_20261002.csv",
    ):
        path = ROOT / "data/samples" / name
        if not path.is_file():
            pytest.skip(f"missing {name}")
        df = pd.read_csv(path, nrows=3)
        assert "buy_vol_usd_60s" in df.columns
        assert "mint" in df.columns
    # orphan matrix must NOT exist
    assert not (ROOT / "data/samples/features_pump_path_a_mcband_scale_20261002.csv").is_file()
