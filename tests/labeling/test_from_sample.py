from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from labeling.from_sample import audit_candidate_sample, materialize_from_enriched, write_report_from_sample


def test_audit_real_sample_missing_t0(tmp_path: Path):
    sample = json.loads(
        Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json").read_text()
    )
    n, missing = audit_candidate_sample(sample)
    assert n == 50
    assert "t0" in missing and "prices_after_t0" in missing


def test_write_report_blocker(tmp_path: Path):
    src = Path("/workspace/solana-10x/data/samples/bitquery_pump_mc_8k_20k_sample.json")
    out = tmp_path / "report.json"
    r = write_report_from_sample(sample_path=src, report_path=out)
    assert r.n_candidates == 50
    assert r.n_labeled == 0
    assert r.base_rate_primary is None
    assert r.blocker and "post-T0" in r.blocker
    assert out.exists()


def test_enriched_materialize():
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        {
            "capture_id": "c1",
            "mint": "m1",
            "t0": t0,
            "p0": 1.0,
            "prices_after_t0": [(t0 + timedelta(days=2), 12.0)],
        }
    ]
    flats, rates = materialize_from_enriched(rows)
    assert flats[0]["hit_10x_30d"] is True
    assert rates["30d"] == 1.0
