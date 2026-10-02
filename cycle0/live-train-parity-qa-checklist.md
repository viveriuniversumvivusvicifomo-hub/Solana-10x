# Live ↔ train parity QA (anti look-ahead)

**Owner:** SolQA · **Date:** 2026-10-01 · **Context:** descalibration live scores vs OOS ≥0.99  
**Diagnosis:** `cycle0/live-vs-train-score-replay-20261001.md`  
**Recipe (SolModelos):** `cycle0/live-train-recipe-parity.md` · `src/paper_live/recipe_parity.py`  
**Code gates:** `src/verification/live_parity.py`

Umbral live temporal (BOSS): **0.99**. No mirar post-T0 para features.

### Política Sinck 2026-10-01 — **paridad operativa** (prod)

**PASS prod / paper reopen** exige **operativo**, no bit-exact USD vs store Dune:

| Requisito | Criterio |
|-----------|----------|
| Trades | `n_trades` / dump ≤T0 = train (recovery_on) |
| Meta | name/symbol fill OK (Create o Dune meta-fill) |
| Oracle | Path A Hermes (`sol × pyth_asof`); **scale 6.6× OFF** |
| Anti-LA | todo feature `ts ≤ t0` |
| Score residual | oracle Δ ~**1e-3–2e-3** (p.ej. 2hCEWY) **aceptado** — **no** bloquea PASS prod |

**Exact** `|Δ score| < 1e-12` vs store Dune = **diagnóstico** (`FAIL_DIAGNOSTIC` / `PASS_ISOLATE`) — **no** es PASS prod.

**Pausado (cero gasto):** P1 Dune scope A, re-fit Path A / candidate joblib.  
**Prohibido:** swap a `usd_store` overlay en live, P2-lite como “fix”.

Gate operativo vs exact también en: `cycle0/gate-paridad-operativa-vs-exact-20261001.md` (SolQA) · auditoría SolAuditor.

---

## 0) Non-negotiables

| ID | Gate | Fail if |
|----|------|---------|
| LP.no_post_t0 | Every trade / create / prior event used in features has `ts ≤ t0` | any `ts > t0` kept |
| LP.windows | buy60 / 30s / 5m / 15m / first5s / first10s end at **that mint’s T0** | window uses poll clock or wall “now” |
| LP.recipe | Live X columns == `FEATURE_SETS['+q5b']` (51), order matter for joblib | missing/extra/`migrated_pre_t0`/`creator_pubkey`/`create_ts`/labels |
| LP.labels_out | `hit_*`, `max_mc_*`, `label_*`, journal followup MC **never** in score vector | present in X |
| LP.refine_t0 | Historical replay / parity tests: `refine_t0=False` with OOS `t0_ts` | C1–C6 rewrite using post-OOS info in replay |
| LP.secrets | No Helius/Dune keys in journals, CSVs, md | hits |

---

## 1) USD / oracle parity (SolDatos owns fix; QA verifies)

1. `amount_usd = sol_amt * sol_usd_asof_t0` (Pyth preferred; document source + as-of).
2. **Forbidden for historical rebuild:** Jupiter/Hermes “now” when scoring past T0.
3. After fix: median `|buy_vol_usd_60s_live / buy_vol_usd_60s_train|` on sniper sample should move toward ~1 (not ~0.3 from 6–7× Dune inflate — track separately; do not “fix” by peeking post-T0).
4. Record `sol_usd_source` + `sol_usd_t0` on each scored row (meta OK; not in X unless recipe says so — currently **out** until Pyth as-of stable).

---

## 2) Helius pagination ≤T0 (SolDatos)

1. Enhanced fetch must reach **create floor** (or T0−48h), not stop after N pages with only post-create noise.
2. Merge mint + bonding-curve PDA; retry on 429; never treat partial page loss as `n_txs=0` silently.
3. After merge: drop `timestamp > t0` again (defense in depth).
4. Parity sample: for OOS highs, `n_trades_pre_t0` live should be in the same ballpark as Dune Q5a (not 1 vs 5–7). Soft until pagination fixed; then hard band TBD.
5. **No** filling missing pre-T0 trades with post-T0 pages.

---

## 3) T0 capture exacto

1. Live poll may use provisional T0; paper entry must re-resolve **first MC∈[8k,20k]** with evidence ≤ that T0.
2. Replay for score parity: freeze OOS `t0_ts` (`refine_t0=False`).
3. If refine enabled in prod: only use curve/trades ≤ candidate T0; never “first time we saw mint in poll” as permanent T0 without audit flag.

---

## 4) Q5a / Q5b feature recipe

1. Aggregate only on `trades` with `ts ≤ t0` (`q5a_agg.aggregate_q5a_for_mint` contract).
2. `migrated_pre_t0` ∈ CSV/journal OK; **DROP_FROM_X** (already).
3. Creator priors: causal (`create_ts < t0`, exclude self). Live Pump frontend ≠ Dune archive → document underestimation; do not backfill with post-T0 launches.
4. Q5b `age_s`: `t0 − create_ts` ≥ 0; null create → null age, not 0 pretending known.

---

## 5) Score / followup separation

1. Scoring uses recipe X only.
2. `followup` / `max_mc_after_t0` / `poll_pump_mcs` may update **labels/journal after entry** — never feed back into the same mint’s live features.
3. Fix `poll_pump_mcs` is BOSS/Datos; QA checks no feature column reads followup state.

---

## 6) Acceptance after fixes (re-score)

```bash
# Recipe + anti-LA static gates
PYTHONPATH=src .venv/bin/python -m verification.live_parity

# Train-store sanity (expect Δ≈0 fold-5)
PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay --out-prefix rescore_train_store_sanity

# Helius rebuild CSV from SolDatos
PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay \
  --features-csv <rebuild_≤T0.csv> --out-prefix rescore_helius_rebuild
```

| Check | Pass |
|-------|------|
| Recipe parity | 51 cols, no banned |
| Trade audit sample | 0 rows with `ts > t0` |
| Store rescore (diagnóstico) | exact \|Δ\|<1e-12 = diag only; prod acepta residual oracle ~1e-3–2e-3 |
| Operativo prod | trades=train + meta OK + Path A Hermes + scale OFF + ≤T0 |
| Helius rebuild highs (n≥3) | scores move up vs 0.63–0.78 baseline; target discuss with BOSS (0.99 may need recalib even after parity) |
| Journal | no post-T0 fields inside feature blob |

---

## 7) Explicit out of scope for this checklist

- Re-training HistGB on Helius scale (Modelos/BOSS product decision).
- Spending extra Helius/Dune credits beyond Sinck/BOSS OK.
- Redefining `migrated_pre_t0` semantics (already dropped from X).

---

## 8) SolQA hard gates (MUST-FIX 2026-10-01)

Config: `data/paper_live/models/live_entry_config.json` (Sinck product umbral **0.99**).

| ID | Gate | Fail if |
|----|------|---------|
| LP.prior_train | `creator_prior_source` ∈ `dune_cohort_*` / `train_store_v1` | `pump_frontend_30d`, `none`, missing after recipe complete → `skip_prior_not_train` |
| LP.t0_refined | `t0_refined=True` before score | False → `skip_t0_not_refined` |
| LP.umbral_config | Explicit `--score-threshold` == config `0.99` | other absolute thr without `--allow-non-train-threshold` |

Code: `verification.live_parity` (`assert_*` / `audit_*`) · `paper_live.score` · `paper_live.entry.EntryGate`.

```bash
PYTHONPATH=src .venv/bin/python -m verification.live_parity
```
