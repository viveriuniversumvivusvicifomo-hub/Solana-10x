# Dune wire — Cycle 0 (positivos MC≥200k / T0 8k–20k)

**Fecha:** 2026-09-29 (CEST)  
**Auth:** cuenta Dune free (UI o `DUNE_API_KEY` vía `.env`, nunca en samples)  
**Streams Helius:** OFF  
**Motivo:** Bitquery 30d → `context deadline exceeded`; list 7d con `limit=50` satura (cota inferior ≥50).

## Objetivo

1. Universo 30d Pump con **MC≥200k** sin tope 50 → reportar `n_hit_200k` completo.  
2. Por mint: reconstruir **T0** = primer trade con MC ∈ [8000, 20000] USD.  
3. Negativos: misma banda T0, **sin** hit MC≥200k (N≈3–10).  
4. Meta de cohorte (`max_mc_*`, `mc_usd_hit_observed`, `label_primary_hint`) **solo** en labels — nunca feature store. QA V2 al materializar.

## Endpoint / auth

| Modo | Uso |
|------|-----|
| UI free | Query editor → Run → Export CSV → `data/samples/` |
| API | `https://api.dune.com/api/v1/` + header `X-Dune-API-Key: <DUNE_API_KEY>` |

No escribir secretos en JSON de sample (`auth` placeholder solo).

## Schema de salida (sample)

Archivo: `data/samples/dune_positives_mc200k_30d.json`

```json
{
  "meta": {
    "source": "dune",
    "window_days": 30,
    "mc_hit": 200000,
    "mc_band_t0": [8000, 20000],
    "n_hit_200k": null,
    "n_con_T0": null,
    "n_negatives": null,
    "query_id": null,
    "definition_version": "v0.3",
    "streams_helius": "OFF",
    "secrets": false
  },
  "hit_200k": [{"mint": "...", "symbol": null, "max_mc_usd_30d": null}],
  "rows_t0": [],
  "rows_negatives": []
}
```

`rows_t0` / labels: pueden llevar `max_mc_after_t0_in_sample`, `label_primary_hint` — **fuera** del feature vector.

## SQL P0 (borrador — validar columnas en Dune)

Supply Pump canónico v0: **1e9** tokens (ajustar si `tokens_solana.fungible` da otro).

```sql
-- SolDatos cycle0: Pump trades 30d → max MC ≥ 200k
-- project filter: verificar 'pump' / 'pumpdotfun' en dex_solana.trades

WITH trades AS (
  SELECT
    COALESCE(token_bought_mint_address, token_sold_mint_address) AS mint,
    block_time,
    amount_usd,
    CASE
      WHEN token_bought_mint_address IS NOT NULL AND token_bought_amount > 0
        THEN amount_usd / token_bought_amount
      WHEN token_sold_mint_address IS NOT NULL AND token_sold_amount > 0
        THEN amount_usd / token_sold_amount
      ELSE NULL
    END AS price_usd
  FROM dex_solana.trades
  WHERE block_time >= NOW() - INTERVAL '30' DAY
    AND blockchain = 'solana'
    AND (
      project = 'pump'
      OR token_bought_mint_address LIKE '%pump'
      OR token_sold_mint_address LIKE '%pump'
    )
    AND amount_usd > 0
),
mc AS (
  SELECT
    mint,
    MAX(price_usd * 1e9) AS max_mc_usd_30d,
    MIN(block_time) AS first_trade_ts,
    MAX(block_time) AS last_trade_ts
  FROM trades
  WHERE price_usd IS NOT NULL AND IS_FINITE(price_usd)
  GROUP BY mint
)
SELECT mint, max_mc_usd_30d, first_trade_ts, last_trade_ts
FROM mc
WHERE max_mc_usd_30d >= 200000
ORDER BY max_mc_usd_30d DESC;
```

T0 (por mint, post-hit list): primer `price_usd * 1e9` ∈ [8000, 20000] ordenado por `block_time ASC`.

Negativos: sample de mints con T0 en banda y `max_mc_usd_30d < 200000` (o censurados).

## Estado

- [ ] Query ejecutada en Dune free  
- [ ] `n_hit_200k` completo  
- [ ] `n_con_T0`  
- [ ] Negativos N≈3–10  

## SQL ejecutada

**Estado 2026-09-29 ~20:55 CEST: NO ejecutada — bloqueada por login.**

- `https://dune.com/queries/new` → redirige a `https://dune.com/auth/login?next=%2Fqueries` detrás de Cloudflare Turnstile ("Verify you are human", HTTP 403).
- La query pública `https://dune.com/queries/4088817` (@whalefund, "Top pump.fun tokens by market cap") se puede ver sin login, pero **Run/Fork** → `/auth/register?...` (hace falta cuenta). Además calcula **MC actual** (último `dex_solana.price_hour` × supply de `solana_utils.latest_balances`) con `LIMIT 100`, así que no sirve para "max MC ≥200k en 30d".
- Siguiente paso: Sinck entra/crea cuenta free de Dune en el navegador del box (o pone `DUNE_API_KEY` en `.env`), y se pega la SQL de abajo en un editor nuevo → Run → Export CSV → `data/samples/dune_pump_mc200k_30d.csv`.

### Tablas/columnas reales encontradas (catálogo Dune)

- `dex_solana.trades`: `blockchain, project, version, block_month, block_date, block_time, block_slot, trade_source, token_bought_symbol, token_sold_symbol, token_pair, token_bought_amount, token_sold_amount, token_bought_amount_raw, token_sold_amount_raw, amount_usd, fee_tier, fee_usd, token_bought_mint_address, token_sold_mint_address, token_bought_vault, token_sold_vault, project_program_id, project_main_id, trader_id, tx_id, outer_instruction_index, inner_instruction_index, tx_index, _updated_at`.
  - Valores de `project` para Pump: **`'pumpdotfun'`** (bonding curve, `project_program_id = 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`) y **`'pumpswap'`** (AMM post-graduación, `project_program_id = pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`). **No** existe `'pump'` (el borrador estaba mal).
  - Los pares son casi siempre contra WSOL `So11111111111111111111111111111111111111112`.
- Usadas en 4088817: `tokens_solana.transfers` (`action = 'mint'`, `outer_executing_account = '6EF8r...'`, `token_mint_address`), `solana_utils.latest_balances` (`token_mint_address, token_balance`), `tokens_solana.fungible` (`token_mint_address, name, symbol`), `dex_solana.price_hour` (`contract_address, hour, price`).

### Fix vs borrador

El borrador dividía `amount_usd / token_bought_amount` aunque el lado comprado fuera WSOL → precio de SOL, no del token. Ahora se toma siempre el lado **no-WSOL**, y se usa **VWAP horario** (en vez de max por trade) para evitar picos por trades dust.

```sql
-- SolDatos cycle0 v0.3: Pump tokens, max MC (VWAP horario × 1e9) >= 200k USD, últimos 30d. SIN LIMIT.
WITH t AS (
  SELECT
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_bought_mint_address ELSE token_sold_mint_address END AS mint,
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_bought_amount ELSE token_sold_amount END AS tok_amt,
    amount_usd,
    block_time,
    project
  FROM dex_solana.trades
  WHERE block_time >= NOW() - INTERVAL '30' DAY
    AND blockchain = 'solana'
    AND project IN ('pumpdotfun', 'pumpswap')
    AND (token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         OR token_bought_mint_address = 'So11111111111111111111111111111111111111112')
    AND amount_usd >= 1
),
hourly AS (
  SELECT mint, date_trunc('hour', block_time) AS hr,
         SUM(amount_usd) / NULLIF(SUM(tok_amt), 0) AS vwap_usd
  FROM t
  WHERE tok_amt > 0
  GROUP BY 1, 2
),
agg AS (
  SELECT mint,
         MAX(vwap_usd * 1e9) AS max_mc_usd_30d,
         MAX_BY(hr, vwap_usd) AS hour_of_max
  FROM hourly
  WHERE IS_FINITE(vwap_usd)
  GROUP BY 1
),
stats AS (
  SELECT mint, MIN(block_time) AS first_trade_ts, MAX(block_time) AS last_trade_ts,
         COUNT(*) AS n_trades_30d, SUM(amount_usd) AS volume_usd_30d,
         MAX(CASE WHEN project = 'pumpswap' THEN 1 ELSE 0 END) AS reached_pumpswap
  FROM t GROUP BY 1
)
SELECT a.mint, a.max_mc_usd_30d, a.hour_of_max,
       s.first_trade_ts, s.last_trade_ts, s.n_trades_30d, s.volume_usd_30d, s.reached_pumpswap
FROM agg a JOIN stats s ON a.mint = s.mint
WHERE a.max_mc_usd_30d >= 200000
ORDER BY a.max_mc_usd_30d DESC;
-- n_hit_200k = COUNT(*) de este resultado (o envolver en SELECT COUNT(*) FROM (...)).
```

Notas: 30d de `pumpdotfun`+`pumpswap` es mucho volumen; en plan free puede tardar mucho/timeout o gastar créditos (4088817 tardó 17 min). Si falla, partir en 3 ventanas de 10d (`block_time` BETWEEN) y unir por `mint` con MAX. Supply 1e9 es convención v0 (Pump fija 1e9 en creación). Meta de estado: `data/samples/dune_pump_mc200k_30d_meta.json`.

## Interim (mientras Dune UI)

| Fuente | Ventana | `n_hit_200k` | Notas |
|--------|---------|--------------|-------|
| Bitquery Trading.Pairs | 7d | ≥50 (limit) | saturado; bands también ~50 |
| Bitquery 30d | 30d | — | deadline |
| `frontend-api-v3.pump.fun` | **CURRENT** | ~1000+ unique MC≥200k | **no** es max-30d; frágil; sin secrets |

Dune 30d histórico sigue siendo la fuente de verdad pedida por BOSS.
