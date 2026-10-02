# GO_CARD — Path A train / build / HTTP scale

**Copy this file, fill every machine field, pass `--go-card <path>`.**  
Process: `cycle0/go-before-coding-gate-20261002.md`  
GO criterion: `cycle0/go-criterion-q5b-candidate-vs-last-20261002.md`  
Protocols: `cycle0/protocolos-verificacion.md` (V1–V8)

SolAuditor / SolModelos **refuse** half-done ships: no filled card → no train.

---

## Human context (optional)

| Field | Value |
|-------|-------|
| Owner | |
| Date (Europe/Madrid) | |
| Action summary | |
| Linked note | |

---

## Machine fields (required — keep the fenced `go_card` block)

Fill values. Do **not** leave `TODO` / `TBD` / `FILL`.  
`verdict` must be `GO` to proceed. `NO-GO` → scripts exit 2.

```go_card
action: train
go_criterion_ref: cycle0/go-criterion-q5b-candidate-vs-last-20261002.md
cost_fence: FILL — e.g. 0 Dune; 0 paid HTTP; local matrix only; OR estimate + STOP rule
api_spend: none
overwrite_q5b_last: NO
paper_restart: NO
protocolos_ack: FILL — e.g. V3,V4,V7 reviewed vs cycle0/protocolos-verificacion.md
verdict: NO-GO
```

### Field rules

| Key | Allowed |
|-----|---------|
| `action` | `train` \| `build` \| `http_scale` |
| `go_criterion_ref` | Must point at `go-criterion-q5b-candidate-vs-last` (path or basename) |
| `cost_fence` | Non-empty cost/STOP statement (credits, HTTP GETs, Dune=0, …) |
| `api_spend` | `none` **or** text containing `Sinck OK` / `Sinck: OK` when paid API/Dune/HTTP scale |
| `overwrite_q5b_last` | Must be `NO` (never YES) |
| `paper_restart` | `NO` **or** text containing `Sinck OK` |
| `protocolos_ack` | Non-empty ack of applicable V1–V8 vs `protocolos-verificacion.md` |
| `verdict` | `GO` to run; `NO-GO` refuses |

---

## Checklist reminder (train)

- [ ] Same-panel lift legs understood (max + med + frac≥0.9) — criterion doc
- [ ] Export only `q5b_path_a_candidate_*` (refuse `q5b_last`)
- [ ] USD scale OFF · Lite OFF · 0 Dune unless Sinck OK in `api_spend`
- [ ] Paper PID untouched unless `paper_restart` has Sinck OK
