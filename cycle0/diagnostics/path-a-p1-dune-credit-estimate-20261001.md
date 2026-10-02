# Path A P1 — Dune credit estimate (ANTES de gastar) — 2026-10-01

**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`  
**BOSS pick:** **P1 scoped** — Dune SQL Path A USD + credit estimate **BEFORE any spend**  
**Paper live:** FROZEN · Scale 6.6× **OFF** · **NO P0 Helius 82k** · **NO P2 as Path A**

---

## ⛔ Explicit gate

| Rule | Status |
|------|--------|
| **No execution until Sinck OK** | **ACTIVE** — SQL written only; **0** Dune API / UI runs this turn |
| Do NOT spend credits / GB on Path A until Sinck picks scope + cap | **ACTIVE** |
| Do NOT treat this estimate as a green light | Estimates are **order-of-magnitude**; smoke measures truth |

**Ask Sinck:** approve which scope **(A / B / C)** + **credit cap** (and engine: Medium recommended).

---

## 1) What was written (no run)

| Path | Role |
|------|------|
| `cycle0/q5_sql/dune-path-a-usd-pre-t0.sql` | Full Path A mint-level agg (runner `RUNNER_INJECTS_SAMPLE`) |
| `cycle0/q5_sql/dune-path-a-usd-ge10-smoke.sql` | Cheapest smoke — 12 ge10 inline |
| `data/samples/dune_path_a_usd_ge10_smoke_upload.csv` | Upload list ge10 (mint,t0_ts) |
| `data/samples/dune_path_a_usd_n200_upload.csv` | Upload list n=200 (ready if B chosen) |
| `cycle0/diagnostics/path-a-p1-dune-credit-estimate-20261001.md` | This file |

**Path A formula in SQL:** `amount_usd = sol_amt × prices.usd[WSOL, minute(block_time)]`  
**Export:** mint-level 13 `+q5b` USD cols (not raw legs) — rebuilds windows inside SQL.

Cohort upload (full): `data/samples/dune_sample_primary_ready_expand_v2_upload.csv` (~82 089).

---

## 2) Scoped options — credit / GB / batch table

### Empiric prior (Q5a) — anchor

| Fact | Value |
|------|------:|
| Q5a successful mint-level batches | **852** files @ **batch_size=100** |
| Q5a coverage | **78 457 / 82 089** |
| Q5a wall | ~40–60 s/batch when healthy |
| Batch 300 | **FAIL** (`QUERY_STATE_FAILED` / too complex) |
| Batch 100 | **OK** (plan Path A the same) |
| Free multi-key pool | **exhausted** (HTTP 402 datapoint limit) across A–L workers during Q5a |
| Typical ok batches before 402 / key | **~70–83** @100 mints (≈ free ~2 500 cr allowance) |
| **Implied cr / Q5a batch (proxy)** | **~30–40** (2500÷70…80) — **not** official; planning band only |
| Q4 expand v2 | **~244** batches @300 (lighter SQL than Q5a); no per-batch credit logged |

Path A SQL ≈ **Q5a trades scan + windows** + **`prices.usd` WSOL minute** join → plan **1.2–2.0×** Q5a compute.

**GB scanned:** Dune credits are compute-based (no public GB→credit formula). Proxy scan footprint:

- Cohort `t0` span ≈ **2026-08-30 → 2026-09-22** (~23 d) + **7 d** lookback → ~**30 d** `dex_solana.trades` filter window per batch (batch-local `bounds`)
- Train Σ `trade_count_total` ≈ **15.5 M** legs (store) — query still scans pump/WSOL pairs then filters to sample mints
- Plus `prices.usd` WSOL minutes over same bounds (~43k minutes / 30 d — cheap vs trades)

Use smoke `execution_cost_credits` to calibrate before B/C.

### Credit table (planning bands)

| Scope | n mints | Batches @100 | Est. credits (low–high) | Est. relative GB / scan | Batch strategy | Suggested credit **cap** |
|-------|--------:|-------------:|------------------------:|-------------------------|----------------|-------------------------:|
| **(A) smoke ge10** | **12** | **1** (inline SQL) | **20–80** | 1× batch · ~2 d t0 cluster + 7 d lookback (tight) | Single UI/API exec · Medium · export CSV | **50–100** |
| **(B) n=200** | **200** | **2** | **40–160** | ~2× smoke (same recipe) | 2× runner batches · upload `dune_path_a_usd_n200_upload.csv` | **200** |
| **(C) full 82k** | **82 089** | **821** | **16 000–66 000** | ~Q5a + oracle · **may exceed Plus 25k/mo** | Claim queue like Q5a · dual/multi keys · batch=100 · sleep 2s · shrink on FAIL | **set AFTER (A)** |

**Central planning point (C):** ~**30k credits** @ ~37 cr/batch × 821 — treat as **Plus monthly (25k) + overage or multi-cycle**. Do **not** start C on residual free 402'd keys.

**Export credits (API):** Plus ≈ **2 cr/MB** exported. Mint-level Path A ≈ 20 cols × 82k rows ≈ few–tens MB → **≪ execute cost**. Prefer mint-agg (this SQL) over raw legs (legs would be GBs + huge export).

### Compare to prior Q5a spend

| Item | Q5a (done) | Path A P1 (proposed) |
|------|------------|----------------------|
| Pattern | `dex_solana.trades` + sample UNION + windows | Same + `prices.usd` × `sol_amt` |
| Batch size | 100 (300 fail) | **100** |
| Batches | 852 → 78.5k mints | 821 → 82.1k (full) |
| Credit source | Multi-free ~11×2500 ≈ **27.5k/mo** pool (now dead/exhausted) | Needs **paid** Plus/Analyst + cap |
| Documented $/cr | Plus ~**$0.014/cr** extra (`stack-cost-study-20261001.md`) | Same |
| Rough Q5a burn | Order **tens of k credits** across keys (402 thunderdome) | Path A full ≈ **same order or +20–100%** |

**Honesty:** No `execution_cost_credits` was persisted in Q5a batch metas — table above is **reconstructed**. Smoke (A) is mandatory calibration.

---

## 3) Residual risk vs live Path A

| Residual | Magnitude | Notes |
|----------|-----------|-------|
| **Dune gross `sol_amt` vs Helius fee-net** | **~1%** systematic on large Pump snipers | Live Path A = Helius net; Dune ≈ net×1.01 (see `usd-path-a-vs-dune-ge10-20261001.md`) |
| **Oracle: `prices.usd` (Coinpaprika minute) vs Hermes `pyth_asof`** | **~0.1–0.3%** typical when both as-of | Not bit-exact Pyth; closest free Dune SOLUSD |
| **As-of trade minute vs live single `pyth_asof(t0)`** | **≪0.1%** on ≤15m windows | Live stamps one T0 price on all legs |
| **Leg inclusion still uses Dune `amount_usd >= 1`** | Rare edge | Then reprice with Path A; optional later filter on path_a ≥ 1 |
| **Q4 historical double-count** | N/A for this SQL | Path A SQL uses Q5a `tok_amt > 0` + builds `buy_vol_usd_60s` itself |
| **Missing oracle minutes** | Track `n_legs_missing_oracle` | Should be ~0; drop those legs |
| **Scale 6.6×** | **OFF** | Forbidden |
| **P2 Path A-lite** | **Not Path A** | Not authorized this turn |

**Bit-exact vs live Helius Path A?** **Near**, not exact — expect **≲1–1.5%** on USD vols after smoke QA vs ge10 pilot (`features_ge10_path_a_usd_pilot_20261001.csv`).

---

## 4) Recommended sequence (after Sinck OK)

1. **Approve (A)** + cap **≤100 cr** → run `dune-path-a-usd-ge10-smoke.sql` once → record `execution_cost_credits`.  
2. Diff 13 USD cols vs Helius Path A pilot; gate: median |rel| ≤ ~1.5% on `buy_vol_usd_total` / `buy_vol_usd_60s`.  
3. Recalibrate table: `cr_per_batch = measured_smoke × (optional B factor)`.  
4. Only then consider **(B)** or **(C)** with explicit cap (C likely needs Plus + overage budget).

Reuse runner pattern: `src/ingestion/run_dune_q5_api.py` (inject sample marker; new pack pointing at `dune-path-a-usd-pre-t0.sql`) — **wire later; do not run now**.

---

## 5) Ask Sinck (copy for room)

Please reply with:

1. **Scope:** **A** (ge10 smoke) / **B** (n=200) / **C** (full 82k) / none  
2. **Credit cap** (hard ceiling for this Path A effort)  
3. Confirm: **no P0 Helius 82k**, **no P2 as Path A**, **scale 6.6× OFF**, **paper frozen**

Until then: **SQL + estimates only — zero Dune spend.**

---

## 6) Explicitly not done

- No Dune API / UI execute  
- No Helius 82k  
- No Path A-lite (P2) store rewrite  
- No paper_live / joblib changes  
- No overwrite of `features_dune_p0_q5_expand_v2.csv`
