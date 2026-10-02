# scripts/archive — NO-GO / historical (SolModelos)

**Do not use these as the happy-path train entry.**

## Canonical train entry

```text
scripts/train_q5b_path_a_candidate_wf.py
```

- Recipe: `cycle0/recipe-path-a-train-canonical-20261002.md`
- GO criterion: `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md`
- Export: `data/paper_live/models/q5b_path_a_candidate_*.joblib` only
- Hard-refuses overwrite of `q5b_last.joblib` / `q5b_calibration.json`

## What lives here

Historical Path A Pump train experiments (2026-10-02), quarantined:

| Script | Former role |
|--------|-------------|
| `train_q5b_pump_wf.py` | Store twin under Pump column recipe |
| `train_q5b_pump_pilot500_wf.py` | pilot500 expand_t0 WF |
| `train_q5b_pump_mcband_wf.py` | MC-band pilot WF |
| `train_q5b_pump_livelike_wf.py` | Live-like geometry WF (best of forest; logic folded into canonical) |

Joblibs from these runs are **NO-GO** for paper swap — see `cycle0/quarantine-q5b-pump-joblibs-20261002.md`.

## Direct invocation

Running any archived script exits **2** with a pointer to the canonical entry unless
`SOLMODELOS_ARCHIVE_FORCE=1` (archaeology only; still must not write `q5b_last`).

## Build matrices (SolDatos)

Train matrices / caches: **SolDatos** owns `scripts/build_pump_path_a.py`
(and profile builders it dispatches). Do not break that CLI from this lane.
