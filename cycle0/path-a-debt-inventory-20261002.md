# Path A — Inventario de deuda (cycle0) — 2026-10-02

**Autor:** BOSS inventory (scan ligero de código + notes path-a)  
**Fecha:** 2026-10-02 ~14:20 CEST (Europe/Madrid)  
**Repo:** `/workspace/solana-10x`  
**Machine list:** `cycle0/diagnostics/debt_inventory_20261002.json`  
**Sustituye:** `cycle0/path-a-debt-inventory-PROVISIONAL-20261002.md` (rebase a este SoT)

**Orden Sinck:** no more half-done hacks; inventory → team depura hasta 100% functional closes.

## Rules of engagement

- **Every fix must ship:** code + tests + note + **SolAuditor GO** before `done`.
- **No paper_live restart** without Sinck OK (current PID **121466** — `--feed pump --enrich-via pump --score-mode histgb_q5b --thr 0.9`).
- **Never overwrite** `q5b_last.joblib` / `q5b_calibration.json`  
  (md5 baseline: `4df6d5a8dff6bf66528d4ee4cf6641b2` / `586e2af105e8b890594a4f70612915a0`).
- **0 Dune** unless Sinck GO + cost.
- Lite OFF · USD scale OFF · companion `q5b_pump_*` = NO-GO swap until GO criterion lifts journal mass.

---

## Summary counts

| Priority | open | accepted-documented | done | **total** |
|----------|-----:|--------------------:|-----:|----------:|
| **P0**   | 1 | 0 | 1 | **2** |
| **P1**   | 4 | 2 | 3 | **9** |
| **P2**   | 2 | 3 | 1 | **6** |
| **All**  | **7** | **5** | **5** | **17** |

Must-include coverage: items **1–12** below (plus 5 related tidy items).

---

## Inventory (P0 / P1 / P2)

### P0 — product / process blockers

| id | item | owner | status | Definition of Done |
|----|------|-------|--------|--------------------|
| **D-01** | **Score mass live ≠ train** (product blocker; separate from tidy debt) | SolModelos + SolDatos | **open** | Pump-true matrix whose **POS geometry ≈ live MC-band T0** → WF candidate joblib (never overwrite `q5b_last` without Sinck) → journal rescore lifts **max + median + frac≥0.9** vs `q5b_last` on same Path A Pump panel (`cycle0/go-criterion-q5b-candidate-vs-last-20261002.md`) → note + SolAuditor GO. **NO** thr cut / USD scale ON / twin swap as fake close. |
| **D-02** | **Protocol gaps: GO criteria before coding** | BOSS + SolAuditor | **done pending SolAuditor GO** | Enforce: written GO/NO-GO + cost fence **before** new build/train/HTTP scale. Automate or checklist-gate `cycle0/protocolos-verificacion.md` V1–V8 (hoy **0/54** boxes checked) for any Path A train/live change. SolAuditor refuses half-done ships. **Shipped:** `go-before-coding-gate` + `templates/GO_CARD.md` + `scripts/check_go_gate.py` + train `--go-card` refuse; note `d-02-go-before-coding-20261002.md`. |

Evidence D-01: `path-a-mcband-feat-diag`, `path-a-pump-pilot500`, `path-a-pump-livelike` — all **NO-GO** paper swap; live mass collapses (e.g. mcband max≈0.19 vs q5b_last≈0.91; livelike median 0.036≪0.171).  
Evidence D-02: pilots/scale started under cancelled-B logic; `protocolos-verificacion.md` still unchecked as box-fill (ack via GO_CARD); **hard gate shipped 2026-10-02** — see `cycle0/d-02-go-before-coding-20261002.md`.

---

### P1 — functional close debt

| id | item | owner | status | Definition of Done |
|----|------|-------|--------|--------------------|
| **D-03** | **features_stub naming / legacy** → real module name or documented contract | SolQA | **done**† | Code: renamed `src/paper_live/features_stub.py` → **`features_t0.py`** (docstring contract; imports in `loop`/`score`/`recipe_parity`/`rescore_replay`/`tests`). †SolAuditor GO stamp still required to close lane formally (code+tests+note already on disk). |
| **D-04** | **Duplicate Pump build/train scripts** (pilot500, mcband, mcband_scale orphan, livelike, twin) — consolidate or quarantine NO-GO artifacts | SolModelos + SolDatos | **done pending SolAuditor GO** (train→`train_q5b_path_a_candidate_wf.py` + `scripts/archive/`; build half still SolDatos) | Single canonical recipe path (`cycle0/recipe-path-a-train-canonical-20261002.md`). Scripts: mark NO-GO / move under `scripts/archive/` **or** delete after SolAuditor GO. Joblibs: keep quarantine inventory (`cycle0/quarantine-q5b-pump-joblibs-20261002.md`); no paper swap. Scale orphan: see D-10. |
| **D-05** | **Residual USD / holders / priors** — accept+document OR fix with DoD | SolDatos | **accepted-documented** (USD, holders, T0, prior-store) + **done** priors stamp | USD scale **OFF**; frontend `valueUsd` vs Dune `amount_usd` accepted until Pump-trained model (`path-a-residual-parity` R5). Holders defs match / trader_id differ → accept short-term (R6). T0 product = `pump_mc_band_sighting_v1` (R7). Prior store frescor accept (R8). **Priors stamp:** code + restart PID 121466 → post-12:13 PT `skip_prior_not_train=0`; stamps `dune_cohort_{exact,recompute,empty}`. |
| **D-06** | **Journal pc1=158 Bitquery / stub legacy stock pollution** | SolQA + SolDatos | **done**† | Quarantine COPY `paper_candidates_legacy_20261001` (n=158; live untouched) + CSV `cycle0/artifacts/…` + filter in `legacy_candidates` / journal summary / backtest entry gate. pc1≠selectivity documented. Tests: `test_legacy_candidates_d06` (3). Note: `depur-d06-d08-20261002.md`. †SolAuditor GO pending. |
| **D-07** | **Incomplete scale script from cancelled B** | SolDatos | **done** (quarantined) | Quarantine `archive/quarantine/mcband_scale_20261002/` + `NO-GO_INCOMPLETE.md`; residual fetch dead; default cache excludes scale; CLI/script refuse; note `cycle0/d-07-mcband-scale-quarantine-20261002.md`; paper 121466 + `q5b_last` untouched. SolAuditor GO pending. |
| **D-08** | **Test gaps for pump_enrich curve / age / priors** | SolQA | **done**† | Remaining 4 gaps in `test_path_a_pump_d08_gaps.py` (holders proxy; `sol_usd_source=pump_frontend` gate; post-restart invariant; coin-overlay regression). Prior curve/age/prior tests unchanged. Note: `depur-d06-d08-20261002.md`. †SolAuditor GO pending. |
| **D-09** | **Lite model disabled but code paths remain** | SolQA | **accepted-documented** | `enable_lite_lane=False`; operativa sin lite. Code: `score_lite.py`, `multi_score.py`, loop thr maps, `candidates_lite` table. DoD accept: keep OFF + doc (`score-mode-lite-cycle0`) **or** gate behind explicit Sinck flag with tests that default path never instantiates LiteScorer. |
| **D-10** | **Script forest vs single entry** (twin `train_q5b_pump_wf` + pilot500 + mcband + livelike) | SolModelos | **done pending SolAuditor GO** (`cycle0/depur-d04-d10-train-forest-20261002.md`) | Same as D-04 focus on **train** entrypoints: one `train_q5b_path_a_candidate_wf.py` (or documented wrapper); others thin aliases or archived. Metrics must refuse overwrite `q5b_last`. |
| **D-11** | **WS3 residual-accept note still thin / missing formal close** | SolDatos | **open** | Formal `path-a-ws3-residual-accept-20261002.md` (or extend residual-parity) listing every accept row with owner+revisit trigger; SolAuditor GO. |

† D-03 code done; lane not closed until SolAuditor GO — counted as **done** for inventory code claim, tracked in JSON `solauditor_go_pending=true`.

---

### P2 — tidy / keep-but-document

| id | item | owner | status | Definition of Done |
|----|------|-------|--------|--------------------|
| **D-12** | **ModelStub / cycle0 stubs still imported in live paths?** | SolQA | **done** | **No.** Live uses joblib HistGB via `paper_live.score`. `ModelStub` only `src/models/stub.py` + tests + `run_stub_wf_cohort200`. Package docstring states offline-only. DoD met for claim; SolAuditor may spot-check. |
| **D-13** | **`skip_sol_usd_not_pyth` / `skip_prior_not_train` “dead” after Pump restart?** | SolQA | **accepted-documented** | **`skip_prior_not_train`:** NOT dead — hard gate remains; post-restart rate **0** because stamps work. Historical 562 rows pre-12:13 PT remain in journal. **`skip_sol_usd_not_pyth`:** 0 sightings ever; Pump scoreable short-circuits pyth require; keep for Helius/hybrid. DoD: document taxonomy in note; optional split skip counters Pump vs Helius; no delete of gates. |
| **D-14** | **Helius enrich still in live path when `enrich=pump`?** | SolQA | **accepted-documented** | **No runtime call** when `via==pump` (`loop._enrich` → `enrich_pump_for_sightings` only). Helius remains opt-in `--enrich-via helius`. Stale docstring in `loop.py` still says “Default enrich: Helius” — **doc fix open** (P2 tidy). |
| **D-15** | **Stale `loop.py` module docstring (default enrich Helius)** | SolQA | **open** | Align docstring with `DEFAULT_ENRICH_VIA="pump"`; test or grep CI that docs match config; SolAuditor GO. |
| **D-16** | **Followup `poll_pump_mcs` errors in `state.json`** | SolQA | **open** | `state.followup_errors` still lists missing `poll_pump_mcs` (method now exists in `followup.py`) + DNS errors. DoD: clear/rotate errors on healthy poll; test FollowupTracker API; no restart without Sinck (can soft-fix in-code for next approved restart). |
| **D-17** | **Companion NO-GO joblibs in models/ (in-situ quarantine)** | SolModelos | **accepted-documented** | Six `q5b_pump_*.joblib` (+calib) inventoried NO-GO; paper stays on `q5b_last`. Optional physical `models/quarantine/` only with Sinck. |

---

## Must-include crosswalk (1–12 → ids)

| # | Requested topic | Inventory id(s) | Priority | Status snapshot |
|---|-----------------|-----------------|----------|-----------------|
| 1 | features_stub naming/legacy | D-03 | P1 | done† (→ `features_t0`) |
| 2 | ModelStub in live paths? | D-12 | P2 | done (not in live) |
| 3 | Duplicate Pump build/train scripts | D-04, D-10 | P1 | done pending SolAuditor GO (train); build→SolDatos |
| 4 | Score mass live≠train | D-01 | **P0** | open |
| 5 | Residual USD/holders/priors | D-05 | P1 | accepted-documented (+ priors done) |
| 6 | skip_sol_usd / skip_prior dead paths | D-13 | P2 | accepted-documented |
| 7 | Helius enrich when enrich=pump? | D-14 (+ D-15 doc) | P2 | accepted-documented (no live call) |
| 8 | Lite disabled but code paths? | D-09 | P1 | accepted-documented |
| 9 | Journal pc1=158 Bitquery legacy | D-06 | P1 | done† (export+filter; SolAuditor GO pending) |
| 10 | Incomplete scale script cancelled B | D-07 | P1 | done (quarantined) |
| 11 | Protocol gaps GO before coding | D-02 | **P0** | done pending SolAuditor GO |
| 12 | Test gaps pump_enrich curve/age/priors | D-08 | P1 | done† (4 gap tests; SolAuditor GO pending) |

---

## Grounding (scan ligero — no prod behavior change)

| Claim | Where |
|-------|--------|
| PID 121466 Path A Pump | `ps` + `path-a-restart-curve-age-20261002.md` |
| `features_t0` ex-stub | `src/paper_live/features_t0.py` L1–15; imports updated |
| ModelStub offline-only | `src/models/__init__.py`; no import under `paper_live/` |
| Enrich branch pump≠helius | `loop._enrich` `if via == "pump"` → `pump_enrich` only |
| skip_prior post-restart = 0 | sqlite `sightings` `created_at >= 2026-10-02T12:13+02` |
| pc1=158 | `paper_candidates` count; rule_buy60 stub feats |
| Scale incomplete | `npz/pump_mcband_scale_build_*.log` mid 1300/2800; no features matrix |
| Lite OFF | `config.enable_lite_lane=False`; restart cmd sin lite flags |
| Protocols unchecked | `protocolos-verificacion.md` 54× `- [ ]`, 0× `- [x]` |
| Curve/age/prior tests | `tests/paper_live/test_path_a_pump_capture.py`, `test_creator_priors_and_threshold.py` |

**This write:** inventory md + diagnostics JSON only. **No** paper restart, **no** model overwrite, **0** Dune.

---

## Team depurate order (suggested)

1. **SolAuditor:** GO stamp D-03/D-12; refuse any ship without GO criterion (D-02).  
2. **SolModelos:** D-01 score-mass path (live-like POS matrix) + D-04/D-10 script quarantine.  
3. **SolDatos:** D-07 scale orphan quarantine + D-05/D-11 residual-accept formal close.  
4. **SolQA:** D-06/D-08 code+tests+note delivered (`depur-d06-d08`); SolAuditor GO; then D-15/D-16 tidy.  

**Close rule:** item → `done` only when code + tests + note + SolAuditor GO all present.
