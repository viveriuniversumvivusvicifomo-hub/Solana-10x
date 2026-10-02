# Path A Pump — rebuild after box wipe (2026-10-02)

**Date:** 2026-10-02 ~08:26 CEST (Europe/Madrid)  
**Trigger:** Box reset ~08:19 CEST to ~06:20 stub; Sinck: "rehace". Desktop offline — rebuild from stub + prior design (no Dune invent / no daemon restart).

## Restored / verified (already on disk post-extract)

| Piece | Status |
|-------|--------|
| Pump MC/T0 scoreable gate (`find_t0_pump_mc_sighting`, MC ∈ [8k,20k], age ≤1d, not graduated) | OK — no Helius / `no_trade_mc_path` |
| Trades `GET /trades/{urlencoded solana:5eykt4Us…}/{mint}?limit=&cursor=` | OK in `fetch_trades_for_mint` |
| Parse → `buy_vol_usd_60s` / Q5a | OK (`parse_pump_frontend_trades`) |
| Defaults: `enrich_via=pump`, `histgb_q5b`, lite **DISABLED** | OK |
| `.venv` | Recreated this session (was missing) |

## Evidence

- Unit: `tests/paper_live/test_path_a_pump_capture.py` → **6 passed**
- Live smoke (~08:26 CEST): artifact `cycle0/artifacts/pump_trades_smoke_rebuild_20261002.json`

| mint (short) | MC USD | scoreable | n_trades≤T0 | buy_vol_usd_60s | buy_n |
|--------------|--------|-----------|-------------|-----------------|-------|
| `2T6HZLQE…` | 8267 | true | 110 | **5015.67** | 63 |
| `3SPKMAEW…` | 14427 | true | 195 | **2196.07** | 43 |
| `BvsC81Qa…` | 8016 | true | 196 | **5.91** | 2 |

**SCOREABLE=3/3 · BUY_VOL_GT0=3/3**

## Restart (NOT run — Sinck approve later)

```bash
cd /workspace/solana-10x
set -a; source .env; set +a
export PYTHONPATH=src
# do NOT start lite
.venv/bin/python -m paper_live --live --cycles 0 --feed pump --enrich-via pump \
  --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.9 --max-calls 100000
# or: scripts/start_paper_thr09.sh
```

## Explicitly not done

- No Dune recalib / invent
- paper_live daemon left **stopped**
- Lite lane left disabled
