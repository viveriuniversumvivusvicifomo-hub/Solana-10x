# Path A Pump recalib / WF — GO / NO-GO (2026-10-02)

**Date:** 2026-10-02 ~08:39 CEST (Europe/Madrid)  
**Trigger:** Sinck "Hazlo" — walk-forward / recalib with Pump as source of truth  
**Constraints honored:** paper_live PID **18531** untouched · Lite OFF · **0 Dune calls** · `q5b_last.joblib` **not** overwritten

## Decision

| Swap | Verdict | Why |
|------|---------|-----|
| Replace `q5b_last.joblib` with new model | **NO-GO** | No Pump-aligned feature matrix; Dune-store OOS ≠ live Pump score mass |
| Write `q5b_pump_*.joblib` from this session | **NO-GO** | Same gap — would just re-fit Dune Path A under a new name |
| Lower live thr 0.9 → open entries | **NO-GO** | Offline Pump-live scores **max 0.532 / p50 0.160**; **0/31 ≥ 0.9** even if prior gate opened |
| Keep USD scale OFF | **GO (keep)** | Confirmed `apply_dune_helius_usd_scale_enabled=false`; Pump MC is frontend USD |
| Keep Lite OFF | **GO (keep)** | Out of scope |
| Wire `pump_enrich` → dune_cohort priors + stamp `creator_prior_source` | **ASK Sinck GO** | Cheapest unblock for *scoring*; does **not** fix thr/model alone |

## Inventory (post-wipe, local)

| Asset | Status |
|-------|--------|
| `features_dune_p0_q5_expand_v2.csv` | **OK** ~82 089 rows / 64 MB |
| `labels_dune_expand_v2.csv` | **OK** hit_10x pos 11 040 (13.4%) |
| `dune_q5b_features.csv` / `dune_q5a_features.csv` | **OK** |
| `q5b_last.joblib` + `q5b_calibration.json` | **OK** (fold5, train_t0_max 2026-09-20) |
| `buy60_last.joblib` | **missing** (ok for histgb_q5b) |
| `features_pump_q5_expand_*.csv` | **MISSING** |
| `labels_pump_aligned_*.csv` | **MISSING** (Dune labels reusable by mint if features land) |
| `q5b_pump_*.joblib` | **MISSING** |

Full machine-readable: `cycle0/artifacts/pump_recalib_inventory_20261002.json`

## Live skip taxonomy (restart window ≥ 06:30 UTC / ~08:30 CEST)

Source: `paper_journal.sqlite` · PID 18531 · `--enrich-via pump` · thr 0.9

| Mode | n |
|------|---|
| `skip_prior_not_train` | **31** |
| `skip_capture_not_scoreable` (age) | 4 |
| `skip_missing_buy_vol` | **0** (trades path works) |
| scored `histgb_q5b` | **0** |

- `capture_scoreable=true` + `t0_definition=pump_mc_band_sighting_v1` on scoreable rows  
- `buy_vol_usd_60s` present on all 31 (26 with buy_vol>0) · source `pump.frontend-api-v3…(+trades)`  
- Features carry Pump frontend priors (`meta_source=create`) but **never** stamp `creator_prior_source=dune_cohort_*` → hard gate in `score.py`

Prior vs local Dune index (`features_dune_p0_q5_expand_v2.csv`, 79 378 mints / 35 118 creators):

- exact mint hit: **0/31**  
- creator in index (recompute possible): **4/31 (12.9%)**

## Offline score distribution (q5b_last, read-only)

### A) Recent live Pump sightings (n=31 scoreable)

| Prior variant | p50 | max | n≥0.9 |
|---------------|-----|-----|-------|
| As logged (Pump priors) | **0.160** | **0.532** | **0** |
| Dune recompute / cold→0 | 0.165 | 0.532 | **0** |

Δ mean abs after prior swap ≈ 0.009 → prior stamp alone does **not** lift scores to thr.

Artifact: `cycle0/artifacts/pump_live_score_dist_20261002.json`

### B) Dune-store OOS after fold5 train_end (proxy fold, no refit)

n=9 851 · p50 0.171 · p95 0.9998 · max 0.9999 · **frac≥0.9 ≈ 9.1%**

→ Model still ultra-select on **train-distribution** features; live Pump band collapses to ~0.02–0.53.

Artifact: `cycle0/artifacts/pump_store_score_dist_foldproxy_20261002.json`

## Concrete offline WF / recalib steps (executable, 0 Dune)

1. **USD scale** — assert OFF (done). Do not enable `APPLY_DUNE_HELIUS_USD_SCALE`.  
2. **Creator priors** — in `pump_enrich.py`, resolve like Helius path:  
   `exact` → `dune_cohort_recompute` via `load_creator_prior_index().priors_for` → `dune_cohort_empty`; stamp `creator_prior_source`. Keep Pump `/coins?creator=` as diagnostic only.  
3. **Feature mask** — `scripts/pump_recalib_feature_mask_audit.py` (done; buy_vol now live-OK so mask is secondary).  
4. **Thr on histgb under Pump features** — keep **0.9** CLI until a Pump-trained artifact exists; do not chase entries by cutting thr while max≈0.53.  
5. **WF refit (blocked)** — needs `features_pump_q5_expand_v1.csv` (Pump trades ≤T0 → Q5a/buy60 on expand mints) joined to existing labels → `python -m models.walk_forward_post_q5 --train` → write **`data/paper_live/models/q5b_pump_YYYYMMDD.joblib`** + calib JSON **alongside**; compare OOS vs `q5b_last`; Sinck GO before any symlink/overwrite of `q5b_last`.

## Cheapest next ask for Sinck

**Option A (code, $0 API):** GO to stamp dune_cohort priors in `pump_enrich` so histgb can *score* (expect still skip_below_thr at 0.9 given max≈0.53).  

**Option B (data, may cost Pump egress only — still 0 Dune):** GO to build a **sample** Pump Q5a overlay (e.g. n=500–2000 expand mints with local/cached trades) → minimal WF fold → `q5b_pump_*.joblib` candidate. Report CU/time before any Dune.  

**Option C (Dune):** only if Pump overlay impossible — **stop**, estimate CU/$, wait explicit GO.

## Non-actions this session

- Did not kill/restart paper_live (PID 18531)  
- Did not start Lite  
- Did not call Dune  
- Did not overwrite `q5b_last.joblib`

## Pointers

- Plan: `cycle0/path-a-pump-recalib-wf-plan-20261002.md`  
- Inventory: `cycle0/artifacts/pump_recalib_inventory_20261002.json`  
- Prior live: `cycle0/artifacts/pump_prior_coverage_live_20261002.json`  
- Captura/trades: `cycle0/path-a-pump-mc-trades-20261002.md`, `cycle0/path-a-pump-rebuild-20261002.md`
