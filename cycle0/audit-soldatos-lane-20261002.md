# SolAuditor — audit SolDatos Pump data-pipeline lane (2026-10-02)

**Auditor:** SolAuditor (zero-shortcuts · read/verify only)  
**Date:** 2026-10-02 ~14:18 CEST (Europe/Madrid)  
**Lane under audit:** SolDatos — unified Path A Pump data pipeline + ORPHAN scale mark  
**Constraints honored:** no paper restart · no PID kill · no modify `q5b_last` / `q5b_calibration.json` · 0 Dune

## Sources reviewed

| # | Path | Present? |
|---|------|----------|
| 1 | `cycle0/path-a-pump-data-pipeline-20261002.md` | YES (~14:15 CEST) |
| 2 | `cycle0/diagnostics/path-a-pump-cache-inventory-20261002.json` | YES |
| 3 | `scripts/pump_path_a_common.py` | YES |
| 4 | `scripts/build_pump_path_a.py` | YES (thin CLI dispatcher) |
| 5 | `scripts/build_pump_mcband_scale.py` | YES — header **ORPHAN / DEPRECATED** |
| 6 | `tests/paper_live/test_path_a_pump_pipeline.py` | YES (11 tests) |
| 7 | `tests/paper_live/test_pump_true_features_offline.py` | YES (3 tests; with pipeline → 14) |

## Checklist operativo (PASS/FAIL)

| Gate | Verdict | Evidence |
|------|---------|----------|
| **Código** | **PASS** | Canonical CLI `build_pump_path_a.py` (inventory/livelike/mcband/pilot500/offline; `scale` refused unless `--force-orphan`). Shared helpers in `pump_path_a_common.py` (`ORPHAN_SCRIPTS`, ordered caches, USD-scale-off invariant). Scale script docstring + `ORPHAN_STATUS` print on entry. |
| **Tests** | **PASS** | Independent re-run ~14:17 CEST: `test_path_a_pump_pipeline.py` → **11 passed**; pipeline + `test_pump_true_features_offline.py` → **14 passed**. Matches claimed 11/11 + 14/14. |
| **Nota** | **PASS** | Pipeline architecture note + cache inventory JSON (`orphan_mcband_scale.status=ORPHAN_INCOMPLETE`, `mcband_scale` matrix/usable **false**). |
| **Integridad paper / q5b_last** | **PASS** | PID **121466** untouched. `q5b_last` md5 `4df6d5a8…` / sha256 `9908b936…`. Calib md5 `586e2af…`. No train/swap from this lane. |

### Verdict operativo lane SolDatos pipeline

**PASS** — unified entrypoint + orphan mark + cache inventory + tests green + paper/q5b intact.

### Inventory follow-ons (not automatic closes)

| id | After this lane | Why |
|----|-----------------|-----|
| **D-07** | still **FAIL** (not full DoD) | Orphan **documented** + CLI refuse + tests, but residual fetch **PID 112910** `build_pump_mcband_scale.py` **still running** (DoD: stop residual fetch). No features/usable matrix (correct). |
| **D-04** | still **FAIL** | Duplicate `build_pump_*` pilots still live under `scripts/` (not archived); CLI consolidates but forest not quarantined to `archive/`. |
| **D-11** | still **FAIL** | Formal `path-a-ws3-residual-accept-20261002.md` **missing**. |
| **D-01** | still **FAIL** | Pipeline ≠ score-mass lift; livelike/mcband still NO-GO vs GO criterion. |
| **D-05** | remains **GO** (accept) | USD scale OFF asserted in tests; residual-parity prior accepts unchanged. |

## Independent verification notes

- Cache inventory on disk: pilot500=495 · mcband_extra=45 · scale=807 (orphan) · scale_deep=0 · livelike=221.
- Matrices: pilot500/mcband/livelike **present**; `features_pump_path_a_mcband_scale_*` **absent** (required for orphan honesty).
- Observational (not a lane FAIL): orphan scale fetch PID 112910 still filling trade cache — left alone by SolDatos; **not** paper. Auditor did not kill it.

## Non-actions

- No paper restart/kill (PID 121466).
- No kill of scale fetch PID 112910 (out of audit mutate scope; flagged for D-07).
- No `q5b_last` / calibration overwrite or swap.
- 0 Dune API calls.
