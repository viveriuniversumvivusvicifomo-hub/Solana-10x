from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from verification.errors import LookAheadError
from verification.sample_join_v2 import assert_first_join_no_lookahead, audit_bitquery_candidate_sample
from verification.secrets import (
    SecretsLeakError,
    assert_bitquery_sample_auth_redacted,
    assert_no_secret_leakage,
    scan_text_for_secrets,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE = ROOT / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json"


def test_scan_allows_placeholder():
    text = '{"auth": "Authorization: Bearer <BITQUERY_TOKEN>"}'
    assert scan_text_for_secrets(text) == []


def test_scan_flags_real_bearer():
    # Construir en runtime para no dejar un falso positivo en el escaneo del repo
    token = "abcd" + "efghijklmnopqr_secret_token_xx"
    text = "Authorization: Bearer " + token
    assert scan_text_for_secrets(text)


def test_repo_no_secret_leakage():
    stats = assert_no_secret_leakage(repo_root=ROOT)
    assert stats["hits"] == 0
    assert stats["files_scanned"] > 0


def test_bitquery_sample_auth_redacted():
    assert_bitquery_sample_auth_redacted(SAMPLE)


def test_audit_sample_no_lookahead_columns():
    report = audit_bitquery_candidate_sample(SAMPLE)
    assert report["n"] == 50
    assert report["ok"] is True
    assert report["join_lookahead"] == "skipped_no_t0"
    assert report["label_columns_present"] is False


def test_first_join_rejects_future_feature():
    t0 = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(LookAheadError):
        assert_first_join_no_lookahead(
            [{"feature_ts": t0 + timedelta(seconds=1)}],
            t0=t0,
        )


def test_audit_enriched_lookahead():
    from verification.sample_join_v2 import audit_enriched_capture_sample

    report = audit_enriched_capture_sample()
    assert report["ok"] is True
    assert report["n"] == 2
    assert report["has_capture_t0"] is True
