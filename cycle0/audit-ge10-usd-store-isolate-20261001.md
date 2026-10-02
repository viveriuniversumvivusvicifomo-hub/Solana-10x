# Audit usd_store isolate — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 18:15 CEST  
**Artefacto:** isolate `…_usd_store_…` (meta `isolate_only=true`)  
**QA:** `data/samples/qa_ge10_usd_store_isolate_exact_report.json`

## Veredictos

| Gate | Resultado |
|------|-----------|
| Isolate `|Δ|=0` vs store (clase USD) | **PASS_ISOLATE** 12/12 |
| Exact **prod** (live Path A vs joblib canónico) | **FAIL** — max Path A vs store **2.35e-3** |
| Swap live / paper | **NO** |

## Next PASS prod

Solo tras: store/joblib rebasado Path A (plan `cycle0/plan-refit-path-a-q5b-20261001.md`) + gate live Path A vs joblib nuevo con `|Δ|<1e-12` 12/12. Scale OFF. Paper freeze.
