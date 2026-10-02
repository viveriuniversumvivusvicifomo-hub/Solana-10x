# GO criterion — q5b candidate vs `q5b_last` (2026-10-02)

**Owner:** SolModelos (criterion) · SolAuditor (audit) · Sinck (swap OK)  
**BOSS wording (explicit):** **lift journal max + med + frac≥0.9 vs `q5b_last`** before another walk-forward / promotion.  
**Zone:** Europe/Madrid  
**No train / no swap in this lane** — criterion only.

---

## When this applies

**Before ANY** new walk-forward that aims at promotion, and **before ANY** candidate → `q5b_last` swap:

1. Score the candidate and `q5b_last` on the **SAME panel** (live journal Path A Pump scoreable, or an agreed Pump-live panel documented in the candidate note).
2. Apply the gates below. Fail any → **NO-GO** (keep paper on `q5b_last`).

---

## GO only if ALL of the following hold

### A) Offline / journal lift vs `q5b_last` (SAME panel)

| Leg | Requirement |
|-----|-------------|
| **max** | Candidate max score improves **meaningfully** vs `q5b_last` on the same panel |
| **median** | Candidate median improves vs `q5b_last` (no score-mass collapse) |
| **frac≥0.9** | Fraction of scores ≥ **0.9** is ≥ baseline of `q5b_last` on the same panel |

**AND document product thr 0.99:**

| Gate | Source | Role |
|------|--------|------|
| frac≥**0.9** | Historical WF / go-nogo artifacts (`live_thr_unchanged: 0.9` in many metrics JSONs) | **BOSS-required lift leg** (this criterion) |
| thr / frac≥**0.99** | `live_entry_config.json` → `score_threshold: 0.99` (`threshold_source=sinck_product_20261001`) | **Live product entry gate** — report frac≥0.99 (or count≥thr) on the same panel; candidate must not make product thr unreachable vs baseline |

Both thresholds must be documented on every candidate report. Promotion without median lift is **NO-GO** even if max and frac≥0.9 rise (see livelike soft: formal max/frac GO, paper swap NO-GO).

**BOSS one-liner:** lift journal **max + med + frac≥0.9** vs `q5b_last` before another WF.

### B) Hard process gates (all required)

| Gate | Requirement |
|------|-------------|
| `recipe_parity` | **PASS** (`assert_recipe_matches_joblib` on candidate) |
| USD scale | **OFF** (6.6× forever off) |
| Joblib overwrite | **None** — export `q5b_path_a_candidate_*.joblib` only; never clobber `q5b_last` without Sinck+GO |
| SolAuditor | **PASS operativo** on ge10 / recovery panel (Path A Hermes, trades=train, anti-LA, scale OFF) |
| Sinck | **OK** for swap |

### C) Recipe alignment

Candidate must follow `cycle0/recipe-path-a-train-canonical-20261002.md` (FEATURE_SETS['+q5b'] 51, imputer→HistGB, Path A USD documented, label `hit_10x_30d`, features ≤T0).

---

## NO-GO if any fail

Any failed leg in A, any failed gate in B, or recipe mismatch → **NO-GO**.  
Do not start another promotion WF until the lift panel shows max+med+frac≥0.9 improvement (or Sinck revises this criterion in writing).

---

## Current `q5b_pump_*` vs this gate (all FAIL)

Numbers from `cycle0/artifacts/q5b_pump_*_wf_metrics.json` + path-a-pump notes. Panel = live journal Path A Pump scoreable where available.

| Candidate | max lift | med lift | frac≥0.9 lift | Other | Verdict |
|-----------|----------|----------|---------------|-------|---------|
| `q5b_pump_20261002` | no Pump journal lift (store twin) | — | — | not Path A Hermes train | **NO-GO** |
| `q5b_pump_pilot500_20261002` | −0.824 (0.084 vs 0.908) | −0.161 (0.0002 vs 0.162) | −0.005 (0 vs 0.005) | small n; empty-pre-T0 | **NO-GO** |
| `q5b_pump_mcband_20261002` | −0.863 (0.045 vs 0.908) | −0.167 (0.00056 vs 0.167) | −0.005 | POS geometry ≠ live | **NO-GO** |
| `q5b_pump_livelike_20261002` | +0.188 (0.919 vs 0.731) | **−0.134** (0.036 vs 0.171) | +0.006 | soft POS quieter than live | **NO-GO** (med) |
| `q5b_pump_livelike_hard_20261002` | +0.195 (0.926 vs 0.731) | **−0.121** (0.050 vs 0.171) | +0.002 | hard secondary | **NO-GO** (med) |
| `q5b_pump_livelike_hard424_20261002` | +0.035 (0.943 vs 0.908) | **−0.156** (0.012 vs 0.168) | +0.004 | hard424 | **NO-GO** (med) |

Full inventory: `cycle0/quarantine-q5b-pump-joblibs-20261002.md`.

---

## Producción until GO

Keep: `q5b_last.joblib` + `q5b_calibration.json` + `live_entry_config.json` (thr 0.99, Path A Pump MC band, scale OFF).
