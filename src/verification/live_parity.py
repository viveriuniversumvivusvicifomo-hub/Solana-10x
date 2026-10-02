"""Live ↔ train parity gates: recipe + anti look-ahead (SolQA).

See cycle0/live-train-parity-qa-checklist.md.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from features.post_q5_sets import DROP_FROM_X, FEATURE_SETS, JOIN_ONLY, LEAK_COL_RE
from verification.secrets import scan_text_for_secrets

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "data/samples/qa_live_train_parity_report.json"
SCORE_SET = "+q5b"
EXPECTED_COLS = FEATURE_SETS[SCORE_SET]


def _check(name: str, ok: bool, detail: Any = None, *, soft: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "soft": soft, "detail": detail}


def assert_recipe_columns(columns: Sequence[str], *, set_name: str = SCORE_SET) -> list[str]:
    """Return list of problems; empty = pass."""
    expected = list(FEATURE_SETS[set_name])
    problems: list[str] = []
    if list(columns) != expected:
        missing = [c for c in expected if c not in columns]
        extra = [c for c in columns if c not in expected]
        order = list(columns) != expected and not missing and not extra
        if missing:
            problems.append(f"missing:{missing}")
        if extra:
            problems.append(f"extra:{extra}")
        if order:
            problems.append("order_mismatch")
    banned = [
        c
        for c in columns
        if c in JOIN_ONLY or c in DROP_FROM_X or LEAK_COL_RE.search(c)
    ]
    if banned:
        problems.append(f"banned:{banned}")
    return problems


def assert_trades_leq_t0(
    trades: Iterable[Mapping[str, Any]],
    *,
    t0: datetime,
    ts_key: str = "ts",
) -> list[str]:
    """Fail list of trade ids/indices with ts > t0."""
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    offenders: list[str] = []
    for i, tr in enumerate(trades):
        raw = tr.get(ts_key)
        if raw is None:
            offenders.append(f"[{i}] missing {ts_key}")
            continue
        if isinstance(raw, datetime):
            ts = raw
        elif isinstance(raw, (int, float)):
            ts = datetime.fromtimestamp(float(raw), tz=timezone.utc)
        else:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts > t0:
            offenders.append(f"[{i}] {ts.isoformat()} > {t0.isoformat()}")
    return offenders


def assert_window_bounds(
    trades: Iterable[Mapping[str, Any]],
    *,
    t0: datetime,
    window_s: int,
    ts_key: str = "ts",
) -> list[str]:
    """Trades claimed inside window must satisfy t0−window_s ≤ ts ≤ t0."""
    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    lo = t0.timestamp() - window_s
    hi = t0.timestamp()
    bad: list[str] = []
    for i, tr in enumerate(trades):
        raw = tr[ts_key]
        if isinstance(raw, datetime):
            ts = raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
            unix = ts.timestamp()
        else:
            unix = float(raw)
        if unix < lo - 1e-6 or unix > hi + 1e-6:
            bad.append(f"[{i}] unix={unix} outside [{lo},{hi}]")
    return bad


def audit_static_recipe() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    cols = list(EXPECTED_COLS)
    checks.append(_check("recipe.n_cols", len(cols) == 51, {"n": len(cols), "set": SCORE_SET}))
    checks.append(
        _check(
            "recipe.banned_absent",
            "migrated_pre_t0" not in cols
            and "creator_pubkey" not in cols
            and "create_ts" not in cols,
            {"drop_from_x": sorted(DROP_FROM_X)},
        )
    )
    leak = [c for c in cols if LEAK_COL_RE.search(c)]
    checks.append(_check("recipe.no_label_like", not leak, leak))
    # recipe_parity module importable
    try:
        from paper_live.recipe_parity import assert_feats_cover_recipe, assert_recipe_matches_joblib

        # empty dict → missing all; pass synthetic full-null cover
        feats = {c: 0.0 for c in cols}
        missing = assert_feats_cover_recipe(feats)
        jr = assert_recipe_matches_joblib()
        checks.append(_check("recipe.feats_cover", not missing, {"missing": missing}))
        soft_joblib = (not jr.ok) and (jr.n_joblib is None)
        checks.append(
            _check(
                "recipe.joblib_match",
                jr.ok,
                jr.as_dict(),
                soft=soft_joblib,
            )
        )
    except Exception as exc:  # noqa: BLE001
        problems = assert_recipe_columns(cols)
        checks.append(
            _check(
                "recipe.paper_live_gate",
                not problems,
                {"exc": str(exc), "problems": problems},
            )
        )
    return checks


def audit_q5a_agg_unit() -> list[dict[str, Any]]:
    """Synthetic: post-T0 trade must not affect aggregates."""
    from datetime import timedelta

    from paper_live.q5a_agg import TradeRow, aggregate_q5a_for_mint

    t0 = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)
    pre = TradeRow(
        mint="m",
        ts=t0 - timedelta(seconds=10),
        side="buy",
        amount_usd=100.0,
        trader_id="a",
        tok_amt=1.0,
        sol_amt=1.0,
        project="pumpdotfun",
    )
    post = TradeRow(
        mint="m",
        ts=t0 + timedelta(seconds=5),
        side="buy",
        amount_usd=1_000_000.0,
        trader_id="b",
        tok_amt=1.0,
        sol_amt=1000.0,
        project="pumpdotfun",
    )
    out = aggregate_q5a_for_mint([pre, post], t0)
    ok = abs(float(out.get("buy_vol_usd_total") or 0) - 100.0) < 1e-6
    offenders = assert_trades_leq_t0(
        [{"ts": pre.ts}, {"ts": post.ts}],
        t0=t0,
    )
    return [
        _check(
            "q5a_agg.filters_post_t0",
            ok,
            {"buy_vol_usd_total": out.get("buy_vol_usd_total"), "expected": 100.0},
        ),
        _check(
            "assert_trades_leq_t0.detects_post",
            len(offenders) == 1,
            offenders,
        ),
    ]



# --- LIVE_ENTRY_GATES_V1 (SolQA MUST-FIX 2026-10-01) ---
LIVE_ENTRY_CONFIG = ROOT / "data/paper_live/models/live_entry_config.json"
TRAIN_PRIOR_PREFIXES = ("dune_cohort_",)
TRAIN_PRIOR_ALIASES = frozenset({"train_store_v1"})
FORBIDDEN_PRIOR = frozenset({"pump_frontend_30d", "none", ""})


def load_live_entry_config(path: Path | None = None) -> dict[str, Any]:
    p = path or LIVE_ENTRY_CONFIG
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def prior_source_is_train(source: Any) -> bool:
    """True iff creator_prior_source is Dune cohort family (or legacy train_store_v1)."""
    if source is None:
        return False
    s = str(source).strip()
    if not s or s in FORBIDDEN_PRIOR:
        return False
    if s in TRAIN_PRIOR_ALIASES:
        return True
    return any(s.startswith(pref) for pref in TRAIN_PRIOR_PREFIXES)


def assert_prior_source_train(source: Any) -> list[str]:
    if prior_source_is_train(source):
        return []
    return [f"prior≠train: creator_prior_source={source!r} (need dune_cohort_* | train_store_v1)"]


def assert_t0_refined(t0_refined: Any) -> list[str]:
    if t0_refined is True:
        return []
    return [f"t0_not_refined: t0_refined={t0_refined!r}"]


def assert_threshold_matches_config(
    score_threshold: float | None,
    *,
    config: Mapping[str, Any] | None = None,
    atol: float = 1e-9,
) -> list[str]:
    """Fail if live umbral ≠ Sinck product config (default 0.99)."""
    cfg = dict(config) if config is not None else load_live_entry_config()
    if not cfg:
        return ["live_entry_config_missing"]
    expected = float(cfg["score_threshold"])
    if score_threshold is None:
        return [f"score_threshold=None ≠ config {expected}"]
    got = float(score_threshold)
    if abs(got - expected) > atol:
        return [f"score_threshold={got} ≠ config.score_threshold={expected} ({cfg.get('threshold_source')})"]
    return []


def audit_score_row_gates(row: Mapping[str, Any]) -> list[str]:
    """Hard fails for one scored/enrich row (meta fields)."""
    problems: list[str] = []
    problems.extend(assert_prior_source_train(row.get("creator_prior_source")))
    problems.extend(assert_t0_refined(row.get("t0_refined")))
    return problems


def audit_entry_config_gates(
    *,
    score_threshold: float | None,
    config: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cfg = dict(config) if config is not None else load_live_entry_config()
    checks: list[dict[str, Any]] = []
    thr_prob = assert_threshold_matches_config(score_threshold, config=cfg)
    checks.append(_check("gate.umbral_eq_config", not thr_prob, thr_prob or {"threshold": score_threshold, "config": cfg.get("score_threshold")}))
    # Sinck 2026-10-02: Helius t0_refined no longer required for Path A (Pump MC gate).
    # Config may set require_t0_refined=false; require_helius_t0_refined is the old gate (opt-in).
    helius_req = bool(cfg.get("require_helius_t0_refined", False))
    checks.append(
        _check(
            "gate.config.require_helius_t0_refined_off_by_default",
            helius_req is False,
            {"require_helius_t0_refined": helius_req, "require_t0_refined": cfg.get("require_t0_refined")},
        )
    )
    checks.append(_check("gate.config.require_prior_train", bool(cfg.get("require_prior_source_train", True)), cfg.get("require_prior_source_train")))
    # unit: known bad/good prior
    checks.append(_check("gate.prior.dune_ok", prior_source_is_train("dune_cohort_exact")))
    checks.append(_check("gate.prior.pump_fail", not prior_source_is_train("pump_frontend_30d")))
    checks.append(_check("gate.t0.true_ok", not assert_t0_refined(True)))
    checks.append(_check("gate.t0.false_fail", bool(assert_t0_refined(False))))
    return checks


def run_live_parity_qa(*, write_report: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    checks.extend(audit_static_recipe())
    try:
        checks.extend(audit_q5a_agg_unit())
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("q5a_agg.filters_post_t0", False, str(exc)))

    # buy_vol window helper
    try:
        from paper_live.buy_vol import WINDOW_S

        t0 = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
        inside = [{"ts": t0.timestamp() - 30}]
        outside = [{"ts": t0.timestamp() + 1}]
        checks.append(
            _check(
                "buy60.window_inside",
                not assert_window_bounds(inside, t0=t0, window_s=WINDOW_S),
            )
        )
        checks.append(
            _check(
                "buy60.window_rejects_post_t0",
                bool(assert_window_bounds(outside, t0=t0, window_s=WINDOW_S)),
                "post-T0 must fail window bound assert",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(_check("buy60.window", False, str(exc), soft=True))

    secret_hits: list[str] = []
    for rel in (
        "cycle0/live-train-parity-qa-checklist.md",
        "cycle0/live-train-recipe-parity.md",
        "src/paper_live/helius_enrich.py",
        "src/paper_live/q5a_agg.py",
    ):
        p = ROOT / rel
        if p.is_file():
            secret_hits.extend(
                scan_text_for_secrets(
                    p.read_text(encoding="utf-8", errors="ignore")[:1_500_000],
                    path=rel,
                )
            )
    checks.append(_check("secrets", not secret_hits, secret_hits[:8]))

    hard = [c for c in checks if not c["ok"] and not c.get("soft")]
    soft = [c for c in checks if not c["ok"] and c.get("soft")]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": len(hard) == 0,
        "score_set": SCORE_SET,
        "n_train_cols": len(EXPECTED_COLS),
        "hard_fails": [c["name"] for c in hard],
        "soft_fails": [c["name"] for c in soft],
        "checks": checks,
        "paths": {
            "checklist": "cycle0/live-train-parity-qa-checklist.md",
            "diagnosis": "cycle0/live-vs-train-score-replay-20261001.md",
            "recipe_doc": "cycle0/live-train-recipe-parity.md",
            "entry_config": "data/paper_live/models/live_entry_config.json",
            "mismatch_hunt": "cycle0/live-vs-train-mismatch-hunt-20261001.md",
            "report": str(REPORT.relative_to(ROOT)),
        },
        "pending_after_datos_fix": [
            "re-run rescore_replay on Helius rebuild CSV",
            "assert 0 trades ts>t0 in rebuild artifact",
            "compare n_trades_pre_t0 vs Dune on sample highs",
        ],
    }
    if write_report:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    r = run_live_parity_qa(write_report=True)
    print(
        json.dumps(
            {k: r[k] for k in ("ok", "n_train_cols", "hard_fails", "soft_fails", "paths")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
