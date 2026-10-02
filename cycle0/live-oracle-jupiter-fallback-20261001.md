# Live oracle Jupiter fallback (no PYTH_API_KEY) — 2026-10-01

**Goal:** Unblock paper-live HistGB scoring when Hermes/Pyth key is unset.  
**Product:** `amount_usd = sol_amt × SOL/USD oracle` (any oracle OK per Sinck).  
**Not changed:** `APPLY_DUNE_HELIUS_USD_SCALE` stays OFF; score threshold 0.99; no retrain.

## Behavior

| Env | Scoring USD | `is_scoreable_capture` |
|-----|-------------|------------------------|
| `PYTH_API_KEY` / `HERMES_API_KEY` set | `require_pyth=True` → must be `pyth_asof` | HIGH + pyth only |
| Key unset | `require_pyth=False` → pyth if reachable, else **CG as-of → Jupiter live → ref** | HIGH or **MED** (`allow_med=True`) |

Journal stamps `sol_usd` + `sol_usd_source` (e.g. `jupiter`, `coingecko_asof`, `jupiter_live_not_asof`) on enrich features / capture.

## Code

- `src/paper_live/helius_enrich.py` — `require_pyth = bool(_optional_pyth_key())` for Path A resolve + gate (batch, T0 refine re-resolve, scoreable).
- `src/ingestion/sol_usd_oracle.py` — `resolve_sol_usd_for_scoring(require_pyth=False)` preference documented; False path uses `fetch_sol_usd_asof`.

## Verify

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python - <<'PY'
from ingestion.sol_usd_oracle import clear_sol_usd_cache, fetch_sol_usd, _optional_pyth_key
clear_sol_usd_cache()
print('key', bool(_optional_pyth_key()))
print(fetch_sol_usd(force_refresh=True))  # expect jupiter ~117 when no key
PY
PYTHONPATH=src .venv/bin/pytest -q tests/ingestion/test_soldatos_parity_hooks_20261001.py
```

## Ops

Restart paper_live after deploy; confirm journal is not 100% `skip_capture_not_scoreable` and that `histgb` scores appear (may still be &lt; 0.99).
