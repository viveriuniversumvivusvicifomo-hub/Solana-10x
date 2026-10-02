# Audit Path A pilot ge10 — diagnóstico

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 18:22 CEST  
**QA:** `data/samples/qa_ge10_path_a_pilot_vs_dune_store_report.json`  
**MD/CSV:** `cycle0/ge10-rescore-path-a-pilot-20261001.md` · `cycle0/diagnostics/helius_parity_rescore_ge10_path_a_pilot_20261001.csv`

## Veredicto: **FAIL_DIAGNOSTIC** (no PASS prod)

| Check | Result |
|-------|--------|
| Recipe/joblib 51/51 | PASS |
| Exact vs store Dune `@1e-12` | **10/12 FAIL** |
| max \|Δ\| | **2.35e-3** (`2hCEWY`) |
| Re-fit full / swap live | **NO** |

Esperado con store Dune actual. Exact prod pendiente scope A Dune Path A + OK Sinck → rebasado. Paper freeze / scale OFF.
