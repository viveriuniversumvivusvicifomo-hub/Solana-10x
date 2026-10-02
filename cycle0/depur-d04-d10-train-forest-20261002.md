# Depur D-04 / D-10 — train script forest → 1 canonical entry (2026-10-02)

**Owner:** SolModelos  
**Zone:** Europe/Madrid (CEST / UTC+2)  
**Stamp:** 2026-10-02 ~14:30 CEST  
**Constraints honored:** no paper restart (PID **121466** untouched) · no train executed in this lane · no overwrite `q5b_last.joblib` · 0 paid APIs / 0 Dune · SolDatos `build_pump_*` CLI not broken

---

## Before / after tree

### Before

```text
scripts/
  train_q5b_pump_wf.py              # twin / store
  train_q5b_pump_pilot500_wf.py
  train_q5b_pump_mcband_wf.py
  train_q5b_pump_livelike_wf.py
  build_pump_path_a.py              # SolDatos (unchanged ownership)
  build_pump_path_a_*.py / mcband_* # SolDatos build forest
```

### After

```text
scripts/
  train_q5b_path_a_candidate_wf.py  # CANONICAL train entry
  train_q5b_path_a_common.py        # shared refuse + journal rescore helpers
  archive/
    README.md                       # NO-GO / historical
    train_q5b_pump_wf.py
    train_q5b_pump_pilot500_wf.py
    train_q5b_pump_mcband_wf.py
    train_q5b_pump_livelike_wf.py
  build_pump_path_a.py              # SolDatos — document-only pointer from train lane
```

---

## Canonical entry + refuse-overwrite policy

| Item | Spec |
|------|------|
| Entry | `scripts/train_q5b_path_a_candidate_wf.py` |
| Default export | `data/paper_live/models/q5b_path_a_candidate_{stamp}.joblib` (+ `*_calibration.json`) |
| Profiles | `--profile {livelike,pilot500,mcband,twin}` (default **livelike**) — export still `q5b_path_a_candidate_*` |
| Refuse | If `--out` / calib path is or resolves to `q5b_last.joblib` or `q5b_calibration.json` → **exit 2** + clear JSON message |
| Prefix gate | Basename must start with `q5b_path_a_candidate` |
| Dry check | `--dry-path-check` validates paths without training |
| Archived invoke | `scripts/archive/train_q5b_pump_*.py` → exit **2** (unless `SOLMODELOS_ARCHIVE_FORCE=1`) |

---

## Links

| Doc | Path |
|-----|------|
| Recipe (SoT) | `cycle0/recipe-path-a-train-canonical-20261002.md` |
| GO criterion | `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` |
| Quarantine joblibs | `cycle0/quarantine-q5b-pump-joblibs-20261002.md` |
| Archive README | `scripts/archive/README.md` |
| Build (SolDatos) | `scripts/build_pump_path_a.py` |

---

## Status D-04 / D-10 (for SolAuditor GO)

| Debt | Scope in this note | Status |
|------|--------------------|--------|
| **D-10** | Train entrypoints → one canonical + archive refuse | **done pending SolAuditor GO** |
| **D-04** | Train half of duplicate build/train scripts | **done pending SolAuditor GO** (train) |
| **D-04 build half** | `build_pump_*` forest | **left to SolDatos** — pointer only; CLI untouched |

SolAuditor: confirm tree, refuse policy, `q5b_last` integrity, paper still on producción, archived scripts exit non-zero.

---

## Integrity — `q5b_last` unchanged

| Check | Value |
|-------|-------|
| Path | `data/paper_live/models/q5b_last.joblib` |
| **md5** | `4df6d5a8dff6bf66528d4ee4cf6641b2` |
| Paper PID | **121466** (not restarted by this lane) |
| Train run this lane | **None** (wiring/docs + refuse tests only) |

---

## Left for SolDatos

- Keep / finish consolidation of **build** forest under `scripts/build_pump_path_a.py` (livelike canonical rebuild).
- Orphan `build_pump_mcband_scale.py` (D-07) remains SolDatos.
- Train lane documents pointer only; do not change SolDatos CLI contracts from SolModelos.
