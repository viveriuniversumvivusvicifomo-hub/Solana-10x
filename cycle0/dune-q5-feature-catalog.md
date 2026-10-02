# Dune Q5 feature catalog (≤ T0) — expand cohort

**Date:** 2026-09-30 (CEST)  
**Cohort:** ~82k `primary_ready` mints (`labels_dune_expand_v2.csv` / `features_dune_p0_flow_expand_v2.csv`)  
**T0:** first MC ∈ [$8k, $20k] on Pump.fun · Label proxy: `hit_200k` (PRIMARY intended `hit_10x_30d`)  
**Motivation:** Ablation shows `buy_vol_usd_60s` dominates; local derived add ~0–0.6pp AP. Need **new external ≤T0** signals that can beat pure momentum.

Streams Helius: **OFF**. Never log API keys.

---

## 1) Inventory (existing)

### Queries / SQL
| Artifact | Path | Tables |
|----------|------|--------|
| Q3 MC-at-T0 | `cycle0/dune-q3-mc-at-t0.sql` | `dex_solana.trades` |
| Q4 flow pre-T0 | `cycle0/dune-q4-flow-pre-t0.sql` (+ `q4_batches/`) | `dex_solana.trades` |
| Expand runners | `src/ingestion/run_dune_expand_v2*.py`, `run_dune_q4_api.py` | API `/sql/execute` |
| Q5a NEW | `cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql` | `dex_solana.trades` |
| Q5b NEW | `cycle0/q5_sql/dune-q5b-creator-age-pre-t0.sql` | `pumpdotfun_solana.pump_call_create` |

### Tables used / considered
| Table | Role | Look-ahead |
|-------|------|------------|
| `dex_solana.trades` | Flow, sniper, trader concentration, progress proxy, migration flag | **L0** if `block_time ≤ t0` |
| `pumpdotfun_solana.pump_evt_createevent` | Creator, create_ts, name/symbol, age, prior (covers create+create_v2) | **L0** if `evt_block_time ≤ t0` |
| `pumpdotfun_solana.pump_call_create` / `_create_v2` | Fallback decoded IX tables | **L0**; v1 alone misses Token-2022 cohort |
| `pumpdotfun_solana.pump_call_withdraw` | Graduation | **L0** only if withdraw ≤ t0; probe returned empty — use pumpswap trades instead |
| `solana_utils.latest_balances` | True holders | **L2 SKIP** — current snapshot, no as-of-T0 |
| `tokens_solana.transfers` | Holder reconstruction | Feasible but heavy; **deferred** (trade-net proxy in Q5a) |
| `tokens_solana.fungible` | name/symbol | Covered via create row |

### Current feature columns (expand v2 flow)
Q3: `mc_usd_t0, price_usd_t0, mc_band_pos, log1p_mc_usd_t0, is_pumpdotfun`  
Q4: `buy/sell_count|vol_60s|5m, unique_traders_60s|5m|total, trade_count_total, time_since_first_trade_s`

---

## 2) Feature catalog by priority

### P0 — must try (implemented in Q5a / Q5b)

| Feature | Pack | Tables | Def (≤T0) | LA | Cost / batch |
|---------|------|--------|-----------|----|--------------|
| `buy/sell_*_30s`, `*_15m` | Q5a | trades | Extra imbalance windows beyond 60s/5m | L0 | ~same as Q4; 300 OK |
| `unique_buyers_total`, `unique_sellers_total` | Q5a | trades | Distinct buy/sell traders ≤T0 | L0 | cheap add-on |
| `buy/sell_count\|vol_total` | Q5a | trades | Lifetime ≤T0 totals | L0 | cheap |
| `first5/10_buy_vol_share`, `sniper_vol_share_5s`, `buy_vol_first_5s\|10s` | Q5a | trades | Early buy concentration after first trade / first N buys | L0 | window fn; may need ≤300 |
| `top1/5/10_buyer_vol_share` | Q5a | trades | Buy-volume concentration across traders | L0 | trader agg |
| `top1/5/10_holder_pct_proxy`, `n_holders_proxy` | Q5a | trades | Net-token positions from buys−sells (excl. curve) | L0* | *proxy — misses CEX/transfers |
| `net_sol_curve`, `progress_curve_proxy` | Q5a | trades | Σ SOL bought−sold on `pumpdotfun` / 85 | L0 | approx vs on-chain BC |
| `migrated_pre_t0` | Q5a | trades | Any `pumpswap` trade ≤T0 | L0 | should be ~0 in-band |
| `max_buy_usd`, `max_buy_share` | Q5a | trades | Largest single buy ≤T0 | L0 | cheap |
| `age_s`, `age_min` | Q5b | create | `t0 − create_ts` | L0 | light |
| `creator_prior_mints_7d\|30d` | Q5b | create | # other creates by same creator before T0 | L0 | 40d create scan |
| `name_len`, `symbol_len`, `name_missing` | Q5b | create | Metadata at create | L0 | cheap |
| `creator_pubkey`, `has_creator` | Q5b | create | Dev wallet id (categorical / hash later) | L0 | not numeric model-ready as-is |

### P1 — after P0 / subsample

| Feature | Tables | Note | LA |
|---------|--------|------|----|
| Wallet quality / repeat buyers across cohort | trades | **Leakage risk** if scored using future mints in same fold — needs causal wallet stats with cutoff ≤ train max t0 | L1 |
| Copycat name density | create + fungible | Count similar names in window before T0 | L1 |
| Creator funding age / CEX-like funder | transfers / SOL | Heavy; not started | L1 |
| True holders via transfers reconstruction | `tokens_solana.transfers` | Better than trade-net proxy; expensive | L0 if filtered |
| `creator_prior_graduates_30d` | withdraw / pumpswap | Only graduates with timestamp ≤ T0 | L0 |

### Skip / flag
| Item | Reason |
|------|--------|
| `solana_utils.latest_balances` holders | L2 current snapshot |
| Any ATH / max_mc / hit_* | Labels only |
| Post-T0 migration / withdraw after T0 | Look-ahead |
| Raw `creator_pubkey` string in tree models without hashing | High cardinality; keep for joins, hash or drop for WF |

---

## 3) SQL sketches & batch strategy

**Shared pattern (from expand v2):**  
`WITH sample AS (SELECT 'mint' … UNION ALL …)` → bounds → filter table → `block_time/create_ts ≤ t0` → aggregate.  
Batch size **300** (1000/500 failed on Q4). Dual keys `DUNE_API_KEY` + `DUNE_API_KEY_2` parallel claim queues. Performance: `medium`.

**Q5a:** see `cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql`  
**Q5b:** see `cycle0/q5_sql/dune-q5b-creator-age-pre-t0.sql`  
**Runner:** `src/ingestion/run_dune_q5_api.py`

Estimated credits: similar to Q4 per 300-mint batch; Q5a heavier (window + trader aggs) → smoke 10 → 50 → 300.

---

## 4) Outputs / merge keys

| Output | Path |
|--------|------|
| Q5a batches | `data/samples/dune_q5a_batches/` |
| Q5b batches | `data/samples/dune_q5b_batches/` |
| Merged Q5a | `data/samples/dune_q5a_features.csv` |
| Merged Q5b | `data/samples/dune_q5b_features.csv` |
| Joined (optional) | `data/samples/features_dune_p0_q5_expand_v2.csv` |
| Catalog + QA | this file + `cycle0/dune-q5-qa-checklist.md` |

**Merge keys:** `mint` + `t0_ts` (prefer `mint` alone if 1:1 with expand cohort).

---

## 5) Next steps (merge + WF)

1. Finish full P0 Q5a (+ Q5b) pulls on 82k.  
2. Left-join onto `features_dune_p0_flow_expand_v2.csv` on `mint`.  
3. QA leak regex + null rates + `migrated_pre_t0` near-zero check.  
4. Re-run walk-forward ablation: `buy_vol_60s` vs `buy60 + Q5a` vs `Q5a-only` vs full.  
5. P1 wallet-quality only with causal cutoffs.

## 6) Runtime notes (2026-09-30)

- **Batch size:** Q5a and Q5b both fail at 300 (`QUERY_STATE_FAILED` / too complex). **100 works** (Q5a ~40–60s/batch; Q5b ~5–8s/batch).
- **Q5b priors:** Dune creator×createevent self-join → "too many stages". Priors computed **offline** from cohort (`add_cohort_creator_priors`) — underestimates true priors; flagged.
- **Q5b source:** `pump_evt_createevent` (not `pump_call_create` alone — misses Token-2022 `create_v2`).
- **Holders:** trade-net proxy only (`top*_holder_pct_proxy`); true SPL holders deferred.
- **Dual keys:** Q5a on `DUNE_API_KEY` (worker A), Q5b on `DUNE_API_KEY_2` (worker B) to progress both P0 packs.


---

## Related: Q6 (dry, 2026-09-30)

Wallets/dev hist design (no credits): `cycle0/dune-q6-feature-catalog.md`, SQL under `cycle0/q6_sql/`. Gate: run only after Q5 lift + BOSS/Sinck OK.
