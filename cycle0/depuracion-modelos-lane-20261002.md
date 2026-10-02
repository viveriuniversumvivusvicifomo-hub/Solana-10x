# Depuración lane modelos — 2026-10-02 (SolModelos → BOSS / SolAuditor)

**Fecha:** 2026-10-02 ~14:15 CEST (Europe/Madrid)  
**Constraints:** sin train · sin overwrite `q5b_last` · sin restart paper · 0 APIs de pago  
**Acción:** **quarantine only** (ficheros en disco, marcados NO-GO; **no** move a `quarantine/` para no romper refs).

## Paths entregados

| Entregable | Path |
|------------|------|
| Inventario NO-GO | `cycle0/quarantine-q5b-pump-joblibs-20261002.md` |
| Receta canónica Path A train | `cycle0/recipe-path-a-train-canonical-20261002.md` |
| Criterio GO vs `q5b_last` | `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` |
| Esta nota | `cycle0/depuracion-modelos-lane-20261002.md` |

## Resumen

1. **Inventario:** los 6 `q5b_pump_*.joblib` (+ calib) son **NO-GO** frente a producción. Motivos: colapso de masa de score en journal, n pequeño, mismatch soft/hard vs live, twin de store sin Path A Hermes, fallo del gate max+med+frac≥0.9.
2. **Producción canónica:** `q5b_last.joblib` + `q5b_calibration.json` + `live_entry_config.json` (thr **0.99**, Path A Pump MC band, scale OFF). Integridad: **md5** `4df6d5a8dff6bf66528d4ee4cf6641b2` (= cita BOSS) · **sha256** `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` (mismo fichero).
3. **Receta:** un solo SoT — `FEATURE_SETS['+q5b']` 51 · Imputer→HistGB · USD Path A · label `hit_10x_30d` · anti-LA · export `q5b_path_a_candidate_*` never overwrite without Sinck+GO. Docs path-a-pump / plan-refit = históricos.
4. **GO:** lift journal **max + med + frac≥0.9** vs `q5b_last` (mismo panel) + documentar thr 0.99 + recipe_parity PASS + scale OFF + SolAuditor PASS operativo + Sinck OK.

## Pedido a SolAuditor

**GO SolAuditor** a auditar estos tres docs (quarantine inventory, recipe canonical, GO criterion) y confirmar que `q5b_last` permanece intacto (**md5** `4df6d5a8…` / **sha256** `9908b936…`, mismo archivo) y paper no apunta a `q5b_pump_*`.

## Acción operativa

Quarantine documental únicamente. Opcional futuro: mover a `data/paper_live/models/quarantine/` **solo** si Sinck lo pide y se documenta; preferencia actual = dejar in situ + este inventario.
