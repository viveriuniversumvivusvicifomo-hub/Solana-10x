# SolAuditor — Path A debt GO checklist (2026-10-02)

**Auditor:** SolAuditor (zero-shortcuts)  
**Date:** 2026-10-02 ~14:19 CEST (Europe/Madrid)  
**Inventory source (canonical):** `cycle0/path-a-debt-inventory-20261002.md` + `cycle0/diagnostics/debt_inventory_20261002.json` (**BOSS**)  
**Superseded provisional:** `cycle0/path-a-debt-inventory-PROVISIONAL-20261002.md`  
**Lane audits:** SolModelos PASS · SolQA PASS · SolDatos PASS (see rollup)

## GO rule

Per debt item **GO** only if **all four** hold:

| # | Gate |
|---|------|
| 1 | **code?** — implementation on disk (or N/A for documented accept) |
| 2 | **tests?** — automated coverage (or N/A for accept) |
| 3 | **note?** — cycle0 evidence note |
| 4 | **paper/q5b integrity?** — PID **121466** untouched by this audit; `q5b_last.joblib` present & **not** swapped |

**FAIL** incomplete deliveries.  
**PENDING** only if work not started / blocked on external GO.

## Integrity snapshot (read-only) — 2026-10-02 ~14:18 CEST

| Check | Result |
|-------|--------|
| paper PID **121466** | ALIVE · pump · histgb_q5b · CLI thr **0.9** |
| `q5b_last.joblib` | EXISTS · md5 `4df6d5a8dff6bf66528d4ee4cf6641b2` · sha256 `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` · **same file** |
| `q5b_calibration.json` | EXISTS · md5 `586e2af105e8b890594a4f70612915a0` |
| Operativa | **q5b_last** · `q5b_pump_*` quarantine NO-GO (not swapped) |
| This audit mutated paper/q5b? | **NO** |
| Observational | orphan scale fetch PID **112910** still running (not paper) · thr CLI 0.9 vs config 0.99 |

---

## Filled status (BOSS inventory D-01…D-17) — lane evidence rebased

| id | owner | code? | tests? | note? | paper/q5b integrity? | GO? | Lane evidence |
|----|-------|-------|--------|-------|----------------------|-----|---------------|
| **D-01** | SolModelos+SolDatos | FAIL — no promotable Pump-true POS≈live candidate | FAIL — no live-lift gate pass | PASS — residual/feat-diag/pilot/mcband/livelike (all swap NO-GO) + GO criterion | PASS | **FAIL** | SolModelos PASS operativo ≠ product close; SolDatos pipeline ≠ mass lift |
| **D-02** | BOSS+SolAuditor | FAIL — protocols not gated in tooling | FAIL — `protocolos-verificacion.md` **0/54** checked | PARTIAL — GO criterion exists; protocol boxes unchecked | PASS | **FAIL** | Auditor enforces 4-gate GO; boxes still unchecked |
| **D-03** | SolQA | PASS — `features_t0.py` (no shim) | PASS — 19+8 re-verified | PASS — `depur-features-stub-modelstub-20261002.md` | PASS | **GO** | **`audit-solqa-lane-20261002.md` PASS** |
| **D-04** | SolModelos+SolDatos | FAIL — duplicate `build_pump_*` still live (not archived) | FAIL — no archive/consolidation suite | PARTIAL — recipe + pipeline CLI; forest not closed | PASS | **FAIL** | SolDatos CLI consolidates entry; pilots still on disk |
| **D-05** | SolDatos | N/A accept + priors stamp PASS | N/A accept + prior stamp tests PASS | PASS — residual-parity R5–R8; pipeline asserts USD scale OFF | PASS | **GO** (accept + priors done) | SolDatos lane re-asserts scale OFF in tests |
| **D-06** | SolQA+SolDatos | FAIL — no pc1 quarantine table/export | FAIL — no stub-stock exclusion test | FAIL — no dedicated pc1 legacy note | PASS | **FAIL** | Out of SolQA rename delivery |
| **D-07** | SolDatos | FAIL — residual fetch PID **112910** still alive; script kept (ORPHAN marked) | PASS — orphan/refuse/no-matrix tests in pipeline suite | PASS — pipeline §4 + cache inventory `ORPHAN_INCOMPLETE` | PASS | **FAIL** | SolDatos lane **PASS** for mark+CLI+tests; full DoD needs stop-fetch |
| **D-08** | SolQA | N/A (code mostly present) | FAIL — remaining gaps open (holders proxy; sol_usd gate; journal invariant; overlay CI) | PARTIAL — depur note 19 passed; does not close gap list | PASS | **FAIL** | SolQA lane PASS is rename/ModelStub only |
| **D-09** | SolQA | N/A accept — Lite OFF | N/A accept | PASS — `score-mode-lite-cycle0-20261002.md` | PASS | **GO** (accept) | — |
| **D-10** | SolModelos | FAIL — multiple `train_q5b_pump_*_wf.py`; no single candidate trainer | FAIL | PARTIAL — recipe forbids overwrite; scripts not archived | PASS | **FAIL** | SolModelos docs-only; train forest open |
| **D-11** | SolDatos | N/A | N/A | FAIL — `path-a-ws3-residual-accept-20261002.md` **missing** | PASS | **FAIL** | Pipeline note ≠ formal residual-accept close |
| **D-12** | SolQA | PASS — ModelStub offline-only; 0 imports under `paper_live/` | PASS — `tests/models/test_stub.py`; live rg clean | PASS — depur note §ModelStub | PASS | **GO** | **`audit-solqa-lane-20261002.md` PASS** |
| **D-13** | SolQA | N/A accept — gates kept; post-restart skip_prior=0 | N/A | PASS — BOSS inventory + restart/residual notes | PASS | **GO** (accept) | — |
| **D-14** | SolQA | PASS — `loop._enrich` pump branch only | N/A accept | PASS — BOSS grounding | PASS | **GO** (accept; docstring tidy → D-15) | — |
| **D-15** | SolQA | FAIL — `loop.py` L4 still “Default enrich: Helius…” vs `DEFAULT_ENRICH_VIA=pump` | FAIL — no docs-match CI | FAIL — no dedicated tidy note | PASS | **FAIL** | Spot-checked still stale |
| **D-16** | SolQA | FAIL — `state.followup_errors` stale poll_pump_mcs / DNS | FAIL — no clear/rotate test | FAIL — no close note | PASS — no restart | **FAIL** | — |
| **D-17** | SolModelos | N/A accept — in-situ quarantine | N/A docs-only honest | PASS — quarantine + GO criterion + recipe; **`audit-solmodelos-lane-20261002.md` PASS** | PASS — dual-hash verified; 6/6 NO-GO | **GO** (accept) | SolModelos lane PASS operativo |

---

## Counts (BOSS-rebased · post 3-lane audits)

| GO? | n | ids |
|-----|---|-----|
| **GO** | **7** | D-03, D-05, D-09, D-12, D-13, D-14, D-17 |
| **FAIL** | **10** | D-01, D-02, D-04, D-06, D-07, D-08, D-10, D-11, D-15, D-16 |
| **PENDING** | **0** | — |
| **Total** | **17** | D-01…D-17 |

### Which P0/P1 closed by today's lanes

| Priority | Closed today (SolAuditor GO stamp) | Still open / FAIL |
|----------|------------------------------------|-------------------|
| **P0** | **none** (D-01 product mass · D-02 protocol gate both FAIL) | D-01, D-02 |
| **P1** | **D-03** formal GO (was code-done†; SolQA lane PASS). D-05/D-09 already accept-GO. | D-04, D-06, D-07, D-08, D-10, D-11 |
| **P2** | **D-12** confirmed GO (SolQA). D-13/D-14/D-17 already accept-GO. | D-15, D-16 |

**Net new formal closes today:** **D-03** (+ spot-confirm D-12). SolDatos/SolModelos lanes PASS without flipping additional inventory ids to GO under full DoD.

## Lane note pointers

| Lane | Audit | Verdict |
|------|-------|---------|
| SolQA | `audit-solqa-lane-20261002.md` | **PASS** |
| SolDatos | `audit-soldatos-lane-20261002.md` | **PASS** |
| SolModelos | `audit-solmodelos-lane-20261002.md` | **PASS operativo** (no rewrite; dual-hash still holds) |
| Rollup | `audit-path-a-debt-lanes-20261002.md` | 3-lane + inventory coverage |

## Non-actions

- No paper restart/kill (PID 121466).
- No `q5b_last` / calibration overwrite or swap.
- No kill of orphan scale fetch PID 112910 (flagged under D-07).
