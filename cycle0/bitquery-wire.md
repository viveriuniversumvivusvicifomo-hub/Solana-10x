# Bitquery wire — Cycle 1 (histórico Pump MC 8k–20k)

**Fecha:** 2026-09-29 (CEST)  
**Owner:** SolDatos  
**Política:** plan FREE — 1ª pasada N≤50–100, ventana corta; parar en 402/429.

## Endpoint + auth

| | |
|--|--|
| **URL** | `https://streaming.bitquery.io/graphql` |
| **Header** | `Authorization: Bearer <BITQUERY_TOKEN>` |
| **Content-Type** | `application/json` |
| **Secret** | solo `.env` / env (`BITQUERY_TOKEN`) — nunca en chat ni `src/` |

Legacy documentado: `https://graphql.bitquery.io` (preferir streaming).

## Módulo

- `src/ingestion/bitquery.py` — cliente + query `Trading.Pairs` filtrado por program Pump + `Supply.MarketCap` ∈ [8000, 20000]
- CLI: `python -m ingestion.bitquery --limit 50 --hours-ago 6`
- Output: `data/samples/bitquery_pump_mc_8k_20k_sample.json` + `bitquery_call_log.json`

## Cuota

- `max_calls=1` en la 1ª pasada
- Ante 402/429 → `QuotaExceeded`, escribir `bitquery_stopped.json`, evaluar Dune/otra gratis antes de gastar

## Enrichment (labels)

- Módulo: `src/ingestion/enrich_sample.py`
- CLI: `python -m ingestion.enrich_sample --n-mints 5 --hours-ago 24`
- Output: `data/samples/bitquery_enriched_capture_sample.json`
- Campos por fila: `t0`, `p0`, `prices_after_t0`, `capture_id`, `capture_quality=LOW`
- **T0 provisional** = primer trade en ventana (no detector C1–C6 completo)

## Positivos MC≥200k (Sinck)

- Módulo: `src/ingestion/positives_high_mc.py`
- Universo: Pump `Supply.MarketCap ≥ 200000` → label PRIMARY=1 (≥10x desde banda 8–20k)
- T0: primer trade con MC≈price×supply ∈ [8000,20000]
- Output: `data/samples/positives_mc200k_t0.json` (máx 2 calls; 402/429 → Dune)
