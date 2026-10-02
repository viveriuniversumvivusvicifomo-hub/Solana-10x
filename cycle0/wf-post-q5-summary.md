# Post-Q5 walk-forward + ablation summary

**Date:** 2026-10-01 (CEST / Europe/Madrid)  
**Run mode:** `--train --allow-partial` (Q5a ~95.6% OK per Sinck; ~3.3k missing)  
**Label:** `hit_200k` proxy — **NOT** PRIMARY `hit_10x_30d`  
**Model:** HistGradientBoosting (expanding 5-fold anti look-ahead WF)  
**Dune credits:** none spent this run (merge of local batches only)

## Artifacts

| Artifact | Path |
|----------|------|
| Joined features | `data/samples/features_dune_p0_q5_expand_v2.csv` (n=82089, 74 cols) |
| Manifest | `data/samples/wf_post_q5_sets_manifest.json` |
| Report JSON/MD | `data/samples/wf_post_q5_report.{json,md}` |
| OOS preds | `data/samples/wf_post_q5_oos_predictions.csv` |
| QA protocol | `data/samples/qa_q5_merge_protocol_report.json` |

## Coverage

| Pack | n unique | expand_n | frac | complete (≥0.995) |
|------|----------|----------|------|-------------------|
| Q5a | 78457 | 82089 | **0.9558** | no (soft; allowed) |
| Q5b | 82089 | 82089 | **1.0000** | yes |

- QA hard gates: **PASS** (`ok_hard=true`); soft fail only `coverage.complete_gate`.
- Left-join preserves expand n=82089; Q5a nulls ~4.4% of rows (imputed at train).
- **DROP_FROM_X:** `creator_pubkey`, `create_ts`, `migrated_pre_t0` (present in CSV for audit only).

## OOS pooled metrics (ablation vs `buy_vol_usd_60s`)

Pos rate `hit_200k` ≈ 10.6% (8713 / 82089).

| set | n_feat | AUC | AP | ΔAUC vs buy60 | ΔAP vs buy60 | P@top1% | P@top5% |
|-----|--------|-----|----|---------------|--------------|---------|---------|
| `buy60` | 1 | 0.9685 | 0.9408 | — | — | 1.000 | 0.999 |
| `buy60+q5a` | 40 | 0.9756 | 0.9488 | **+0.0071** | **+0.0080** | 1.000 | 1.000 |
| `q5a_only` | 39 | 0.9715 | 0.9375 | +0.0030 | −0.0034 | 1.000 | 1.000 |
| `+q5b` (buy60+q5a+q5b) | 51 | **0.9771** | 0.9494 | **+0.0086** | **+0.0086** | 1.000 | 1.000 |
| `full` (expand18+q5a+q5b) | 68 | 0.9769 | **0.9496** | +0.0084 | +0.0087 | 1.000 | 1.000 |

Fold AUC means track pooled (buy60 ~0.969 → +q5b ~0.977 across all 5 folds).

## Does Q5 lift?

**Yes, modestly but consistently** on the proxy label:

1. **buy60 is already very strong** on `hit_200k` (AUC 0.9685) — ceiling is high; absolute lift room is small.
2. **Q5a adds ~+0.007 AUC / +0.008 AP** on top of buy60; q5a_alone ≈ buy60 (slightly worse AP).
3. **Q5b adds a further small bump** (~+0.0015 AUC over buy60+q5a); best set by AUC is `+q5b`.
4. **`full` ≈ `+q5b`** — expand flow extras beyond buy60 do not help much once Q5a/b are in.
5. Precision@top1%/5% saturates near 1.0 for all sets on this proxy (not discriminative for ranking among tops).

## Caveats

- Proxy label ≠ PRIMARY `hit_10x_30d`; expect different ranking when primary freezes.
- Partial Q5a: missing mints get NaN→median impute; not inventing features.
- `progress_curve_proxy` / `migrated_pre_t0` quirks remain (latter out of X).
- Extremely high P@top may reflect label–feature entanglement of MC/volume with `hit_200k`.

## Next recommendation

1. **Prefer production candidate `+q5b` (or `buy60+q5a` if Q5b cost matters)** for interim modeling; do not chase `full`.
2. **Wire PRIMARY `hit_10x_30d`** and re-run the same WF/ablation — treat current numbers as proxy-only.
3. Optional: finish remaining ~3.6k Q5a mints later if cheap; not blocking given Sinck OK.
4. Dig into **feature importance / partial dependence** on Q5a sniper/concentration and Q5b creator priors to confirm non-redundant signal vs buy_vol.
