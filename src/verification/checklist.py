"""Checklist ejecutable V1–V8 (espejo de cycle0/protocolos-verificacion.md).

Cada item tiene id estable, protocolo, descripción y estado:
- implemented: hay assert/función en src/verification
- stub: contrato listo; falta fixture o wiring Cycle 1
- manual: review humano (PR)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Literal

Status = Literal["implemented", "stub", "manual"]


@dataclass(frozen=True)
class CheckItem:
    id: str
    protocol: str  # V1..V8
    description: str
    status: Status
    hook: str | None = None  # nombre de función pública si aplica


# --- V1 Capture ---
V1_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V1.schema.required", "V1", "Campos obligatorios CaptureEvent", "implemented", "verify_capture_schema"),
    CheckItem("V1.schema.complete_false", "V1", "complete == false en aceptados", "implemented", "verify_capture_schema"),
    CheckItem("V1.schema.mc_range", "V1", "8000 ≤ mc0 ≤ 20000", "implemented", "verify_capture_schema"),
    CheckItem("V1.schema.definition_version", "V1", 'definition_version == "v0.3" (FROZEN captura)', "implemented", "verify_capture_schema"),
    CheckItem("V1.schema.oracle_pyth", "V1", "Oracle SOL/USD FROZEN = Pyth; HIGH exige sol_usd_source=pyth", "implemented", "assert_oracle_frozen"),
    CheckItem("V1.unit.no_future_candles", "V1", "Detector no lee trades/candles post-T0", "stub", "verify_no_future_reads"),
    CheckItem("V1.unit.first_cross", "V1", "Primer cruce MC [5k,7k,9k,12k] → T0 en 9k", "stub", None),
    CheckItem("V1.unit.overshoot", "V1", "Primera vista 25k → OVERSHOT", "stub", None),
    CheckItem("V1.unit.graduated", "V1", "complete=true → rechazo", "stub", None),
    CheckItem("V1.unit.migrated", "V1", "Migrado PumpSwap → rechazo", "stub", None),
    CheckItem("V1.unit.tradeable_N", "V1", "tradeable <30s no captura; ≥30s sí", "stub", None),
    CheckItem("V1.unit.idempotent", "V1", "Segundo pase no duplica capture_id", "stub", "verify_idempotent_capture_ids"),
    CheckItem("V1.unit.sol_usd_immutable", "V1", "Cambio SOL_USD no reescribe capturas", "stub", None),
    CheckItem("V1.golden.mints", "V1", "≥3 mints históricos en tests/fixtures/captures/", "stub", None),
    CheckItem("V1.golden.snapshot_hash", "V1", "Hash snapshot BC == fixture", "stub", None),
    CheckItem("V1.golden.mc_diff", "V1", "Diff MC0 vs indexador ≤2%", "stub", None),
)

# --- V2 Joins ---
V2_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V2.feature_ts_leq_t0", "V2", "feature_ts ≤ t0 (o slot ≤ slot0)", "implemented", "assert_all_feature_ts_leq_t0"),
    CheckItem("V2.reject_future_row", "V2", "Fila ts=t0+1s → fail/descarta", "implemented", "assert_all_feature_ts_leq_t0"),
    CheckItem("V2.reject_latest_no_ts", "V2", "holder_count 'latest' sin ts → rechazo", "implemented", "assert_feature_rows_have_ts"),
    CheckItem("V2.asof_backward_only", "V2", "asof_join direction=backward únicamente", "implemented", "assert_asof_backward_only"),
    CheckItem("V2.staleness_audit", "V2", "Log % filas stale > max_staleness", "implemented", "assert_staleness"),
    CheckItem("V2.first_join_sample", "V2", "Primer join sample: sin labels; si hay t0 → feature_ts≤t0", "implemented", "audit_bitquery_candidate_sample"),
    CheckItem("V2.enriched_lookahead", "V2", "Enriched: prices ts>t0; features≤t0 si existen; sin label cols", "implemented", "audit_enriched_capture_sample"),
)

# --- V3 Leakage ---
V3_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V3.labels_separate", "V3", "labels sin merge automático a X_train", "manual", None),
    CheckItem("V3.column_disjoint", "V3", "feature_columns ∩ label_columns == ∅", "implemented", "assert_feature_label_column_disjoint"),
    CheckItem("V3.whitelist_train", "V3", "X_train solo columnas P0/P1 whitelisteadas", "implemented", "assert_train_columns_whitelisted"),
    CheckItem("V3.label_window", "V3", "Labels con precios ts > t0", "implemented", "assert_label_window_strictly_after_t0"),
    CheckItem("V3.primary_30d", "V3", "PRIMARY FROZEN = hit_10x_30d (secundarias 1h/6h/24h/7d)", "implemented", None),
    CheckItem("V3.adversarial_max_mc", "V3", "max_mc_24h en features → fail_leakage", "implemented", "fail_if_label_like_in_features"),
    CheckItem("V3.model_feature_names", "V3", "Modelo no pide columna label-*", "implemented", None),
)

# --- V4 Walk-forward ---
V4_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V4.split_by_t0", "V4", "Split por tiempo de T0", "implemented", "assert_walk_forward_order"),
    CheckItem("V4.order", "V4", "train_end < val_start < test_start", "implemented", "assert_walk_forward_order"),
    CheckItem("V4.embargo", "V4", "gap ≥ H_label (=30d PRIMARY) entre train y val", "implemented", "assert_walk_forward_order"),
    CheckItem("V4.mint_one_split", "V4", "Un mint/T0 no cruza splits", "implemented", "assert_mint_single_split"),
    CheckItem("V4.purge", "V4", "Purge train cuyo horizon solapa val (backtest.purge_train_overlapping_val)", "implemented", None),
    CheckItem("V4.primary_embargo_30d", "V4", "default_embargo() == 30d (= PRIMARY)", "implemented", None),
)

# --- V5 DRY ---
V5_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V5.mc_single_impl", "V5", "mc_usd solo en capture/math.py", "implemented", "assert_mc_single_impl"),
    CheckItem("V5.parsers_once", "V5", "Parsers Pump IDL no duplicados", "manual", None),
    CheckItem("V5.constants_once", "V5", "Constantes Global en pump_constants.py", "implemented", "assert_constants_module"),
    CheckItem("V5.sol_usd_one_source", "V5", "No SOL_USD hardcode distinto labeling vs capture", "stub", None),
    CheckItem("V5.notebooks_call_modules", "V5", "Notebooks no reimplementan detector", "manual", None),
    CheckItem("V5.denylist_names", "V5", "Denylist compute_market_cap / bonding_curve_price fuera de math", "implemented", "assert_no_denylist_dupes"),
    CheckItem("V5.secrets_no_leak", "V5", "No fuga Helius/Bitquery tokens en src/tests/cycle0/data", "implemented", "assert_no_secret_leakage"),
    CheckItem("V5.bitquery_auth_redacted", "V5", "Sample Bitquery meta con Bearer placeholder", "implemented", "assert_bitquery_sample_auth_redacted"),
)

# --- V6 E2E ---
V6_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V6.fixture_tar", "V6", "Fixture tar raw+snapshots+oracle", "stub", None),
    CheckItem("V6.pipeline_run", "V6", "ingestion→capture→features→labels offline", "stub", "run_golden_e2e"),
    CheckItem("V6.golden_json", "V6", "Outputs vs golden (tol 1e-6 / 1%)", "stub", None),
    CheckItem("V6.snapshot_hash", "V6", "snapshot_hash run == esperado", "stub", None),
    CheckItem("V6.bitquery_smoke", "V6", "Smoke sample Bitquery n=50 MC 8k–20k presente + audit", "implemented", "audit_bitquery_candidate_sample"),
)

# --- V7 Repro ---
V7_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V7.seed", "V7", "SEED fijo", "implemented", "assert_seed_set"),
    CheckItem("V7.manifest_hashes", "V7", "SHA256 particiones leídas", "stub", "repro_check"),
    CheckItem("V7.versions_on_artifact", "V7", "definition/feature/code_git_sha en artefacto", "implemented", "assert_artifact_versions"),
    CheckItem("V7.oracle_immutable", "V7", "Oracle SOL series versionada por día", "stub", None),
    CheckItem("V7.lockfile", "V7", "pyproject + lock idéntico", "manual", None),
    CheckItem("V7.cli", "V7", "python -m verification.repro_check --run-id", "stub", "repro_check"),
)

# --- V8 Live ---
V8_ITEMS: tuple[CheckItem, ...] = (
    CheckItem("V8.zero_capture_alert", "V8", "Alerta tasa captura 0 en 15m", "stub", None),
    CheckItem("V8.low_quality_alert", "V8", "Alerta % LOW > 40%", "stub", None),
    CheckItem("V8.complete_true_alert", "V8", "Alerta complete=true en stream", "stub", None),
    CheckItem("V8.mc0_drift", "V8", "Drift mc0 vs semana previa", "stub", None),
)

ALL_ITEMS: tuple[CheckItem, ...] = (
    V1_ITEMS + V2_ITEMS + V3_ITEMS + V4_ITEMS + V5_ITEMS + V6_ITEMS + V7_ITEMS + V8_ITEMS
)


def items_by_protocol(protocol: str) -> tuple[CheckItem, ...]:
    return tuple(i for i in ALL_ITEMS if i.protocol == protocol)


def checklist_summary() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for item in ALL_ITEMS:
        bucket = out.setdefault(item.protocol, {"implemented": 0, "stub": 0, "manual": 0, "total": 0})
        bucket[item.status] += 1
        bucket["total"] += 1
    return out


def checklist_as_dicts(items: Iterable[CheckItem] | None = None) -> list[dict]:
    src = ALL_ITEMS if items is None else items
    return [asdict(i) for i in src]
