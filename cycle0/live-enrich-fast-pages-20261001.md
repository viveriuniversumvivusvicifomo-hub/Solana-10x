# Live enrich FAST (max pages) — 2026-10-01

**Sinck:** recovery create→T0 completo en paper llega tarde para sniping.

| Mode | `max_pages_per_mint` | Where |
|------|---------------------:|-------|
| Live paper | **5** (`DEFAULT_HELIUS_MAX_PAGES_LIVE`) | `loop.py` helius enrich |
| Offline / parity | **80** (`DEFAULT_HELIUS_MAX_PAGES_PRE_T0`) | ge10 recovery / scripts |

Trade-off: live may under-count `n_trades` on spammy mints; score latency target = **seconds**.
