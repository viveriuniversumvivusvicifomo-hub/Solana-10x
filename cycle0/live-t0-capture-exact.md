# Exact T0 capture (SolDatos) — 2026-10-01

**Product:** `cycle0/definicion-captura-v0.md` v0.3 + `src/ingestion/pump_constants.py`.  
**Code:** `src/paper_live/t0_capture.py` (`find_t0_c1_c6`, `evolve_curve_mc_series`).

## Definition (frozen)

T0 = first `block_time` `t*` with **all** of:

| # | Condition | v0 params |
|---|-----------|-----------|
| C1 | mint ∈ Pump bonding-curve universe | program `6EF8…` |
| C2 | `complete(t*) == false` | — |
| C3 | `MC_usd(t*) ∈ [8000, 20000]` | `MC_LO`/`MC_HI` |
| C4 | continuously tradeable ≥ N s | `N=30` |
| C5 | ≥1 successful trade in `[t*−N, t*]` | — |
| C6 | no prior capture for mint | journal idempotency |

### MC formula (same as train / captura)

```
MC_usd = (vs * S / vt) / 1e9 * SOL_USD(t*)
```

- `vs`,`vt` = virtual SOL/token reserves (evolve from Global initials + trade SOL legs).
- `SOL_USD(t*)` = **Pyth as-of t*** (product). Fallback Jupiter/CoinGecko ⇒ `capture_quality ≤ MED`.
- **Not** DexScreener FDV; **not** a later live oracle for historical T0.

## Before (live/replay gap)

| Mode | Behavior |
|------|----------|
| Live poll | Provisional T0 = first sighting in band (Pump frontend MC) |
| Refine | `refine_t0=True` walks trade MC path — **but** incomplete ≤T0 trades → often stays provisional (`capture_quality=LOW`) |
| Historical diag | Fixed OOS `t0_ts` with **`refine_t0=False`** (no C1–C6 refine) |

## After (alignment)

1. Enrich still starts from sighting T0 (anti look-ahead vs poll).
2. With **complete pre-T0 trades** (pagination fix) + **SOL/USD as-of T0** (oracle fix), `find_t0_c1_c6`:
   - Evolves curve from `INITIAL_VIRTUAL_*`.
   - First chronological band cross with C4/C5 → **`refined=True`**, quality HIGH if `sol_usd_source` is Pyth.
3. Features / buy60 use **`t0_use`** (refined when possible), strictly `tx_time ≤ t0_use`.
4. Historical rebuild should set `refine_t0=True` **or** pass product T0 only when OOS T0 is already C1–C6-true; do not leave refine off unless intentional freeze.

## Algorithm (code path)

```
trades ≤ sighting_t0  (Helius BC+mint, as-of SOL/USD)
series = evolve_curve_mc_series(trades, sol_usd)
for (ts, mc) in series chronological:
  if mc in [8000,20000] and tradeable≥30s and trades_in_window≥1:
    return CaptureT0(t0=ts, refined=True, quality=HIGH|MED)
else:
  return provisional sighting_t0, quality=LOW|MED
```

## Verify

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/paper_live/test_paper_live_v0.py -q -k 't0 or capture or helius_enrich_records'
```

On a mint with full create→band history: expect `t0_refined=True`, `capture_quality` HIGH/MED, `mc_usd_t0` in [8k,20k], `sol_usd_source` pyth/pyth_asof when Hermes available.

## Remaining risk

- First-sight already in band with truncated history → LOW (exclude from train by protocol).
- Frontend `usd_market_cap` may disagree ±% with reserve MC if oracle differs — prefer on-chain path for refine.

## paper_live call contract

See **`cycle0/live-parity-fixes-soldatos-20261001.md`**. SolDatos owns `src/ingestion/*` helpers; BOSS wires `paper_live` to call them (no forked enrich in SolDatos).
