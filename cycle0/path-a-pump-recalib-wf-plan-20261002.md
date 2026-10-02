# Path A recalib / WF plan — Pump as source of truth

**Date:** 2026-10-02 (CEST)  
**Trigger:** Sinck — after Pump MC+T0(+trades) live rewrite, recalibrate USD scale, Q5a/Q5b, creator priors, score thresholds.  
**Constraints:** No Dune credit burn without explicit cost note + Sinck GO. Prefer **offline / local store**. Lite stays **disabled**.

## Why recalib

Live captura no longer mirrors Helius Enhanced trade-refine C1–C6. HistGB was trained on Dune Q3/Q4/Q5 Path A features (trade-implied MC, Pyth USD, dune_cohort priors). Pump sighting MC + (eventually) Pump trades will **shift** feature distributions → scores/thresholds drift.

## Scope (ordered)

| # | Workstream | Offline source (prefer) | Dune? | Output |
|---|------------|-------------------------|-------|--------|
| 0 | **Captura gate** Pump MC+age | live code (done 2026-10-02) | no | `path-a-pump-mc-trades-20261002.md` |
| 1 | **Inventory local stores** | `data/samples/features_*.csv`, labels, helius parity dumps, pump samples | no | checklist below |
| 2 | **USD scale** | Existing Path A scale study (`USD_RECALIB_PLAN`, ge10 diagnostics); keep scale **OFF** for live until Pump-USD vs Dune-USD measured | no (reuse local) | confirm `apply_dune_helius_usd_scale` OFF; note Pump MC is already USD from frontend |
| 3 | **Q5a features** | When Pump trades API works: rebuild buy60/Q5a from Pump ≤T0; until then: measure null rates / skip rates on live journal | **hold** Dune Q5a | `cycle0/artifacts/pump_q5a_gap_*.json` |
| 4 | **Q5b + creator priors** | Local `dune_cohort_*` CSVs already on disk for exact/recompute; Pump `/coins?creator=` only as soft explore — histgb still requires `dune_cohort_*` | no new Dune | document prior hit-rate on live mints vs store |
| 5 | **Score thresholds** | Offline: re-score fold-5 TEST with **available** Pump-like feature mask (null Q5a→imputer behavior) OR wait for Pump trades; propose thr vs current 0.9 / config 0.99 | no | `lite` N/A; histgb thr proposal in artifacts |
| 6 | **WF refit (optional, later)** | Only if Sinck GO + local feature matrix has Pump-parity columns; joblib new `q5b_pump_*` — **do not** overwrite `q5b_last.joblib` without GO | Dune only if gaps + cost noted | frozen recipe note |

## Cost fence

- **Default:** zero Dune API calls. Use `data/samples/features_dune_p0_q5_expand_v2.csv`, `labels_dune_expand_v2.csv`, creator prior index, ge10 parity dumps.
- If a Dune pull is unavoidable: write estimated CU/$ in the cycle0 note and **stop for Sinck GO**.

## First concrete steps (start now)

1. ✅ Ship Pump captura gate + default `--enrich-via pump` (this cycle).
2. **Inventory** local feature/label/prior files + sizes → `cycle0/artifacts/pump_recalib_inventory_20261002.json`.
3. **Baseline skip taxonomy** on dry-run pump enrich (n cycles): counts of `skip_capture_not_scoreable` (expect 0 from `no_trade_mc_path`), `skip_missing_buy_vol`, `skip_incomplete_q5b`, `skip_prior_not_train`.
4. **USD:** assert live Path A scale flag OFF; document that Pump `usd_market_cap` is frontend USD (not sol×pyth trade MC).
5. **Priors:** script to measure % of Pump-band sample mints with `dune_cohort_exact` hit in local store (no network).
6. **Thr:** defer numeric thr move until buy_vol/Q5a non-null path exists OR Sinck accepts score-on-partial with explicit imputer audit.

## Non-goals (this wave)

- Lite calib / lite daemon  
- Burning Dune for Q5a backfill  
- Claiming Pump live ≡ Dune train bit-exact  
- Overwriting `q5b_last.joblib` without Sinck GO  

## Success criteria (expanded)

| Criterion | Status |
|-----------|--------|
| Pump `capture_scoreable` without Helius trades | code + tests |
| No `no_trade_mc_path` score skip on Pump path | code + tests |
| Recalib plan documented | **this file** |
| Inventory artifact written | step 2 |
| Dry-run skip taxonomy | step 3 |
| USD scale policy restated | step 4 |
| Prior hit-rate on local store | step 5 |
| Thr / WF refit | blocked on trades or Sinck GO |


## Progress log (2026-10-02 ~08:11 CEST)

| Step | Result |
|------|--------|
| 0 Captura gate | **DONE** — see `path-a-pump-mc-trades-20261002.md` |
| 2 Inventory | **DONE** → `cycle0/artifacts/pump_recalib_inventory_20261002.json` (expand features 64MB, labels, q5b CSV, q5b_last.joblib present; buy60_last.joblib missing) |
| 3 Dry skip taxonomy | **DONE** — 8/8 `capture_scoreable=true`; 0× `no_trade_mc_path`; score modes: **8× `skip_missing_buy_vol`** (Pump trades API gap) |
| 4 USD scale | **DONE** — `apply_dune_helius_usd_scale_enabled=false`; live policy: Pump frontend USD MC; scale stays OFF |
| 5 Prior hit-rate | **DONE (local)** — 0/8 pump sample mints in exact meta store (expected: live band ≢ train cohort). histgb still requires `dune_cohort_*` → many live mints will `skip_prior_not_train` once buy_vol exists |
| 6 Thr / WF | **BLOCKED** on Pump trades (buy_vol) or Sinck GO for partial-feature / new joblib |

### Dry-run evidence

```text
[paper-live] cycle=1 ... polled=8 new=8 paper=0 skip_vol=8 ... enrich_via=pump
journal: capture_scoreable=true, t0_definition=pump_mc_band_sighting_v1,
         score_mode=skip_missing_buy_vol (NOT skip_capture_not_scoreable)
```

### Next concrete files to add (offline, no Dune)

1. `scripts/pump_recalib_prior_coverage.py` — scan live journal mints vs local creator prior index (% dune_cohort_exact).
2. `scripts/pump_recalib_feature_mask_audit.py` — on expand CSV, null-out Q5a/buy60 like live Pump gap → measure HistGB score collapse / skip rate (offline).
3. When Pump trades API fixed: `scripts/rebuild_pump_trades_features_offline.py` → new feature matrix → thr sweep → optional `q5b_pump_*` joblib (Sinck GO before overwrite `q5b_last`).


## Progress log (2026-10-02 ~08:39 CEST) — Sinck "Hazlo"

| Step | Result |
|------|--------|
| Inventory refresh | **DONE** → `artifacts/pump_recalib_inventory_20261002.json` (expand/labels/q5b OK; **no** Pump feature matrix / `q5b_pump_*`) |
| USD scale | **CONFIRMED OFF** |
| Live skip taxonomy (PID 18531 window) | **31× skip_prior_not_train**, 4× age-not-scoreable, **0× skip_missing_buy_vol** |
| Prior coverage (live vs local store) | 0/31 exact mint; 4/31 creator in Dune index (12.9%) |
| Offline live scores vs thr 0.9 | **max 0.532 · p50 0.160 · 0≥0.9** (Pump priors or Dune-recompute) |
| Store OOS score proxy (post fold5 train_end) | n=9851 · frac≥0.9 ≈ 9.1% · max≈0.9999 |
| Feature mask audit | refreshed; secondary now that buy_vol works |
| WF refit / new joblib | **NOT RUN** — blocked on Pump-aligned features |
| Model / thr swap | **NO-GO** — see `path-a-pump-recalib-go-nogo-20261002.md` |
| paper_live | undisturbed (PID 18531) · Lite OFF · Dune calls **0** |

### Executable next (await Sinck)

1. GO Option A: stamp `creator_prior_source=dune_cohort_*` in `pump_enrich` (offline code).  
2. GO Option B: sample Pump Q5a overlay → `q5b_pump_*.joblib` (no overwrite `q5b_last`).  
3. Any Dune pull: cost note + stop for GO.
