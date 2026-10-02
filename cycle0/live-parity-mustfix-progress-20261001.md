# Live parity MUST-FIX progress — 2026-10-01

**Owner:** BOSS / paper_live wire · **Repo:** `/workspace/solana-10x`  
**Source hunt:** `cycle0/live-vs-train-mismatch-hunt-20261001.md`  
**Umbral:** **0.99** (Sinck product / `live_entry_config.json`) — **NO cambiado**.

---

## Path A hooks (SolDatos) → paper_live wire

| Hook | Module | Wired in |
|------|--------|----------|
| `resolve_sol_usd_for_scoring(..., require_pyth=True)` | `ingestion.sol_usd_oracle` | `helius_enrich.enrich_helius_for_sightings` (batch + post-refine) |
| `require_pyth_asof` | same | via `resolve_sol_usd_for_scoring` |
| `USD_RECALIB_PLAN` chosen **A** | same | stamped `feats["usd_recalib_plan"]` |
| `fetch_create_to_t0_txs` | `ingestion.helius_enhanced` | live enrich (replaces bare `fetch_pre_t0_enhanced_txs`) |
| `age_s_from_create` / `AGE_MAX_SCOREABLE_S` | `ingestion.q5b_age` | enrich overwrites Q5b age; scorer uses `filter_anomalous_age_features` |
| `is_scoreable_capture` / `score_reject_reason` | `ingestion.t0_capture` | enrich → `capture_scoreable` / `score_reject_reason`; scorer `skip_capture_not_scoreable` |

### USD Path A (not blind 6.6×)

- **Chosen:** A — live `amount_usd = sol_amt × pyth_asof(T0)` (firmas ≈ Dune `amount_usd`, med ratio ~1.017).
- **B** (rebuild train + re-fit) / **C** (documented factor) — SolModelos / last resort; `APPLY_DUNE_HELIUS_USD_SCALE` stays **OFF**.
- Scale 6.6× **rejected** as ground truth.

---

## MUST-FIX status this turn

| Item | Status | Notes |
|------|--------|-------|
| 1. Pyth as-of T0 / Path A USD | **WIRED** / **BLOCKED ops** | Code requires Pyth for scoreable live rows. **`PYTH_API_KEY` / `HERMES_API_KEY` ausente en `.env`** → `resolve_sol_usd_for_scoring` → `pyth_asof_unavailable` → **todo score skip** hasta que Sinck ponga la key. |
| 2. Creator priors Dune cohort | **WIRED** (prior turn + status) | `dune_q5b_features.csv` on disk → `dune_cohort_exact/recompute/empty`. Pump frontend only if `ALLOW_PUMP_FRONTEND_PRIORS=1`. Scorer skips non-train sources. |
| 3. Require T0 refined C1–C6 | **WIRED** | `is_scoreable_capture` refuses unrefined/LOW; `require_t0_refined` on scorer. |
| 4. age_s anomalies | **WIRED** | `age_s_from_create` + max 1d; `created_dt` handles s vs ms. |
| 5. Score threshold 0.99 | **UNCHANGED** | Default `PaperLiveConfig.score_threshold=0.99`; `live_entry_config.json` pins product; restart uses `--score-threshold 0.99`. |

---

## Code touched

- `src/paper_live/helius_enrich.py` — Path A oracle, `fetch_create_to_t0_txs`, age + scoreable gate
- `src/paper_live/score.py` — `skip_capture_not_scoreable` / age / pyth / prior gates
- `src/paper_live/loop.py` — skip mode counters
- `src/paper_live/config.py` — default threshold 0.99; parity gate flags
- `src/paper_live/t0_capture.py` — re-export scoreable helpers
- `src/ingestion/pump_frontend.py` — robust `created_dt` units
- `tests/paper_live/test_paper_live_v0.py` — EntryGate unit tests allow non-product thr

**Tests:** `tests/paper_live/test_paper_live_v0.py` + `tests/verification/test_live_parity.py` → **45 passed**.

---

## PYTH_API_KEY — OPEN (crítico)

```
PYTH_API_KEY present: False
resolve_sol_usd_for_scoring(..., require_pyth=True) → (None, "pyth_asof_unavailable")
```

Sin key Hermes, live **no** marcará `capture_scoreable=True` (Path A `require_pyth`).  
Journal seguirá enriqueciendo con fallback Jupiter/CoinGecko para auditoría, pero **HistGB no scoreará** filas live hasta:

1. Añadir `PYTH_API_KEY` o `HERMES_API_KEY` a `.env`, y  
2. Reiniciar paper_live (hecho abajo con umbral 0.99).

---

## Restart live

Comando (umbral Sinck 0.99, **sin** cambiar sweet spot):

```bash
# stop old PID; start:
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 0 \
  --poll-interval 10 --feed pump --enrich-via helius \
  --score-mode histgb_q5b --entry-rule train_quantile \
  --score-threshold 0.99 --max-calls 50000
```

Expectativa post-restart **sin** Pyth key: `skip_q5b` / `skip_capture_not_scoreable` altos; `paper=0`.  
Con Pyth key: scoreable solo si C1–C6 refined + pyth_asof + age ok + dune priors.

---

## Residual OPEN

1. Ops: provision `PYTH_API_KEY`.  
2. SolDatos verify: re-replay BZof/4M3g con `fetch_create_to_t0_txs`.  
3. Journal legacy scores pre-wire — no confiar; re-score tras Pyth.  
4. FeePayer vs Dune WSOL side / trader_id — still P1 hunt.

## Restart ejecutado

| Campo | Valor |
|-------|-------|
| Hora (CEST) | 2026-10-01 ~16:42 |
| PID nuevo | 253708 |
| Log | `data/paper_live/logs/run_pump_helius_pathA_20261001-1645.log` |
| CLI thr | `--score-threshold 0.99` |
| PYTH key | **AUSENTE** |
| Evidencia | cycle1–2: `paper=0 skip_q5b=N` (gates Path A; esperable sin Hermes) |

