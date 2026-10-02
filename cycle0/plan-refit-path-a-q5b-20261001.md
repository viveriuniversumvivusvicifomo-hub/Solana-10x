# Plan — rebase store + joblib to Path A (WF `+q5b`)

**Date:** 2026-10-01 (CEST)  
**Owner:** SolModelos (re-fit) · SolDatos (Path A USD en cohort) · SolQA/SolAuditor (gate exact)  
**BOSS GO:** sí — paper **FROZEN**; **no** swap live/`q5b_last.joblib` hasta PASS auditor + OK Sinck.  
**Scale 6.6×:** OFF forever.

## Goal
Canonical train X USD legs = **Path A** (`sol_amt × pyth_asof_t0`, Q5a `tok_amt>0` anchor). Live Path A then scores against a joblib trained on the same USD definition → exact Δ≈0 without Dune overlay in prod.

## Why
Isolate pack proved residual class = USD only (`12/12` Δ=0 with store USD overlay). Prod stays Path A; store Dune `amount_usd` ≠ Path A (~$28 on 2hCEWY → Δ score ~2.35e-3).

## Sequence

### 1) SolDatos — store Path A (blocker for re-fit)
- Rebuild / patch cohort expand features so all USD volume cols used by `FEATURE_SETS['+q5b']` are Path A (not Dune amount_usd).
- Document: source oracle, as-of, Q5a filter, coverage %, mints with missing pyth.
- Deliverable paths (examples):  
  `data/samples/features_*_path_a_*.csv` + meta/sha + `cycle0/diagnostics/…`
- Do **not** spend Dune credits without BOSS (local Helius/pyth rebuild preferred).

### 2) SolModelos — plan checks then re-fit
**Pre-flight (this doc):**
- Feature set frozen: `FEATURE_SETS['+q5b']` (51) · DROP_FROM_X unchanged · label `hit_10x_30d`.
- Pipeline: `SimpleImputer(median)` → `HistGB` (no StandardScaler) — same as current.
- WF: `src/models/walk_forward_post_q5.py` / existing q5b last-fold export path.
- Anti-LA: fold = time; features ≤T0 only.

**Re-fit steps (after store Path A lands):**
1. Join Path A store + labels; assert coverage +q5b complete.
2. Run WF `+q5b` (same folds as q5b_last if possible).
3. Export **candidate** artifacts under versioned paths (NOT overwrite live yet):  
   - `data/paper_live/models/q5b_path_a_candidate.joblib`  
   - `data/paper_live/models/q5b_path_a_candidate_calibration.json`  
   - report `cycle0/wf-path-a-q5b-refit-20261001.md` (AUC/AP/top1%/top5% vs old)
4. Recalibrate trainQ top1%/top5% on fold-5 TRAIN only; keep Sinck product threshold policy separate (0.99) until Sinck decides.
5. Recipe parity gate: `assert_recipe_matches_joblib` on candidate.

### 3) Exact gate (SolQA / SolAuditor)
- Re-score ge10 `…_recovery_on_…` Path A features with **candidate** joblib + meta-fill.
- PASS only if **12/12** `|Δ live−store_path_a|<1e-12` (or agreed atol) **and** trades=train, pyth_asof, scale OFF, anti-LA.
- n=200 OOS Path A when enrich ready (secondary).

### 4) Cutover (BOSS / Sinck only)
- Swap `q5b_last.joblib` ← candidate; update calibration; restart paper — **only** after PASS + Sinck OK.
- Keep previous joblib as `q5b_last_dune_usd_backup.joblib`.

## Non-goals
- Overlay Dune USD into live enrich.
- Blind 6.6× scale.
- Reopening paper before PASS.

## Status (Sinck 2026-10-01 — paridad operativa)
Gate prod = **operativa** (trades=train, meta OK, Path A Hermes, scale OFF, ≤T0). Residual oracle ~1e-3–2e-3 **aceptado** — **no** exige `|Δ|<1e-12`. P1/re-fit **PAUSADOS** (cero gasto). Live model: `q5b_last.joblib` (sin swap usd_store/P2). Paper reopen: BOSS.

| Step | Owner | State |
|------|-------|-------|
| Path A cohort USD (P1) | SolDatos | **PAUSADO** — Sinck (cero gasto) |
| Plan | SolModelos | **THIS DOC** |
| Pilot score (ge10 Path A USD) | SolModelos | **DONE** — FAIL_DIAGNOSTIC vs Dune (esperado) |
| Re-fit full Path A candidate | SolModelos | **PAUSADO** — Sinck; keep `q5b_last.joblib` |
| Exact bit gate `|Δ|<1e-12` | SolQA/SolAuditor | **N/A prod** — gate operativo documentado por Auditor |
| Live swap Path A joblib | BOSS/Sinck | **NO** — no candidate; paper reopen under operativa |

