# ge10 Path A re-enrich — 2026-10-01

SolDatos interrupt package for SolModelos re-score. Dump-driven; no paper_live.

## Paths
- Features: `data/samples/helius_parity_features_ge10_reenrich_20261001.csv`
- Mint enrich: `data/samples/helius_parity_enrich_ge10_reenrich_20261001.csv`
- Meta: `data/samples/helius_parity_features_ge10_reenrich_20261001_meta.json`
- Dumps: `data/samples/helius_parity_tx_dump_ge10_20261001.csv` + `data/samples/helius_parity_tx_dump_2hCEWY_20261001.csv` (2hCEWY preferred)

## Counts
- n_mints: **12**
- n_scoreable: **12**
- n_pyth_asof: **12**
- n_le_t0_false: **0**

## Method
- USD Path A: `resolve_sol_usd_for_scoring(require_pyth=True)` → sol_amt × pyth_asof
- Scale 6.6×: **OFF**
- Fetch: dump `tx_sig` → Helius parse-by-sig → `filter_txs_le_t0`
- Parse: WSOL multi-leg via paper wrapper → ingestion `helius_trade_parse`
- buy_vol_usd_60s: `buy_vol_60s_from_trades` (Q5a-aligned window [t0−60s, t0])
- Fixed T0 from ge10 prior / OOS t0_ts

## Per-mint buy_vol_usd_60s (Path A)

| mint | trades | buy60 | sol_src | scoreable |
|---|---:|---:|---|---|
| `69xneXbByUnx…` | 1 | 10001.85712455884 | pyth_asof | True |
| `BZofTtkyrBM2…` | 4 | 28688.92826836499 | pyth_asof | True |
| `4M3gYZ2dQ39K…` | 3 | 343103.6348496157 | pyth_asof | True |
| `wbf55KygjChm…` | 1 | 9918.971315280738 | pyth_asof | True |
| `2ahcm3vhbPTi…` | 1 | 9900.373744405726 | pyth_asof | True |
| `4X9d1Mc1cXJU…` | 1 | 9918.319454579942 | pyth_asof | True |
| `G4G4cN8BLGaD…` | 1 | 9937.087777451288 | pyth_asof | True |
| `2DU2GNLBhXg2…` | 1 | 9916.025142251696 | pyth_asof | True |
| `wXcbD8Sr23So…` | 1 | 9901.124132057594 | pyth_asof | True |
| `2hCEWYZcFZNW…` | 6 | 17638.784115112943 | pyth_asof | True |
| `6mCCo1Abfz2r…` | 1 | 10119.244444547134 | pyth_asof | True |
| `56ofoyzfMaGw…` | 1 | 10026.386689440902 | pyth_asof | True |
