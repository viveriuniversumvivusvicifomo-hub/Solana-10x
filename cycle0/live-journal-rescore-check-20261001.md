# Live journal rescore check — 2026-10-01

**Owner:** SolModelos · **Repo:** `/workspace/solana-10x`  
**Generated:** 2026-10-01 ~16:46 Europe/Madrid (UTC+2)  
**Live not restarted** by this check.

## Goal

Re-score recent `histgb_q5b` journal rows (`features_json` → same `FEATURE_SETS['+q5b']` / `q5b_last.joblib`) and compare **journal score vs recomputed score**.  
**Expectation if recipe path OK:** Δ ≈ 0 (bit-identical float path).

## Paths

| Item | Path |
|------|------|
| Journal | `data/paper_live/paper_journal.sqlite` |
| Model | `data/paper_live/models/q5b_last.joblib` |
| Tool | `src/paper_live/rescore_replay.py --journal` |
| Sample CSV (newest 200) | `cycle0/artifacts/live_journal_rescore_20261001.csv` |
| Post-restart CSV (n=36) | `cycle0/artifacts/live_journal_rescore_post_restart_20261001.csv` |
| JSON summary | `cycle0/artifacts/live_journal_rescore_20261001_report.json` |

## Method

1. `assert_recipe_matches_joblib()` — recipe `FEATURE_SETS['+q5b']` vs joblib `feature_names`.
2. Load `sightings` where `score_mode='histgb_q5b'`, parse `features_json`.
3. Require `required_q5b_present(feats)`; build X via `feature_vector_for_set(..., "+q5b")`.
4. `pipeline.predict_proba` — **bypass** `PaperScorer` live gates (`t0_refined` / Pyth / `creator_prior_source`) so Δ measures **recipe+X fidelity only**, not enrich/gate policy.
5. Δ = `journal_score − rescore`.

Restart cuts (from live logs, Europe/Madrid):

| Cut | Log | Meaning |
|-----|-----|---------|
| `2026-10-01T16:29:00` | `run_pump_helius_parity_20261001-162922.log` | Parity restart — last window with `histgb_q5b` scores |
| `2026-10-01T16:43:00` | `run_pump_helius_mustfix_*` / `pathA_*` | Must-fix / Path A — **0** `histgb_q5b` since then |

## 1. Journal inventory

| Metric | Value |
|--------|------:|
| `histgb_q5b` total | **925** |
| `histgb_q5b` pre parity restart (&lt;16:29) | **889** |
| `histgb_q5b` post parity (≥16:29) | **36** |
| `histgb_q5b` post must-fix (≥16:43) | **0** |
| `features_json` null on histgb | **0** |
| created_at range | 10:43:16 → 16:42:03 (+02) |

**Sightings columns:** `mint, t0_ts, mc_usd_t0, name, symbol, source, features_json, score, score_mode, paper_candidate, created_at`.

**Post must-fix (≥16:43):** only `skip_capture_not_scoreable` (n=16 at check time). Those rows **do** stamp `creator_prior_source` (`dune_cohort_empty` / `dune_cohort_recompute`) but have **no journal score** to Δ against (score NULL). 15/16 have complete X and *would* rescore in ~0.04–0.27 if gates were off — not a journal↔joblib residual.

## 2. Recipe ↔ joblib parity

| Check | Result |
|-------|--------|
| `FEATURE_SETS['+q5b']` n | 51 |
| joblib `feature_names` n | 51 |
| order + membership | **PASS** |
| DROP/JOIN leak | none |

## 3. Residuals (honest)

### Newest N=200 with complete X

| Stat | Value |
|------|------:|
| n rows / n rescored / n incomplete | 200 / **200** / 0 |
| of which post-parity restart | 36 |
| **max \|Δ\|** | **0.0** |
| p50 \|Δ\| | **0.0** |
| p95 \|Δ\| | **0.0** |
| n \|Δ\| > 1e-6 | **0** |
| n \|Δ\| > 1e-4 | **0** |
| n exact zero | **200 / 200** |

Journal score band on sample: min 0.015, p50 0.104, max 0.564. **n ≥ 0.99: 0**.

### Post-parity restart (all histgb, n=36)

| Stat | Value |
|------|------:|
| n rescored | **36** |
| **max \|Δ\|** | **0.0** |
| p50 / p95 \|Δ\| | **0.0 / 0.0** |
| n \|Δ\| > 1e-6 or 1e-4 | **0** |

### Oldest 100 histgb (spot check)

Same: max \|Δ\| = **0.0**, n>0 = 0.

### Verdict on recipe path

**Δ = 0 exactly** on every rescored histgb row checked (200 newest + 36 post-restart + 100 oldest).  
**Recipe / joblib / journal `features_json` → score path is bit-faithful.**  
This does **not** claim live enrich matches train, nor that live gates are healthy.

## 4. `creator_prior_source` distribution

| Population | Distribution |
|------------|--------------|
| All 925 `histgb_q5b` | **`<ABSENT>`: 925** (field never persisted on scored histgb rows) |
| Newest 200 sample | `<ABSENT>`: 200 |
| Post-parity histgb (36) | `<ABSENT>`: 36 |
| `skip_capture_not_scoreable` (must-fix window) | `dune_cohort_empty`: 13, `dune_cohort_recompute`: 3 |

**No `dune_cohort_*` on any row that has a journal `histgb_q5b` score.**  
Those stamps appear only on **skipped** post–Path-A rows (no score to compare).

### `sol_usd_source` on samples

| Sample | Dist |
|--------|------|
| Newest 200 | `jupiter`: 167, `coingecko_asof`: 29, `jupiter_live_not_asof`: 4 |
| Post-parity 36 | `coingecko_asof`: 29, `jupiter_live_not_asof`: 4, `jupiter`: 3 |

None are `pyth` / `pyth_asof` — consistent with Path A blocking new scores after must-fix restart when Pyth key missing.

## 5. Recipe mismatches

**None** in column recipe vs joblib.  
**None** in journal-score vs recompute for stored X.

What *is* mismatched vs current live policy (out of scope for Δ, but blockers for BOSS/SolDatos):

1. **Post must-fix: 0 histgb scores** — all new sightings `skip_capture_not_scoreable` (Pyth / capture gates). Cannot extend journal↔joblib Δ into that window.
2. **`creator_prior_source` absent on all scored histgb** — prior gate cannot be audited from scored journal rows; only skip rows carry `dune_cohort_*`.
3. **Live score level still far from trainQ 0.99** on sample (max 0.564) — enrich/USD/prior issue, **not** recipe dump bug (confirmed by Δ=0).

## 6. Blockers for BOSS / SolDatos

| # | Blocker | Owner hint |
|---|---------|------------|
| 1 | No Pyth as-of → Path A refuses scoreable captures after must-fix restart | Ops / Sinck key; SolDatos oracle |
| 2 | Scored journal lacks `creator_prior_source` stamp (always ABSENT on histgb) | SolDatos enrich persist + SolModelos gate audit |
| 3 | Cannot “prove” prior path via journal Δ until histgb rows exist **with** `dune_cohort_*` + score | Wait for first Path-A scoreable histgb after Pyth |
| 4 | Score calibration vs train still open (max live ≪ 0.99) — separate from recipe fidelity | SolDatos USD/pagination/T0; already documented in mismatch hunt |

## 7. CLI for re-run

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay \
  --journal --limit 200 --out-prefix live_journal_rescore

PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay \
  --journal --since 2026-10-01T16:29:00 --limit 50 \
  --out-prefix live_journal_rescore_post_restart
```

## Bottom line

- **Recipe Δ ≈ 0?** **Yes — exact 0** on n=200 (and n=36 post-restart, n=100 oldest).  
- **Journal has feature vectors?** **Yes** for all 925 histgb (`features_json` nonempty, complete X on samples).  
- **Post live must-fix restart:** **no histgb scores yet** to re-score; only skips.  
- **Do not handwave:** recipe path is clean; live **entry/calibration/gates** remain broken or blocked independently of joblib dump fidelity.
