# Live FAST — Helius soft max_calls (2026-10-01)

## Bug
`PaperLiveRunner._get_helius_client` used `soft = max(80, pages_live×top_k×2)` ≈ **100**.
With FAST `max_pages=5`, ~15 mints exhausted the soft cap → `max_calls Helius Enhanced alcanzado — stop` after cycle 2.

This is **our** session brake, not a Helius cloud quota.

## Fix
- `DEFAULT_HELIUS_MAX_CALLS_LIVE = 100_000`
- soft = max(that, cfg.max_calls_live, pages×…)
- Restart: `--max-calls 100000` (also raises Bitquery session if ever used)

## Unchanged
- Path A Hermes, scale OFF, thr 0.99, pages live=5, poll 10s
- Offline recovery still 80 pages / separate budgets
