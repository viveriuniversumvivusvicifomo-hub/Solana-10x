# SolAuditor — audit SolModelos depuración lane (2026-10-02)

**Auditor:** SolAuditor (zero-shortcuts · read/verify only)  
**Date:** 2026-10-02 ~14:15 CEST (Europe/Madrid)  
**Lane under audit:** SolModelos quarantine + recipe canonical + GO criterion  
**Constraints honored:** no paper restart · no PID kill · no modify `q5b_last.joblib`

## Sources reviewed

| # | Path | Present? |
|---|------|----------|
| 1 | `cycle0/quarantine-q5b-pump-joblibs-20261002.md` | YES (mtime ~14:14; includes md5+sha256 for `q5b_last`) |
| 2 | `cycle0/recipe-path-a-train-canonical-20261002.md` | YES |
| 3 | `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` | YES |
| 4 | `cycle0/depuracion-modelos-lane-20261002.md` | YES (mtime ~14:14; dual-hash claim) |

---

## Checklist operativo (PASS/FAIL)

| Gate | Verdict | Evidence |
|------|---------|----------|
| **Código** | **PASS** (N/A new code; pointers valid) | Lane = quarantine/docs only. Recipe SoT pointers exist: `src/features/post_q5_sets.py` `FEATURE_SETS['+q5b']` **n=51** (independent count); `src/paper_live/recipe_parity.py` HistGB+imputer gate / no StandardScaler in recipe; `MODEL_Q5B_PATH → q5b_last.joblib` in `src/paper_live/config.py:66`. |
| **Tests** | **PASS** (docs-only honest) | No new automated test required for documentary quarantine. Existing recipe coverage: `tests/verification/test_live_parity.py`, `tests/paper_live/test_paper_live_v0.py` (`len(+q5b)`). **Gap (non-blocking for this lane):** no test that hard-fails if paper config points at `q5b_pump_*`. Prior PA-MCBAND / PA-LIVELIKE still FAIL on missing dedicated WF tests (separate ids). |
| **Nota** | **PASS** | Four cycle0 notes landed; quarantine inventories 6 NO-GO with sha256; GO criterion = max+med+frac≥0.9 before another WF; recipe canonical documented. |
| **Integridad paper / q5b_last** | **PASS** | See §Integridad below. Paper untouched by this audit. |

### Verdict operativo lane SolModelos depuración

**PASS operativo** — quarantine + recipe + GO criterion delivery is complete and honest for a docs-only lane. Paper stays on `q5b_last`. All 6 `q5b_pump_*` remain NO-GO vs ALL-three lift gate.

---

## Independent verification

### Dual hash — same file (BOSS md5 ↔ SolModelos sha256)

| Algo | Claimed | Measured `sha256sum` / `md5sum` | Match? |
|------|---------|----------------------------------|--------|
| **md5** | `4df6d5a8dff6bf66528d4ee4cf6641b2` (BOSS / prior checklist) | `4df6d5a8dff6bf66528d4ee4cf6641b2` | **YES** |
| **sha256** | `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` (SolModelos; prefix `9908b936`) | `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` | **YES** |

**Conclusion:** md5 `4df6d5a8…` and sha256 `9908b936…` are **the same** `data/paper_live/models/q5b_last.joblib` (size 263012 · mtime 2026-10-02 08:21 CEST). Not two different files.

Calib companion (read-only check):

| File | md5 | sha256 |
|------|-----|--------|
| `q5b_calibration.json` | `586e2af105e8b890594a4f70612915a0` | `b338c56efd19553a3d3c88b4b2529c524388e55835d4c3335f2b75bef145f10b` |

### Paper does NOT point to `q5b_pump_*`

| Check | Result |
|-------|--------|
| `src/paper_live/config.py` | `MODEL_Q5B_PATH = …/q5b_last.joblib` · `CALIBRATION_Q5B_PATH = …/q5b_calibration.json` |
| `live_entry_config.json` | No model path field; `score_mode=histgb_q5b` · thr **0.99** · Path A `pump_mc_band_sighting_v1` · dune_cohort priors · no pump joblib name |
| paper PID **121466** cmdline | `.venv/bin/python -m paper_live --live … --score-mode histgb_q5b …` — **no** `--model` / `q5b_pump` |
| `/proc/121466/environ` | No `MODEL*` / `Q5B*` / `APPLY_DUNE*` override pointing at pump |
| Grep `q5b_pump` under paper runtime configs | Hits only **companion calib JSONs** + **train scripts** (export paths) — not live operativa wiring |
| systemd units | None found for paper/solana |

**Observation (pre-existing, not SolModelos regression):** live cmdline uses `--score-threshold 0.9` while `live_entry_config.json` / config default document product thr **0.99**. Does not imply paper loads a pump twin.

### Exactly 6 `q5b_pump_*.joblib` quarantined NO-GO

On disk under `data/paper_live/models/` (left in place; no move):

| Joblib | Claimed sha256 prefix | Disk match |
|--------|----------------------|------------|
| `q5b_pump_20261002.joblib` | `96d8fce8…` | OK |
| `q5b_pump_pilot500_20261002.joblib` | `0e66685a…` | OK |
| `q5b_pump_mcband_20261002.joblib` | `5ba05df3…` | OK |
| `q5b_pump_livelike_20261002.joblib` | `00be1242…` | OK |
| `q5b_pump_livelike_hard_20261002.joblib` | `5785745b…` | OK |
| `q5b_pump_livelike_hard424_20261002.joblib` | `50445c0f…` | OK |

**Count:** 6/6 claimed · 6 on disk · all marked **NO-GO** in quarantine + GO-criterion table.

### GO criterion written (before another WF)

`cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` requires **ALL** of:

- journal lift **max + med + frac≥0.9** vs `q5b_last` (same panel)
- document product thr 0.99 / frac≥0.99
- `recipe_parity` PASS · USD scale OFF · no overwrite without Sinck · SolAuditor PASS · Sinck OK

**Honesty note:** `cycle0/npz/q5b_pump_livelike_20261002_wf_metrics.json` still carries formal `go_nogo=GO` (max+frac only). SolModelos quarantine correctly overrides to **NO-GO** on median collapse (`lift_median≈−0.134`) — aligns with BOSS ALL-three wording. Audit agrees with quarantine override.

### Recipe canonical (+q5b/51, HistGB+imputer, scale OFF)

| Claim | Independent check |
|-------|-------------------|
| `FEATURE_SETS['+q5b']` 51 | `PYTHONPATH=src` → `len(FEATURE_SETS['+q5b']) == 51` |
| Imputer → HistGB · no StandardScaler in pipeline | Documented in recipe note + `cycle0/imputation-q5b-live-train.md`; recipe_parity header Path A USD |
| USD scale 6.6× OFF | Recipe forbids `APPLY_DUNE_HELIUS_USD_SCALE`; paper environ has no scale-ON override |
| Export `q5b_path_a_candidate_*` never clobber `q5b_last` without Sinck+GO | Written in recipe §7 |

---

## Gaps / non-blockers

1. **No automated lock** preventing a future CLI/env from pointing paper at `q5b_pump_*` (docs-only quarantine). Recommend optional follow-up test; not a FAIL for this documentary lane.
2. **Livelike metrics formal GO** vs criterion ALL-three — mitigated by quarantine NO-GO; future train scripts should encode median leg in `go_nogo`.
3. **score-threshold 0.9 on PID cmdline vs 0.99 product config** — operativa inconsistency outside SolModelos quarantine scope.
4. Prior checklist FAILs (PA-MCBAND tests, PA-LIVELIKE tests, PA-R1-DIST, etc.) **unchanged** by this lane — quarantine does not erase those debts.

---

## Non-actions (this audit)

- Did **not** restart / kill paper_live (PID 121466 still alive ~2h+ at audit).  
- Did **not** modify `q5b_last.joblib` / calib / entry config.  
- Did **not** move `q5b_pump_*` off disk.

## Checklist cross-link

Updated BOSS-rebased `cycle0/audit-path-a-debt-go-checklist-20261002.md` → **D-17** (SolModelos quarantine) refreshed with dual-hash + this audit path; integrity snapshot now lists md5+sha256 for `q5b_last`.
