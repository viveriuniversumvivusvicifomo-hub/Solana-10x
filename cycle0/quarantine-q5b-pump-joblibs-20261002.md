# Quarantine inventory — `q5b_pump_*.joblib` vs producción `q5b_last` (2026-10-02)

**Lane:** SolModelos depuración modelos (BOSS)  
**Zone:** Europe/Madrid (CEST / UTC+2)  
**Written:** 2026-10-02 ~14:15 CEST  
**Constraints honored:** no train · no overwrite/swap `q5b_last` · no paper restart · 0 paid APIs

## Producción canónica (KEEP)

| Asset | Path | md5 (BOSS) | sha256 | size | mtime (CEST) |
|-------|------|------------|--------|------|--------------|
| Model | `data/paper_live/models/q5b_last.joblib` | `4df6d5a8dff6bf66528d4ee4cf6641b2` | `9908b93649a12cf676d42ee53fd6e3d98ba32d3ca9ea04a68c23fd4b45396a0c` | 263012 | 2026-10-02 08:21 |
| Calibration | `data/paper_live/models/q5b_calibration.json` | `b338c56efd19553a3d3c88b4b2529c524388e55835d4c3335f2b75bef145f10b` | 995 | 2026-10-02 08:21 |
| Entry config | `data/paper_live/models/live_entry_config.json` | (see file) | 1206 | 2026-10-02 08:21 |

**Policy (live_entry_config):** `score_mode=histgb_q5b` · **thr 0.99** (Sinck product) · Path A captura = `pump_mc_band_sighting_v1` · creator priors `dune_cohort_*` only · **USD scale 6.6× OFF**.

All `q5b_pump_*` below are **NO-GO vs producción**. Files stay on disk (prefer leave in place; no move to `quarantine/` this lane — avoids breaking refs). Do **not** point paper at any of them.

---

## Inventory — EVERY `q5b_pump_*.joblib` (+ matching `_calibration.json`)

### 1) `q5b_pump_20261002.joblib`

| Field | Value |
|-------|-------|
| sha256 | `96d8fce8e36478ad6d891415e67c26397d21765af077e1d81714b9e4a535ca65` |
| size / mtime | 264092 · 2026-10-02 09:36 CEST |
| calibration | `q5b_pump_20261002_calibration.json` · sha256 `0ad7c78ce833d07196b7db53ff4e600592d1f4462d068614b75ebee292481ae8` · 3321 B |
| cycle0 note | `cycle0/path-a-pump-ab-priors-wf-20261002.md` |
| wf_metrics | `cycle0/artifacts/q5b_pump_20261002_wf_metrics.json` |
| recipe tag | `train_on_store_with_Pump_path_column_set` |
| Key metrics | OOS n=9851 · AUC/AP/frac≥0.9/med/max **identical** to `q5b_last` on same fold (0.9327 / 0.8608 / 0.0915 / 0.171 / 0.9999) — twin of store HistGB, not a Pump-trade refit |
| **NO-GO (1-line)** | Twin of `q5b_last` on Dune-store X — does **not** lift live Pump score mass (prior note: live max≈0.53); not Path A Hermes-aligned train; default NO-GO swap until Sinck OK |

### 2) `q5b_pump_pilot500_20261002.joblib`

| Field | Value |
|-------|-------|
| sha256 | `0e66685a1d61a5396a273bd29f679776616343ba2b52127c9aa85e72f0f31a97` |
| size / mtime | 212073 · 2026-10-02 10:38 CEST |
| calibration | `q5b_pump_pilot500_20261002_calibration.json` · sha256 `22ce927d515477a13f36189a3e9da4501462dc008bb886fdc16287d7e26aa78b` · 2262 B |
| cycle0 note | `cycle0/path-a-pump-pilot500-20261002.md` |
| wf_metrics | `cycle0/artifacts/q5b_pump_pilot500_20261002_wf_metrics.json` |
| recipe tag | `pump_true_pilot500_expand_t0_overlay` · t0=`expand_t0_ts` · matrix n≈495 |
| Key metrics | OOS n=60 AUC 0.962 AP 0.783 (small-n, not swap evidence). **Live journal n=200:** pilot med **0.00020** / max **0.084** / frac≥0.9 **0.0** vs `q5b_last` med **0.162** / max **0.908** / frac≥0.9 **0.005** → lift_max **−0.824**, lift_median **−0.161** |
| **NO-GO (1-line)** | Live score-mass **collapse** vs `q5b_last` on journal; small OOS n; expand_t0 vs live MC-band T0 mismatch (64/69 pos empty-pre-T0) |

### 3) `q5b_pump_mcband_20261002.joblib`

| Field | Value |
|-------|-------|
| sha256 | `5ba05df30d83cf383d7517fb5e110b9faa2313ff3d2d8572495d16d4bcec90bf` |
| size / mtime | 225288 · 2026-10-02 11:11 CEST |
| calibration | `q5b_pump_mcband_20261002_calibration.json` · sha256 `99af227b45bd58f800ee60273417b11a60002776978a7abc9c4ce2b8c27f1a11` · 2233 B |
| cycle0 note | `cycle0/path-a-pump-mcband-pilot-20261002.md` |
| wf_metrics | `cycle0/artifacts/q5b_pump_mcband_20261002_wf_metrics.json` |
| recipe tag | `pump_mc_band_from_trades_v1` · usable n=467 / 34 pos |
| Key metrics | OOS n=57 AUC 0.997 (small-n). **Live journal n=200:** pilot med **0.00056** / max **0.045** / frac≥0.9 **0.0** vs last med **0.167** / max **0.908** / frac≥0.9 **0.005** → lift_max **−0.863**, lift_median **−0.167**; `go_nogo_observed=NO-GO` |
| **NO-GO (1-line)** | Journal score mass collapsed (max≪last); POS geometry outlier vs live captura (see feat-diag); fails max+med+frac lift gate |

### 4) `q5b_pump_livelike_20261002.joblib` (soft primary)

| Field | Value |
|-------|-------|
| sha256 | `00be12427ead82d2d9ef694f06c4c2535ff1f744bb988542ba318d5b12e0b9da` |
| size / mtime | 201847 · 2026-10-02 13:48 CEST |
| calibration | `q5b_pump_livelike_20261002_calibration.json` · sha256 `d53d5cda70f24478505c1711902df28f8dd3a2dabf8301e8c976496cc440cea5` · 2452 B |
| cycle0 note | `cycle0/path-a-pump-livelike-20261002.md` |
| wf_metrics | `cycle0/artifacts/q5b_pump_livelike_20261002_wf_metrics.json` |
| recipe tag | `pump_mc_band_from_trades_v1_livelike_filter` · soft usable n=332 / 38 pos |
| Key metrics | OOS n=40 AUC 0.75 frac≥0.9 **0.0** max 0.49. **Live journal n=500:** pilot med **0.036** / max **0.919** / frac≥0.9 **0.006** vs last med **0.171** / max **0.731** / frac≥0.9 **0.0** → lift_max **+0.188** but lift_median **−0.134**; `go_nogo_paper_swap=NO-GO` |
| **NO-GO (1-line)** | Max/frac≥0.9 improve but **median mass collapses** (0.036≪0.171); soft/hard prior mismatch vs mid-live POS; only ~7 mid-live-like positives; fails ALL-three lift gate |

### 5) `q5b_pump_livelike_hard_20261002.joblib`

| Field | Value |
|-------|-------|
| sha256 | `5785745b6616c55323ed5e01018151dedb056111aa1e9c83580557c6d342829b` |
| size / mtime | 216518 · 2026-10-02 13:48 CEST |
| calibration | `q5b_pump_livelike_hard_20261002_calibration.json` · sha256 `a3fddbae52b4a191304ce650370589f8fae3c67632ea2fd40b483f05b88b5bd4` · 1130 B |
| cycle0 note | `cycle0/path-a-pump-livelike-20261002.md` (secondary) |
| wf_metrics | `cycle0/artifacts/q5b_pump_livelike_hard_20261002_wf_metrics.json` |
| recipe tag | hard-ok filter · n=444 / 55 pos |
| Key metrics | OOS n=54 AUC 0.878 frac≥0.9 0.056 max 0.985. **Live n=500:** pilot med **0.050** / max **0.926** / frac≥0.9 **0.002** vs last med **0.171** / max **0.731** / frac≥0.9 **0.0** → lift_median **−0.121** |
| **NO-GO (1-line)** | Secondary hard filter — live median still collapsed vs `q5b_last`; soft/hard prior mismatch; fails median leg of GO criterion |

### 6) `q5b_pump_livelike_hard424_20261002.joblib`

| Field | Value |
|-------|-------|
| sha256 | `50445c0fc8ac2b650063d060cc90b365afe2663179a3f3f261eb09a8b5e916f1` |
| size / mtime | 208362 · 2026-10-02 13:17 CEST |
| calibration | `q5b_pump_livelike_hard424_20261002_calibration.json` · sha256 `5fd465a5ab84e66a40190480b143a28bc2c63cc50051183e02be3d1663116915` · 2154 B |
| cycle0 note | covered under `cycle0/path-a-pump-livelike-20261002.md` (hard424 prelim / alternate hard slice) |
| wf_metrics | `cycle0/artifacts/q5b_pump_livelike_hard424_20261002_wf_metrics.json` |
| recipe tag | hard424 slice · n=424 / 40 pos |
| Key metrics | OOS n=424 AUC 0.822 frac≥0.9 0.059 med 0.0068 max 0.996. **Live n=500:** pilot med **0.012** / max **0.943** / frac≥0.9 **0.006** vs last med **0.168** / max **0.908** / frac≥0.9 **0.002** → lift_median **−0.156** |
| **NO-GO (1-line)** | Hard424 alt — median mass collapse vs last on journal; fails ALL-three (max+med+frac≥0.9) GO gate |

---

## Summary table (journal / agreed panel vs `q5b_last`)

| Joblib | Journal n | pilot max | last max | pilot med | last med | pilot frac≥0.9 | last frac≥0.9 | Gate |
|--------|-----------|-----------|----------|-----------|----------|----------------|---------------|------|
| q5b_pump_20261002 | (twin; no Pump lift) | — | — | — | — | — | — | **NO-GO** |
| pilot500 | 200 | 0.084 | 0.908 | 0.00020 | 0.162 | 0.0 | 0.005 | **NO-GO** |
| mcband | 200 | 0.045 | 0.908 | 0.00056 | 0.167 | 0.0 | 0.005 | **NO-GO** |
| livelike soft | 500 | 0.919 | 0.731 | 0.036 | 0.171 | 0.006 | 0.0 | **NO-GO** (med↓) |
| livelike hard | 500 | 0.926 | 0.731 | 0.050 | 0.171 | 0.002 | 0.0 | **NO-GO** (med↓) |
| livelike hard424 | 500 | 0.943 | 0.908 | 0.012 | 0.168 | 0.006 | 0.002 | **NO-GO** (med↓) |

Numbers from `cycle0/artifacts/q5b_pump_*_wf_metrics.json` + linked path-a-pump-*.md — not invented.

## Quarantine action

- **Status:** marked NO-GO in this doc + optional STATUS stamp on linked notes.  
- **Disk:** files **left in place** under `data/paper_live/models/` (no move to `quarantine/` — prefer stability of refs).  
- **Paper:** stays on `q5b_last.joblib` + `q5b_calibration.json` + `live_entry_config.json`.

See also: `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` · `cycle0/recipe-path-a-train-canonical-20261002.md`.
