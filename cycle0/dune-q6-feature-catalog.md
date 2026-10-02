# Dune Q6 feature catalog — wallets / dev hist ≤ T0 (DRY)

**Date:** 2026-09-30 (CEST)  
**Status:** **diseño + SQL en seco** — **no gastar créditos Dune** hasta que Sinck/BOSS lo pida tras ver lift Q5.  
**Cohort target (when authorized):** mismo expand v2 (~82k) / keys `mint` + `t0_ts`.  
**Streams Helius:** OFF. No secrets en samples.

Depends on Q5 (partial OK to *design*; do not block on Q5a finish):
- Q5b already: `age_s`, `creator_prior_mints_*` (offline cohort), `creator_pubkey` (join only, **fuera de X**)
- Q5a: microstructure / holder proxy / sniper

---

## 1) Goal

Signals beyond momentum (`buy_vol_usd_60s`) that use **dev history** and **buyer wallet history**, strictly ≤ T0, without putting raw `creator_pubkey` in the model matrix.

---

## 2) Packs

| Pack | Path | Intent | Run when |
|------|------|--------|----------|
| **Q6a** | `cycle0/q6_sql/dune-q6a-creator-graduates-pre-t0.sql` | `creator_prior_graduates_{7d,30d,all_in_window}` via first `pumpswap` trade ≤ T0 on other mints of same creator | After Q5 lift review + BOSS OK |
| **Q6b** | `cycle0/q6_sql/dune-q6b-buyer-wallet-hist-pre-t0.sql` | Per-mint agg of buyers' prior creates (30d) ≤ T0 | After Q5 lift; smoke tiny first |
| **Q6c offline** | (WF / Python, no Dune) | Fold-causal wallet quality: stats trained only on train-fold mints with cutoff ≤ fold `max(t0_train)` | With WF post-Q5; **no credits** |

### Features (proposed)

| Feature | Pack | Def (≤T0) | In X? | LA |
|---------|------|-----------|-------|----|
| `creator_prior_graduates_7d` | Q6a | # other creator mints with first pumpswap ≤ t0 and create in last 7d before t0 | yes | L0 |
| `creator_prior_graduates_30d` | Q6a | same, 30d | yes | L0 |
| `creator_prior_graduates_all_in_window` | Q6a | same, full scan window | yes | L0 |
| `creator_pubkey` | Q6a | join key only | **no** (same rule as Q5b) | — |
| `n_buyers_pre_t0` | Q6b | distinct buyers ≤ t0 | yes (or drop if redundant w/ Q5a) | L0 |
| `mean_buyer_prior_creates_30d` | Q6b | avg # prior creates by buyers as creators, create_ts < t0 | yes | L0 |
| `max_buyer_prior_creates_30d` | Q6b | max of above | yes | L0 |
| `pct_buyers_with_prior_create_30d` | Q6b | share of buyers with ≥1 prior create | yes | L0 |
| `wallet_quality_*` fold scores | Q6c | e.g. buyer hit-rate on **train** mints only, applied OOS | yes if causal | L1 if mis-cut |

### Deferred / skip

| Item | Reason |
|------|--------|
| True SPL holders via `tokens_solana.transfers` | Heavy; Q5a proxy first |
| `solana_utils.latest_balances` | L2 look-ahead |
| Creator funding age / CEX funder | P1+; needs transfer graph; sketch later |
| `creator_prior_mints_*` | Already Q5b (offline) — do not duplicate in Q6a |
| Raw `creator_pubkey` in X | High card / leakage surface |

---

## 3) Anti-lookahead (Q6)

1. Every create / trade / grad event joined must have `ts ≤ t0_ts` (strict `<` for *other* mints' creates vs this t0).  
2. Graduation = first `dex_solana.trades` with `project='pumpswap'` on mint_j; require `first_grad_ts ≤ t0_i`.  
3. Never use post-T0 withdraw / ATH / max_mc / labels.  
4. `creator_pubkey` may appear in CSV for join; SolModelos **drops** from train X (same as Q5).  
5. Q6c wallet scores: compute only with events and labels available at fold train cutoff — document in WF report.

---

## 4) Cost / batch (estimate, not run)

- Pattern: inject `sample` UNION like Q5; dual keys only if authorized.  
- Expect **batch 50–100**; 300 likely fails (Q5 precedent).  
- Q6a: creator×creates + pumpswap filter — medium/heavy.  
- Q6b: buys × createevent by trader — **heavy**; prefer smoke 10; if slow, derive from Q5a trader extracts offline.  
- **This pass spends 0 Dune credits.**

---

## 5) Merge (when authorized)

```
features_dune_p0_flow_expand_v2.csv
  LEFT JOIN dune_q5a_features.csv USING (mint)   -- when complete
  LEFT JOIN dune_q5b_features.csv USING (mint)
  LEFT JOIN dune_q6a_features.csv USING (mint)   -- future
  LEFT JOIN dune_q6b_features.csv USING (mint)   -- future
```

Keys: `mint` (+ `t0_ts` check). Drop `creator_pubkey` before WF X.

Ablation sets (post-Q5 first; Q6 later):  
`buy60 | buy60+q5a | q5a_only | +q5b | full` → then `full+q6a | full+q6b`.

---

## 6) Artifacts (this dry pass)

| Artifact | Path |
|----------|------|
| Catalog | `cycle0/dune-q6-feature-catalog.md` |
| QA checklist | `cycle0/dune-q6-qa-checklist.md` |
| Q6a SQL | `cycle0/q6_sql/dune-q6a-creator-graduates-pre-t0.sql` |
| Q6b SQL | `cycle0/q6_sql/dune-q6b-buyer-wallet-hist-pre-t0.sql` |
| Outputs (future) | `data/samples/dune_q6{a,b}_features.csv` — **not created** |

## 7) Gate

**Do not** call Dune `/sql/execute` for Q6 until BOSS/Sinck explicitly authorize after Q5 lift review.
