-- SolDatos Path A USD — pre-T0 mint-level aggregates (P1 scoped)
-- definition_version: features.dune.p0.path_a_usd.v1
-- Date: 2026-10-01 (CEST / Europe/Madrid)
--
-- PRODUCT
-- -------
--   amount_usd_path_a = sol_amt × sol_usd_asof(block_time)
--   Scale 6.6× OFF. Do NOT use dex_solana.trades.amount_usd as Path A.
--   Aggregate windows rebuilt INSIDE SQL (cheaper than exporting raw legs).
--
-- ORACLE (Dune-native stand-in for live pyth_asof)
-- ------------------------------------------------
--   prices.usd (legacy minute view of prices_external.minute) for WSOL:
--     blockchain = 'solana'
--     contract_address = from_base58('So11111111111111111111111111111111111111112')
--   Join: date_trunc('minute', block_time) = prices.usd.minute
--   Live Path A stamps one pyth_asof(t0) on all legs; minute-asof trade time is
--   the Dune equivalent (≤15m windows → SOL drift residual typically ≪0.1%).
--
-- FILTERS (parity with Q5a / Q4 hygiene 2026-10-01)
-- -------------------------------------------------
--   pumpdotfun+pumpswap, WSOL pair, amount_usd >= 1 (leg inclusion), tok_amt > 0
--   ALL aggs: block_time <= t0_ts. NO labels. NO post-T0.
--
-- OUTPUTS — 13 +q5b USD cols (path-a-train-cohort-plan-20261001.md §3.A)
--   buy_vol_usd_60s, buy_vol_first_10s, buy_vol_first_5s,
--   buy_vol_usd_15m, buy_vol_usd_30s, buy_vol_usd_total,
--   first10_buy_vol_usd, first5_buy_vol_usd, first_buy_usd, max_buy_usd,
--   sell_vol_usd_15m, sell_vol_usd_30s, sell_vol_usd_total
-- Plus diagnostics: sol_usd_asof_median, n_legs_missing_oracle, dune_buy_vol_usd_total
--
-- COHORT / BATCH
-- --------------
-- Default: RUNNER_INJECTS_SAMPLE (same as dune-q5a-microstructure-pre-t0.sql).
-- Runner: reuse src/ingestion/run_dune_q5_api.py pattern — UNION ALL mint+t0,
-- batch_size=100 (300 fails on Q5a). Upload CSV:
--   data/samples/dune_sample_primary_ready_expand_v2_upload.csv (~82k)
-- Alt UI: replace sample CTE with FROM dune.<user>.dataset_... upload table.
--
-- *** NO EXECUTION until Sinck OK (credit estimate first). ***

WITH sample AS (
  -- RUNNER_INJECTS_SAMPLE
  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0
),
bounds AS (
  SELECT
    MIN(t0_ts) - INTERVAL '7' DAY AS t_lo,
    MAX(t0_ts) AS t_hi
  FROM sample
),
-- SOL/USD minute oracle (scoped to batch bounds — do not full-scan prices)
sol_px AS (
  SELECT
    minute AS px_minute,
    CAST(price AS double) AS sol_usd
  FROM prices.usd
  CROSS JOIN bounds b
  WHERE blockchain = 'solana'
    AND contract_address = from_base58('So11111111111111111111111111111111111111112')
    AND minute >= b.t_lo
    AND minute <= b.t_hi
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
    amount_usd AS amount_usd_dune,
    block_time,
    trader_id,
    project,
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_bought_amount
      ELSE token_sold_amount
    END AS tok_amt,
    CASE
      WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
        THEN token_sold_amount
      ELSE token_bought_amount
    END AS sol_amt
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
joined AS (
  SELECT
    s.mint,
    s.t0_ts,
    r.side,
    r.amount_usd_dune,
    r.block_time,
    r.trader_id,
    r.project,
    r.tok_amt,
    r.sol_amt,
    p.sol_usd,
    -- Path A: sol × oracle as-of trade minute
    CASE
      WHEN p.sol_usd IS NOT NULL AND r.sol_amt IS NOT NULL
        THEN r.sol_amt * p.sol_usd
      ELSE NULL
    END AS amount_usd,
    date_diff('second', r.block_time, s.t0_ts) AS secs_before_t0
  FROM sample s
  INNER JOIN raw_sample r
    ON r.mint = s.mint
   AND r.block_time <= s.t0_ts
  LEFT JOIN sol_px p
    ON p.px_minute = date_trunc('minute', r.block_time)
),
-- Drop legs without oracle (should be rare if prices.usd covers window)
priced AS (
  SELECT *
  FROM joined
  WHERE amount_usd IS NOT NULL
),
first_ts AS (
  SELECT mint, t0_ts, MIN(block_time) AS first_trade_ts
  FROM priced
  GROUP BY mint, t0_ts
),
buys AS (
  SELECT
    j.*,
    f.first_trade_ts,
    date_diff('second', f.first_trade_ts, j.block_time) AS secs_after_first,
    ROW_NUMBER() OVER (
      PARTITION BY j.mint, j.t0_ts
      ORDER BY j.block_time ASC, j.amount_usd DESC
    ) AS buy_rn
  FROM priced j
  INNER JOIN first_ts f ON f.mint = j.mint AND f.t0_ts = j.t0_ts
  WHERE j.side = 'buy'
),
flow AS (
  SELECT
    mint,
    t0_ts,
    -- buy60 (Q4 window; Path A USD)
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS buy_vol_usd_60s,
    -- Q5a windows
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS buy_vol_usd_30s,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS sell_vol_usd_30s,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS buy_vol_usd_15m,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS sell_vol_usd_15m,
    SUM(CASE WHEN side = 'buy' THEN amount_usd ELSE 0 END) AS buy_vol_usd_total,
    SUM(CASE WHEN side = 'sell' THEN amount_usd ELSE 0 END) AS sell_vol_usd_total,
    MAX(CASE WHEN side = 'buy' THEN amount_usd ELSE NULL END) AS max_buy_usd,
    -- diagnostics (not in +q5b X; useful for QA)
    SUM(CASE WHEN side = 'buy' THEN amount_usd_dune ELSE 0 END) AS dune_buy_vol_usd_total,
    approx_percentile(sol_usd, 0.5) AS sol_usd_asof_median,
    COUNT(*) AS trade_count_path_a,
    SUM(CASE WHEN side = 'buy' THEN sol_amt ELSE 0 END) AS buy_sol_total_gross
  FROM priced
  GROUP BY mint, t0_ts
),
sniper AS (
  SELECT
    mint,
    t0_ts,
    SUM(CASE WHEN buy_rn <= 5 THEN amount_usd ELSE 0 END) AS first5_buy_vol_usd,
    SUM(CASE WHEN buy_rn <= 10 THEN amount_usd ELSE 0 END) AS first10_buy_vol_usd,
    SUM(CASE WHEN secs_after_first BETWEEN 0 AND 5 THEN amount_usd ELSE 0 END) AS buy_vol_first_5s,
    SUM(CASE WHEN secs_after_first BETWEEN 0 AND 10 THEN amount_usd ELSE 0 END) AS buy_vol_first_10s,
    MAX(CASE WHEN buy_rn = 1 THEN amount_usd END) AS first_buy_usd
  FROM buys
  GROUP BY mint, t0_ts
),
miss AS (
  SELECT
    s.mint,
    s.t0_ts,
    COUNT(*) AS n_legs_missing_oracle
  FROM sample s
  INNER JOIN joined j
    ON j.mint = s.mint AND j.t0_ts = s.t0_ts
  WHERE j.amount_usd IS NULL
  GROUP BY s.mint, s.t0_ts
)
SELECT
  f.mint,
  f.t0_ts,
  -- === 13 +q5b USD cols (Path A) ===
  COALESCE(f.buy_vol_usd_60s, 0) AS buy_vol_usd_60s,
  COALESCE(s.buy_vol_first_10s, 0) AS buy_vol_first_10s,
  COALESCE(s.buy_vol_first_5s, 0) AS buy_vol_first_5s,
  COALESCE(f.buy_vol_usd_15m, 0) AS buy_vol_usd_15m,
  COALESCE(f.buy_vol_usd_30s, 0) AS buy_vol_usd_30s,
  COALESCE(f.buy_vol_usd_total, 0) AS buy_vol_usd_total,
  COALESCE(s.first10_buy_vol_usd, 0) AS first10_buy_vol_usd,
  COALESCE(s.first5_buy_vol_usd, 0) AS first5_buy_vol_usd,
  COALESCE(s.first_buy_usd, 0) AS first_buy_usd,
  f.max_buy_usd,
  COALESCE(f.sell_vol_usd_15m, 0) AS sell_vol_usd_15m,
  COALESCE(f.sell_vol_usd_30s, 0) AS sell_vol_usd_30s,
  COALESCE(f.sell_vol_usd_total, 0) AS sell_vol_usd_total,
  -- diagnostics
  f.sol_usd_asof_median,
  f.dune_buy_vol_usd_total,
  f.buy_sol_total_gross,
  f.trade_count_path_a,
  COALESCE(m.n_legs_missing_oracle, 0) AS n_legs_missing_oracle,
  'path_a_sol_x_prices_usd_minute' AS path_a_oracle_tag,
  false AS apply_dune_helius_usd_scale
FROM flow f
LEFT JOIN sniper s ON s.mint = f.mint AND s.t0_ts = f.t0_ts
LEFT JOIN miss m ON m.mint = f.mint AND m.t0_ts = f.t0_ts
