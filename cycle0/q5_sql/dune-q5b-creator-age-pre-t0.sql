-- SolDatos Q5b — creator / age / metadata ≤ T0 (lite; priors computed offline)
-- Table: pumpdotfun_solana.pump_evt_createevent (covers create + create_v2)
-- Anti-lookahead: create_ts <= t0_ts
-- Prior launches: computed in Python from expand cohort (causal create_ts < t0)
--   to avoid Dune "too many stages" on creator×createevent self-join.

WITH sample AS (
  -- RUNNER_INJECTS_SAMPLE
  SELECT CAST(NULL AS varchar) AS mint, CAST(NULL AS TIMESTAMP) AS t0_ts WHERE 1=0
),
bounds AS (
  SELECT MIN(t0_ts) - INTERVAL '40' DAY AS t_lo, MAX(t0_ts) AS t_hi FROM sample
),
sample_mints AS (SELECT DISTINCT mint FROM sample),
creates_for_sample AS (
  SELECT
    CAST(e.mint AS varchar) AS mint,
    CAST(COALESCE(e.creator, e."user") AS varchar) AS creator,
    e.evt_block_time AS create_ts,
    CAST(e.name AS varchar) AS token_name,
    CAST(e.symbol AS varchar) AS token_symbol
  FROM pumpdotfun_solana.pump_evt_createevent e
  INNER JOIN sample_mints sm ON sm.mint = CAST(e.mint AS varchar)
  CROSS JOIN bounds b
  WHERE e.evt_block_time >= b.t_lo
    AND e.evt_block_time <= b.t_hi
),
creates_dedup AS (
  SELECT * FROM (
    SELECT c.*, ROW_NUMBER() OVER (PARTITION BY mint ORDER BY create_ts ASC) AS rn
    FROM creates_for_sample c
  ) x WHERE rn = 1
)
SELECT
  s.mint,
  s.t0_ts,
  c.creator AS creator_pubkey,
  c.create_ts,
  date_diff('second', c.create_ts, s.t0_ts) AS age_s,
  CASE WHEN c.create_ts IS NOT NULL
       THEN date_diff('second', c.create_ts, s.t0_ts) / 60.0 ELSE NULL END AS age_min,
  COALESCE(LENGTH(c.token_name), 0) AS name_len,
  COALESCE(LENGTH(c.token_symbol), 0) AS symbol_len,
  CASE WHEN c.token_name IS NULL THEN 1 ELSE 0 END AS name_missing,
  CASE WHEN c.token_symbol IS NULL THEN 1 ELSE 0 END AS symbol_missing,
  CASE WHEN c.creator IS NOT NULL THEN 1 ELSE 0 END AS has_creator
FROM sample s
LEFT JOIN creates_dedup c
  ON c.mint = s.mint
 AND c.create_ts <= s.t0_ts
