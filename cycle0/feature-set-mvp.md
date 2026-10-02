# Feature set MVP — solo datos ≤ T0

**Versión:** 0.1 · **Fecha:** 2026-09-29 (CEST)  

**Oracle SOL/USD (Sinck, 2026-09-29):** FROZEN = **Pyth**. Jupiter/Birdeye solo fallback → `capture_quality` ≤ MED (dueño: SolDatos, `pump_constants`). No reimplementar el source en features/labeling (V5).

**Regla:** si el timestamp del dato es > T0 → no entra al vector. Prioridad: **P0** (obligatorio MVP), **P1** (siguiente ciclo).

Leyenda look-ahead: **L0** sin riesgo si se filtra bien · **L1** riesgo si el indexador retrasa/backfill · **L2** alto riesgo (agregados “actuales” sin ts).

---

## A. Estructura de mercado (en T0)

| Feature | Definición | Fuente | Look-ahead | Prio |
|---------|------------|--------|------------|------|
| `mc_usd_t0` | MC0 (definición captura) | BondingCurve + SOL_USD | L0 | P0 |
| `price_usd_t0` | P0 | idem | L0 | P0 |
| `mc_band_pos` | (MC0 − 8000) / (20000 − 8000) | derivado | L0 | P0 |
| `sol_usd_t0` | oracle **FROZEN Pyth** (`SOL_USD_SOURCE="pyth"`, captura v0.3) | Pyth | L0 | P0 |
| `progress_curve` | 1 − rt/rt_init | BondingCurve | L0 | P0 |
| `virtual_sol` / `real_sol` | vs, rs en SOL | BondingCurve | L0 | P0 |
| `virtual_token` / `real_token` | vt, rt | BondingCurve | L0 | P0 |
| `inv_k` | vs*vt (chequeo invariante) | derivado | L0 | P1 |

## B. Estado de curva / liquidez proxy

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `liq_real_sol` | rs/1e9 | BC | L0 | P0 |
| `liq_virt_sol` | vs/1e9 | BC | L0 | P0 |
| `liq_real_over_mc` | (rs/1e9 * SOL_USD) / MC0 | derivado | L0 | P0 |
| `complete_flag` | debe ser false | BC | L0 | P0 |
| `fee_bps_effective` | fee schedule aplicable ≤ T0 | Global / fee program | L1 | P1 |

## C. Edad

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `age_s` | T0 − t_create | create tx | L0 | P0 |
| `age_slots` | slot0 − slot_create | RPC | L0 | P0 |
| `time_since_first_trade_s` | T0 − t_first_buy | trades | L0 | P0 |
| `time_in_band_s` | tiempo continuo con MC≥8000 hasta T0 | detector | L0 | P1 |

## D. Holders / concentración (pre-grad)

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `holder_count` | # cuentas token >0 excl. curve PDA | Bitquery BalanceUpdates / RPC | L1 | P0 |
| `top1_pct` / `top5_pct` / `top10_pct` | % supply UI en top holders (excl. curve) | idem | L1 | P0 |
| `creator_holding_pct` | balance creator / supply | Bitquery + create signer | L1 | P0 |
| `curve_holding_pct` | tokens aún en curva (rt) / S | BC | L0 | P0 |
| `gini_holders` | Gini sobre top-N | derivado | L1 | P1 |

## E. Flujo temprano (ventanas que **terminan** en T0)

Ventanas sugeridas: `W ∈ {30s, 60s, 5m, 15m}` ∩ `[t_create, T0]`.

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `buy_count_W` / `sell_count_W` | # trades | Helius / Bitquery | L0 | P0 |
| `buy_vol_sol_W` / `sell_vol_sol_W` | volumen | idem | L0 | P0 |
| `unique_buyers_W` / `unique_sellers_W` | signers distintos | idem | L0 | P0 |
| `buy_sell_ratio_vol_W` | buy_vol / max(sell_vol, ε) | derivado | L0 | P0 |
| `net_flow_sol_W` | buy − sell | derivado | L0 | P0 |
| `vwap_vs_p0_W` | VWAP_W / P0 − 1 | trades ≤ T0 | L0 | P1 |
| `max_trade_sol_W` | mayor buy en W | trades | L0 | P1 |
| `trade_count_total` | desde create hasta T0 | trades | L0 | P0 |

## F. Authorities / Token-2022 / metadatos

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `mint_authority_none` | mint auth null | mint account / DAS | L0 | P0 |
| `freeze_authority_none` | freeze null | idem | L0 | P0 |
| `is_token_2022` | owner program Token-2022 | mint | L0 | P0 |
| `t22_transfer_fee` | feebps si existe | extensions | L0 | P0 |
| `t22_permanent_delegate` | bool | extensions | L0 | P0 |
| `t22_non_transferable` | bool | extensions | L0 | P1 |
| `metadata_mutable` | is_mutable | Metaplex / T22 metadata | L0 | P0 |
| `update_authority_is_creator` | bool | metadata | L0 | P1 |
| `has_social_uri` | uri http(s) presente | metadata | L0 | P1 |
| `name_symbol_len` / `spam_charset` | heurística | metadata | L0 | P1 |

## G. Creator / funding

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `creator_pubkey` | de create / BC.creator | on-chain | L0 | P0 |
| `creator_prior_mints_7d` | # creates Pump por wallet en 7d **antes** T0 | Bitquery | L1 | P0 |
| `creator_prior_graduates_30d` | graduaciones previas | Bitquery/Dune | L1 | P1 |
| `creator_funding_age_s` | edad primer funding inbound | Helius Wallet / transfers | L1 | P1 |
| `creator_funding_from_cex_like` | heurística labels propias | interno | L2 | P1 |
| `same_funding_cluster_mints` | mints con mismo funder ≤ T0 | grafo transfers | L1 | P1 |

## H. Conteos de trade / microestructura

| Feature | Definición | Fuente | LA | Prio |
|---------|------------|--------|----|------|
| `buys_per_min` | buy_count / max(age_min, ε) | trades | L0 | P0 |
| `burstiness` | var de inter-arrival ≤ T0 | trades | L0 | P1 |
| `unique_traders_total` | buyers ∪ sellers ≤ T0 | trades | L0 | P0 |
| `sniper_ratio` | fracción volumen en primeros 5s post-create | trades | L0 | P1 |

---

## Vector P0 mínimo (checklist implementación)

1. `mc_usd_t0`, `price_usd_t0`, `progress_curve`, `liq_real_sol`, `liq_virt_sol`  
2. `age_s`, `time_since_first_trade_s`  
3. `holder_count`, `top10_pct`, `creator_holding_pct`  
4. Ventana W=60s y W=5m: buy/sell count, vol SOL, unique buyers, net flow  
5. `mint_authority_none`, `freeze_authority_none`, `is_token_2022`, `t22_transfer_fee`, `metadata_mutable`  
6. `creator_prior_mints_7d`, `trade_count_total`, `unique_traders_total`

Todo lo demás P1.

---

## Fuentes por grupo (resumen)

| Grupo | PRIMARY | SECONDARY |
|-------|---------|-----------|
| Mercado / curva | Helius RPC BondingCurve | Bitquery pools |
| Flujo / trades | Helius Parsed Streams / Bitquery DEXTrades | Birdeye txs |
| Holders | Bitquery BalanceUpdates | getProgramAccounts (caro) |
| Authorities / T22 | RPC mint + DAS | Shyft |
| Creator | Bitquery Instructions create | Helius history |
| Labels (no features) | Bitquery/Birdeye OHLCV post-T0 | GeckoTerminal |

---

## Explicitamente fuera del MVP de features

- Sentimiento Twitter/Telegram en T0 (latencia/sesgo; Cycle ≥2).  
- Labels Nansen/Arkham sin licencia.  
- Cualquier ATH / “migrated” / retorno futuro.  
- Precio Jupiter del mint en curva (omisiones frecuentes).
