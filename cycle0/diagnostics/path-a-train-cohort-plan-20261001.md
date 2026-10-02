# Path A train cohort plan (WF +q5b) — 2026-10-01

**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`  
**BOSS GO:** rebase train store → Path A for WF `+q5b`  
**Order:** (1) SolDatos Path A USD on train · (2) SolModelos re-fit · (3) QA/Auditor gate  
**Paper live:** FROZEN (untouched) · Scale 6.6× **OFF** · Do **NOT** swap live/paper

---

## Executive verdict (this turn)

| Question | Answer |
|----------|--------|
| **Method chosen** | **STOP after plan + ge10 pilot** — true offline Path A **not feasible** for full train |
| **Why** | Dune/flow CSVs are **mint-level aggregates only** — **no per-trade `sol_amt` + timestamps** |
| **Helius for majority?** | **YES** for bit-exact Path A on ~82k → **needs BOSS OK** (do not burn API) |
| **Full store CSV built?** | **NO** (`features_dune_p0_q5_expand_v2_path_a_usd_20261001.csv` not started) |
| **Ready-for-SolModelos?** | **Partial Y** — ge10 Path A pilot (12) ready for pipeline validation; full re-fit **blocked** on BOSS decision |
| **6.6× / Dune AmountInUSD as Path A?** | **Forbidden** (policy intact) |

---

## 1) Scope — cheapest correct Path A for TRAIN

### Path A definition (product)

```
amount_usd = sol_amt × pyth_asof(t)     # per trade leg
# then rebuild buy/sell vol recipe cols (q5a_agg + buy60 windows)
APPLY_DUNE_HELIUS_USD_SCALE = OFF       # never 6.6×
# Do NOT copy Dune AmountInUSD as Path A
```

### Preferred offline reprice — **FAILED inventory check**

| Source | Has per-trade `sol_amt`? | Has trade timestamps? | Usable for Path A rebuild? |
|--------|--------------------------|----------------------|----------------------------|
| `dune_q4_flow_expand_v2.csv` | **No** (agg USD only) | No | No |
| `dune_q4_batches_v2/*.csv` | **No** | No | No |
| `dune_q5a_features.csv` / batches | **No** (agg; has `max_buy_sol`, `net_sol_*`) | No | Partial proxy only |
| `features_dune_p0_q5_expand_v2.csv` | **No** | No | Target store only |
| Q5a SQL (`dune-q5a-microstructure-pre-t0.sql`) | Yes **inside** Dune CTE | Yes | Would need **paid Dune re-export** of legs or Path A agg |
| Helius Enhanced dumps | Yes (live parse) | Yes | **ge10 + partial n200 only** |

**Conclusion:** Cannot compute `amount_usd = sol_amt × pyth_asof(t)` per trade from existing train CSVs.

### Alternatives ranked (cost ↑)

| ID | Method | Coverage | Cost | Bit-exact vs live Path A? | BOSS gate |
|----|--------|----------|------|---------------------------|-----------|
| **P0** | **Helius ≤T0 enrich** all train mints → Path A agg | ~82 089 | **HIGH paid API** | **Yes** (policy match) | **ASK before burn** |
| **P1** | Dune re-export: legs or `SUM(sol_amt)×oracle` | ~82k | Dune credits | Near (gross sol; ~1% fee vs live net) | ASK (credits) |
| **P2** | **Path A-lite** mint-level: `usd' = usd × pyth_asof(t0) / (max_buy_usd/max_buy_sol)` | **78 109 / 82 089 (95.15%)** with `max_buy_sol>0` | Offline + free/cheap Pyth as-of | **No** — closes oracle gap (~0.1–0.3%); leaves ~1% fee net/gross; not true per-trade Path A | Optional compromise |
| **P3** | ge10 (12) Path A already live | 12 | **$0 this turn** | Yes on those mints | **Shipped as pilot** |

### Gaps → Helius (or Dune legs)

| Gap | n mints | Notes |
|-----|--------:|-------|
| Store train cohort | **82 089** | `features_dune_p0_q5_expand_v2.csv` |
| Missing `max_buy_sol` (no Path A-lite) | **3 980** | of which **3 596** still have `buy_vol_usd_60s>0` |
| Store without Q5a row | **3 632** | Q4-only USD/vol; no `max_buy_sol` / microstructure |
| Q5a present | **78 457** | Has SOL aggregates + USD vols |

**True Path A for majority = Helius (P0) or Dune legs (P1).** Path A-lite (P2) is **not** authorized as Path A without BOSS naming it a compromise.

---

## 2) Helius need Y/N + cost estimate

| Item | Estimate |
|------|----------|
| **Need Helius for true Path A on majority?** | **Y** |
| Train mints | 82 089 |
| Σ `trade_count_total` | ~15.5M |
| Lower-bound Enhanced pages @100 tx/page | **~213k** pages (trades alone; + BC PDA + mint dual crawl → higher) |
| Empiric rate (n200 enrich) | **20 mints / ~1112 s** (~55.6 s/mint wall) with recovery helpers |
| Extrapolate 82k @ same rate | **~53 days** single-threaded wall · **hundreds of k API calls** |
| Plan risk | Developer credits / 429 / Soft caps — **SolAuditor: no paid APIs without BOSS OK** |

**This turn:** **no Helius calls** for train Path A rebuild.

**Pilot already paid:** ge10 recovery_on Path A features exist (`helius_parity_features_ge10_recovery_on_20261001.csv`) — reused offline.

---

## 3) Exact USD/vol cols SolModelos `+q5b` uses

Source of truth: `src/features/post_q5_sets.py` → `FEATURE_SETS['+q5b']` (**51 cols**).

### A. USD absolute — **must change** under Path A reprice (13)

| Col | Pack |
|-----|------|
| `buy_vol_usd_60s` | buy60 |
| `buy_vol_first_10s` | Q5a |
| `buy_vol_first_5s` | Q5a |
| `buy_vol_usd_15m` | Q5a |
| `buy_vol_usd_30s` | Q5a |
| `buy_vol_usd_total` | Q5a |
| `first10_buy_vol_usd` | Q5a |
| `first5_buy_vol_usd` | Q5a |
| `first_buy_usd` | Q5a |
| `max_buy_usd` | Q5a |
| `sell_vol_usd_15m` | Q5a |
| `sell_vol_usd_30s` | Q5a |
| `sell_vol_usd_total` | Q5a |

### B. Share / concentration — **invariant** under uniform mint reprice; may move under per-trade Path A (6)

`first5_buy_vol_share`, `max_buy_share`, `sniper_vol_share_5s`, `top1_buyer_vol_share`, `top5_buyer_vol_share`, `top10_buyer_vol_share`

### C. SOL-native — leave unless `sol_amt` definition changes (fee net vs gross) (4)

`max_buy_sol`, `net_sol_curve`, `net_sol_total`, `progress_curve_proxy`

### D. Counts / meta / Q5b — **unchanged** by USD Path A

All `*_count_*`, `unique_*`, holders proxies, `age_*`, name/symbol, `creator_prior_*`, `has_creator`, `n_holders_proxy`, …

**Store cols outside +q5b** (e.g. `sell_vol_usd_60s`, `buy_vol_usd_5m`) — optional hygiene if shipping a full replacement CSV; not in HistGB `+q5b` X.

Recipe rebuild code (live ≡ target train): `paper_live.q5a_agg.aggregate_q5a_for_mint` + `buy_vol_60s_from_trades` with Path A `amount_usd` on each `TradeRow`.

---

## 4) Deliverables this turn

| Path | Status | Role |
|------|--------|------|
| `cycle0/diagnostics/path-a-train-cohort-plan-20261001.md` | **Written** | This plan |
| `data/samples/features_ge10_path_a_usd_pilot_20261001.csv` | **Written** | 12-mint Path A USD overlay (store skeleton + Path A USD/vol) |
| `data/samples/features_ge10_path_a_usd_pilot_20261001_meta.json` | **Written** | Meta / col list / policy |
| `scripts/build_ge10_path_a_usd_pilot_20261001.py` | **Written** | Reproducible offline builder |
| `data/samples/features_dune_p0_q5_expand_v2_path_a_usd_20261001.csv` | **NOT started** | Full train — blocked on BOSS |
| Dune store `features_dune_p0_q5_expand_v2.csv` | **Intact** | bak already exists (`*.bak_pre_q5a_20261001`); no overwrite |

### ge10 pilot notes (seed validation for SolModelos)

- Source Path A: `helius_parity_features_ge10_recovery_on_20261001.csv` (12/12 trades exact vs train counts; `pyth_asof`; scale OFF).
- Overlay replaces USD direct (+ share/sol from Path A when present) onto store rows for those 12 mints.
- Headline: `2hCEWY…` `buy_vol_usd_60s` Path A **17638.784115** (store was **17610.973964**, Δ≈$28).
- Use for: SolModelos smoke re-score / recipe check **before** full 82k rebase.
- Side residual table: `helius_parity_features_ge10_recovery_on_path_a_usd_side_20261001.csv`.

---

## 5) Pilot vs full

| Mode | n | Action |
|------|--:|--------|
| **Pilot (done)** | 12 ge10 | Path A features → pilot CSV; SolModelos can validate rebase plumbing |
| **Full (blocked)** | 82 089 | Needs BOSS pick: **P0 Helius** / **P1 Dune legs** / **P2 Path A-lite compromise** |

---

## 6) Blockers for BOSS

1. **Authorize paid Helius full-train enrich (P0)?** Y/N — if Y, budget/credits + parallelism + checkpoint dir; expect multi-day + 100k–500k+ Enhanced calls.
2. **Authorize Dune paid re-export of legs / Path A agg SQL (P1)?** Y/N — credits; still ~1% fee gross vs live net unless SQL uses net.
3. **Accept Path A-lite mint rescale (P2) as interim train?** Y/N — offline, ~95% coverage, **not** bit-exact Path A; document residual; still need Helius for 3.9k gap mints or leave Dune USD flagged.
4. Until one of the above: **SolModelos full re-fit on Path A store = N**; can only smoke on ge10 pilot.

---

## 7) Ready-for-SolModelos

| Item | Y/N |
|------|-----|
| ge10 Path A pilot CSV for validation | **Y** |
| Full train Path A USD store (~82k) | **N** (blocked) |
| Paper / live swap | **N** (frozen; not requested) |
| Scale 6.6× | **OFF** |
| Copy Dune AmountInUSD as Path A | **N** |

**Handoff:** SolModelos may (a) wire rebase job against `features_ge10_path_a_usd_pilot_20261001.csv` shape, (b) wait for BOSS on P0/P1/P2 before full HistGB re-fit.

---

## 8) Explicitly not done

- No Helius / Dune paid calls for 82k Path A rebuild  
- No `APPLY_DUNE_HELIUS_USD_SCALE`  
- No paper_live / joblib / live scoring changes  
- No overwrite of `features_dune_p0_q5_expand_v2.csv`  
- No claim that mint-level rescale ≡ Path A  

---

## Pointers

- Path A vs store residual (ge10): `cycle0/diagnostics/usd-exact-ge10-path-a-vs-store-20261001.md`  
- Q4↔Q5a parity anchor: `cycle0/diagnostics/usd-q4-q5a-parity-anchor-20261001.md`  
- Oracle policy: `cycle0/live-usd-oracle-parity.md`  
- Recipe: `src/features/post_q5_sets.py`, `src/paper_live/q5a_agg.py`
