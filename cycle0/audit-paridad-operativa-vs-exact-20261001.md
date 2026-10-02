# Audit: paridad operativa vs exact — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 18:49 CEST  
**Decisión Sinck/BOSS:** paridad **operativa** (no bit-exact USD).  
**Alineado con:** `cycle0/gate-paridad-operativa-vs-exact-20261001.md` (SolQA)

---

## 1. Dos gates (no mezclar)

| Gate | Criterio | Uso |
|------|----------|-----|
| **OPERATIVO (PASS prod)** | trades=train · meta OK · Path A Hermes · scale OFF · ≤T0 · residual oracle ~1e-3–2e-3 **aceptado** | Paper live / avisos |
| **EXACT (diagnóstico)** | `|Δ score| < 1e-12` vs store/joblib Path A | No bloquea prod; no PASS prod |

**Prohibido para PASS prod:** overlay `usd_store`, P2-lite, forzar live≡Dune USD.

**Pausado (cero gasto):** P1 Dune scope A · re-fit Path A / candidate joblib.

---

## 2. Estado ge10 `recovery_on` + meta-fill (referencia actual)

Evidencia: `audit-ge10-recovery-on-trades` · `audit-ge10-recovery-on-exact` · QA metafill exact · SolQA gate doc.

| Check | Resultado |
|-------|-----------|
| Trades 12/12 = train | **PASS** |
| Meta `dune_store_exact` 12/12 | **PASS** |
| Path A Hermes / scale OFF / ≤T0 | **PASS** |
| Residual max \|Δ\| vs store Dune | **2.35e-3** (`2hCEWY`) — dentro/borde banda operativa aceptada |
| **PASS OPERATIVO (prod)** | **PASS** |
| Exact `|Δ|<1e-12` | **FAIL_DIAGNOSTIC** (5/12 bit-exact; no bloquea prod) |

Dump-only `…_reenrich_…` sigue **FAIL histórico** (no usar). Isolate `usd_store` = solo clase USD, no prod.

---

## 3. Paper / avisos

Bajo gate operativo: paper live **puede reabrirse** y avisos **ON** (lo ejecuta BOSS). Sin swap a store Dune ni usd_store.

---

## 4. Audits previos (cómo leerlos)

| Archivo | Lectura ahora |
|---------|----------------|
| `audit-baseline-20261001.md` | Histórico pre-recovery |
| `audit-ge10-post-recovery-20261001.md` | FAIL bajo regla exact antigua |
| `audit-ge10-reenrich-20261001.md` | FAIL dump-only (sigue válido) |
| `audit-ge10-recovery-on-trades-20261001.md` | PASS trades (válido) |
| `audit-ge10-recovery-on-exact-20261001.md` | FAIL exact → ahora **diagnóstico**, no bloquea operativo |
| `audit-ge10-usd-store-isolate-20261001.md` | PASS_ISOLATE ≠ PASS prod |
| `audit-ge10-path-a-pilot-20261001.md` | FAIL_DIAGNOSTIC (válido) |

---

## 5. Next

- BOSS: reopen paper + avisos bajo operativo.  
- SolAuditor: siguientes entregas con **PASS/FAIL operativo**; exact solo como anexo diagnóstico.  
- n=200: audit operativo cuando caiga (mismos checks; no exigir bit-exact).
