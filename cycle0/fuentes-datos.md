# Fuentes de datos — Cycle 0 (Solana / Pump.fun captura 8k–20k MC)

**Fecha:** 2026-09-29 (CEST)  
**Objetivo:** detectar tokens en bonding curve de Pump.fun con MC estimado ∈ [8000, 20000] USD **antes** de migración a PumpSwap/Raydium.  
**Convención:** no se afirma haber llamado APIs privadas sin clave. Límites de rate no documentados → `desconocido — verificar`.

---

## 0. Hechos de protocolo (fuente primaria)

| Ítem | Valor | Fuente | Confianza |
|------|-------|--------|-----------|
| Programa Pump (bonding curve) | `6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P` | [pump-public-docs](https://github.com/pump-fun/pump-public-docs), [docs oficiales](https://pump.fun/docs/bonding-curve) | Alta |
| Programa PumpSwap (AMM post-grad) | `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA` | Bitquery / Chainstack / docs Pump | Alta |
| Global PDA | `4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf` | [PUMP_PROGRAM_README](https://raw.githubusercontent.com/pump-fun/pump-public-docs/main/docs/PUMP_PROGRAM_README.md) | Alta |
| `initial_virtual_sol_reserves` | 30_000_000_000 lamports (30 SOL) | Global on-chain | Alta |
| `initial_virtual_token_reserves` | 1_073_000_000_000_000 | Global on-chain | Alta |
| `initial_real_token_reserves` | 793_100_000_000_000 | Global on-chain | Alta |
| `token_total_supply` | 1_000_000_000_000_000 (1B × 10^6 decimals) | Global on-chain | Alta |
| Graduación (`complete=true`) | cuando `real_token_reserves == 0` (~85 SOL reales depositados) | README oficial | Alta |
| MC USD en graduación (cita histórica) | ≈ **$69k** (varía con precio SOL) | blogs 2026 + arXiv; **no** cifra fija on-chain | Media |
| Rango operativo Sinck | **$8k–$20k** en curva | requisito de producto | — |
| Mención usuario ~40k | posible confusión con “King of the Hill” (~30–35k) o MC intermedio; **no** es el umbral de graduación | Bitquery KOTH docs | Media |
| Migración desde 2025-03-20 | a **PumpSwap** (Raydium = legado) | Chainstack / Xanguard | Alta |
| Fee curva | ~1.25% total (protocolo + creator; ver fee schedule actual) | [pump.fun/docs/bonding-curve](https://pump.fun/docs/bonding-curve) | Media–Alta |
| API datos oficial Pump.fun | **No existe** | Bitquery + GitHub | Alta |
| Frontend no oficial | `frontend-api-v3.pump.fun` (p.ej. `/coins/{mint}`) | ingeniería inversa comunitaria; frágil | Baja–Media |

### Fórmula de precio / MC (convención v0)

Spot en SOL (aprox. marginal constant-product):

```
P_sol = virtual_sol_reserves / virtual_token_reserves   # ambos en unidades nativas
```

Market cap estimado (convención Pump / indexadores):

```
MC_sol = (virtual_sol_reserves * token_total_supply) / virtual_token_reserves
MC_usd = MC_sol * SOL_USD(t)
```

Donde `SOL_USD(t)` debe ser un oracle fijado en el instante de captura (ver `definicion-captura-v0.md`). Confianza fórmula: **Alta** (constante de producto + supply fijo 1B).

---

## 1. Fuentes evaluadas

### 1.1 On-chain directo (Helius RPC + cuentas BondingCurve)

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Lectura de cuenta `BondingCurve` PDA, txs `buy`/`sell`/`create`/`create_v2`/`migrate`, logs, slot/time |
| **Auth** | API key Helius |
| **Rate limits** | Free 10 RPS RPC / 2 RPS DAS; Developer 50/10; Business 200/50; Professional 500/100 ([docs](https://www.helius.dev/docs/billing/rate-limits)) |
| **Latencia / profundidad** | Tiempo real vía RPC/WS; histórico con `getTransaction` / `getTransactionsForAddress` (límites de batch documentados) |
| **Fitness 8k–20k curva** | **Excelente** — fuente de verdad de `virtual_*` / `real_*` / `complete` |
| **Coste** | Freemium → planes pagos |
| **Recomendación** | **PRIMARY** (detección de captura + estado de curva) |

### 1.2 Helius Parsed Events / Parsed Streams / Webhooks

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Instrucciones decodificadas por IDL (sustituye Enhanced Transactions en deprecación); streams WS; webhooks por dirección/tipo |
| **Auth** | API key; Parsed Events en planes pagos (beta abierta citada hasta ~2026-09-21 en marketing; verificar estado actual) |
| **Rate limits** | Ver tabla Helius; webhooks: Free 5 / Dev+ 50; 100k addresses/webhook |
| **Latencia** | Sub-segundo en streams; webhooks push |
| **Fitness** | **Alta** para ingestión de trades Pump filtrando program ID |
| **Coste** | Créditos por plan |
| **Recomendación** | **PRIMARY** (ingesta live); Enhanced Transactions = legado, no construir encima |

URLs: [Parsed Events](https://www.helius.dev/docs/parsed-events), [Parsed Data](https://www.helius.dev/parsed-data), [DAS](https://www.helius.dev/docs/das-api)

### 1.3 Helius DAS (Digital Asset Standard)

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Metadata unificada token/NFT, authorities, supply views |
| **Auth** | API key |
| **Rate limits** | Misma columna “DAS & Enhanced” (2–100 RPS según plan) |
| **Fitness** | **Media** para features de authorities/metadata en T0; no sustituye curva |
| **Recomendación** | **SECONDARY** |

### 1.4 QuickNode / Triton / otros RPC

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | RPC genérico; QuickNode marketplace tiene add-on **Pump Fun API** (quotes/swaps/instrucciones) |
| **Auth** | Endpoint + key |
| **Rate limits** | Por plan — **desconocido — verificar** en dashboard |
| **Fitness** | RPC: **PRIMARY backup**; add-on Pump: útil para ejecución, no necesariamente para dataset histórico de captura |
| **Recomendación** | RPC **SECONDARY/PRIMARY-failover**; add-on QuickNode Pump **LATER** (trading), no ciclo-0 labeling |
| **URLs** | [QuickNode Pump Fun guide](https://www.quicknode.com/guides/solana-development/tooling/solana-kit/pump-fun-api), marketplace add-on |

Triton / otros RPC staked: mismos usos que Helius RPC; sin parsers Pump nativos → **SECONDARY**.

### 1.5 Bitquery — Pump.fun API (GraphQL / WS / gRPC / Kafka)

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Crear tokens, trades, OHLCV, holders, top traders, progreso curva, filtros por **MarketCap**, streams “>10k MC”, KOTH 30–35k, migraciones PumpSwap |
| **Auth** | Access token ([account.bitquery.io](https://account.bitquery.io)); trial 7 días citado |
| **Rate limits** | Documentados: **30 / 90 / 240 req/min** (Personal / Pro / Scale); Enterprise custom ([docs](https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-API/)) |
| **Latencia / profundidad** | Realtime + `dataset: archive` (add-on); Trading cube ~30 días USD; archive para histórico largo |
| **Fitness 8k–20k** | **Excelente** — queries nativas `Supply.MarketCap` en programa Pump |
| **Coste** | Por puntos/streams; archive de pago |
| **Recomendación** | **PRIMARY** para histórico + etiquetado + candidatos MC; validar siempre vs on-chain |

### 1.6 Birdeye API

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Precio, OHLCV v3 (intervalos 1s/15s/30s), trades, liquidez |
| **Auth** | API key (`X-API-KEY`), header `x-chain: solana` |
| **Rate limits** | Documentados por endpoint: p.ej. OHLCV V3 **300 rps**, price **300 rps**, history_price **100 rps** ([api-performance](https://docs.birdeye.so/docs/api-performance)); retención 1s ≈ 2 semanas, 15s/30s ≈ 3 meses |
| **Fitness** | **Buena** para labels post-T0 y OHLCV; cobertura bonding-curve pre-grad **variable** — verificar por mint |
| **Coste** | Paquetes Standard → Enterprise |
| **Recomendación** | **SECONDARY** (OHLCV/labels); no única fuente de T0 en curva |

### 1.7 DexScreener API

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Snapshots de pares: price, MC, liquidez, volumen, txns; sin histórico OHLCV en API pública |
| **Auth** | Ninguna |
| **Rate limits** | ~**300 req/min** grupo dex; ~**60 req/min** profiles/boosts (por IP) — [docs comunitarios / dxttools](https://dxttools.trade/dexscreener/api); oficial: [docs.dexscreener.com](https://docs.dexscreener.com/api/reference) |
| **Fitness** | **Baja–Media** para captura en curva (prioriza pools DEX listados; tokens solo-curva pueden faltar o retrasarse) |
| **Recomendación** | **LATER / secondary check** post-migración; no detector primario 8k–20k |

### 1.8 Jupiter Price API v3 / Quote

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | `GET https://api.jup.ag/price/v3?ids=` hasta 50 mints; `usdPrice`, liquidez agregada, `blockId`. Quote/swap API = precios de ejecución |
| **Auth** | `x-api-key` ([portal](https://developers.jup.ag/portal)) |
| **Rate limits** | **desconocido — verificar** en portal |
| **Fitness** | **Baja** para tokens solo en curva: “Tokens without a reliable price are omitted” ([docs](https://developers.jup.ag/docs/api-reference/price)) |
| **Recomendación** | **SECONDARY** para `SOL_USD` y tokens ya en AMM; **no** para P0 de captura en curva |

### 1.9 Shyft

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | Parsing txs, wallet portfolio, algo de DeFi/pools (incl. referencias pumpFunAmm) |
| **Auth** | API key |
| **Rate limits** | **desconocido — verificar** |
| **Fitness** | Media para enriquecimiento wallet; no líder en MC-on-curve |
| **Recomendación** | **LATER** |

### 1.10 Dune Analytics (tablas Solana / pumpdotfun)

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | SQL offline: esquemas comunitarios `pumpdotfun_solana` (`pump_call_create`, `pump_call_migrate`, eventos trade); dashboards de migración |
| **Auth** | Cuenta Dune; API de pago para automatizar |
| **Rate limits / coste** | Según plan Dune — **desconocido — verificar** |
| **Latencia** | Minutos–horas; no live trading |
| **Fitness** | **Alta para research offline / validación de labels**; no captura live |
| **Recomendación** | **SECONDARY research**; **LATER** en pipeline online |

### 1.11 Metaplex Token Metadata + Token-2022

| Campo | Detalle |
|-------|---------|
| **Qué aporta** | name/symbol/uri, update authority, creators; Token-2022: transfer fee, freeze, permanent delegate, metadata pointer, etc. |
| **Auth** | Lectura on-chain / DAS / RPC |
| **Fitness** | **Alta** para features de riesgo (authorities, extensiones) en T0 |
| **URLs** | [Solana Token Extensions](https://solana.com/docs/tokens/extensions), Metaplex docs |
| **Recomendación** | **PRIMARY** (features authorities / T22) vía RPC o DAS |

Nota: Pump ha migrado creación hacia **Token-2022** (`create_v2`) según docs SDK — el detector debe aceptar ambos.

### 1.12 Pump.fun — endpoints frontend / Moralis / indexadores terceros

| Fuente | Qué | Auth | Limits | Fitness | Rec |
|--------|-----|------|--------|---------|-----|
| `frontend-api-v3.pump.fun/coins/{mint}` | Snapshot: `virtual_*`, `real_*`, `complete`, `usd_market_cap` | ninguna típica | no publicados | útil ad-hoc; **frágil** | **LATER** / smoke test, no producción |
| `@pump-fun/pump-sdk` / IDL | Instrucciones + fetch curva | — | — | **PRIMARY** para math/PDA | PRIMARY |
| Moralis Solana | OHLCV por **pair address**, precios | API key | por plan — verificar | Media post-listado | SECONDARY labels |
| QuickNode Pump add-on | Quote/swap low-latency | endpoint | verificar | ejecución | LATER trading |

### 1.13 OHLCV memecoins

| Fuente | Intervalos | Histórico | Rec |
|--------|------------|-----------|-----|
| Bitquery Trading / DEXTradeByTokens | 1s+ | archive | **PRIMARY labels** |
| Birdeye `/defi/v3/ohlcv` | 1s, 15s, 30s… | 1s≈2w; 15/30s≈3m | SECONDARY |
| GeckoTerminal | OHLCV pools | público ~10–30 rpm (cita FAQ/support CoinGecko); Pro vía CoinGecko | LATER |
| DexScreener | **sin** OHLCV histórico en API pública | — | no |

### 1.14 Wallet labeling (público)

| Fuente | Qué | Acceso | Rec |
|--------|-----|--------|-----|
| Solscan labels | etiquetas cuantitativas on-site | scraping/UI; API limitada | LATER manual |
| Nansen / Arkham | smart money / entidades | de pago, ToS | LATER (ciclo features avanzadas) |
| Listas propias (creators seriales, bots) | a construir desde Bitquery top creators + funding | on-chain | **P1** en features |
| Helius Wallet API | funding source, history | key + rate DAS | SECONDARY funding creator |

**No hay** fuente pública gratuita de calidad “smart money” comparable a Nansen para Solana en 2026 — planificar labels internas.

---

## 2. Matriz de decisión (captura 8k–20k)

| Necesidad | PRIMARY | SECONDARY | Evitar como única fuente |
|-----------|---------|-----------|---------------------------|
| Detectar MC ∈ [8k,20k] en curva | Bitquery MC filter **+** Helius/RPC estado curva | frontend-api snapshot | DexScreener, Jupiter Price |
| Precio P0 / reservas | Cuenta BondingCurve on-chain | Bitquery pool | DexScreener |
| Trades pre-T0 | Helius streams / Bitquery DEXTrades | Birdeye txs | — |
| OHLCV post-T0 (labels) | Bitquery archive / Birdeye | GeckoTerminal, Moralis | DexScreener API |
| Metadata / T22 / authorities | RPC + DAS / Metaplex | Shyft | — |
| Holders en T0 | Bitquery BalanceUpdates / RPC token accounts | — | — |
| Research offline | Dune | arXiv / dashboards | — |

---

## 3. Stack recomendado Cycle 0 → 1

1. **Helius** (RPC + Parsed Streams o webhooks al program Pump) — verdad on-chain y live.  
2. **Bitquery** Pump.fun — candidatos por MC, histórico, holders, OHLCV para labels.  
3. **Oracle SOL/USD** — **FROZEN = Pyth** (Sinck 2026-09-29); Jupiter/Birdeye solo fallback → quality≤MED.  
4. **Birdeye** — backup OHLCV labels.  
5. **DexScreener / Jupiter token price** — no gating de captura.  
6. **Dune** — validación semanal offline.

---

## 4. Discrepancia de umbrales (documentar explícitamente)

| Umbral | USD aprox. | Uso |
|--------|------------|-----|
| Rango búsqueda Sinck (Cycle 0) | **8 000 – 20 000** | Momento de Captura v0 |
| “King of the Hill” (indexadores) | ~30 000 – 35 000 | señal social; **fuera** de v0 |
| Graduación / migrate | ~**69 000** (≈85 SOL reales; **flota con SOL**) | exclusión si `complete=true` |
| Mención usuario “~40k” | no es umbral on-chain fijo | tratar como hipótesis a A/B; no usar como T0 |

---

## 5. Referencias (URLs)

- https://pump.fun/docs/bonding-curve  
- https://github.com/pump-fun/pump-public-docs  
- https://raw.githubusercontent.com/pump-fun/pump-public-docs/main/docs/PUMP_PROGRAM_README.md  
- https://www.pumpdocs.fun/  
- https://docs.bitquery.io/docs/blockchain/Solana/Pumpfun/Pump-Fun-API/  
- https://www.helius.dev/docs/billing/rate-limits  
- https://www.helius.dev/docs/parsed-events  
- https://docs.birdeye.so/docs/api-performance  
- https://docs.birdeye.so/reference/get-defi-v3-ohlcv  
- https://developers.jup.ag/docs/api-reference/price  
- https://docs.dexscreener.com/api/reference  
- https://solana.com/docs/tokens/extensions  
- https://arxiv.org/html/2602.14860v1 (estudio empírico Pump.fun; confianza media)

