# Features Dune P0 Q3-only v1

**Fecha:** 2026-09-30 (CEST)  
**feature_set_version:** `features.dune.p0.q3.v1`  
**definition_version:** `dune_cohort_v1`  
**Streams Helius:** OFF · **Paid APIs:** none

## Qué hay

Stratified sample of `primary_ready` cohort rows that already have Q3 `mc_usd_t0` / `price_usd_t0`, then a **label-free** feature CSV from fields available at T0 only.

| Artefacto | Path |
|-----------|------|
| Sample (ids + label cols) | `data/samples/dune_sample_primary_ready_v1.csv` |
| Features (NO labels) | `data/samples/features_dune_p0_q3_sample_v1.csv` |
| Features meta | `data/samples/features_dune_p0_q3_sample_v1.json` |
| Labels (separate) | `data/samples/labels_dune_sample_v1.csv` |
| QA report | `data/samples/qa_features_dune_p0_q3_sample_v1.json` |
| Builder | `src/features/build_dune_p0_q3_features.py` |
| Q4 flow SQL (pending run) | `cycle0/dune-q4-flow-pre-t0.sql` |

## Sample

- Pool: `primary_ready==true` ∧ non-null `mc_usd_t0` from `dune_cohort_v1_labels_with_t0_mc.csv`
- Target: ~1000 pos (`hit_200k=1`) + ~1000 neg, stratified by UTC `t0_week`, `SEED=42`
- If fewer pos than target: take all pos with mc+primary_ready and match negs 1:1

## Feature columns (≤ T0, Q3-only)

| Column | Def |
|--------|-----|
| `mc_usd_t0` | Q3 exact MC at first band hit |
| `price_usd_t0` | Q3 price at T0 |
| `mc_band_pos` | `(mc - 8000) / (20000 - 8000)` |
| `log1p_mc_usd_t0` | `log1p(mc_usd_t0)` |
| `is_pumpdotfun` | 1 iff `project_at_t0 == 'pumpdotfun'` |

Meta only: `mint`, `t0_ts`, `feature_set_version`.

## Labels (never merged into feature store)

`mint`, `hit_200k`, `max_mc_after_t0`, `label_primary_hint`

**Caveat:** `label_primary_hint` is currently the `hit_200k` proxy. True PRIMARY `hit_10x_30d` needs full 30d post-T0 follow-up (right-censor aware).

## Explicitly NOT in this store yet

- **Flow** 60s / 5m (`buy_count_*`, `sell_*`, vols, unique traders) — waiting on Sinck running **Q4b** in `cycle0/dune-q4-flow-pre-t0.sql` after uploading the sample table
- **Holders** / concentration
- **`sol_usd_t0` Pyth** as-of T0
- Bonding-curve internals (`progress_curve`, `virtual_*`, …) — need capture/RPC, not Dune Q3

## QA gates

Script asserts:

1. Feature columns matching `/max_mc|hit_|label_|after_t0/` → **zero**
2. All `mc_usd_t0` ∈ [8000, 20000]
3. `n(features) == n(sample)`

See `qa_features_dune_p0_q3_sample_v1.json` (`ok: true`).

## Next

1. Sinck: upload `dune_sample_primary_ready_v1.csv` → run **Q4b** SQL → export flow CSV  
2. Merge Q4 flow into feature store (still no labels)  
3. Re-run QA leakage + band checks
