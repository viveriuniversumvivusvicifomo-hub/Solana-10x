# Dune cohort v1 — Q1+Q2 filter & labels

**definition_version:** `dune_cohort_v1`
**Generated:** from `data/samples/dune_pump_mc200k_30d.csv` (Q1) + `dune_pump_t0_labels_30d.csv` (Q2)
**Script:** `src/labeling/build_dune_cohort_v1.py` (idempotent)
**Helius streams:** OFF · **No invented facts** — counts from CSVs only.

## Frozen rules applied

| Rule | Value |
|------|-------|
| Capture band | MC USD ∈ [8000, 20000] (T0 from Q2) |
| PRIMARY label | `hit_10x_30d` (hint col `label_primary_hint` ← Q2 `hit_10x_from_band_top_hint`) |
| Positive | `hit_200k==1` ⇒ `max_mc_after_t0 >= 200000` after filters |
| Mint preference | `mint.endswith("pump")` |
| Absurd MC | drop if `max_mc_after_t0 > 1e10` ($10B) |
| Tiny vol vs MC | if mint ∈ Q1: drop if `volume_usd_30d / max_mc_usd_30d < 1e-4` OR Q1 `max_mc > 1e10` |
| Right-censor | `followup_days_available` vs window end `2026-09-29T23:59:59+00:00`; `primary_ready` iff ≥ **7** days |
| Feature store | `max_mc_*` / `hit_*` / labels **never** merged into feature store files |

## Counts

| Stage | N |
|-------|--:|
| Raw Q1 | 6339 |
| Raw Q2 | 136856 |
| After filters (cohort all) | 115409 |
| Positives (`hit_200k==1`) | 11514 |
| Negatives (`hit_200k==0`) | 103895 |
| PRIMARY-ready (all) | 83089 |
| Positives PRIMARY-ready | 8767 |
| Negatives PRIMARY-ready | 74322 |

### Filter steps (Q2 path)

- **raw_q2**: in=136856 → out=136856 (dropped 0)
- **prefer_mint_endswith_pump**: in=136856 → out=115411 (dropped 21445)
- **drop_absurd_max_mc_after_t0**: in=115411 → out=115411 (dropped 0)
- **drop_q1_outlier_when_joined**: in=115411 → out=115409 (dropped 2)

Negatives sampling: `{'applied': False, 'reason': 'estimated CSV 19827312 bytes < 52428800', 'n_written': 103895}` — full negatives kept (CSV under 50MB).

## Outputs

| File | Rows (written) |
|------|---------------:|
| `data/samples/dune_cohort_v1_positives.csv` | 11514 |
| `data/samples/dune_cohort_v1_negatives.csv` | 103895 |
| `data/samples/dune_cohort_v1_labels.csv` | 115409 |
| `data/samples/dune_cohort_v1_meta.json` | — |

Labels columns include filter flags, `followup_days_available`, `primary_ready`, `label_primary_hint`.

## Next: Q3 (MC at T0)

Draft SQL: `cycle0/dune-q3-mc-at-t0.sql` — per-trade non-WSOL price × 1e9 at first band hit.
Prefer joining `primary_ready` mints if the free-plan 30d scan times out.
