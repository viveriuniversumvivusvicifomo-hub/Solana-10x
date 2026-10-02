# Canonical Path A train recipe (SINGLE source of truth) — 2026-10-02

**Owner:** SolModelos  
**Status:** CANONICAL — supersedes conflicting `path-a-pump-*` docs for **"what is train"**  
**Zone:** Europe/Madrid  
**Constraints:** do not train in this lane; document only. Future candidates must follow this recipe.

Older docs remain as **historical pointers** (plans, pilots, diagnostics) — **not** competing recipes:
- `cycle0/plan-refit-path-a-q5b-20261001.md` → historical plan (P1 paused)
- `cycle0/path-a-pump-recalib-wf-plan-20261002.md` / `path-a-pump-recalib-go-nogo-20261002.md` → historical recalib decision
- `cycle0/path-a-pump-true-features-plan-20261002.md` / pilots (`pilot500`, `mcband`, `livelike`, `ab-priors-wf`) → experiment notes; outputs quarantined in `cycle0/quarantine-q5b-pump-joblibs-20261002.md`
- `cycle0/live-train-recipe-parity.md` / `cycle0/imputation-q5b-live-train.md` → supporting detail (still valid; this doc consolidates)

---

## 1. Feature set

| Item | Spec |
|------|------|
| Pack | `FEATURE_SETS['+q5b']` |
| n cols | **51** |
| Source | `src/features/post_q5_sets.py` |
| Composition | buy60 + Q5a + Q5b (age/name/creator priors) |
| Banned from X | `JOIN_ONLY` (mint, t0, create_ts, creator_pubkey, …) · `DROP_FROM_X` (`migrated_pre_t0`) · labels · leak-like names |

Gate live ↔ joblib: `src/paper_live/recipe_parity.py` → `assert_recipe_matches_joblib()`.

---

## 2. Pipeline

| Step | Spec |
|------|------|
| 1 | `SimpleImputer(strategy="median")` — medians frozen from fold train at export |
| 2 | `HistGradientBoostingClassifier` |
| **Never** | `StandardScaler` in the pipeline |

Detail: `cycle0/imputation-q5b-live-train.md`.  
Live: missing → `np.nan` → same frozen imputer → HistGB (no live re-fit of medians).

Critical: `creator_prior_mints_all_in_window` stays **null** when unknown (never invent `0.0`).

---

## 3. USD (Path A)

| Role | Definition |
|------|------------|
| **Path A (claim parity)** | `amount_usd = sol_amt × sol_usd_asof_t0` (Pyth preferred / live Pump Path A Hermes) |
| Scale 6.6× | **OFF forever** — do not enable `APPLY_DUNE_HELIUS_USD_SCALE` |
| Dune `AmountInUSD` | Do **not** train on Dune AmountInUSD if claiming Path A parity |
| Sinck operativa | Residual oracle accepted for **paper** on current `q5b_last`; any **candidate** MUST document USD source in its calib / cycle0 note |

Code comment of record: `src/paper_live/recipe_parity.py` header (live Path A vs train Dune drift = data issue).

---

## 4. Label

- Primary: **`hit_10x_30d`**
- Proxy only if primary absent: `hit_200k` (not preferred for Path A candidate promotion)
- Resolver: `resolve_label_column` in `post_q5_sets.py`

---

## 5. Anti look-ahead

- Features **≤ T0** only (strict pre/at-T0 trades/meta)
- Time folds in walk-forward (expanding; last-fold export matches current `q5b_last` protocol unless Sinck revises)
- `DROP_FROM_X` as today (`migrated_pre_t0` never in X)
- Labels use strictly **post-T0** outcomes

---

## 6. Creator priors

| Context | Rule |
|---------|------|
| Live score gate | `dune_cohort_*` only (`live_entry_config.json` · `allowed_creator_prior_prefixes`) |
| Forbidden | `pump_frontend_30d`, `none`/null as scoreable train-family (see config) |
| Train | cohort priors causal on `create_ts` via expand / Dune cohort index — never invent non-train sources into X |

---

## 7. Export path for ANY future candidate

| Rule | Spec |
|------|------|
| Filename | `data/paper_live/models/q5b_path_a_candidate_*.joblib` (+ matching `*_calibration.json`) |
| **Never** | Overwrite `q5b_last.joblib` / `q5b_calibration.json` without **Sinck OK + GO criterion PASS** |
| Quarantined names | Do not reuse `q5b_pump_*` as production targets; existing `q5b_pump_*` are NO-GO (see quarantine inventory) |
| Alongside calib | Document: USD source, T0 policy, n/pos, recipe tag, journal lift vs `q5b_last`, `recipe_parity` result |

Promotion gate: `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md`.

---

## 8. Code pointers (implementation SoT)

| Concern | Path |
|---------|------|
| Feature pack / DROP_FROM_X / label | `src/features/post_q5_sets.py` |
| Walk-forward / last-fold export | `src/models/walk_forward_post_q5.py` (and existing export helpers used by q5b_last) |
| Live scoring | `PaperScorer` / paper_live score path (`src/paper_live/`) |
| Recipe gate | `src/paper_live/recipe_parity.py` |
| Imputation notes | `cycle0/imputation-q5b-live-train.md` |
| **Train entry (canonical)** | `scripts/train_q5b_path_a_candidate_wf.py` |
| Historical train scripts | `scripts/archive/train_q5b_pump_*.py` (NO-GO; refuse on invoke) |
| Build matrices (SolDatos) | `scripts/build_pump_path_a.py` |
| Entry thr / Path A captura | `data/paper_live/models/live_entry_config.json` |

---

## 9. Producción canónica (until GO + Sinck)

- Model: `q5b_last.joblib`
- Calib: `q5b_calibration.json`
- Entry: `live_entry_config.json` — thr **0.99**, Path A Pump MC band, scale OFF

Do not swap paper to a candidate until GO criterion + SolAuditor PASS operativo + Sinck OK.
