# Paper-live tracker v0 — poll MC 8k–20k, score ≤T0, journal paper (NO trading)

**Fecha:** 2026-10-01 (Europe/Madrid)  
**Owner:** Sinck / SolDatos  
**Estado:** runnable. **Default = Pump discover + Helius Enhanced enrich** (`--feed pump --enrich-via helius`). Bitquery optional (`--feed bitquery` / `--enrich-via bitquery`, often 402). Streams Helius **OFF** (pull Enhanced only). Trading=false.

## Qué es / qué no es

| Es | No es |
|----|-------|
| Poll ~10s de mints Pump en banda MC **$8k–$20k** | Bot de ejecución / órdenes reales |
| Snapshot T0 = **primer avistamiento en banda** (provisional) | Detector captura C1–C6 completo |
| Score **solo con features ≤T0** alineadas a WF (`FEATURE_SETS['+q5b']`) | Look-ahead con MC post-T0 o labels |
| Journal paper (SQLite + CSV) + follow-up `hit_10x_30d` | PnL con fills / MEV |
| Skip/hold si falta **cualquier** col requerida del set | Sustitutos inventados (name/symbol score) |

Relacionado (offline OOS): [`paper-trade-v1.md`](paper-trade-v1.md) — simulación walk-forward, **no** este live poller.

## Decisiones v0

| Pieza | Decisión | Notas |
|-------|----------|-------|
| Feed default | **Pump.fun** `frontend-api-v3.pump.fun/coins` | `--feed pump` (default) |
| Feed optional | Bitquery `Trading.Pairs` | `--feed bitquery` (402/429 common) |
| Streams Helius | **OFF** | Push/WS still OFF; Enhanced REST pull ON for enrich |
| Intervalo poll | **~10 s** live | Respect frontend 429 backoff |
| T0 paper | First sight in band | `capture_quality` LOW |
| Features default set | **`+q5b`** = buy60 + Q5a + Q5b | Same as WF / paper_trade_v1 |
| Enrich via **helius** (default) | Q5b from Pump coin + Q5a/buy60 from Enhanced txs ≤T0 | Hybrid; histgb_q5b can score |
| Enrich via pump | Q5b age/creator/name + curve proxies | **No** buy_vol/Q5a (trades API gap) |
| Enrich via bitquery | Full Q5a+Q5b+buy60 | When quota allows |
| Enrich dry (helius) | `helius_enhanced_txs_fixture.json` + pump sample Q5b | 0 calls |
| Enrich dry (bitquery sample) | `q5_live_fixture.json` | 0 calls |
| Enrich dry (pump-only) | coin fields in sample | 0 calls; Q5a null |
| Score default | **`histgb_q5b`** (trained recipe) | Needs `--export-model +q5b` |
| Incomplete vector | **skip / hold** | No HistGB-as-excuse for missing packs |
| Fallback Q5b name/symbol | **OFF** (`--allow-q5b-fallback` DEBUG) | Not WF-comparable |
| Selección | **Ultra-select:** score ≥ trainQ top1% (fold-5 histgb_q5b) + max_per_hour=2; top_k = batch safety only | Matches paper-trade-v1 Entrada A / ~topK_100 daily rate; NOT top-20 every 10s |
| Trading | **False** hard | |


## Pump.fun native feed (default, 2026-10-01)

Bitquery FREE returned **HTTP 402** during live enrich. Tokens launch on Pump.fun, so the
default discovery path is the same frontend API already used in cycle0
(`pump_frontend_mc200k_current.json`, `universo-current-vs-30d.md`).

### Endpoints used

| Method | URL | Auth | Role |
|--------|-----|------|------|
| GET | `https://frontend-api-v3.pump.fun/coins?offset&limit&sort=last_trade_timestamp\|created_timestamp&order=DESC&includeNsfw=false&complete=false` | none | Discover recent incomplete coins |
| GET | same + `creator={wallet}` | none | Creator prior mints (partial index) |
| GET | `/trades/all/{mint}` | JWT optional | **Broken** — path validates mint as CAIP `chainId` (32-char); unusable for buy_vol |
| GET | `/coins/{mint}` | — | **404** on current v3 |

Client-side filter: `8000 ≤ usd_market_cap ≤ 20000` and `complete=false`.
Query `marketCapMin/Max` are **unreliable** (observed out-of-band rows) — do not trust alone.

Optional env (never print values): `HELIUS_API_KEY` (required for default enrich), `PUMP_JWT` / `PUMP_API_TOKEN` (Bearer, optional for `/coins`).

### Hybrid: Pump discover + Helius enrich (default, 2026-10-01)

User-agreed path after Bitquery FREE 402 and broken Pump `/trades/all/{mint}`:

| Stage | Source | Role |
|-------|--------|------|
| Discover | Pump `frontend-api-v3` `/coins` | MC ∈ [8k,20k], `complete=false` |
| Q5b | Pump coin fields (+ `/coins?creator=` priors) | age, creator, name/symbol, priors |
| Q5a + `buy_vol_usd_60s` | Helius Enhanced `GET /v0/addresses/{mint}/transactions` | ≤T0 trades; USD via `sol_amt × SOL_USD_REF` |
| Creator fallback | BondingCurve account decode (Helius RPC) | If coin lacks creator |
| Streams | **OFF** | No WS / Parsed Streams |

Code: `src/ingestion/helius_enhanced.py`, `src/paper_live/helius_enrich.py`, `src/ingestion/bonding_curve.py`.

### Features: Pump-only vs hybrid Helius vs train `+q5b`

| Pack | Pump-only | Hybrid Helius (default) | Notes vs Dune/Bitquery train |
|------|-----------|-------------------------|------------------------------|
| `age_s` / `age_min` / `has_creator` / name+symbol | ✅ | ✅ | Same Pump coin fields |
| `creator_prior_mints_{7d,30d,cohort}` | ⚠️ partial | ⚠️ partial | Frontend creator index undercounts vs Dune 30d |
| `buy_vol_usd_60s` + Q5a windows / sniper / concentration | ❌ | ✅ | Enhanced `PUMP_FUN` SWAP; SOL from bonding-curve `nativeBalanceChange` |
| `progress_curve_proxy` / `net_sol_*` | ⚠️ reserve proxy | ✅ trade-flow when txs present | Falls back to reserves if zero trades ≤T0 |
| Full `FEATURE_SETS['+q5b']` | ❌ skip histgb | ✅ when pages cover create→T0 | Empty trades ≤T0 still valid (zeros) |

### Gaps vs full train `+q5b` (honest)

| Gap | Severity | Detail |
|-----|----------|--------|
| USD oracle | **fixed** | Live: Pyth Hermes (if `PYTH_API_KEY`) → Jupiter v3 → CoinGecko → ref 103.11; stored as `sol_usd_t0` / `sol_usd_source` |
| Per-trade historical SOL/USD (Dune as-of) | low residual | Short create→T0 window uses one oracle quote at enrich (Hermes as-of needs key) |
| Enhanced page budget (`max_pages_per_mint`, default 2–3 ×100) | med | Busy mints may truncate early create→T0 history → undercount totals/sniper |
| Jupiter/router swaps | low | Parsed when feePayer net mint flow ≠0; `source!=PUMP_FUN` mapped carefully |
| Creator priors 30d | **fixed** | Paginate Pump `/coins?creator=` until ≥30d window (train parity); still not full Dune archive |
| `creator_prior_mints_all_in_window` | none | Train ~100% null — allowed |
| Aggregator / multi-hop SOL attribution | low | Prefer curve balance change; fee-payer native fallback |
| Streams / sub-second push | n/a | Pull poll only (by design) |
| C1–C6 capture T0 | **partial** | Hybrid enrich refines T0 via bonding-curve MC path when Helius trades cover create→band; else first-sight `capture_quality=LOW` |

### CLI

```bash
# Default live hybrid: Pump feed + Helius enrich (histgb_q5b can score)
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed pump --enrich-via helius

# Enrich-only smoke (2 mints, budget Enhanced pages)
PYTHONPATH=src .venv/bin/python -m paper_live --live --enrich-only --max-calls 6

# Dry smoke hybrid (fixture txs + pump sample Q5b)
PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 1 --feed pump --enrich-via helius

# Pump-only enrich (Q5b only; expect skip_incomplete_q5b)
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed pump --enrich-via pump

# Optional Bitquery (if quota recovers)
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed bitquery --enrich-via bitquery --max-calls 8
```

Code: `src/ingestion/pump_frontend.py`, `src/ingestion/helius_enhanced.py`, `src/paper_live/helius_enrich.py`, `src/paper_live/pump_enrich.py`, `--feed` / `--enrich-via` in `paper_live.__main__`.

## Ultra-select entry (theory-aligned, 2026-10-01)

**Problem:** v0 originally entered **top-K of every ~10s poll batch** (K=20). That is *not*
comparable to offline paper-trade-v1, where P@top≈100% only in the ultra-select tail:

| Offline rule (paper-trade-v1) | n | hit | trades/day |
|------------------------------|---|-----|------------|
| `+q5b_trainQ_top1%` (Entrada A) | 708 | 100% | ≈48.7 |
| `+q5b_topK_100` (Entrada B) | 500 | 100% | ≈34.4 |

Live has continuous streams, not fold batches — top-20 every cycle would over-enter by orders
of magnitude and destroy that selectivity.

**Chosen live rule (default):**

1. **Primary — Entrada A train quantile:** enter only if
   `score >= quantile(fold-5 train scores, 1 - top_frac)` with **top_frac=0.01** (top 1%).
   Threshold from TRAIN / exported calibration only (anti look-ahead). Fold-5 histgb_q5b
   default ≈ **0.999807** (`data/paper_live/models/q5b_calibration.json`).
2. **Capacity — max_per_hour=2:** ≈48/day, matching trainQ_top1% OOS rate (same ballpark as
   topK_100 ≈34/day). Rolling window over journal `entered_at` + session.
3. **`top_k` (default 50):** within-batch safety *after* the two gates above — **not** the
   primary selector.

**Why Entrada A over live top-K/batch:** fold-level top-K cannot be applied to a 10s poll;
a rolling capacity + absolute trainQ threshold is the causal live proxy that preserves
ultra-select rates. Entrada B remains the preferred *offline* capacity rule; live mirrors
its *rate*, not its batch mechanic.

**CLI:**

```bash
# defaults (very strict)
--entry-rule train_quantile --train-top-frac 0.01 --max-per-hour 2

# override absolute threshold
--score-threshold 0.999807

# legacy top-K-every-batch (debug / rule_buy60 smoke only)
--entry-rule topk_batch --top-k 20

# journal backtest (no live / no Bitquery)
PYTHONPATH=src .venv/bin/python -m paper_live --backtest-entry-gate
```

Cycle logs include `skip_below_thr=` and `skip_cap=` counts. Summary adds
`n_skipped_below_threshold_total` and `entry` describe block.

### Anti look-ahead (obligatorio)

1. Features / score solo del snapshot en `seen_at` (T0 provisional).  
2. Follow-up MC vive en tabla `followup` — no se joinea a X.  
3. Gate `assert_no_lookahead_keys` rechaza keys `hit_*` / `max_mc` / `after_t0` / `label_*`.  
4. Secretos (`.env`) **nunca** en journal, CSV, state ni logs.  
5. Trades/creates con `ts > t0` se descartan; priors usan `create_ts < this create`.

## Feature matrix: live vs train (`FEATURE_SETS['+q5b']`, 51 cols)

Hard rule: **same names/defs as training; missing → skip/hold; no substitutes.**

| # | Column | Pack | Live source | Status |
|---|--------|------|-------------|--------|
| 1 | `buy_vol_usd_60s` | buy60 | Bitquery `DEXTradeByTokens` buys ∈[t0−60s,t0] | ✅ wired |
| 2 | `age_proxy_s` | Q5a | max age of trade ≤T0 (first→T0) | ✅ wired |
| 3–11 | `buy_count_30s/15m/total`, `buy_vol_usd_30s/15m/total`, `buy_vol_first_5s/10s` | Q5a | same trades agg | ✅ wired |
| 12–20 | `first5/10_buy_vol_*`, `first_buy_usd`, `max_buy_*`, `sniper_vol_share_5s` | Q5a | sniper / first-N | ✅ wired |
| 21–27 | `sell_*_30s/15m/total` | Q5a | sells ≤T0 | ✅ wired |
| 28–34 | `top1/5/10_buyer_vol_share`, `top*_holder_pct_proxy`, `n_holders_proxy` | Q5a | trader net positions | ✅ wired |
| 35–39 | `unique_buyers_*`, `unique_sellers_total`, `unique_traders_30s/15m` | Q5a | distinct traders | ✅ wired |
| 40–41 | `net_sol_curve`, `net_sol_total`, `progress_curve_proxy` | Q5a | SOL flow /85 | ✅ wired (⚠️ SOL amt schema approx) |
| 42–43 | `age_s`, `age_min` | Q5b | Instructions `create`/`create_v2` | ✅ wired |
| 44 | `has_creator` | Q5b | Transaction.Signer / args | ✅ wired |
| 45–48 | `name_len`, `name_missing`, `symbol_len`, `symbol_missing` | Q5b | create args + Pairs fallback | ✅ wired |
| 49–51 | `creator_prior_mints_7d/30d/cohort` | Q5b | Instructions by creator ≤30d | ✅ wired |
| 52 | `creator_prior_mints_all_in_window` | Q5b | same scan; **train ~100% null** | ✅ allowed null (train parity) |

Join-only (never in X): `mint`, `t0_ts`, `creator_pubkey`, `create_ts`, `token_name`, `token_symbol`.  
Dropped from X: `migrated_pre_t0` (still computed for debug, not scored).

### Parity checklist vs walk-forward / paper_trade_v1

| # | Check | Status |
|---|-------|--------|
| 1 | Feature names identical to `FEATURE_SETS['+q5b']` | ✅ |
| 2 | Window buys `[t0−60s,t0]`; no post-T0 trades | ✅ |
| 3 | Q5a windows 30s / 15m / totals / sniper / concentration | ✅ `q5a_agg.py` |
| 4 | Q5b age + creator priors causal (`create_ts < t0`) | ✅ `q5b_agg.py` |
| 5 | `histgb_q5b` columns = exported joblib / FEATURE_SETS | ✅ |
| 6 | Default score mode = `histgb_q5b` | ✅ |
| 7 | Incomplete vector → skip (no invented substitute) | ✅ `required_q5b_present` |
| 8 | Label / post-T0 never in X | ✅ |
| 9 | USD schema Bitquery ≡ Dune `amount_usd` | ✅ derive USD↔SOL; drop `< $1` (Dune) |
| 10 | SOL amount for `net_sol_*` / `max_buy_sol` | ✅ `Side.Amount` or `usd/103.11`; project default pumpdotfun |
| 11 | Creator priors: live Pump paginated 30d vs train Dune | ⚠️ same formula + 30d window; index coverage ≠ full archive |
| 12 | T0 = C1–C6 captura (not first sight) | ⚠️ refine when trade MC path available; else LOW provisional |
| 13 | HistGB joblib present by default | ⚠️ run `--export-model +q5b` |

**Trust rule:** only trust live `histgb_q5b` rankings when `features_complete_q5b=true` and enrich source is `hybrid.pump.frontend+helius.enhanced`, `bitquery.*`, or dry fixtures. Never trust `rule_q5b_partial_fallback_DEBUG` or pump-only partial vectors.


## Live↔train score calibration (2026-10-01)

### Exact-calibration pass (2026-10-01 afternoon)

| Gap | Fix |
|-----|-----|
| `USD ≈ SOL×103` | `sol_usd_oracle.fetch_sol_usd` — Pyth→Jupiter→CoinGecko; hybrid enrich tags `sol_usd_t0`/`sol_usd_source` |
| Creator priors undercount | `fetch_creator_coins(..., window_days=30)` paginates to train 30d window |
| Provisional T0 | `t0_capture.find_t0_c1_c6` reconstructs first MC band cross (C1–C6) from ≤T0 trades when possible |

**Honest residual (physically blocked without more archive/key):** Hermes as-of historical SOL/USD per trade needs `PYTH_API_KEY`; Pump frontend creator index ≠ full Dune create archive; Enhanced page truncation on hot mints can miss early sniper window → refined T0 falls back to LOW first-sight.


### Symptom
Fold-5 trainQ top1% threshold ≈ **0.999807**. Live `histgb_q5b` journal scores max ≈ **0.886** → **0 / 150** pass (user note: 0/138 earlier subset).

### Root causes (feature parity, not the classifier)

| # | Bug | Evidence | Fix |
|---|-----|----------|-----|
| A | `net_sol_curve` / `progress_curve_proxy` / `max_buy_sol` ≈ **0** on live | Live med 0 vs train med curve **18.9 SOL**, progress **0.22** | `parse_bitquery_trades`: derive `sol_amt = usd / 103.11` when `Side.Amount` null; derive USD from SOL when USD null |
| B | `Dex.ProgramAddress` null → `project=unknown` → curve never accumulates | 1/150 had `net_sol_total≠0` but `net_sol_curve=0` | Default `pumpdotfun` when program null / ProtocolName contains pump (query already filters pump programs) |
| C | Q5a lookback reused poll `hours_ago=2` | Truncates create→T0 vs Dune ≤7d | `DEFAULT_Q5A_HOURS_AGO=48` (+ widen to cover); loop uses `q5a_hours_ago` not poll window |
| D | Trades with null `AmountInUSD` dropped | Whale SOL legs lost | Keep trade if SOL amount present; fill USD |

Train sniper rows (curve≥80, buy60≥100k) still score **≥0.999** on exported `q5b_last.joblib` — model/export OK. Live gap is **feature construction**.

### Before / after (journal histgb_q5b, n=150)

Partial repair only (`--recalibrate-journal`): reconstruct SOL from USD on stored vectors (no Bitquery). Full re-enrich blocked by **HTTP 402**.

| | before | after SOL repair |
|--|--------|------------------|
| median score | 0.041 | 0.092 |
| mean score | 0.058 | 0.115 |
| max score | 0.886 | 0.926 |
| n ≥ trainQ top1% (0.999807) | **0** | **0** |

Key column medians (raw live vs train matrix):

| col | train med | live med (raw) | live after SOL repair |
|-----|-----------|----------------|------------------------|
| `buy_vol_usd_60s` | 1938 | 183 | 183 (unchanged; needs re-fetch) |
| `net_sol_curve` | 18.9 | **0** | 0.12 (from USD flow) |
| `progress_curve_proxy` | 0.223 | **0** | 0.0015 |
| `max_buy_sol` | 2.96 | **0** | 0.56 |
| `age_s` | 12 | 50 | 50 |

### Honest residual gap
Even after SOL repair, **0 pass top1%**. Remaining issues:

1. **Volume scale** — live `buy_vol_usd_60s` med ≈10× below train at same MC band (esp. MC 10–12k: train med ~9k / curve 85 vs live ~61 / curve 0). Needs live re-enrich with fixed parse + 48h lookback (402 for now).
2. **trainQ top1% is extreme** — train passers are age≈0 snipers with buy60 ≫ $100k and `net_sol_curve≈85`. Provisional first-sight T0 rarely matches that tail even with correct features.
3. **T0 definition** — live = first sight in band; train = captura C1–C6. Structural, not a unit bug.

### CLI
```bash
# diagnose + dry re-score (no write)
PYTHONPATH=src .venv/bin/python -m paper_live --recalibrate-journal

# write repaired SOL features + scores into journal
PYTHONPATH=src .venv/bin/python -m paper_live --recalibrate-journal --recalibrate-write

# live enrich after Bitquery quota recovers (uses q5a_hours_ago=48)
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --max-calls 8 --q5a-hours-ago 48
```

## Cost (Bitquery)

| Path | Calls / batch of new mints | Notes |
|------|---------------------------|-------|
| Dry-run | 0 | `q5_live_fixture.json` |
| Live full +q5b | **poll 1 + trades 1 + create 1 + priors 1 ≈ 4** | Default `--max-calls 8` → ~2 cycles |
| Live buy60-only (`--no-enrich-q5`) | poll 1 + buy_vol 1 ≈ 2 | Legacy |

**Dune:** not used in live (hours–days lag). Offline WF / batch only.

## Layout

```
src/paper_live/
  entry.py         # ultra-select gate (trainQ + max_per_hour)
  q5a_agg.py       # pure Q5a ≤T0 (Dune SQL parity)
  q5b_agg.py       # pure Q5b creator/age/priors
  helius_enrich.py # hybrid Pump Q5b + Helius Enhanced Q5a/buy60 (default)
  q5_enrich.py     # Bitquery + fixture orchestrator
  pump_enrich.py   # Pump-only Q5b (no trades)
  buy_vol.py       # legacy buy60-only enrich
  features_t0.py # completeness gates
  score.py         # histgb_q5b default; skip if incomplete; export writes calibration
  calibrate.py     # SOL repair + journal re-score (live↔train)
  ...

data/samples/q5_live_fixture.json   # dry-run complete +q5b vectors (bitquery path)
data/samples/helius_enhanced_txs_fixture.json  # dry hybrid Enhanced txs
src/ingestion/helius_enhanced.py     # Enhanced REST client (throttle; no key logs)
data/paper_live/models/q5b_last.joblib  # from --export-model +q5b
data/paper_live/models/q5b_calibration.json  # trainQ thresholds (top1%/top5%)
```

## Cómo arrancar

```bash
cd /workspace/solana-10x
source .venv/bin/activate

# 1) Smoke dry-run with rule_buy60 (no model needed; legacy topk_batch)
PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 3 --top-k 10 \
  --score-mode rule_buy60 --entry-rule topk_batch

# 1b) Enrich-only dry (full +q5b fixture)
PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --enrich-only

# 2) Export trained +q5b last-fold model (offline)
PYTHONPATH=src .venv/bin/python -m paper_live --export-model +q5b

# 3) Dry-run with histgb_q5b (default)
PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 2 --score-mode histgb_q5b

# 4) Live hybrid Pump+Helius (default) — complete +q5b → histgb scores; ultra-select gate
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed pump --enrich-via helius --max-calls 10

# 4b) Enrich-only hybrid smoke
PYTHONPATH=src .venv/bin/python -m paper_live --live --enrich-only --max-calls 6

# 4c) Live Bitquery (optional; ~4 calls/cycle when quota OK)
PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed bitquery --enrich-via bitquery --max-calls 8

# 4b) Journal backtest: how many prior histgb entries pass trainQ top1%
PYTHONPATH=src .venv/bin/python -m paper_live --backtest-entry-gate

# 5) Tests
PYTHONPATH=src .venv/bin/python -m pytest tests/paper_live -q
```


## Schema fix (2026-10-01 Europe/Madrid)

**Root cause:** live Q5a enrich (`QUERY_TRADES_Q5A` in `src/paper_live/q5_enrich.py`) used
`Side: { Type: { in: ["buy", "sell"] } }` — Bitquery rejects **string** literals in
`Trade.Side.Type.in` (`Expected type …Trade_Side_Input, found "buy"`). Error messages
truncated at `since_rel…`, which looked like a `since_relative` bug; that filter is valid
(same as working `buy_vol.py` / docs).

**Fix (Q5a trades):** use unquoted GraphQL enums: `Side: { Type: { in: [buy, sell] } }`.
`Block.Time.since_relative.hours_ago` was fine (message truncated). Poll MC (`Trading.Pairs`) OK.

**Secondary (Q5b Instructions):** `Arguments` is under `Instruction.Program`, not
`Instruction` — Bitquery error `Cannot query field "Arguments" on type …Instruction`.
Queries + `parse_bitquery_creates` updated to `Program.Arguments`.

**Smoke (2026-10-01):** `--live --enrich-only --max-calls 6` → `n_complete_q5b=2`,
`buy_vol_usd_60s` ≈1300 / ≈5239, `q5a_ok=q5b_ok=true`, 51/51 feats. Restart long-running
live process after pull; no kill required unless still on old code.


## Hybrid Helius smoke (2026-10-01 Europe/Madrid)

```bash
PYTHONPATH=src .venv/bin/python -m paper_live --live --enrich-only --feed pump --enrich-via helius --max-calls 6
# → source=live.hybrid.pump+helius; n_complete_q5b≥1 on quiet minutes

PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed pump --enrich-via helius --max-calls 10
# → n_skipped_incomplete_q5b=0, n_skipped_missing_vol=0; scores below trainQ top1% → skip_below_thr (expected)
```

Trading remains **false**. Never print `HELIUS_API_KEY`.

## Gaps / blockers

| Gap | Impacto | Mitigación |
|-----|---------|------------|
| Loose top-K-per-batch entry | Over-enter vs theory P@top | **Fixed:** trainQ top1% + max_per_hour |
| Bitquery FREE 402/429 | Live Bitquery enrich para | **Default `--feed pump`**; Bitquery optional |
| Pump `/trades/all/{mint}` chainId schema | No buy_vol from frontend alone | **Mitigated:** `--enrich-via helius` (default) |
| Enhanced page truncation on hot mints | Undercount early Q5a/sniper | Raise `max_pages_per_mint` / budget credits |
| USD oracle (Pyth preferred) | Scale vs Dune | **Wired:** `ingestion/sol_usd_oracle.py`; Pyth needs `PYTH_API_KEY` (Hermes 401 without) |
| Pump creator list 30d window | Prior undercount | **Wired:** paginate to 30d; residual vs Dune archive possible |
| Joblib ausente | `histgb_q5b` → `skip_missing_model` | `--export-model +q5b` |
| SOL/USD schema drift vs Dune | Scale mismatch on sol/usd feats | Checklist #9–10; calibrate cohort |
| Creator prior coverage ≠ train cohort | Prior magnitude shift | Document; same causal formula |
| Instructions mint parsing fragile | q5b_ok false → skip | Prefer args.mint; Accounts fallback |
| C1–C6 T0 incomplete history | Missed early band cross | **Partial:** `t0_capture.find_t0_c1_c6` when Helius pages cover curve; else LOW |
| Helius streams OFF | No push | Poll pull-only |

## Smoke esperado (dry-run)

- Fixture → `features_complete_q5b=true` for sample mints.  
- `rule_buy60` + `--entry-rule topk_batch`: paper top-K enters; `n_skipped_missing_vol==0`.  
- `histgb_q5b` without model: skip_missing_model (hold).  
- `histgb_q5b` default entry: scores below trainQ top1% → `skip_below_thr` (expect ~0 enters on typical live band).  
- CLI imprime `"trading": false` and `"entry_rule": "train_quantile"`.
