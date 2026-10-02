from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ingestion.pump_constants import DEFINITION_VERSION
from verification.capture_v1 import verify_capture_schema, verify_idempotent_capture_ids, verify_no_future_reads
from verification.errors import CaptureSchemaError


def _valid_event(**overrides):
    base = {
        "capture_id": "c1",
        "mint": "Mint111",
        "t0_iso": "2024-06-01T12:00:00+00:00",
        "slot0": 100,
        "sig0": "sig",
        "mc0": 12_000.0,
        "p0": 1e-8,
        "sol_usd": 150.0,
        "sol_usd_source": "pyth",
        "vs": 30_000_000_000,
        "vt": 1_000_000_000_000_000,
        "rs": 0,
        "rt": 793_100_000_000_000,
        "complete": False,
        "definition_version": DEFINITION_VERSION,
        "capture_quality": "HIGH",
        "snapshot_hash": "abc",
    }
    base.update(overrides)
    return base


def test_schema_ok():
    verify_capture_schema(_valid_event())


def test_schema_rejects_complete_true():
    with pytest.raises(CaptureSchemaError, match="complete"):
        verify_capture_schema(_valid_event(complete=True))


def test_schema_rejects_mc_out_of_range():
    with pytest.raises(CaptureSchemaError, match="mc0"):
        verify_capture_schema(_valid_event(mc0=25_000))


def test_schema_rejects_naive_t0():
    with pytest.raises(CaptureSchemaError, match="timezone"):
        verify_capture_schema(_valid_event(t0_iso=datetime(2024, 6, 1, 12, 0, 0)))


def test_idempotent_dupes():
    with pytest.raises(CaptureSchemaError, match="duplicados"):
        verify_idempotent_capture_ids(["a", "b", "a"])


def test_no_future_reads():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    verify_no_future_reads([t0 - timedelta(seconds=5), t0], t0)
    with pytest.raises(CaptureSchemaError, match="post-T0"):
        verify_no_future_reads([t0 + timedelta(seconds=1)], t0)


def test_high_rejects_non_pyth():
    with pytest.raises(CaptureSchemaError, match="pyth"):
        verify_capture_schema(_valid_event(sol_usd_source="jupiter", capture_quality="HIGH"))


def test_med_allows_fallback_source():
    verify_capture_schema(_valid_event(sol_usd_source="jupiter", capture_quality="MED"))
