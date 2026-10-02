# ge10 rescore — recovery_on + metafill — 2026-10-01

**Owner:** SolModelos · **Paper live:** FROZEN (untouched) · No paid APIs
**Model:** `data/paper_live/models/q5b_last.joblib` · `FEATURE_SETS['+q5b']` (51 cols)
**Recipe==joblib:** PASS (`assert_recipe_matches_joblib`)
**Scorer:** joblib `pipeline.predict_proba` on numpy row (same path as `PaperScorer._histgb`)

## Inputs
- Features: `data/samples/helius_parity_features_ge10_recovery_on_20261001.csv`
- Enrich: `data/samples/helius_parity_enrich_ge10_recovery_on_20261001.csv`
- Dump: `data/samples/helius_parity_tx_dump_ge10_recovery_on_20261001.csv`
- Note: `cycle0/diagnostics/ge10-reenrich-recovery-on-20261001.md`
- Overlay Q5a (optional, recorded only): `data/samples/features_buy_vol_q5a_overlay_ge10_20261001.csv`
- Train store: `data/samples/features_dune_p0_q5_expand_v2.csv`
- Meta fill: `fill_meta_from_dune_store_exact` / `exact_meta_for_mint`

## Outputs
- CSV: `cycle0/diagnostics/helius_parity_rescore_ge10_recovery_on_metafill_20261001.csv`
- This note: `cycle0/ge10-rescore-recovery-on-metafill-20261001.md`

## Checks

| Check | Result |
|-------|--------|
| n_trades / buys vs train_buy_count | **12/12** exact |
| enrich `trades_exact` | **12/12** |
| live_score vs train_store_rescore `|Δ|<1e-12` | **5/12** |
| max `|Δ(live−store)|` | **2.350002e-03** |
| `|Δ|<1e-9` / `1e-6` / `1e-4` / `1e-3` | 5 / 5 / 11 / 11 |
| store_rescore vs oos max`|Δ|` | **2.938e-03** |
| Exact Δ≈0 (bit / 1e-12) | **FAIL** |

## Method
- Build X from recovery_on features (`+q5b`).
- When `name_missing`/`symbol_missing`, apply `fill_meta_from_dune_store_exact` from expand_v2 via `CreatorPriorIndex.exact_meta_for_mint`.
- Score with same joblib pipeline as train (`q5b_last.joblib`), numpy row order = `feature_names`.
- `train_store_rescore` = same joblib on store row for that mint.
- Q5a overlay **not** applied to X (Path A `pyth_asof` buy_vol kept); overlay vols recorded in CSV.

## Per-mint table

| mint | trades | oos | store_rescore | live (no meta) | live (metafill) | Δ(live−store) | meta_source | n_resid | top_resid |
|---|---:|---:|---:|---:|---:|---:|---|---:|---|
| `69xneXbByUnx…` | 3/3 | 0.999491 | 0.999491 | 0.999403 | 0.999491 | 0 | dune_store_exact | 15 | buy_vol_usd_60s |
| `BZofTtkyrBM2…` | 4/4 | 0.999818 | 0.999818 | 0.999796 | 0.999818 | 0 | dune_store_exact | 16 | first_buy_usd |
| `4M3gYZ2dQ39K…` | 3/3 | 0.999846 | 0.999846 | 0.999796 | 0.999805 | -4.047e-05 | dune_store_exact | 19 | buy_vol_usd_60s |
| `wbf55KygjChm…` | 3/3 | 0.999853 | 0.999853 | 0.999796 | 0.999805 | -4.754e-05 | dune_store_exact | 19 | buy_vol_usd_60s |
| `2ahcm3vhbPTi…` | 3/3 | 0.999826 | 0.999826 | 0.999796 | 0.999796 | -2.972e-05 | dune_store_exact | 16 | first_buy_usd |
| `4X9d1Mc1cXJU…` | 3/3 | 0.999826 | 0.999826 | 0.999826 | 0.999826 | 0 | dune_store_exact | 16 | buy_vol_usd_60s |
| `G4G4cN8BLGaD…` | 3/3 | 0.999826 | 0.999826 | 0.999826 | 0.999826 | 0 | dune_store_exact | 16 | buy_vol_usd_60s |
| `2DU2GNLBhXg2…` | 3/3 | 0.999819 | 0.999819 | 0.999796 | 0.999755 | -6.341e-05 | dune_store_exact | 19 | buy_vol_first_10s |
| `wXcbD8Sr23So…` | 3/3 | 0.999458 | 0.999458 | 0.999403 | 0.999458 | 0 | dune_store_exact | 15 | buy_vol_usd_60s |
| `2hCEWYZcFZNW…` | 6/6 | 0.995362 | 0.992424 | 0.993319 | 0.994774 | 2.350e-03 | dune_store_exact | 18 | buy_vol_usd_60s |
| `6mCCo1Abfz2r…` | 4/4 | 0.999846 | 0.999846 | 0.999796 | 0.999796 | -4.976e-05 | dune_store_exact | 19 | first_buy_usd |
| `56ofoyzfMaGw…` | 3/3 | 0.999846 | 0.999846 | 0.999796 | 0.999796 | -4.976e-05 | dune_store_exact | 19 | first_buy_usd |

## 2hCEWY row

- mint: `2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump`
- trades: **6** = train **6** (exact)
- meta: before name/symbol_len=0/0 missing=1/1 → after **7/7** missing=0/0 (`dune_store_exact`)
- oos_score: `0.995361820598`
- train_store_rescore: `0.992423560390`
- live_score_no_metafill: `0.993318780009`
- live_score (metafill): `0.994773562561`
- Δ(live−store): **`2.350002e-03`**
- buy_vol_usd_60s live/store: `17638.784115` / `17610.973964` (Δ=27.810151)
- residual feat cols: 18; top=`buy_vol_usd_60s` max`|Δfeat|`=27.81

| feat | live | store | Δ |
|---|---:|---:|---:|
| `buy_vol_usd_60s` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `buy_vol_first_10s` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `buy_vol_first_5s` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `buy_vol_usd_15m` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `buy_vol_usd_30s` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `buy_vol_usd_total` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `first10_buy_vol_usd` | 17638.784115112943 | 17610.973964359822 | 27.81015075312098 |
| `first5_buy_vol_usd` | 17522.316601424354 | 17494.84556941422 | 27.471032010133058 |
| `first_buy_usd` | 7628.864215568446 | 7616.04384643776 | 12.820369130685322 |
| `max_buy_usd` | 7628.864215568446 | 7616.04384643776 | 12.820369130685322 |
| `net_sol_total` | 149.79302450799997 | 149.778652529 | 0.014371978999975 |
| `max_buy_sol` | 64.786248131 | 64.773293472 | 0.0129546589999876 |

## Residual feature diffs (summary)

All 12 mints get `meta_source=dune_store_exact` (live create lacked name/symbol).
META cols match store after fill. Remaining Δscore is from **USD/vol / share** Path A vs Dune store — not meta, not trade-count.

- mints with zero residual +q5b cols after metafill: **0/12**
- mints with `|Δscore|<1e-12`: **5/12**
- metafill reduced `|Δ|` on **5/12** mints (median `|Δ|` before=4.965e-05 after=3.509e-05)


## Note: 2hCEWY store_rescore ≠ recorded oos

On **11/12** mints, `train_store_rescore` (joblib on expand_v2 row) matches `oos_score` from `wf_post_q5_oos_predictions` to ~1e-16.

**Exception:** `2hCEWY…` — store_rescore=`0.992423560390` vs oos=`0.995361820598` (Δ≈2.94e-3). Same mint/joblib; likely fold-OOS vs last-fold export drift or store row drift post-OOS — **not** a live Path A issue. Primary PASS/FAIL below is live−store.

## Verdict

**FAIL** — exact Δ≈0 not achieved: **5/12** with `|Δ|<1e-12`; max`|Δ|`=2.350002e-03. Trades **12/12** exact; meta fill applied **12/12**. Residual = Path A `sol×pyth_asof` USD/vol features ≠ Dune store `AmountInUSD` (see per-mint residual cols / 2hCEWY table). Joblib on store vs oos max`|Δ|`=2.938e-03.

Paper left **FROZEN**. No model retrain / threshold change.
