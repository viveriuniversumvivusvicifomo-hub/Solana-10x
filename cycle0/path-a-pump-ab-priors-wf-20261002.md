STATUS: NO-GO quarantined — see cycle0/quarantine-q5b-pump-joblibs-20261002.md

# Path A Pump — A (dune_cohort priors) + B (q5b_pump WF) — 2026-10-02

**Date:** 2026-10-02 ~09:36 CEST (Europe/Madrid)  
**Constraints:** paper_live PID **18531** untouched · Lite OFF · **0 Dune API** · `q5b_last.joblib` **not** overwritten · USD scale OFF

## A — Stamp `dune_cohort_*` in `pump_enrich`

### Problem
`pump_enrich.py` filled meta via `exact_meta_for_mint` but never stamped `creator_prior_source=dune_cohort_*`. Live then hit `skip_prior_not_train` in `score.py` (31× in restart window). Helius path already resolved + stamped correctly.

### Fix
- `src/paper_live/pump_enrich.py` now mirrors Helius:
  - import `CREATOR_PRIOR_SOURCE_*` + `resolve_creator_priors` / `load_creator_prior_index`
  - resolve: **exact → `dune_cohort_recompute` → `dune_cohort_empty`** via `resolve_creator_priors(..., allow_pump=False)`
  - apply `exact_overlay` when present; stamp `feats["creator_prior_source"]` + `feats["creator_priors_incomplete"]`
  - Pump `/coins?creator=` kept as **diagnostic/gap only** (does not overwrite model prior counts/source)
  - Prior resolution no longer requires network (`need_net` = trades only)

### Tests
- Extended `tests/paper_live/test_creator_priors_and_threshold.py`:
  - `test_pump_enrich_stamps_dune_cohort_recompute_or_empty`
  - `test_pump_enrich_stamps_dune_cohort_exact`
  - asserts score mode ≠ `skip_prior_not_train` when source is train family
- Existing `tests/paper_live/test_path_a_pump_capture.py` still green

**Pytest:** `16 passed` (`test_creator_priors_and_threshold.py` + `test_path_a_pump_capture.py`)

### Effect on live (without restart)
- **A alone unblocks scoring gate** (`skip_prior_not_train` → histgb can score) once paper_live picks up the code change (restart needed for running PID).
- Does **not** by itself lift scores to thr 0.9: offline Pump-live max≈0.53 / 0≥0.9 (see prior go-nogo). Expect `skip_below_thr` after restart unless thr/model change.

## B — Walk-forward → `q5b_pump_20261002.joblib`

### Approach
Offline, local store only (`features_dune_p0_q5_expand_v2.csv` + `labels_dune_expand_v2.csv`).  
True Pump-trade feature rebuild impossible without network → recipe:

**`train_on_store_with_Pump_path_column_set`**

| Taxonomy | Columns |
|----------|---------|
| Pump-like (Q5b/age/name/priors) | `age_*`, `has_creator`, `name_*`, `symbol_*`, `creator_prior_mints_*` |
| Still Dune-trade-implied (Q5a/buy60/curve) | remaining `+q5b` (live Pump now fills these from frontend trades; train values remain Dune-store) |
| Pump-gap force-null | `creator_prior_mints_all_in_window` (always None live+train) |

Script: `scripts/archive/train_q5b_pump_wf.py` (ARCHIVED; use `scripts/train_q5b_path_a_candidate_wf.py`) (reuses `build_hist_gb` + fold-5 expanding protocol from `export_last_fold_model` / post_q5).

### Artifacts (alongside `q5b_last`, never overwrite)
| Path | Role |
|------|------|
| `data/paper_live/models/q5b_pump_20261002.joblib` | new model |
| `data/paper_live/models/q5b_pump_20261002_calibration.json` | calib + OOS + taxonomy |
| `cycle0/artifacts/q5b_pump_20261002_wf_metrics.json` | metrics dump |
| `data/paper_live/models/q5b_last.joblib` | **unchanged** md5 `4df6d5a8…` |
| `data/paper_live/models/q5b_calibration.json` | **unchanged** (still points at q5b_last) |

### OOS (fold 5 held-out, same protocol as q5b_last)

| Metric | q5b_pump_20261002 | q5b_last (same OOS) |
|--------|-------------------|---------------------|
| n | 9851 | 9851 |
| AUC | **0.9327** | 0.9327 |
| AP / PR | **0.8608** | 0.8608 |
| frac≥0.9 | **9.15%** | 9.15% |
| median / max | 0.171 / 0.9999 | identical |
| proposed thr (trainQ top1%) | **0.9998068** | 0.9998068 |
| live thr | **unchanged 0.9** | — |

Bit-identical OOS to `q5b_last` expected: same expand matrix + same HistGB recipe; Pump-gap mask only nulls `all_in_window` (already null). Artifact is a **named Pump-path companion**, not a distribution-shifted Pump-trade refit.

## GO / NO-GO

| Action | Verdict |
|--------|---------|
| Point paper at `q5b_pump_20261002` / restart for model swap | **NO-GO** (default until Sinck OK) — twin of q5b_last; does not fix live Pump score mass (max≈0.53) |
| Restart paper_live to pick up **A** prior stamp only (keep q5b_last + thr 0.9) | **ASK Sinck GO** — unblocks `skip_prior_not_train` → expect `histgb_q5b` then mostly `skip_below_thr` |
| Lower live thr 0.9 | **NO-GO** without separate Sinck decision |
| Enable USD scale / Lite / Dune | **NO-GO** |

## Non-actions
- Did not kill/restart paper_live (PID 18531 still running)
- Did not call Dune API
- Did not overwrite `q5b_last.joblib` / `q5b_calibration.json`
- Lite remains disabled; `apply_dune_helius_usd_scale` stays OFF

## Pointers
- Plan / prior go-nogo: `cycle0/path-a-pump-recalib-wf-plan-20261002.md`, `cycle0/path-a-pump-recalib-go-nogo-20261002.md`
- Train script: `scripts/archive/train_q5b_pump_wf.py` (ARCHIVED; use `scripts/train_q5b_path_a_candidate_wf.py`)
