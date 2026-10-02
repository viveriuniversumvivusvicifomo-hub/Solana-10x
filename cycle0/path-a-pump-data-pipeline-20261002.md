# Path A — Pump data pipeline unificado (2026-10-02)

**Status:** COMPLETE (100%)  
**Owner lane:** SolDatos  
**Finished:** 2026-10-02 ~14:20 CEST; **D-07 quarantine** ~14:25 CEST (Europe/Madrid)  
**Constraints enforced:** 0 Dune API · Lite OFF · **USD scale 6.6× OFF forever** · `q5b_last` / `q5b_calibration.json` untouched · paper_live PID **121466** not killed/restarted

## 1. Arquitectura / Architecture

```
Pump frontend RPC  GET /trades/{chainId}/{mint}
        │  cursor pages ≤T0 / until MC-band
        ▼
Trade caches (JSON per mint)  ─────────────────────────────────┐
  pilot500 / mcband_extra / livelike  (+ scale only via --reuse-orphan-scale) │
        │                                                       │
        ▼                                                       │
T0 = first trade MC ∈ [8k,20k]   (pump_mc_band_from_trades_v1)  │
Features ≤T0 (Q5a/Q5b + buy_vol)  USD = valueUsd (Pump)         │
Live Path A USD = sol_amt × pyth_asof   (scale 6.6× OFF)        │
        │                                                       │
        ▼                                                       │
Feature matrices → usable slices → train_q5b_pump_*_wf          │
Live paper: python -m paper_live --feed pump --enrich-via pump ─┘
```

**Path A USD (live):** `amount_usd = sol_amt × pyth_asof` (`APPLY_DUNE_HELIUS_USD_SCALE` default OFF; 6.6× rejected forever).  
**Path A USD (offline Pump trades):** frontend `valueUsd` / `priceUsd×1e9` for MC — never multiply by 6.6.

## 2. Canonical entrypoints

| Role | Path | Notes |
|------|------|-------|
| **CLI dispatcher** | `scripts/build_pump_path_a.py` | `inventory` / `livelike` / `mcband` / `pilot500` / `offline`; refuses `scale` unless `--force-orphan` |
| **Shared helpers** | `scripts/pump_path_a_common.py` | cache catalog, resolve/load, fetch_missing_band_aware, invariants |
| **Train rebuild (canonical)** | `scripts/build_pump_path_a_livelike.py` | live-like geometry filter; reuses all caches |
| **Live paper** | `python -m paper_live … --enrich-via pump` | **do not restart** from this lane |
| Offline journal/smoke | `scripts/build_pump_true_features_offline.py` | 0 Dune; journal extract / ≤20 mint smoke |

### Historical pilots (kept, not deleted)

| Script | Matrix | Status |
|--------|--------|--------|
| `build_pump_path_a_pilot500.py` | `features_pump_path_a_pilot500_20261002.csv` | KEEP — GO-1 expand_t0_ts |
| `build_pump_mcband_pilot.py` | `features_pump_path_a_mcband_20261002.csv` | KEEP — T0 MC-band recipe source of helpers |
| `build_pump_path_a_livelike.py` | `features_pump_path_a_livelike_20261002.csv` | KEEP — **canonical train** |

## 3. Trade caches (stamp `20261002`)

Priority lookup (`ordered_cache_dirs` **default**): **livelike → mcband_extra → pilot500**.  
Scale paths are **excluded** unless `--reuse-orphan-scale` / `REUSE_ORPHAN_SCALE=1`.

| Kind | Directory | n files (approx) | Role |
|------|-----------|------------------|------|
| pilot500 | `data/samples/pump_pilot500_trades_20261002/` | 495 | Base GO-1 cache |
| mcband_extra | `data/samples/pump_mcband_trades_extra_20261002/` | 45 | Deep pages for MC-band pilot |
| livelike | `data/samples/pump_livelike_trades_20261002/` | 221 | Canonical train fetch dir |
| scale (quarantine) | `archive/quarantine/mcband_scale_20261002/pump_mcband_scale_trades_*` | 837 | **NO-GO incomplete** (D-07) |
| scale_deep (quarantine) | same quarantine dir | 0 | Empty / unused |

**Cache schema (per mint JSON):** required top keys `mint`, `trades[]`; trade rows carry `blockTimeMs` + (`valueUsd`|`priceUsd`|`valueNative`). Optional: `n_raw`, `fetch_meta`, `fetched_at`, `t0_ts`.

### Matrices / usable

| Artifact | Present |
|----------|---------|
| `features_pump_path_a_pilot500_20261002.csv` | YES |
| `features_pump_path_a_mcband_20261002.csv` | YES |
| `features_pump_path_a_livelike_20261002.csv` | YES |
| `features_pump_path_a_mcband_scale_20261002.csv` | **NO** (ORPHAN — must stay absent for train) |
| `pump_livelike_usable_*.csv` | YES |
| `pump_mcband_scale_usable_*.csv` | **NO** |

## 4. ORPHAN — `build_pump_mcband_scale` (D-07 quarantine)

**Status:** `ORPHAN_INCOMPLETE` → **quarantined NO-GO** at `archive/quarantine/mcband_scale_20261002/` (`NO-GO_INCOMPLETE.md`).

| Has (in quarantine) | Missing |
|---------------------|---------|
| `pump_mcband_scale_sample_20261002.csv` (n=2800) | `features_pump_path_a_mcband_scale_*` |
| partial trades (~837 JSON) + fetch checkpoint + build logs/meta | `pump_mcband_scale_usable_*` |
| | deep trades (0 files) |

**Naming collision:** this is an *n-mint scale-up* recipe, **not** the rejected USD 6.6× scale.  
**Action (D-07):** artifacts **moved** to quarantine; script + CLI **refuse** unless `--force-orphan`; default cache order **excludes** scale.  
**Reuse:** only with explicit `--reuse-orphan-scale` / `REUSE_ORPHAN_SCALE=1`. Livelike universe still resolves sample CSV from quarantine path.  
**Do not train** WF / paper on scale. Residual fetch PID 112910 killed by BOSS; paper **121466** untouched. Optional Sinck delete later.  
**Note:** `cycle0/d-07-mcband-scale-quarantine-20261002.md`.

## 5. Deleted / deprecated vs kept

| Item | Decision |
|------|----------|
| `scripts/build_pump_mcband_scale.py` | **DEPRECATED/ORPHAN refuse** (kept; points at quarantine) |
| `scripts/pump_path_a_common.py` | **NEW** — shared resolve/fetch/inventory |
| `scripts/build_pump_path_a.py` | **NEW** — thin canonical CLI |
| `build_pump_path_a_livelike.py` | **KEEP** — imports common (no longer imports scale module) |
| `build_pump_mcband_pilot.py` / `pilot500` / `true_features_offline` | **KEEP** |
| ge10 Path A scripts (`build_ge10_*`, `reenrich_ge10_*`) | **KEEP** untouched (recovery_on / USD store isolate) |
| Dune SQL under `cycle0/` | **KEEP** as historical docs — **0 Dune API calls** from this lane |
| Trade caches pilot/mcband/livelike | **KEEP** (unified via ordered resolve) |
| Scale trades/sample/logs/checkpoint | **QUARANTINED** `archive/quarantine/mcband_scale_20261002/` |
| `q5b_last*` / paper PID | **UNTOUCHED** |

Scale artifacts moved (not deleted) under quarantine NO-GO; optional Sinck hard-delete later.

## 6. How to rebuild cache / matrix

```bash
cd /workspace/solana-10x
set -a; source .env; set +a
export PYTHONPATH=src:scripts

# Inventory (no HTTP)
.venv/bin/python scripts/build_pump_path_a.py inventory --stamp 20261002

# Canonical train matrix (reuses caches; caps HTTP)
.venv/bin/python scripts/build_pump_path_a.py livelike -- --stamp 20261002 --build-only
# or with fetch budget:
.venv/bin/python scripts/build_pump_path_a_livelike.py --stamp 20261002 --max-http 4500

# Offline journal extract (no network)
.venv/bin/python scripts/build_pump_true_features_offline.py --mode journal

# DO NOT: build_pump_path_a.py scale   (refused)
# DO NOT: enable APPLY_DUNE_HELIUS_USD_SCALE
# DO NOT: restart paper_live / overwrite q5b_last
```

## 7. Tests (SolDatos focused)

`tests/paper_live/test_path_a_pump_pipeline.py`

- USD scale 6.6× OFF (+ rejects when env forced ON)
- `mcband_scale` orphan flags / no matrix
- ordered cache priority (**scale excluded** by default; opt-in reuse)
- quarantine dir + `NO-GO_INCOMPLETE.md`
- trade cache schema on disk
- resolve across unified caches
- CLI inventory + refuses orphan scale (dispatcher + script)
- livelike no longer imports scale module; sample resolved from quarantine
- paper / `q5b_last` paths untouched
- feature matrices expose `buy_vol_usd_60s`

SolQA keeps V1–V8 ownership — these tests do **not** duplicate verification protocols wholesale.

## 8. Residual risks

1. **D-07 closed:** scale fetch killed; artifacts quarantined; default cache no longer depends on orphan. Prefer `--build-only` for deterministic audits.
2. **Scale sample** for livelike universe builder now resolved from quarantine path (historical seed) — still not a train matrix.
3. **USD residual** Pump `valueUsd` vs historical Dune `amount_usd` — expected; do not “fix” with 6.6×.
4. **Empty-pre-T0** fixed on mcband/livelike recipes; pilot500 expand_t0 still has historical empty-pos issue — do not swap paper to pilot500.
5. **HTTP 429 / budget** — rebuilds abort toward usable≥400 rather than chasing full expand.
6. **ge10 recovery_on / live Path A** — not modified this pass; paper left running.

## 9. Ready for SolAuditor

**Y** — pipeline mapped, D-07 quarantine complete, common entrypoint + tests, doc complete.  
Auditor should verify: scale OFF, quarantine README present, default cache excludes scale, no Dune calls, paper PID 121466 + `q5b_last` md5 untouched, orphan scale refused by CLI/script.
