# Path A — MC-band feature diagnosis (live journal vs train) — 2026-10-02

**Status:** COMPLETE
**Finished:** 2026-10-02 ~12:00 CEST (Europe/Madrid)
**Constraints:** paper_live PID **18531** untouched · 0 Dune · Lite OFF · USD scale OFF · `q5b_last` / `q5b_calibration.json` **not** overwritten

## Context

MC-band pilot NO-GO: live journal scores collapse vs `q5b_last` on same Path A Pump rows.
Train matrix `features_pump_path_a_mcband_20261002.csv` usable **n=467** (pos=34); live scoreable **n=505** (`t0_definition=pump_mc_band_sighting_v1` ∧ `capture_scoreable` ∧ `features_json`).

## Score mass (this run)

| Dist | mcband | q5b_last |
|------|--------|----------|
| n | 505 | 505 |
| median | 0.00050 | 0.16372 |
| max | **0.1874** | **0.9080** |
| p90 | 0.00573 | 0.27852 |
| frac≥0.9 | 0.0000 | 0.0020 |

## Top 5 gaps (importance × shift)

Ranked by shift×importance among histgb imp>0.01.

| Rank | Feature | Imp | KS | mean‖z‖ | train med (p10–p90) | live med (p10–p90) | null% tr→lv | flags |
|------|---------|-----|----|---------|---------------------|--------------------|-------------|-------|
| 1 | `unique_sellers_total` | 0.338 | 0.296 | 1.05 | 4.0000 (0.0000–117.8000) | 18.0000 (2.0000–52.0000) | 0.000→0.000 | — |
| 2 | `net_sol_curve` | 0.102 | 0.322 | 0.82 | 0.9765 (-65.0009–22.5937) | 17.0355 (0.0644–27.9659) | 0.000→0.000 | ks |
| 3 | `sell_vol_usd_30s` | 0.071 | 0.296 | 1.98 | 96.9553 (0.0000–9.66e+03) | 691.7111 (16.8812–4.25e+03) | 0.000→0.000 | — |
| 4 | `sell_vol_usd_total` | 0.046 | 0.368 | 1.87 | 163.7773 (0.0000–2.19e+04) | 1.93e+03 (62.3580–5.04e+03) | 0.000→0.000 | ks |
| 5 | `age_s` | 0.022 | 0.243 | 3.76 | 27.0000 (2.0000–1.57e+03) | 40.3849 (11.4252–272.8868) | 0.000→0.000 | scale |
### Train POS vs NEG vs live (killer geometry)

The mcband HistGB puts **33.8%** importance on `unique_sellers_total`. Train **positives** are extreme outliers vs live captura:

| Feature | train POS med | train NEG med | live med | live closer | imp |
|---------|---------------|---------------|----------|-------------|-----|
| `unique_sellers_total` | 400.0000 | 3.0000 | 18.0000 | **NEG** | 0.338 |
| `net_sol_curve` | -107.8486 | 1.2273 | 17.0355 | **NEG** | 0.102 |
| `progress_curve_proxy` | 0.0000 | 0.0144 | 0.4914 | **NEG** | 0.000 |
| `sell_vol_usd_30s` | 1.22e+04 | 76.6714 | 691.7111 | **NEG** | 0.071 |
| `sell_vol_usd_total` | 2.22e+04 | 127.3834 | 1.93e+03 | **NEG** | 0.046 |
| `age_proxy_s` | 159.5000 | 17.0000 | 40.3849 | **NEG** | 0.009 |
| `age_s` | 1.01e+03 | 24.0000 | 40.3849 | **NEG** | 0.022 |
| `buy_vol_usd_60s` | 770.5408 | 531.6755 | 2.59e+03 | **POS** | 0.003 |

In-matrix memorization check: mcband scores its own train positives at median **≈0.995** (91% ≥0.9) while live max stays **0.19**.

### Drivers taxonomy

-(a) **Missing/null on live:** no material holes on scoreable slice (intentional 100% null: `creator_prior_mints_all_in_window`).
-(b) **Scale/distribution shift:** `age_proxy_s` (KS=0.31, z≈8.7), seller/sell-vol family, `progress_curve_proxy` (live med 0.49 vs train ~0.01).
-(c) **High histgb importance ∩ shifted:** `unique_sellers_total` (0.34), `net_sol_curve` (0.10), `sell_vol_usd_30s` (0.07), `sell_vol_usd_total` (0.05), `top1_buyer_vol_share` (0.04).
-(d) **Train-only / live-only columns:** ∅ — all 51 `+q5b` cols present both sides. Recipe match; values do not.

## Known code-overwrite residuals

- `age_proxy_s` == `age_s` on live: **1.000** (should be t0−first_trade from q5a_agg).
- live `progress_curve_proxy` med=0.4914 vs train med≈0.01 (Pump coin overlay).
- live `n_trades_pre_t0` med=99.0000 (frac_zero=0.000) — empty-pre-T0 fixed vs expand pilot.

## Sensitivity (leave-one / family swap → train median)

Slice: top-50 live rows by `q5b_last` score.

| Intervention | median | mean | max |
|--------------|--------|------|-----|
| baseline mcband | 0.00061 | 0.00435 | 0.1053 |
| baseline q5b_last (same slice) | 0.34704 | 0.38179 | 0.9080 |
| curve+age → train median | 0.00051 | 0.00275 | 0.0488 |
| vol-family → train median (28 cols) | 0.00076 | 0.00157 | 0.0085 |
| combo top-shifted+suspects | 0.00154 | 0.00372 | 0.0288 |
| **all features → train median** | 0.00011 | 0.00011 | **0.0001** |

Leave-one largest |Δmean|: `buy_vol_usd_30s`, `sell_vol_usd_total`, `top1_buyer_vol_share` lift modestly (new max still ≤0.26 ≪ 0.9).

## Verdict

PRIMARY BLOCKER: n/overfit + distribution (train-positive geometry ≠ live captura). mcband live max=0.1874 vs q5b_last max=0.9080 on n=505 Path A Pump scoreable rows (usable train n=467, only 34 pos). HistGB puts ~34% importance on unique_sellers_total where train POS median=400 vs NEG=3 vs live=18 (live≈NEG). Same pattern for net_sol_curve (POS −108 / NEG +1.2 / live +17) and sell_vol_usd_30s (POS ~12k / NEG ~77 / live ~692). Model memorizes the 34 train positives (in-matrix pos median score≈0.995, 91%≥0.9) but live sits in neg-like region → score mass collapse. Code overwrite confirmed: age_proxy_s==age_s on 100% of live; progress_curve_proxy live med≈0.49 vs train≈0.01 (coin overlay). Sensitivity: curve+age→train-median and vol-family swaps do NOT restore mass (slice max stays ≪0.9); all-features→train-median collapses to ~0 (median row = typical negative). Recommendation: scale-n (B) alone CANNOT help — first need (1) code patches for curve/age defs so live Q5a matches train recipe, (2) a larger Pump-true matrix whose positives look like live captura at T0 (not extreme seller/curve outliers), then re-WF. Do not swap paper to mcband.

### Recommendation

1. **Code patches first** (0 API): stop Pump coin overlay of `progress_curve_proxy` / `net_sol_curve` when trades present; stop `age_proxy_s ← age_s`.
2. **Scale-n (B) alone: NO** — current 34 positives are geometric outliers (sellers≈400, net_sol_curve≪0) that live captura never matches; more rows of the same recipe will not move live mass.
3. Rebuild a larger Pump-true matrix whose **positives resemble live MC-band T0** (seller/curve/vol in live ranges), then re-WF and re-rescore. Keep paper on `q5b_last` (NO-GO swap).

## Artifacts

- JSON: `cycle0/diagnostics/mcband_live_feat_diag_20261002.json`
- This note: `cycle0/path-a-mcband-feat-diag-20261002.md`
- Residual ranking: `cycle0/path-a-residual-parity-20261002.md`
- MC-band pilot: `cycle0/path-a-pump-mcband-pilot-20261002.md`

## Non-actions

- paper_live PID **18531** not killed/restarted
- `q5b_last.joblib` / `q5b_calibration.json` untouched
- Dune API calls: **0** · Lite OFF · USD scale OFF
