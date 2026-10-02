# Live USD oracle parity (SolDatos) — 2026-10-01

**Scope:** SOL/USD for paper-live enrich + historical ≤T0 rebuild.  
**Product frozen:** `SOL_USD_SOURCE=pyth` (`src/ingestion/pump_constants.py`, captura v0.3).

## Before

| Path | Behavior |
|------|----------|
| Live enrich | `resolve_sol_usd()` → Pyth latest if reachable, else **Jupiter ~117**, else CoinGecko, else ref 103.11 |
| Historical replay | Often used **live** Jupiter price at rebuild time (not SOL/USD as-of T0) |
| Train Dune USD | Volumes look **~6–7×** vs `sol_amt × ~103` (diag: buy60/net_sol ≈681 vs ~103) |
| Scale factor | None documented; blind multiply risk |

## After

| Path | Behavior |
|------|----------|
| Helper | `ingestion.sol_usd_oracle.fetch_sol_usd` (live) + **`fetch_sol_usd_asof(ts)`** |
| As-of chain | **Pyth Hermes** `/v2/updates/price/{publish_time}` → **CoinGecko** daily `history?date=DD-MM-YYYY` → live tag `*_live_not_asof` / ref |
| Live enrich | `enrich_helius_for_sightings(..., sol_usd_as_of_t0=True)` resolves as-of sighting/refined T0 |
| Preference | Env `SOL_USD_SOURCE` (default `pyth`). HIGH quality still requires Pyth per captura protocol |
| Optional scale | **`APPLY_DUNE_HELIUS_USD_SCALE` default OFF**. Factor `DUNE_HELIUS_USD_SCALE` default **6.6** (diag 2026-10-01) |

### Why not default-ON scale?

Diagnostics (`cycle0/diagnostics/scale_isolation.csv`):

- Scaling USD alone: mean score ~0.97 (highs still fail ≥0.99)
- Incomplete ≤T0 trades (1 vs 5–7): mean ~0.725

Prefer **oracle as-of + Helius pre-T0 recovery**. Scale is an escape hatch for train↔live mapping until SolModelos recalibrates on Helius-scale features.

## Code

- `src/ingestion/sol_usd_oracle.py` — `fetch_sol_usd_asof`, `maybe_scale_usd`, `DUNE_HELIUS_USD_SCALE_FACTOR`
- `src/paper_live/helius_enrich.py` — as-of at T0; optional scale on USD legs

## Verify

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python - <<'PY'
from datetime import datetime, timezone, timedelta
from ingestion.sol_usd_oracle import clear_sol_usd_cache, fetch_sol_usd, fetch_sol_usd_asof, apply_dune_helius_usd_scale_enabled
clear_sol_usd_cache()
print('live', fetch_sol_usd(force_refresh=True))
print('asof', fetch_sol_usd_asof(datetime.now(timezone.utc)-timedelta(days=10)))
print('scale_flag', apply_dune_helius_usd_scale_enabled())  # expect False
PY
```

Historical replay on 3 high mints from `cycle0/diagnostics/helius_historical_replay_robust.csv`:
pass OOS `t0_ts` into `resolve_sol_usd(as_of=t0)` (or leave `sol_usd_as_of_t0=True` on enrich). Expect `sol_usd_source` ∈ `{pyth_asof, coingecko_asof}` when network allows — **not** bare `jupiter` for historical T0.

## Env (no secrets in docs)

| Env | Default | Meaning |
|-----|---------|---------|
| `SOL_USD_SOURCE` | `pyth` | Product preference label |
| `PYTH_API_KEY` / `HERMES_API_KEY` | unset | Hermes auth when public egress 401s |
| `APPLY_DUNE_HELIUS_USD_SCALE` | off | Multiply USD features by factor |
| `DUNE_HELIUS_USD_SCALE` | `6.6` | Factor when flag on |

## Remaining risk

Dune train USD inflation may still need **model recalibration** (SolModelos) even after Pyth as-of + full trade recovery. Do not treat 6.6× as ground truth for labels.

## paper_live call contract

See **`cycle0/live-parity-fixes-soldatos-20261001.md`**. SolDatos owns `src/ingestion/*` helpers; BOSS wires `paper_live` to call them (no forked enrich in SolDatos).

## 2026-10-01 update — Jupiter OK without Pyth key

See **`cycle0/live-oracle-jupiter-fallback-20261001.md`**. Path A enrich now sets
`require_pyth = bool(PYTH/HERMES key)` so MED+Jupiter/CG captures are scoreable when
the key is unset; with key, non-pyth is still rejected. Journal stamps `sol_usd_source`.
