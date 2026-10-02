# Replay pre-T0 features (cohort 200)

**Fecha:** 2026-09-29 ~23:58 Europe/Madrid · **Agente:** SolDatos  
**Streams Helius:** OFF · **Secrets in outputs:** false · **Re-download raw:** NO

## Input
- Cohort: `data/samples/features_p0_min_pumpapi_cohort.json` (n=200; mint+t0 pairs)
- Raw (already on disk): `data/samples/pumpapi_replay/{15,16,17,18}.jsonl.zst` (~2.4G; ~12.34M lines)

## Extractor
- `src/ingestion/replay_pre_t0_features.py` — streams zstd JSONL line-by-line; mint-set filter (200); events with `timestamp ≤ t0_ms` only
- Buy/sell via `breakdown[]` when present (incl. create initial buy), else top-level `action` + `tradersInvolved` / `txSigner`
- Windows ending at T0: **60s**, **5m** (300s), **all** (t_first→T0)

## Output
- `data/samples/features_replay_pre_t0_cohort200.json` — `{meta, rows}` one row per `capture_id` (order aligned to cohort)

### Meta counts
| Metric | Value |
|--------|-------|
| hours_used | 15, 16, 17, 18 (2026-09-29 UTC) |
| n_cohort | 200 |
| n_with_pre_t0_events | 200 |
| n_missing_pre_t0 | 0 |
| n_lines_scanned | 12_343_894 |
| n_matched_mint_pre_t0_events | 45_374 |
| elapsed_s | ~97 |

### Features filled (where events exist)
Flow W∈{60s,5m,all}: `buy_count_*`, `sell_count_*`, `buy_vol_sol_*`, `sell_vol_sol_*`, `unique_buyers_*`, `unique_sellers_*`, `buy_sell_ratio_vol_*`, `net_flow_sol_*`  
Totals: `trade_count_total`, `unique_traders_total`, `buys_per_min`  
Age proxy: `t_first_event_ms`, `age_s_replay`, `time_since_first_trade_s`  
Auth (last event ≤T0 with fields): `mint_authority_none`, `freeze_authority_none`  
Holders: `holder_count` / `top1_pct` / `top5_pct` / `top10_pct` = **null**, `holders_status: "unavailable_in_replay_free"`

### Explicitly NOT in rows
`max_mc_*`, `label_*`, `mc_usd_hit_observed`, PRIMARY, `sol_usd_t0` (snapshot banned until Pyth as-of T0)

## Caveats (obligatorio)
1. **`age_s_replay` = first-seen in 4h replay window**, NOT on-chain create age (~half the cohort has age≈0 because T0 event is first sighting in these hours)
2. **4h ≠ 30d** label horizon
3. **No holders** from free replay; Bitquery/Helius holders skipped (streams stay OFF)
4. **No `sol_usd_t0`** in this extract
5. 27/200 have pre-T0 mint events but **zero buy/sell legs** (e.g. `createPool` only) → flow zeros / `time_since_first_trade_s` null; auth flags still set when fields present
6. Auth flags from last replay event ≤T0 that carried the fields — not a dedicated mint-account RPC

## Run
```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -m ingestion.replay_pre_t0_features
```
