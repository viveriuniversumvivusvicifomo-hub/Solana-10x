# Path A — Pump-true feature matrix plan (2026-10-02)

**Date:** 2026-10-02 ~09:45 CEST (Europe/Madrid)  
**Workstream:** 2 — Pump-true feature matrix (design + max offline build)  
**Constraints:** paper_live PID **18531** untouched · Lite OFF · USD scale OFF · **0 Dune** · `q5b_last.joblib` **not** overwritten

## Goal

Train HistGB on features built the **same way live Path A Pump scores** (Pump MC-band T0 + frontend trades ≤T0 + Q5b/priors), not on Dune-store Q5a under a renamed joblib twin.

## Column map (live Pump enrich vs train expand / `+q5b`)

Recipe: `FEATURE_SETS['+q5b']` = **51** cols (recipe==joblib PASS). Full machine-readable map: `cycle0/artifacts/pump_true_feature_inventory_20261002.json` → `column_map`.

| Taxonomy | Meaning | Examples |
|----------|---------|----------|
| **identical** | Same agg windows / `q5a_agg` / buy60 code path | Almost all Q5a counts/vols/shares/holders; `buy_vol_usd_60s` windows |
| **remapped** | Same name, different construction or overwrite | `age_proxy_s` (live=`age_s` create→T0; train=`t0−first_trade`); `progress_curve_proxy` / `net_sol_curve` (**Pump coin overlay overwrites** trade agg); age/name/symbol from Pump coin; creator priors from dune_cohort store |
| **null-on-live** | Always None (train ~99.99% null too) | `creator_prior_mints_all_in_window` |
| **Pump-only meta** | Journal/enrich keys **not** in X | `sol_usd_source=pump_frontend`, `t0_definition`, `capture_scoreable`, `creator_prior_source`, … |
| **Dune-only expand** | In expand CSV / `full` set, **not** in histgb `+q5b` X | `mc_band_pos`, 5m flow, `time_since_first_trade_s`, `migrated_pre_t0` (banned) |

**USD note (all USD legs):** live Pump uses frontend `valueUsd` (fallback `sol×sol_usd`); train uses Dune `amount_usd`. `APPLY_DUNE_HELIUS_USD_SCALE` **OFF** — do not invent a blind factor.

## Local data inventory (no Dune)

Written: **`cycle0/artifacts/pump_true_feature_inventory_20261002.json`**.

| Source | Role for Pump-true matrix | Usable now? |
|--------|---------------------------|-------------|
| `paper_journal.sqlite` Path A Pump scoreable rows | Full live `+q5b` vectors at Pump T0 | **YES** — 167 rows (2026-10-02+) |
| `labels_dune_expand_v2.csv` | Labels by mint | Join on journal: **0/167** (live cohort ∉ expand) |
| `features_dune_p0_q5_expand_v2.csv` | Train matrix (Dune) | Structure/labels only — **not** Pump-true |
| `dune_q5a/q5b_features.csv` | Store overlays | Not Pump trades |
| `helius_parity_features_*.csv` | ~65 expand mints Helius-scale | Overlap expand but **Helius USD**, not Pump |
| `pump_frontend_mc_8k_20k_sample.json` + trades smokes | Fixtures / smoke | Small n |
| Historical Pump trades for expand mints | Needed for labeled Pump matrix | **MISSING on disk** |

## Offline build (done this session)

Script: **`scripts/build_pump_true_features_offline.py`**

| Output | n | Labels | Notes |
|--------|---|--------|-------|
| `data/samples/features_pump_path_a_journal_20261002.csv` | **167** | **0 joins** | Extracted from journal; 0 network |
| `data/samples/features_pump_path_a_smoke_20261002.csv` | **5** | **0 joins** | Pump frontend re-fetch; **5/5** `n_trades>0`, buy60 filled |
| `features_pump_path_a_expand_*.csv` | — | — | **NOT built** — blocked by cost fence |

Tests: `tests/paper_live/test_pump_true_features_offline.py` + path_a capture → **10 passed**.

### Journal matrix status

- All `+q5b` cols present; only intentional null = `creator_prior_mints_all_in_window`.
- `sol_usd_source=pump_frontend` 100%; `meta_source=create` 100%.
- `creator_prior_source` empty in running PID (code A stamped but **process not restarted**).
- **Cannot WF** on journal alone: no `hit_10x_30d` labels for these mints.

### Smoke pipeline proof

≤5 journal mints via `GET /trades/{chainId}/{mint}` → parse → `aggregate_q5a_for_mint` → CSV. Smoke T0 = max(trade.ts) when not passing journal T0 — **pipeline proof only**, not train-grade.

## Full expand rebuild — API plan + STOP

| Item | Value |
|------|-------|
| Target | `features_pump_path_a_expand_v1.csv` ⋈ `labels_dune_expand_v2` by mint |
| n mints | ~**82 089** |
| API | Pump frontend trades cursor route (working); **0 Dune** |
| Cap | `limit=200`, `max_pages=5` → ≤5 GETs/mint |
| **Est. HTTP** | **~410 445** GETs |
| Est. trade rows upper | ~82k × 1000 |
| Dune credits | **0** |

**STOP before burning network at scale.** Do not run expand-wide fetch without Sinck GO + rate-limit / backoff plan + T0 policy decision.

### Blockers beyond volume

1. **T0 policy:** live `pump_mc_band_sighting_v1` ≠ expand `t0_ts` (Dune/C1–C6). Rebuilding trades ≤expand-t0 may still mismatch live captura; rebasing T0 to first Pump MC∈[8k,20k] needs MC history (not just trades).
2. Historical trades retention on Pump API for old mints — unknown truncation.
3. Even with Pump trades, USD (`valueUsd` vs Dune `amount_usd`) and curve overlays remain remapped.

## Recipe (recommended build order)

1. Keep journal CSV as **live reference distribution** (score mass ~0.02–0.53).
2. Pilot Pump overlay on **n=200–2000** expand mints (Sinck GO): trades ≤chosen T0 → Q5a/buy60; keep Q5b/priors from store; join labels → `features_pump_path_a_pilot_*.csv`.
3. WF → `q5b_pump_<date>.joblib` **alongside** (never overwrite `q5b_last`) ; compare OOS frac≥0.9 and live rescore max.
4. Only then consider thr / model swap GO.

## Gaps summary

| Gap | Severity | Mitigation |
|-----|----------|------------|
| No labeled Pump-true matrix | **BLOCKER** for real refit | Pilot expand overlay (network, 0 Dune) |
| Journal 0 label joins | Expected | Follow-up labels later or expand pilot |
| Twin `q5b_pump_20261002` ≡ Dune store | Known NO-GO swap | Needs new matrix |
| `age_proxy_s` / curve overlays | Residual (WS3) | Code fix vs accept |
| Prior stamp not live until restart | Ops | Sinck GO restart for A only |

## Cost fence

- This session: **0 Dune**; Pump smoke **5** mints only.
- Expand-scale: ~**410k** Pump GETs — **STOP** / ask Sinck.
- USD scale / Lite: stay **OFF**.

## Recommended next Sinck GO

| Option | Action | Why |
|--------|--------|-----|
| **GO-1 (preferred data)** | Pilot **n=500** expand mints Pump trades overlay → partial `features_pump_path_a_pilot_*.csv` + WF candidate joblib alongside | Only path to score mass shift; ~2.5k HTTP |
| **GO-2 (ops)** | Restart paper for **A** prior stamp only (keep `q5b_last`, thr 0.9) | Unblocks `skip_prior_not_train`; expect mostly `skip_below_thr` |
| **NO-GO** | Swap to twin `q5b_pump_20261002` / lower thr / USD scale / Dune | Twin≠Pump-true; thr cut insufficient (max≈0.53); scale OFF |

**Verdict:** Matrix status = **partial** (`journal` + `smoke` CSVs on disk). Full train-grade Pump matrix = **blocked** on labeled expand overlay + T0 policy. Next GO = **GO-1 pilot** (or GO-2 restart if scoring gate is the immediate ask).

## Non-actions

- Did not kill/restart paper_live (PID 18531)
- Did not call Dune API
- Did not overwrite `q5b_last.joblib`
- Did not run expand-scale Pump fetch
