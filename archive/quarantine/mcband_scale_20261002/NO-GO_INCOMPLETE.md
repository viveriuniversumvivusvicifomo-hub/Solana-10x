# NO-GO — incomplete `mcband_scale` (quarantine 2026-10-02)

**Status:** NO-GO_INCOMPLETE  
**Debt:** D-07  
**Lane:** SolDatos  

## Why quarantined

Incomplete n-mint scale-up fetch from cancelled Path B work (~1.3k/2.8k mints in checkpoint;
~837 trade JSON files under `pump_mcband_scale_trades_20261002/`; deep cache empty=True).

- **No** `features_pump_path_a_mcband_scale_*` matrix
- **No** `pump_mcband_scale_usable_*`
- **Not for** train / walk-forward / paper swap
- Feat-diag already: **scale-n alone = NO** (`cycle0/path-a-mcband-feat-diag-20261002.md`)

This is an *n-mint scale recipe*, **not** the rejected USD 6.6× scale.

## Do not use

- Do not train WF on these artifacts
- Do not resume `build_pump_mcband_scale.py` for production train (CLI refuses; script refuses unless `--force-orphan`)
- Default `ordered_cache_dirs` **excludes** these paths — prod livelike must not silently depend on orphan
- Explicit opt-in only: `--reuse-orphan-scale` / env `REUSE_ORPHAN_SCALE=1`

## Optional Sinck delete later

Contents may be hard-deleted after Sinck GO. Until then: **move-only quarantine** (retained for audit).

## Manifest (moved here 2026-10-02T14:21:28+02:00)

- `data/samples/pump_mcband_scale_trades_20261002` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_trades_20261002`
- `data/samples/pump_mcband_scale_trades_deep_20261002` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_trades_deep_20261002`
- `data/samples/pump_mcband_scale_sample_20261002.csv` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_sample_20261002.csv`
- `cycle0/checkpoints/pump_mcband_scale_fetch_20261002.json` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_fetch_20261002.json`
- `cycle0/npz/pump_mcband_scale_build_20261002.log` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_build_20261002.log`
- `cycle0/artifacts/pump_mcband_scale_build_20261002.log` → `archive/quarantine/mcband_scale_20261002/artifacts__pump_mcband_scale_build_20261002.log`
- `cycle0/artifacts/pump_mcband_scale_build_meta_20261002.json` → `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_build_meta_20261002.json`

## Counts at quarantine

- n_trade_json (scale trades dir): 837
- n_deep_json: 0
- sample CSV: present under this dir
- features matrix: absent (never produced)

## Related

- Script (kept on disk, ORPHAN refuse): `scripts/build_pump_mcband_scale.py`
- Note: `cycle0/d-07-mcband-scale-quarantine-20261002.md`
- Pipeline: `cycle0/path-a-pump-data-pipeline-20261002.md` § orphan
