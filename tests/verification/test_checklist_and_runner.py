from __future__ import annotations

from verification.checklist import ALL_ITEMS, checklist_summary
from verification.runner import build_report, run_static_gates


def test_checklist_covers_v1_v8():
    protocols = {i.protocol for i in ALL_ITEMS}
    assert protocols == {"V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8"}
    summary = checklist_summary()
    assert summary["V2"]["implemented"] >= 4


def test_static_gates_pass():
    gates = run_static_gates()
    assert all(g.ok for g in gates)
    report = build_report(run_id="test")
    assert report["ok"] is True
    assert report["checklist_n"] == len(ALL_ITEMS)


def test_primary_frozen_30d_in_checklist():
    from labeling.horizons import PRIMARY_HORIZON
    from verification.checklist import ALL_ITEMS
    from verification.leakage_v3 import DEFAULT_LABEL_COLUMNS

    assert PRIMARY_HORIZON == "30d"
    ids = {i.id for i in ALL_ITEMS}
    assert "V3.primary_30d" in ids
    assert "V4.primary_embargo_30d" in ids
    assert "hit_10x_30d" in DEFAULT_LABEL_COLUMNS
    v1_def = next(i for i in ALL_ITEMS if i.id == "V1.schema.definition_version")
    assert "v0.3" in v1_def.description


def test_oracle_pyth_frozen_in_checklist():
    from ingestion.pump_constants import SOL_USD_SOURCE, SOL_USD_SOURCE_FROZEN
    from verification.capture_v1 import assert_oracle_frozen

    assert SOL_USD_SOURCE == "pyth"
    assert SOL_USD_SOURCE_FROZEN is True
    assert_oracle_frozen()
    ids = {i.id for i in ALL_ITEMS}
    assert "V1.schema.oracle_pyth" in ids
