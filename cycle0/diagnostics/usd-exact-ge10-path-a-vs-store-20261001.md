# USD exact — ge10 Path A vs store (isolate Δ only) — 2026-10-01

**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`  
**Paper live:** FROZEN (untouched) · Scale 6.6× **OFF** · recovery_on **intact**  
**n=200:** not blocked  
**BOSS:** `…_usd_store_…` pack is **ISOLATE-ONLY** — never force live ≡ Dune USD

## Purpose

SolModelos FAIL after `recovery_on` + metafill: max `|Δ live−store| = 2.35e-3` on `2hCEWY…`. Trades **12/12** exact; meta fill OK. Residual = Path A `sol×pyth_asof` USD/vol ≠ Dune store `AmountInUSD`.

This note **quantifies** that residual per mint. The optional `usd_store` CSV copies store USD onto recovery_on rows **only to isolate score Δ** (prove residual is USD/vol, not trades/meta). **It is not a production fix and must not be used as live scoring input.**

**Production live stays Path A** (`amount_usd = sol_amt × pyth_asof`). Scale 6.6× stays **OFF**.

## Artifacts (NEW paths only)

| Path | Role |
|------|------|
| `data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001.csv` | **ISOLATE-ONLY** audit pack (store USD/vol swapped in). **NOT for prod / live scoring.** |
| `data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001_meta.json` | Labels pack as isolate-only / not_production |
| `data/samples/helius_parity_features_ge10_recovery_on_path_a_usd_side_20261001.csv` | Side table: Path A vs store per residual col |
| `cycle0/diagnostics/usd-exact-ge10-path-a-vs-store-20261001.md` | This diagnostic |
| `scripts/overlay_usd_store_ge10_20261001.py` | Reproducible isolate builder |

Inputs (read-only):
- live Path A: `data/samples/helius_parity_features_ge10_recovery_on_20261001.csv`
- store: `data/samples/features_dune_p0_q5_expand_v2.csv`
- evidence: `cycle0/ge10-rescore-recovery-on-metafill-20261001.md`

## Path A vs store residual (per mint, +q5b USD/vol)

All **12/12** mints have exact trade parity (`n_buys_le_t0 == train_buy_count`). Residual cols are USD/vol / sol / share economics (not meta, not trade-count).

| mint | trades | n_usd_diff | max\|Δfeat\| | top feat | buy60 Path A | buy60 store | Δbuy60 |
|---|---:|---:|---:|---|---:|---:|---:|
| `69xneXbByUnx…` | Y | 15 | 23.37 | buy_vol_usd_60s | 24903.295161 | 24879.923363 | +23.37 |
| `BZofTtkyrBM2…` | Y | 16 | 116.9 | first_buy_usd | 28688.928268 | 28770.205488 | −81.28 |
| `4M3gYZ2dQ39K…` | Y | 16 | 3427 | buy_vol_usd_60s | 343103.634850 | 346531.104437 | −3427.47 |
| `wbf55KygjChm…` | Y | 16 | 3586 | buy_vol_usd_60s | 355242.804740 | 358828.645563 | −3585.84 |
| `2ahcm3vhbPTi…` | Y | 16 | 3968 | first_buy_usd | 413156.778997 | 417124.524062 | −3967.75 |
| `4X9d1Mc1cXJU…` | Y | 16 | 4866 | buy_vol_usd_60s | 471748.429101 | 476614.877108 | −4866.45 |
| `G4G4cN8BLGaD…` | Y | 16 | 4833 | buy_vol_usd_60s | 472791.723994 | 477624.426742 | −4832.70 |
| `2DU2GNLBhXg2…` | Y | 16 | 2107 | buy_vol_first_10s | 204990.756176 | 207097.385616 | −2106.63 |
| `wXcbD8Sr23So…` | Y | 15 | 25.38 | buy_vol_usd_60s | 23730.510486 | 23755.887426 | −25.38 |
| `2hCEWYZcFZNW…` | Y | 18 | 27.81 | buy_vol_usd_60s | 17638.784115 | 17610.973964 | **+27.81** |
| `6mCCo1Abfz2r…` | Y | 16 | 1403 | first_buy_usd | 174669.483555 | 176058.994031 | −1389.51 |
| `56ofoyzfMaGw…` | Y | 16 | 1176 | first_buy_usd | 184616.366335 | 185761.230064 | −1144.86 |

Typical magnitude: **~0.1–1%** relative on buy_vol (fee net vs Dune gross / pyth vs Dune implied) — **not** 30%, **not** 6.6×.

### 2hCEWY headline (FAIL driver)

- mint: `2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump`
- trades: **6 = 6** (exact)
- `buy_vol_usd_60s` Path A **17638.784115** vs store **17610.973964** (Δ ≈ **$27.81**)
- Same absolute Δ on windowed `buy_vol_*` / `first10_*` (short-lived mint)
- Score: live(metafill) − store_rescore = **+2.350e-3** (FAIL evidence)

## Why `store_rescore ≠ oos` on 2hCEWY after Q5a overlay

OOS was recorded against the **pre-Q5a** expand_v2 row. Q4 hygiene later patched local store `buy_vol_usd_60s` / `buy_count_60s` from Q5a (`scripts/patch_q4_buy_vol_from_q5a_overlay_20261001.py`):

```
pre-Q5a  buy_vol_usd_60s = 25228.5410196028  (count=7) → joblib = 0.995361820598 ≡ oos (~3e-13)
post-Q5a buy_vol_usd_60s = 17610.973964359822 (count=6) → joblib = 0.992423560390
|oos − post-Q5a store_rescore| ≈ 2.938e-3
```

Side effect of Q5a expand_v2 buy_vol patch — **not** a live Path A bug. Backup: `features_dune_p0_q5_expand_v2.csv.bak_pre_q5a_20261001`.

## Recommendations (BOSS)

| Option | Action | Expectation |
|--------|--------|-------------|
| **(A)** | **Keep live Path A**; treat ~0.1–1% USD residual as known train/live economics gap (fee net vs Dune gross / pyth vs AmountInUSD). Optional Path A tweaks (e.g. fee-gross sol_amt) may shrink residual **without** copying Dune USD into live. | Residual closes or shrinks under Path A policy; live never forced to Dune |
| **(B)** | SolModelos **rebases store / re-fits joblib to Path A** (reprice train USD as `sol×pyth_asof`, re-OOS) if bit-exact live≡train is mandatory | live ≡ train after Path A train rebase — correct direction |
| **(C)** | Do **NOT** re-enable 6.6×; do **NOT** overlay store/Dune USD into live scoring as the “fix” | Blind scale rejected; forcing live≡Dune rejected |

**Forbidden:** using `…_usd_store_…` as production/live feature input to make scores match store.

**Isolate pack use:** optional only — swap-in store USD to **prove** score Δ vanishes (audit), then discard for prod. Verified offline: overlay scores ≡ store_rescore bit-identical 12/12; that shows residual class, it does **not** authorize live←Dune.

## Verdict

- Residual after recovery_on+metafill = **Path A USD/vol vs Dune store** (2hCEWY buy60 Δ~$28 → score Δ 2.35e-3).
- Fix direction: **Path A closes residual** and/or **SolModelos rebases train to Path A** — never force live to Dune USD.
- `usd_store` CSV = **isolate-only**. recovery_on Path A **intact**. Paper **FROZEN**. Scale **OFF**. n=200 unblocked.
