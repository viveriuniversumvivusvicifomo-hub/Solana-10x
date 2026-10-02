-- SolDatos Q5a — pre-T0 microstructure / concentration / sniper / progress proxies
-- definition_version: dune_cohort_v1 companion / features.dune.p0.q5a.v1
-- Date: 2026-09-30 (CEST)
--
-- Anti-lookahead: ALL aggregates use block_time <= t0_ts only.
-- NO labels. NO post-T0. Streams Helius OFF.
-- Tables: dex_solana.trades only (WSOL pair, pumpdotfun+pumpswap, amount_usd>=1).
-- Batch: UNION ALL sample CTE (~300 mints). Placeholders replaced by runner.
--
-- Outputs (per mint+t0): see FEATURE_COLS in run_dune_q5_api.py

WITH sample AS (
  -- RUNNER_INJECTS_SAMPLE
  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0
),
bounds AS (
  SELECT MIN(t0_ts) - INTERVAL '7' DAY AS t_lo, MAX(t0_ts) AS t_hi FROM sample
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
    amount_usd,
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
  WHERE r.side IS NOT NULL
    AND r.tok_amt > 0
),
joined AS (
  SELECT
    s.mint,
    s.t0_ts,
    r.side,
    r.amount_usd,
    r.block_time,
    r.trader_id,
    r.project,
    r.tok_amt,
    r.sol_amt,
    date_diff('second', r.block_time, s.t0_ts) AS secs_before_t0
  FROM sample s
  INNER JOIN raw_sample r
    ON r.mint = s.mint
   AND r.block_time <= s.t0_ts
),
first_ts AS (
  SELECT mint, t0_ts, MIN(block_time) AS first_trade_ts
  FROM joined
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
  FROM joined j
  INNER JOIN first_ts f ON f.mint = j.mint AND f.t0_ts = j.t0_ts
  WHERE j.side = 'buy'
),
trader_agg AS (
  SELECT
    mint,
    t0_ts,
    trader_id,
    SUM(CASE WHEN side = 'buy' THEN amount_usd ELSE 0 END) AS buy_usd,
    SUM(CASE WHEN side = 'sell' THEN amount_usd ELSE 0 END) AS sell_usd,
    SUM(CASE WHEN side = 'buy' THEN tok_amt ELSE -tok_amt END) AS net_tok,
    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) AS n_buys,
    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) AS n_sells
  FROM joined
  GROUP BY mint, t0_ts, trader_id
),
trader_ranked AS (
  SELECT
    mint,
    t0_ts,
    trader_id,
    buy_usd,
    sell_usd,
    net_tok,
    ROW_NUMBER() OVER (PARTITION BY mint, t0_ts ORDER BY buy_usd DESC) AS rn_buy_vol,
    ROW_NUMBER() OVER (
      PARTITION BY mint, t0_ts
      ORDER BY CASE WHEN net_tok > 0 THEN net_tok ELSE NULL END DESC NULLS LAST
    ) AS rn_hold
  FROM trader_agg
),
flow AS (
  SELECT
    mint,
    t0_ts,
    -- extra windows beyond Q4 (30s, 15m)
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 30 THEN 1 ELSE 0 END) AS buy_count_30s,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 30 THEN 1 ELSE 0 END) AS sell_count_30s,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS buy_vol_usd_30s,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 30 THEN amount_usd ELSE 0 END) AS sell_vol_usd_30s,
    COUNT(DISTINCT IF(secs_before_t0 BETWEEN 0 AND 30, trader_id, NULL)) AS unique_traders_30s,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 900 THEN 1 ELSE 0 END) AS buy_count_15m,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 900 THEN 1 ELSE 0 END) AS sell_count_15m,
    SUM(CASE WHEN side = 'buy'  AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS buy_vol_usd_15m,
    SUM(CASE WHEN side = 'sell' AND secs_before_t0 BETWEEN 0 AND 900 THEN amount_usd ELSE 0 END) AS sell_vol_usd_15m,
    COUNT(DISTINCT IF(secs_before_t0 BETWEEN 0 AND 900, trader_id, NULL)) AS unique_traders_15m,
    -- unique buyers/sellers ≤ T0
    COUNT(DISTINCT IF(side = 'buy', trader_id, NULL)) AS unique_buyers_total,
    COUNT(DISTINCT IF(side = 'sell', trader_id, NULL)) AS unique_sellers_total,
    SUM(CASE WHEN side = 'buy' THEN 1 ELSE 0 END) AS buy_count_total,
    SUM(CASE WHEN side = 'sell' THEN 1 ELSE 0 END) AS sell_count_total,
    SUM(CASE WHEN side = 'buy' THEN amount_usd ELSE 0 END) AS buy_vol_usd_total,
    SUM(CASE WHEN side = 'sell' THEN amount_usd ELSE 0 END) AS sell_vol_usd_total,
    -- SOL net flow (progress proxy numerator); Pump grad ~85 SOL real
    SUM(CASE WHEN side = 'buy' THEN sol_amt ELSE -sol_amt END) AS net_sol_total,
    SUM(CASE WHEN side = 'buy' AND project = 'pumpdotfun' THEN sol_amt
             WHEN side = 'sell' AND project = 'pumpdotfun' THEN -sol_amt
             ELSE 0 END) AS net_sol_curve,
    -- migration flag ≤ T0 only
    MAX(CASE WHEN project = 'pumpswap' THEN 1 ELSE 0 END) AS migrated_pre_t0,
    -- max single buy
    MAX(CASE WHEN side = 'buy' THEN amount_usd ELSE NULL END) AS max_buy_usd,
    MAX(CASE WHEN side = 'buy' THEN sol_amt ELSE NULL END) AS max_buy_sol,
    COUNT(*) AS trade_count_total_q5,
    COUNT(DISTINCT trader_id) AS unique_traders_total_q5,
    MAX(secs_before_t0) AS age_proxy_s
  FROM joined
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
    SUM(CASE WHEN buy_rn <= 5 THEN 1 ELSE 0 END) AS n_first5_buys,
    COUNT(DISTINCT IF(buy_rn <= 5, trader_id, NULL)) AS unique_buyers_first5,
    COUNT(DISTINCT IF(secs_after_first BETWEEN 0 AND 5, trader_id, NULL)) AS unique_buyers_first_5s,
    MAX(CASE WHEN buy_rn = 1 THEN amount_usd END) AS first_buy_usd,
    SUM(amount_usd) AS buy_vol_all_buys
  FROM buys
  GROUP BY mint, t0_ts
),
conc AS (
  SELECT
    mint,
    t0_ts,
    MAX(CASE WHEN rn_buy_vol = 1 THEN buy_usd END) AS top1_buyer_usd,
    SUM(CASE WHEN rn_buy_vol <= 5 THEN buy_usd ELSE 0 END) AS top5_buyer_usd,
    SUM(CASE WHEN rn_buy_vol <= 10 THEN buy_usd ELSE 0 END) AS top10_buyer_usd,
    SUM(buy_usd) AS sum_buyer_usd,
    -- trade-based holder concentration (net positive token positions)
    MAX(CASE WHEN rn_hold = 1 AND net_tok > 0 THEN net_tok END) AS top1_net_tok,
    SUM(CASE WHEN rn_hold <= 5 AND net_tok > 0 THEN net_tok ELSE 0 END) AS top5_net_tok,
    SUM(CASE WHEN rn_hold <= 10 AND net_tok > 0 THEN net_tok ELSE 0 END) AS top10_net_tok,
    SUM(CASE WHEN net_tok > 0 THEN net_tok ELSE 0 END) AS sum_pos_net_tok,
    COUNT(CASE WHEN net_tok > 0 THEN 1 END) AS n_pos_holders_proxy,
    COUNT(CASE WHEN net_tok > 0 AND buy_usd > 0 THEN 1 END) AS n_holders_proxy
  FROM trader_ranked
  GROUP BY mint, t0_ts
)
SELECT
  f.mint,
  f.t0_ts,
  f.buy_count_30s,
  f.sell_count_30s,
  f.buy_vol_usd_30s,
  f.sell_vol_usd_30s,
  f.unique_traders_30s,
  f.buy_count_15m,
  f.sell_count_15m,
  f.buy_vol_usd_15m,
  f.sell_vol_usd_15m,
  f.unique_traders_15m,
  f.unique_buyers_total,
  f.unique_sellers_total,
  f.buy_count_total,
  f.sell_count_total,
  f.buy_vol_usd_total,
  f.sell_vol_usd_total,
  f.net_sol_total,
  f.net_sol_curve,
  CASE WHEN f.net_sol_curve IS NULL THEN NULL
       ELSE LEAST(GREATEST(f.net_sol_curve / 85.0, 0.0), 2.0) END AS progress_curve_proxy,
  f.migrated_pre_t0,
  f.max_buy_usd,
  f.max_buy_sol,
  f.age_proxy_s,
  COALESCE(s.first5_buy_vol_usd, 0) AS first5_buy_vol_usd,
  COALESCE(s.first10_buy_vol_usd, 0) AS first10_buy_vol_usd,
  COALESCE(s.buy_vol_first_5s, 0) AS buy_vol_first_5s,
  COALESCE(s.buy_vol_first_10s, 0) AS buy_vol_first_10s,
  COALESCE(s.unique_buyers_first5, 0) AS unique_buyers_first5,
  COALESCE(s.unique_buyers_first_5s, 0) AS unique_buyers_first_5s,
  COALESCE(s.first_buy_usd, 0) AS first_buy_usd,
  CASE WHEN COALESCE(s.buy_vol_all_buys, 0) > 0
       THEN COALESCE(s.first5_buy_vol_usd, 0) / s.buy_vol_all_buys ELSE NULL END AS first5_buy_vol_share,
  CASE WHEN COALESCE(s.buy_vol_all_buys, 0) > 0
       THEN COALESCE(s.buy_vol_first_5s, 0) / s.buy_vol_all_buys ELSE NULL END AS sniper_vol_share_5s,
  CASE WHEN COALESCE(c.sum_buyer_usd, 0) > 0
       THEN COALESCE(c.top1_buyer_usd, 0) / c.sum_buyer_usd ELSE NULL END AS top1_buyer_vol_share,
  CASE WHEN COALESCE(c.sum_buyer_usd, 0) > 0
       THEN COALESCE(c.top5_buyer_usd, 0) / c.sum_buyer_usd ELSE NULL END AS top5_buyer_vol_share,
  CASE WHEN COALESCE(c.sum_buyer_usd, 0) > 0
       THEN COALESCE(c.top10_buyer_usd, 0) / c.sum_buyer_usd ELSE NULL END AS top10_buyer_vol_share,
  CASE WHEN COALESCE(c.sum_pos_net_tok, 0) > 0
       THEN COALESCE(c.top1_net_tok, 0) / c.sum_pos_net_tok ELSE NULL END AS top1_holder_pct_proxy,
  CASE WHEN COALESCE(c.sum_pos_net_tok, 0) > 0
       THEN COALESCE(c.top5_net_tok, 0) / c.sum_pos_net_tok ELSE NULL END AS top5_holder_pct_proxy,
  CASE WHEN COALESCE(c.sum_pos_net_tok, 0) > 0
       THEN COALESCE(c.top10_net_tok, 0) / c.sum_pos_net_tok ELSE NULL END AS top10_holder_pct_proxy,
  COALESCE(c.n_pos_holders_proxy, 0) AS n_holders_proxy,
  CASE WHEN f.buy_vol_usd_total > 0
       THEN f.max_buy_usd / f.buy_vol_usd_total ELSE NULL END AS max_buy_share
FROM flow f
LEFT JOIN sniper s ON s.mint = f.mint AND s.t0_ts = f.t0_ts
LEFT JOIN conc c ON c.mint = f.mint AND c.t0_ts = f.t0_ts
