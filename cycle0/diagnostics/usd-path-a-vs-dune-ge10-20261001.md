# USD Path A vs Dune (ge10) — 2026-10-01

**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`  
**Policy:** Path A = `amount_usd = sol_amt × pyth_asof`. Scale 6.6× **OFF**. Paper live **FROZEN** (untouched).

## Executive conclusion (Sinck)

| Verdict | Meaning |
|---------|---------|
| **(a) partially fixable under Path A** | 2hCEWY `buy_vol_usd_60s` 0.70× is **not** an oracle bug — train **Q4** counts **+1 buy** vs **Q5a**/Helius (extra ≈ `max_buy_usd`). Fix train Q4 filter (`tok_amt > 0`, same as Q5a) **or** stop trusting Q4 `buy_vol_usd_60s` when `buy_count_60s ≠ buy_count_total`. |
| **(a) optional Path A sol_amt tweak** | Systematic **~0.988%** live under-vol on large snipers = Helius **net** SOL vs Dune **gross** (`sol_net × 1.01 ≈ dune_sol`). Defining Path A `sol_amt` as fee-gross (×1.01 on Pump buys) closes most of that gap **without** enabling 6.6×. |
| **(b) for exact score parity** | After Q4 hygiene, residual USD still ≠ train until SolModelos **reprices train USD with Path A** (or accepts ~0.1–1% feature noise). |
| **(c) irreducible residual** | Even with pyth_asof + matched legs: Dune `amount_usd` is not guaranteed `sol×spot` on every row; after (a), expect **≲1%** on vol features (not 30%, not 6.6×). |

**Do not** turn `APPLY_DUNE_HELIUS_USD_SCALE` ON. Blind 6.6× is rejected by firmas + this hunt.

---

## Evidence sources

| Artifact | Role |
|----------|------|
| `cycle0/diagnostics/helius-recovery-2hCEWY-20261001.md` | Trade count closed 6=6; USD residual called out |
| `cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv` | Per-feature train vs live |
| `cycle0/live-usd-oracle-parity.md` | Path A / as-of chain / scale OFF |
| `cycle0/live-vs-train-mismatch-hunt-20261001.md` | USD MUST-FIX backlog |
| `data/samples/helius_parity_tx_dump_2hCEWY_20261001.csv` (+ meta) | 6 buy legs; `sol_usd=117.7543759` **`pyth_asof`** |
| `data/samples/dune_q4_flow_expand_v2.csv` vs `dune_q5a_features.csv` | Q4 vs Q5a inconsistency |
| **This hunt outputs** | `usd-path-a-vs-dune-ge10-20261001.md` (this file), `usd_path_a_vs_dune_per_trade_ge10_20261001.csv`, `usd_path_a_vs_dune_mint_summary_ge10_20261001.csv` |

---

## 1) Oracle: pyth_asof vs T0 (not the 0.70 cause)

| mint | T0 (UTC) | `pyth_asof` | `publish_time` lag vs T0 | source | CoinGecko? |
|------|----------|------------|--------------------------|--------|------------|
| 2hCEWY | 2026-09-22 01:41:06 | **117.754376** | **0 s** | `pyth_asof` | No (Pyth OK with key) |
| 4M3g | 2026-09-22 07:03:04 | 116.485707 | 0 s | `pyth_asof` | No |
| BZof | 2026-09-22 15:29:59 | 117.369153 | 0 s | `pyth_asof` | No |
| wbf55 | 2026-09-22 06:42:20 | 116.684659 | 0 s | `pyth_asof` | No |

- `APPLY_DUNE_HELIUS_USD_SCALE` = **False** (verified).
- `PYTH_API_KEY` / Hermes reachable → `require_pyth_asof` succeeds.
- Earlier firmas CSV used `FALLBACK:coingecko_asof` (~118.87) when key path failed in that run; **replay meta for 2hCEWY used true `pyth_asof`**.
- Product: HIGH still prefers Pyth; CoinGecko is as-of fallback only when `require_pyth=False`.

**Implied Dune USD/SOL** (`max_buy_usd/max_buy_sol`) on ge10 ≈ **116.5–117.6** — same ballpark as Pyth. **Not ~168, not ~681.**

---

## 2) 2hCEWY — why live/train `buy_vol_usd_60s` ≈ 0.70

### Per-trade Path A (Helius dump, pyth_asof=117.754376)

| tx (prefix) | source | sol_amt | amount_usd Path A |
|-------------|--------|--------:|------------------:|
| xWGrzEKU… | PUMP_FUN CREATE | 0.989072 | 116.47 |
| 2qTzpLaf… | PUMP_FUN (leg1) | 29.629630 | 3489.02 |
| 2qTzpLaf… | PUMP_FUN (leg2) | 24.758445 | 2915.91 |
| 4t3XKdmU… | PUMP_FUN (leg1) | 9.876543 | 1163.01 |
| 4t3XKdmU… | PUMP_FUN (leg2) | 19.753086 | 2326.01 |
| 2SBSMPFq… | PUMP_AMM | 64.786248 | 7628.86 |
| 2E5GiJM7… | PUMP_AMM CREATE_POOL | — | **skipped** (0 legs) |
| **Σ** | 6 buys | **149.793025** | **17638.78** |

CREATE_POOL moves ~85 SOL WSOL internally but is **not** a trader buy — correctly excluded by Helius parse (matches Q5a `tok_amt > 0` intent).

### Train store inconsistency (same mint)

| pack | buy_count | buy_vol_usd | notes |
|------|----------:|------------:|-------|
| **Q4** `buy_*_60s` | **7** | **25228.54** | merged into X as `buy_vol_usd_60s` |
| **Q5a** `buy_vol_usd_total` | **6** | **17610.97** | matches Path A Σ within **+0.16%** |
| Q4 − Q5a | **+1** | **+7617.57** | ≈ `max_buy_usd` **7616.04** |

```
live / train_60s  = 17638.78 / 25228.54 = 0.699  (~0.70 BOSS observation)
live / train_total = 17638.78 / 17610.97 = 1.0016
```

Implied “168 USD/SOL” from `25228/149.79` is an artifact of **Q4 double-counting one ~max_buy leg**, not a real SOL price.

**Root cause class:** **missing/extra legs in train Q4** (Dune quoting / filter), **not** oracle timestamp, **not** Path A formula.

Q5a SQL filters `tok_amt > 0`; Q4 SQL does **not**. Across expand_v2, ~17k mints have `|Q4/Q5a − 1| > 1%`; worst cases show exact **2.000×** (= double-count of the only buy). 2hCEWY is the ge10 instance (ratio 1.43 = total+max_buy).

---

## 3) Other ge10 mints — ~1% USD/vol deltas (fee / sol_amt)

From `helius_ge10_feature_delta_20261001.csv` (`buy_vol_usd_60s` live/train):

| mint | ratio | primary driver |
|------|------:|----------------|
| 69xneX | 1.0009 | Path A ≈ Dune (tiny pyth vs implied) |
| wXcb | 0.9989 | ~flat |
| BZof | 0.9972 | sol_amt + missing tiny leg in some dumps |
| 4M3g / wbf55 / 2ahcm / 2DU2 | **0.990±0.001** | **systematic** |

### Fee-gross hypothesis (Path A–preserving)

On large PUMP_AMM max buys:

| mint | Helius `max_buy_sol` (net) | ×1.01 | Train `max_buy_sol` |
|------|--------------------------:|------:|--------------------:|
| 4M3g | 2859.462451 | **2888.057** | **2888.0** |
| BZof | 158.418972 | **160.003** | **160.0** |
| wbf55 | 2958.474308 | **2988.059** | **2988.0** |
| 2ahcm | 3461.454545 | **3496.069** | **3496.0** |

→ Dune `sol_amt` ≈ Helius net × **1.01** (Pump fee gross).  
4M3g Path A **gross** Σ / train total ≈ **0.9997** (with recovered legs).

2hCEWY max buy does **not** follow 1.01 (64.786 vs 64.773) — already net-matched; its 0.70 is the Q4 extra leg only.

**sol_amt parse:** multi-buyer BC native legs are correct for 2hCEWY (6=6). Residual undercount on BZof/4M3g dumps is **missing 1 small buy** in some recoveries, separate from USD formula.

---

## 4) What was ruled out

| Hypothesis | Status |
|------------|--------|
| Oracle timestamp wrong / stale Pyth | **Ruled out** — lag 0; pyth_asof ≈ Dune implied |
| CoinGecko fallback causing 0.70 | **Ruled out** for 2hCEWY replay (`pyth_asof` in meta) |
| Blind need for 6.6× scale | **Ruled out** — firmas med ~1.02; Path A ~1.00 on Q5a |
| Missing Helius legs → 0.70 on 2hCEWY | **Ruled out** — 6 buys = train Q5a; Q4 has the +1 |
| Path A product change | **Not required** for the 0.70 smoking gun |

---

## 5) Recommendation for Sinck

### Choose one packaging (all keep Path A product policy)

**(a) Fixable under Path A (SolDatos / train SQL) — preferred next step**

1. **Q4 hygiene:** add `tok_amt > 0` (and/or dedupe tx) to Q4 raw CTE so `buy_vol_usd_60s` ≡ Q5a semantics; re-export flow features for mints with `buy_count_60s ≠ buy_count_total`.  
   → Clears 2hCEWY 0.70 on `buy_vol_usd_60s` without touching live Path A.
2. **Optional sol_amt definition:** document Path A `sol_amt` as **fee-gross** (`net × 1.01` on Pump) to match Dune, **or** leave net and accept ~1% vol delta.

**(b) Train reprice with Path A (SolModelos)**

Rebuild train USD legs as `sol_amt_helius_or_dune_sol × pyth_asof(t0)` and re-fit HistGB → exact live≡train economic features. Needed if ZERO-tolerance score equality is mandatory after (a).

**(c) Irreducible residual + magnitude**

If Sinck keeps Dune `amount_usd` as train ground truth and Helius net Path A as live:

| residual | magnitude | notes |
|----------|-----------|-------|
| Q4 vs Q5a (unfixed) | **up to ~30–50%** on affected mints (2hCEWY 30%) | data bug, not oracle |
| Fee net vs gross | **~1.0%** | systematic on large snipers |
| pyth vs Dune implied | **~0.1–0.3%** | when both as-of |
| True Dune quirks | **unknown, likely ≪1%** after above | no 6.6× |

**Default recommendation:** **(a1) Q4 filter fix** + keep Path A net + scale OFF; treat ~1% as known bias until SolModelos picks (a2) or (b). Score gap on 2hCEWY after Q4 fix should shrink to Q5a-level (~2e-3 → much smaller from USD; name_len still separate).

---

## 6) Artifacts written

- `cycle0/diagnostics/usd-path-a-vs-dune-ge10-20261001.md` (this report)
- `cycle0/diagnostics/usd_path_a_vs_dune_per_trade_ge10_20261001.csv`
- `cycle0/diagnostics/usd_path_a_vs_dune_mint_summary_ge10_20261001.csv`

n=200 enrich: **not blocked** by this work. Paper live: **not restarted**.
