-- SolDatos Q6b — buyer wallet history ≤ T0 (DRY DESIGN — do not run until BOSS/Sinck)
-- Scope (safe L0 per row): for buyers of mint_i with trade block_time ≤ t0_i,
--   count THEIR prior pumpdotfun creates / prior pumpswap grads with ts < t0_i.
-- Does NOT use same-fold future mints as labels — only on-chain events ≤ t0_i.
-- Fold-level "wallet quality score trained on train mints" stays OFFLINE in WF (see catalog).
-- Anti-lookahead: all joined events require timestamp ≤ sample.t0_ts.
-- Batch: smoke 10 → 50; likely ≤50 if joins explode. Prefer offline if Q5a already has trader lists.
-- Credits: NOT authorized in this design pass.

WITH sample AS (
  -- RUNNER_INJECTS_SAMPLE
  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0
),
bounds AS (
  SELECT
    MIN(t0_ts) - INTERVAL '40' DAY AS t_lo,
    MAX(t0_ts) AS t_hi
  FROM sample
),
sample_mints AS (SELECT DISTINCT mint FROM sample),

-- Buys on sample mints ≤ t0
buys AS (
  SELECT
    s.mint,
    s.t0_ts,
    CAST(t.trader_id AS varchar) AS trader,
    t.block_time AS buy_ts,
    COALESCE(t.amount_usd, 0) AS buy_usd
  FROM sample s
  INNER JOIN dex_solana.trades t
    ON CAST(t.token_bought_mint AS varchar) = s.mint
   AND t.block_time <= s.t0_ts
  CROSS JOIN bounds b
  WHERE t.project IN ('pumpdotfun', 'pumpswap')
    AND t.block_time >= b.t_lo
    AND t.block_time <= b.t_hi
    AND t.token_bought_mint IS NOT NULL
    AND t.trader_id IS NOT NULL
),
buyers AS (
  SELECT DISTINCT mint, t0_ts, trader FROM buys
),

-- Prior creates by those traders (as creator) before this t0
prior_creates AS (
  SELECT
    b.mint,
    b.t0_ts,
    b.trader,
    COUNT(DISTINCT CAST(e.mint AS varchar)) AS trader_prior_creates_30d
  FROM buyers b
  LEFT JOIN pumpdotfun_solana.pump_evt_createevent e
    ON CAST(COALESCE(e.creator, e."user") AS varchar) = b.trader
   AND e.evt_block_time < b.t0_ts
   AND e.evt_block_time >= b.t0_ts - INTERVAL '30' DAY
   AND CAST(e.mint AS varchar) <> b.mint
  GROUP BY 1, 2, 3
),

-- Aggregate to mint level
mint_agg AS (
  SELECT
    bu.mint,
    bu.t0_ts,
    COUNT(DISTINCT bu.trader) AS n_buyers_pre_t0,
    AVG(COALESCE(pc.trader_prior_creates_30d, 0) * 1.0) AS mean_buyer_prior_creates_30d,
    MAX(COALESCE(pc.trader_prior_creates_30d, 0)) AS max_buyer_prior_creates_30d,
    AVG(CASE WHEN COALESCE(pc.trader_prior_creates_30d, 0) >= 1 THEN 1.0 ELSE 0.0 END) AS pct_buyers_with_prior_create_30d,
    SUM(bu.buy_usd) AS buy_vol_usd_total_q6b_check
  FROM (
    SELECT mint, t0_ts, trader, SUM(buy_usd) AS buy_usd
    FROM buys GROUP BY 1, 2, 3
  ) bu
  LEFT JOIN prior_creates pc
    ON pc.mint = bu.mint AND pc.t0_ts = bu.t0_ts AND pc.trader = bu.trader
  GROUP BY 1, 2
)
SELECT * FROM mint_agg
