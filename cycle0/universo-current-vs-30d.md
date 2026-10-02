# Universo positivos: CURRENT vs max-30d

**Fecha:** 2026-09-29 (CEST)  
**Decisión BOSS:** pivot SIN Dune (Cloudflare UI + free sin API key). Streams Helius OFF.

| Campo | CURRENT (`frontend-api-v3.pump.fun`) | Ideal max-30d (Dune — bloqueado) |
|-------|--------------------------------------|----------------------------------|
| Definición | MC **ahora** ≥ 200k USD | Algún instante en 30d con MC ≥ 200k |
| `n_hit_200k` | ≈1012 unique (snapshot) | desconocido / pendiente |
| Sesgo | Solo tokens que **siguen** ≥200k; pierde rugs/dumps que ya bajaron | Incluye hits temporales |
| Uso cycle0 | OK para cohorte provisional de positivos + T0 | Fuente de verdad pedida; no disponible free ahora |

**Reportar siempre por separado:** `n_hit_200k_current` ≠ `n_con_T0`.  
Meta cohorte (`max_mc_*`, `label_primary_hint`) fuera del feature store; QA V2 al materializar.

## Estado tras pivot (esta sesión)

- `n_hit_200k_current` = **1012** (`data/samples/pump_frontend_mc200k_current.json`)
- `n_con_T0` = **3** (sin altas nuevas: Bitquery 429; mid-caps sin cruce 8k–20k en ventana early trades)
- `n_negatives` provisional = **8** (`data/samples/negatives_mc_band_provisional.json`, quality LOW)
- Streams OFF. Dune abandonado cycle0.
