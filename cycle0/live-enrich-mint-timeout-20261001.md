# Live enrich fail-soft mint timeout — 2026-10-01

**Sinck:** paper_live hung ~1.5h mid-cycle on Helius enrich despite FAST `max_pages=5` (cycle1 ~1h45 for 10 mints; no sightings while process "alive").

## Cause
Live still used offline-style Helius client defaults: **httpx 45s**, **up to 10×429** with sleeps up to **60s**, BC+mint pagination. One sticky mint / 429 storm stalls the whole cycle.

## Fix (Path A / thr / pages **unchanged**)
| Knob | Live FAST | Offline recovery |
|------|----------:|-----------------:|
| `DEFAULT_HELIUS_MAX_PAGES_LIVE` | **5** | 80 (`PRE_T0`) |
| `DEFAULT_HELIUS_MINT_TIMEOUT_S_LIVE` | **25s** wall / mint | n/a |
| `DEFAULT_HELIUS_HTTP_TIMEOUT_S_LIVE` | **10s** | 45s |
| `DEFAULT_HELIUS_MAX_RETRIES_429_LIVE` | **2** | 10 |
| `DEFAULT_HELIUS_MAX_BACKOFF_S_LIVE` | **5s** | 60s |

On mint timeout: gap `helius_mint_timeout>25s`, skip that mint's txs, continue other mints, finish cycle. Mid-cycle heartbeat: `[paper-live] enrich i/N mint=… elapsed=…`. Cycle line adds `wall_s=`.

## Files
- `src/paper_live/config.py` — timeout constants
- `src/ingestion/helius_enhanced.py` — `deadline_mono`, `max_backoff_s`, `HeliusDeadlineExceeded`
- `src/paper_live/helius_enrich.py` — per-mint wall + heartbeat
- `src/paper_live/loop.py` — live client FAST knobs + pass timeout

## Unchanged
Path A Hermes, scale OFF, score threshold / features, `DEFAULT_HELIUS_MAX_PAGES_LIVE=5`.
