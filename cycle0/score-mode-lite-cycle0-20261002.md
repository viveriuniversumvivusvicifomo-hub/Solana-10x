# Cycle 0 — `score_mode=lite` (+ multi-scorer lanes)

**Date:** 2026-10-02 (Europe/Madrid, CEST)  
**Owner:** SolModelos (design + skeleton) · SolDatos (fast feature sources) · SolQA (gates)  
**Sinck GO:** rebuild product algorithm — **simple score on 5–10 features** measurable in **seconds** via **Pump + RPC**; calibrate to WF insights; **NOT** cloning full Dune/Helius `histgb_q5b` pipeline. **Also** run several models in parallel.  
**Paper / Path A:** **FROZEN** rules unchanged — no Dune credit burn; no claim of exact live↔train parity for lite; live primary lane stays `histgb_q5b` @ thr **0.9** (`scripts/start_paper_thr09.sh`).

---

## 1. Why lite (product)

| Pain | histgb_q5b today | lite intent |
|------|------------------|-------------|
| Latency / cost | Full `FEATURE_SETS['+q5b']` (51 cols) needs Helius ≤T0 pagination + dune_cohort priors + Path A gates | 5–10 cols from Pump snapshot + thin RPC trade window |
| Fragility | Skip on incomplete pack / non-train prior / non-pyth | Soft-missing OK with documented defaults; skip only if core momentum missing |
| Parity claims | Bound to Path A / recipe freeze | **Explicitly non-parity** — ranking proxy calibrated to WF, not bit-exact replay |
| Product | Single ultra-select lane | **Parallel lanes**: histgb (frozen) + lite (explore) + room for more |

WF PRIMARY `hit_10x_30d` (see `wf-post-q5-primary-summary.md`):

1. **`buy_vol_usd_60s` alone ≈ AUC 0.905** — dominant.
2. **Q5a on top ≈ +0.024 AUC** — sniper / early concentration matter.
3. **Q5b ≈ small bump** — creator priors non-zero but secondary.
4. **`full` ≈ `+q5b`** — do not chase expand extras.

Lite = distill (1)+(2)+cheap slice of (3) into a **seconds-budget** score.

---

## 2. Feature list (lite v0) — only what live can compute fast

Sources: **Pump frontend** coin snapshot + `/coins?creator=` · **RPC/Helius FAST** ≤T0 trades (existing live page budget, not recovery 80-page). **No new Dune pulls.**

| # | Feature | WF pack | Live source (seconds) | Missing policy |
|---|---------|---------|------------------------|----------------|
| 1 | `buy_vol_usd_60s` | buy60 | Helius FAST ≤T0 Path A USD (existing enrich) | **required** → skip lite |
| 2 | `sniper_vol_share_5s` | Q5a | same trades → `q5a_agg` | default 0.0 if no buys |
| 3 | `top1_buyer_vol_share` | Q5a (concentration) | same | default 0.0 if no buys |
| 4 | `top5_buyer_vol_share` | Q5a | same | default 0.0 |
| 5 | `age_s` | Q5b | Pump `created_timestamp` vs T0 | default NaN→median proxy **60s** (doc only; stub uses 60) |
| 6 | `progress_curve_proxy` | Q5a | Pump BC reserves | default 0.0 |
| 7 | `net_sol_curve` | Q5a | Pump `real_sol` / trades pumpdotfun | default 0.0 |
| 8 | `creator_prior_mints_7d` | Q5b | Pump creator coins **or** dune_cohort cache (prefer cache if present; Pump OK for lite) | default 0 |
| 9 | `creator_prior_mints_30d` | Q5b | same | default 0 |

**Out of lite (intentionally):** full Q5a window farm (15m/30s/…), holder proxies needing balance index, `creator_prior_mints_all_in_window`, expand-flow extras, anything needing Dune batch.

Constants live in `features.post_q5_sets.LITE_COLS` / `paper_live.score_lite`.

---

## 3. Scoring rule (v0)

**Form:** logistic of a **linear score** on clipped / log1p features (tiny model; no HistGB).

\[
z = w^\top \phi(x) + b,\quad
p = \sigma(z) = (1+e^{-z})^{-1}
\]

**Transforms \(\phi\) (freeze for cycle0 stubs):**

| Feature | \(\phi\) | Rationale |
|---------|----------|-----------|
| buy_vol | \(\log1p(\mathrm{clip}(v,0,10^7))/10\) | WF dominant; compress heavy tail |
| sniper_vol_share_5s | \(\mathrm{clip}(s,0,1)\) | early sniper mass |
| top1_buyer_vol_share | \(\mathrm{clip}(s,0,1)\) | concentration risk/signal |
| top5_buyer_vol_share | \(\mathrm{clip}(s,0,1)\) | softer concentration |
| age_s | \(\log1p(\mathrm{clip}(a,0,86400))/10\) | very old re-band → downweight |
| progress_curve_proxy | \(\mathrm{clip}(p,0,1)\) | curve progress |
| net_sol_curve | \(\mathrm{clip}(n,-85,85)/85\) | SOL on curve proxy |
| creator_prior_7d | \(\log1p(\mathrm{clip}(c,0,100))/5\) | spam creators |
| creator_prior_30d | \(\log1p(\mathrm{clip}(c,0,300))/5\) | longer prior |

**Initial weights** (heuristic from WF ranking — **not** OOS-fit; recalibrate offline later without Dune):

```
w_buy_vol          = +2.40   # buy60 dominates
w_sniper           = +0.80
w_top1             = +0.50
w_top5             = +0.35
w_age              = -0.25   # older → slightly worse for band entry
w_progress         = +0.20
w_net_sol          = +0.30
w_prior_7d         = -0.40   # high mint spam → down
w_prior_30d        = -0.25
b (bias)           = -1.20   # keep mass of scores mid/low until calib
```

**Mode string:** `lite_logistic_v0`.  
**Alt (rules stub):** `lite_rules_v0` = weighted sum of gates (buy_vol≥X AND sniper≤Y …) → `{0,1}` — kept as stub only.

**Calibration path (next build, no Dune):** score OOS preds’ *same* lite cols from local `features_dune_p0_q5_expand_v2.csv` → fit bias / one temperature on TRAIN folds only; write `data/paper_live/models/lite_calibration.json`. Do **not** overwrite histgb artifacts.

---

## 4. Entry thresholds (per lane)

| Lane | `score_mode` | Default thr | Capacity | Role |
|------|--------------|-------------|----------|------|
| **A primary (live)** | `histgb_q5b` | **0.9** (Sinck thr09 script; config JSON may still say 0.99 — thr09 wins when launched) | `max_per_hour` shared or per-lane | Frozen product |
| **B explore** | `lite` / `lite_logistic_v0` | **0.55** stub (until calib) | separate `max_per_hour_lite` default 2 | Second candidate stream |
| Future | e.g. `histgb_buy60` | trainQ / explicit | optional | Ablation lane |

Rules:

- Thresholds are **per model**; never mix scores across lanes.
- Capacity: prefer **per-lane** counters (`paper_candidates.score_mode` already stored) so lite cannot starve histgb.
- Shared mint: may enter **both** lanes (two rows) **or** one row with `lanes_json` — skeleton uses **one sighting**, optional **enter per lane** with distinct `score_mode` (second enter needs mint PK change — see §5).

---

## 5. How lite sits beside `histgb_q5b`

```
sighting → enrich (Pump + Helius FAST)
        → feats (+q5b pack when available; lite subset always attempted)
        → MultiScorer.score_all(feats)
              ├─ histgb_q5b  → ScoreResult (Path A gates unchanged)
              └─ lite        → ScoreResult (soft missing; no Path A prior gate)
        → journal sighting: score=primary, scores_json={...}, score_lite=...
        → EntryGate per lane (thr_A, thr_B)
        → candidates: primary lane writes paper_candidates as today;
                      lite lane → candidates_lite.csv (+ optional sqlite table)
```

**Non-goals / freeze:**

- Do **not** burn Dune credits for lite train or live.
- Do **not** claim lite ≈ histgb or exact Path A parity.
- Do **not** swap `q5b_last.joblib` or reopen Path A re-fit (still PAUSADO).
- Do **not** weaken histgb skip gates (`require_t0_refined`, train priors, pyth).

**Parallelism:** score lanes are CPU-cheap; run **sequentially in-process** first (skeleton). True thread/process pool is optional later.

---

## 6. Code map (skeleton delivered)

| Path | Role |
|------|------|
| `cycle0/score-mode-lite-cycle0-20261002.md` | This design |
| `src/features/post_q5_sets.py` | `LITE_COLS` + `FEATURE_SETS['lite']` |
| `src/paper_live/score_lite.py` | `LiteScorer` logistic v0 + rules stub |
| `src/paper_live/multi_score.py` | `MultiPaperScorer` — histgb + lite |
| `src/paper_live/score.py` | unchanged histgb Path A (importable) |
| `src/paper_live/config.py` | parallel modes, lite thr, paths |
| `src/paper_live/journal.py` | `scores_json` / CSV lite cols; `candidates_lite.csv` |
| `src/paper_live/loop.py` | score_all + dual entry (opt-in) |
| `src/paper_live/__main__.py` | `--parallel-score-modes`, `--score-threshold-lite` |
| `tests/paper_live/test_score_lite_multi.py` | unit tests |
| `data/paper_live/models/lite_calibration.json` | stub weights/thr |

Default CLI remains `--score-mode histgb_q5b` (single lane). Enable second lane:

```bash
PYTHONPATH=src .venv/bin/python -m paper_live --live ... \
  --score-mode histgb_q5b --score-threshold 0.9 \
  --parallel-score-modes histgb_q5b,lite --score-threshold-lite 0.55
```

---

## 7. Recommended next build step (Sinck)

1. **Offline calib (no Dune):** from local expand CSV, compute lite \(\phi\) on fold-5 TRAIN → temperature/bias so lite P@top≈ histgb ranking correlation; write real `lite_calibration.json`.
2. **Wire FAST-only feature path** that stops after lite cols (skip waiting on full +q5b completeness for lane B).
3. **Paper dual journal smoke** dry-run 3 cycles; compare histgb vs lite accept sets (no live capital).
4. Only then: consider raising/lowering lite thr; keep histgb thr 0.9 until Sinck revises.

---

## 8. Status

| Item | State |
|------|-------|
| Design (this doc) | **DONE** 2026-10-02 |
| Code skeleton multi-scorer + lite | **DONE** (opt-in; live default unchanged) |
| Offline lite calib on WF CSV | **DONE** 2026-10-02 → `lite_calibration.json` + `lite-calib-offline-cycle0-20261002.md` |
| Dual dry-run vs histgb@0.9 | **DONE** (smoke; see calib note) |
| Live thr histgb 0.9 | **UNCHANGED** |
| Path A / paper freeze / no Dune | **HELD** |
