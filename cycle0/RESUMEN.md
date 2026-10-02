# RESUMEN ejecutivo — Cycle 0 (≈2 min)

**Qué es:** sistema cuant para detectar tokens Pump.fun **aún en bonding curve** cuando el MC estimado entra en **$8k–$20k**, con el objetivo de anticipar múltiplos ≥10x **antes** de la migración a PumpSwap (~$69k / ~85 SOL reales; la cifra USD flota con el SOL).

**Qué no es:** bot de trading listo; no hay claves API ni datos live privados en este ciclo.

---

## Decisiones tomadas

1. **Captura v0:** primer instante T0 con MC∈[8k,20k], curva `complete=false`, tradeable ≥ **30s**, ≥1 trade en la ventana; precio/reservas desde cuenta BondingCurve on-chain.  
2. **Fuente de verdad:** on-chain (Helius RPC/streams) + **Bitquery** para histórico/MC filters/holders.  
3. **No** usar DexScreener ni Jupiter Price del mint como gating de captura.  
4. **Features MVP:** solo ≤T0 — curva, edad, flujo W=60s/5m, holders, authorities/T22, creator priors.  
5. **Labels** post-T0 en tabla separada; protocolos anti look-ahead definidos.  
6. **~40k** del brief: no es umbral de graduación; KOTH suele citarse ~30–35k; graduación ~69k. Rango operativo Sinck = 8–20k.

---

## Entregables

| Archivo | Contenido |
|---------|-----------|
| `fuentes-datos.md` | Barrido de fuentes + recomendaciones |
| `definicion-captura-v0.md` | T0 formal + fórmulas + A/B params |
| `feature-set-mvp.md` | Features P0/P1 |
| `protocolos-verificacion.md` | Checklists V1–V8 |
| `pipeline-esqueleto.md` | Stages + gates |
| Scaffold `src/*` | Contratos/stubs, sin fake logic |
| `paper-live-v0.md` | Poller paper-live MC 8k–20k (default Pump discover + Helius Enhanced enrich; Bitquery optional; NO trading) |
| paper-live exact calibration (2026-10-01) | SOL/USD oracle Pyth→Jupiter; creator priors 30d paginated; T0 C1–C6 refine when MC path available |

---

## Próximo ciclo (necesita keys)

- Helius + Bitquery tokens → connectors reales + 1 semana de capturas HIGH.  
- Fijar oracle SOL y validar MC0 vs indexadores (±2%).  
- Materializar labels `hit_10x_*` y primer walk-forward basline.

---

## Preguntas abiertas (para Sinck)

1. ¿Oracle SOL preferido: Pyth, Jupiter o Birdeye?  
2. ¿Incluir ya `min_unique_buyers≥3` en v0 o dejarlo A/B?  
3. ¿Horizonte de label primario: 1h, 6h o 24h?  
4. ¿Presupuesto mensual aprox. Helius+Bitquery+Birdeye?  
5. ¿Confirmar que ~40k era KOTH/hipótesis y no sustituye 8–20k?
