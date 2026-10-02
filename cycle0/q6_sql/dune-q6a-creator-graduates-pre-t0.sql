-- SolDatos Q6a — creator prior graduates ≤ T0 (DRY DESIGN — do not run until BOSS/Sinck after Q5 lift)
-- Anti-lookahead:
--   * sample create for mint_i must have create_ts <= t0_i
--   * other mint_j by same creator: create_ts < t0_i
--   * graduation proxy: first pumpswap trade on mint_j with block_time <= t0_i
-- Tables: pump_evt_createevent + dex_solana.trades (project = 'pumpswap')
-- Batch: start smoke 10 → 50 → 100 (300 likely fails like Q5)
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

-- Create row for sample mints (≤ t0 enforced at join)
creates_sample AS (
  SELECT * FROM (
    SELECT
      CAST(e.mint AS varchar) AS mint,
      CAST(COALESCE(e.creator, e."user") AS varchar) AS creator,
      e.evt_block_time AS create_ts,
      ROW_NUMBER() OVER (PARTITION BY CAST(e.mint AS varchar) ORDER BY e.evt_block_time ASC) AS rn
    FROM pumpdotfun_solana.pump_evt_createevent e
    INNER JOIN sample_mints sm ON sm.mint = CAST(e.mint AS varchar)
    CROSS JOIN bounds b
    WHERE e.evt_block_time >= b.t_lo
      AND e.evt_block_time <= b.t_hi
  ) x WHERE rn = 1
),

-- All creates by those creators in window (for prior scan)
creator_set AS (
  SELECT DISTINCT creator FROM creates_sample WHERE creator IS NOT NULL
),
creates_by_creator AS (
  SELECT
    CAST(e.mint AS varchar) AS mint_j,
    CAST(COALESCE(e.creator, e."user") AS varchar) AS creator,
    e.evt_block_time AS create_ts_j
  FROM pumpdotfun_solana.pump_evt_createevent e
  INNER JOIN creator_set cs ON cs.creator = CAST(COALESCE(e.creator, e."user") AS varchar)
  CROSS JOIN bounds b
  WHERE e.evt_block_time >= b.t_lo
    AND e.evt_block_time <= b.t_hi
),

-- First pumpswap trade per mint_j in bounds (= graduation proxy)
grad_first AS (
  SELECT
    CAST(t.token_bought_mint AS varchar) AS mint_j,
    MIN(t.block_time) AS first_grad_ts
  FROM dex_solana.trades t
  CROSS JOIN bounds b
  WHERE t.project = 'pumpswap'
    AND t.block_time >= b.t_lo
    AND t.block_time <= b.t_hi
    AND CAST(t.token_bought_mint AS varchar) IN (SELECT mint_j FROM creates_by_creator)
  GROUP BY 1
),

-- For each sample row: count prior graduates of same creator with grad_ts <= t0
priors AS (
  SELECT
    s.mint,
    s.t0_ts,
    cs.creator,
    cs.create_ts,
    COUNT(DISTINCT CASE
      WHEN cbc.mint_j <> s.mint
       AND cbc.create_ts_j < s.t0_ts
       AND gf.first_grad_ts IS NOT NULL
       AND gf.first_grad_ts <= s.t0_ts
       AND gf.first_grad_ts >= cbc.create_ts_j
       AND date_diff('day', cbc.create_ts_j, s.t0_ts) <= 7
      THEN cbc.mint_j END) AS creator_prior_graduates_7d,
    COUNT(DISTINCT CASE
      WHEN cbc.mint_j <> s.mint
       AND cbc.create_ts_j < s.t0_ts
       AND gf.first_grad_ts IS NOT NULL
       AND gf.first_grad_ts <= s.t0_ts
       AND gf.first_grad_ts >= cbc.create_ts_j
       AND date_diff('day', cbc.create_ts_j, s.t0_ts) <= 30
      THEN cbc.mint_j END) AS creator_prior_graduates_30d,
    COUNT(DISTINCT CASE
      WHEN cbc.mint_j <> s.mint
       AND cbc.create_ts_j < s.t0_ts
       AND gf.first_grad_ts IS NOT NULL
       AND gf.first_grad_ts <= s.t0_ts
       AND gf.first_grad_ts >= cbc.create_ts_j
      THEN cbc.mint_j END) AS creator_prior_graduates_all_in_window
  FROM sample s
  LEFT JOIN creates_sample cs
    ON cs.mint = s.mint AND cs.create_ts <= s.t0_ts
  LEFT JOIN creates_by_creator cbc
    ON cbc.creator = cs.creator
  LEFT JOIN grad_first gf
    ON gf.mint_j = cbc.mint_j
  GROUP BY 1, 2, 3, 4
)
SELECT
  mint,
  t0_ts,
  creator AS creator_pubkey,
  create_ts,
  COALESCE(creator_prior_graduates_7d, 0) AS creator_prior_graduates_7d,
  COALESCE(creator_prior_graduates_30d, 0) AS creator_prior_graduates_30d,
  COALESCE(creator_prior_graduates_all_in_window, 0) AS creator_prior_graduates_all_in_window,
  CASE WHEN creator IS NOT NULL THEN 1 ELSE 0 END AS has_creator
FROM priors
