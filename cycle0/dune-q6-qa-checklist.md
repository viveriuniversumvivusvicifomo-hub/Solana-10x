# Q6 anti-lookahead QA checklist (DRY)

Use when Q6 is authorized. Until then: design-only.

## Always

1. **Join key:** `mint` (+ `t0_ts` equality check vs expand cohort).  
2. **Time filter:** every source row `ts ≤ t0_ts`; other-mint creates use `create_ts < t0_ts`.  
3. **Grad proxy:** `first_grad_ts ≤ t0` and `≥ create_ts_j`.  
4. **No** `latest_balances`, ATH, `max_mc_*`, `hit_*`, post-T0 withdraw.  
5. **`creator_pubkey`:** present for join OK; **absent from train X**.  
6. **No secrets** in CSV/meta. Streams Helius OFF.  
7. **Credits:** only after BOSS/Sinck gate; smoke 10 before any full pull.

## Q6a

- [ ] Smoke 10: finite non-neg graduate counts; null creator → zeros + `has_creator=0`  
- [ ] Spot-check 3 mints: manual prior grads ≤ T0  
- [ ] No duplicate mint rows after merge  
- [ ] Batch shrink on `QUERY_STATE_FAILED` (do not treat as credit stop)

## Q6b

- [ ] Smoke 10: `n_buyers_pre_t0` ≥ 0; shares in [0,1]  
- [ ] Buyers only from trades with `block_time ≤ t0`  
- [ ] Prior creates by trader use `create_ts < t0` and mint ≠ sample mint  
- [ ] If query too heavy → fall back to offline from Q5a trader lists

## Q6c (offline WF)

- [ ] Wallet scores fit only on train fold; apply to val/test  
- [ ] Cutoff ≤ `max(t0)` of train fold  
- [ ] Document in WF report as L1-causal

## Merge into X

- [ ] Drop `creator_pubkey`, labels, `max_mc_*`  
- [ ] `feature_ts` / event times ≤ t0  
- [ ] Report null rates and credit spend
