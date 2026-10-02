-- SolDatos Path A USD — ge10 SMOKE (12 mints) — cheapest validation before paid full run
-- definition_version: features.dune.p0.path_a_usd.v1.smoke_ge10
-- Date: 2026-10-01 (CEST)
--
-- Upload CSV (optional): data/samples/dune_path_a_usd_ge10_smoke_upload.csv
--   → Dune table e.g. dune_path_a_usd_ge10_smoke_upload (mint, t0_ts)
-- Inline sample below = same 12 ge10 mints (no upload needed).
--
-- Compare export vs:
--   data/samples/features_ge10_path_a_usd_pilot_20261001.csv  (Helius Path A pilot)
-- Expect: ≤~1% on vol cols (Dune gross sol vs Helius fee-net; prices.usd vs pyth_asof).
--
-- *** NO EXECUTION until Sinck OK. Cap credits ≤50 for this smoke. ***

WITH sample AS (
  -- Inline ge10 (from features_ge10_path_a_usd_pilot_20261001.csv)
  SELECT * FROM (
    VALUES
      ('4M3gYZ2dQ39KuBuJYVmQi5qrtFfMpMWHpJhhx7Wapump', TIMESTAMP '2026-09-22 07:03:04'),
      ('G4G4cN8BLGaDe7yS7KSwegFDPACaBbM2d1ZFXYhMpump', TIMESTAMP '2026-09-22 05:50:37'),
      ('4X9d1Mc1cXJUFXtADbAuMkQniK9411dvAP1ovCFopump', TIMESTAMP '2026-09-22 06:05:17'),
      ('2ahcm3vhbPTi7WzECWW7Jb7uP4mEyVRCHsRTzvaDpump', TIMESTAMP '2026-09-22 06:21:58'),
      ('wbf55KygjChmSMkTeVTmQ3j7vuGqVdKQbdRfg6epump', TIMESTAMP '2026-09-22 06:42:20'),
      ('2DU2GNLBhXg2GqkgCnDf6uFWREp9dFeUhU1SRmT2pump', TIMESTAMP '2026-09-22 03:54:37'),
      ('56ofoyzfMaGwzgeeTsTchJuVM8Trx5GHhW9pxh9Jpump', TIMESTAMP '2026-09-21 19:19:59'),
      ('6mCCo1Abfz2riT4UcgaVq4Hs5ZGxYjgxjhizDfnfpump', TIMESTAMP '2026-09-22 00:22:37'),
      ('BZofTtkyrBM2EDdRBN6GCavdWvxd61xbLTVFnoPgpump', TIMESTAMP '2026-09-22 15:29:59'),
      ('wXcbD8Sr23SoN1J8zE7i6Js4EaoCDAFWkUhdoe8pump', TIMESTAMP '2026-09-22 03:16:47'),
      ('69xneXbByUnx7WtEC7tqHHo1NJoXJqM9dNFYYu8pump', TIMESTAMP '2026-09-22 16:55:10'),
      ('2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump', TIMESTAMP '2026-09-22 01:41:06')
  ) AS t(mint, t0_ts)
  -- Alt upload (comment VALUES, uncomment):
  -- SELECT CAST(mint AS varchar) AS mint, CAST(t0_ts AS timestamp) AS t0_ts
  -- FROM dune_path_a_usd_ge10_smoke_upload
),
bounds AS (
  SELECT MIN(t0_ts) - INTERVAL '7' DAY AS t_lo, MAX(t0_ts) AS t_hi FROM sample
),
sol_px AS (
  SELECT minute AS px_minute, CAST(price AS double) AS sol_usd
  FROM prices.usd
  CROSS JOIN bounds b
  WHERE blockchain = 'solana'
    AND contract_address = from_base58('So11111111111111111111111111111111111111112')
    AND minute >= b.t_lo
    AND minute <= b.t_hi
),
raw AS (
  SELECT
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_bought_mint_address ELSE token_sold_mint_address END AS mint,
    CASE
      WHEN token_bought_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_sold_mint_address = 'So11111111111111111111111111111111111111112' THEN 'buy'
      WHEN token_sold_mint_address <> 'So11111111111111111111111111111111111111112'
           AND token_bought_mint_address = 'So11111111111111111111111111111111111111112' THEN 'sell'
      ELSE NULL END AS side,
    amount_usd AS amount_usd_dune,
    block_time,
    trader_id,
    project,
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_bought_amount ELSE token_sold_amount END AS tok_amt,
    CASE WHEN token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         THEN token_sold_amount ELSE token_bought_amount END AS sol_amt
  FROM dex_solana.trades
  CROSS JOIN bounds b
  WHERE block_time >= b.t_lo
    AND block_time <= b.t_hi
    AND blockchain = 'solana'
    AND project IN ('pumpdotfun', 'pumpswap')
    AND (token_sold_mint_address = 'So11111111111111111111111111111111111111112'
         OR token_bought_mint_address = 'So11111111111111111111111111111111111111112')
    AND amount_usd >= 1
),
raw_sample AS (
  SELECT r.*
  FROM raw r
  INNER JOIN (SELECT DISTINCT mint FROM sample) s ON s.mint = r.mint
  WHERE r.side IS NOT NULL AND r.tok_amt > 0
),
joined AS (
  SELECT
    s.mint, s.t0_ts, r.side, r.amount_usd_dune, r.block_time, r.trader_id, r.project,
    r.tok_amt, r.sol_amt, p.sol_usd,
    CASE WHEN p.sol_usd IS NOT NULL AND r.sol_amt IS NOT NULL
         THEN r.sol_amt * p.sol_usd ELSE NULL END AS amount_usd,
    date_diff('second', r.block_time, s.t0_ts) AS secs_before_t0
  FROM sample s
  INNER JOIN raw_sample r ON r.mint = s.mint AND r.block_time <= s.t0_ts
  LEFT JOIN sol_px p ON p.px_minute = date_trunc('minute', r.block_time)
),
priced AS (
  SELECT * FROM joined WHERE amount_usd IS NOT NULL
),
first_ts AS (
  SELECT mint, t0_ts, MIN(block_time) AS first_trade_ts
  FROM priced GROUP BY mint, t0_ts
),
buys AS (
  SELECT
    j.*, f.first_trade_ts,
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
    mint, t0_ts,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 60 THEN amount_usd ELSE 0 END) AS buy_vol_usd_60s,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS buy_vol_usd_30s,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS sell_vol_usd_30s,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS buy_vol_usd_15m,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS sell_vol_usd_15m,
    SUM(CASE WHEN side = 'buy' THEN amount_usd ELSE 0 END) AS buy_vol_usd_total,
    SUM(CASE WHEN side = 'sell' THEN amount_usd ELSE 0 END) AS sell_vol_usd_total,
    MAX(CASE WHEN side = 'buy' THEN amount_usd ELSE NULL END) AS max_buy_usd,
    SUM(CASE WHEN side = 'buy' THEN amount_usd_dune ELSE 0 END) AS dune_buy_vol_usd_total,
    approx_percentile(sol_usd, 0.5) AS sol_usd_asof_median,
    COUNT(*) AS trade_count_path_a,
    SUM(CASE WHEN side = 'buy' THEN sol_amt ELSE 0 END) AS buy_sol_total_gross
  FROM priced
  GROUP BY mint, t0_ts
),
sniper AS (
  SELECT
    mint, t0_ts,
    SUM(CASE WHEN buy_rn <= 5 THEN amount_usd ELSE 0 END) AS first5_buy_vol_usd,
    SUM(CASE WHEN buy_rn <= 10 THEN amount_usd ELSE 0 END) AS first10_buy_vol_usd,
    SUM(CASE WHEN secs_after_first BETWEEN 0 AND 5 THEN amount_usd ELSE 0 END) AS buy_vol_first_5s,
    SUM(CASE WHEN secs_after_first BETWEEN 0 AND 10 THEN amount_usd ELSE 0 END) AS buy_vol_first_10s,
    MAX(CASE WHEN buy_rn = 1 THEN amount_usd END) AS first_buy_usd
  FROM buys
  GROUP BY mint, t0_ts
)
SELECT
  f.mint,
  f.t0_ts,
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
  f.sol_usd_asof_median,
  f.dune_buy_vol_usd_total,
  f.buy_sol_total_gross,
  f.trade_count_path_a,
  'path_a_sol_x_prices_usd_minute' AS path_a_oracle_tag,
  false AS apply_dune_helius_usd_scale
FROM flow f
LEFT JOIN sniper s ON s.mint = f.mint AND s.t0_ts = f.t0_ts
ORDER BY f.mint
