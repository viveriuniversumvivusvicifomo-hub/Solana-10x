# Helius ≤T0 pagination (SolDatos) — 2026-10-01

**Scope:** Enhanced Transactions REST for hybrid enrich (Streams Helius remain OFF).

## Before

| Issue | Effect |
|-------|--------|
| `max_pages=3` (live) / `50` (replay) alone | Hot mints: newest→oldest never reaches create/T0 |
| Mint address only | Thousands of post-T0 txs before pre-T0 trades |
| 429 mid-page → exception | Caller saw **`n_txs=0`** (false empty) |
| No merge | Bonding-curve PDA underused (where Pump pre-grad lives) |

Diag replay: highs recovered **1 trade ≤T0** vs **5–7** in Dune → Q5a/buy60 collapse.

## After

| Change | Detail |
|--------|--------|
| Early-stop pagination | Continue until `blockTime < floor` **OR** create signature **OR** empty/short page — `max_pages` is a **safety cap** (default **80**) |
| BC-first merge | Fetch **bonding-curve PDA** first (few pre-grad txs), then mint; **dedupe by signature** |
| Floor | `create_ts − 5s` if known, else `t0 − 48h` |
| Anti look-ahead | Keep only `timestamp ≤ t0` before parse; parse also filters `ts ≤ t0` |
| 429 | Exponential backoff + Retry-After; **keep partial pages** (`stopped_reason=partial_429`) |
| Budget | Enhanced soft cap ≫ Bitquery `max_calls_live` (~8) — pagination is page-heavy |

## Code

- `src/ingestion/helius_enhanced.py` — `fetch_transactions_until` → `TxPageFetch`, retries, `merge_tx_lists`, `DEFAULT_MAX_PAGES_PRE_T0=80`
- `src/paper_live/helius_enrich.py` — `_fetch_pre_t0_txs` (BC + mint)
- `src/paper_live/config.py` — `DEFAULT_HELIUS_MAX_PAGES_PRE_T0`
- `src/paper_live/loop.py` / `__main__.py` — higher Enhanced call soft-cap

## Verify

Re-run historical enrich on the 3 high mints from diagnostics (`69xne…`, `BZofT…`, `4M3gY…`):

```bash
# Expect n_trades_pre_t0 closer to Dune 5–7 (not 1), gaps containing helius_bc: / helius_mint:
# and stop ∈ {floor, create_sig, short_page} rather than silent empty after 429.
PYTHONPATH=src .venv/bin/python -m pytest tests/paper_live/test_paper_live_v0.py -q -k 'helius or parse_helius'
```

Live: new sightings near create should need **few BC pages**; mint-side early-stops once oldest `< floor`.

## Remaining risk

- Free-plan Enhanced RPS / 429 still slow for multi-day-old snipers on mint address.
- If create_ts unknown and mint is weeks old, floor = t0−48h may still under-fetch early curve (quality LOW).
- Incomplete pages after 429 → still undercount vs Dune; gaps flag `partial`.

## paper_live call contract

See **`cycle0/live-parity-fixes-soldatos-20261001.md`**. SolDatos owns `src/ingestion/*` helpers; BOSS wires `paper_live` to call them (no forked enrich in SolDatos).
