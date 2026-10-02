# USD Q4 ↔ Q5a parity anchor — 2026-10-01

**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`  
**Status:** **AUTHORITATIVE** for live Path A ↔ train USD parity  
**Evidence:** `cycle0/diagnostics/usd-path-a-vs-dune-ge10-20261001.md`  
**Paper live:** FROZEN (untouched) · n=200 enrich: do not block

---

## Verdict (BOSS close)

| Claim | Rule |
|-------|------|
| **Path A ≈ Q5a** | Live Path A `amount_usd = sol_amt × pyth_asof` matches **Q5a** `buy_vol_usd_total` (filter `tok_amt > 0`) within ~0.1–1%. |
| **Q4 is NOT the parity target when counts differ** | Do **not** compare Path A / live `buy_vol_usd_60s` to train **Q4** `buy_vol_usd_60s` when `buy_count_60s ≠ buy_count_total` (Q5a). Q4 can falsely **+1 buy** (2hCEWY: 7 vs 6; +≈`max_buy_usd`). |
| **Scale 6.6×** | **OFF forever** for this path. `APPLY_DUNE_HELIUS_USD_SCALE` must stay False. Blind scale rejected by firmas + Path A hunt. |

Smoking gun (2hCEWY):

```
live Path A Σ / Q4 buy_vol_usd_60s   = 17638.78 / 25228.54 ≈ 0.70   ← false train leg
live Path A Σ / Q5a buy_vol_usd_total = 17638.78 / 17610.97 ≈ 1.0016 ← parity anchor
```

Root cause: Q4 raw CTE lacked `tok_amt > 0` (Q5a has it). Zero-token / CREATE_POOL-class rows inflate Q4 buy counts/vol.

---

## Policy for SolAuditor / SolModelos

1. **Exact USD train column for Path A parity:** use **Q5a** `buy_vol_usd_total` (and Q5a buy counts), **or** Q4 `buy_vol_usd_60s` **only after** hygiene (`tok_amt > 0`) and count consistency with Q5a.
2. When auditing live vs store and `buy_count_60s (Q4) ≠ buy_count_total (Q5a)`, treat Q4 `buy_vol_usd_60s` as **contaminated** — score/feature Δ vs that column is not an oracle bug.
3. Residual after Q4 hygiene: expect **≲1%** vol bias (fee net vs gross / pyth vs Dune implied), **not** 30% and **not** 6.6×.
4. Optional later: SolModelos may reprice train USD as `sol × pyth_asof(t0)` for ZERO-tolerance score equality; not required to close the 0.70 smoking gun.

---

## What SolDatos shipped (this close)

### 1. SQL hygiene (no Dune credits spent)

Q4 buy path now matches Q5a: `raw` selects `tok_amt`; `raw_sample` requires `r.tok_amt > 0`.

| Path | Change |
|------|--------|
| `cycle0/dune-q4-flow-pre-t0.sql` | Q4b active CTE + header Filters line |
| `cycle0/dune-q4-flow-pre-t0-inline.sql` | same |
| `cycle0/q4_batches/*.sql` (incl. runner template `dune-q4-b05of20.sql`, smoke) | same |
| `src/ingestion/run_dune_q4_api.py` | docstring points at this anchor; future batches inherit template suffix |

Q4a commented self-contained block already filtered `tok_amt > 0` via `priced` CTE (unchanged semantics).

### 2. Offline overlay (ge10) — no API

| Artifact | Role |
|----------|------|
| `data/samples/features_buy_vol_q5a_overlay_ge10_20261001.csv` | mint → Q5a `buy_vol` / counts vs Q4; `use_q5a_for_parity=1` on 2hCEWY |
| `scripts/patch_q4_buy_vol_from_q5a_overlay_20261001.py` | rebuilds local `buy_vol_usd_60s` (+ count) from Q5a for flagged mints |

**Applied** (flagged only): `dune_q4_flow_expand_v2.csv`, `features_dune_p0_flow_expand_v2.csv`, `features_dune_p0_q5_expand_v2.csv` — 2hCEWY `buy_count_60s=6`, `buy_vol_usd_60s=17610.97…`. Backups: `*.bak_pre_q5a_20261001`.

### 3. Explicitly not done

- No Dune full expand re-export (credits; needs BOSS approval).
- No paper_live restart / touch.
- No fight with n=200 enrich agent.

---

## Dune re-export still needed?

| Scope | Needed? |
|-------|---------|
| **ge10 / Path A parity close** | **No** — SQL fixed for future runs; local CSVs overlaid from Q5a for 2hCEWY. |
| **Full train store / expand_v2 population (~17k mints with \|Q4/Q5a−1\|>1%)** | **Yes, only with BOSS approval** — re-run Q4 expand with hygienic SQL, or batch-offline patch from Q5a for all count-mismatched mints. Do not spend credits without that approval. |

---

## Pointers

- Hunt detail: `cycle0/diagnostics/usd-path-a-vs-dune-ge10-20261001.md`
- Live oracle policy: `cycle0/live-usd-oracle-parity.md` (Path A, scale OFF)
- Q5a filter reference: `cycle0/q5_sql/dune-q5a-microstructure-pre-t0.sql` (`raw_sample … AND r.tok_amt > 0`)
