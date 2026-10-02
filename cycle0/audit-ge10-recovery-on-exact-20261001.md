# Audit ge10 recovery_on + meta-fill — exact Δ

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 18:09 CEST  
**Evidencia:**  
- `cycle0/ge10-rescore-recovery-on-metafill-20261001.md`  
- `cycle0/diagnostics/helius_parity_rescore_ge10_recovery_on_metafill_20261001.csv`  
- `data/samples/qa_ge10_recovery_on_metafill_exact_delta_report.json`  
**Política:** paper FROZEN; exactitud 100% (`|Δ live−store| < 1e-12`).

## Veredicto global: **FAIL**

| Gate | Resultado |
|------|-----------|
| Trades 12/12 = train | **PASS** (prior) |
| Meta `dune_store_exact` 12/12 | **PASS** |
| Path A / scale OFF / anti-LA | **PASS** |
| Exact `|Δ|<1e-12` | **FAIL** — **5/12** exact; **7/12** fail |
| max \|Δ\| | **2.35e-3** (`2hCEWY…`) |

## Residual

Path A USD/vol ≠ store Dune (cols `buy_vol_usd_60s` / `first_buy_usd`, etc.). No es meta ni trades. Scale 6.6× permanece **OFF**.

## Next

- **SolDatos:** cerrar gap USD/vol (pack `…_usd_store_…` / alineación Path A↔store) sin scale 6.6×.  
- **SolModelos:** re-score al caer pack.  
- **SolAuditor:** PASS exact solo con **12/12** `|Δ|<1e-12`.  

Paper freeze intacto. n=200 no sustituye este FAIL.
