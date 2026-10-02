# ge10 feature Δ live vs train store — 2026-10-01

**Owner:** SolModelos  
**Paper live:** FROZEN (untouched)  
**Set:** `FEATURE_SETS['+q5b']` (51 cols) · `data/paper_live/models/q5b_last.joblib`

## Verdict (feature chase)

| Check | Result |
|-------|--------|
| Recipe joblib == `+q5b` (51, order) | **PASS** (`assert_recipe_matches_joblib`) |
| Store X → joblib == `train_store_rescore` | **PASS** (max \|Δ\| ≤ 1e-16 on n=12) |
| Live score Δ vs store explained by **joblib drift** | **No** — same model; Δ is **feature X** |
| Dominant soft score driver (trades exact) | **`name_len` / `symbol_*` missing on live** |
| Hard residual (trades ≠ train) | **`2hCE…`** buy_vol ratio ~0.70, trades 4≠6 |

## Canonical feature-Δ table (SolDatos — do not duplicate)

Full per-mint / per-col live vs store deltas:

- **`cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv`** (123 rows, 8 mints with live X, 22 distinct cols)

Replay scores/aggregates (no feature vectors persisted in JSON):

- `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_20261001.csv`
- Audit: `cycle0/audit-ge10-post-recovery-20261001.md`

### Headline magnitudes (from SolDatos CSV)

| mint | max\|Δfeature\| | score Δ (oos−live) | note |
|------|----------------:|-------------------:|------|
| 2hCEWYZcFZNW… | **7589.8** (`buy_vol_usd_60s`) | **2.04e-3** | trades 4≠6; incomplete recovery |
| 2ahcm3vhbPTi… | 3967.8 (`first_buy_usd`) | 3.0e-5 | USD scale; score mover = `buy_vol_usd_total` |
| wbf55KygjChm… | 3585.8 | 6.9e-6 | score mover = **`name_len`** |
| 4M3gYZ2dQ39K… | 3427.5 | 7.2e-6 | score mover = **`name_len`** |
| BZofTtkyrBM2… | 116.9 | 2.2e-5 | score movers = `symbol_len`/`name_len` |
| 69xneXbByUnx… | 23.4 | 8.8e-5 | score movers = META |

USD vol cols differ ~0.1–1% rel (pyth_asof vs Dune `AmountInUSD`) but **do not move** HistGB on most ≥0.99 leaves.  
META (`name_len=0`, `name_missing=1`, same for symbol) **fully explains** soft Δscore on **10/12** when trades match (ablation: store X + live-missing META → live score).

## Code fix (SolModelos) — meta = train when create name missing

Live `CreateRow` often lacks `token_name`/`token_symbol` → `q5b_from_create` emits missing meta ≠ train store.

**Fix (wired):**

1. `fill_meta_from_dune_store_exact` in `src/paper_live/q5b_agg.py`  
   (alias: `prefer_train_store_meta_name_symbol`)
2. `CreatorPriorIndex.exact_meta_for_mint` + `by_mint_meta` in `src/paper_live/creator_priors.py`  
   (loads `name_len`/`name_missing`/`symbol_len`/`symbol_missing` from expand_v2)
3. Call after sighting fill in:
   - `helius_enrich.py`, `pump_enrich.py`, `q5_enrich.py`
   - ge10 replay scripts under `cycle0/scripts_live_parity_replay*_20261001.py`

Order: create → sighting → **dune_store_exact** (only fills still-missing sides).  
Offline check: fill restores store score on **12/12** ge10 (= `train_store_rescore`).

**Not fixed here:** `2hCE` trade-count / buy_vol under-recovery (SolDatos). USD scale residual on `2ahcm` after META fill (pyth vs Dune) — separate from META.

## Recipe confirmation

```
assert_recipe_matches_joblib → PASS (51 cols, order match)
max|store_joblib − train_store_rescore| ≤ 1e-16 on ge10
```

Paper live left **FROZEN**. No threshold / model retrain.

## Next

1. Re-run ge10 parity replay (post meta fill) → expect soft score Δ→0 on trades-exact mints.  
2. SolDatos: close `2hCE` trades 4→6.  
3. Optional: persist live feature vectors in replay JSON to avoid re-fetch for audits.
