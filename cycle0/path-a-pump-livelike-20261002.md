STATUS: NO-GO quarantined — see cycle0/quarantine-q5b-pump-joblibs-20261002.md

# Path A — Pump live-like feature matrix + WF (workstreams 1+2) — 2026-10-02

**Status:** COMPLETE  
**Finished:** 2026-10-02 ~13:50 CEST (Europe/Madrid)  
**Constraints:** paper_live PID **121466** untouched · 0 Dune · Lite OFF · USD scale OFF · `q5b_last` / `q5b_calibration.json` **not** overwritten  
**Workstream 3 (residual-accept):** deferred — not done this run

## Why prior pilots failed (encoded)

From `path-a-mcband-feat-diag-20261002.md`: mcband usable n=467 / **34 pos** had **outlier POS geometry** vs live Path A captura:

| Feature | mcband POS med | live med | problem |
|---------|----------------|----------|---------|
| `unique_sellers_total` | ~400 | ~18–21 | HistGB ~34% importance; live≈NEG |
| `net_sol_curve` | ≪0 (~−108) | ~14–17 | dump / re-entry geometry |
| sell vols | huge (~12–22k) | ~0.7–2.3k | scale shift |
| `n_trades_pre_t0` | ~1000 | ~110 | mega-pre band |

**Scale-n alone: NO.** Need positives whose feature geometry resembles live MC-band T0.

## Live-like filter (workstream 1)

**Target distribution:** journal Path A scoreable with `q5a_curve_age_source=q5a_trades` (post curve/age restart). Snapshot in `cycle0/artifacts/pump_livelike_live_target_20261002.json` (n_used≈108 at final rebuild).

### Live medians (q5a_trades)

| Feature | p50 (live) |
|---------|------------|
| `buy_vol_usd_60s` | ~2340 |
| `unique_sellers_total` | 21 |
| `net_sol_curve` | ~14.1 |
| `sell_vol_usd_30s` | ~1005 |
| `sell_vol_usd_total` | ~2270 |
| `age_proxy_s` | ~33 |
| `progress_curve_proxy` | ~0.17 |
| `n_trades_pre_t0` | ~95–111 |

### HARD reject (killer outliers)

Documented in build script / meta:

- `unique_sellers_total` ≤ 100  
- `net_sol_curve` ≥ −20  
- `sell_vol_usd_30s` ≤ 15000  
- `sell_vol_usd_total` ≤ 25000  
- `n_trades_pre_t0` ∈ [5, 450]  
- `age_proxy_s` ≤ 3600  

### SOFT live bands (approx live p05–p95 widened)

- sellers ∈ [1, 90], net_sol ∈ [−5, 45], buy60 ∈ [20, 20k]  
- sell30 ≤ 12k, selltot ≤ 15k, n_trades ∈ [10, 350]  
- age_proxy ≤ 2000, progress ≤ 0.60, buyers ∈ [2, 180]  

**Recipe frozen:** T0 = first Pump trade MC∈[8k,20k]; label 10× from that T0; features ≤T0; **expand_create_proxy OFF**.

## Matrix build (workstream 2)

Scripts:

- `scripts/build_pump_path_a_livelike.py`  
- `scripts/archive/train_q5b_pump_livelike_wf.py` (ARCHIVED; use `scripts/train_q5b_path_a_candidate_wf.py`)  

Caches reused: `pump_pilot500_trades_*`, `pump_mcband_trades_extra_*`, `pump_mcband_scale_trades_*`, plus new `pump_livelike_trades_20261002/` (~221 files).  
HTTP this session: **~1880** Pump frontend GETs (0×429); stopped near budget (not full 82k). Dune API: **0**.

| Slice | n | pos | note |
|-------|---|-----|------|
| Full matrix rows | (see meta) | — | all universe with/without cache |
| Reconstructable | 748 | — | MC-band T0 found |
| Soft livelike usable | **332** | **38** | primary train |
| Hard-ok usable | **444** | **55** | fallback / secondary |
| Mid-live-like pos (sellers 8–70 ∧ buy60 400–12k ∧ net −5…40 ∧ ntr 30–350) | — | **7** | still scarce |

**Coverage:** usable soft 332 / hard 444 — meets min≥400 on hard; soft below 400; target≥800 **not** reached under HTTP cap (abort toward 82k).

### Geometry: train POS vs live (soft slice)

| Feature | live med | soft POS med | soft NEG med |
|---------|----------|--------------|--------------|
| `unique_sellers_total` | 21 | ~4–5 | ~3 |
| `net_sol_curve` | ~14 | ~0.4–0.8 | ~2 |
| `buy_vol_usd_60s` | ~2340 | ~135–200 | ~480 |
| `sell_vol_usd_30s` | ~1000 | ~80 | ~70 |
| `n_trades_pre_t0` | ~95–111 | ~40–55 | ~31 |

**Killer outliers removed**, but surviving POS remain **quieter** than live mid-activity captura. Mid-live-like 10× positives are rare in expand+Pump-cache (~7).

## WF + live rescore

### Primary: `q5b_pump_livelike_20261002.joblib` (soft n=332 / 38 pos)

| Metric | livelike | q5b_last (same journal slice) |
|--------|----------|-------------------------------|
| OOS AUC | 0.75 | (baseline on OOS fold; see metrics JSON) |
| OOS AP | 0.41 | — |
| OOS frac≥0.9 | 0.0 | — |
| OOS max | 0.49 | — |
| Live n | 500 | 500 |
| Live median | **0.036** | **0.171** |
| Live max | **0.919** | 0.731 |
| Live frac≥0.9 | **0.006** | 0.000 |
| lift_max | +0.188 | — |
| lift_median | **−0.134** | — |
| lift_frac≥0.9 | +0.006 | — |

### Secondary: `q5b_pump_livelike_hard_20261002.joblib` (hard n=444 / 55 pos)

- OOS AUC ≈ 0.88, AP ≈ 0.67, OOS frac≥0.9 ≈ 0.056, OOS max ≈ 0.98  
- Live max ≈ 0.926 vs last 0.731; live median ≈ 0.050 vs 0.171; live frac≥0.9 ≈ 0.002  

## GO / NO-GO

| Gate | Result | Reason |
|------|--------|--------|
| Formal (live **max** ∧ **frac≥0.9** ↑ vs q5b_last, OOS not absurd) | **GO** | max 0.919>0.731; frac 0.006>0.0; OOS AUC 0.75 |
| **Paper swap / operativa** | **NO-GO** | live **median mass collapsed** (0.036≪0.171); POS still not live-like mid-activity; only 7 mid-live pos; thr 0.9 still almost never fires |

**Keep paper on `q5b_last` (PID 121466).** Do not swap to livelike.

## Artifacts

| Path | Role |
|------|------|
| `data/samples/features_pump_path_a_livelike_20261002.csv` | Full matrix |
| `data/samples/pump_livelike_usable_soft_20261002.csv` | Soft usable (primary) |
| `data/samples/pump_livelike_usable_hard_20261002.csv` | Hard usable |
| `data/samples/pump_livelike_usable_20261002.csv` | Build usable (hard fallback) |
| `data/paper_live/models/q5b_pump_livelike_20261002.joblib` | Primary model |
| `data/paper_live/models/q5b_pump_livelike_20261002_calibration.json` | Calib + GO notes |
| `data/paper_live/models/q5b_pump_livelike_hard_20261002.joblib` | Secondary hard |
| `cycle0/artifacts/q5b_pump_livelike_20261002_wf_metrics.json` | WF metrics |
| `cycle0/artifacts/pump_livelike_build_meta_20261002.json` | Build meta |
| `cycle0/artifacts/pump_livelike_live_target_20261002.json` | Live target bands |
| `cycle0/path-a-pump-livelike-20261002.md` | This note |

## Non-actions

- paper_live PID **121466** not killed/restarted  
- `q5b_last.joblib` / `q5b_calibration.json` untouched (md5 `4df6d5a8…` / `586e2af1…`)  
- Dune API: **0** · Lite OFF · USD scale OFF  
- Workstream 3 residual-accept doc: **not written** (left for later)

## Next (if Sinck wants)

1. Hunt / label more **mid-live-like** 10× at MC-band T0 (geometry match, not just hard reject).  
2. Workstream 3: residual curve/age accept vs further code parity.  
3. Only revisit paper swap if live **median** and frac≥0.9 both lift without OOS collapse.
