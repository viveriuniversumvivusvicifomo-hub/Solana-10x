# Audit ge10 re-enrich Path A — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 17:57 CEST  
**Entrega:** `data/samples/helius_parity_features_ge10_reenrich_20261001.csv` (+ enrich/meta/nota)  
**QA:** `data/samples/qa_ge10_reenrich_path_a_pre_score_report.json`  
**Política:** paper FROZEN; exactitud 100%.

## Veredicto global: **FAIL** (regresión trades)

| Gate | Resultado |
|------|-----------|
| Anti-LA (`n_le_t0_false=0`) | **PASS** |
| Path A `pyth_asof` 12/12 | **PASS** |
| Scale 6.6× OFF | **PASS** |
| 2hCEWY trades 6=6 | **PASS** |
| Trades exact vs train (12 mints) | **FAIL** — **9/12** `n_trades_le_t0` ≪ train (a menudo 1 vs 3/4) |
| Score Δ≈0 | **N/A** — no medible / no PASS mientras counts regresan |

OK trades solo: BZof, 4M3g, 2hCEWY (per SolQA).

## Hard blockers

1. Regresión recovery helpers en re-enrich vs post-recovery ge10 (9 mints).  
2. Exact Δ≈0 **cannot PASS** con trade counts rotos.  
3. `name_len=0` en CSV features — esperado fill en score; no sustituye trades.

## Next

- **SolDatos:** recovery helpers ON en esos 9; re-dump/re-enrich.  
- **SolModelos:** re-score solo tras trades exactos.  
- **SolAuditor:** no PASS exact hasta trades 12/12 + Δ≈0.  

Paper freeze intacto. n=200 no desbloquea este FAIL.
