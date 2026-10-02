# Path A — Pump trades feed fixed (no Helius)

**Date:** 2026-10-02 (Europe/Madrid, CEST)  
**Goal:** Populate `buy_vol_usd_60s` / Q5a from Pump frontend without Helius.

## Working endpoint

```
GET https://frontend-api-v3.pump.fun/trades/{urlencoded chainId}/{mint}?limit=&cursor=
```

- `chainId` = `solana:5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp` (URL-encoded as `solana%3A…`)
- Response: `{trades, aggregates, cursor, source}`
- Page size max ≈ **100**; paginate with **`cursor`** (`offset` is a no-op)
- Trade fields used: `blockTimeMs`, `side`, `valueUsd`, `valueNative`, `trader.address`, `baseAmount`/`quoteAmount`

## Still broken (do not use)

| URL | Status |
|-----|--------|
| `/trades/all/{mint}` | 400 `chainId must match solana:<32>` |
| `/trades/all/solana:<32>` | 400 (Nest splits on `:`) |
| `/coins/{mint}` | 404 |

## Code changes

| File | Change |
|------|--------|
| `src/ingestion/pump_frontend.py` | `fetch_trades_for_mint` → `/trades/{chainId}/{mint}` + cursor pages |
| `src/paper_live/pump_enrich.py` | Parse indexed schema; wire fetch; narrow gap string |
| `tests/paper_live/test_path_a_pump_capture.py` | `test_parse_pump_frontend_trades_indexed_schema` |
| `cycle0/artifacts/pump_trades_smoke_20261002.json` | Live smoke artifact |

**Not touched:** `q5b_last.joblib`, lite, paper_live daemon (still stopped).

## Smoke (live poll, 2026-10-02 ~08:16 CEST)

| mint (short) | MC USD | scoreable | n_trades≤T0 | buy_vol_usd_60s | buy_n_60s |
|--------------|--------|-----------|-------------|-----------------|-----------|
| `88o6Ju5L…pump` | 9017 | true | 10 | 0.00 (sells-only in 60s) | 0 |
| `9pRgJc9f…pump` | 10033 | true | 200 | **1022.98** | 25 |
| `5hpck3Fa…pump` | 15785 | true | 199 | **2070.99** | 52 |

Unit: `tests/paper_live/test_path_a_pump_capture.py` → **6 passed**.

## Score check (no daemon restart)

On the same live sample, histgb reached past `skip_missing_buy_vol` (buy_vol present) but hit **`skip_prior_not_train`** when creator is not in the Dune train cohort — orthogonal to the trades fix.

## Restart readiness

| Gate | Status |
|------|--------|
| Pump trades API | **YES** — `/trades/{chainId}/{mint}` |
| `capture_scoreable` + `buy_vol` on live poll | **YES** (2/3 mints with buy_vol>0) |
| paper_live daemon restart | **NO (left stopped)** — Sinck can restart when ready; expect some `skip_prior_not_train` on cold creators |

```bash
# when Sinck wants histgb paper again (do NOT start lite):
cd /workspace/solana-10x && set -a && source .env && set +a
export PYTHONPATH=src
.venv/bin/python -m paper_live --live --cycles 0 --feed pump --enrich-via pump \
  --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.9 --max-calls 100000
```
