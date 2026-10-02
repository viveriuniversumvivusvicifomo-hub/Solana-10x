# GO before coding — Path A process gate (D-02) — 2026-10-02

**Owner:** BOSS + SolAuditor (enforce) · SolModelos / SolDatos (fill card before train/build/HTTP)  
**Zone:** Europe/Madrid  
**Inventory:** D-02 (P0)  
**Status:** code + template + process **shipped**; SolAuditor GO stamp still required to formally close lane

---

## Rule (one line)

**No new Path A train / build / HTTP scale without a written GO/NO-GO + cost fence** (filled `GO_CARD`) **before** the run. SolAuditor refuses half-done ships.

---

## Wiring

| Piece | Path |
|-------|------|
| Process (this doc) | `cycle0/go-before-coding-gate-20261002.md` |
| GO criterion (product lift) | `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` |
| Protocols V1–V8 | `cycle0/protocolos-verificacion.md` (+ executable mirror `src/verification/checklist.py`) |
| Template | `cycle0/templates/GO_CARD.md` |
| Validator CLI | `scripts/check_go_gate.py` |
| Canonical train refuse | `scripts/train_q5b_path_a_candidate_wf.py` requires `--go-card` (skipped only for `--dry-path-check`) |

---

## Required fields (before any Path A train / build / HTTP scale)

Fill the `go_card` fenced block in a copy of the template. All keys mandatory:

| Field | Meaning |
|-------|---------|
| `action` | `train` \| `build` \| `http_scale` |
| `go_criterion_ref` | Must cite `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md` |
| `cost_fence` | Explicit cost/STOP (0 Dune, HTTP GET budget, credits, …) |
| `api_spend` | `none` **or** statement containing **Sinck OK** if any paid API / Dune / HTTP scale |
| `overwrite_q5b_last` | Must be **NO** (never overwrite producción without separate Sinck+GO swap lane) |
| `paper_restart` | **NO** **or** text with **Sinck OK** (current paper PID **121466** stays unless OK) |
| `protocolos_ack` | Which V1–V8 apply / were reviewed vs `protocolos-verificacion.md` |
| `verdict` | **GO** to proceed; **NO-GO** → scripts exit 2 |

Placeholders (`TODO` / `TBD` / `FILL`) → **REFUSE**.

---

## How the gate works

1. Copy `cycle0/templates/GO_CARD.md` → e.g. `cycle0/artifacts/go_card_train_<stamp>.md`.
2. Fill machine fields; set `verdict: GO` only when cost fence + criterion + protocols ack are honest.
3. **Train:**  
   `python scripts/train_q5b_path_a_candidate_wf.py --profile livelike --go-card cycle0/artifacts/go_card_train_<stamp>.md …`  
   Missing/invalid card → **exit 2** JSON `REFUSE` (before matrix I/O / fit).
4. **Build / HTTP scale:** run  
   `python scripts/check_go_gate.py --go-card … --expect-action build`  
   (or `http_scale`) **before** starting fetch/scale; SolAuditor treats missing card as half-done.
5. `--dry-path-check` on the train entry validates export paths only (no card) — does **not** train.

Hard refuses already stacked with this gate:

- `--out` → `q5b_last.joblib` / `q5b_calibration.json` → exit 2  
- Archived `scripts/archive/train_q5b_pump_*.py` → exit 2  

---

## SolAuditor half-done refuse

Ship is **incomplete** if any of:

- No filled GO_CARD for a new train/build/HTTP scale  
- Card `verdict: NO-GO` or placeholders  
- Train ran without `--go-card`  
- Protocols ack empty (V1–V8 not acknowledged for the change class)  
- Would overwrite `q5b_last` or restart paper without Sinck OK  

Product lift (max+med+frac≥0.9) remains governed by the **criterion** doc; this gate is the **process** fence *before coding/running*.

---

## Constraints honored by this lane

- Do **not** restart paper PID **121466**  
- Do **not** overwrite `q5b_last` / `q5b_calibration.json`  
- **0 Dune** (default `api_spend: none`)  
