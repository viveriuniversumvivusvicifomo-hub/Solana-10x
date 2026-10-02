# Live parity replay post-recovery — 2026-10-01

Paper live: **FROZEN** (untouched). Scale 6.6×: **OFF**. Path A: `amount_usd = sol_amt × pyth_asof`.

## Sources

- Merged dump (SolQA PASS): `data/samples/helius_parity_tx_dump_ge10_20261001.csv`
- QA gate: `data/samples/qa_helius_parity_tx_dump_merged_le_t0_report.json`
- Prior replay (10/12): `cycle0/artifacts/helius_parity_replay_ge10_20261001.csv`
- Model: `data/paper_live/models/q5b_last.joblib` + `FEATURE_SETS['+q5b']`
- Threshold: **0.99** abs (Sinck product); trainQ top1% ≈0.9998 / top5% / top10% fold thr ~0.66–0.92 (note only)

## Result

| metric | value |
|--------|------:|
| n | 12 |
| live ≥ 0.99 | **12/12** |
| live ≥ 0.89 | 12/12 |
| median live | 0.999826 |
| sol_usd_source | pyth_asof |

## Fail-target before → after

| mint | before score | after score | trades before→after | ≥0.99 |
|------|-------------:|------------:|--------------------:|:-----:|
| 4M3gYZ2dQ39K… | 0.5733 | **0.9998** | 1→3 | YES |
| BZofTtkyrBM2… | 0.7307 | **0.9998** | 1→4 | YES |

## Per-mint

| mint | oos | live | before | n_trades | sol_src | prior_src | pass≥0.99 |
|------|----:|-----:|-------:|---------:|---------|-----------|:---------:|
| 69xneXbByUnx… | 0.9995 | 0.9994 | 0.9994 | 3 | pyth_asof | train_store_v1 | Y |
| BZofTtkyrBM2… | 0.9998 | 0.9998 | 0.7307 | 4 | pyth_asof | train_store_v1 | Y |
| 4M3gYZ2dQ39K… | 0.9998 | 0.9998 | 0.5733 | 3 | pyth_asof | train_store_v1 | Y |
| wbf55KygjChm… | 0.9999 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |
| 2ahcm3vhbPTi… | 0.9998 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |
| 4X9d1Mc1cXJU… | 0.9998 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |
| G4G4cN8BLGaD… | 0.9998 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |
| 2DU2GNLBhXg2… | 0.9998 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |
| wXcbD8Sr23So… | 0.9995 | 0.9994 | 0.9994 | 3 | pyth_asof | train_store_v1 | Y |
| 2hCEWYZcFZNW… | 0.9954 | 0.9929 | 0.9929 | 4 | pyth_asof | train_store_v1 | Y |
| 6mCCo1Abfz2r… | 0.9998 | 0.9998 | 0.9998 | 4 | pyth_asof | train_store_v1 | Y |
| 56ofoyzfMaGw… | 0.9998 | 0.9998 | 0.9998 | 3 | pyth_asof | train_store_v1 | Y |

## Residual mismatches

None — all 12 live ≥ 0.99.

## Artifacts

- CSV: `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_20261001.csv`
- JSON: `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_20261001.json`
- Summary: `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_summary.json`

## Method

1. Load 12 OOS≥0.99 mints from prior ge10 CSV.
2. Resolve Path A USD via `resolve_sol_usd_for_scoring(..., require_pyth=True)` → pyth_asof.
3. Prefer merged dump tx_sigs → Enhanced parse-by-sig (no re-getBlock).
4. Parse with SolDatos WSOL multi-leg path; aggregate Q5a/Q5b; score `q5b_last.joblib`.
5. Fallback `fetch_create_to_t0_txs` only if dump under-recovers a prior passer or fail target.

