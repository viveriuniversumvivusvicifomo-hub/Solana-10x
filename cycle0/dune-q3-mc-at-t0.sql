-- SolDatos cycle0 — Q3: exact MC / price at T0 for Pump.fun band captures
-- definition_version: dune_cohort_v1 companion
-- Date draft: 2026-09-30 (CEST)
--
-- Goal
-- ----
-- For each mint whose first band-hit trade (MC ∈ [8000, 20000] USD) falls in the
-- last ~30d, return the *exact* T0 trade: mint, t0_ts, mc_usd_t0, price_usd_t0,
-- project_at_t0, tx_id.
--
-- Pricing (same as Q2 T0 logic / task spec — NOT the Q1 hourly VWAP):
--   non-WSOL side token amount
--   price_usd_t0 = amount_usd / tok_amt
--   mc_usd_t0    = price_usd_t0 * 1e9   (Pump supply convention v0)
--
-- Filters aligned with Q2 / dune-wire:
--   project IN ('pumpdotfun', 'pumpswap')
--   WSOL quote pair only
--   amount_usd >= 1
--   Prefer mint LIKE '%pump' (Pump.fun create convention)
--
-- Efficiency / free-plan notes
-- ---------------------------
-- 30d of pumpdotfun+pumpswap is heavy; free plan may timeout (Q1 VWAP query was
-- already borderline). Mitigations if Run fails:
--   1) Shrink to 10d windows and UNION by mint (keep earliest t0_ts).
--   2) Restrict to an uploaded temp table / IN-list of primary_ready mints from
--      data/samples/dune_cohort_v1_labels.csv (primary_ready=true) — see ALT below.
--   3) Add block_date filters / shorter lookback.
-- Do NOT enable Helius streams; this is Dune-only.
--
-- Auth: Dune UI free or DUNE_API_KEY — never write secrets into samples.
-- Export → data/samples/dune_q3_mc_at_t0.csv

WITH t AS (
  SELECT
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_mint_address
      ELSE token_sold_mint_address
    END AS mint,
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_amount
      ELSE token_sold_amount
    END AS tok_amt,
    amount_usd,
    block_time,
    project,
    tx_id
  FROM dex_solana.trades
  WHERE block_time >= NOW() - INTERVAL '30' DAY
    AND blockchain = 'solana'
    AND project IN ('pumpdotfun', 'pumpswap')
    AND (
      token_sold_mint_address = 'So11111111111111111111111111111111111111112'
      OR token_bought_mint_address = 'So11111111111111111111111111111111111111112'
    )
    AND amount_usd >= 1
),
priced AS (
  SELECT
    mint,
    block_time,
    project,
    tx_id,
    amount_usd / NULLIF(tok_amt, 0) AS price_usd,
    (amount_usd / NULLIF(tok_amt, 0)) * 1e9 AS mc_usd
  FROM t
  WHERE tok_amt > 0
    AND mint LIKE '%pump'
),
in_band AS (
  SELECT *
  FROM priced
  WHERE mc_usd BETWEEN 8000 AND 20000
    AND IS_FINITE(mc_usd)
),
ranked AS (
  SELECT
    mint,
    block_time AS t0_ts,
    mc_usd AS mc_usd_t0,
    price_usd AS price_usd_t0,
    project AS project_at_t0,
    tx_id,
    ROW_NUMBER() OVER (
      PARTITION BY mint
      ORDER BY block_time ASC, tx_id ASC
    ) AS rn
  FROM in_band
)
SELECT
  mint,
  t0_ts,
  mc_usd_t0,
  price_usd_t0,
  project_at_t0,
  tx_id
FROM ranked
WHERE rn = 1
ORDER BY t0_ts DESC;

-- =============================================================================
-- ALT (recommended if full 30d times out): restrict to cohort primary_ready mints
-- =============================================================================
-- 1) Export mint list from dune_cohort_v1_labels.csv WHERE primary_ready = true
--    (n_positives_primary_ready + n_negatives_primary_ready; see dune_cohort_v1_meta.json).
-- 2) Upload as a Dune upload / temp table, e.g. dune_cohort_v1_primary_ready(mint varchar)
--    OR paste VALUES / IN list in chunks if >~10k.
-- 3) After computing `mint` in CTE `t`, inner-join before pricing:
--
-- , t_cohort AS (
--     SELECT t.*
--     FROM t
--     INNER JOIN dune_cohort_v1_primary_ready pr ON pr.mint = t.mint
--   )
-- -- then use t_cohort instead of t in `priced`.
--
-- Example VALUES stub (replace with real mints from the CSV — do not invent):
-- WITH cohort(mint) AS (
--   VALUES
--     ('REPLACE_WITH_PRIMARY_READY_MINT_1pump'),
--     ('REPLACE_WITH_PRIMARY_READY_MINT_2pump')
-- )
