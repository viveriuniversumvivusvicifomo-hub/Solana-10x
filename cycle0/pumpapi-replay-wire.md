# Wire: replay.pumpapi.io (cycle0 smoke)

## URL
`https://replay.pumpapi.io/YYYY/MM/DD/HH.jsonl.zst`

Ejemplo smoke: `2026/09/29/17` → ~630–660 MB comprimido; ~3.2M líneas JSONL.

## Disco
- Smoke **pocas horas** por pasada (esta: 4h mismo día; **no** dump de día completo).
- No descargar dumps multi-día de golpe.
- Tras parsear: se pueden borrar `.zst` nuevas si el disco aprieta; **mantener 17** y los JSON export.
- Estado 2026-09-29 21:29 Europe/Madrid: 4h `.zst` (~2.4G) + JSON; ~108G libres — se mantienen las 4.

## Schema (campos usados)
| Campo | Uso |
|-------|-----|
| `mint` | id token |
| `marketCapQuote` | MC en SOL (× SOL/USD → USD) |
| `timestamp` | ms epoch |
| `price` | p0 en T0 |
| `signature` | sig0 |
| `symbol` / `name` | meta |
| `pool` | `pump` / `pump-amm` |
| `action` | evento (no filtrado en smoke) |

Otros campos presentes (no usados en smoke): `block`, `quoteAmount`, `tokenAmount`, `poolId`, `virtualQuoteInPool`, etc.

## Oráculo SOL/USD
- Producto: Pyth (`SOL_USD_SOURCE=pyth`).
- Smoke: **snapshot único** al inicio del parse (no per-event). Caveat en meta.
- Decode: cuenta `H6ARHf6YXhGYeQfUzQNGk6rDNnLBQKrenN712K4AQJEG` vía Helius RPC (getAccountInfo; **streams OFF**).

## Definición captura (producto)
- Banda T0: MC USD ∈ **[8000, 20000]**
- Hit positivo (proxy ≥10x): MC USD ≥ **200000** en la ventana observada
- Meta cohorte (`max_mc_*`, `mc_usd_hit_observed`, `label_primary_hint`) **fuera** del feature store

## Sanity MC
- Skip si `marketCapQuote` ≤ 0 o `>` 5e8 SOL, o MC USD `>` 5e10
- Aun así p95/max de hits puede pegarse al techo → quotes ruidosas; no usar max_mc como verdad absoluta sin más horas / caps más estrictos

## Smoke 2026-09-29 hora 17 (sanidad ON) — histórico 1h
| Métrica | Valor |
|---------|-------|
| n_lines | 3_224_910 |
| n_mints | 11_575 |
| n_skip_insane_mc | 29_458 |
| **n_hit_200k_in_hour** | **2827** |
| **n_con_T0_among_hits** (t0 ≤ first_hit) | **81** |
| n_con_T0_among_hits_raw | 181 |
| n_t0_any_in_hour | 1651 |
| n_negatives_pool (t0, no hit en misma hora) | 1470 |
| SOL/USD | ~119.23 (Pyth snapshot) |

## Smoke multi-hora 2026-09-29 15+16+17+18 (sanidad ON)
Horas nuevas descargadas: **15, 16, 18** (17 ya existía; no re-descargada). HEAD 19 → 404.

| Métrica | Valor |
|---------|-------|
| hours_smoked | 2026/09/29/15, 16, 17, 18 |
| sizes (zst) | 576M / 578M / 630M / 647M |
| n_lines | 12_343_890 |
| n_mints | 29_125 |
| n_skip_insane_mc | 130_214 |
| **n_hit_200k_in_window** | **5833** |
| **n_con_T0_among_hits** (t0 ≤ first_hit) | **206** |
| n_con_T0_among_hits_raw | 464 |
| n_t0_any_in_window | 4655 |
| n_negatives_pool (t0, no hit en ventana 4h) | 4191 |
| n_negatives_exported | **100** (cap; prefer more events then later hours) |
| n_positives_exported | 100 (top max_mc; n_con_T0 total = 206) |
| SOL/USD | ~119.23378 (Pyth snapshot, same decode) |
| elapsed parse | ~306 s |

Agregación: per mint **across all hours** — max/min mc, first T0 in band, first hit 200k, n_events, pools, hours_seen.

## Artefactos (sin secrets; streams_helius OFF)
- `data/samples/pumpapi_replay_smoke_multi_h.json` — meta 4h + top 100 pos T0 + 100 neg
- `data/samples/positives_pumpapi_replay_t0.json` — slim pos (meta: hours list, n_hit_200k_in_window, n_con_T0=206)
- `data/samples/negatives_pumpapi_replay_provisional.json` — **100** neg provisional (right-censored 4h)
- `data/samples/pumpapi_replay_smoke_20260929_17.json` — histórico 1h (no sobrescrito)
- raw: `data/samples/pumpapi_replay/{15,16,17,18}.jsonl.zst`

## Caveats (obligatorio al reportar)
1. **4h ≠ 30d** — no es universo de label `hit_10x_30d`; multi-hora sigue **right-censored**
2. Negativos **right-censored** (pueden hit ≥200k después de la ventana 15–18)
3. CURRENT frontend / Bitquery / esta ventana replay **no son intercambiables**; reportar `n_hit_200k*` y `n_con_T0` por separado
4. Streams Helius **OFF**; no secrets en JSON; SOL/USD **snapshot** no per-event
5. Features: aún no → QA V2 N/A hasta feature store ≤T0
6. max_mc de hits puede pegarse al techo de sanity (quotes ruidosas)

## Siguiente
Más horas (otro día o 13–14) si hace falta ventana más larga para negativos; no forzar Bitquery mientras 429; no descargar día completo.

## Pre-T0 features (2026-09-29 night)
- Extractor: `src/ingestion/replay_pre_t0_features.py`
- Output: `data/samples/features_replay_pre_t0_cohort200.json` (200/200 with pre-T0 events; holders unavailable; streams OFF)
- Note: `cycle0/replay-pre-t0-features.md`
