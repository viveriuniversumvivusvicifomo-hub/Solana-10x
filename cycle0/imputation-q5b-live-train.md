# Q5b imputation: live ↔ train parity

**Owner:** SolModelos · **Date:** 2026-10-01  
**Model:** `data/paper_live/models/q5b_last.joblib`  
**Related:** `cycle0/live-vs-train-mismatch-hunt-20261001.md` §8

## Pipeline (train + live)

1. Feature vector `X` in recipe order `FEATURE_SETS['+q5b']` (51 cols).
2. **`SimpleImputer(strategy="median")`** — medians frozen from **fold-5 train** at export.
3. **`HistGradientBoostingClassifier`** — no `StandardScaler` in the pipeline.

Live path: `None` / missing → `np.nan` → same imputer statistics → HistGB.
There is no live re-fit of medians.

## Critical nulls

| Column | Train | Live must |
|--------|-------|-----------|
| `creator_prior_mints_all_in_window` | ~99.99% NULL | **Always `None`** (never invent `0.0`) |
| `*_share` / `*_pct_proxy` / max_buy_* | null when no buys | null-ok **only** if `buy_count_total==0` |

Filling `creator_prior_mints_all_in_window=0.0` when priors are empty poisons live vs the train null path (imputer median ≠ 0).

## Creator priors (counts)

Train: `add_cohort_creator_priors` on Dune cohort CSV (causal `create_ts`).  
Live (2026-10-01 SolModelos fix):

1. `dune_cohort_exact` — mint in `features_dune_p0_q5_expand_v2.csv` (preferred) or `dune_q5b_features.csv` → copy 7d/30d/cohort; `all_in_window` → None.
2. `dune_cohort_recompute` — uncapped cohort index (`window_days=None`) + `q5b_from_create`.
3. `none` / `dune_cohort_empty` — empty priors → counts 0 (same as train first mint).
4. `pump_frontend_30d` — **off by default**; opt-in `ALLOW_PUMP_FRONTEND_PRIORS=1` (non-parity).

Persist `creator_prior_source` on enrich features always.

## How to verify

```bash
# Recipe names/order == joblib
PYTHONPATH=src .venv/bin/python -c "
from paper_live.recipe_parity import assert_recipe_matches_joblib
assert_recipe_matches_joblib()
print('recipe_parity OK')
"

# Inspect frozen imputer medians
PYTHONPATH=src .venv/bin/python -c "
import joblib
from paper_live.config import MODEL_Q5B_PATH
blob = joblib.load(MODEL_Q5B_PATH)
pipe = blob['model']  # or blob['pipeline'] depending on export
# Walk to SimpleImputer
from sklearn.impute import SimpleImputer
imp = None
est = pipe
if hasattr(est, 'named_steps'):
    for step in est.named_steps.values():
        if isinstance(step, SimpleImputer):
            imp = step
            break
elif hasattr(est, 'steps'):
    for _, step in est.steps:
        if isinstance(step, SimpleImputer):
            imp = step
            break
assert imp is not None, 'SimpleImputer not found'
names = blob.get('feature_names') or []
stats = list(imp.statistics_)
idx = names.index('creator_prior_mints_all_in_window') if 'creator_prior_mints_all_in_window' in names else None
print('n_features', len(stats), 'all_in_window_median', stats[idx] if idx is not None else 'N/A')
"
```

Also: `python -m verification.live_parity` and unit tests under `tests/paper_live/`.
