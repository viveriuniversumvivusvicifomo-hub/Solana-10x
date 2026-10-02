# Cycle0 — offline lite calib + dual dry-run (2026-10-02 CEST)

**Sinck YES:** offline calib lite from local features CSV (no Dune), then dry-run dual journal vs histgb@0.9.  
**Live daemon:** **NOT touched** (histgb thr stays 0.9 / `start_paper_thr09.sh`).

## 1. Features store

- `data/samples/features_dune_p0_q5_expand_v2.csv` (82 089 rows) + `labels_dune_expand_v2.csv`
- Label: **`hit_10x_30d`** (PRIMARY)
- Fold-5 TRAIN: n=72 238 · t0_max `2026-09-20 17:48:12+00:00` · TEST n=9 851

## 2. Calib (`lite_logistic_v0`)

Fit: sklearn `LogisticRegression` L2 C=1 `class_weight=balanced` on **φ(LITE_COLS)** fold-5 TRAIN only.

| | TRAIN | fold-5 TEST |
|--|------:|------------:|
| AUC | 0.911 | 0.919 |
| AP | 0.847 | 0.830 |
| score median | 0.177 | 0.173 |
| score p95 | 0.975 | 0.946 |

- **bias** = −4.340 · **temperature** = 1.0
- Dominant weight: `buy_vol_usd_60s` ≈ +3.69; sniper negative (−1.22); top1 +2.29; priors mild negative
- Alt Platt T/b on heuristic weights kept under `alt_heuristic_temperature_bias` (not active)

**Paths**

- `data/paper_live/models/lite_calibration.json` ← **real fit** (stub bak: `lite_calibration.json.bak_stub_20261002`)
- Report copy: `cycle0/artifacts/lite_calib_fold5_report.json`

### Thr suggestion (explore lane only)

| thr | role | fold-5 OOS n / prec |
|-----|------|---------------------|
| **0.85** | **`threshold_default`** (≈ trainQ top10%) | ~9–10% rate · high prec |
| 0.975 | trainQ top5% | ultra-select |
| 0.55 | volume/smoke explore | n=1481 · prec≈0.69 |

**Do not** change histgb live thr (0.9).

## 3. Accept sets vs histgb@0.9 (fold-5 TEST offline)

Spearman(histgb, lite) ≈ **0.65**. Artifact: `cycle0/artifacts/lite_vs_histgb_fold5_accept.json`

| set | n | prec |
|-----|--:|-----:|
| histgb ≥ 0.9 | 901 | 0.992 |
| lite ≥ 0.85 | 967 | 0.931 |
| **intersection** | **887** | 0.992 |
| lite@0.85 only | 80 | 0.25 |
| histgb only | 14 | 1.00 |
| lite ≥ 0.55 | 1481 | 0.693 |

→ lite@0.85 ≈ histgb@0.9 coverage with small exclusive tails; scores look **sane**.

## 4. Dry-run dual journal

```bash
PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 2 \
  --score-mode histgb_q5b --score-threshold 0.9 --enable-lite-lane \
  --score-threshold-lite 0.55 --enrich-via bitquery \
  --sample /tmp/pump_sample_q5_aligned.json \
  --q5-fixture data/samples/q5_live_fixture.json \
  --data-dir /tmp/paper_live_dual_dry3
```

| lane | result |
|------|--------|
| histgb@0.9 | **0** accepts — all 12 `skip_prior_not_train` (fixture prior_source=None) |
| lite@0.55 | **6** accepts → `paper_candidates_lite` (scores 0.60–0.74) |
| lite@0.85 (same fixture) | **0** accepts (max lite score 0.735) |

Summary JSON: `cycle0/artifacts/dual_dryrun_summary_20261002.json`

## 5. Status

| Item | State |
|------|-------|
| Offline lite calib (no Dune) | **DONE** |
| Dual dry-run journal | **DONE** (smoke; histgb gated by prior in fixture) |
| Live thr / daemon restart | **NOT done** (scores sane → leave alone) |
| Path A / Dune spend | **HELD** |
