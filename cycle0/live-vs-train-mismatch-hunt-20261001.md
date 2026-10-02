# Live ≠ train mismatch hunt — ZERO tolerance (2026-10-01)

**Owner:** SolQA/SolModelos hunt · **Repo:** `/workspace/solana-10x`  
**Comparación:** `paper_live` (hybrid Pump+Helius, `histgb_q5b`) vs train store / WF `FEATURE_SETS['+q5b']` + `q5b_last.joblib`  
**Política Sinck:** **ZERO tolerance** — toda divergencia es **MUST-FIX** (o **BLOCKER** si no se puede cerrar en este turno). **No hay ACCEPTABLE.**  
**No se afirma 100% parity.**

**Modelo / calib:** `data/paper_live/models/q5b_last.joblib` · `q5b_calibration.json`  
**Train store:** `data/samples/features_dune_p0_q5_expand_v2.csv` (label `hit_10x_30d`)  
**Journal live (corte ~16:36 CEST):** `data/paper_live/paper_journal.sqlite`  
**Proceso vivo al cierre:**  
`python -m paper_live --live ... --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.99`

---

## Resumen ejecutivo

| Área | ¿Paridad? | Severidad |
|------|-----------|-----------|
| Nombres/orden X vs joblib (51) | **MATCH** | — |
| USD (`sol×oracle` vs Dune `amount_usd`) | **MISMATCH** | MUST-FIX / BLOCKER recalib |
| Ventanas 5s/30s/60s/15m vs T0 | **MATCH** (defs código) | residual datos |
| Buy/sell + universo project | **MISMATCH** (parcialmente FIXED hoy) | MUST-FIX residual |
| Creator priors source | **FIXED código** (exact+recompute; no pump default) | MUST-FIX residual store frescor |
| Holders / Q5b proxies | **MISMATCH** residual | MUST-FIX |
| Definición T0 | **MISMATCH** operativo | MUST-FIX |
| Imputation / missing flags | **FIXED** all_in_window=None + doc | MUST-FIX residual re-score journal |
| Umbral 0.99 vs train top1% | **PRODUCT** Sinck 0.99 (hard reject removed) | ops: document vs Entrada A |
| Journal scores vs esperado train | **MISMATCH** | MUST-FIX evidencia |

**Fixes aplicados en este hunt (código):** ver §Fixes. Restantes = blockers / ops / SolDatos / SolModelos.

---

## 1) Feature names / order vs joblib

| Check | Train | Live | Status |
|-------|-------|------|--------|
| Set | `FEATURE_SETS['+q5b']` | `histgb_q5b` → same | MUST verify continuous |
| n cols | 51 | 51 | MATCH |
| order | tuple in `post_q5_sets.py` | `blob['feature_names']` | **MATCH** (`assert_recipe_matches_joblib` PASS) |
| banned in X | `migrated_pre_t0`, join-only, labels | stripped via recipe | MATCH |
| Gate | — | `src/paper_live/recipe_parity.py` + `verification.live_parity` | keep green |

**MUST-FIX residual:** CI/cron gate must fail deploy if joblib re-export drifts; no auto-skip.

---

## 2) USD formula (sol×oracle vs Dune)

| | Train | Live |
|---|-------|------|
| Definición | Dune `dex_solana.trades.amount_usd` | `amount_usd = sol_amt * sol_usd_asof_t0` |
| Precio implícito | `max_buy_usd/max_buy_sol` mediana ≈ **103.11** | Pyth as-of → CoinGecko as-of → Jupiter live → ref 103.11 |
| Escala ciega 6.6× | — | `APPLY_DUNE_HELIUS_USD_SCALE` **OFF** (correcto no inventar) |

**Journal (histgb_q5b):** `sol_usd_source` ≈ jupiter **498**, coingecko_asof **15**, jupiter_live_not_asof **1**, None **475** — **casi nunca Pyth**. Producto captura v0.3 exige Pyth as-of.

**MUST-FIX / BLOCKER**
1. Forzar cadena Pyth as-of en todo enrich histórico y live; fallar / `capture_quality=LOW` + **skip score** si no hay Pyth (hoy se scorea con Jupiter).
2. Paridad económica con train **no** se cierra solo con oracle: Dune `amount_usd` ≠ `sol×spot` en todos los snipers. Opciones (elige BOSS, cero tolerancia no permite “dejarlo”):
   - **A)** Re-entrenar HistGB en features Helius-scale (mismo oracle), o
   - **B)** Rebuild train USD legs con `sol_amt × pyth_asof` y re-fit, o
   - **C)** Factor documentado + re-calib thresholds (no 6.6 ciego sin evidencia por mint).
3. Registrar `sol_usd_t0` + `sol_usd_source` en journal siempre (hoy muchos `None` legacy).

---

## 3) Window defs (5s / 30s / 60s / 15m) relative to T0

| Feature window | Train (Dune SQL) | Live (`q5a_agg` / `buy_vol`) | Def match? |
|----------------|------------------|------------------------------|------------|
| buy/sell **30s** | `secs_before_t0 BETWEEN 0 AND 30` | `(t0−ts) ∈ [0,30]` | MATCH |
| buy/sell **15m** | `BETWEEN 0 AND 900` | `[0,900]` | MATCH |
| buy60 | Q4 `BETWEEN 0 AND 60` | `[t0−60, t0]` buys only | MATCH |
| **first 5s / 10s** | `secs_after_first` from **first trade ≤T0** | same | MATCH |
| first5 / first10 **buys** | `buy_rn` by time ASC, amount DESC | same sort | MATCH |

**MUST-FIX residual (datos, no fórmula):** recovery incompleta de trades ≤T0 (paginación / 429 / hot mint) hace que las ventanas estén **correctas pero vacías/submuestreadas** vs Dune (históricamente 1 vs 5–7 trades). Ver `live-helius-pre-t0-pagination.md` + replay ge10. Replay post-fix 10/12 ≥0.99 no implica journal live poblacional parity.

---

## 4) Buy / sell classification + project universe

| | Train | Live (antes → después este hunt) |
|---|-------|----------------------------------|
| Side | WSOL sold→**buy** token; WSOL bought→**sell** | Net mint token flow to `feePayer` |
| Project filter | `project IN ('pumpdotfun','pumpswap')` | Antes: Jupiter/OKX contaban; `other`→**pumpdotfun**; RAYDIUM→pumpswap |
| Min USD | `amount_usd >= 1` | `min_amount_usd=1` (post oracle) |
| Trader id | Dune `trader_id` | Helius `feePayer` |

**FIXED hoy (`helius_enrich.parse_helius_enhanced_txs`):**
- Drop `project not in {pumpdotfun, pumpswap}`.
- Remove `other → pumpdotfun` remap.
- Remove RAYDIUM from pumpswap set (solo `PUMP_SWAP`/`PUMPSWAP`/`PUMP_AMM`).

**MUST-FIX residual / BLOCKER**
1. Side via feePayer net-flow ≠ Dune token_sold/bought WSOL — cuantificar mismatch en muestra parity (misma firma).
2. `trader_id` feePayer vs Dune trader — concentra top1/top5/holders distinto en rutas agregadoras.
3. Reiniciar proceso live para cargar código nuevo (PID actual sigue en binario viejo hasta restart).

---

## 5) Creator priors source

| | Train | Live (post SolModelos 2026-10-01) |
|---|-------|------|
| Fuente | `add_cohort_creator_priors` sobre cohort Dune expand (create_ts causal) | **A)** `dune_cohort_exact` row lookup expand_v2 → q5b CSV; **B)** `dune_cohort_recompute` uncapped (`window_days=None`); **C)** `none`/`dune_cohort_empty` → counts 0. Pump **off** unless `ALLOW_PUMP_FRONTEND_PRIORS=1` |
| Ventanas | 7d / 30d / cohort rank (cohort = all earlier, no 30d cap on list) | same via exact copy or `q5b_from_create` |
| Cobertura | Solo mints **en cohort** (subestima fuera) | Exact on train mints; recompute for live mints using static cohort index (still no post-`train_t0_max` creates) |
| Audit | — | `creator_prior_source` always on features; legacy alias `train_store_v1` |

**Bug fixed:** live used `priors_for(..., window_days=30)` capping **all** priors at 30d → cohort undercount vs train; then fell back to `pump_frontend_30d` → live median prior_7d ~14 vs train ~1.

**FIXED (código):** `creator_priors.py` + `helius_enrich.py` — exact + uncapped recompute; no pump default.

**MUST-FIX residual (SolDatos / BOSS)**
1. Static store still misses creates after train cutoff / outside CSV — need updatable causal create index (Bitquery/Helius) **or** re-fit train on live source.
2. Restart live process to load patch (ops).

---

## 6) Holders / Q5b proxies

| Proxy | Train | Live | Notas |
|-------|-------|------|-------|
| `n_holders_proxy` | SQL final = `n_pos_holders_proxy` (`net_tok>0`) | `len(pos_holders)` net_tok>0 | Def MATCH; inputs trader/tok pueden diferir |
| top1/5/10 holder pct | net_tok shares | same | MATCH def |
| `progress_curve_proxy` | `net_sol_curve/85` clip [0,2] trade-only | same agg; **antes** overlay frontend si 0 trades | |
| `age_s` / `age_min` | create_ts Dune ≤T0 | Pump create / sighting | |
| name/symbol lens | CreateEvent | Pump + sighting fill | |

**FIXED hoy:** eliminado overlay `curve_progress_proxy` / `net_sol_curve_proxy` frontend cuando Helius trae 0 trades (rompe paridad Dune trade-only → ceros).

**MUST-FIX residual**
1. `age_s` journal: **107 / 910** con `age_s > 1d` (hasta ~2e7 s) — mints viejos re-vistos en banda o `create_ts` mal resuelto. Train snipers OOS≥0.99 tienen `age_s≈0`. Filtrar / exigir create≤T0 fresco alineado a captura C1–C6.
2. Q5b name/symbol desde sighting puede diferir de CreateEvent Dune.
3. Path `enrich_via=pump` sigue metiendo curve proxies frontend (`pump_enrich.py`) — no produce X completo, pero **MUST-FIX** si se usa para scoring parcial.

---

## 7) T0 definition

| | Train | Live |
|---|-------|------|
| Definición producto | C1–C6 (`definicion-captura-v0.md`) | Poll: first sighting MC∈[8k,20k]; opcional `find_t0_c1_c6` refine |
| Journal `t0_refined` | — | True **58**, False **456**, None **475** |
| Replay score parity | suele `refine_t0=False` + OOS `t0_ts` | live `refine_t0=True` |

**MUST-FIX**
1. No scorear paper-enter con `capture_quality=LOW` / `t0_refined=False` si train exige C1–C6.
2. Alinear MC: frontend `usd_market_cap` vs reserve MC `(vs*S/vt)/1e9*SOL_USD` — train labels usan path Dune/captura.
3. Congelar política: replay siempre documenta refine on/off; prod solo entra si refine+Pyth (o skip).

---

## 8) Imputation / missing flags

| | Train | Live |
|---|-------|------|
| Pipeline | `SimpleImputer(median)` + HistGB (**no** StandardScaler) | same joblib |
| Completeness gate | filas train con packs mergeados | `required_q5b_present` — skip si falta col (salvo null-ok) |
| `creator_prior_mints_all_in_window` | **~99.988% NULL** en store | **siempre None** (`q5b_agg` + exact overlay) |

**FIXED hoy (`q5b_agg`):** `creator_prior_mints_all_in_window` **siempre None** (paridad train; imputer usa mediana train ≈ null path).

**Doc:** `cycle0/imputation-q5b-live-train.md` — pipeline, null-ok shares, verify recipe_parity + joblib imputer stats.

**MUST-FIX residual**
1. Re-score / no confiar en scores journal previos con `all_in_window=0.0`.
2. Auditar otras cols: shares null-ok solo si `buy_count_total==0`; no rellenar 0 “falso observado”.
3. `skip_incomplete_q5b` journal n=81 — OK policy; no sustituir con fallback DEBUG.

---

## 9) Score threshold 0.99 vs train top1%

| Regla | Valor | Origen |
|-------|-------|--------|
| TrainQ top1% (fold-5 TRAIN) | **0.9998068280570067** | `q5b_calibration.json` / joblib |
| TrainQ top5% | 0.9997995037737603 | same |
| Default código (`score_threshold=None`) | calib top_frac=0.01 → **≈0.999807** | Entrada A alternate |
| **Producto Sinck (elegido)** | **`--score-threshold 0.99`** | abs floor; **keep** — do not revert without Sinck |
| Sweep OOS abs 0.99 | sweet-spot throughput (paper) | product rule (not “trainQ parity”) |

**SolModelos (2026-10-01):** removed hard reject of explicit 0.99 in `resolve_score_threshold` — if `score_threshold` is set, **return it** (no raise). `--allow-non-train-threshold` retained as harmless no-op. Default when omitted remains trainQ.

**Status (Sinck):** umbral live **0.99 abs** es elección de producto — **NO revertir** a trainQ sin Sinck.  
Documentar que 0.99 ≠ train top1% (reglas distintas). Parity de **features** sigue ZERO tolerance; threshold ops = Sinck.
Candidates históricos (158) con scores bajos / `rule_buy60` no son evidencia de selectividad HistGB@0.99.

---

## 10) Live journal recent scores vs expected

**Universo:** `score_mode=histgb_q5b`, n≈908–910.

| Métrica | Live journal | Esperado si parity + snipers train-like |
|---------|--------------|----------------------------------------|
| max score | **0.926** | cola ≥ **0.99** / top1% ≥ **0.9998** |
| n ≥ 0.99 | **0** | >0 si hay snipers recuperados |
| n ≥ trainQ top1% | **0** | — |
| n ≥ 0.5 | 6 | — |
| mediana | ~0.10 | train mediana ~0.17; snipers ~0.999+ |
| buy60 mediana | ~103 | train OOS≥0.99 ~5e4–3e5 |
| age_s mediana | ~42 | snipers train ~0 |

**Conclusión:** descalibration **operativa vigente** en journal (población + USD source + priors + T0 + código viejo pre-fix). Replay Helius ge10 post-paginación recuperó **10/12** highs OOS≥0.99 — demuestra que **joblib OK** y que el gap journal ≠ “modelo roto”, pero **no** cierra ZERO tolerance en live stream.

**MUST-FIX**
1. Restart live con patches §Fixes + umbral trainQ.
2. Tras N ciclos: exigir distribución scores (p99 live vs p99 train OOS) y tasa ≥0.99 en mints con `n_trades_pre_t0`≈Dune.
3. No paper-enter hasta gates §7–§9 verdes.

---

## Fixes aplicados este turno (código)

| Archivo | Cambio |
|---------|--------|
| `src/paper_live/q5b_agg.py` | `creator_prior_mints_all_in_window` siempre `None` |
| `src/paper_live/helius_enrich.py` | Filtro project pumpdotfun/pumpswap; sin overlay curve; **priors:** exact/recompute via `resolve_creator_priors`; no pump default; `creator_prior_source` |
| `src/paper_live/creator_priors.py` | expand_v2 first; exact mint lookup; `priors_for(window_days=None)`; `ALLOW_PUMP_FRONTEND_PRIORS` |
| `src/paper_live/entry.py` (+ config/`__main__`) | **UNDO** hard reject of `--score-threshold 0.99`; explicit threshold returned |
| `cycle0/imputation-q5b-live-train.md` | imputation + verify recipe |

**No reiniciado** el proceso live — requiere acción ops explícita.

---

## MUST-FIX backlog (prioridad)

### P0 — BLOCKER (parity / selectividad)
1. **Umbral:** Sinck frozen **0.99 abs** — do not revert; feature parity separate from threshold ops.
2. **USD:** Pyth as-of obligatorio o skip; plan A/B/C recalib Helius↔Dune (§2).
3. **Restart** paper_live para cargar patches project/all_in_window/overlay.
4. **T0:** no enter si no C1–C6 + quality HIGH/MED Pyth.

### P1 — MUST-FIX (features)
5. Creator priors: código exact+recompute DONE; residual = índice causal actualizable post-train cutoff (SolDatos).
6. Cuantificar buy/sell feePayer vs Dune WSOL side + trader_id.
7. Filtrar age_s anómalo / mints fuera captura.
8. Persistencia audit: `sol_usd_source`, `creator_prior_source`, `n_trades_pre_t0`, `t0_refined` en todo score row.

### P2 — MUST-FIX (evidencia)
9. Re-score journal post-restart; comparar p50/p99 vs OOS.
10. Sample firmas: Dune amount_usd vs sol×pyth_asof mismo trade.
11. Gate CI: `python -m verification.live_parity` + recipe joblib en cada export modelo.

---

## MATCH confirmados (no eximen ZERO tolerance global)

- Recipe 51 cols nombre+orden == joblib.
- Ventanas 30s/60s/15m/first5–10s **definiciones** alineadas a SQL.
- `n_holders_proxy` def = net_tok>0 (SQL final).
- Imputer median en pipeline joblib.
- `APPLY_DUNE_HELIUS_USD_SCALE` default OFF.
- Anti look-ahead agg `ts≤t0` en `q5a_agg`.

---

## Artefactos

| Path | Rol |
|------|-----|
| `cycle0/live-vs-train-mismatch-hunt-20261001.md` | este informe |
| `cycle0/live-vs-train-score-replay-20261001.md` | diag descalibration |
| `cycle0/live-parity-fix-20261001.md` | replay ge10 post-paginación |
| `cycle0/live-train-parity-qa-checklist.md` | gates QA |
| `cycle0/score-threshold-sweep-20261001.md` | 0.99 vs trainQ (reglas distintas) |
| `data/paper_live/models/q5b_calibration.json` | top1% = 0.9998068… |

---

---

## SolDatos — residual mismatches + code status (2026-10-01, UTC+2)

**Scope:** `src/ingestion/*` hooks only (BOSS owns `paper_live` wiring).  
**Policy:** ZERO acceptable residual for SolDatos-owned defs. Threshold **0.99 stays** (Sinck).  
**Honesty:** ge10 **10/12 ≥0.99** is **not** parity — BZof/4M3g still fail; all 12 had `t0_refined=False` / `capture_quality=LOW` / `coingecko_asof` (not Pyth) in prior replay.

### What is still NOT identical (SolDatos)

1. **Oracle:** live scoring must be `sol_amt × pyth_asof`; Hermes currently **unavailable** here → `require_pyth_asof` returns None → **skip score** (OPEN ops: `PYTH_API_KEY`). Firmas compare shows CoinGecko fallback already ≈ Dune `max_buy_usd` (med ratio **1.017**) — **not** a 6.6× problem.
2. **Buy/sell / project:** parse moved to `ingestion.helius_trade_parse` (WSOL pair heuristic, pumpdotfun/pumpswap only, min $1, feePayer). Side still feePayer net-flow vs Dune token_sold/bought — OPEN quantify on same sig.
3. **T0 C1–C6:** `is_scoreable_capture` **refuses** LOW/unrefined/non-Pyth. Prior journal scored provisional T0 — OPEN until paper_live calls the gate.
4. **create→T0:** `fetch_create_to_t0_txs` (BC Enhanced + RPC BC **and** mint, max_pages_rpc=120). BZof/4M3g still **OPEN** until re-replay proves n_trades≈Dune.
5. **age_s:** `ingestion.q5b_age.age_s_from_create` = Q5b `create_ts→t0`; rejects age>1d. Must not use Q5a `age_proxy_s` for X.

### Mismatch table (SolDatos)

| ID | Area | Live | Train | Δ / evidence | Severity | Fix owner | Status |
|----|------|------|-------|--------------|----------|-----------|--------|
| SD-USD-01 | Oracle as-of | `amount_usd=sol×oracle`; prefer Pyth | Dune `amount_usd` | Firmas ge10: live/dune max_buy med **1.017** (`artifacts/dune_helius_usd_firmas_compare_20261001.csv`). Pyth as-of **FAIL** → all FALLBACK coingecko_asof. Scale 6.6× **OFF**/rejected. | P0 | SolDatos | **FIXED** formula Path A + `require_pyth_asof` / `resolve_sol_usd_for_scoring`; **OPEN** Hermes key / skip-score wire |
| SD-USD-02 | Recalib plan | Helius-scale reconstruct | Dune store | Path **A** chosen: match Dune semantics via `sol×pyth_asof` (fastest live≡train w/o blind 6.6×). Path B = SolModelos rebuild train on sol×pyth. Path C = per-mint factor last resort. | P0 | SolDatos→SolModelos | **FIXED** plan in `USD_RECALIB_PLAN`; A implemented in ingestion |
| SD-SIDE-01 | Buy/sell def | feePayer net mint flow | WSOL sold/bought | `helius_trade_parse` dune filters; no RAYDIUM→pumpswap; no other→pump remap | P1 | SolDatos | **FIXED** canonical parse; **OPEN** same-sig side audit |
| SD-T0-01 | C1–C6 vs train T0 | poll provisional + refine | Q3 first MC∈[8k,20k] + captura C1–C6 | `find_t0_c1_c6` + `find_t0_c1_c6_train_aligned` + `find_t0_dune_q3`; **`is_scoreable_capture` refuses LOW/unrefined/non-Pyth** | P0 | SolDatos | **FIXED** gate in ingestion; **OPEN** paper_live must call gate (BOSS) |
| SD-REC-01 | create→T0 recovery | Enhanced mint pages / 1 trade | Dune 3–7 buys | BZof 0.73 / 4M3g 0.57; `fetch_create_to_t0_txs` BC+mint RPC | P0 | SolDatos | **fixing** helper landed; **OPEN** re-replay BZof/4M3g |
| SD-AGE-01 | age_s | journal age_proxy / bad create (107/910 >1d) | Q5b `date_diff(create,t0)` | `q5b_age.age_s_from_create` + `AGE_MAX_SCOREABLE_S=1d` | P0 | SolDatos | **FIXED** hook; **OPEN** wire + filter in enrich (BOSS) |

### Code landed (`src/ingestion/`)

| File | Change |
|------|--------|
| `sol_usd_oracle.py` | Path A docs; `require_pyth_asof`, `resolve_sol_usd_for_scoring`, `amount_usd_dune_compatible`, `USD_RECALIB_PLAN`; Hermes Bearer+X-API-KEY |
| `helius_trade_parse.py` | Canonical Dune-parity parse (project/minUSD/WSOL heuristic) |
| `helius_enhanced.py` | `get_transactions_by_signatures`, `fetch_create_to_t0_txs` (BC+mint RPC, rpc pages 120) |
| `t0_capture.py` | `find_t0_dune_q3`, `find_t0_c1_c6_train_aligned`, **`is_scoreable_capture` / `score_reject_reason` / `require_scoreable_capture`** |
| `q5b_age.py` | **NEW** create_ts→age_s + anomaly filter |
| `cycle0/scripts_dune_helius_usd_firmas_compare_20261001.py` | Sample firmas Dune vs sol×oracle |
| `tests/ingestion/test_soldatos_parity_hooks_20261001.py` | 7 passed |

### Remaining blockers (cannot Δ≈0 in SolDatos alone)

| Blocker | Why | Owner |
|---------|-----|-------|
| Hermes 401 without `PYTH_API_KEY` | Scoring gate requires Pyth → all captures skip until key | Ops / SolDatos |
| paper_live must call `is_scoreable_capture` + `age_s_from_create` + `resolve_sol_usd_for_scoring(require_pyth=True)` | BOSS owns paper_live — hooks ready | BOSS |
| BZof / 4M3g trade undercount | Need live re-replay with `fetch_create_to_t0_txs` proving n_trades | SolDatos verify |
| Train labels with age_s=0 vs product C4≥30s | If strict C4-only scoring, SolModelos must refilter cohort to C1–C6 | SolModelos |
| Blind 6.6× | **Rejected** — firmas show ~1.0× on max_buy | — |

### P0 residuals (SolDatos)

1. **SD-USD-01 OPEN:** Pyth as-of not reachable → enforce skip-score (hook ready).  
2. **SD-T0-01 OPEN:** wire `is_scoreable_capture` in enrich/loop (BOSS).  
3. **SD-REC-01 OPEN:** BZof/4M3g still 1 trade in last ge10 CSV.  
4. **SD-AGE-01 OPEN:** wire `age_s_from_create` + drop anomalous (BOSS).


## Veredicto

**Parity 100%: NO.**  
Recipe/joblib OK; **USD, umbral live 0.99, priors, T0 operativo, sol_usd_source, journal scores** siguen **MUST-FIX**. Tres bugs de feature wiring se corrigieron en código; **no están en el proceso vivo hasta restart**. Bajo ZERO tolerance no se marca ningún residual como ACCEPTABLE.


---

## SolQA gates (2026-10-01 tarde)

| Gate | Status |
|------|--------|
| prior≠train → FAIL | **FIXED** `skip_prior_not_train` (recipe complete; need `dune_cohort_*`) |
| t0 no refined → FAIL | **FIXED** `skip_t0_not_refined` (ya en score) |
| umbral≠config → FAIL | **FIXED** `EntryGate` + `live_entry_config.json` (**0.99** Sinck; no trainQ) |

Artefactos: `data/paper_live/models/live_entry_config.json` · `src/verification/live_parity.py` · `data/samples/qa_live_train_parity_report.json`

---

## Follow-up 2026-10-01 — Q5b meta train parity (SolModelos)

Live `name_len`/`symbol_len`=0 vs train nonzero (ge10 feature-Δ; 2hCEWY soft Δscore ~2e-3 partly meta). Trades for 2hCEWY already **6=6** (SolDatos).
**Fix:** prefer create/sighting meta; else exact store fill (`meta_source=dune_store_exact`).
Doc: `cycle0/q5b-meta-features-train-parity-20261001.md`. Residual = USD/vol (Path A), not meta / not trade count.
Paper FROZEN; no joblib retrain.
