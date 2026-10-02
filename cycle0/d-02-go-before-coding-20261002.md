# D-02 — GO criteria before coding (2026-10-02)

**Status:** DONE (code + tests + note) — Ready for SolAuditor GO stamp  
**Finished:** 2026-10-02T14:25:00+02:00 (Europe/Madrid / CEST)  
**Owner lane:** BOSS + SolAuditor (process) · SolModelos (train refuse wired)  
**Constraints:** 0 Dune · no paper restart · no `q5b_last` overwrite

## DoD (from inventory)

| Check | Result |
|-------|--------|
| Written GO/NO-GO + cost fence **before** new build/train/HTTP scale | YES — process + template |
| Checklist-gate wired to GO criterion + `protocolos-verificacion.md` | YES — card fields `go_criterion_ref` + `protocolos_ack` |
| SolAuditor can refuse half-done ships | YES — missing/invalid card → exit 2; note + process doc |
| Code refuse on canonical train entry | YES — `train_q5b_path_a_candidate_wf.py --go-card` |
| Lightweight validator + tests | YES — `scripts/check_go_gate.py` + fixtures |
| Paper PID **121466** untouched | YES |
| `q5b_last.joblib` md5 unchanged | `4df6d5a8dff6bf66528d4ee4cf6641b2` |
| `q5b_calibration.json` md5 unchanged | `586e2af105e8b890594a4f70612915a0` |
| 0 Dune | YES |

## Deliverables

| Artifact | Path |
|----------|------|
| Process | `cycle0/go-before-coding-gate-20261002.md` |
| Template | `cycle0/templates/GO_CARD.md` |
| Validator | `scripts/check_go_gate.py` |
| Train integration | `scripts/train_q5b_path_a_candidate_wf.py` (`--go-card`; skipped only for `--dry-path-check`) |
| Tests | `tests/models/test_check_go_gate.py` |
| Fixtures | `tests/fixtures/go_cards/*.md` |
| Criterion (pre-existing) | `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` |
| Protocols (pre-existing) | `cycle0/protocolos-verificacion.md` |

## How the gate works (operator)

1. Copy `cycle0/templates/GO_CARD.md`, fill `go_card` fields (`cost_fence`, `api_spend: none` or Sinck OK, `overwrite_q5b_last: NO`, `paper_restart: NO`, `protocolos_ack`, `verdict: GO`).
2. Train: `python scripts/train_q5b_path_a_candidate_wf.py ... --go-card <filled.md>`  
   Without card / NO-GO / placeholders → **REFUSE exit 2** before fit.
3. Build/HTTP scale: `python scripts/check_go_gate.py --go-card <filled.md> --expect-action build|http_scale` before starting.

## Not done in this lane (out of scope)

- Checking all 54 boxes in `protocolos-verificacion.md` (ack + applicable V's on the card; V1–V8 still tracked in `src/verification/checklist.py`)
- Product score-mass lift (D-01)
- Any train/WF execution, paper restart, or model overwrite

## Ready for SolAuditor

**Y** — confirm refuse without `--go-card`, valid fixture PASS, paper/`q5b_last` integrity.
