# SolAuditor — D-04 / D-10 train forest (2026-10-02)

**Auditor:** SolAuditor (zero-shortcuts)  
**Stamp:** 2026-10-02 ~14:28 CEST (Europe/Madrid)  
**Inventory SoT:** `cycle0/path-a-debt-inventory-20261002.md` §D-04 · §D-10  
**Claim note:** `cycle0/depur-d04-d10-train-forest-20261002.md`  
**Constraints honored:** no paper kill/restart · no train run · no `q5b_last` mutate · 0 Dune

## Verdicts

| id | Verdict | One-line why |
|----|---------|--------------|
| **D-10** | **PASS / GO** | Single canonical train entry + archive refuse exit 2 + 9/9 tests + integrity |
| **D-04** | **FAIL** | Train half closed; **build** forest still live under `scripts/build_pump_*.py` (SolDatos) |

## Gates

### D-10 (train entrypoints)

| Gate | Result | Evidence |
|------|--------|----------|
| **código** | **PASS** | Canonical `scripts/train_q5b_path_a_candidate_wf.py`; archive refuse; no active `train_q5b_pump_*.py` under `scripts/` |
| **tests** | **PASS** | `tests/models/test_train_q5b_path_a_candidate_wf.py` → **9 passed** |
| **nota** | **PASS** | `cycle0/depur-d04-d10-train-forest-20261002.md` |
| **integridad** | **PASS** | Paper 121466 ALIVE; q5b_last md5 intact; no train executed this audit |

### D-04 (duplicate build/train — full DoD)

| Gate | Result | Evidence |
|------|--------|----------|
| **código** | **FAIL** (partial) | Train archived ✓ · build still: `build_pump_mcband_pilot.py`, `build_pump_path_a_livelike.py`, `build_pump_path_a_pilot500.py`, `build_pump_true_features_offline.py`, `build_pump_mcband_scale.py` (orphan refuse only) |
| **tests** | **PASS** (train) / **FAIL** (full) | Train suite 9/9; no consolidation/archive suite for build forest |
| **nota** | **PASS** | Note honestly leaves build half to SolDatos |
| **integridad** | **PASS** | paper/q5b untouched |

## Independent checks (train)

| Check | Result |
|-------|--------|
| Active train scripts under `scripts/` | `train_q5b_path_a_candidate_wf.py` + `train_q5b_path_a_common.py` only |
| Archive | `scripts/archive/train_q5b_pump_{wf,pilot500,mcband,livelike}_wf.py` + README |
| Archive invoke (all 4) | **exit 2** NO-GO (unless `SOLMODELOS_ARCHIVE_FORCE=1`) |
| `--dry-path-check --out …/q5b_last.joblib` | **REFUSE exit 2** |
| `--dry-path-check` candidate path | **exit 0** `ok_path_check` |
| Leftover `scripts/train_q5b_pump*.py` | **NONE** |

## Tests re-run
```
PYTHONPATH=src pytest -q tests/models/test_train_q5b_path_a_candidate_wf.py
→ 9 passed in 7.58s
```

## Integrity
| Check | Value |
|-------|-------|
| Paper PID **121466** | ALIVE |
| `q5b_last` md5 | `4df6d5a8dff6bf66528d4ee4cf6641b2` |
| `q5b_last` sha256 | `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` |
| Train run this audit | **None** |

## Inventory stamps

| id | After SolAuditor |
|----|------------------|
| **D-10** | **GO** |
| **D-04** | **FAIL** — residual: SolDatos must quarantine/consolidate remaining `build_pump_*` (except canonical `build_pump_path_a.py` dispatcher) |

## Residual FAIL blockers (D-04)
1. Live build forest not archived / not single-entry DoD.
2. No automated suite proving build orphans refuse or are gone.
