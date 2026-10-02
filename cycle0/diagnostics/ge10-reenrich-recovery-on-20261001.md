# ge10 Path A re-enrich — recovery helpers ON — 2026-10-01

SolDatos interrupt for SolQA/SolAuditor. **NEW paths** (dump-only audit trail kept).

## Paths
- Features: `data/samples/helius_parity_features_ge10_recovery_on_20261001.csv`
- Mint enrich: `data/samples/helius_parity_enrich_ge10_recovery_on_20261001.csv`
- Meta: `data/samples/helius_parity_features_ge10_recovery_on_20261001_meta.json`
- Tx dump (recovery_on): `data/samples/helius_parity_tx_dump_ge10_recovery_on_20261001.csv`
- Dump-only audit (untouched): `data/samples/helius_parity_features_ge10_reenrich_20261001.csv` + `data/samples/helius_parity_tx_dump_ge10_20261001.csv`

## Counts
- n_mints: **12**
- n_scoreable: **12**
- n_trades_exact_vs_train: **12/12**
- n_pyth_asof: **12**
- n_le_t0_false: **0**

## Method
- USD Path A: `resolve_sol_usd_for_scoring(require_pyth=True)` → sol_amt × pyth_asof
- Scale 6.6×: **OFF**
- Recovery helpers ON via `fetch_create_to_t0_txs` (Enhanced+RPC+slot) — results harvested from in-flight n=200 enrich for overlapping ge10 mints (avoid 429 slam)
- Fallback for 4M3g / 2hCEWY: prior dump recovery already exact (n200 under-recovered those two)
- Parse: WSOL multi-leg + BC multi-buyer → `helius_trade_parse`
- Fixed T0 from OOS; paper_live / dump-only / n200 CSVs: **not overwritten**

## Before → after (trades/buys vs train)

| mint | before trades/buys | after trades/buys | train | source | fetch_mode | exact |
|---|---:|---:|---:|---|---|---|
| `69xneXbByUnx…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `BZofTtkyrBM2…` | 4/4 | 4/4 | 4.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `4M3gYZ2dQ39K…` | 3/3 | 3/3 | 3.0 | dump_exact_fallback | dump_parse_by_sig+prior_recovery | True |
| `wbf55KygjChm…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `2ahcm3vhbPTi…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `4X9d1Mc1cXJU…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `G4G4cN8BLGaD…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `2DU2GNLBhXg2…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `wXcbD8Sr23So…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc | True |
| `2hCEWYZcFZNW…` | 6/6 | 6/6 | 6.0 | dump_exact_fallback | dump_parse_by_sig+prior_recovery | True |
| `6mCCo1Abfz2r…` | 1/1 | 4/4 | 4.0 | n200_recovery | fetch_create_to_t0+rpc+slot | True |
| `56ofoyzfMaGw…` | 1/1 | 3/3 | 3.0 | n200_recovery | fetch_create_to_t0+rpc+slot | True |

## Per-mint buy_vol_usd_60s (Path A)

| mint | trades | buys | buy60 | sol_src | scoreable |
|---|---:|---:|---:|---|---|
| `69xneXbByUnx…` | 3 | 3 | 24903.295161180882 | pyth_asof | True |
| `BZofTtkyrBM2…` | 4 | 4 | 28688.928268364987 | pyth_asof | True |
| `4M3gYZ2dQ39K…` | 3 | 3 | 343103.6348496157 | pyth_asof | True |
| `wbf55KygjChm…` | 3 | 3 | 355242.80473982287 | pyth_asof | True |
| `2ahcm3vhbPTi…` | 3 | 3 | 413156.77899690083 | pyth_asof | True |
| `4X9d1Mc1cXJU…` | 3 | 3 | 471748.42910112074 | pyth_asof | True |
| `G4G4cN8BLGaD…` | 3 | 3 | 472791.7239935927 | pyth_asof | True |
| `2DU2GNLBhXg2…` | 3 | 3 | 204990.75617557717 | pyth_asof | True |
| `wXcbD8Sr23So…` | 3 | 3 | 23730.510485761286 | pyth_asof | True |
| `2hCEWYZcFZNW…` | 6 | 6 | 17638.784115112943 | pyth_asof | True |
| `6mCCo1Abfz2r…` | 4 | 4 | 174669.48355483537 | pyth_asof | True |
| `56ofoyzfMaGw…` | 3 | 3 | 184616.36633482904 | pyth_asof | True |
