# Definición formal — Momento de Captura v0

**Versión:** 0.3  
**Fecha:** 2026-09-29 (CEST)  
**Universo:** tokens SPL / Token-2022 creados en el programa Pump.fun bonding curve.  
**Prohibición dura:** ninguna feature ni score en T0 puede usar datos con timestamp > T0.

## Estado Sinck (frozen)

| Ítem | Decisión | Notas |
|------|----------|-------|
| Banda MC captura v0 | **FROZEN** `MC_lo=8000`, `MC_hi=20000` USD | Confirmado Sinck 2026-09-29 |
| Oracle SOL/USD | **FROZEN** = **Pyth** SOL/USD | Confirmado Sinck 2026-09-29; `sol_usd_source0="pyth"` |
| Mención ~40k | **No** sustituye la banda | KOTH/hipótesis (~30–35k típico); experimento aparte, fuera de T0 v0 |

---

## 1. Universo U

Un mint `m` ∈ U sii:

1. Fue creado vía instrucción `create` o `create_v2` del programa  
   `PumpProgram = 6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P`.
2. Existe PDA BondingCurve `BC(m) = PDA(["bonding-curve", m], PumpProgram)`.
3. En el primer instante observado que dispara captura, `BC(m).complete == false`  
   **y** no existe pool PumpSwap canónico migrado para `m`  
   (programa `pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA`).
4. `quote_mint` es SOL nativo o `Pubkey::default()` (Cycle 0: **solo pares SOL**; USDC/custom → diferido).

---

## 2. Oráculos y unidades

| Símbolo | Definición |
|---------|------------|
| `vs`, `vt` | `virtual_sol_reserves`, `virtual_token_reserves` (u64 on-chain) |
| `rs`, `rt` | `real_sol_reserves`, `real_token_reserves` |
| `S` | `token_total_supply` (típicamente 1e15 raw = 1e9 tokens UI @ 6 decimals) |
| `SOL_USD(t)` | precio USD de 1 SOL en tiempo `t`. Fuente **FROZEN** = **Pyth SOL/USD**. Se persiste `sol_usd_source0="pyth"` en el registro. Fallback Jupiter/Birdeye solo si Pyth no disponible → `capture_quality≤MED` y documentar; **no** cambia la definición frozen. |
| `dec` | decimals del mint (Pump: 6) |

### Precio spot bonding curve (SOL por token raw)

```
P_raw_sol(t) = vs(t) / vt(t)     # división en float64 o Decimal; documentar precisión
P_ui_sol(t)  = P_raw_sol(t) * 10^dec   # SOL por 1 token UI
```

Equiv. marginal Uniswap-v2 con reservas virtuales (mismo cociente).

### Market cap estimado (convención v0 = indexadores Pump)

```
MC_sol(t) = (vs(t) * S) / vt(t)
MC_usd(t) = MC_sol(t) * SOL_USD(t) / 1e9
```

Notas:

- `vs` y `S` en lamports / raw; el factor `1e9` convierte lamports→SOL.  
- Validar en fixtures que `MC_usd` coincide ±2% con `usd_market_cap` de frontend-api o Bitquery en el mismo slot.  
- **No** usar FDV de DexScreener como definición de T0.

### Liquidez proxy en curva

```
L_sol_real(t)  = rs(t) / 1e9
L_sol_virt(t)  = vs(t) / 1e9
progress(t)    = 1 - (rt(t) / initial_real_token_reserves)   # ∈ [0,1]
```

`initial_real_token_reserves` leído de Global (793_100_000_000_000) o del estado al create.

---

## 3. Evento de captura T0

### 3.1 Definición

Sea una serie de observaciones on-chain (o indexadas)  
`(slot_i, block_time_i, vs_i, vt_i, rs_i, rt_i, complete_i)` para mint `m`,  
ordenadas por `(slot, tx_index)`.

**T0** es el **primer** `block_time` `t*` tal que se cumplen **todas**:

| # | Condición | Parámetro v0 |
|---|-----------|--------------|
| C1 | `m ∈ U` | — |
| C2 | `complete(t*) == false` | — |
| C3 | `MC_usd(t*) ∈ [MC_lo, MC_hi]` | `MC_lo=8000`, `MC_hi=20000` |
| C4 | Continuamente tradeable ≥ N segundos | `N=30` |
| C5 | Al menos 1 trade exitoso (`buy` o `sell`) en la ventana `[t*-N, t*]` | — |
| C6 | No se había registrado captura previa para `m` | idempotencia |

### 3.2 “Continuamente tradeable” (C4) — justificación de N=30

Definición operativa:

- Existe cuenta BondingCurve con `complete=false` durante todo `[t*-N, t*]`.
- No hay gap de disponibilidad de mercado > 0 (en Pump la curva está viva desde create; el riesgo real es **creación→primer trade** o **complete flip**).
- Proxy medible: `block_time(create) ≤ t*-N` **o** (si create es reciente) la curva ha tenido ≥1 trade antes de `t*-N` y ningún `migrate`/`complete`.

**Por qué N=30s:**

- Filtra snipes de un solo bloque que cruzan 8k por un trade enorme y revierten (dump inmediato).
- Compatible con slots Solana (~400ms): ~75 slots de historia mínima.
- Suficientemente corto para no perder el rango 8k–20k en pumps verticales.
- **Abierto a A/B:** {10, 30, 60, 120} s en Cycle 1.

### 3.3 Precio y estado congelados en T0

```
P0      = P_ui_sol(t*) * SOL_USD(t*)     # USD por token UI
MC0     = MC_usd(t*)
L0_real = L_sol_real(t*)
L0_virt = L_sol_virt(t*)
slot0, sig0 = slot y firma de la tx que primero satisface C1–C6
sol_usd_source0 = "pyth"   # FROZEN; otro valor ⇒ quality≤MED + alerta
```

Todo el vector de features se calcula con datos `≤ t*` (≤ `slot0` si hay empate temporal).

---

## 4. Exclusiones

Excluir mint si en el **primer sighting** que evalúa el detector:

1. `complete == true`, o  
2. Ya migró a PumpSwap/Raydium (pool detectado / instrucción `migrate` ejecutada), o  
3. `MC_usd` ya > `MC_hi` en la primera observación disponible (**lookback incompleto** → marcar `capture_quality=LOW` o descartar según política §6), o  
4. Mint no-SOL quote (Cycle 0).

---

## 5. Política de datos futuros (anti look-ahead)

| Permitido en features | Prohibido en features |
|-----------------------|------------------------|
| Cualquier dato on-chain/indexado con `ts ≤ T0` | Precios, trades, holders, social **después** de T0 |
| Oracle SOL_USD(T0) | SOL_USD(t>T0) recalculando MC0 |
| Metadata mint inmutable ya publicada ≤ T0 | Cambios de metadata post-T0 |

Los **labels** (p.ej. max MC en [T0, T0+H], multiple ≥10x) se calculan **solo** con precios post-T0 y viven en tablas separadas; **nunca** se joinean al feature store de entrenamiento como columnas de input.

---

## 6. Calidad de captura (`capture_quality`)

| Grado | Criterio |
|-------|----------|
| HIGH | Historia continua desde create; primer cruce 8k observado; oracle SOL ok |
| MED | Historia parcial pero C3–C5 ok; oracle fallback |
| LOW | Primera vista ya dentro de banda (posible missed earlier entry); usar solo para live, **excluir de train** por defecto |
| REJECT | Violación C1–C2 o migración previa |

---

## 7. Parámetros abiertos a A/B (Cycle ≥1)

**Frozen (no A/B en v0):** `MC_lo=8000`, `MC_hi=20000`; oracle SOL/USD = **Pyth**. ~40k/KOTH no entra en T0.

| Parámetro | v0 | Candidatos |
|-----------|----|------------|
| `N` (s) | 30 | 10, 60, 120 |
| `min_unique_buyers` en [T0-N, T0] | 0 (off) | 3, 5, 10 |
| `min_real_sol` | 0 | 2, 5 SOL |
| `min_trades` en ventana | 1 | 5, 10 |
| `max_creator_holding_pct` | off | 5%, 10% |
| `require_renounced_mint_auth` | off | on |
| Banda KOTH / ~40k | **fuera de T0 v0** | solo experimento aparte; no sustituye 8k–20k |

---

## 8. Pseudocódigo reproducible

```
for each mint m created on PumpProgram:
  stream curve state after each successful buy/sell
  if complete or migrated: skip
  mc = MC_usd(state, SOL_USD(now))
  if mc < MC_lo: continue
  if mc > MC_hi:
    if never_captured(m): mark OVERSHOT; continue
  if age_tradeable(m, now) >= N and trades_in(m, now-N, now) >= 1:
    if not already_captured(m):
      emit Capture(m, T0=now, P0, MC0, L0_*, quality)
```

---

## 9. Identificador de registro

Cada captura persiste:

`capture_id = hash(mint || slot0 || sig0 || definition_version="v0.3")`

Más: snapshot hash de cuentas `BC` + Global + `SOL_USD` usados (reproducibilidad).
