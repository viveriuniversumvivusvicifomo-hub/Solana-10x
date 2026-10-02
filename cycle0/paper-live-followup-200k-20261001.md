# Paper-live follow-up: Pump sightings → MC ≥200k (2026-10-01)

**Fecha:** 2026-10-01 ~15:40 Europe/Madrid (UTC+2)  
**Fuente sightings:** `data/paper_live/paper_journal.sqlite` (`source LIKE '%pump%'` → `pump.frontend-api-v3`)  
**Umbral entrada paper (trainQ top1%):** `0.9998068281` ≈ **0.9998**  
**Max score live en cohort pump:** **0.8349** (ninguno ≥ umbral; `n_ge_thr=0`)

## Método

1. Cargar sightings pump con `score IS NOT NULL` (mint, score, mc_usd_t0, t0_ts, paper_candidate).
2. MC post-T0: **DexScreener** `GET /latest/dex/tokens/{mints}` en batches de 30 (19 batches, 0 errores 429).  
   - `followup.poll_pump_mcs` está **roto** (indentado bajo `in_capture_band`; no es método de clase usable).  
   - Pump `GET /coins/{mint}` → **404** en v3 (confirmado).  
   - Cross-check puntual: listado Pump frontend overlap ≥50k confirma el hitter `9pJWJdp…` (~459k).
3. **`max_mc_lb = max(mc_usd_t0, mc_usd_now)`** — cota inferior del pico post-T0.  
   **Limitación:** no es ATH histórico; tokens que tocaron ≥200k y ya cayeron por debajo **no** se cuentan. Peak real ≥ esta cota.

**Muestra:** cohort **completo** scored pump (**N=553**), no subsample.

## Conteos

| Métrica | N |
|--------|---|
| Scored pump | **553** |
| Con MC post (DexScreener) | **502** |
| Sin MC Dex (desaparecidos / sin pares) | 51 |
| `max_mc_lb` ≥ **200k** USD | **2** |
| `max_mc_lb` ≥ **1M** USD | **0** |
| MC actual ≥200k | 2 |
| `paper_candidate=1` en pump | 0 |
| score ≥ trainQ top1% (0.9998) | **0** |

Extras (MC actual): ≥50k = 7; ≥80k = 4; ≥100k = 3. Solo **106/502** tienen `mc_now > mc_t0` (mayoría ya por debajo de T0).

## Scores: hitters ≥200k vs no

| Grupo | n | min | median | mean | max |
|-------|---|-----|--------|------|-----|
| Todos scored pump | 553 | 0.0111 | 0.1084 | 0.1266 | **0.8349** |
| Hit ≥200k (LB) | 2 | 0.1115 | **0.1120** | 0.1120 | **0.1125** |
| No-hit (con MC) | 500 | 0.0111 | 0.1103 | 0.1274 | 0.8349 |

**Lectura:** los 2 hitters tienen score ~**0.11** (median **0.1120**), lejos del max live **0.835** y del umbral **0.9998**. El mint con max score (0.835) está ahora ~3.3k MC (dump). Scores altos en live **no** predijeron los ≥200k de este día; los ≥200k observados fueron mid-pack ~0.11.

## Hitters (≥200k LB)

- `9pJWJdpPebyANys45eetpemLJo8yTz4n5B9zbpYw9ZMr` — score **0.1115**, mc_t0=9802, mc_now=469502 (~47.9×), dex=pumpswap, t0=2026-10-01T13:15:42.767+00:00
- `BVF8qXM6wu1pGrsLd4SH3DLU62EadaKWPjVsCGRypump` — score **0.1125**, mc_t0=8393, mc_now=256715 (~30.6×), dex=pumpfun, t0=2026-10-01T11:34:58.246+00:00

## Relación score ↔ umbral

- Calibración trainQ top1%: threshold **0.999807**.
- Max score pump journal: **0.8349** ≪ umbral → **0 entradas paper** por regla A (coherente con `paper_candidate=0` en todos los pump).
- Hit-rate ≥200k en cohort con MC observada: **2/502** ≈ 0.40%.
- Entre hitters, **ninguno** habría pasado el umbral 0.9998; el scorer live no los privilegió.

## Artefactos

- `data/paper_live/pump_followup_dex_mc_20261001.json` — MC Dex por mint  
- `data/paper_live/pump_followup_200k_summary.json` — resumen numérico  
- Este informe: `cycle0/paper-live-followup-200k-20261001.md`
