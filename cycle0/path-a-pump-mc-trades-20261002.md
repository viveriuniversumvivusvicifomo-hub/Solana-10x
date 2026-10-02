# Path A live captura → Pump MC + T0 (+ trades when API works)

**Date:** 2026-10-02 (Europe/Madrid, CEST)  
**Sinck:** Reject Helius Enhanced trade-refine as live Path A gate. MC/T0/trades from **Pump**. Lite disabled (do not restart lite daemon).

## Binding

| Item | Decision |
|------|----------|
| Captura MC | Pump `usd_market_cap` ∈ **[8k, 20k]** at sighting |
| T0 | Pump first sighting `seen_at` (`pump_mc_band_sighting_v1`) |
| `capture_scoreable` | True when Pump MC in band + create_ts + age ≤ 1d + not graduated — **no** Helius trades / `no_trade_mc_path` |
| Trades / buy_vol / Q5a | Prefer Pump frontend trade history; **gap** if API broken |
| Helius | Optional extras (`--enrich-via helius`) — not the gate |
| Lite | **DISABLED** — out of scope |

## Code map

| Path | Change |
|------|--------|
| `src/ingestion/t0_capture.py` | `find_t0_pump_mc_sighting`, `is_scoreable_pump_capture`, `score_reject_reason_pump` |
| `src/paper_live/pump_enrich.py` | Path A enrich: Pump MC gate + Q5b + optional trades parse |
| `src/paper_live/config.py` | `DEFAULT_ENRICH_VIA="pump"`, `require_t0_refined=False` |
| `src/paper_live/loop.py` | `auto` → pump; dry/live pump enrich |
| `src/paper_live/score.py` | Pump `capture_scoreable` bypasses Helius-only refine skip |
| `scripts/start_paper_thr09.sh` | `--enrich-via pump` |
| `data/paper_live/models/live_entry_config.json` | `require_t0_refined=false`, `path_a_capture=pump_mc_band_sighting_v1` |
| `tests/paper_live/test_path_a_pump_capture.py` | New gate tests |

## Pump trades API (fixed 2026-10-02)

**Working:** `GET /trades/{urlencoded solana:5eykt4Us…}/{mint}?limit=&cursor=`  
→ populates `buy_vol_usd_60s` + Q5a via `fetch_trades_for_mint` + `parse_pump_frontend_trades`.

**Still broken:** `/trades/all/{mint|chainId}` → 400 (Nest colon / regex). Do not use.

Details + smoke: `cycle0/path-a-pump-trades-fix-20261002.md`.

## Success checks

1. Unit: Pump sighting scoreable without trades ✓  
2. Dry-run: no `skip_capture_not_scoreable` from `no_trade_mc_path` ✓ (may still `skip_missing_buy_vol`)  
3. Restart (when Sinck wants histgb paper again):

```bash
cd /workspace/solana-10x
set -a; source .env; set +a
export PYTHONPATH=src
# kill any old daemon first; do NOT start lite
.venv/bin/python -m paper_live --live --cycles 0 --feed pump --enrich-via pump \
  --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.9 --max-calls 100000
# or: scripts/start_paper_thr09.sh
```

## Follow-on

Full recalib/WF with Pump as source of truth → `cycle0/path-a-pump-recalib-wf-plan-20261002.md`.


## Dry-run evidence (2026-10-02)

1 cycle, sample `pump_frontend_mc_8k_20k_sample.json`, `--enrich-via pump`:

- 8/8 new sightings: `capture_scoreable=true`, `t0_definition=pump_mc_band_sighting_v1`
- Score (pre-trades-fix dry): `skip_missing_buy_vol` ×8 — **zero** `skip_capture_not_scoreable` / `no_trade_mc_path`
- Post-fix: live smoke has `buy_vol` (see `path-a-pump-trades-fix-20261002.md`)
- Tests: `tests/paper_live/test_path_a_pump_capture.py` + related — passing

## Recalib / WF

Plan + first offline steps: `cycle0/path-a-pump-recalib-wf-plan-20261002.md`  
Inventory artifact: `cycle0/artifacts/pump_recalib_inventory_20261002.json`  
Lite: disabled (no fix / no restart).
