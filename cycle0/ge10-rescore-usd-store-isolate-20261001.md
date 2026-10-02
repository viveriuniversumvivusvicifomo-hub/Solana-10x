# ge10 rescore — usd_store ISOLATE pack vs train store — 2026-10-01

**Owner:** SolModelos · **Paper live:** FROZEN (untouched) · No paid APIs · **No Path A re-fit**
**Model:** `data/paper_live/models/q5b_last.joblib` · `FEATURE_SETS['+q5b']` (51 cols)
**Recipe==joblib:** PASS (`assert_recipe_matches_joblib`)
**Scorer:** joblib `pipeline.predict_proba` on numpy row (same path as `PaperScorer._histgb`)

## ⚠ ISOLATE ≠ prod Path A

This pack (`…_usd_store_…`) is an **offline audit overlay** that copies train-store USD/vol
(+ meta) onto recovery_on rows **only** to prove residual class = USD/vol.
**It is NOT production / live Path A.** Do NOT feed into live scoring. Do NOT use to force live≡Dune.
Production stays Path A (`sol_amt × pyth_asof`, scale 6.6× OFF). Paper left **FROZEN**. No model retrain.

## Inputs
- Features (isolate): `data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001.csv` (`isolate_only=true`)
- Meta: `data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001_meta.json`
- Path A recovery_on (contrast): `data/samples/helius_parity_features_ge10_recovery_on_20261001.csv`
- Train store: `data/samples/features_dune_p0_q5_expand_v2.csv`
- Meta fill (if needed): `fill_meta_from_dune_store_exact` / `exact_meta_for_mint`
- Prior FAIL evidence: `cycle0/ge10-rescore-recovery-on-metafill-20261001.md`

## Outputs
- CSV: `cycle0/diagnostics/helius_parity_rescore_ge10_usd_store_isolate_20261001.csv`
- This note: `cycle0/ge10-rescore-usd-store-isolate-20261001.md`

## Checks

| Check | Result |
|-------|--------|
| n_trades / buys vs train_buy_count | **12/12** exact |
| isolate_score vs train_store_rescore `|Δ|<1e-12` | **12/12** |
| max `|Δ(isolate−store)|` | **0.000000e+00** |
| `|Δ|<1e-9` / `1e-6` | 12 / 12 |
| zero residual +q5b cols (isolate vs store) | **12/12** |
| Path A metafill residual mints (contrast) | **12/12** |
| max `|Δ(path_a_metafill−store)|` (contrast) | **2.350002e-03** |
| Exact Δ≈0 isolate (bit / 1e-12) | **PASS** |

## Method
- Build X from **isolate** usd_store features (`+q5b`).
- Apply `fill_meta_from_dune_store_exact` when `name_missing`/`symbol_missing` (pack already prefilled → no-op).
- Score with same joblib pipeline as train (`q5b_last.joblib`), numpy row order = `feature_names`.
- `train_store_rescore` = same joblib on expand_v2 store row for that mint.
- Contrast: Path A recovery_on + metafill scored the same way (expects non-zero Δ = USD residual).
- **No** overlay written into prod code. **No** Path A re-fit.

## Per-mint table

| mint | trades | oos | store_rescore | isolate | Δ(iso−store) | path_a+meta | Δ(pa−store) | n_resid_iso | n_resid_pa | top_pa |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `69xneXbByUnx…` | 3/3 | 0.999491 | 0.999491 | 0.999491 | 0.000e+00 | 0.999491 | 0.000e+00 | 0 | 15 | first5_buy_vol_usd |
| `BZofTtkyrBM2…` | 4/4 | 0.999818 | 0.999818 | 0.999818 | 0.000e+00 | 0.999818 | 0.000e+00 | 0 | 16 | max_buy_usd |
| `4M3gYZ2dQ39K…` | 3/3 | 0.999846 | 0.999846 | 0.999846 | 0.000e+00 | 0.999805 | -4.047e-05 | 0 | 19 | first5_buy_vol_usd |
| `wbf55KygjChm…` | 3/3 | 0.999853 | 0.999853 | 0.999853 | 0.000e+00 | 0.999805 | -4.754e-05 | 0 | 19 | first5_buy_vol_usd |
| `2ahcm3vhbPTi…` | 3/3 | 0.999826 | 0.999826 | 0.999826 | 0.000e+00 | 0.999796 | -2.972e-05 | 0 | 16 | max_buy_usd |
| `4X9d1Mc1cXJU…` | 3/3 | 0.999826 | 0.999826 | 0.999826 | 0.000e+00 | 0.999826 | 0.000e+00 | 0 | 16 | first5_buy_vol_usd |
| `G4G4cN8BLGaD…` | 3/3 | 0.999826 | 0.999826 | 0.999826 | 0.000e+00 | 0.999826 | 0.000e+00 | 0 | 16 | first5_buy_vol_usd |
| `2DU2GNLBhXg2…` | 3/3 | 0.999819 | 0.999819 | 0.999819 | 0.000e+00 | 0.999755 | -6.341e-05 | 0 | 19 | buy_vol_first_5s |
| `wXcbD8Sr23So…` | 3/3 | 0.999458 | 0.999458 | 0.999458 | 0.000e+00 | 0.999458 | 0.000e+00 | 0 | 15 | first5_buy_vol_usd |
| `2hCEWYZcFZNW…` | 6/6 | 0.995362 | 0.992424 | 0.992424 | 0.000e+00 | 0.994774 | 2.350e-03 | 0 | 18 | first10_buy_vol_usd |
| `6mCCo1Abfz2r…` | 4/4 | 0.999846 | 0.999846 | 0.999846 | 0.000e+00 | 0.999796 | -4.976e-05 | 0 | 19 | max_buy_usd |
| `56ofoyzfMaGw…` | 3/3 | 0.999846 | 0.999846 | 0.999846 | 0.000e+00 | 0.999796 | -4.976e-05 | 0 | 19 | max_buy_usd |

## Residual class confirmation

- Isolate vs store: **12/12** bit-identical scores (`|Δ|<1e-12`); **12/12** zero residual +q5b feature cols.
- Path A recovery_on + metafill vs store (same mints/joblib): **12/12** still have feature residuals; max `|Δscore|` = **2.350002e-03**.
- Therefore residual class of the prior FAIL was **USD/vol (Path A `sol×pyth_asof` vs Dune store `AmountInUSD`)**, not trades, not meta.
- Closing residual under policy = keep Path A / optional Path A economics tweak, **or** SolModelos Path A train rebase — **never** live←Dune USD overlay in prod.

## 2hCEWY row (prior FAIL driver)

- mint: `2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump`
- trades: **6** = train **6** (exact)
- oos_score: `0.995361820598`
- train_store_rescore: `0.992423560390`
- isolate_score: `0.992423560390`
- Δ(isolate−store): **`0.000000e+00`** → bit-identical = `True`
- path_a_metafill_score: `0.994773562561`
- Δ(path_a−store): **`2.350002e-03`** (USD residual; matches prior metafill FAIL)
- buy_vol_usd_60s isolate/store/path_a: `17610.973964359822` / `17610.973964359822` / `17638.784115112943`

## Verdict

**PASS (isolate only)** — **12/12** with `|Δ isolate−store|<1e-12`; max`|Δ|`=0.000000e+00.
Confirms residual class of prior Path A FAIL was **USD**. Path A contrast still max`|Δ|`=2.350002e-03.

**Explicit:** isolate pack ≠ prod Path A. Overlay not in prod code. Paper **FROZEN**. No Path A re-fit in this task.

