# Audit baseline — Cycle 0

**Auditor:** SolAuditor  
**Fecha:** 2026-10-01 17:03 CEST  
**Ámbito:** `/workspace/solana-10x` (box-local; sin remote GitHub)  
**Política BOSS:** freeze total — paper live + aviso 5m **PAUSADOS** hasta paridad EXACTA live=train. **No reabrir paper.**

**Veredicto global:** **FAIL** (residuales P0 abiertos). Anti-look-ahead dump: **PASS**.

---

## 1. Inventario de evidencia

| Rol | Path | Estado |
|-----|------|--------|
| Protocolo V1–V8 | `cycle0/protocolos-verificacion.md` | Presente |
| Checklist live↔train | `cycle0/live-train-parity-qa-checklist.md` | Presente (SolQA) |
| Recipe parity | `cycle0/live-train-recipe-parity.md` | Presente (SolModelos) |
| Mismatch hunt | `cycle0/live-vs-train-mismatch-hunt-20261001.md` | Presente |
| MUST-FIX progress | `cycle0/live-parity-mustfix-progress-20261001.md` | Presente (posible stale vs reports ~16:58) |
| Dump ge10 | `data/samples/helius_parity_tx_dump_ge10_20261001.csv` + `_meta.json` | Presente (~16:49 CEST) |
| Gate 0 trades >t0 | `data/samples/qa_helius_parity_tx_dump_le_t0_report.json` | **PASS** (`ok:true`, `n_ts_gt_t0:0`) |
| QA static parity | `data/samples/qa_live_train_parity_report.json` | **PASS** (`hard_fails=[]`) |
| QA replay ge10 | `data/samples/qa_helius_parity_replay_ge10_report.json` | 10/12 ≥0.99; soft recovery fails |
| Paper journal | `data/paper_live/` | Congelado (política BOSS) |
| Audits previos `cycle0/audit-*.md` | — | Ninguno antes de este archivo |

---

## 2. Residuales ABIERTOS

| ID | Veredicto | Síntoma | Evidencia | Owner | Sev |
|----|-----------|---------|-----------|-------|-----|
| **SD-REC-01** | **FAIL** | Recovery create→T0: **1 trade** vs train **3–4** buys; `recovery_improved=false`; `stuck_rpc_gap=true` | `_meta.json` fail_targets BZof/4M3g; SolQA `polish_remaining` | **SolDatos** (re-dump); SolQA re-gate | **P0** |
| **LIVE-SCORE-GAP** | **FAIL** | Scores live histgb ~0.15–0.25 vs thr **0.99** (enrich incompleto) | `qa_helius_parity_tx_dump_le_t0_report.json`; journal scores | SolDatos enrich (+ SolModelos si recalib) | **P0** |
| **SD-SIDE-01** | **OPEN** | feePayer net-flow ≠ Dune WSOL sold/bought (same-sig) | mismatch-hunt SD-SIDE-01 | SolDatos | P1 |
| **Q5b-HOLDERS** | **OPEN** | Holders/top shares sesgados si Q5a incompleto; sin snapshot ≤T0 | `live-parity-fix-20261001.md` | SolDatos | P1 |
| **PRIORS-INDEX** | **OPEN** | Índice causal post-cutoff / frescor store | mismatch-hunt P1 #5 | SolDatos | P1 |
| **FEE/PARSE** | **OPEN** | Residual feePayer/trader_id | mustfix Residual OPEN #4 | SolDatos | P1 |

### Cerrados / PASS (no reabrir sin regresión)

| Item | Veredicto | Evidencia |
|------|-----------|-----------|
| Recipe 51 cols == joblib | **PASS** | `qa_live_train_parity_report.json` |
| Gate 0 trades `ts>t0` en dump ge10 | **PASS** | `qa_helius_parity_tx_dump_le_t0_report.json` |
| Scale 6.6× OFF; max_buy live/dune ≈1.017 | **PASS** | Path A / mismatch-hunt |
| Gates código prior/t0_refined/umbral 0.99 | **PASS** | mismatch-hunt SolQA FIXED |

**Nota Pyth:** `live-parity-mustfix-progress` (~16:42) mencionaba key ausente; report SolQA (~16:58) ya muestra `pyth_asof` + `dune_cohort_*` en journal. **No** marcar Pyth OPEN sin re-check ops.

---

## 3. Detalle P0 — BZof / 4M3g (`n_trades`)

| Campo | BZof…pump | 4M3g…pump |
|-------|-----------|-----------|
| Esperado train `buy_count_total` | **4** | **3** |
| Actual `n_trades_le_t0` | **1** | **1** |
| Replay live_rebuild score | **0.731** | **0.573** |
| OOS referencia | ~0.9998 | ~0.9998 |
| Causas doc. | mint max_pages / rpc short_reached | Helius Enhanced **HTTP 429**, `rpc_empty` |

- Anti-LA: **PASS** (0 trades >t0).
- Veredicto: **OPEN / FAIL recovery** — undercount pre-T0, no look-ahead.
- Criterio de cierre: `n_trades≈train (3–4)`, `recovery_improved=true`, re-replay score ≥ umbral; SolQA re-corre gate tras re-dump SolDatos.

---

## 4. Next (orden)

1. **SolDatos:** cerrar recovery BZof/4M3g + re-dump post-fix (stuck_rpc_gap / 429).
2. **SolQA:** re-gate 0>t0 + `n_trades` vs Dune al llegar re-dump.
3. **SolAuditor:** re-auditar entrega → `cycle0/audit-*.md` PASS/FAIL; **no** reabrir paper hasta paridad exacta.
4. P1 en paralelo solo si no diluye P0.

---

## 5. Mapa protocolo (baseline)

Checklist V1–V8 del protocolo siguen en plantilla (casillas sin marcar en markdown). Evidencia live actual se ancla a reports SolQA JSON + mismatch-hunt, no a un barrido V1–V8 automatizado completo en este baseline. Próximo audit de entrega puede cruzar LP.* checklist ítem a ítem.
