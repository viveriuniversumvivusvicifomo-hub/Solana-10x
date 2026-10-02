# Post-Q5 walk-forward — PRIMARY `hit_10x_30d`

**Date:** 2026-10-01 09:40 CEST (Europe/Madrid)  
**Run mode:** `--train --allow-partial` (same as prior hit_200k run; Q5a ~95.6%)  
**Label:** **PRIMARY** `hit_10x_30d` (`labels.hit_10x_30d.mc_t0.v1`) — auto-picked by `resolve_label_column`  
**Model:** HistGradientBoosting (expanding 5-fold anti look-ahead WF)  
**Dune credits:** none (local labels + prior joined features only)

## Definition (frozen)

```
hit_10x_30d = 1  iff  max_mc_after_t0 >= 10.0 * mc_usd_t0  (and mc_usd_t0 > 0)
max_multiple_30d = max_mc_after_t0 / mc_usd_t0
```

- **Rationale:** constant pump supply ⇒ MC multiple ≈ price multiple from T0.
- **Not** `hit_200k` (that was ≈10× from band top $20k).
- **Sources:** `mc_usd_t0` from `features_dune_p0_q5_expand_v2.csv`; `max_mc_after_t0` from expand labels; `followup_days_available` / `primary_ready` joined from cohort for documentation.
- **Meta:** `data/samples/labels_hit_10x_30d_meta.json`
- **Labels file:** `data/samples/labels_dune_expand_v2.csv` (backup: `labels_dune_expand_v2.prev_hit200k_only.csv`)

## Base rate & censor

| Quantity | Value |
|----------|-------|
| n (expand-v2) | 82089 |
| `hit_10x_30d` positives | 11040 (**13.45%**) |
| `hit_200k` positives (kept) | 8713 (10.61%) |
| Crosstab: hit_10x ∧ ¬hit_200k | 2327 (extra PRIMARY hits below $200k) |
| Crosstab: ¬hit_10x ∧ hit_200k | 0 (all $200k hits are ≥10× from T0 MC here) |
| followup ≥7d | 100% (cohort `primary_ready`) |
| followup ≥14d | 55783 (**67.95%**) |
| followup ≥30d | 518 (**0.63%**) |
| followup median / p90 | 19.4d / 28.4d |

### Right-censor caveat (important)

Cohort gate required ≥7d post-T0 followup; **only ~0.6% of rows have ≥30d** of observation to the Q2 window end. The label uses **max MC observed in the available Q2 post-T0 window** (up to ~30d / data end), **not** a fully realized 30d mark-to-market. **False negatives are possible** for short followup (token may 10× after our last observation). **Do not invent prices.** Interpret AUC/AP as ranking under this censored outcome.

## Artifacts

| Artifact | Path |
|----------|------|
| Labels (+ PRIMARY) | `data/samples/labels_dune_expand_v2.csv` |
| Label meta | `data/samples/labels_hit_10x_30d_meta.json` |
| Backup (hit_200k-only) | `data/samples/labels_dune_expand_v2.prev_hit200k_only.csv` |
| Joined features | `data/samples/features_dune_p0_q5_expand_v2.csv` |
| Manifest | `data/samples/wf_post_q5_sets_manifest.json` (`is_primary: true`) |
| Report JSON/MD | `data/samples/wf_post_q5_report.{json,md}` |
| OOS preds | `data/samples/wf_post_q5_oos_predictions.csv` |
| followup≥14 subset metrics | `data/samples/wf_post_q5_followup14_subset_metrics.json` |

**DROP_FROM_X:** `creator_pubkey`, `create_ts`, `migrated_pre_t0` (and labels / `max_mc_*` / `hit_*` / `max_multiple_30d`).

## OOS pooled metrics (PRIMARY `hit_10x_30d`)

OOS n ≈ 49254 (expanding folds; earliest slice train-only). Pos rate in OOS ≈ 14.13%.

| set | n_feat | AUC | AP | ΔAUC vs buy60 | ΔAP vs buy60 | P@top1% | P@top5% |
|-----|--------|-----|----|---------------|--------------|---------|---------|
| `buy60` | 1 | 0.9052 | 0.8557 | — | — | 1.000 | 1.000 |
| `buy60+q5a` | 40 | 0.9292 | 0.8706 | **+0.0240** | **+0.0150** | 1.000 | 1.000 |
| `q5a_only` | 39 | 0.9192 | 0.8580 | +0.0140 | +0.0023 | 1.000 | 1.000 |
| `+q5b` (buy60+q5a+q5b) | 51 | **0.9305** | 0.8716 | **+0.0253** | **+0.0159** | 1.000 | 1.000 |
| `full` (expand18+q5a+q5b) | 68 | 0.9304 | **0.8723** | +0.0252 | +0.0166 | 1.000 | 1.000 |

Fold AUC means track pooled (`buy60` ~0.906 → `+q5b` ~0.931 across 5 folds).

## Comparison vs previous `hit_200k` proxy run

Prior numbers from `cycle0/wf-post-q5-summary.md` (same flags / model).

| set | AUC hit_200k → PRIMARY | AP hit_200k → PRIMARY | ΔAUC lift vs buy60 (200k → PRIMARY) |
|-----|------------------------|----------------------|-------------------------------------|
| `buy60` | 0.9685 → **0.9052** | 0.9408 → **0.8557** | — |
| `buy60+q5a` | 0.9756 → 0.9292 | 0.9488 → 0.8706 | +0.007 → **+0.024** |
| `q5a_only` | 0.9715 → 0.9192 | 0.9375 → 0.8580 | +0.003 → +0.014 |
| `+q5b` | 0.9771 → **0.9305** | 0.9494 → 0.8716 | +0.009 → **+0.025** |
| `full` | 0.9769 → 0.9304 | 0.9496 → 0.8723 | +0.008 → +0.025 |

**Takeaways:**

1. Absolute AUC/AP are **lower** on PRIMARY than on `hit_200k` (harder / less entangled with raw MC band outcome).
2. **Relative Q5 lift vs buy60 is larger** on PRIMARY (~+0.024–0.025 AUC) than on the proxy (~+0.007–0.009) — Q5 packs matter more when the label is true 10×-from-T0.
3. Ranking of sets is unchanged: **`+q5b` ≈ `full` > `buy60+q5a` > `q5a_only` > `buy60`**.
4. P@top1%/5% still saturates at 1.0 (not discriminative among tops on this cohort).

## Secondary: OOS subset `followup_days_available >= 14`

Stricter observation window (still right-censored vs full 30d). OOS n=22948; pos rate ≈ 14.98%.

| set | AUC | AP | ΔAUC vs buy60 | P@top1% | P@top5% |
|-----|-----|----|---------------|---------|---------|
| `buy60` | 0.9123 | 0.8735 | — | 1.000 | 1.000 |
| `buy60+q5a` | 0.9315 | 0.8858 | +0.0192 | 1.000 | 1.000 |
| `q5a_only` | 0.9214 | 0.8721 | +0.0091 | 1.000 | 1.000 |
| `+q5b` | 0.9317 | 0.8864 | +0.0194 | 1.000 | 1.000 |
| `full` | **0.9322** | **0.8875** | +0.0199 | 1.000 | 1.000 |

Same qualitative ranking; lift vs buy60 remains material (~+0.02 AUC). Full 30d-realized subset is too small (n=518 / 0.63%) for stable WF — not reported as primary.

## Does Q5 lift on PRIMARY?

**Yes — more clearly than on `hit_200k`:**

1. buy60 remains strong (AUC 0.905) but no longer near-ceiling.
2. Q5a on top of buy60: **~+0.024 AUC / +0.015 AP**.
3. Q5b adds a small further bump; best AUC set is `+q5b` (full ties on AP).
4. expand-flow extras beyond buy60 add little once Q5a/b are in (`full` ≈ `+q5b`).

## Recommendation

1. **Treat `hit_10x_30d` as the production label** going forward; keep `hit_200k` only for comparison / legacy.
2. **Production candidate: `+q5b`** (or `buy60+q5a` if Q5b cost matters). Do not chase `full`.
3. Document censor in any external write-up: metrics are under **observed max-MC window**, not guaranteed 30d realization; FN risk for short followup.
4. Optional later: re-score when more mints reach ≥30d followup, or train with explicit followup-aware weighting / IPC — not blocking.
5. Next useful dig: feature importance / PD on Q5a sniper-concentration and Q5b creator priors under PRIMARY (confirm non-redundant vs buy_vol).
