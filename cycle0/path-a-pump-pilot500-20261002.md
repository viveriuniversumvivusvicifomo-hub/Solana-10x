STATUS: NO-GO quarantined — see cycle0/quarantine-q5b-pump-joblibs-20261002.md

# Path A — Pump pilot500 (GO-1) — 2026-10-02

**Status:** COMPLETE (NO-GO paper swap)  
**Finished:** 2026-10-02T10:38:09+02:00 (CEST)  
**Zone:** Europe/Madrid  
**Constraints:** paper_live PID untouched · 0 Dune · Lite OFF · USD scale OFF · `q5b_last` / `q5b_calibration.json` not overwritten

## T0 policy (explicit)

**`expand_t0_ts`** — filter Pump frontend trades with `ts ≤ expand t0_ts`.  
Labels (`hit_10x_30d`) are defined vs expand T0. Live captura uses `pump_mc_band_sighting_v1` (residual mismatch accepted for pilot).

## Sample rule

Frame = expand ⋈ labels with `t0_ts ≥ 2026-09-01` (fold-friendly / recent).  
Stratified by `hit_10x_30d` to preserve frame base-rate; within stratum prefer recent (70% from newest half); `random_state=42`; **n=500**.

## Overlay recipe

- **From Pump trades ≤ T0:** all Q5A cols + `buy_vol_usd_60s` (parse_pump_frontend_trades → aggregate_q5a_for_mint / buy_vol_60s)
- **From expand store:** Q5B age/name/creator priors
- Pagination: cursor newest→oldest until ≥15m pre-T0 coverage or `max_pages=12`

## Fetch final

| Metric | Value |
|--------|-------|
| n_attempted | 500 |
| n_ok | 495 |
| n_fail | 5 |
| fail_frac | 0.01 |
| http_calls | 2582 |
| n_retries_429 | 0 |
| elapsed_s | 2681.6 |
| finished_at | 2026-10-02T10:36:59+02:00 |
| dune_api_calls | **0** |

Of the 495 ok: 383 with ≥1 pre-T0 trade, 112 empty pre-T0. **64/69 positives are empty-pre-T0** under `expand_t0_ts` (T0 often precedes first Pump frontend trade) — WF therefore keeps all fetch_ok rows (dropping empties collapses label rate ~0.138→~0.010).

## Matrix

| Item | Value |
|------|-------|
| Path | `data/samples/features_pump_path_a_pilot500_20261002.csv` |
| Shape | **500 × 105** (WF uses 495 fetch_ok) |
| Overlay | `pump_trades_q5a_buy60` |
| Label | `hit_10x_30d` |
| Hit rate (sample / fetch_ok) | **0.138 / 0.137** |
| t0_policy | `expand_t0_ts` |

## WF OOS (fold 5, train_n=435, test_n=60)

| Metric | pilot500 | q5b_last on same OOS X |
|--------|----------|------------------------|
| AUC | **0.962** | 0.085 |
| AP | **0.783** | 0.083 |
| frac ≥ 0.9 | 0.117 | 0.0 |
| median | 0.0007 | 0.141 |
| max | 0.990 | 0.559 |
| base_rate | 0.117 | — |
| proposed thr top1% (train) | 0.990 | — |

Caveat: OOS AUC/AP look strong but are **not** swap evidence — empty-pre-T0 pattern + expand vs live T0 mismatch likely dominate; see live rescore.

## Live journal rescore (n=200 Path A Pump scoreable, since 2026-10-02)

| Dist | pilot500 | q5b_last |
|------|----------|----------|
| median | 0.00020 | 0.162 |
| mean | 0.00163 | 0.170 |
| max | 0.084 | 0.908 |
| frac ≥ 0.9 | **0.0** | 0.005 |
| p90 | 0.0019 | 0.281 |
| lift_max / lift_median | **−0.824 / −0.161** | — |

**No live score-mass lift** — pilot scores collapse vs production `q5b_last` on real journal Pump rows.

## Artifacts

| Item | Path |
|------|------|
| Sample | `data/samples/pump_pilot500_sample_20261002.csv` |
| Trades dir | `data/samples/pump_pilot500_trades_20261002/` |
| Checkpoint | `cycle0/artifacts/pump_pilot500_checkpoint_20261002.json` |
| Build meta | `cycle0/npz/pump_pilot500_build_meta_20261002.json` |
| Matrix | `data/samples/features_pump_path_a_pilot500_20261002.csv` |
| Joblib | `data/paper_live/models/q5b_pump_pilot500_20261002.joblib` |
| Calibration | `data/paper_live/models/q5b_pump_pilot500_20261002_calibration.json` |
| WF metrics | `cycle0/npz/q5b_pump_pilot500_20261002_wf_metrics.json` |
| Twin (untouched) | `data/paper_live/models/q5b_pump_20261002.joblib` |

## GO / NO-GO for paper swap

**NO-GO** (default; confirmed).

Reasons:
1. Live journal score mass **drops** vs `q5b_last` (max 0.08 vs 0.91; frac≥0.9 = 0).
2. Expand-T0 empty-pre-trade bias on positives undermines “Pump-true features → live captura” transfer.
3. High OOS AUC on matrix does not translate to live score lift under `pump_mc_band_sighting_v1`.

Do **not** point paper_live at `q5b_pump_pilot500_20261002.joblib` without a follow-up that closes the T0 gap and shows non-negative live lift.

## Integrity checks

| Check | Result |
|-------|--------|
| paper_live PID | **18531** still running (untouched) |
| `q5b_last.joblib` md5 | `4df6d5a8dff6bf66528d4ee4cf6641b2` (unchanged) |
| `q5b_calibration.json` md5 | `586e2af105e8b890594a4f70612915a0` (unchanged) |
| Dune API calls | 0 |
| Distinct from twin | yes (`q5b_pump_pilot500_*` ≠ `q5b_pump_20261002*`) |

## Non-actions

- Did not kill/restart paper_live
- Did not call Dune API
- Did not overwrite `q5b_last.joblib` or `q5b_calibration.json`
- Did not swap live model path
