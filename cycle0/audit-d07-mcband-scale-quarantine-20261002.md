# SolAuditor — D-07 mcband_scale quarantine (2026-10-02)

**Auditor:** SolAuditor (zero-shortcuts)  
**Stamp:** 2026-10-02 ~14:27 CEST (Europe/Madrid)  
**Inventory SoT:** `cycle0/path-a-debt-inventory-20261002.md` §D-07  
**Claim note:** `cycle0/d-07-mcband-scale-quarantine-20261002.md`  
**Constraints honored:** no paper kill/restart · no `q5b_last` / calib mutate · 0 Dune · write only this audit

## Verdict: **PASS / GO**

| Gate | Result | Evidence |
|------|--------|----------|
| **código** | **PASS** | Quarantine + refuse + default cache excludes scale |
| **tests** | **PASS** | `tests/paper_live/test_path_a_pump_pipeline.py` → **15 passed** (re-run) |
| **nota** | **PASS** | `cycle0/d-07-mcband-scale-quarantine-20261002.md` |
| **integridad** | **PASS** | Paper **121466** ALIVE; `q5b_last` md5 unchanged; fetch **112910** dead |

## Independent checks

### 1. Quarantine inventory
| Check | Result |
|-------|--------|
| Dir `archive/quarantine/mcband_scale_20261002/` | EXISTS |
| `NO-GO_INCOMPLETE.md` | EXISTS |
| `manifest.json` | EXISTS (`n_trades: 837`, `n_deep: 0`, `status: NO-GO_INCOMPLETE`) |
| Trade JSON count | **837** under `pump_mcband_scale_trades_20261002/` (deep=0) |
| Features / usable matrix in quarantine | **NONE** |
| Default path remnants (`data/samples/pump_mcband_scale*`, checkpoints) | **NONE** (moved) |

### 2. Code — refuse + cache order
| Check | Result |
|-------|--------|
| `scripts/build_pump_path_a.py scale` | `refused_orphan` **exit 2** |
| `scripts/build_pump_mcband_scale.py` (no `--force-orphan`) | ORPHAN/DEPRECATED · `refused_orphan` **exit 2** |
| `pump_path_a_common.CACHE_KIND_ORDER` | `('livelike', 'mcband_extra', 'pilot500')` — **scale OUT** |
| Opt-in | `--reuse-orphan-scale` / `REUSE_ORPHAN_SCALE` / `reuse_orphan_scale=True` only |

### 3. Tests
```
PYTHONPATH=src pytest -q tests/paper_live/test_path_a_pump_pipeline.py
→ 15 passed in 0.35s
```

### 4. Integrity (read-only)
| Check | Value |
|-------|-------|
| Paper PID **121466** | ALIVE · pump · histgb_q5b · thr 0.9 |
| Scale fetch PID **112910** | **DEAD** (BOSS kill confirmed) |
| `q5b_last.joblib` md5 | `4df6d5a8dff6bf66528d4ee4cf6641b2` |
| `q5b_last.joblib` sha256 | `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` |
| `q5b_calibration.json` md5 | `586e2af105e8b890594a4f70612915a0` |
| This audit mutated paper/q5b? | **NO** |

## Inventory stamp

| id | Prior | After SolAuditor |
|----|-------|------------------|
| **D-07** | done (quarantined) · GO pending | **GO** |

## Residual blockers
**None** for D-07 DoD.
