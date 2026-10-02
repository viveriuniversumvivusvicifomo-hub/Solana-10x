# D-07 — Quarantine incomplete `mcband_scale` (2026-10-02)

**Status:** DONE (SolDatos) — Ready for SolAuditor  
**Finished:** 2026-10-02T14:22:45+02:00 (Europe/Madrid)  
**Constraints:** 0 Dune · no paper restart · no `q5b_last` overwrite

## DoD

| Check | Result |
|-------|--------|
| No `build_pump_mcband_scale` process | YES (residual fetch PID 112910 already killed by BOSS) |
| Paper PID **121466** untouched | YES (still running histgb_q5b / pump) |
| `q5b_last.joblib` md5 unchanged | `4df6d5a8dff6bf66528d4ee4cf6641b2` |
| Artifacts moved to quarantine NO-GO | YES |
| Default `ordered_cache_dirs` excludes scale | YES |
| CLI + script refuse | YES (`refused_orphan`, exit 2) |
| Tests | `tests/paper_live/test_path_a_pump_pipeline.py` |

## Quarantine path

`archive/quarantine/mcband_scale_20261002/`

- README: `NO-GO_INCOMPLETE.md`
- Manifest: `manifest.json`
- Incomplete fetch ~1352 done / ~2800 target; **837** trade JSON; deep=0; **no** features matrix

### Moved

- `data/samples/pump_mcband_scale_trades_20261002/` → quarantine
- `data/samples/pump_mcband_scale_trades_deep_20261002/` → quarantine
- `data/samples/pump_mcband_scale_sample_20261002.csv` → quarantine
- `cycle0/checkpoints/pump_mcband_scale_fetch_20261002.json` → quarantine
- `cycle0/Diagnostics/pump_mcband_scale_build_20261002.log` → quarantine
- `cycle0/diagnostics/pump_mcband_scale_build_*.log` / `*_meta*.json` → quarantine

## Code

- `scripts/pump_path_a_common.py` — default cache order **livelike → mcband_extra → pilot500**; scale only with `reuse_orphan_scale=True` / `REUSE_ORPHAN_SCALE=1` / `--reuse-orphan-scale`
- `scripts/build_pump_mcband_scale.py` — **ORPHAN refuse** (exit 2) unless `--force-orphan`; header points at quarantine
- `scripts/build_pump_path_a.py scale` — refuse unchanged (hint updated)
- `scripts/build_pump_path_a_livelike.py` — resolves sample CSV from quarantine; `--reuse-orphan-scale` opt-in

## Not for

Train / WF / paper. Optional Sinck hard-delete later.

## Ready for SolAuditor

**Y**
