# Audit ge10 post-recovery — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 17:30 CEST  
**Ámbito:** `/workspace/solana-10x` (box-local; sin git push/clone)  
**Entrega auditada:**
- `cycle0/live-parity-replay-post-recovery-20261001.md`
- `data/samples/qa_helius_parity_replay_post_recovery_ge10_report.json`
**Cruzado con:** helius dump/meta, mismatch-hunt, `protocolos-verificacion.md`, `live-train-parity-qa-checklist.md`, `audit-baseline-20261001.md`  
**Política BOSS / Sinck:** paper live **FROZEN** — no reabrir. Live debe igualar train con **exactitud 100%** (scores **y** trade counts). Cualquier soft gap / aproximación = **FAIL**.

**Alcance explícito:** este audit es **n=12 ge10** post-recovery. **NO** es entrega OOS n=200.

**Veredicto global:** **FAIL** (bajo EXACT 100%).

---

## 0. Por qué FAIL (no negociable)

| Criterio Sinck | Resultado | Evidencia |
|----------------|-----------|-----------|
| Scores live == train/OOS (exact) | **FAIL** | Solo 4/12 live bit-idénticos a `train_store_rescore`; 0/12 idénticos a `oos_score`; max \|Δ oos−live\| = **0.00245** (`2hCE…`) |
| Trade counts live == train | **FAIL** | `soft_trade_count_gap` en `2hCE…`: `n_trades_pre_t0=4` vs `train_buy_count_total=6` |
| Umbral producto ≥0.99 (solo gate blando) | 12/12 live ≥0.99 | SolQA JSON `n_live_ge_0.99=12` — **insuficiente** para PASS exact |
| Soft gaps permitidos | **No** | Mandate: `soft_trade_count_gap = not exact` → FAIL |

SolQA marcó `verdict: PASS` con nota *"Soft gaps do not block P0 score gate"*. **Auditor override:** Sinck exige exactitud total; soft gap bloquea.

Paper freeze: **intact** (`paper_live: FROZEN_untouched` en QA + summary). Scale 6.6×: **OFF**. Path A `pyth_asof`: **12/12**.

---

## 1. Inventario de evidencia (entrega)

| Rol | Path | Estado |
|-----|------|--------|
| MD entrega | `cycle0/live-parity-replay-post-recovery-20261001.md` | Presente (~17:23 CEST) |
| QA gate replay | `data/samples/qa_helius_parity_replay_post_recovery_ge10_report.json` | Presente; soft_issue 2hCE |
| Replay CSV | `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_20261001.csv` | n=12 |
| Replay summary | `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_summary.json` | fail_targets recovered |
| Dump merged | `data/samples/helius_parity_tx_dump_ge10_20261001.csv` + `_meta.json` | recovery BZof/4M3g |
| Anti-LA dump | `data/samples/qa_helius_parity_tx_dump_merged_le_t0_report.json` | **PASS** (`n_ts_gt_t0=0`) |
| Recovery note | `cycle0/diagnostics/helius-recovery-bzof-4m3g-20261001.md` | Presente |
| Baseline prior | `cycle0/audit-baseline-20261001.md` | FAIL residual P0 (pre-recovery) |

---

## 2. Tabla score-level (n=12, thr 0.99)

Fuente: `cycle0/artifacts/helius_parity_replay_ge10_post_recovery_20261001.csv`.

| mint (12) | OOS | train_store | live | Δ(oos−live) | ≥0.99? | n_trades live | train buys | trades exact? |
|-----------|----:|------------:|-----:|------------:|:------:|--------------:|-----------:|:-------------:|
| 69xneXbByUnx… | 0.999491 | 0.999491 | 0.999403 | +8.81e-05 | Y | 3 | 3 | Y |
| BZofTtkyrBM2… | 0.999818 | 0.999818 | 0.999796 | +2.19e-05 | Y | 4 | 4 | Y |
| 4M3gYZ2dQ39K… | 0.999846 | 0.999846 | 0.999838 | +7.20e-06 | Y | 3 | 3 | Y |
| wbf55KygjChm… | 0.999853 | 0.999853 | 0.999846 | +6.87e-06 | Y | 3 | 3 | Y |
| 2ahcm3vhbPTi… | 0.999826 | 0.999826 | 0.999796 | +2.97e-05 | Y | 3 | 3 | Y |
| 4X9d1Mc1cXJU… | 0.999826 | 0.999826 | 0.999826 | ~0 | Y | 3 | 3 | Y |
| G4G4cN8BLGaD… | 0.999826 | 0.999826 | 0.999826 | ~0 | Y | 3 | 3 | Y |
| 2DU2GNLBhXg2… | 0.999819 | 0.999819 | 0.999849 | −3.03e-05 | Y | 3 | 3 | Y |
| wXcbD8Sr23So… | 0.999458 | 0.999458 | 0.999403 | +5.54e-05 | Y | 3 | 3 | Y |
| **2hCEWYZcFZNW…** | 0.995362 | 0.995362 | 0.992909 | **+2.45e-03** | Y | **4** | **6** | **N** |
| 6mCCo1Abfz2r… | 0.999846 | 0.999846 | 0.999846 | ~0 | Y | 4 | 4 | Y |
| 56ofoyzfMaGw… | 0.999846 | 0.999846 | 0.999846 | ~0 | Y | 3 | 3 | Y |

**Agregados:** live≥0.99 = **12/12**; trades exact = **11/12**; score exact vs store = **4/12**; median live = 0.999826; `sol_usd_source` = pyth_asof all; `prior_source` = train_store_v1.

Fail-targets recovery (before→after):

| mint | score before→after | trades before→after | ≥0.99 |
|------|-------------------:|--------------------:|:-----:|
| 4M3g… | 0.5733 → 0.9998 | 1 → 3 | Y |
| BZof… | 0.7307 → 0.9998 | 1 → 4 | Y |

---

## 3. Residuales vs `audit-baseline-20261001.md`

| ID | Baseline | Ahora | Notas |
|----|----------|-------|-------|
| **SD-REC-01** (BZof / 4M3g) | OPEN / FAIL | **CLOSED** | meta: buys 1→4 / 1→3; `recovery_improved=true`; `stuck_rpc_gap=false`; replay scores ≥0.99; trades = train |
| **LIVE-SCORE-GAP** (ge10 fail targets) | OPEN / FAIL (~0.57–0.73 vs 0.99) | **CLOSED** en n=12 ge10 fail targets | Ambos ≥0.99 post-recovery |
| **LIVE-SCORE-GAP** (exact live=OOS + all mints) | — | **OPEN** | Soft score deltas + gap 2hCE; no bit-identity 8/12 |
| **SOFT-TRADE-2hCE** | (no en baseline como ID) | **OPEN / FAIL** | 4 vs 6 buys; buy_vol_live/train ≈ 0.70 |
| **SD-SIDE-01** | OPEN P1 | **OPEN** | Sin cambio en esta entrega |
| **Q5b-HOLDERS** | OPEN P1 | **OPEN** | Sin cambio |
| **PRIORS-INDEX** | OPEN P1 | **OPEN** | Replay usa `train_store_v1` (OK para ge10); frescor live prod sigue P1 |
| **FEE/PARSE** | OPEN P1 | **OPEN** (parcial mejora) | Multi-leg WSOL parse landed for recovery; residual feePayer hunt no cerrado |
| Anti-LA dump 0 `ts>t0` | PASS | **PASS** | merged gate `ok:true` |
| Recipe 51 cols | PASS | **PASS** (no regresión citada) | Static parity prior sigue ancla |
| Scale 6.6× OFF | PASS | **PASS** | summary `scale_enabled: false` |

**Regresiones:** ninguna en BZof/4M3g. Residual **nuevo/explicitado** bajo mandato exacto: `2hCE` soft_trade_count_gap (SolQA lo etiquetó soft; auditor lo eleva a bloqueante).

---

## 4. Qué NO es esta entrega

| Item | Estado | Nota |
|------|--------|------|
| Journal rescore n=200 | **Diagnóstico** (no esta entrega) | `live-journal-rescore-check-20261001.md`: Δ journal↔joblib = 0; **0/200 ≥0.99** — mide fidelity recipe, **no** paridad Helius OOS |
| cohort200 features | ≠ OOS replay n=200 | Store/cohort features no sustituyen dump+replay Helius |
| Sample OOS≥0.99 n=200 | Prep on disk | `data/samples/parity_oos99_n200_sample_20261001.csv` + meta (~17:29 CEST) — **muestra**, no replay/audit PASS |
| OOS Helius replay n=200 | **PENDIENTE** | Sin CSV/QA/audit de replay post-recovery a escala 200 |

---

## 5. Checklist cruzado (LP / protocolo)

| Gate | Status en esta entrega |
|------|------------------------|
| LP.no_post_t0 | **PASS** dump merged |
| LP windows / Path A pyth_asof | **PASS** (12/12 pyth_asof) |
| LP.recipe / priors train | **PASS** en replay (`train_store_v1`) |
| Exact trade count vs train | **FAIL** (1/12: 2hCE) |
| Exact score vs OOS/train | **FAIL** (8/12 Δ≠0 vs store; max Δ 2.45e-3) |
| Umbral ≥0.99 only | Met but **not sufficient** for Sinck exact |

Protocolo V1–V8: sin barrido automatizado nuevo; ancla anti-LA = V2-style gate dump.

---

## 6. Next

### SolDatos
1. Cerrar recovery **2hCE…**: `n_trades_pre_t0` **6** (= train), no 4; investigar buy_vol ratio ~0.70.
2. Re-dump / parse multi-leg si hace falta; mantener 0 `ts>t0`.
3. Preparar dump+replay path para **n=200** OOS≥0.99 (sample ya existe; falta Helius fetch/replay).

### SolModelos
1. No recalibrar umbral ni reabrir paper.
2. Tras Datos: re-score exact live vs `train_store_rescore` / OOS (bit o tolerancia formal BOSS=0).
3. No confundir journal rescore 0/200≥0.99 con fallo de recipe (recipe OK).

### SolQA
1. Re-gate post-fix 2hCE: hard-fail `soft_trade_count_gap` bajo mandato exacto (no soft-pass).
2. Exigir score exactness table (live vs OOS/store) en próximo QA JSON.
3. Cuando exista replay n=200: gate completo + pedir re-audit SolAuditor.

### SolAuditor / BOSS
- Paper sigue **FROZEN** hasta PASS exact (scores + trades) en el alcance acordado.
- Próximo audit de entrega n=12 solo si 2hCE cerrado; aparte, audit n=200 cuando SolDatos/SolQA entreguen replay.

---

## 7. Resumen ejecutivo

**FAIL.** Recovery BZof/4M3g **CLOSED**; 12/12 ≥0.99; anti-LA PASS; freeze intact. Bloquea exactitud: **2hCE trades 4≠6** + deltas de score no nulos (8/12). Entrega = **n=12 ge10**, no n=200. n=200 OOS Helius replay **sigue esperando**.
