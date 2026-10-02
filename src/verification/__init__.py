"""Verification — gates V1–V8 (cycle0/protocolos-verificacion.md).

Contrato
--------
- CLI: ``python -m verification --run-id <id>`` → JSON pass/fail (exit != 0 bloquea).
- Fallo de leakage o look-ahead → excepción / exit != 0.

API pública
-----------
"""

from verification.capture_v1 import (
    assert_oracle_frozen,
    verify_capture_schema,
    verify_idempotent_capture_ids,
    verify_no_future_reads,
    verify_sol_usd_source,
)
from verification.checklist import ALL_ITEMS, checklist_as_dicts, checklist_summary
from verification.dry_v5 import assert_constants_module, assert_mc_single_impl, assert_no_denylist_dupes
from verification.e2e_v6 import run_golden_e2e
from verification.errors import (
    CaptureSchemaError,
    DryError,
    LeakageError,
    LookAheadError,
    ReproError,
    VerificationError,
    WalkForwardError,
)
from verification.joins_v2 import (
    assert_all_feature_ts_leq_t0,
    assert_asof_backward_only,
    assert_feature_rows_have_ts,
    assert_staleness,
)
from verification.leakage_v3 import (
    assert_feature_label_column_disjoint,
    assert_label_window_strictly_after_t0,
    assert_train_columns_whitelisted,
    fail_if_label_like_in_features,
)
from verification.live_v8 import check_live_alerts
from verification.repro_v7 import assert_artifact_versions, assert_seed_set, repro_check
from verification.runner import build_report, run_static_gates
from verification.sample_join_v2 import assert_first_join_no_lookahead, audit_bitquery_candidate_sample, audit_enriched_capture_sample
from verification.secrets import SecretsLeakError, assert_bitquery_sample_auth_redacted, assert_no_secret_leakage
from verification.walkforward_v4 import assert_mint_single_split, assert_walk_forward_order

__all__ = [
    "ALL_ITEMS",
    "assert_oracle_frozen",
    "assert_bitquery_sample_auth_redacted",
    "assert_first_join_no_lookahead",
    "assert_no_secret_leakage",
    "audit_bitquery_candidate_sample",
    "audit_enriched_capture_sample",
    "SecretsLeakError",
    "CaptureSchemaError",
    "DryError",
    "LeakageError",
    "LookAheadError",
    "ReproError",
    "VerificationError",
    "WalkForwardError",
    "assert_all_feature_ts_leq_t0",
    "assert_artifact_versions",
    "assert_asof_backward_only",
    "assert_constants_module",
    "assert_feature_label_column_disjoint",
    "assert_feature_rows_have_ts",
    "assert_label_window_strictly_after_t0",
    "assert_mc_single_impl",
    "assert_mint_single_split",
    "assert_no_denylist_dupes",
    "assert_seed_set",
    "assert_staleness",
    "assert_train_columns_whitelisted",
    "assert_walk_forward_order",
    "build_report",
    "check_live_alerts",
    "checklist_as_dicts",
    "checklist_summary",
    "fail_if_label_like_in_features",
    "repro_check",
    "run_golden_e2e",
    "run_static_gates",
    "verify_capture_schema",
    "verify_idempotent_capture_ids",
    "verify_no_future_reads",
]
