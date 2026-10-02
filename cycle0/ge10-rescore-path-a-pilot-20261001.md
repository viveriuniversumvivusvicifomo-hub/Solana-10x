# ge10 Path A USD pilot rescore — 2026-10-01

**Owner:** SolModelos · **Paper live:** FROZEN · **Model/joblib:** untouched · **No paid APIs**

## Gate and method

- Recipe gate: **PASS** — `assert_recipe_matches_joblib`, `FEATURE_SETS["+q5b"]` = 51 ordered columns.
- Scorer: same read-only `PaperScorer(mode="histgb_q5b")` / joblib `predict_proba` path used by the isolate rescore.
- Pilot rows scored: **12/12**; each matched to one Dune train-store row and +q5b OOS score where available.
- No API calls, refit, live swap, paper change, or joblib write.

## Result versus current Dune store

- Exact score equality at `atol=1e-12`: **10/12** — **FAIL exact vs Dune store (expected)**.
- `max |delta(pilot - store)|`: **2.350002171612e-03**.
- The residual is the Path A USD/volume pilot versus the current Dune `AmountInUSD` store; it is not a cutover signal.

| mint | trades | oos | store_rescore | pilot | delta | n resid | top residual |
|---|---:|---:|---:|---:|---:|---:|---|
| `4M3gYZ2dQ39K…` | 3/3 | 0.999845680640 | 0.999845680640 | 0.999845680640 | 0.000e+00 | 16 | `buy_vol_usd_60s` |
| `G4G4cN8BLGaD…` | 3/3 | 0.999825851756 | 0.999825851756 | 0.999825851756 | 0.000e+00 | 16 | `buy_vol_usd_60s` |
| `4X9d1Mc1cXJU…` | 3/3 | 0.999825851756 | 0.999825851756 | 0.999825851756 | 0.000e+00 | 16 | `buy_vol_usd_60s` |
| `2ahcm3vhbPTi…` | 3/3 | 0.999825851756 | 0.999825851756 | 0.999796128227 | -2.972e-05 | 16 | `first_buy_usd` |
| `wbf55KygjChm…` | 3/3 | 0.999852754492 | 0.999852754492 | 0.999852754492 | 0.000e+00 | 16 | `buy_vol_usd_60s` |
| `2DU2GNLBhXg2…` | 3/3 | 0.999818636177 | 0.999818636177 | 0.999818636177 | 0.000e+00 | 16 | `buy_vol_first_10s` |
| `56ofoyzfMaGw…` | 3/3 | 0.999845885485 | 0.999845885485 | 0.999845885485 | 0.000e+00 | 16 | `first_buy_usd` |
| `6mCCo1Abfz2r…` | 4/4 | 0.999845885485 | 0.999845885485 | 0.999845885485 | 0.000e+00 | 16 | `first_buy_usd` |
| `BZofTtkyrBM2…` | 4/4 | 0.999817842610 | 0.999817842610 | 0.999817842610 | 0.000e+00 | 16 | `first_buy_usd` |
| `wXcbD8Sr23So…` | 3/3 | 0.999458459136 | 0.999458459136 | 0.999458459136 | 0.000e+00 | 15 | `buy_vol_usd_60s` |
| `69xneXbByUnx…` | 3/3 | 0.999491195663 | 0.999491195663 | 0.999491195663 | 0.000e+00 | 15 | `buy_vol_usd_60s` |
| `2hCEWYZcFZNW…` | 6/6 | 0.995361820598 | 0.992423560390 | 0.994773562561 | 2.350e-03 | 18 | `buy_vol_usd_60s` |

## 2hCEWY headline

- `2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump`: trades **6/6**, oos **0.995361820598**, store **0.992423560390**, pilot **0.994773562561**, delta **2.350002171612e-03**.
- This reproduces the expected ~2.35e-3 Path A-vs-store score residual.

## Prior recovery_on + metafill contrast

- Reconstructed Path A + exact name/symbol metafill is q5b-feature-identical to the pilot on **7/12** rows; on those rows, pilot score matches the prior metafill diagnostic within `1e-12` (**7/7**).
- Across all 12 prior diagnostic scores, max `|pilot - prior metafill|` is **6.341279854061e-05**; the five non-identical rows differ only in `creator_prior_mints_*` (the pilot is store-base, while `fill_meta_from_dune_store_exact` fills name/symbol only).
- Therefore the conditional alignment check passes where features are the same; the pilot fixture is not a replacement for a full Path A cohort.

## Freeze / gate decision

- **NO re-fit:** full Path A cohort re-fit remains BLOCKED pending SolDatos P1 Dune and Sinck OK.
- **NO swap:** do not overwrite `q5b_last.joblib`; do not swap live or paper.
- **Paper freeze:** remains explicit and unchanged.
- This pilot is a fixture for the future Path A candidate gate only; diagnostics CSV is the audit path, not production input.

## Artifacts

- `cycle0/diagnostics/helius_parity_rescore_ge10_path_a_pilot_20261001.csv`
- `cycle0/ge10-rescore-path-a-pilot-20261001.md`
