# WF post-Q5 pipeline (SolModelos)

**Date:** 2026-09-30 (CEST)  
**Status:** scaffold ready — **no train on incomplete Q5** (BOSS merges+WF when Q5 closes).

## Inputs
| Artifact | Path |
|----------|------|
| Expand features | `data/samples/features_dune_p0_flow_expand_v2.csv` |
| Labels | `data/samples/labels_dune_expand_v2.csv` |
| Q5a (partial→full) | `data/samples/dune_q5a_features.csv` |
| Q5b (partial→full) | `data/samples/dune_q5b_features.csv` |

## Feature sets
Defined in `src/features/post_q5_sets.py`:

| Set | Contents |
|-----|----------|
| `buy60` | `buy_vol_usd_60s` |
| `buy60+q5a` | buy60 + Q5a numerics |
| `q5a_only` | Q5a numerics |
| `+q5b` | buy60 + Q5a + Q5b numerics |
| `full` | expand flow (18) + Q5a + Q5b |

**Banned from X:** `creator_pubkey`, `create_ts`, `migrated_pre_t0` (pumpswap≤T0 ≠ graduation; rate~0.68), labels / `max_mc_*` / `hit_*`.

## Label slot
`resolve_label_column`: prefers **`hit_10x_30d`** when present; else proxy **`hit_200k`** (flagged non-PRIMARY).

## Metrics
AUC, AP, **precision @ top 1% / 5%** (plus expand-v2 helpers).

## Commands
```bash
# Manifest + coverage (default; safe while Q5 downloads)
.venv/bin/python -m models.walk_forward_post_q5 --dry-run

# After Q5 complete (BOSS): write joined CSV + multi-set WF
.venv/bin/python -m models.walk_forward_post_q5 --train --require-complete
```

## Outputs
| Artifact | Path |
|----------|------|
| Sets manifest | `data/samples/wf_post_q5_sets_manifest.json` |
| Joined features (on train) | `data/samples/features_dune_p0_q5_expand_v2.csv` |
| Report | `data/samples/wf_post_q5_report.{json,md}` |
| OOS preds | `data/samples/wf_post_q5_oos_predictions.csv` |

## Merge protocol (for SolQA)
1. Left-join Q5a/Q5b → expand on **`mint`** (1:1).  
2. If pack `t0_ts` present: null pack features when `|t0_expand − t0_pack| > 2s`.  
3. Labels merged separately; never into feature file columns used as X.  
4. Gate train for Q5 sets until coverage ≥ **99.5%** of expand n.
