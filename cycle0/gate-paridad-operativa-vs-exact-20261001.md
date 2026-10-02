# Gate: paridad operativa vs exact (Sinck 2026-10-01)

**Owner:** SolQA · **Auditor:** SolAuditor · **Decisión:** BOSS/@Sinck en room Solana 10x

## PASS prod (paridad operativa)

- trades = train (dump ≤T0 / recovery_on)
- meta OK (name/symbol)
- oracle **Path A Hermes** (`sol × pyth_asof`)
- **scale OFF** (no 6.6×)
- anti look-ahead: features `ts ≤ t0`
- residual score vs store Dune ~**1e-3–2e-3** **aceptado** (no bloquea)

Paper live **reabierto**; avisos **ON** bajo este gate.

## Exact (diagnóstico, no PASS prod)

- `|Δ score| < 1e-12` live Path A vs store/joblib Path A bit-exact
- Pilot Path A vs Dune store: **10/12** exact, max Δ **2.35e-3** (`2hCEWY`) → `FAIL_DIAGNOSTIC`
- `usd_store` isolate / P2-lite = solo clasificar residual USD — **nunca** live

## Pausado (cero gasto)

- P1 Dune scope A (Path A store rebase)
- re-fit Path A / candidate `q5b_path_a_*`

## Checklist

Ver sección política en `cycle0/live-train-parity-qa-checklist.md`.
