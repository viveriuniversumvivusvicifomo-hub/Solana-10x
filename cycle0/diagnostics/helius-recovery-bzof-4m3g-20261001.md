# Helius recovery: BZof + 4M3g (stuck_rpc_gap) — 2026-10-01

Paper live remains PAUSED until this lands (Sinck). Scale 6.6× OFF. Path A: `amount_usd = sol_amt × pyth_asof`.

## Before → after

| mint | train buy_count | prior n_trades | after n_buys / n_trades | n_txs_le_t0 | fetch_mode | stuck_rpc_gap |
|------|----------------:|---------------:|------------------------:|------------:|------------|---------------|
| BZofTtkyrBM2…pump | 4 | 1 | **4 / 4** | 14 | enhanced+rpc_sig_window+slot | **cleared** |
| 4M3gYZ2dQ39K…pump | 3 | 1 | **3 / 3** | 5 | enhanced+rpc_sig_window+slot | **cleared** |

`n_le_t0_false = 0` (main dump + fail2 artifact).

## Root cause (why txs_le rose but trades stayed 1)

1. **Parse gap (primary for BZof):** RPC already returned 14 le_t0 txs (incl. `PUMP_AMM` SWAPs), but `sol_amt` used bonding-curve / native fallbacks → ATA-rent (~0.0015 SOL) → USD &lt; $1 filter. Real size lives in **WSOL token transfers**. Bundled txs also had **non-feePayer** whale legs + **multi-hop same-tx** buys (Dune `dex_solana.trades` row granularity).
2. **Fetch gap (primary for 4M3g):** age≈0 `migrated_pre_t0` — mint crawl buried under post-T0 spam (`rpc_empty:max_pages=60`); BC only had CREATE / CREATE_POOL / failed SWAP. Missing post-grad AMM buys sit in the **create slot**, not on the bonding curve.
3. Prior run also hit Enhanced **HTTP 429** on 4M3g (bc+mint); this run used stronger backoff / slower pacing (`min_interval_s=0.7`, `max_retries_429=12`) and succeeded on Enhanced too.

## Fixes

| area | change |
|------|--------|
| `src/ingestion/helius_trade_parse.py` | Prefer WSOL for `sol_amt`; emit **one trade per mint↔WSOL leg** (multi-trader / multi-hop); skip `CREATE_POOL`; ignore ATA-rent native dust |
| `src/ingestion/helius_rpc.py` | `get_block_signatures` + `collect_signatures_around_slot` |
| `src/ingestion/helius_enhanced.py` | Stronger 429 backoff; create-slot recovery inside `fetch_create_to_t0_txs` |
| `scripts/dump_helius_parity_tx_ge10_20261001.py` | Fail recovery: slot±1 getBlock; `--only-fail`; `n_buys_le_t0`; use ingestion parse |

`paper_live/` ownership untouched (BOSS). Live enrich already delegates parse to `ingestion.helius_trade_parse`.

## Artifacts

- Report: `cycle0/diagnostics/helius-recovery-bzof-4m3g-20261001.md`
- Focused CSV/meta: `cycle0/diagnostics/helius_recovery_bzof_4m3g_20261001.csv` (+ `_meta.json`)
- Run log: `cycle0/diagnostics/helius_recovery_fail2_run.log`
- Merged main dump: `data/samples/helius_parity_tx_dump_ge10_20261001.csv` + `_meta.json`
- Fail-only raw: `data/samples/helius_parity_tx_dump_ge10_20261001_fail2_20261001.csv`

## Next step

- Re-run ge10 parity replay / rescore on these 2 mints (or full 12) so `n_trades_pre_t0` / Q5a match train buys; then unpause paper live when BOSS acks.
- If more age≈0 migrated snipers appear: always use create-slot window (cheap vs mint max_pages chase).
- Optional: wire `fetch_create_to_t0_txs` (slot path) into live enrich for the same class of mints.
