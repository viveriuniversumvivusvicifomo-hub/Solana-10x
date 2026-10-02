# Q5b meta features train parity — 2026-10-01

**Owner:** SolModelos · Paper live **FROZEN** (untouched) · No joblib retrain · Scale 6.6× OFF

## Problem

Live Q5b rebuild / ge10 dump path often left `name_len`/`symbol_len`=0 and
`name_missing`/`symbol_missing`=1 even when the mint is in the Dune train store
(`features_dune_p0_q5_expand_v2.csv`) with nonzero lengths. Evidence:
`cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv` + recovery note for
`2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump` (train name_len=symbol_len=**7**;
live=0). Soft Δscore oos−live ~**2e-3** partly from this meta gap (remainder =
Path A pyth USD ≠ Dune `amount_usd`).

## Trades (context)

2hCEWY buy_count ≤T0 is already **6=6** vs train (SolDatos recovery closed). This note is **meta-only** (`name_len`/`symbol_len`); do not re-open trade-count work.

## Resolution order (live)

1. **CreateEvent / Pump coin** name+symbol on `CreateRow` → `q5b_from_create`
   (`meta_source=create` when present).
2. **`prefer_sighting_meta_name_symbol`** — Pairs/sighting meta for live coins
   (`meta_source=sighting`). Kept as-is for coins with sighting meta.
3. **`fill_meta_from_dune_store_exact`** — if still missing **and** mint ∈ train
   store: copy exact `name_len` / `symbol_len` / `name_missing` /
   `symbol_missing`. Stamp `meta_source=dune_store_exact` (+ gap).
   **Does not invent names** — lengths only for score parity.

Wired in: `helius_enrich.py`, `pump_enrich.py`, `q5_enrich.py`.
Store index: `CreatorPriorIndex.by_mint_meta` / `exact_meta_for_mint` in
`creator_priors.py` (same expand_v2 / q5b CSV as priors).

## 2hCEWY resolve

| col | train store | live before | live after (store fill) |
|-----|------------:|------------:|------------------------:|
| name_len | 7 | 0 | **7** |
| symbol_len | 7 | 0 | **7** |
| name_missing | 0 | 1 | **0** |
| symbol_missing | 0 | 1 | **0** |
| meta_source | — | — | `dune_store_exact` |

Other ge10 with same meta Δ (store fill applies when mint∈store): 69xne…,
BZof…, wbf55…, 2ahcm…, 4M3g… (see feature-Δ CSV).

## Residual

- **USD / vol family** still diverges (Path A `sol×pyth_asof` vs Dune
  `amount_usd`) — dominant residual on 2hCEWY buy_vol_usd_60s (~−30%).
  Scale 6.6× stays OFF; no blind USD invent.
- Full Helius re-enrich of ge10 / journal not run here (HELIUS contention +
  paper FROZEN). **SolDatos** should re-run enrich/parity with this fix for
  production live scores; store-meta-only rescore of snapshot feats is a
  diagnostic only (see below / diagnostics).

## Tests

`tests/paper_live/test_q5b_meta_store_parity.py`

## Related

- `cycle0/diagnostics/helius-recovery-2hCEWY-20261001.md`
- `cycle0/diagnostics/helius_ge10_feature_delta_20261001.csv`
- `cycle0/live-vs-train-mismatch-hunt-20261001.md` (meta secondary)
