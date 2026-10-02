# Q5 anti-lookahead QA + merge protocol

**Owner:** SolQA · **Packs:** `features.dune.p0.q5a.v1`, `features.dune.p0.q5b.v1`  
**Cohort base:** `features_dune_p0_flow_expand_v2.csv` + `labels_dune_expand_v2.csv`  
**Code:** `src/verification/q5_merge.py` · `src/features/post_q5_sets.py`  
**Date:** 2026-09-30 (CEST)

Streams Helius **OFF**. Never print/write `DUNE_API_KEY*`.

---

## A) Column deny-list (must be empty ∩ train X)

| Pattern / column | Why |
|------------------|-----|
| `max_mc*`, `hit_*`, `label_*`, `after_t0`, `primary_ready` | Labels / post-T0 |
| `creator_pubkey` | Join-only (high-card / identity); **never in X** |
| `create_ts` | Join / audit only; not a model feature |
| `mint`, `t0_ts`, `t0`, `feature_set_version` | Keys / meta |
| `solana_utils.latest_balances` derived | L2 snapshot |
| `migrated_pre_t0` | DROP_FROM_X — pumpswap≤T0 ≠ curve graduation |
| ATH / post-T0 withdraw / migration after T0 | Look-ahead |

Regex gate (same as `post_q5_sets.LEAK_COL_RE`):  
`/(max_mc|hit_|label_|after_t0|primary_ready)/i`

Allowed in **joined CSV** but stripped before train: `creator_pubkey`, `create_ts`, label frame cols.

---

## B) Per-pack ≤T0 rules

### Q5a (`dune_q5a_features.csv`)
1. Source trades: `block_time ≤ t0_ts`.
2. Windows (30s / 60s / 5m / 15m / first5s / first10s / first5 buys) end at **T0**, not wall clock.
3. Shares (`*_share`, `*_pct_proxy`) ∈ [0, 1] when non-null.
4. `progress_curve_proxy` clipped [0, 2].
5. `migrated_pre_t0`: **DROP_FROM_X** (pumpswap≤T0 ≠ bonding graduation; observed rate ~0.68). May stay in CSV for audit; never in train sets.
6. Holder proxies are **trade-net**, not SPL holders — model card caveat.
7. No label columns in file.

### Q5b (`dune_q5b_features.csv`)
1. Create row: `create_ts ≤ t0_ts` (strict `<` for *other* mints in prior counts).
2. `age_s` ≥ 0 when non-null; document null-create rate.
3. Offline priors (`add_cohort_creator_priors`): only creates with `create_ts < this.t0`; exclude self mint; **underestimates** true priors (out-of-cohort) — document L0-under.
4. `creator_pubkey` may sit in CSV for join; **out of every FEATURE_SET**.
5. No label columns.

---

## C) Merge protocol (expand ← Q5a ← Q5b)

**Target:** `data/samples/features_dune_p0_q5_expand_v2.csv`

| Step | Rule |
|------|------|
| 1 | Left-join on **`mint`**; keep expand row count unchanged. |
| 2 | Carry pack `t0_ts` as `_t0_pack`; drop pack cols where `\|t0_pack − t0_expand\| > 2s` (set NaN). Prefer dual-key `mint+t0_ts` when duplicates appear. |
| 3 | `n(q5*) ≤ n(expand)`; coverage report `frac`; **complete** iff `frac ≥ 0.995` before `--require-complete` WF. |
| 4 | Labels stay in **separate** frame (`labels_dune_expand_v2.csv`); never auto-merge into X. |
| 5 | Train X = `FEATURE_SETS[set_name]` only — asserts `creator_pubkey`/`create_ts`/leak regex absent. |
| 6 | Numeric NaN → 0 only **after** logging missingness by column; do not invent for audit CSV. |
| 7 | Secrets scan on outputs; no key material in meta JSON. |

Sets (SolModelos): `buy60` \| `buy60+q5a` \| `q5a_only` \| `+q5b` \| `full`.

Label slot: prefer `hit_10x_30d` when present; else proxy `hit_200k` (mark **not PRIMARY**).

---

## D) Executable gates

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -m verification.q5_merge
# or
PYTHONPATH=src .venv/bin/python -c "from verification.q5_merge import run_q5_qa; print(run_q5_qa())"
```

Writes `data/samples/qa_q5_merge_protocol_report.json`.

| ID | Gate | Fail if |
|----|------|---------|
| Q5.leak.cols | deny-list ∩ feature CSVs / train sets | any hit |
| Q5.creator.out | `creator_pubkey` ∉ all FEATURE_SETS | present |
| Q5.create_ts.out | `create_ts` ∉ FEATURE_SETS | present |
| Q5.t0.match | expand vs pack t0 ≤2s on matched mints | mismatches kept filled |
| Q5.q5b.create_leq_t0 | `create_ts ≤ t0` | any row |
| Q5.q5b.age_nonneg | `age_s ≥ 0` | any row |
| Q5.q5a.shares_01 | share cols in [0,1] | out of range |
| Q5.q5a.progress_clip | progress in [0,2] | out of range |
| Q5.q5a.migrated_rate | `mean(migrated_pre_t0) ≤ 0.01` soft | **warn/fail-soft** if ≫1% |
| Q5.merge.cardinality | left join preserves expand n | n changes |
| Q5.coverage | report frac; block `--require-complete` if <0.995 | train without OK |
| Q5.secrets | no API keys in sample paths | hits |

---

## E) Smoke / batch (ingestion)

- [ ] Q5a smoke 10: finite shares in [0,1]
- [ ] Q5b smoke 10: `age_s ≥ 0` for matched creates
- [ ] Batch shrink on `QUERY_STATE_FAILED` (100 worked; 300 failed)
- [ ] Partial batches resumable; do not treat incomplete Q5 as ready for full set WF

---

## F) Status note (partial pull, 2026-09-30)

Observed on incomplete files (do **not** train full sets yet):

- Q5a coverage ~17%; Q5b ~98% (see `wf_post_q5_sets_manifest.json`)
- `migrated_pre_t0` mean **~0.68** → dropped from X (`DROP_FROM_X`); redefine later if needed
- `progress_curve_proxy` median ~1.0 (catalog expected ~0.1–0.3) → sanity review
- t0 match expand↔Q5a: 0 mismatches on overlapping mints (good)

BOSS merges + WF when Q5 closes and these gates pass (or columns dropped).
