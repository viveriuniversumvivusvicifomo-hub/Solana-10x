# Pipeline esqueleto — Cycle 0

Flujo offline-first. Cada etapa declara **inputs**, **outputs**, **verificación**.  
Sin código que simule resultados; contratos en `src/*/`.

```
[RPC/Streams/Bitquery] → ingestion → capture → features
                                              ↘
                                         labeling → (models) → backtest
                                              ↘
                                         verification (cruzado)
```

---

## Stage 0 — Config & constants

| | |
|--|--|
| **Hace** | Carga `MC_lo/hi`, `N`, oracle source, program IDs, `definition_version` |
| **Verifica** | Schema config; constantes Pump Global alineadas a README |
| **Módulo** | `ingestion/pump_constants.py` + config YAML (Cycle 1) |

---

## Stage 1 — Ingestion

| | |
|--|--|
| **Hace** | Normaliza creates, trades buy/sell, snapshots BondingCurve, oracle SOL_USD a tablas crudas particionadas por día/slot |
| **Inputs** | Helius / Bitquery / archivos parquet de research |
| **Outputs** | `raw.creates`, `raw.trades`, `raw.curve_snapshots`, `raw.oracle_sol` |
| **Verifica** | PK únicos `(sig, ix_index)`; `program_id` filtro Pump; monotonicidad temporal por mint; V5 DRY parsers; V7 hashes |
| **No hace** | Decidir T0 ni calcular features |

---

## Stage 2 — Capture

| | |
|--|--|
| **Hace** | Aplica Momento de Captura v0; emite `CaptureEvent` inmutables |
| **Inputs** | `raw.*` + config |
| **Outputs** | `capture.events` (+ `capture.rejected` con motivo) |
| **Verifica** | **V1** completo; calidad HIGH/MED/LOW; exclusión graduados |
| **Prohibido** | Leer OHLCV futuro |

---

## Stage 3 — Features

| | |
|--|--|
| **Hace** | Materializa vector P0 en T0 (`feature-set-mvp.md`) |
| **Inputs** | `capture.events` + raw ≤ T0 |
| **Outputs** | `features.mvp` (wide table, 1 fila / capture_id) |
| **Verifica** | **V2** joins; whitelist columnas; staleness |
| **Prohibido** | Columnas post-T0; labels |

---

## Stage 4 — Labeling

| | |
|--|--|
| **Hace** | Calcula outcomes post-T0 (p.ej. `hit_10x_H`, `max_multiple_H`, `migrated_H`, `time_to_migration`) |
| **Inputs** | capturas + series de precio **estrictamente > T0** (Bitquery/Birdeye) |
| **Outputs** | `labels.v0` separada |
| **Verifica** | **V3** leakage; horizonte H documentado (propuesta H ∈ {1h, 6h, 24h, 7d}) |
| **Nota Cycle 0** | Definir schema labels; implementación mínima diferible a Cycle 1 con API keys |

---

## Stage 5 — Models (stub)

| | |
|--|--|
| **Hace** | Placeholder: interfaz `fit(X,y)` / `predict_proba` |
| **Verifica** | feature names ⊂ whitelist; **V3**; no entrenar hasta V1–V4 verdes |
| **Estado C0** | Solo contrato + docstring |

---

## Stage 6 — Backtest (stub)

| | |
|--|--|
| **Hace** | Walk-forward scoring de política “entrar en T0 si score>τ” |
| **Verifica** | **V4** splits; costos fee 1.25% curva; no look-ahead en fills (fill @ P0 o peor) |
| **Estado C0** | Contrato |

---

## Stage 7 — Verification job

| | |
|--|--|
| **Hace** | Corre checklists V1–V7 sobre artefactos del run |
| **Outputs** | `verification/report.json` pass/fail |
| **Gate** | Fallo → no publicar dataset de train |

---

## Diagrama de dependencias de verificación

```
ingestion ──V5,V7──┐
capture ────V1,V6──┼──► verification report
features ───V2,V5──┤
labels ─────V3─────┤
splits ─────V4─────┘
```

---

## Orden de implementación sugerido

1. Constantes + math MC/precio (tests unitarios)  
2. Ingestion offline desde parquet/fixtures  
3. Detector captura + golden fixtures  
4. Features P0 + auditoría temporal  
5. Schema labels + un label `hit_10x_24h`  
6. Verification CLI  
7. (Cycle 1) connectors live Helius + Bitquery
