# Parity OOS≥0.99 n=200 enrich — 2026-10-01

- Sample: `data/samples/parity_oos99_n200_sample_20261001.csv` (n=200)
- Enrich: `data/samples/helius_parity_enrich_oos99_n200_20261001.csv` (n_done=65, partial=True)
- Tx dump: `data/samples/helius_parity_tx_dump_oos99_n200_20261001.csv`
- Features: `data/samples/helius_parity_features_oos99_n200_20261001.csv`
- Checkpoint: `data/samples/parity_oos99_n200_ckpt_20261001`

## Counts
- n_sample: **200**
- n_done / enriched: **65**
- n_scoreable: **59**
- n_pyth_asof: **65**
- n_le_t0_false (mint-level): **0**
- n_tx_le_t0_false (dump): **0**
- elapsed_s: 15887.2

## Path A / ops
- USD: `resolve_sol_usd_for_scoring(require_pyth=True)` → amount_usd = sol_amt × pyth_asof
- Scale 6.6×: **OFF**
- Recovery: `fetch_create_to_t0_txs` (BC Enhanced + RPC window + getBlock±1)
- Parse: `helius_trade_parse` WSOL multi-leg (via paper wrapper + direct for dump)
- Fixed T0 from OOS `t0_ts` (no refine look-ahead)
- Paper live: **not touched**; SolModelos joblib: **not touched**

## sol_usd_source
```
{
  "pyth_asof": 65
}
```

## skip / failure modes
```
{
  "no_trades_le_t0": 6
}
```

## Paths
- `data/samples/helius_parity_enrich_oos99_n200_20261001.csv`
- `data/samples/helius_parity_enrich_oos99_n200_20261001_meta.json`
- `data/samples/helius_parity_tx_dump_oos99_n200_20261001.csv`
- `data/samples/helius_parity_tx_dump_oos99_n200_20261001_meta.json`
- `data/samples/helius_parity_features_oos99_n200_20261001.csv`
- `data/samples/helius_parity_features_oos99_n200_20261001_meta.json`
- `cycle0/diagnostics/parity-oos99-n200-enrich-20261001.md`
