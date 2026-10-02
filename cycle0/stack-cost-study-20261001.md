# Estudio de costes del stack Solana memecoin ≥10x — 2026-10-01

**Usuario:** Sinck / BOSS  
**Fecha research:** 2026-10-01 (Europe/Madrid, CEST)  
**Alcance:** Pricing público actual (páginas oficiales); donde no hay cifra pública se marca **[ESTIMATE]** o **Contact sales**.

---

## Resumen ejecutivo (ES)

Para un stack de investigación histórica (~80k+ mints, features Q5) + paper-trading live (descubrir MC 8k–20k cada ~10s), el cuello de botella **ya no es solo Bitquery 402**: **Dune Free dejó de dar créditos el 10-sep-2026** (view-only). La estrategia multi-cuenta `11×2500 ≈ 27.5k créditos/mes` está **muerta o a punto de morir**. **Dune Plus sola (25k créditos)** cubre un volumen comparable al pool free antiguo para **histórico batch**, pero **no sirve para live cada 10s** y probablemente **no basta sola** para re-ejecutar todos los pulls pesados Q4/Q5 + labels post-T0 sin overages o Enterprise.

| Escenario | $/mes (aprox.) | One-time | Recomendación |
|-----------|----------------|----------|---------------|
| **A Lean** | **~$175–450** | $0–125 (Triton deposit opcional) | Solo si aceptas gaps en wallet-intel y archive Bitquery |
| **B Serious (recomendado)** | **~$1,200–1,900** | $0–125 | Mejor ROI: Helius Business + Bitquery Pro+archive Solana + Dune Plus + Cielo/Birdeye lite |
| **C Ideal firehose** | **~$4,500–8,500+** | $0–3k setup self-host | Solo si edge de latencia/wallet graph justifica; dedicated node o LaserStream Pro |

**Recomendación clave:** Ir a **B**. Subir **Helius a Business ($499)** (LaserStream gRPC mainnet) para live; **Bitquery Pro ($99) + Solana transfers archive ($400/yr-eq)** para sustituir 402 y enriquecer; **Dune Plus anual ($349)** para histórico (no Free). Arkham/Bubblemaps solo cuando el modelo de sniper-dev demuestre lift. **No pagar Pyth Starter ($500)** solo por SOL-USD (Jupiter + CG bastan).

---

## 1. Inventario de proveedores (precios citados)

### 1.1 Helius — RPC / LaserStream / enrich live

| | |
|--|--|
| **Producto** | Solana RPC, DAS, webhooks, LaserStream WSS/gRPC, shreds |
| **Para este stack** | Live discover + enrich (balances, txs, parsed events); alternativa a Geyser hosted |
| **Free** | $0 · 1M créditos/mes · 10 RPC req/s · LaserStream WSS estándar (sin extensions) |
| **Paid** | Developer **$49** (10M cr, 50 rps) · Business **$499** (100M, 200 rps, **gRPC mainnet**) · Professional **$999** (200M, 500 rps) · Dedicated desde **$2,900/mo** · Enterprise custom |
| **Créditos** | RPC estándar 1 cr; `getProgramAccounts` / archival / DAS 10 cr; overage **$5 / 1M** |
| **Add-ons** | Shreds **$1,000/IP/mo** (Pro $800) · LaserStream data add-ons (solo Pro): 5TB **$400**, 10TB **$750**, 25TB **$1,750**, … |
| **Caveats** | Free/Dev sin gRPC mainnet; live denso → Business mínimo; shreds caros |
| **URLs** | https://www.helius.dev/pricing · https://www.helius.dev/docs/billing/plans |

### 1.2 Bitquery — GraphQL / streams / archive Solana

| | |
|--|--|
| **Producto** | GraphQL + WebSocket; DEX trades, transfers, OHLCV |
| **Para este stack** | Live trades/bonding enrich; archive para buy_vol histórico (sustituye 402) |
| **Free/trial** | 7 días trial: 1k points, streaming limitado; **sin archive** |
| **Paid (anual / mensual)** | Personal **$39 / $49** (100k pts, sin stream, **no commercial**) · Pro **$79 / $99** (1M pts, streams) · Scale **$239 / $299** (5M pts) · Enterprise flat custom |
| **Points** | ~5 pts/call; overage **$50/1M pts** mensual (**$40** anual) |
| **Solana archive add-ons** | OHLCV & price **$210/mo** (yearly eq.) / **~$300** monthly · Transfers & balances **$400/mo** yearly eq. / **~$500** monthly |
| **Caveats** | Self-serve = **realtime only** (trades ~30d, on-chain hot 4–8h) sin add-on; Personal no sirve commercial; **402 = points limit** |
| **URLs** | https://bitquery.io/pricing · https://docs.bitquery.io/docs/plans/how-billing-works/ · https://docs.bitquery.io/docs/ide/paid/ |

### 1.3 Dune Analytics — histórico SQL / features Q5 / labels post-T0

| | |
|--|--|
| **Producto** | SQL sobre ledgers Solana (Pump creates, trades, bonding, MC paths) |
| **Para este stack** | Ledger ≤T0, Q5 features, labels post-T0; **no** cadence 10s |
| **Free (post 10-sep-2026)** | **View-only** · **0 créditos mensuales** · sin ejecutar queries/API ([noticia](https://cryptobriefing.com/dune-free-plan-view-only-access/) Aug 27 2026; docs) |
| **Trial** | Cuentas nuevas: ~14 días, **2,500 créditos totales** (no mensuales) |
| **Paid** | Analyst **$75/mo** o **$65/mo** anual (4,000 cr) · Plus **$399/mo** o **$349/mo** anual (25,000 cr) · Premium legacy N/A · Enterprise custom (100k+ cr) |
| **Extra credits** | Analyst ~**$0.016–0.01875**/cr · Plus ~**$0.014/cr** (docs: per 100 cr) |
| **Export** | Free 20 cr/MB · Analyst 10 · Plus **2** cr/MB |
| **Caveats** | **Multi-free 11×2500 rota.** Créditos = compute real (queries pesadas Q4/Q5 pueden comer miles). Engine Small/Medium en planes bajos |
| **URLs** | https://dune.com/pricing · https://docs.dune.com/resources/credits-billing/how-credits-work · https://docs.dune.com/api-reference/overview/billing |

#### ¿Dune Plus sola basta vs 11×2500 free + live?

| Pregunta | Respuesta |
|----------|-----------|
| Volumen créditos | Plus **25k/mo** ≈ pool antiguo **27.5k** → **sí, orden de magnitud similar** para batch histórico |
| Histórico 80k mints Q4/Q5 | **Tal vez** si queries están muy optimizadas y se cachean resultados; **riesgo alto** de necesitar overages o Enterprise en re-runs |
| Live discover cada 10s | **NO.** Dune no es API de baja latencia; quemarías créditos y no cumples SLO |
| Conclusión | Plus **puede** reemplazar el pool free para **histórico**. **No** reemplaza Helius/Bitquery/Pump para live. Para ambos jobs a la vez → Plus + overages **o** Enterprise + live stack separado |

### 1.4 QuickNode — RPC / Solana gRPC

| | |
|--|--|
| **Para este stack** | Backup RPC / gRPC Yellowstone-compatible |
| **Free** | Trial 1 mes · 10M credits · 15 RPS (no free permanente) |
| **Paid** | Build **$49** (80M) · Accelerate **$249** (450M) · Scale **$499** (950M, **gRPC incluido**) · Business **$999** (2B) · Business+ $1,499–$2,999 · Flat Rate RPS Solana desde **~$1,199** (150 RPS) **[desde Mar 2026]** |
| **gRPC add-on** | Build/Accelerate: **+$499/mo**; Scale+ incluido |
| **Caveats** | Solana methods ~30 credits/call (más caro por call que Helius en entry) |
| **URL** | https://www.quicknode.com/pricing · https://www.quicknode.com/pricing.md |

### 1.5 Triton One — PAYG RPC + Dragon’s Mouth / Riptide gRPC

| | |
|--|--|
| **Para este stack** | Firehose gRPC de calidad trading; shreds/preconfs opcionales |
| **Entry** | Depósito mínimo **$125** (prepaid 12 meses, non-refundable) |
| **Rates** | Streaming **$0.08/GB** · RPC **$0.08/GB + $10/M calls** · DAS **+$50/M** · Shreds desde **$450/mo/IP** o PAYG |
| **Caveats** | Coste variable; bueno si tráfico controlado; sin “plan flat” simple |
| **URL** | https://www.triton.one/pricing |

### 1.6 Shyft — RPC + Yellowstone gRPC flat

| | |
|--|--|
| **Para este stack** | RPC/gRPC sin créditos (RPS-gated) |
| **Free** | $0 · 10 RPC req/s · **sin gRPC** |
| **Paid** | Build **$199** (100 rps + gRPC) · Grow **$349** (150 rps) · Accelerate **$649** (400 rps) · Dedicated desde **$1,800/mo** |
| **Caveats** | Flat = predecible; menos “parsed memecoin” que Birdeye/Bitquery |
| **URL** | https://shyft.to/solana-rpc-grpc-pricing |

### 1.7 Pyth — oráculo SOL-USD (y más)

| | |
|--|--|
| **Para este stack** | Precio SOL-USD de alta calidad (opcional si Jupiter/CG bastan) |
| **Free** | Terminal view-only · **sin API** · update 10s |
| **Paid** | Starter **$500/mo** (crypto API, ~1s) · Pro desde **$2,500/mo** |
| **Caveats** | **Caro** solo para un feed SOL; no recomendado en Lean/B |
| **URL** | https://app.pyth.com/plans · https://docs.pyth.network/price-feeds/core/api-instances-and-providers/hermes |

### 1.8 Jupiter Price API

| | |
|--|--|
| **Para este stack** | SOL/token USD prices on-chain-aware |
| **Free** | Keyless 0.5 rps · Free key **$0**, **1 rps**, créditos **ilimitados** |
| **Paid** | Developer **$25** (10 rps, 25M cr) · Launch **$100** · Pro **$500** |
| **Caveats** | Price `/price/v3` = 1 credit; Free suele bastar para oracle SOL |
| **URL** | https://developers.jup.ag/docs/portal/plans · https://developers.jup.ag/docs/portal/rate-limits |

### 1.9 CoinGecko / CoinMarketCap

| Provider | Free | Paid (mensual) | Para stack | URL |
|----------|------|----------------|------------|-----|
| **CoinGecko** | Demo: 10k calls/mo, 100/min | Basic **$35** (100k, 300/min) · Analyst **$129** (500k) · Lite **$499** (2M) · Pro **$999+** · Enterprise | Meta CEX + onchain/GeckoTerminal (Pump bonding en algunos endpoints) | https://www.coingecko.com/en/api/pricing |
| **CMC** | Basic: 15k credits, 50/min | Builder **$29** · Startup **$79** · Growth **$299** · Professional **$699** | Precio/meta CEX; DEX API en mismos planes | https://coinmarketcap.com/api/pricing/ |

### 1.10 Arkham Intelligence — wallet labels / entity graph

| | |
|--|--|
| **Para este stack** | Priors sniper/dev/insider (labels, counterparties, transfers) |
| **Trial** | Individual **100k** credits · Org **1M** |
| **Paid** | Custom usage-based · **starts at $100/mo** · PAYG / x402 también |
| **Credits** | Address lookup 1–4 · batch 250–1000 · transfers **2/row** · counterparties **50**/call |
| **Caveats** | Sales form; cobertura Solana OK pero labels memecoin uneven; caro si scrapeas mucho |
| **URL** | https://arkm.com/llms/guides/getting-access.md · https://arkm.com/llms/guides/credit-pricing.md · https://arkm.com/api |

### 1.11 Cielo Finance — wallet PnL / feed

| | |
|--|--|
| **API** | Free 5k cr (/feed only) · Builder **$89/mo** (100k, all endpoints) · Architect **$188/mo** (250k) · *−10% anual* |
| **App (track wallets)** | Free 50 wallets · Pro **~$59/mo** · Whale **~$199/mo** **[ESTIMATE app; verificar en app.cielo.finance]** |
| **Para stack** | Feed txs + PnL wallets para priors |
| **URL** | https://developer.cielo.finance/docs/getting-started |

### 1.12 Bubblemaps — holder clusters / maps

| | |
|--|--|
| **Paid** | Starter **$170/mo** (100k credits) · Standard **$850/mo** (750k) · Enterprise custom |
| **Para stack** | Clusters holders / sniper-dev visual + API scores |
| **Caveats** | Sin free API útil; caro relativo al lift |
| **URL** | https://pro.bubblemaps.io/ · https://docs.bubblemaps.io/ |

### 1.13 Birdeye — token market / OHLCV / new listings / WS

| | |
|--|--|
| **Free** | Standard · **30k CU/mo** **[confirm en dashboard; página muestra Standard free]** |
| **Paid** | Lite **$39** (2.5M CU, 15 rps) · Starter **$99** (8M) · Premium **$199** (20M, **WS**) · Business **$499** (60M) |
| **Para stack** | Enrich MC/vol/new listings; alternativa/complemento Bitquery live |
| **URL** | https://birdeye.so/data-api/pricing · https://docs.birdeye.so/docs/pricing |

### 1.14 DexScreener

| | |
|--|--|
| **API pública** | **Gratis**, sin key · pairs/tokens/search ~**300 req/min** · profiles/boosts/metas ~**60 req/min** |
| **Paid API** | Mencionada en ToS; **precio no publicado** en docs → **Contact / checkout** |
| **Caveats** | Frágil para producción 24/7; bueno como señal secundaria MC/socials |
| **URL** | https://docs.dexscreener.com/api/reference · https://docs.dexscreener.com/api/api-terms-and-conditions |

### 1.15 Pump.fun public / frontend APIs

| | |
|--|--|
| **Oficial** | **No hay API key oficial** pública; SDKs + on-chain programs |
| **Frontend** | Endpoints no documentados (`frontend-api-v3.pump.fun/...`) — creates, coins, trades |
| **Coste** | **$0** |
| **Caveats** | **Frágil**: rate limits opacos, breaking changes, ToS riesgo; OK discovery + paper, no como única fuente |
| **Refs** | Community docs / repos (p.ej. BankkRoll/pumpfun-apis); no pricing page |

### 1.16 Self-hosted Solana RPC + Geyser (Yellowstone)

| Línea | Rango $/mo | Notas |
|-------|------------|-------|
| Bare metal (EPYC, ~512GB–1TB RAM, dual NVMe) | **$1,500–2,500** | Lease |
| Bandwidth 10Gbps | **$80–250** | A menudo metered |
| Hot-standby HA | **+$1,500–2,500** | Duplica hardware |
| DevOps / on-call | **10–30 h eng/mo** | ABI Geyser por release Agave |
| **All-in self-host** | **~$3,500–5,000** | [Subglow breakdown 2026](https://subglow.io/dedicated-solana-node-cost) |
| Managed dedicated (Helius/Subglow/etc.) | **~$2,900–6,000** | Flat, menos ops |
| ERPC dedicated Geyser | **[~€1,580–2,980]** **[ESTIMATE regional]** | Ver erpc.global |

**One-time:** setup/images/snapshots **$0–500**; rack colocation HFT **mucho más**.

---

## 2. Mapeo stack → proveedores

| Need | Fuentes viables | Notas coste |
|------|-----------------|-------------|
| 1. Histórico ≤T0 (80k+ mints, Q5) | **Dune Plus/Enterprise**; Bitquery Solana archive; self-index Geyser | Dune Free muerto |
| 2. Live MC 8k–20k @10s + buy_vol/Q5 | Pump frontend + **Helius Business** (+ Birdeye/Bitquery stream) | Bottleneck actual |
| 3. Wallet graph / sniper-dev | Self-built + **Cielo** + Arkham + Bubblemaps | Empezar self+Cielo |
| 4. Meta/socials/embeddings | DexScreener, Pump, CG Demo, Twitter/X free-ish | Mayormente $0 |
| 5. Oracle SOL-USD | **Jupiter Free** + CG Demo; Pyth solo si hace falta | Evitar $500 Pyth |
| 6. Post-T0 MC labels | Dune scheduled + Helius/Birdeye polls | Misma cuenta Plus |
| 7. Own node/Geyser | Triton PAYG → dedicated → self-host | Solo escenario C |

---

## 3. Tres escenarios de presupuesto

Precios en **USD/mes**, billing mensual salvo nota “anual eq.”. Totales = rangos honestos.

### A) Lean — “arreglar live, mínimo histórico”

**Filosofía:** Aceptar que Free Dune murió → **Analyst** barato; upgrade solo live (Helius Dev o Business light); Bitquery mínimo para dejar de ver 402; resto free.

| Línea | Plan | $/mo |
|-------|------|------|
| Dune | Analyst (anual eq. $65 o mensual $75) | **65–75** |
| Helius | Developer **$49** *(si hace falta gRPC mainnet → Business $499)* | **49** (o **499**) |
| Bitquery | Pro anual **$79** *(sin archive primero)* | **79–99** |
| Jupiter | Free key | **0** |
| CoinGecko | Demo | **0** |
| DexScreener / Pump frontend | Free | **0** |
| Birdeye | Standard free / Lite $39 si hace falta | **0–39** |
| Cielo / Arkham / Bubblemaps | Skip o Cielo Free feed | **0** |
| **Total Lean** | | **~$175–250** (sin Helius Business) · **~$625–850** si Helius Business |
| **One-time** | — | **$0** |

**Gaps vs ideal:**
- Sin LaserStream gRPC robusto (si te quedas en Dev)
- Sin Bitquery Solana **archive** → histórico buy_vol sigue en Dune/self
- Sin wallet-intel comercial (Arkham/Bubblemaps)
- Analyst 4k créditos **<<** 27.5k free antiguo → histórico 80k **muy justo**; puede necesitar overages
- Pump frontend frágil
- Sin nodo propio / shreds

---

### B) Serious research + live — **RECOMENDADO**

**Filosofía:** Histórico en Dune Plus; live en Helius Business + Bitquery Pro+archive; wallet priors con Cielo (+ Arkham trial); oracles free/baratos.

| Línea | Plan | $/mo |
|-------|------|------|
| Dune | Plus **anual eq. $349** (25k cr) | **349** |
| Helius | Business | **499** |
| Bitquery | Pro **$99** + Solana transfers archive **~$400** yearly-eq (+ OHLCV **$210** opcional) | **499–709** |
| Birdeye | Starter o Premium | **99–199** |
| Cielo API | Builder | **89** |
| Arkham | Entry custom / trial → paid | **0–150** **[ESTIMATE floor $100]** |
| Jupiter | Free o Developer | **0–25** |
| CoinGecko | Basic | **35** |
| DexScreener / Pump | Free | **0** |
| Bubblemaps | Skip (eval después) | **0** |
| Pyth | Skip | **0** |
| **Total B** | | **~$1,570–2,055** (con OHLCV archive + Arkham floor) · **~$1,200–1,600** core sin OHLCV/Arkham |
| **One-time** | Triton deposit opcional si pruebas gRPC | **$0–125** |

**Core B “mínimo serio” (~$1,370):** Dune Plus $349 + Helius Business $499 + Bitquery Pro+transfers $499 + Cielo $89 + CG $35.

**Gaps vs ideal:**
- Sin Bubblemaps Standard ($850)
- Sin Arkham a escala (counterparties caros)
- Sin LaserStream data add-on / shreds / dedicated
- Sin Pyth sub-second institutional
- Dune 25k puede requerir overages en re-train full cohort
- Self-built wallet graph incompleto vs firehose labels

---

### C) Full “ideal model” — firehose + wallet intel

**Filosofía:** Latencia + cobertura máxima; duplicar RPC; intel wallets de pago; archive completo.

| Línea | Plan | $/mo |
|-------|------|------|
| Dune | Plus + overages **o** Enterprise **[ESTIMATE $800–2,000+]** | **349–2,000** |
| Helius | Professional **$999** + LaserStream 5TB **$400** **o** Dedicated **$2,900** | **1,399–2,900** |
| Alt/extra RPC | Triton PAYG **[EST. $200–500]** y/o Shyft Grow **$349** | **200–850** |
| Bitquery | Scale **$299** + Solana OHLCV+transfers **~$610** yearly-eq | **909** |
| Birdeye | Business | **499** |
| Cielo | Architect | **188** |
| Arkham | Custom mid **[EST. $300–800]** | **300–800** |
| Bubblemaps | Standard | **850** |
| Jupiter | Launch/Pro | **100–500** |
| CoinGecko | Analyst/Lite | **129–499** |
| Pyth | Starter (opcional) | **0–500** |
| Self-host Geyser (alt. a dedicated) | All-in | **3,500–5,000** *(en vez de Helius dedicated)* |
| **Total C (hosted)** | Sin self-host | **~$4,900–8,500+** |
| **Total C (self-host path)** | Self-host + APIs intel | **~$6,000–10,000+** |
| **One-time** | Node setup / deposits | **$125–3,000** |

**Gaps residuales:** ToS Pump frontend; labels memecoin incompletos en Arkham; DevOps si self-host; Enterprise Dune quote opaca.

---

## 4. Comparativa rápida A/B/C

```
$/mo ≈
A Lean ........ 175–450 (o ~650–850 si Helius Business)
B Serious ..... 1,200–2,050   ← RECOMENDADO
C Ideal ....... 4,900–8,500+ (hosted) / 6k–10k+ (self-host)
```

| Capacidad | A | B | C |
|-----------|---|---|---|
| Histórico 80k Q5 | Débil (Analyst) | OK con Plus | Fuerte |
| Live 10s MC band | Frágil | Fuerte | Firehose |
| Bitquery 402 resuelto | Parcial (Pro sin archive) | Sí | Sí + Scale |
| Wallet priors | Self only | Cielo (+ Arkham light) | Full |
| Own Geyser | No | No | Sí |

---

## 5. Respuestas explícitas

### ¿11 Dune × 2500 créditos vs Dune Plus?

1. **Pool free ~27.5k cr/mo ya no es viable** tras el cambio a Free view-only (10-sep-2026).
2. **Plus = 25k cr/mo** ≈ mismo orden de magnitud que el pool antiguo → **sustituto razonable para histórico batch**.
3. **Plus sola NO es suficiente para histórico + live**: el live debe salir de Helius/Bitquery/Pump/Birdeye.
4. Para **re-runs masivos** Q4/Q5 sobre 80k mints, presupuesta **overages Plus** (~$0.014/cr) o habla **Enterprise**; no asumas que 25k bastan cada mes.

### ¿Qué upgradear primero (orden ROI)?

1. **Helius → Business ($499)** — desbloquea gRPC mainnet / throughput live  
2. **Dune → Plus ($349 anual)** — recupera capacidad histórica perdida con Free  
3. **Bitquery → Pro + Solana transfers archive** — mata 402 + deep buy_vol  
4. **Cielo Builder ($89)** — priors wallets sin Bubblemaps aún  
5. Birdeye Premium solo si WS/new-listings aportan lift medible  
6. Arkham/Bubblemaps/Pyth/dedicated — solo con evidencia de edge  

---

## 6. Notas metodológicas / caveats

- Research con WebSearch + WebFetch a páginas oficiales el **2026-10-01**.
- Precios **anuales** mostrados como $/mo equivalent cuando la página lo hace (Bitquery, Dune, etc.).
- **[ESTIMATE]** = no hay lista pública clara (Arkham mid-tier, Enterprise Dune, self-host all-in ranges de blogs 2026).
- ToS: multi-cuenta Dune free era zona gris; ahora además **técnicamente inútil**.
- FX: todo en USD; IVA/tax local no incluido.
- Bitquery Personal **no commercial** — no usar en stack BOSS production.

---

## 7. Fuentes (checklist)

| Fuente | URL |
|--------|-----|
| Helius pricing | https://www.helius.dev/pricing |
| Bitquery pricing | https://bitquery.io/pricing |
| Dune pricing | https://dune.com/pricing |
| Dune credits docs | https://docs.dune.com/resources/credits-billing/how-credits-work |
| Dune Free→view-only news | https://cryptobriefing.com/dune-free-plan-view-only-access/ |
| QuickNode | https://www.quicknode.com/pricing.md |
| Triton | https://www.triton.one/pricing |
| Shyft | https://shyft.to/solana-rpc-grpc-pricing |
| Pyth plans | https://app.pyth.com/plans |
| Jupiter plans | https://developers.jup.ag/docs/portal/plans |
| CoinGecko | https://www.coingecko.com/en/api/pricing |
| CMC | https://coinmarketcap.com/api/pricing/ |
| Arkham access/credits | https://arkm.com/llms/guides/getting-access.md · credit-pricing.md |
| Cielo | https://developer.cielo.finance/docs/getting-started |
| Bubblemaps Pro | https://pro.bubblemaps.io/ |
| Birdeye | https://birdeye.so/data-api/pricing |
| DexScreener | https://docs.dexscreener.com/api/reference |
| Self-host cost 2026 | https://subglow.io/dedicated-solana-node-cost |

---

*Fin del informe. Generado para Sinck / BOSS — ciclo0 cost study.*
