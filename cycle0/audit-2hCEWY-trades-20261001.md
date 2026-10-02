# Audit 2hCEWY trades — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 17:51 CEST  
**Ámbito:** box-local `/workspace/solana-10x`  
**Política:** paper **FROZEN**; exactitud 100% Sinck (trades **y** scores Δ≈0).

## Veredicto

| Gate | Resultado |
|------|-----------|
| Trades live == train (6=6) + anti-LA ≤t0 | **PASS** |
| Score Δ live vs OOS/store ≈0 | **FAIL / OPEN** (Δ≈+2.04e-3) |
| **Global exact** | **FAIL** — no PASS auditor hasta Δ≈0 |

## Evidencia

- Dump: `data/samples/helius_parity_tx_dump_2hCEWY_20261001.csv` + meta
- QA: `data/samples/qa_helius_parity_tx_dump_2hCEWY_le_t0_report.json` (`trades_eq_train: true`, `n_le_t0_false: 0`, `pyth_asof`, scale OFF)
- Nota: `cycle0/diagnostics/helius-recovery-2hCEWY-20261001.md`
- Feature-Δ: `cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv`

## Residuales que bloquean PASS exact

1. Path A pyth buy_vol ~**0.70×** Dune USD (`buy_vol_live_over_train≈0.699`) — owner SolDatos  
2. `name_len` / `symbol_len` 0 vs train — owner SolModelos  

## Estado vs audit-ge10-post-recovery

- Soft **SOFT-TRADE-2hCE** (4≠6): **CLOSED**  
- Score deltas ge10 / 2hCEWY: **OPEN**  
- n=200 OOS: pendiente (enrich en curso)

Paper freeze intacto.
