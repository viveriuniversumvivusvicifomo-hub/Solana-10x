# Depur: features_stub → features_t0 + ModelStub live-path = 0

**Date:** 2026-10-02 ~14:14 CEST (Europe/Madrid)  
**Lane:** SolQA — Sinck/BOSS depuración total  
**Tree:** `/workspace/solana-10x/` (existing; no clone, no paper restart, no paid APIs)

## Summary

| Item | Verdict |
|------|---------|
| `features_stub.py` | **Was live production** (loop/score/rescore/recipe). **Renamed** → `features_t0.py`; all imports updated. Misleading `stub` name removed from live scoring path. |
| `ModelStub` / `models/stub.py` | **0 usage on live paper path**. Offline/Cycle-0 + unit tests only. Docstrings clarified. **PASS** (no live-path fix needed). |
| Curve / age / priors tests | **19 passed** (`test_path_a_pump_capture` 9 + `test_creator_priors_and_threshold` 10). No new tests added (coverage already present). |
| `verification.live_parity` | **ok: true** (hard_fails=[], soft_fails=[]). |

**Overall:** **GO** for SolAuditor (rename + ModelStub isolation + tests green).

## Decisions

### 1) `features_stub` → rename (option a)

**Inventory (pre-rename imports of `paper_live.features_stub`):**

| Consumer | Symbols |
|----------|---------|
| `src/paper_live/loop.py` | `assert_no_lookahead_keys`, `features_at_t0` |
| `src/paper_live/score.py` | `feature_vector_for_set`, `required_buy60_present`, `required_q5b_present` |
| `src/paper_live/rescore_replay.py` | `feature_vector_for_set`, `required_q5b_present` |
| `src/paper_live/recipe_parity.py` | `NULL_OK_Q5B`, `NULL_OK_WHEN_NO_BUYS`, `required_buy60_present` |
| `tests/paper_live/test_paper_live_v0.py` | full feature API |

**Why rename (not “document and leave”):** module builds the ≤T0 feature vector for the live scoring path (`histgb_q5b` / buy60). Name `stub` falsely implies placeholder/offline. Prefer rename per DoD.

**New path:** `src/paper_live/features_t0.py`  
**Contract** (module top): production live feature builder; completeness gates; anti look-ahead; aligned with `features.post_q5_sets`. No shim left at old path (clean break; all code imports updated).

### 2) ModelStub — document, keep offline

**Evidence — live path = 0:**

```text
$ rg -n 'ModelStub|models\.stub' src/paper_live tests/paper_live
# (no matches)
```

**Where it *does* appear (offline only):**

| Path | Role |
|------|------|
| `src/models/stub.py` | `ModelStub` class (fit freezes cols; predict_proba → 0.5) |
| `src/models/__init__.py` | re-export |
| `tests/models/test_stub.py` | unit tests |
| `src/models/run_stub_wf_cohort200.py` | comment / offline WF note |
| `data/samples/stub_walk_forward_cohort200_report.json` | sample report |

Live scoring uses joblib HistGB via `paper_live.score` — never `ModelStub`.

Docstrings on `models/stub.py` and `models/__init__.py` updated to state **offline / Cycle-0 only**.

### 3) Tests — verify existing; no suite invent

BOSS claim of ~19 curve/age/priors tests confirmed. Gaps vs curve/age/priors are covered by existing cases (`test_pump_enrich_keeps_trade_curve_and_age_proxy_when_trades_present`, gapfill, prior stamps, etc.). **No new tests added.**

Note: `test_hybrid_helius_dry_enrich_complete_for_fixture_mint` fails independently (fixture mint `age_gt_max_86400s` → `q5b_ok=False`). Unrelated to rename; not in the 19 curve/age/priors set. Out of scope for this lane.

## Files touched

| Path | Change |
|------|--------|
| `src/paper_live/features_stub.py` → `features_t0.py` | rename + production contract docstring |
| `src/paper_live/loop.py` | import → `features_t0` |
| `src/paper_live/score.py` | import → `features_t0` |
| `src/paper_live/rescore_replay.py` | import → `features_t0` |
| `src/paper_live/recipe_parity.py` | import → `features_t0` |
| `tests/paper_live/test_paper_live_v0.py` | import → `features_t0` |
| `cycle0/paper-live-v0.md` | filename ref `features_t0.py` |
| `src/models/stub.py` | offline-only docstring |
| `src/models/__init__.py` | offline-only docstring |
| `cycle0/depur-features-stub-modelstub-20261002.md` | this note |

**Not touched:** paper live PID, models joblib, secrets, paid APIs.

## Test commands + pass counts

```text
PYTHONPATH=src .venv/bin/python -m pytest \
  tests/paper_live/test_path_a_pump_capture.py \
  tests/paper_live/test_creator_priors_and_threshold.py -q
→ 19 passed in ~7.7s

PYTHONPATH=src .venv/bin/python -m pytest \
  tests/paper_live/test_paper_live_v0.py -k 'features or lookahead or buy60 or q5b_present or vector' -q
→ 8 passed, 31 deselected

PYTHONPATH=src .venv/bin/python -m pytest tests/models/test_stub.py -q
→ (included in broader run; ModelStub tests green)

PYTHONPATH=src .venv/bin/python -m verification.live_parity
→ {"ok": true, "hard_fails": [], "soft_fails": [], "n_train_cols": 51}
```

## ModelStub live-path = 0 proof (rg)

```text
# Live paper path — zero hits
rg -n 'ModelStub|models\.stub' src/paper_live tests/paper_live
# → no matches

# Repo usages (offline / tests only)
rg -n 'ModelStub|models\.stub' -g '!.venv/**' -g '!**/__pycache__/**' src tests
# → tests/models/test_stub.py, src/models/{stub,__init__,run_stub_wf_cohort200}.py only
```

## GO request for SolAuditor

- Rename applied; live scoring path no longer says `stub`.
- ModelStub confirmed absent from score/entry/loop/paper_live.
- 19 curve/age/priors + live_parity green; paper not restarted.

**Request:** SolAuditor please audit this note + diff (import graph + ModelStub isolation) and mark PA-LANE-STUB done if satisfied.
