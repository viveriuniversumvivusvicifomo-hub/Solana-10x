# SolDatos live↔train parity fixes — 2026-10-01

**Owner:** SolDatos (`src/ingestion/`). **paper_live scoring/enrich wiring:** BOSS (do not fork enrich here).

Detail docs: `live-usd-oracle-parity.md`, `live-helius-pre-t0-pagination.md`, `live-t0-capture-exact.md`.

## Canonical helpers (call these from paper_live)

| Concern | Module | Entry points |
|---------|--------|--------------|
| SOL/USD live + as-of T0 | `ingestion.sol_usd_oracle` | `fetch_sol_usd`, **`fetch_sol_usd_asof(ts)`**, `resolve_sol_usd(..., as_of=)`, `maybe_scale_usd` (flag **OFF**) |
| Helius ≤T0 pages | `ingestion.helius_enhanced` | `HeliusEnhanced.fetch_transactions_until`, **`fetch_pre_t0_enhanced_txs`**, `merge_tx_lists`, `filter_txs_le_t0` |
| Exact T0 C1–C6 | `ingestion.t0_capture` | **`find_t0_c1_c6`**, `evolve_curve_mc_series`, `CaptureT0` |
| Frozen constants | `ingestion.pump_constants` | `SOL_USD_SOURCE=pyth`, `MC_LO_USD`/`MC_HI_USD`, `TRADEABLE_N_S` |

### Recommended enrich sequence

```text
1. quote = resolve_sol_usd(as_of=sighting_t0)          # prefer Pyth as-of
2. txs, gaps = fetch_pre_t0_enhanced_txs(client, mint, t0=..., bonding_curve=..., create_ts=...)
3. trades = parse Enhanced → TradeLeg (≤ t0) using quote.price
4. cap = find_t0_c1_c6(trades, sighting_t0=..., sighting_mc=..., sol_usd=quote.price, sol_usd_source=quote.source)
5. features / buy60 with trades ≤ cap.t0; refine_t0=True when history allows
```

Env: `APPLY_DUNE_HELIUS_USD_SCALE` default **OFF**; `DUNE_HELIUS_USD_SCALE`≈6.6 diagnostic only. Prefer oracle + full ≤T0 recovery over multiply.

## Accidental paper_live touches (stop — BOSS owns)

Earlier SolDatos pass also edited (leave for BOSS merge/reconcile):

- `src/paper_live/helius_enrich.py` — as-of oracle, `_fetch_pre_t0_txs` (prefer switch to `fetch_pre_t0_enhanced_txs`)
- `src/paper_live/config.py` — `DEFAULT_HELIUS_MAX_PAGES_PRE_T0=80`
- `src/paper_live/loop.py`, `__main__.py` — higher Enhanced budget / max_pages
- `src/paper_live/t0_capture.py` — docstring only (canonical = `ingestion.t0_capture`)
- `tests/paper_live/test_paper_live_v0.py` — extra oracle/pagination tests

## Verify (no long Helius replay)

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -c "
from ingestion.sol_usd_oracle import fetch_sol_usd, fetch_sol_usd_asof, apply_dune_helius_usd_scale_enabled
from ingestion.helius_enhanced import fetch_pre_t0_enhanced_txs, DEFAULT_MAX_PAGES_PRE_T0
from ingestion.t0_capture import find_t0_c1_c6, CaptureT0
from ingestion.pump_constants import MC_LO_USD, SOL_USD_SOURCE
assert SOL_USD_SOURCE=='pyth' and MC_LO_USD==8000 and DEFAULT_MAX_PAGES_PRE_T0==80
assert apply_dune_helius_usd_scale_enabled() is False
print('ok', fetch_sol_usd(allow_network=False))
"
PYTHONPATH=src .venv/bin/python -m pytest tests/paper_live/test_paper_live_v0.py -q -k 'sol_usd or merge_tx or fetch_transactions or helius or t0' --tb=line
```

Historical check (when BOSS ready): rebuild 3 high mints from `cycle0/diagnostics/helius_historical_replay_robust.csv` with as-of Pyth + `fetch_pre_t0_enhanced_txs` + `refine_t0=True`.

## Remaining risks

- Dune USD inflation (~6.6×) may still need **SolModelos recalibration** on Helius-scale features.
- Hermes may 401 without `PYTH_API_KEY` → live Jupiter / as-of CoinGecko (quality ≤ MED).
- 429 partial pages can still undercount vs Dune; gaps flag `partial`.
