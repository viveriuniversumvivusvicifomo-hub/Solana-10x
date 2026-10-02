# Audit ge10 recovery_on — trades gate

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 18:05 CEST  
**Artefacto:** `data/samples/helius_parity_features_ge10_recovery_on_20261001.csv` (+ enrich/dump)  
**QA:** `data/samples/qa_ge10_recovery_on_trades_eq_train_report.json`

## Veredicto parcial

| Gate | Resultado |
|------|-----------|
| Trades 12/12 = train | **PASS** |
| Anti-LA `n_le_t0_false=0` | **PASS** |
| Path A `pyth_asof` / scale OFF | **PASS** |
| Score Δ live−store ≈0 | **PENDIENTE** (re-score SolModelos) |
| **Exact global 100%** | **aún FAIL / open** hasta Δ≈0 |

Dump-only `…_reenrich_…` permanece FAIL histórico. Paper freeze intacto.
