STATUS: NO-GO quarantined — see cycle0/quarantine-q5b-pump-joblibs-20261002.md

# Path A — Pump MC-band pilot (T0 rebase) — 2026-10-02

**Status:** COMPLETE (**NO-GO** paper swap)  
**Finished:** 2026-10-02T11:11:12+02:00 (CEST)  
**Zone:** Europe/Madrid  
**Constraints:** paper_live PID **18531** untouched · 0 Dune · Lite OFF · USD scale OFF · `q5b_last` / `q5b_calibration.json` **not** overwritten

Follow-up to GO-1 `expand_t0_ts` pilot (`path-a-pump-pilot500-20261002.md`): that run had **64/69 positives empty-pre-T0** and collapsed live journal scores. This rebuild sets T0 = first Pump trade MC∈[8k,20k] and relabels `hit_10x_30d` from that T0.

---

## Frozen T0 recipe (`pump_mc_band_from_trades_v1`)

| Step | Rule |
|------|------|
| Implied MC | `float(priceUsd) * 1e9` (Pump UI supply = 1B; matches Dune Q3 `amount_usd/tok_amt*1e9`) |
| Band | MC ∈ **[8000, 20000]** USD |
| **T0** | Timestamp of **first chronological** Pump frontend trade with MC in band |
| Captura gate | `find_t0_pump_mc_sighting` + `is_scoreable_pump_capture` (`pump_mc_band_sighting_v1`); needs `create_ts` from expand; age ≤ 86400s |
| Deep fetch | If cache never enters band: paginate up to 40 pages / mint (cap ≤80 mints, HTTP budget) until band or oldest past expand T0 |
| **Non-reconstructable** | After deep fetch: `never_in_band` or `no_trades` → **excluded** from WF matrix (no expand_create_proxy this run) |

`expand_create_proxy` (use expand `t0_ts`/`mc_usd_t0` when Pump band missing) is **OFF** by default — would reintroduce empty-pre-T0 bias.

### Reconstructability (n=500 pilot500 sample)

| Method | n |
|--------|---|
| `pump_trade_mc_band` (pilot500 cache) | **455** |
| `pump_trade_mc_band_deep` (extra pages) | **39** |
| **Total reconstructable** | **494** |
| `never_in_band` | 4 |
| `no_trades` | 2 |

Of 494 recon: **467** scoreable (27 drop: 14 `age_gt_max_86400s`, 13 `missing_create_ts`).

**Empty pre-T0 on usable:** **0 / 467** (fixes the GO-1 empty-positive failure mode).

---

## Frozen label recipe (`hit_10x_30d` from new T0)

| Item | Definition |
|------|------------|
| Positive | `max_mc_after_new_t0 ≥ 10 × mc_usd_t0` within **30d** |
| Local trades | max implied MC from Pump trades with `new_t0 < ts ≤ new_t0+30d` |
| Expand supplement | `labels_dune_expand_v2.max_mc_after_t0` **only if** `expand_t0 ≥ new_t0` **or** `\|Δt\| ≤ 1h` (near-parity; valid LB / no pre-T0 peak attribution) |
| Sources | Cached + deep Pump trades + local expand CSV — **0 Dune API** |
| Anti look-ahead | Labels use **strictly post-T0** prices/MC only |

| Metric | Value |
|--------|-------|
| n usable WF | **467** |
| Label rate (new) | **0.0728** (34 pos) |
| Expand label rate on same rows | 0.122 |
| Agreement new↔expand | 0.946 |

---

## Feature matrix

| Item | Value |
|------|-------|
| Path | `data/samples/features_pump_path_a_mcband_20261002.csv` |
| Overlay | Q5a + `buy_vol_usd_60s` from Pump trades **≤ new T0**; Q5b age/name/creator priors from expand (age recomputed create→new T0) |
| Trades reuse | `data/samples/pump_pilot500_trades_20261002/` |
| Extra trades | `data/samples/pump_mcband_trades_extra_20261002/` (39 deep band hits) |
| Deep HTTP (resume total ok) | ~526 calls this resume + prior partial; **0 Dune** |

Anti look-ahead: `parse_pump_frontend_trades(..., t0=new_t0)` keeps only `ts ≤ T0`.

---

## WF OOS → `q5b_pump_mcband_20261002`

| Metric | mcband | q5b_last on same OOS X |
|--------|--------|------------------------|
| n test | 57 | — |
| AUC | **0.997** | 0.072 |
| AP | **0.976** | — |
| frac ≥ 0.9 | 0.053 | — |
| median | 0.00068 | — |
| max | 0.993 | — |
| base_rate | 0.105 | — |

Caveat: OOS looks strong on small held-out fold — **not** swap evidence. See live rescore.

Distinct artifacts (not twin, not pilot500, not `q5b_last`):

- `data/paper_live/models/q5b_pump_mcband_20261002.joblib`
- `data/paper_live/models/q5b_pump_mcband_20261002_calibration.json`
- `cycle0/artifacts/q5b_pump_mcband_20261002_wf_metrics.json`

---

## Live journal rescore (n=200 Path A Pump scoreable)

| Dist | mcband | q5b_last |
|------|--------|----------|
| median (p50) | **0.00056** | 0.167 |
| max | **0.045** | 0.908 |
| frac ≥ 0.9 | **0.0** | 0.005 |
| p90 | 0.0058 | 0.265 |
| **lift_max** | **−0.863** | — |
| **lift_p50** | **−0.167** | — |
| **lift_frac≥0.9** | **−0.005** | — |

No live score-mass lift vs production `q5b_last`.

---

## GO / NO-GO for paper swap

**NO-GO** (default; confirmed).

Reasons:
1. Live journal score mass **drops** vs `q5b_last` (max 0.045 vs 0.91; frac≥0.9 = 0).
2. Closing the T0 gap (0 empty-pre-T0) did **not** restore live score mass — residual is still feature-distribution / train-cohort vs live-captura (see residual-parity).
3. High OOS AUC on the mcband matrix does not transfer to journal Pump rows.

Do **not** point paper_live at `q5b_pump_mcband_20261002.joblib`.

---

## Integrity checks

| Check | Result |
|-------|--------|
| paper_live PID | **18531** still running (untouched) |
| `q5b_last.joblib` md5 | `4df6d5a8dff6bf66528d4ee4cf6641b2` (unchanged) |
| `q5b_calibration.json` md5 | `586e2af105e8b890594a4f70612915a0` (unchanged) |
| Dune API calls | **0** |
| Lite / USD scale | OFF / OFF |
| Distinct from pilot500 + twin | yes (`q5b_pump_mcband_*`) |

## Non-actions

- Did not kill/restart paper_live  
- Did not call Dune API  
- Did not overwrite `q5b_last.joblib` or `q5b_calibration.json`  
- Did not swap live model path  
- Did not enable expand_create_proxy  

## Scripts / artifacts

| Item | Path |
|------|------|
| Build | `scripts/build_pump_mcband_pilot.py` |
| WF | `scripts/archive/train_q5b_pump_mcband_wf.py` (ARCHIVED; use `scripts/train_q5b_path_a_candidate_wf.py`) |
| Build meta | `cycle0/artifacts/pump_mcband_build_meta_20261002.json` |
| T0 recon CSV | `cycle0/artifacts/pump_mcband_t0_recon_20261002.csv` |
| Matrix | `data/samples/features_pump_path_a_mcband_20261002.csv` |
| Joblib | `data/paper_live/models/q5b_pump_mcband_20261002.joblib` |

## Pointers

- Prior pilot (expand T0): `cycle0/path-a-pump-pilot500-20261002.md`  
- Residual parity: `cycle0/path-a-residual-parity-20261002.md`  
- Live T0 helper: `ingestion.t0_capture.find_t0_pump_mc_sighting`
