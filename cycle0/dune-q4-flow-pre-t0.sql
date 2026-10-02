-- SolDatos cycle0 — Q4: pre-T0 flow features (windows ending AT T0)
-- HYGIENE 2026-10-01 (SolDatos): raw_sample requires tok_amt > 0 (same as Q5a). Excludes tok_amt=0 legs (e.g. CREATE_POOL / zero-token) that falsely inflate buy_count_*/buy_vol_usd_*. See cycle0/diagnostics/usd-q4-q5a-parity-anchor-20261001.md
-- definition_version: dune_cohort_v1 companion / features.dune.p0.q3.v1 + flow
-- Date draft: 2026-09-30 (CEST)
--
-- Goal
-- ----
-- For each mint+t0_ts, aggregate DEX trades STRICTLY in
--   [t0_ts - W, t0_ts]  with block_time <= t0_ts  (inclusive T0 trade OK)
-- Windows W ∈ {60 seconds, 5 minutes}.
-- Also: trade_count_total ≤ T0, time_since_first_trade_s, unique traders.
--
-- Buy / sell (same WSOL convention as Q1–Q3):
--   WSOL = So11111111111111111111111111111111111111112
--   BUY  = token_bought_mint_address = mint  (WSOL sold)
--   SELL = token_sold_mint_address   = mint  (WSOL bought)
-- Filters: project IN ('pumpdotfun','pumpswap'), WSOL pair, amount_usd >= 1, tok_amt > 0 (Q5a parity; HYGIENE 2026-10-01).
--
-- NO labels. NO post-T0 trades. Streams Helius OFF.
-- Preferred path on free plan = Q4b (upload sample). Q4a is heavy self-contained.
--
-- Outputs (per mint):
--   buy_count_60s, sell_count_60s, buy_vol_usd_60s, sell_vol_usd_60s,
--   unique_traders_60s,
--   buy_count_5m,  sell_count_5m,  buy_vol_usd_5m,  sell_vol_usd_5m,
--   unique_traders_5m,
--   trade_count_total, time_since_first_trade_s, unique_traders_total
--
-- Auth: Dune UI free or DUNE_API_KEY — never write secrets into samples.
-- Export → data/samples/dune_q4_flow_pre_t0_sample_v1.csv
--
-- HOW TO RUN
-- ----------
-- Default below = Q4b (upload join). To run Q4a instead, comment out Q4b and
-- uncomment the Q4a block.

-- =============================================================================
-- Q4b — RECOMMENDED (free plan): join against uploaded sample mint+t0_ts
-- =============================================================================
-- Steps for Sinck:
--   1) Upload data/samples/dune_sample_primary_ready_v1.csv to Dune as a table
--      named dune_sample_primary_ready_v1 with at least:
--        mint varchar, t0_ts timestamp  (extra cols OK; ignored)
--      Adjust FROM below if Dune prefixes the upload
--      (e.g. dune.<user>.dataset_dune_sample_primary_ready_v1).
--   2) Run this query → Export CSV →
--      data/samples/dune_q4_flow_pre_t0_sample_v1.csv
--   3) Merge into feature store later (still NO label columns).
-- =============================================================================

WITH sample AS (
  SELECT
    CAST(mint AS varchar) AS mint,
    CAST(t0_ts AS timestamp) AS t0_ts
  FROM dune_sample_primary_ready_v1
),
bounds AS (
  SELECT
    MIN(t0_ts) - INTERVAL '7' DAY AS t_lo,
    MAX(t0_ts) AS t_hi
  FROM sample
),
raw AS (
  SELECT
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_mint_address
      ELSE token_sold_mint_address
    END AS mint,
    CASE
      WHEN token_bought_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN 'buy'
      WHEN token_sold_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_bought_mint_address = 'So11111111111111111111111111111111111111112'
        THEN 'sell'
      ELSE NULL
    END AS side,
    amount_usd,
    block_time,
    trader_id,
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_bought_amount ELSE token_sold_amount END AS tok_amt
  FROM dex_solana.trades
  CROSS JOIN bounds b
  WHERE block_time >= b.t_lo
    AND block_time <= b.t_hi
    AND blockchain = 'solana'
    AND project IN ('pumpdotfun', 'pumpswap')
    AND (
      token_sold_mint_address = 'So11111111111111111111111111111111111111112'
      OR token_bought_mint_address = 'So11111111111111111111111111111111111111112'
    )
    AND amount_usd >= 1
),
raw_sample AS (
  SELECT r.*
  FROM raw r
  INNER JOIN (SELECT DISTINCT mint FROM sample) s ON s.mint = r.mint
  WHERE r.side IS NOT NULL
    AND r.tok_amt > 0
),
joined_all AS (
  SELECT
    s.mint,
    s.t0_ts,
    r.side,
    r.amount_usd,
    r.block_time,
    r.trader_id,
    date_diff('second', r.block_time, s.t0_ts) AS secs_before_t0
  FROM sample s
  INNER JOIN raw_sample r
    ON r.mint = s.mint
   AND r.block_time <= s.t0_ts
)
SELECT
  mint,
  t0_ts,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN 1 ELSE 0 END) AS buy_count_60s,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 60 THEN 1 ELSE 0 END) AS sell_count_60s,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS buy_vol_usd_60s,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS sell_vol_usd_60s,
  COUNT(DISTINCT CASE WHEN secs_before_t0 BETWEEN 0 AND 60 THEN trader_id END) AS unique_traders_60s,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 300 THEN 1 ELSE 0 END) AS buy_count_5m,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 300 THEN 1 ELSE 0 END) AS sell_count_5m,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 300 THEN amount_usd ELSE 0 END) AS buy_vol_usd_5m,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 300 THEN amount_usd ELSE 0 END) AS sell_vol_usd_5m,
  COUNT(DISTINCT CASE WHEN secs_before_t0 BETWEEN 0 AND 300 THEN trader_id END) AS unique_traders_5m,
  COUNT(*) AS trade_count_total,
  COUNT(DISTINCT trader_id) AS unique_traders_total,
  MAX(secs_before_t0) AS time_since_first_trade_s
FROM joined_all
GROUP BY mint, t0_ts
ORDER BY t0_ts DESC;

-- =============================================================================
-- Q4a — SELF-CONTAINED HEAVY (all band T0 mints in ~30d) — DO NOT paste with Q4b
-- =============================================================================
-- Reconstructs T0 the same way as Q3, then aggregates pre-T0 flow for EVERY
-- band mint. Likely to timeout / hit free-plan limits. Prefer Q4b above.
-- To run: comment out the entire Q4b WITH…SELECT above, then uncomment below.
-- =============================================================================

/*
WITH t AS (
  SELECT
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_mint_address
      ELSE token_sold_mint_address
    END AS mint,
    CASE
      WHEN token_bought_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN 'buy'
      WHEN token_sold_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_bought_mint_address = 'So11111111111111111111111111111111111111112'
        THEN 'sell'
      ELSE NULL
    END AS side,
    amount_usd,
    block_time,
    trader_id,
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_amount
      ELSE token_sold_amount
    END AS tok_amt
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
    side,
    amount_usd,
    block_time,
    trader_id,
    (amount_usd / NULLIF(tok_amt, 0)) * 1e9 AS mc_usd
  FROM t
  WHERE tok_amt > 0
    AND mint LIKE '%pump'
    AND side IS NOT NULL
),
in_band AS (
  SELECT mint, block_time AS t0_ts, mc_usd
  FROM priced
  WHERE mc_usd BETWEEN 8000 AND 20000
    AND IS_FINITE(mc_usd)
),
t0 AS (
  SELECT mint, t0_ts
  FROM (
    SELECT
      mint,
      t0_ts,
      ROW_NUMBER() OVER (PARTITION BY mint ORDER BY t0_ts ASC) AS rn
    FROM in_band
  ) x
  WHERE rn = 1
),
joined AS (
  SELECT
    p.mint,
    t0.t0_ts,
    p.side,
    p.amount_usd,
    p.block_time,
    p.trader_id,
    date_diff('second', p.block_time, t0.t0_ts) AS secs_before_t0
  FROM priced p
  INNER JOIN t0 ON t0.mint = p.mint
  WHERE p.block_time <= t0.t0_ts
)
SELECT
  mint,
  t0_ts,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN 1 ELSE 0 END) AS buy_count_60s,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 60 THEN 1 ELSE 0 END) AS sell_count_60s,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS buy_vol_usd_60s,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS sell_vol_usd_60s,
  COUNT(DISTINCT CASE WHEN secs_before_t0 BETWEEN 0 AND 60 THEN trader_id END) AS unique_traders_60s,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 300 THEN 1 ELSE 0 END) AS buy_count_5m,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 300 THEN 1 ELSE 0 END) AS sell_count_5m,
  SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 300 THEN amount_usd ELSE 0 END) AS buy_vol_usd_5m,
  SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 300 THEN amount_usd ELSE 0 END) AS sell_vol_usd_5m,
  COUNT(DISTINCT CASE WHEN secs_before_t0 BETWEEN 0 AND 300 THEN trader_id END) AS unique_traders_5m,
  COUNT(*) AS trade_count_total,
  COUNT(DISTINCT trader_id) AS unique_traders_total,
  MAX(secs_before_t0) AS time_since_first_trade_s
FROM joined
GROUP BY mint, t0_ts
ORDER BY t0_ts DESC;
*/
