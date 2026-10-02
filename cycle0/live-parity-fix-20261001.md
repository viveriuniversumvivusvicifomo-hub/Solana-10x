# Live↔train parity fix — 2026-10-01 (Europe/Madrid UTC+2)

**Repo:** `/workspace/solana-10x`  
**Modelo:** `data/paper_live/models/q5b_last.joblib` (`histgb_q5b` / `+q5b`)  
**Helpers canónicos (SolDatos):** `cycle0/live-parity-fixes-soldatos-20261001.md`  
**Replay:** `cycle0/artifacts/helius_parity_replay_ge10_20261001.csv`

## Veredicto

| Pregunta | Respuesta |
|----------|-----------|
| ¿Joblib / train store rotos? | **NO** (diag previo Δ≈0) |
| ¿USD necesita multiplicador 6.6×? | **NO** — `APPLY_DUNE_HELIUS_USD_SCALE` default **OFF**. Fórmula live = `sol_amt × oracle(as-of T0)` |
| ¿Rebuild Helius ≤T0 recupera snipers OOS≥0.99? | **SÍ mayoría** — **10/12 (83%)** live score ≥0.99 (antes 0/3 en robust diag) |
| ¿`FollowupTracker.poll_pump_mcs` AttributeError? | **FIXED** (método en la clase; indent bug) |

## Before → After (scores)

### Diagnóstico previo (`helius_historical_replay_robust.csv`, n=3 high)

| mint | oos | before live |
|------|-----|-------------|
| 69xneXb… | 0.9995 | **0.771** |
| BZofTtk… | 0.9998 | **0.775** |
| 4M3gYZ2… | 0.9998 | **0.630** |
| **%≥0.99** | | **0%** |

### Replay post-fix (n=12 OOS high recientes)

| mint | oos | before | **after** | buy60 live/train | trades≤T0 | mode |
|------|-----|--------|-----------|------------------|-----------|------|
| 69xneXb… | 0.9995 | 0.771 | **0.9994** | 25202/24880 | 2 | enhanced+rpc |
| BZofTtk… | 0.9998 | 0.775 | 0.731 | 10105/28770 | 1 | enhanced+rpc |
| 4M3gYZ2… | 0.9998 | 0.630 | 0.573 | 10105/346531 | 1 | enhanced only* |
| wbf55Ky… | 0.9999 | — | **0.9998** | 365414/358829 | 2 | enhanced+rpc |
| 2ahcm3v… | 0.9998 | — | **0.9998** | 425801/417125 | 2 | enhanced+rpc |
| 4X9d1Mc… | 0.9998 | — | **0.9998** | 485320/476615 | 2 | enhanced+rpc |
| G4G4cN8… | 0.9998 | — | **0.9998** | 485475/477624 | 2 | enhanced+rpc |
| 2DU2GNL… | 0.9998 | — | **0.9998** | 210880/207097 | 2 | enhanced+rpc |
| wXcbD8S… | 0.9995 | — | **0.9994** | 24251/23756 | 2 | enhanced+rpc |
| 2hCEWYZ… | 0.9954 | — | **0.9929** | 17909/25229 | 4 | enhanced+rpc |
| 6mCCo1A… | 0.9998 | — | **0.9998** | 176062/176059 | 3 | enhanced+rpc |
| 56ofoyz… | 0.9998 | — | **0.9998** | 175624/185761 | 2 | enhanced+rpc |

\*RPC window no alcanzó create en presupuesto (mint ultra-caliente post-T0).

| Umbral | Before (n=3) | **After (n=12)** |
|--------|--------------|------------------|
| ≥0.99 | **0%** | **83.3%** |
| ≥0.89 | 0% | 83.3% |
| mediana live | ~0.77 | **0.9998** |

## Causas + fixes

### 1. USD scale (NO 6.6×)

- **Train:** Dune `dex_solana.trades.amount_usd`; `max_buy_usd/max_buy_sol` mediana ≈ **103** (precio SOL real).
- **“6.6×” engañoso:** `buy_vol_usd_60s / net_sol_curve` ≈681 en snipers ≠ precio; compara ventana 60s vs net curva ~85 SOL.
- **Live:** `amount_usd = sol_amt × resolve_sol_usd(as_of=t0)` (Pyth as-of → CoinGecko as-of → Jupiter live → ref 103.11).
- Flag `APPLY_DUNE_HELIUS_USD_SCALE` / `maybe_scale_usd` **OFF** por defecto (diag only).

### 2. Helius enrich / Q5a incompleto

- **Antes:** Enhanced mint newest→oldest + `max_pages` bajo → 1 trade ≤T0.
- **SolDatos:** `fetch_pre_t0_enhanced_txs` — BC-first merge, floor create−5s, 429 keep-partial, cap 80.
- **Histórico snipers age≈0:** post-T0 spam impide llegar a create vía Enhanced; replay añade **RPC `getSignaturesForAddress` [create,t0] + parse-by-sig**.
- **Live:** T0≈now → Enhanced BC+mint basta (paper_live cableado a SolDatos).
- **PUMP_AMM** mapeado a `pumpswap` (net_sol_curve solo pumpdotfun).

### 3. T0 C1–C6

- Canonical: `ingestion.t0_capture.find_t0_c1_c6`.
- `paper_live.t0_capture` = re-export.
- Replay scorea con **t0_ts OOS fijo** (anti look-ahead); refine se reporta aparte.

### 4. Creator priors

- `paper_live.creator_priors.load_creator_prior_index` → `train_store_v1` desde `dune_q5b_features.csv` / expand_v2 (n≈79k).
- Fallback: `pump_frontend_30d`.
- Gaps journal: `creator_priors=train_store_v1 n=…`.

### 5. Q5b holders / top shares

- Proxies (`n_holders_proxy`, `top*_holder_pct_proxy`) salen del flujo neto token ≤T0.
- Con trades recuperados vía RPC window, parity mejora.
- **Residual:** si RPC/Enhanced no cubren create→T0 (p.ej. 4M3g), holders/top shares quedan sesgados; no hay API holders on-chain ≤T0 sin coste extra.

### 6. `FollowupTracker.poll_pump_mcs`

- Bug: método indentado bajo `in_capture_band` → AttributeError.
- Fix: método de instancia en `FollowupTracker` (loop.py ya lo llama).

## Código tocado (box)

| Path | Cambio |
|------|--------|
| `src/ingestion/helius_enhanced.py` | Restaurado SolDatos: `fetch_pre_t0_enhanced_txs`, `TxPageFetch`, merge/filter, 429 retry |
| `src/ingestion/sol_usd_oracle.py` | (SolDatos) `fetch_sol_usd_asof`, scale OFF |
| `src/ingestion/t0_capture.py` | (SolDatos) C1–C6 canónico |
| `src/paper_live/helius_enrich.py` | Wire a SolDatos fetch/oracle/t0; PUMP_AMM; priors train_store |
| `src/paper_live/t0_capture.py` | Re-export SolDatos |
| `src/paper_live/followup.py` | `poll_pump_mcs` en clase |
| `src/paper_live/creator_priors.py` | Índice train_store_v1 |
| `src/ingestion/helius_rpc.py` | `collect_signatures_in_window` (replay/histórico) |
| `cycle0/scripts_live_parity_replay_20261001.py` | Replay ≥10 |

**Restart live:** BOSS (no kill en este pass).

## Gaps residuales (números)

1. **BZofTtk / 4M3gYZ:** live 0.73 / 0.57 — 1 trade vs train 4 / 3 buys; buy60 ~10k vs 29k / 347k. RPC no recuperó ventana completa (4M3g: >50k sigs post-T0).
2. **Dune sol_amt inflado** en algunos snipers (max_buy_sol ≫ 85) — modelo entrenado así; live Helius es más fiel on-chain. Recalibrar HistGB en escala Helius = SolModelos (fuera de scope).
3. **Q5b holders** sin snapshot on-chain ≤T0 — residual cuando Q5a incompleto.
4. **Oracle as-of:** sin `PYTH_API_KEY` → CoinGecko/Jupiter (quality ≤ MED).

## Cómo verificar

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -c "
from ingestion.sol_usd_oracle import apply_dune_helius_usd_scale_enabled
from ingestion.helius_enhanced import fetch_pre_t0_enhanced_txs, DEFAULT_MAX_PAGES_PRE_T0
from ingestion.t0_capture import find_t0_c1_c6
from paper_live.followup import FollowupTracker
assert apply_dune_helius_usd_scale_enabled() is False
assert DEFAULT_MAX_PAGES_PRE_T0==80
assert hasattr(FollowupTracker,'poll_pump_mcs')
print('ok')
"
PYTHONPATH=src .venv/bin/python -m pytest tests/paper_live/test_paper_live_v0.py -q -k 'sol_usd or merge_tx or fetch_transactions or helius or t0'
# replay (API budget):
PYTHONUNBUFFERED=1 PYTHONPATH=src .venv/bin/python cycle0/scripts_live_parity_replay_20261001.py
```
