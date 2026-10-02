# Sweep de umbrales de score — `histgb_q5b` / `hit_10x_30d`

**Fecha:** 2026-10-01 15:58 CEST  
**Universo:** OOS pooled del WF post-Q5, set `+q5b` (`buy60+q5a+q5b`).  
**Fuente principal:** `data/samples/wf_post_q5_oos_predictions.csv`; contraste con `cycle0/paper-trade-v1.md` y `data/samples/paper_trade_v1_report.json`.

## Resultado

OOS tiene **49.254 filas y 6.960 positivos (14,13%)**. Para umbral absoluto se cuenta `score >= threshold`; `precision = n_hits / n_entries`; recall se refiere a los 6.960 positivos OOS.

| Regla / score mínimo | n_entries | n_hits | precision | recall OOS |
|---|---:|---:|---:|---:|
| score >= 0.50 | 7.343 | 5.653 | 76,98% | 81,22% |
| score >= 0.70 | 5.878 | 5.331 | 90,69% | 76,59% |
| score >= 0.80 | 5.324 | 5.147 | 96,68% | 73,95% |
| score >= 0.85 | 5.158 | 5.089 | 98,66% | 73,12% |
| score >= 0.89 | 5.126 | 5.074 | 98,99% | 72,90% |
| score >= 0.95 | 5.088 | 5.055 | 99,35% | 72,63% |
| score >= 0.99 | 4.959 | 4.948 | 99,78% | 71,09% |
| score >= 0.999 | 4.458 | 4.457 | 99,98% | 64,04% |
| trainQ top1% (por fold, train-only) | 708 | 708 | 100,00% | 10,17% |
| trainQ top5% (por fold, train-only) | 2.325 | 2.325 | 100,00% | 33,41% |
| trainQ top10% (por fold, train-only) | 5.317 | 5.151 | 96,88% | 74,01% |

`trainQ top1%` y `top5%` son extraídos del paper-trade existente. `top10%` fue recalculado con el mismo código WF/paper-trade, sin mirar labels OOS para fijar thresholds y sin sobrescribir los artefactos canónicos. Sus thresholds TRAIN por fold fueron: **0,663657; 0,739587; 0,916849; 0,883095; 0,876455**, con entradas por fold **1.172 / 1.314 / 960 / 963 / 908** y hits **1.098 / 1.259 / 953 / 944 / 897**.

## Lectura / sweet spot

- **Operativo equilibrado:** `score >= 0.99`: **4.948 ganadores de 4.959 entradas**, sólo **11 misses**; conserva 71,09% de todos los positivos OOS.
- **Ultra-selectivo:** `score >= 0.999`: **4.457 ganadores / 4.458 entradas**, sólo **1 miss**; baja la cobertura a 64,04%.
- `score >= 0.95` añade 107 ganadores frente a 0,99, pero también 22 misses adicionales. `trainQ top10%` captura más ganadores (5.151), aunque con 166 misses; top1/top5 son perfectos en este OOS pero de baja capacidad.
- Recomendación: usar **0,99** como sweet spot de throughput/precisión; reservar **0,999** o trainQ top1% para modo sniper/capacidad estricta. Los resultados están right-censored según la ventana observada, como advierte el paper-trade.

## Artefactos consultados

- `cycle0/paper-trade-v1.md`
- `data/samples/paper_trade_v1_report.json`
- `data/samples/wf_post_q5_report.json`
- `data/samples/wf_post_q5_oos_predictions.csv`
- `data/paper_live/models/q5b_calibration.json`
