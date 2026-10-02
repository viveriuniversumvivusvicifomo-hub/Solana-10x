# Helius recovery: 2hCEWY — 2026-10-01

Paper live remains **FROZEN** (untouched). Scale 6.6× **OFF**. Path A: `amount_usd = sol_amt × pyth_asof`.

Mint: `2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump`  
T0 / create: `2026-09-22 01:41:06 UTC` (age_s=0, `migrated_pre_t0=1`)

## Before → after

| metric | before (post BZof/4M3g replay) | after this recovery |
|--------|-------------------------------:|--------------------:|
| n_trades / n_buys ≤T0 | 4 / 4 (dump parsed 3) | **6 / 6** |
| train `buy_count_total` | 6 | 6 (**exact**) |
| n_txs ≤T0 | 5 (fallback) / 4 (dump) | **5** (+ CREATE_POOL non-trade) |
| `n_le_t0_false` | 0 | **0** |
| live rebuild score | 0.992909 | **0.993319** |
| OOS / train_store | 0.995362 | 0.995362 |
| Δ(oos−live) | +2.45e-03 | **+2.04e-03** (shrunk, not zero) |
| buy_vol_usd_60s live | 17638.78 | 17638.78 (same total SOL) |
| buy_vol_usd_60s train | 25228.54 | 25228.54 (ratio ≈ 0.70) |

Trade-count residual **CLOSED**. Soft score gap **OPEN** (Path A pyth USD ≠ Dune `amount_usd`).

## Root cause (gaps)

1. **Fetch gap (dump):** ge10 dump treated 2hCEWY as non-fail → `enhanced_pre_t0` only (no RPC window / getBlock±1). Missing post-grad **PUMP_AMM SWAP** `2SBSMPF…` (~64.79 SOL = train `max_buy_sol`). CREATE_POOL `2E5GiJM…` present but correctly skipped.
2. **Parse gap (primary for buy_count 4→6):** two PUMP_FUN SWAPs are **multi-buyer bundled**:
   - `2qTzp…`: FxmsyBp 29.63 SOL + 5si8996 24.76 SOL → BC (was collapsed to feePayer-only 54.39)
   - `4t3XK…`: 5tX3Vg 9.88 SOL + FbWgcr 19.75 SOL → BC (was collapsed to feePayer-only 29.63)
   - NativeTransfers trader→BC give per-buyer SOL (Dune row granularity).
3. **Score residual after exact trades:** live `buy_vol_usd_60s` stays ~17639 (= Σ sol × pyth_asof 117.75). Train Dune USD ~25229 (~168 USD/SOL implied). Scale 6.6× remains OFF. Also live Q5b `name_len`/`symbol_len`=0 vs train 7 (CREATE meta not wired in replay rebuild).

## Fixes landed

| area | change |
|------|--------|
| `src/ingestion/helius_trade_parse.py` | `_bc_native_buy_legs`: one buy per BC→trader mint receipt; SOL from trader→BC `nativeTransfers`; `_sol_amt_from_tx` prefers per-user→BC before total BC delta |
| tests | `test_parse_helius_multibuyer_bc_native_buys` |
| `scripts/dump_helius_parity_tx_ge10_20261001.py` | `FAIL_PREFIXES` += `2hCEWYZcFZNW` |
| dump merge | replaced 2hCEWY rows in `helius_parity_tx_dump_ge10_20261001.csv` (4→7 rows; le_false=0) |

## Tx inventory ≤T0 (5 txs, 6 buy legs)

| sig (prefix) | type | source | legs |
|--------------|------|--------|------|
| 2E5GiJM… | CREATE_POOL | PUMP_AMM | 0 (skipped) |
| xWGrzEK… | CREATE | PUMP_FUN | 1 buy 0.989 SOL (creator) |
| 2qTzpLa… | SWAP | PUMP_FUN | **2** buys 29.63 + 24.76 |
| 4t3XKdm… | SWAP | PUMP_FUN | **2** buys 9.88 + 19.75 |
| 2SBSMPF… | SWAP | PUMP_AMM | 1 buy 64.79 SOL |

Unique buyers = 6 = train `unique_buyers_total`.

## Feature delta (8 non-exact prior scores)

See `cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv`.

For trades-exact mints with \|Δ oos−live\| > 1e-6, differing cols are almost entirely **USD / vol family** (`buy_vol_*`, `first*_buy_vol_usd`, `max_buy_usd`, `net_sol_*`, share proxies) from Path A pyth_asof vs Dune `amount_usd` (~0.1–1% on most; **−30%** on 2hCEWY). **`age_s`**: no diffs (all age≈0). Secondary: live `name_len`/`symbol_len`/`name_missing` vs train (CREATE name not in live rebuild).

2DU2 / wXcb: full live feature rebuild deferred (HELIUS contended with parallel n=200 enrich); CSV rows use prior-replay `buy_vol_live` only.

## Artifacts

- Report: `cycle0/diagnostics/helius-recovery-2hCEWY-20261001.md`
- Focused dump: `data/samples/helius_parity_tx_dump_2hCEWY_20261001.csv` + `_meta.json`
- Merged ge10 dump/meta updated for this mint
- Feature delta: `cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv`
- Live feats snapshot: `cycle0/diagnostics/helius_2hCEWY_live_feats.json`

## Next

1. SolQA: hard-gate trade count exact on 2hCEWY (6=6); score exact still FAIL until USD/name parity decided.
2. Optional: wire Pump CREATE name/symbol into live Q5b rebuild; do **not** turn Scale 6.6× ON without BOSS.
3. Re-run ge10 parity replay post this dump+parse (sparing HELIUS vs n=200).
4. Paper stays FROZEN until exact scores+trades PASS.

## Meta parity follow-up (SolModelos, 2026-10-01)

Live Q5b now prefers create/sighting name+symbol, else exact train-store lengths (`meta_source=dune_store_exact`). Trades remain **6=6**. Soft score residual ≈ USD/vol (Path A), not meta/trade count. See `cycle0/q5b-meta-features-train-parity-20261001.md`.
