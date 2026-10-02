# Live ↔ train feature recipe parity (SolModelos)

**Date:** 2026-10-01  
**Score set:** `FEATURE_SETS['+q5b']` (51 cols) · model `data/paper_live/models/q5b_last.joblib`

## Rule
Live enrich → score vector **must** be the same columns (name + order) as WF train.  
Source of truth: `src/features/post_q5_sets.py`. Gate: `src/paper_live/recipe_parity.py`.

Banned from X (journal OK): `creator_pubkey`, `create_ts`, `migrated_pre_t0`, labels.

## USD (data parity — SolDatos)
Live: `amount_usd = sol_amt * sol_usd_asof_t0` (Pyth preferred).  
Train Dune: `AmountInUSD`. Scale drift ≠ column recipe bug — fix oracle / historical px, then re-score.

## Re-score after Helius/T0/oracle fixes
```bash
# Sanity: train store vs OOS (expect Δ≈0 on fold-5)
PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay --out-prefix rescore_train_store_sanity

# After rebuild CSV from SolDatos (full +q5b cols, ≤T0)
PYTHONPATH=src .venv/bin/python -m paper_live.rescore_replay \
  --features-csv path/to/helius_rebuild_features.csv \
  --out-prefix rescore_helius_rebuild
```

Outputs under `cycle0/artifacts/rescore_*`.
