# Protocolos de verificación — Cycle 0

**Objetivo:** detectar look-ahead, bugs de join temporal, fugas de label, código duplicado y no-reproducibilidad **antes** de entrenar.  
Cada checklist debe poder convertirse en test automatizado en `src/verification/`.

---

## V1 — Detector de captura (schema + unit)

### Schema del registro `CaptureEvent`

- [ ] Campos obligatorios: `capture_id`, `mint`, `t0_iso`, `slot0`, `sig0`, `mc0`, `p0`, `sol_usd`, `sol_usd_source`, `vs,vt,rs,rt`, `complete`, `definition_version`, `capture_quality`, `snapshot_hash`
- [ ] Tipos: timestamps timezone-aware UTC; montos Decimal o int raw + factor
- [ ] `complete == false` siempre en eventos aceptados
- [ ] `8000 ≤ mc0 ≤ 20000`
- [ ] Oracle SOL/USD **FROZEN = Pyth** (`SOL_USD_SOURCE`); `capture_quality=HIGH` exige `sol_usd_source=pyth` (fallback Jupiter/Birdeye → quality ≤ MED)
- [ ] `definition_version == "v0.3"` (FROZEN captura Sinck)

### Unit tests del detector

- [ ] **No future candles:** fixture con trades/candles post-T0; el detector **no** las lee (mock assert call args `ts<=t0`)
- [ ] Primer cruce: serie MC `[5k,7k,9k,12k]` → T0 en el tick 9k (no 12k)
- [ ] Overshoot: primera vista 25k → `OVERSHOT` / no Capture HIGH
- [ ] Graduado: `complete=true` → rechazo
- [ ] Migrado PumpSwap → rechazo
- [ ] `N=30`: tradeable 20s → no captura; 30s+ → captura
- [ ] Idempotencia: segundo pase no duplica `capture_id`
- [ ] Cambio de `SOL_USD` no reescribe capturas históricas (inmutables)

### Golden fixtures

- [ ] ≥3 mints reales históricos (documentar mint + slot0 esperado) en `tests/fixtures/captures/`
- [ ] Hash de snapshot BC coincide con fixture
- [ ] Diff MC0 vs Bitquery/frontend en mismo slot ≤ 2%

---

## V2 — Auditoría de join temporal (features)

Para cada columna del feature store:

- [ ] Existe `feature_ts` ≤ `t0` (o `slot_feature ≤ slot0`)
- [ ] Test: inyectar fila feature con `ts = t0 + 1s` → pipeline **falla** o descarta
- [ ] Test: holder_count tomado de snapshot “latest” sin ts → **rechazo** (L2)
- [ ] Join semántica: `asof_join(features, captures, direction='backward')` únicamente
- [ ] Log de auditoría: % filas donde `t0 - feature_ts > max_staleness` (alertar si > umbral)

**max_staleness v0:** 15s para curva/trades; 60s para holders indexados.

---

## V3 — Label leakage

**PRIMARY FROZEN (Sinck):** `hit_10x_30d`. Secundarias: `1h` / `6h` / `24h` / `7d`.

Labels viven en `labels` (p.ej. `max_mc_*`, `hit_10x_*`, `time_to_10x`, `migrated`).

- [ ] Tabla `labels` **sin** FK que se mergeé automáticamente en `X_train`
- [ ] Test: `assert set(feature_columns) ∩ set(label_columns) == ∅`
- [ ] Test: training dataset builder recibe solo columnas whitelisteadas P0/P1
- [ ] Labels calculadas con precios **estrictamente** `ts > t0` (ventana `(t0, t0+H]`)
- [ ] Test adversario: si se añade `max_mc_24h` al feature frame → `verification.fail_leakage`
- [ ] Serialización modelo: feature names frozen; CI falla si el modelo pide columna label-* 

---

## V4 — Walk-forward / splits

- [ ] Split por **tiempo de T0**, nunca por mint aleatorio solo
- [ ] `train_end < val_start < test_start` (timestamps)
- [ ] Embargo: gap ≥ `H_label` (= **30d** PRIMARY) entre train y val para no filtrar info de labels solapadas
- [ ] Assert: `max(train.t0) + embargo <= min(val.t0)`
- [ ] Mismos mints no cruzan splits si T0 en ambos (un mint → un T0 → un split)
- [ ] Purge: eliminar del train capturas cuyo label horizon solapa el inicio de val

---

## V5 — DRY / código duplicado

Checklist de review (PR):

- [ ] Una sola implementación de `mc_usd(vs,vt,S,sol_usd)` en `capture/math.py`
- [ ] Parsers Pump IDL no copiados en ingestion y features
- [ ] Constantes Global (reservas iniciales) en un único módulo `ingestion/pump_constants.py`
- [ ] No hay `SOL_USD` hardcodeado distinto en labeling vs capture
- [ ] Scripts notebook no reimplementan detector (llaman al mismo módulo)
- [ ] `rg` / CI: denylist de funciones duplicadas por nombre (`compute_market_cap`, `bonding_curve_price`)

---

## V6 — Golden path E2E (offline)

- [ ] Fixture tar: raw txs + account snapshots + oracle CSV
- [ ] Correr pipeline: ingestion → capture → features → labels → (no train obligatorio en C0)
- [ ] Comparar outputs con golden JSON (tolerancia numérica relativa 1e-6 precios; 1% holders si indexador)
- [ ] `snapshot_hash` del run == esperado

---

## V7 — Reproducibilidad

- [ ] `SEED` fijo para cualquier muestreo
- [ ] Manifest: hashes SHA256 de cada partición de datos leída
- [ ] `definition_version`, `feature_set_version`, `code_git_sha` en cada artefacto
- [ ] Oracle SOL series versionada (archivo inmutable por día)
- [ ] Docker/lockfile de deps (`pyproject.toml` + lock) idéntico
- [ ] Comando: `python -m verification.repro_check --run-id ...` exit 0

---

## V8 — Monitoreo live (cuando exista connector)

- [ ] Alerta si tasa de captura cae a 0 en 15 min con mercado activo
- [ ] Alerta si % `capture_quality=LOW` > 40%
- [ ] Alerta si `complete=true` aparece en stream de capturas
- [ ] Drift: distribución `mc0` vs semana previa (KS test)

---

## Mapa step → protocolo

| Paso pipeline | Protocolos |
|---------------|------------|
| Ingestion | V5, V7 |
| Capture | V1, V6 |
| Features | V2, V5 |
| Labeling | V3 |
| Models / Backtest | V3, V4, V7 |
| Verification job | V1–V8 |
