# Live vs train score replay — descalibration diagnosis

**Fecha:** 2026-10-01 (Europe/Madrid, UTC+2)  
**Repo:** `/workspace/solana-10x`  
**Modelo:** `data/paper_live/models/q5b_last.joblib` (`histgb_q5b`, set `+q5b`, fold 5)  
**OOS:** `data/samples/wf_post_q5_oos_predictions.csv` (filtro `set=+q5b`)  
**Artefactos:** `cycle0/artifacts/`

## Veredicto (claro)

**SÍ — las features live colapsan / desescalan los scores** respecto al OOS train en mints que en WF eran ≥0.99.

| Pregunta | Respuesta |
|----------|-----------|
| ¿El joblib exportado está roto? | **NO** — re-score con vectores del feature store = OOS del último fold (Δ≈0) |
| ¿Rebuild Helius ≤T0 de snipers OOS mantiene ≥0.99? | **NO** — 0/3 altos; scores ~0.63–0.78 |
| ¿El journal live alcanza trainQ top1% (≈0.9998)? | **NO** — max histgb ≈0.926; 0/804 ≥0.99 |

## 1. Muestra OOS

Fuente: `wf_post_q5_oos_predictions.csv`, `set=+q5b` (paper live = `histgb_q5b` / `FEATURE_SETS['+q5b']`).

| Banda | n | Criterio |
|-------|---|----------|
| `high_ge0.99` | 40 | score≥0.99 (mezcla recientes Sep20–22 + stratified y) |
| `mid_~0.5` | 10 | score ∈ [0.40, 0.60] |
| `low_~0.1` | 10 | score ∈ [0.05, 0.15] |
| **Total** | **60** | `cycle0/artifacts/sample_mints.csv` |

## 2. Re-score con feature store (train) + joblib live

Join: `features_dune_p0_q5_expand_v2.csv` → `predict_proba` con `q5b_last.joblib`.

| Subconjunto | \|Δ\| median (oos − rescore) |
|-------------|------------------------------|
| Toda la muestra | ~1.4e-4 |
| OOS post `train_t0_max` (fold 5) | **≈0** (1e-16) |
| Folds anteriores | ~0.009 (esperado: OOS usó otro modelo de fold) |

**Conclusión:** el pipeline de score live y el joblib son fieles al train. La descalibration **no** es un bug de export/imputer.

## 3. Rebuild live (Helius ≤T0) en t0 histórico

### Límites honestos

1. **Enhanced newest→oldest:** mints calientes (Sep 22 → hoy) requieren muchas páginas para llegar a create≈t0. Con `max_pages=50` (5000 txs) a menudo **no** se alcanza el suelo create; los trades pre-T0 útiles salieron sobre todo del **bonding-curve PDA** (pocas txs).
2. **429:** un primer intento perdió páginas parciales al fallar mid-paginación → `n_txs=0` falso. Replay robusto con retry + merge mint+BC.
3. **Priors Pump frontend** no son archivo Dune histórico → se **inyectaron priors Q5b del train store** (causales Dune) para no confundir drift de creator-index con Q5a/buy60.
4. **`refine_t0=False`:** se fijó el `t0_ts` OOS (sin look-ahead de C1–C6).
5. **SOL/USD:** oracle live Jupiter ≈117.6 (no el SOL histórico exacto del t0).
6. Replay profundo solo en **5 mints** (3 high + 1 mid + 1 low) por presupuesto API.

### Resultados Helius robusto (`helius_historical_replay_robust.csv`)

| mint (12) | band | oos | live rebuild | Δ | buy60 live | buy60 train | trades ≤T0 |
|-----------|------|-----|--------------|---|------------|-------------|------------|
| 69xneXbByUnx | high | 0.9995 | **0.771** | +0.229 | 9996 | 24880 | 1 |
| BZofTtkyrBM2 | high | 0.9998 | **0.775** | +0.225 | 9996 | 28770 | 1 |
| 4M3gYZ2dQ39K | high | 0.9998 | **0.630** | +0.370 | 9996 | 346531 | 1 |
| EH2j3pjSnJ1Q | mid | 0.497 | 0.572 | −0.076 | 8538 | 7026 | 6 |
| 85nwGzjZ8JC4 | low | 0.088 | 0.064 | +0.024 | 58 | 366 | 1 |

**Altos (n=3):**

| Umbral | % que se mantienen |
|--------|-------------------|
| ≥0.99 | **0%** |
| ≥0.89 | **0%** |
| ≥0.50 | 100% |

Mid/low no “explotan” hacia arriba: el rebuild no inventa snipers.

## 4. Por qué colapsan (aislamiento)

### A) Escala USD Dune ≫ Helius

En train OOS≥0.99, `buy_vol_usd_60s / net_sol_curve` mediana ≈ **681 USD/SOL** (~6.6× vs ref train ~103).  
Helius live: `sol_amt × oracle ≈117` → buy60 sniper tipico ~**10k** (un buy ~85 SOL cerca de graduación), no 25k–346k.

Aislamiento (`scale_isolation.csv`), media en 3 highs:

| Variante | score medio |
|----------|-------------|
| Train store | 0.9997 |
| Solo `buy_vol_usd_60s` → live | 0.973 |
| Escalar todos los USD por ratio buy60 | 0.863 |
| Overlay deltas clave live | 0.955 |
| **Rebuild Helius completo** | **0.725** |

La escala USD sola baja poco (~0.97); el **rebuild incompleto de Q5a** (1 trade vs 5–7 en Dune) empuja a ~0.63–0.78.

### B) Población live ≠ snipers de train

Journal `histgb_q5b` completo (n=804), 2026-10-01:

| Feature (mediana) | Train OOS≥0.99 | Live journal |
|-------------------|----------------|--------------|
| `buy_vol_usd_60s` | ~59 145 | ~183 |
| `age_s` | 0 | ~45 |
| `sniper_vol_share_5s` | 1.0 | ~0.51 |
| `progress_curve_proxy` | ~1.0 | ~0.012 |
| `net_sol_curve` | ~85 | ~1.0 |
| score max / ≥0.99 | — | 0.926 / **0%** |

### C) Perturbación controlada (train high → “cara live”)

Sobre los 40 vectores high del sample (`perturbation_collapse.csv`):

| Escenario | median score | %≥0.99 |
|-----------|--------------|--------|
| base train | 0.9998 | 92.5% |
| solo age live | 0.9997 | 92.5% |
| buy60 → mediana live | 0.953 | **0%** |
| **combo tipico live** | **0.348** | **0%** |

## 5. Enrich live reciente

No hace falta re-llamar Helius para “unos mints recientes”: el journal ya es el pipeline paper_live (`--enrich-via helius`).  
804 vectores `histgb_q5b` completos; max 0.926; mediana ~0.106; **ninguno** ≥ trainQ top1% (0.9998).  
Eso confirma descalibration operativa *y* ausencia de snipers train-like en la banda poll actual.

## 6. Respuesta operativa

1. **Descaled: SÍ** para snipers OOS al pasar por enrich Helius ≤T0 (pierden el umbral ultra-select).  
2. **No es (solo) “no hay snipers”:** aunque hay efecto población, el **mismo mint** histórico alto cae ~0.23–0.37 al rebuild.  
3. **Arreglos candidatos (fuera de este diagnóstico):**
   - Re-entrenar / recalibrar HistGB con features en escala Helius (o factor de escala Dune→Helius documentado).
   - Mejorar recuperación de trades pre-T0 (más páginas, priorizar bonding-curve, floor create).
   - No usar umbral trainQ top1% entrenado en USD Dune inflados sin mapear a live.

## Archivos

| Path | Contenido |
|------|-----------|
| `cycle0/live-vs-train-score-replay-20261001.md` | este informe |
| `cycle0/artifacts/sample_mints.csv` | muestra 60 |
| `cycle0/artifacts/sample_train_rescore.csv` | OOS vs train-store rescore |
| `cycle0/artifacts/helius_historical_replay_robust.csv` | rebuild Helius |
| `cycle0/artifacts/helius_historical_replay_robust.json` | + feature deltas |
| `cycle0/artifacts/feature_dist_train_hi_vs_live.csv` | medianas train-hi vs live |
| `cycle0/artifacts/perturbation_collapse.csv` | escenarios sintéticos |
| `cycle0/artifacts/scale_isolation.csv` | aislamiento escala USD |
| `cycle0/artifacts/final_stats.json` | blob numérico |
