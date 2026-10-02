# Path A — Residual parity audit (2026-10-02)

**Date:** 2026-10-02 ~09:45 CEST (Europe/Madrid)  
**Workstream:** 3 — Residual live↔train gaps after Pump captura + A/B session  
**Constraints:** paper_live PID **18531** untouched · Lite OFF · USD scale OFF · 0 Dune · `q5b_last` untouched  
**Inputs:** mismatch-hunt 2026-10-01, ge10/USD diagnostics, journal Path A Pump window, prior coverage artifact, WS2 column map

## Executive ranking

| Rank | Gap | Class | Fix type | Action |
|------|-----|-------|----------|--------|
| **1** | Feature **distribution** at Pump T0 (MC 8–20k, early curve) vs train snipers (near-grad curve, buy60 median ~59k vs live ~0.2–2k) | data / definition | **data** | Build Pump-true labeled matrix (WS2 GO-1); twin joblib NO-GO |
| **2** | `progress_curve_proxy` / `net_sol_curve` **Pump coin overlay overwrites** trade agg | code | **code** | Stop overwrite on Pump path when trades present (match Helius fix); or accept + document |
| **3** | `age_proxy_s` live = `age_s` (create→T0); train Q5a = t0−first_trade | code | **code** | Keep trade `age_proxy_s` from `q5a_agg`; do not overwrite with create age |
| **4** | Creator prior stamp: running PID still `creator_prior_source=None` → `skip_prior_not_train` | ops / code-done | **ops** | Restart for A (Sinck GO); expect exact≈0%, recompute≈13%, empty≈87% |
| **5** | USD: `sol_usd_source=pump_frontend` / `valueUsd` vs train Dune `amount_usd` (+ legacy Pyth as-of train ideal) | data | **accept** (scale OFF) unless pilot shows otherwise |
| **6** | Q5b holders: defs match; inputs (trader_id) differ Pump vs Dune | data | **accept** short-term; remeasure on Pump matrix |
| **7** | T0 definition: Pump sighting vs train C1–C6 | definition | **accept** for Path A product; train must follow |
| **8** | Prior store frescor (no creates after train_t0_max) | data | **accept** / later Bitquery index |
| **9** | Open mismatch-hunt items (Helius side/project — N/A on Pump gate) | n/a | **accept** for enrich-via=pump | Helius-only residuals |

## 1) Oracle / USD

| Side | Source |
|------|--------|
| **Live Path A Pump** | `feats["sol_usd_source"]="pump_frontend"`; MC = frontend `usd_market_cap`; trade USD = `valueUsd` (else sol×`sol_usd` if provided) |
| **Train** | Dune `amount_usd`; product doc prefers Pyth as-of-T0 for Helius rebuilds |
| **Scale flag** | `apply_dune_helius_usd_scale_enabled=false` (**confirmed**) |

### Sensitivity (reuse local diagnostics — no new paid calls)

| Evidence | Result |
|----------|--------|
| `cycle0/artifacts/scale_isolation.csv` | Scaling USD alone does **not** restore ≥0.99; incomplete ≤T0 trades dominate collapse |
| ge10 Path A USD pilot | max \|Δ\| vs store ≈ **2.35e-3** on already-high OOS rows — residual class = USD/vol, not cutover signal |
| Pump live offline scores | max≈**0.53** / 0≥0.9 with or without prior swap (Δ mean abs ≈0.009) |
| Feature dist train_oos≥0.99 vs live | live `buy_vol_usd_60s` median ~**183** vs train hi ~**59k**; `progress_curve` live ~0.01 vs train ~1.0 |

**Recommendation:** keep **USD scale OFF**. Pump frontend USD is intentional for Path A MC; a 6.6× Helius↔Dune factor is the wrong lever for Pump-true. Revisit only after Pump-labeled WF if OOS calibration demands an explicit documented factor (not blind).

## 2) Q5b / holders

### Which Q5b cols fill on Pump enrich vs train

| Col | Train | Live Pump enrich (journal scoreable n=167) |
|-----|-------|-----------------------------------------------|
| `age_s` / `age_min` | Dune create | Pump create — **100% filled**, age gate OK |
| `has_creator`, name/symbol lens | CreateEvent | Pump coin / sighting — **100%** (`meta_source=create`) |
| `creator_prior_mints_{7d,30d,cohort}` | cohort SQL | Filled (counts present) but source stamp empty until restart |
| `creator_prior_mints_all_in_window` | ~99.99% NULL | **100% null** (correct) |
| Holders (`n_holders_proxy`, top1/5/10) | trade net_tok | From Pump trades agg — **0% null** on scoreable |
| `features_complete_q5b` | — | **true** on all 167 scoreable |

**Incomplete rates (recent journal Path A scoreable):** Q5b pack incomplete ≈ **0%** (only intentional `all_in_window` null). Pre-scoreable skips are age/MC gate (`skip_capture_not_scoreable`), not Q5b holes.

## 3) Prior coverage (after A — expected)

Code in `pump_enrich.py` now resolves **exact → dune_cohort_recompute → dune_cohort_empty** and stamps `creator_prior_source` (A done). **Running PID 18531 still old binary** → journal shows prior source empty / `skip_prior_not_train`.

From `cycle0/artifacts/pump_prior_coverage_live_20261002.json` (n=31 scoreable window):

| Outcome after restart | Expected rate |
|-----------------------|---------------|
| `dune_cohort_exact` | **~0%** (0/31 mint in store) |
| `dune_cohort_recompute` | **~13%** (4/31 creator in index) |
| `dune_cohort_empty` | **~87%** |
| Pump `/coins?creator=` | diagnostic only (not model counts) |

Prior stamp alone does **not** lift scores to thr 0.9 (offline max still ≈0.53).

## 4) Other open mismatches (from hunt + Pump path)

Still open / reclassified for enrich-via=pump:

| Item (hunt §) | Status on Pump Path A |
|---------------|------------------------|
| Feature names/order 51 | **MATCH** — keep recipe gate green |
| USD sol×oracle vs Dune | **Remapped** to frontend USD — accept + scale OFF |
| Window defs 5s/30s/60s/15m | **MATCH** in `q5a_agg` |
| Buy/sell + project filter (Helius) | **N/A** — Pump trades use `side` + project=`pumpdotfun` |
| Creator priors source | **Code fixed (A)**; **ops pending restart** |
| Holders proxies | Def MATCH; trader universe may differ — accept |
| T0 definition | **Product change** — train must move to Pump-true |
| Imputation `all_in_window` | **MATCH** (always None) |
| Thr 0.9 vs trainQ top1% | Product — NO-GO lower without Sinck |
| Curve frontend overlay | **OPEN code bug vs Helius parity fix** — rank #2 |
| `age_proxy_s` overwrite | **OPEN code** — rank #3 |

## 5) Ranked fixes

### Code (cheap, 0 API)

1. **Do not overwrite** `progress_curve_proxy` / `net_sol_curve` from Pump coin when trades produced Q5a values (align with Helius “no frontend curve overlay” fix). Keep coin proxies only when trades empty / gap.
2. **Stop overwriting** `age_proxy_s` with `age_s`; leave `q5a_agg` first-trade definition.
3. (Already done A) dune_cohort stamp — needs **restart** to take effect.

### Data

1. **Pump-true labeled matrix** (WS2 pilot n=500–2000) → real WF — only path to move score mass.
2. Optional: extend creator create index past `train_t0_max` (Bitquery/Helius) — later.

### Accept (for now)

1. USD scale OFF; frontend USD vs Dune amount_usd residual until Pump-trained model.
2. Exact prior hit-rate ~0 on live band; empty/recompute cold start.
3. T0 = Pump MC band sighting as product truth.
4. Holder trader_id differences vs Dune.
5. Twin `q5b_pump_20261002` as named companion only — **not** a swap.

## Recommended next Sinck GO

1. **GO-1:** WS2 pilot Pump overlay on expand sample → new matrix → WF candidate (alongside `q5b_last`).  
2. **GO-2:** Restart paper for A prior stamp (expect score then `skip_below_thr`).  
3. **GO-3 (optional code):** patch curve/`age_proxy_s` overwrites before restart.  
4. **NO-GO:** thr cut, USD scale ON, Dune burn, overwrite `q5b_last`, swap twin joblib.

## Non-actions this audit

- paper_live PID **18531** not killed/restarted  
- `q5b_last.joblib` md5 **4df6d5a8…** unchanged  
- Dune API calls: **0** · Lite OFF · USD scale OFF  

## Pointers

- WS2 plan: `cycle0/path-a-pump-true-features-plan-20261002.md`  
- Inventory: `cycle0/artifacts/pump_true_feature_inventory_20261002.json`  
- Journal/smoke CSVs: `data/samples/features_pump_path_a_{journal,smoke}_20261002.csv`  
- Prior hunt: `cycle0/live-vs-train-mismatch-hunt-20261001.md`  
- A/B session: `cycle0/path-a-pump-ab-priors-wf-20261002.md`
