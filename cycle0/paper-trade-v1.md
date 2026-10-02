# Paper-trading v1 — OOS simulación (PRIMARY `hit_10x_30d`)

**Fecha:** 2026-10-01T10:14:13+02:00 (Europe/Madrid)  
**Modelo candidato:** `+q5b` (buy60+Q5a+Q5b) vs baseline `buy60`  
**Label:** `hit_10x_30d` · OOS base rate ≈ 14.13%  
**Anti look-ahead:** umbrales/capacidad sin mirar labels OOS; train cuantiles solo en train.

## Reglas v1 (decisiones)

| Pieza | Regla |
|-------|-------|
| Entrada A | score >= quantile(train_scores, 1-top_frac); threshold from TRAIN only (note: buy60 scores pile near 1.0 → top1%≈top5% via ties) |
| Entrada B | within each OOS fold, take top-k by model score (fixed capacity; no label peek; ties broken by earlier t0) |
| Sizing | equal weight / fixed 1R notional unit per trade |
| Salida / horizonte | hold until hit_10x OR end of available followup (right-censored) |
| PnL principal (TP10) | `R = clip(mc_multiple, 0, 10.0) - 1 - cost_rt  (take-profit at 10×; do not assume catching the peak)` |
| PnL binario | `+9.0R on hit, -1.0R on miss, minus cost_rt` |
| PnL oracle20 (diag) | `R = clip(mc_multiple, 0, 20.0) - 1 - cost_rt (diagnostic upper bound only)` |
| Costes RT default | `1.5%` (sens 1.0%, 1.5%, 2.0%) |
| Top-fracs (A) | 5%, 1% |
| Top-K / fold (B) | 50, 100, 200, 500, 1000, 1400 |

### Censor / followup

Label/PnL use max MC in observed post-T0 window (cohort ≥7d gate; ~0.6% have ≥30d). False negatives possible for short followup. Do not invent prices.

Esto es un **proxy de investigación**, no equity real: sin fills, MEV ni impacto de pool.

## Folds (expanding WF = post-Q5)

| fold | train_n | test_n | train_t0_max | test_t0_min |
|------|---------|--------|--------------|-------------|
| 1 | 32835 | 9851 | `2026-09-08T10:54:47+00:00` | `2026-09-08T10:55:31+00:00` |
| 2 | 42686 | 9850 | `2026-09-10T23:37:05+00:00` | `2026-09-10T23:37:06+00:00` |
| 3 | 52536 | 9851 | `2026-09-14T08:44:38+00:00` | `2026-09-14T08:47:20+00:00` |
| 4 | 62387 | 9851 | `2026-09-17T22:45:58+00:00` | `2026-09-17T22:46:00+00:00` |
| 5 | 72238 | 9851 | `2026-09-20T17:48:12+00:00` | `2026-09-20T17:48:41+00:00` |

## Resultados OOS — Entrada B preferida (top-K / fold)

Top-K evita el colapso por empates de score en `buy60` (scores ~1.0).

| strategy | n | hit rate | lift | cum R TP10 | mean R TP10 | max DD TP10 | cum R bin | max DD bin | trades/day |
|----------|---|----------|------|------------|-------------|-------------|-----------|------------|------------|
| `+q5b_topK_50` | 250 | 100.00% | 7.08 | 2246.2 | 8.985 | 0.0 | 2246.2 | 0.0 | 17.2 |
| `+q5b_topK_100` | 500 | 100.00% | 7.08 | 4492.5 | 8.985 | 0.0 | 4492.5 | 0.0 | 34.4 |
| `+q5b_topK_200` | 1000 | 100.00% | 7.08 | 8985.0 | 8.985 | 0.0 | 8985.0 | 0.0 | 68.8 |
| `+q5b_topK_500` | 2500 | 100.00% | 7.08 | 22462.5 | 8.985 | 0.0 | 22462.5 | 0.0 | 172.0 |
| `+q5b_topK_1000` | 5000 | 97.10% | 6.87 | 44412.6 | 8.883 | 0.0 | 43475.0 | -3.0 | 343.8 |
| `+q5b_topK_1400` | 7000 | 79.81% | 5.65 | 56864.6 | 8.124 | -0.0 | 48765.0 | -7.1 | 481.3 |
| `buy60_topK_50` | 250 | 100.00% | 7.08 | 2246.2 | 8.985 | 0.0 | 2246.2 | 0.0 | 19.7 |
| `buy60_topK_100` | 500 | 100.00% | 7.08 | 4492.5 | 8.985 | 0.0 | 4492.5 | 0.0 | 37.2 |
| `buy60_topK_200` | 1000 | 100.00% | 7.08 | 8985.0 | 8.985 | 0.0 | 8985.0 | 0.0 | 69.5 |
| `buy60_topK_500` | 2500 | 100.00% | 7.08 | 22462.5 | 8.985 | 0.0 | 22462.5 | 0.0 | 172.1 |
| `buy60_topK_1000` | 5000 | 97.02% | 6.87 | 44430.3 | 8.886 | 0.0 | 43435.0 | -3.0 | 343.8 |
| `buy60_topK_1400` | 7000 | 79.16% | 5.60 | 56470.2 | 8.067 | -0.0 | 48305.0 | -8.1 | 481.3 |

## Resultados OOS — Entrada A (train quantile)

| strategy | n | hit rate | lift | cum R TP10 | mean R TP10 | max DD TP10 | cum R bin | max DD bin | trades/day |
|----------|---|----------|------|------------|-------------|-------------|-----------|------------|------------|
| `+q5b_trainQ_top5%` | 2325 | 100.00% | 7.08 | 20890.1 | 8.985 | 0.0 | 20890.1 | 0.0 | 160.0 |
| `+q5b_trainQ_top1%` | 708 | 100.00% | 7.08 | 6361.4 | 8.985 | 0.0 | 6361.4 | 0.0 | 48.7 |
| `buy60_trainQ_top5%` | 2759 | 100.00% | 7.08 | 24789.6 | 8.985 | 0.0 | 24789.6 | 0.0 | 189.9 |
| `buy60_trainQ_top1%` | 2759 | 100.00% | 7.08 | 24789.6 | 8.985 | 0.0 | 24789.6 | 0.0 | 189.9 |

### Trades por fold (todas las strategies)

- `+q5b_trainQ_top5%`: f1=695, f2=651, f3=280, f4=396, f5=303
- `+q5b_trainQ_top1%`: f1=110, f2=323, f3=91, f4=127, f5=57
- `+q5b_topK_50`: f1=50, f2=50, f3=50, f4=50, f5=50
- `+q5b_topK_100`: f1=100, f2=100, f3=100, f4=100, f5=100
- `+q5b_topK_200`: f1=200, f2=200, f3=200, f4=200, f5=200
- `+q5b_topK_500`: f1=500, f2=500, f3=500, f4=500, f5=500
- `+q5b_topK_1000`: f1=1000, f2=1000, f3=1000, f4=1000, f5=1000
- `+q5b_topK_1400`: f1=1400, f2=1400, f3=1400, f4=1400, f5=1400
- `buy60_trainQ_top5%`: f1=926, f2=847, f3=466, f4=314, f5=206
- `buy60_trainQ_top1%`: f1=926, f2=847, f3=466, f4=314, f5=206
- `buy60_topK_50`: f1=50, f2=50, f3=50, f4=50, f5=50
- `buy60_topK_100`: f1=100, f2=100, f3=100, f4=100, f5=100
- `buy60_topK_200`: f1=200, f2=200, f3=200, f4=200, f5=200
- `buy60_topK_500`: f1=500, f2=500, f3=500, f4=500, f5=500
- `buy60_topK_1000`: f1=1000, f2=1000, f3=1000, f4=1000, f5=1000
- `buy60_topK_1400`: f1=1400, f2=1400, f3=1400, f4=1400, f5=1400

## Comparación `+q5b` vs `buy60`

| rule | hit q5b | hit buy60 | Δ hit | Δ cum R TP10 | Δ cum R bin | n q5b | n buy60 |
|------|---------|-----------|-------|--------------|-------------|-------|---------|
| trainQ_top5% | 100.00% | 100.00% | 0.00% | -3899.5 | -3899.5 | 2325 | 2759 |
| trainQ_top1% | 100.00% | 100.00% | 0.00% | -18428.2 | -18428.2 | 708 | 2759 |
| topK_50 | 100.00% | 100.00% | 0.00% | 0.0 | 0.0 | 250 | 250 |
| topK_100 | 100.00% | 100.00% | 0.00% | 0.0 | 0.0 | 500 | 500 |
| topK_200 | 100.00% | 100.00% | 0.00% | 0.0 | 0.0 | 1000 | 1000 |
| topK_500 | 100.00% | 100.00% | 0.00% | 0.0 | 0.0 | 2500 | 2500 |
| topK_1000 | 97.10% | 97.02% | 0.08% | -17.7 | 40.0 | 5000 | 5000 |
| topK_1400 | 79.81% | 79.16% | 0.66% | 394.4 | 460.0 | 7000 | 7000 |

## vs random (mismo n por fold, 5 seeds)

| strategy | model hit | random hit | model cum R TP10 | random cum R TP10 |
|----------|-----------|------------|------------------|-------------------|
| `+q5b_trainQ_top5%` | 100.00% | 14.65% | 20890.1 | 5198.4 |
| `+q5b_trainQ_top1%` | 100.00% | 14.32% | 6361.4 | 1568.9 |
| `+q5b_topK_50` | 100.00% | 14.48% | 2246.2 | 550.7 |
| `+q5b_topK_100` | 100.00% | 14.04% | 4492.5 | 1084.8 |
| `+q5b_topK_200` | 100.00% | 14.74% | 8985.0 | 2267.8 |
| `+q5b_topK_500` | 100.00% | 14.04% | 22462.5 | 5427.7 |
| `+q5b_topK_1000` | 97.10% | 14.62% | 44412.6 | 11214.8 |
| `+q5b_topK_1400` | 79.81% | 14.02% | 56864.6 | 15300.4 |
| `buy60_trainQ_top5%` | 100.00% | 14.39% | 24789.6 | 6115.8 |
| `buy60_trainQ_top1%` | 100.00% | 14.39% | 24789.6 | 6115.8 |
| `buy60_topK_50` | 100.00% | 14.48% | 2246.2 | 550.7 |
| `buy60_topK_100` | 100.00% | 14.04% | 4492.5 | 1084.8 |
| `buy60_topK_200` | 100.00% | 14.74% | 8985.0 | 2267.8 |
| `buy60_topK_500` | 100.00% | 14.04% | 22462.5 | 5427.7 |
| `buy60_topK_1000` | 97.02% | 14.62% | 44430.3 | 11214.8 |
| `buy60_topK_1400` | 79.16% | 14.02% | 56470.2 | 15300.4 |

## Sensibilidad a costes (cum R TP10)

| strategy | 1.0% | 1.5% | 2.0% |
|----------|------|------|------|
| `+q5b_topK_50` | 2247.5 | 2246.2 | 2245.0 |
| `+q5b_topK_100` | 4495.0 | 4492.5 | 4490.0 |
| `+q5b_topK_200` | 8990.0 | 8985.0 | 8980.0 |
| `+q5b_topK_500` | 22475.0 | 22462.5 | 22450.0 |
| `+q5b_topK_1000` | 44437.6 | 44412.6 | 44387.6 |
| `+q5b_topK_1400` | 56899.6 | 56864.6 | 56829.6 |
| `buy60_topK_50` | 2247.5 | 2246.2 | 2245.0 |
| `buy60_topK_100` | 4495.0 | 4492.5 | 4490.0 |
| `buy60_topK_200` | 8990.0 | 8985.0 | 8980.0 |
| `buy60_topK_500` | 22475.0 | 22462.5 | 22450.0 |
| `buy60_topK_1000` | 44455.3 | 44430.3 | 44405.3 |
| `buy60_topK_1400` | 56505.2 | 56470.2 | 56435.2 |

## Umbrales train (Entrada A) — `+q5b`

### top 5%

| fold | threshold | n_enter | enter_frac | hit_rate | n_unique_train_scores |
|------|-----------|---------|------------|----------|----------------------|
| 1 | 0.999471 | 695 | 7.06% | 100.00% | 27265 |
| 2 | 0.999584 | 651 | 6.61% | 100.00% | 33422 |
| 3 | 0.999779 | 280 | 2.84% | 100.00% | 44533 |
| 4 | 0.999734 | 396 | 4.02% | 100.00% | 52076 |
| 5 | 0.999800 | 303 | 3.08% | 100.00% | 59657 |

### top 1%

| fold | threshold | n_enter | enter_frac | hit_rate | n_unique_train_scores |
|------|-----------|---------|------------|----------|----------------------|
| 1 | 0.999490 | 110 | 1.12% | 100.00% | 27265 |
| 2 | 0.999588 | 323 | 3.28% | 100.00% | 33422 |
| 3 | 0.999788 | 91 | 0.92% | 100.00% | 44533 |
| 4 | 0.999754 | 127 | 1.29% | 100.00% | 52076 |
| 5 | 0.999807 | 57 | 0.58% | 100.00% | 59657 |


## Top-K hit rates por fold — `+q5b`

### K=50

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 50 | 100.00% | 0.999490 |
| 2 | 50 | 100.00% | 0.999597 |
| 3 | 50 | 100.00% | 0.999797 |
| 4 | 50 | 100.00% | 0.999757 |
| 5 | 50 | 100.00% | 0.999810 |

### K=100

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 100 | 100.00% | 0.999490 |
| 2 | 100 | 100.00% | 0.999588 |
| 3 | 100 | 100.00% | 0.999787 |
| 4 | 100 | 100.00% | 0.999756 |
| 5 | 100 | 100.00% | 0.999805 |

### K=200

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 200 | 100.00% | 0.999471 |
| 2 | 200 | 100.00% | 0.999588 |
| 3 | 200 | 100.00% | 0.999784 |
| 4 | 200 | 100.00% | 0.999744 |
| 5 | 200 | 100.00% | 0.999803 |

### K=500

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 500 | 100.00% | 0.999471 |
| 2 | 500 | 100.00% | 0.999584 |
| 3 | 500 | 100.00% | 0.999763 |
| 4 | 500 | 100.00% | 0.999724 |
| 5 | 500 | 100.00% | 0.999793 |

### K=1000

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 1000 | 100.00% | 0.997192 |
| 2 | 1000 | 100.00% | 0.999507 |
| 3 | 1000 | 97.40% | 0.810723 |
| 4 | 1000 | 96.20% | 0.806419 |
| 5 | 1000 | 91.90% | 0.774817 |

### K=1400

| fold | n | hit_rate | score_min_selected |
|------|---|----------|--------------------|
| 1 | 1400 | 82.29% | 0.540254 |
| 2 | 1400 | 91.64% | 0.660988 |
| 3 | 1400 | 75.21% | 0.519113 |
| 4 | 1400 | 76.36% | 0.532674 |
| 5 | 1400 | 73.57% | 0.414469 |

## Lectura rápida

### topK=100 (cola saturada)

- `+q5b`: **n=500**, hit **100.00%** (lift 7.08×), cum R TP10 **4492.5**, max DD TP10 **0.0**, trades/day ≈ 34.4.
- `buy60`: hit **100.00%**, cum R TP10 **4492.5**, max DD TP10 **0.0**.
- Random matched: hit ≈ 14.04%, cum R TP10 ≈ 1084.8.
- Δ(`+q5b`−`buy60`) hit=0.00%, Δ cum R TP10=0.0.

### topK=1400 (cerca tasa natural (~14%))

- `+q5b`: **n=7000**, hit **79.81%** (lift 5.65×), cum R TP10 **56864.6**, max DD TP10 **-0.0**, trades/day ≈ 481.3.
- `buy60`: hit **79.16%**, cum R TP10 **56470.2**, max DD TP10 **-0.0**.
- Random matched: hit ≈ 14.02%, cum R TP10 ≈ 15300.4.
- Δ(`+q5b`−`buy60`) hit=0.66%, Δ cum R TP10=394.4.

**Nota:** hasta ~K=500/fold la precisión OOS satura en 100% para ambos modelos (coherente con P@top5%=1.0 del WF). La diferenciación `+q5b` vs `buy60` aparece al profundizar la cola (K≈1000–1400). El valor de Q5 sigue siendo de ranking/AUC; en paper-trade ultra-selectivo ambos ya capturan casi solo hits.

## Artefactos

| Artifact | Path |
|----------|------|
| Script | `src/models/paper_trade_v1.py` |
| Trades CSV | `data/samples/paper_trade_v1_trades.csv` |
| Report JSON | `data/samples/paper_trade_v1_report.json` |
| Este MD | `cycle0/paper-trade-v1.md` |
| Features | `data/samples/features_dune_p0_q5_expand_v2.csv` |
| Labels | `data/samples/labels_dune_expand_v2.csv` |

## Cómo reproducir

```bash
cd /workspace/solana-10x
PYTHONPATH=src .venv/bin/python -m models.paper_trade_v1
PYTHONPATH=src .venv/bin/python -m models.paper_trade_v1 \
  --top-frac 0.05 --top-frac 0.01 --top-k 50 --top-k 100 --top-k 200 --cost-rt 0.015
```

## Limitaciones

1. Proxy ≠ P&L real (sin ejecución / slippage de pool / capacidad).
2. Right-censor: pocos mints con ≥30d followup; FN posibles.
3. TP10 asume que se puede salir a 10×; en la práctica el path importa.
4. `buy60` train-quantile colapsa por empates de score≈1; preferir top-K.
5. Sin embargo de horizonte 30d entre folds (span t0 corto); solo `train_t0 < test_t0`.
6. Oracle20 satura en la cola seleccionada — informativo, no operable.

