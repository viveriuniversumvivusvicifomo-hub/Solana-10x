# Path A Pump: curve + age_proxy overwrite patch (2026-10-02)

**Goal:** Stop Pump coin overlay from overwriting trade-derived Q5a curve features, and keep `age_proxy_s` from `q5a_agg` (t0−first_trade) instead of create→T0 `age_s`.

**Refs:** residual ranks #2/#3 in `cycle0/path-a-residual-parity-20261002.md`; feat diag `cycle0/path-a-mcband-feat-diag-20261002.md`.

## Files changed

| File | Change |
|------|--------|
| `src/paper_live/pump_enrich.py` | Guard coin overlay + `age_s→age_proxy_s` behind `if not trades`; stamp `q5a_curve_age_source`; module docstring |
| `tests/paper_live/test_path_a_pump_capture.py` | `test_pump_enrich_keeps_trade_curve_and_age_proxy_when_trades_present`; `test_pump_enrich_coin_overlay_gapfill_when_no_trades` |
| `cycle0/path-a-curve-age-patch-20261002.md` | This note |

**Not touched:** `q5b_last.joblib`, paper_live restart, Dune, Helius enrich (already trade-only for these cols).

## Before → after

| Feature | Before (live Pump enrich) | After (code; needs restart to journal) |
|---------|---------------------------|----------------------------------------|
| `progress_curve_proxy` | Always overwritten from Pump coin `real_token_reserves` when present | Kept from `q5a_agg` (net_sol_curve/85) when pre-T0 trades exist; coin overlay only if trades empty |
| `net_sol_curve` | Always overwritten from Pump coin `real_sol_reserves` | Same: trade agg wins when trades present |
| `age_proxy_s` | Always set to `age_s` (create→T0) | Kept from `q5a_agg` (t0−first_trade) when trades present; gap-fill from `age_s` only if no trades |
| `age_s` | create→T0 via `age_s_from_create` (gate) | **Unchanged** — still create→T0 for scoreable gate |
| stamp | (none) | `q5a_curve_age_source` = `q5a_trades` \| `pump_coin_gapfill` |

Matches Helius path behavior: no frontend curve overlay of train-recipe Q5a when trades produced values.

## Tests

```text
PYTHONPATH=src pytest tests/paper_live/test_path_a_pump_capture.py \
  tests/paper_live/test_creator_priors_and_threshold.py -q
→ 19 passed
```

New cases cover: trades present → trade net_sol/progress + age_proxy≠age_s; no trades → coin gap-fill + age_proxy←age_s.

## Integrity (paper not restarted)

- Paper PID **18531** left running (Path A Pump, `histgb_q5b`, thr 0.9) — **not** restarted.
- Prior stamp A already in source; running binary still old until Sinck GO restart.
- This patch is source-only; journals will keep old overlay until restart picks up new code.

## Offline journal sample (pre-restart — expected old)

8 recent `sightings.features_json` rows (2026-10-02 ~12:01–12:04 Europe/Madrid):

- `age_proxy_s == age_s` on **all 8** (age_eq=True).
- `q5a_curve_age_source` absent (`None`) — confirms daemon has not loaded this patch.
- `n_trades_pre_t0` often 100–200 with `progress_curve_proxy` med ~0.47–0.59 (coin-like), consistent with residual #2/#3.

## Next ops (not done here)

1. Sinck GO restart paper once (picks up prior stamp A **and** this curve/age patch).
2. Then rebuild / re-WF Pump-true matrix; do **not** overwrite `q5b_last` without explicit GO.
