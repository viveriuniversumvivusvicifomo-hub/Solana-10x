# Path A restart / curve-age verification — 2026-10-02

## Action

Sinck-approved graceful restart completed at approximately 12:13 PT (Europe/Madrid).

- Stopped the prior `paper_live` PID **18531** with `SIGTERM`; it exited cleanly.
- Started the same operativa via `scripts/start_paper_thr09.sh`.
- New PID: **121466** (alive at verification).
- Log: `data/paper_live/logs/run_operativa_20261002-121325_histgb_pump_restart.log`
- Command shape: `--live --cycles 0 --feed pump --enrich-via pump --score-mode histgb_q5b --entry-rule train_quantile --score-threshold 0.9 --max-calls 100000`
- Lite lane: **OFF** (no `--enable-lite-lane` / parallel lite mode).
- USD scale: **OFF** for the Pump path.
- Dune network calls: **0**; creator-prior stamps use the local train-parity resolver.

## Verification

- Cycle 1 completed in **10.9s** (`cycle=1`, within the requested ~2 minutes).
- Cycle 2 and cycle 3 also completed; the daemon remained alive.
- Post-restart journal rows: **2** at verification.
- Both rows had trades and the expected stamps:
  - `q5a_curve_age_source=q5a_trades`
  - `n_trades_pre_t0`: **42** and **160**
  - `creator_prior_source=dune_cohort_empty`
  - `score_mode=histgb_q5b`
  - `skip_prior_not_train`: **0** post-restart rows

Sample mints:

- `CV9MNNYjAA4TBwCaCD19RP8K5wUgnjUV4sVaZ7MP5vRy` — 42 pre-T0 trades; `q5a_trades`; `dune_cohort_empty`.
- `2HEpVChocEXvVmFQ8UmWuSXv9Y1z6CZBfLHrnDaoVfbj` — 160 pre-T0 trades; `q5a_trades`; `dune_cohort_empty`.

## Model safety

`q5b_last.joblib` and `q5b_calibration.json` were not overwritten. Checksums remained:

- `q5b_last.joblib`: `4df6d5a8dff6bf66528d4ee4cf6641b2`
- `q5b_calibration.json`: `586e2af105e8b890594a4f70612915a0`
