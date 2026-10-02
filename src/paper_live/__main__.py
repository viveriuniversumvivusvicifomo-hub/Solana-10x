"""CLI entrypoint: python -m paper_live ...

Ejemplos
--------
  # Smoke dry-run (sample + q5 fixture, sin API) — legacy topk for rule scores:
  PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 3 \\
    --score-mode rule_buy60 --entry-rule topk_batch --top-k 10

  # Default histgb_q5b ultra-select (trainQ top1% + max_per_hour=2):
  PYTHONPATH=src .venv/bin/python -m paper_live --export-model +q5b
  PYTHONPATH=src .venv/bin/python -m paper_live --dry-run --cycles 2 --score-mode histgb_q5b

  # Live poll Pump.fun + Helius enrich (default hybrid):
  PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed pump --enrich-via helius

  # Optional Bitquery feed (often 402 on FREE):
  PYTHONPATH=src .venv/bin/python -m paper_live --live --cycles 1 --feed bitquery --max-calls 8

  # Backtest how many journal histgb scores pass the gate (no live):
  PYTHONPATH=src .venv/bin/python -m paper_live --backtest-entry-gate
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from paper_live.config import (  # noqa: E402
    DEFAULT_ENTRY_RULE,
    DEFAULT_ENRICH_VIA,
    DEFAULT_FEED,
    DEFAULT_MAX_PER_HOUR,
    DEFAULT_Q5A_HOURS_AGO,
    DEFAULT_SCORE_MODE,
    DEFAULT_SOL_USD_REF,
    DEFAULT_TOP_K,
    DEFAULT_TRAIN_TOP_FRAC,
    SAMPLE_PUMP,
    PaperLiveConfig,
)
from paper_live.entry import (  # noqa: E402
    backtest_scores_against_threshold,
    load_calibration,
    resolve_score_threshold,
)
from paper_live.loop import PaperLiveRunner  # noqa: E402
from paper_live.score import export_last_fold_model  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Paper-live tracker v0 (NO real trading)")
    p.add_argument("--dry-run", action="store_true", default=False, help="Replay sample + q5 fixture")
    p.add_argument("--live", action="store_true", help="Poll live feed (default Pump.fun frontend)")
    p.add_argument(
        "--feed",
        default=DEFAULT_FEED,
        choices=("pump", "bitquery"),
        help="Live discovery feed (default: pump = frontend-api-v3.pump.fun)",
    )
    p.add_argument(
        "--enrich-via",
        default=DEFAULT_ENRICH_VIA,
        choices=("auto", "helius", "pump", "bitquery"),
        help=(
            "Feature enrich source (default: helius = Pump Q5b + Helius ≤T0 Q5a/buy60). "
            "auto: helius if --feed pump else bitquery"
        ),
    )
    p.add_argument("--cycles", type=int, default=3, help="N ciclos (0=infinito). Default 3 para smoke")
    p.add_argument("--poll-interval", type=float, default=10.0, help="Segundos entre polls live")
    p.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=(
            "Within-batch safety AFTER threshold+capacity (default %(default)s). "
            "NOT the primary ultra-select — use --score-threshold / --train-top-frac."
        ),
    )
    p.add_argument(
        "--entry-rule",
        default=DEFAULT_ENTRY_RULE,
        choices=("train_quantile", "topk_batch", "off"),
        help=(
            "Default train_quantile = paper-trade-v1 Entrada A (score >= trainQ). "
            "topk_batch = legacy top-K every poll (debug only)."
        ),
    )
    p.add_argument(
        "--train-top-frac",
        type=float,
        default=DEFAULT_TRAIN_TOP_FRAC,
        help="Train quantile top-frac for Entrada A (default 0.01 = top 1%%)",
    )
    p.add_argument(
        "--score-threshold",
        type=float,
        default=None,
        help="Absolute score floor (e.g. 0.99 Sinck product). Omit → trainQ from calibration.",
    )
    p.add_argument(
        "--allow-non-train-threshold",
        action="store_true",
        help="Deprecated no-op: explicit --score-threshold is always allowed",
    )
    p.add_argument(
        "--max-per-hour",
        type=int,
        default=DEFAULT_MAX_PER_HOUR,
        help="Rolling capacity cap (~2/h ≈ trainQ_top1%% ~48/day; matches theory)",
    )
    p.add_argument("--hours-ago", type=int, default=2, help="Poll MC lookback hours (not Q5a)")
    p.add_argument(
        "--q5a-hours-ago",
        type=int,
        default=DEFAULT_Q5A_HOURS_AGO,
        help="Q5a trade lookback hours (create→T0; default %(default)s, not poll window)",
    )
    p.add_argument(
        "--recalibrate-journal",
        action="store_true",
        help="Repair SOL features on journaled histgb_q5b rows, re-score, report pass@top1%%; exit",
    )
    p.add_argument(
        "--recalibrate-write",
        action="store_true",
        help="With --recalibrate-journal: write repaired features+scores back to sqlite",
    )
    p.add_argument("--max-calls", type=int, default=8, help="Tope llamadas Bitquery por sesión live")
    p.add_argument(
        "--score-mode",
        default=DEFAULT_SCORE_MODE,
        choices=("rule_buy60", "histgb_buy60", "histgb_q5b", "lite"),
    )
    p.add_argument(
        "--parallel-score-modes",
        default="",
        help="Comma list e.g. histgb_q5b,lite — score each sighting on all lanes (opt-in)",
    )
    p.add_argument(
        "--enable-lite-lane",
        action="store_true",
        help="Shorthand: run histgb (score-mode) + lite explore lane in parallel",
    )
    p.add_argument(
        "--score-threshold-lite",
        type=float,
        default=0.55,
        help="Absolute thr for lite explore lane (stub default 0.55 until calib)",
    )
    p.add_argument(
        "--max-per-hour-lite",
        type=int,
        default=DEFAULT_MAX_PER_HOUR,
        help="Capacity cap for lite lane (separate stream)",
    )
    p.add_argument("--export-model", choices=("buy60", "+q5b"), default=None)
    p.add_argument(
        "--backtest-entry-gate",
        action="store_true",
        help="Report how many existing journal histgb_q5b scores pass the new gate; exit",
    )
    p.add_argument("--data-dir", type=Path, default=None)
    p.add_argument("--sample", type=Path, default=None)
    p.add_argument("--buy-vol-fixture", type=Path, default=None)
    p.add_argument("--q5-fixture", type=Path, default=None)
    p.add_argument(
        "--no-enrich-buy-vol",
        action="store_true",
        help="Disable legacy buy_vol-only enrich (ignored when enrich_q5 on)",
    )
    p.add_argument(
        "--no-enrich-q5",
        action="store_true",
        help="Disable full +q5b enrich (fall back to buy_vol-only if enabled)",
    )
    p.add_argument(
        "--allow-q5b-fallback",
        action="store_true",
        help="DEBUG only: name/symbol proxy when features missing (NOT WF-comparable)",
    )
    p.add_argument(
        "--enrich-only",
        action="store_true",
        help="Smoke: enrich +q5b for first sample/live mint batch then exit (no loop)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.export_model:
        meta = export_last_fold_model(set_name=args.export_model)
        print(json.dumps(meta, indent=2))
        return 0 if meta.get("status") == "ok" else 1

    if args.backtest_entry_gate:
        return _run_backtest_entry_gate(args)

    if args.recalibrate_journal:
        return _run_recalibrate_journal(args)

    dry = True
    live = False
    if args.live:
        live = True
        dry = False
    if args.dry_run:
        dry = True
        live = False
    if not args.live and not args.dry_run:
        dry = True

    cfg = PaperLiveConfig(
        dry_run=dry,
        live=live,
        feed=args.feed,
        enrich_via=args.enrich_via,
        cycles=args.cycles,
        poll_interval_s=args.poll_interval,
        top_k=args.top_k,
        hours_ago=args.hours_ago,
        q5a_hours_ago=args.q5a_hours_ago,
        max_calls_live=args.max_calls,
        score_mode=args.score_mode,
        parallel_score_modes=getattr(args, "parallel_score_modes", "") or "",
        enable_lite_lane=bool(getattr(args, "enable_lite_lane", False)),
        score_threshold_lite=getattr(args, "score_threshold_lite", 0.55),
        max_per_hour_lite=getattr(args, "max_per_hour_lite", DEFAULT_MAX_PER_HOUR),
        enrich_buy_vol=not args.no_enrich_buy_vol,
        enrich_q5=not args.no_enrich_q5,
        allow_q5b_fallback=args.allow_q5b_fallback,
        entry_rule=args.entry_rule,
        train_top_frac=args.train_top_frac,
        score_threshold=args.score_threshold,
        allow_non_train_threshold=args.allow_non_train_threshold,
        max_per_hour=args.max_per_hour,
    )
    # Default dry sample follows feed
    if args.sample is None and args.feed == "pump":
        cfg.sample_path = SAMPLE_PUMP
    if args.data_dir:
        cfg.data_dir = args.data_dir
        cfg.state_path = args.data_dir / "state.json"
        cfg.sqlite_path = args.data_dir / "paper_journal.sqlite"
    if args.sample:
        cfg.sample_path = args.sample
    if args.buy_vol_fixture:
        cfg.buy_vol_fixture_path = args.buy_vol_fixture
    if args.q5_fixture:
        cfg.q5_fixture_path = args.q5_fixture

    # Resolve threshold for banner (histgb only unless explicit)
    cal = load_calibration()
    thr = resolve_score_threshold(
        score_threshold=cfg.score_threshold,
        train_top_frac=cfg.train_top_frac,
        score_mode=cfg.score_mode,
        calibration=cal,
        allow_non_train_threshold=cfg.allow_non_train_threshold,
    )
    print(
        json.dumps(
            {
                "paper_live": "v0",
                "dry_run": cfg.dry_run,
                "live": cfg.live,
                "feed": cfg.feed,
                "enrich_via": cfg.enrich_via,
                "score_mode": cfg.score_mode,
                "entry_rule": cfg.entry_rule,
                "train_top_frac": cfg.train_top_frac,
                "score_threshold": thr,
                "max_per_hour": cfg.max_per_hour,
                "top_k_batch_safety": cfg.top_k,
                "cycles": cfg.cycles,
                "enrich_q5": cfg.enrich_q5,
                "enrich_buy_vol": cfg.enrich_buy_vol,
                "allow_q5b_fallback": cfg.allow_q5b_fallback,
                "data_dir": str(cfg.data_dir),
                "trading": False,
            },
            indent=2,
        ),
        flush=True,
    )

    if args.enrich_only:
        return _run_enrich_only(cfg)

    runner = PaperLiveRunner(cfg)
    summary = runner.run()
    print(json.dumps(summary, indent=2, default=str))
    return 0



def _run_recalibrate_journal(args: argparse.Namespace) -> int:
    from paper_live.calibrate import recalibrate_journal_scores
    from paper_live.config import SQLITE_PATH

    sqlite_path = SQLITE_PATH
    if args.data_dir:
        sqlite_path = Path(args.data_dir) / "paper_journal.sqlite"
    if not sqlite_path.is_file():
        print(json.dumps({"status": "missing_journal", "path": str(sqlite_path)}))
        return 1
    rep = recalibrate_journal_scores(
        sqlite_path,
        sol_usd=DEFAULT_SOL_USD_REF,
        write=bool(args.recalibrate_write),
    )
    import numpy as np

    def _stats(xs: list[float]) -> dict:
        if not xs:
            return {}
        a = np.asarray(xs, dtype=float)
        return {
            "n": int(len(a)),
            "min": float(a.min()),
            "median": float(np.median(a)),
            "mean": float(a.mean()),
            "p95": float(np.quantile(a, 0.95)),
            "p99": float(np.quantile(a, 0.99)),
            "max": float(a.max()),
        }

    doc = {
        "status": "ok",
        "kind": "paper_live_sol_calibration_repair",
        "sqlite": str(sqlite_path),
        "wrote": bool(args.recalibrate_write),
        "n_histgb": rep.n_histgb,
        "n_repaired": rep.n_repaired,
        "thr_top1": rep.thr_top1,
        "before": {
            **_stats(rep.before_scores),
            "n_pass_top1pct": rep.before_n_pass,
        },
        "after": {
            **_stats(rep.after_scores),
            "n_pass_top1pct": rep.after_n_pass,
        },
        "note": rep.note,
    }
    print(json.dumps(doc, indent=2))
    return 0


def _run_backtest_entry_gate(args: argparse.Namespace) -> int:
    """How many existing journal histgb_q5b paper scores would pass the new gate."""
    data_dir = args.data_dir or (ROOT / "data" / "paper_live")
    sqlite_path = Path(data_dir) / "paper_journal.sqlite"
    cal = load_calibration()
    thr = resolve_score_threshold(
        score_threshold=args.score_threshold,
        allow_non_train_threshold=args.allow_non_train_threshold,
        train_top_frac=args.train_top_frac,
        score_mode="histgb_q5b",
        calibration=cal,
    )
    assert thr is not None
    from paper_live.legacy_candidates import (
        PC1_NOT_SELECTIVITY,
        entry_metrics_from_sqlite,
        filter_path_a_pump_candidates,
        load_paper_candidate_rows,
    )

    scores: list[float] = []
    scores_raw_histgb: list[float] = []
    n_paper_histgb = 0
    n_paper_histgb_raw = 0
    legacy_meta: dict = {}
    if sqlite_path.is_file():

        all_pc = load_paper_candidate_rows(sqlite_path)
        histgb_raw = [
            r
            for r in all_pc
            if r.get("score_mode") == "histgb_q5b" and r.get("score") is not None
        ]
        scores_raw_histgb = [float(r["score"]) for r in histgb_raw]
        n_paper_histgb_raw = len(scores_raw_histgb)
        # D-06: entry/selectivity metrics exclude pc1 Bitquery/stub legacy stock
        histgb_path_a = [
            r
            for r in filter_path_a_pump_candidates(histgb_raw)
        ]
        scores = [float(r["score"]) for r in histgb_path_a]
        n_paper_histgb = len(scores)
        legacy_meta = entry_metrics_from_sqlite(sqlite_path).as_dict()
        con = sqlite3.connect(sqlite_path)
        # also all scored histgb sightings (raw; sightings filter is separate)
        sight = con.execute(
            "SELECT score FROM sightings WHERE score_mode='histgb_q5b' AND score IS NOT NULL"
        ).fetchall()
        sight_scores = [float(r[0]) for r in sight]
        con.close()
    else:
        sight_scores = []

    paper_bt = backtest_scores_against_threshold(scores, threshold=thr)
    paper_bt_raw = backtest_scores_against_threshold(scores_raw_histgb, threshold=thr)
    sight_bt = backtest_scores_against_threshold(sight_scores, threshold=thr)
    out = {
        "backtest_entry_gate": True,
        "entry_rule": "train_quantile",
        "train_top_frac": args.train_top_frac,
        "score_threshold": thr,
        "max_per_hour": args.max_per_hour,
        "calibration_source": (cal or {}).get("source"),
        "theory": (
            "paper-trade-v1 +q5b_trainQ_top1% ≈ 48.7 trades/day, P@top=100%; "
            "NOT top-20 every 10s batch"
        ),
        # Path A Pump filtered (excludes pc1=158 legacy) — use this for selectivity.
        "paper_candidates_histgb_q5b": paper_bt,
        "n_paper_histgb_q5b": n_paper_histgb,
        # Raw audit trail (includes 2026-10-01 Bitquery/stub) — NOT selectivity.
        "paper_candidates_histgb_q5b_raw_incl_legacy": paper_bt_raw,
        "n_paper_histgb_q5b_raw_incl_legacy": n_paper_histgb_raw,
        "legacy_filter": legacy_meta,
        "pc1_not_selectivity_claim": True,
        "pc1_note": PC1_NOT_SELECTIVITY,
        "sightings_scored_histgb_q5b": sight_bt,
        "trading": False,
    }
    print(json.dumps(out, indent=2, default=str))
    return 0


def _run_enrich_only(cfg: PaperLiveConfig) -> int:
    """One-shot enrich smoke (dry fixture / pump live / Bitquery live)."""
    from paper_live.feed import poll_bitquery, poll_pump, poll_sample
    from paper_live.q5_enrich import enrich_q5_for_sightings
    from features.post_q5_sets import FEATURE_SETS

    cfg.ensure_dirs()
    via = (cfg.enrich_via or "auto").lower()
    if via == "auto":
        via = "bitquery" if cfg.feed == "bitquery" else "helius"

    if cfg.live and not cfg.dry_run:
        if via == "bitquery" or (cfg.feed == "bitquery" and via != "helius" and via != "pump"):
            from ingestion.bitquery import BitqueryClient

            client = BitqueryClient(max_calls=max(4, cfg.max_calls_live))
            try:
                sightings, _log = poll_bitquery(limit=5, hours_ago=cfg.hours_ago, client=client)
                results = enrich_q5_for_sightings(
                    sightings[:2],
                    dry_run=False,
                    client=client,
                    trade_limit=cfg.q5a_trade_limit,
                    hours_ago=cfg.q5a_hours_ago,
                    enrich_q5a=cfg.enrich_q5a,
                    enrich_q5b=cfg.enrich_q5b,
                )
            finally:
                client.close()
            source = "live.bitquery"
        elif via == "pump":
            from ingestion.pump_frontend import PumpFrontendClient
            from paper_live.pump_enrich import enrich_pump_for_sightings

            client = PumpFrontendClient()
            try:
                sightings, _log = poll_pump(client=client)
                results = enrich_pump_for_sightings(
                    sightings[:5],
                    client=client,
                    fetch_priors=cfg.enrich_q5b,
                )
            finally:
                client.close()
            source = "live.pump"
        else:
            # hybrid default: pump discover + helius enrich
            from ingestion.helius_enhanced import HeliusEnhanced
            from ingestion.pump_frontend import PumpFrontendClient
            from paper_live.helius_enrich import enrich_helius_for_sightings

            pump = PumpFrontendClient()
            from paper_live.config import DEFAULT_HELIUS_MAX_PAGES_PRE_T0

            helius = HeliusEnhanced(
                max_calls=max(200, DEFAULT_HELIUS_MAX_PAGES_PRE_T0 * 4)
            )
            try:
                sightings, _log = poll_pump(client=pump)
                from paper_live.config import DEFAULT_HELIUS_MAX_PAGES_PRE_T0

                results = enrich_helius_for_sightings(
                    sightings[:2],
                    client=helius,
                    pump_client=pump,
                    dry_run=False,
                    fetch_priors=cfg.enrich_q5b,
                    sol_usd=None,  # Pyth as-of T0 (product); Jupiter/CG fallback
                    refine_t0=True,
                    max_pages_per_mint=DEFAULT_HELIUS_MAX_PAGES_PRE_T0,
                    sol_usd_as_of_t0=True,
                )
            finally:
                pump.close()
                helius.close()
            source = "live.hybrid.pump+helius"
    else:
        sightings = poll_sample(cfg.sample_path, batch=5)
        if via == "helius" or (via == "auto" and cfg.feed == "pump"):
            from paper_live.config import SAMPLE_HELIUS_TX_FIXTURE
            from paper_live.helius_enrich import enrich_helius_for_sightings

            results = enrich_helius_for_sightings(
                sightings,
                client=None,
                dry_run=True,
                fixture_path=SAMPLE_HELIUS_TX_FIXTURE,
                fetch_priors=False,
                sol_usd=cfg.sol_usd_ref,
            )
            source = "dry_run.helius_fixture"
        else:
            results = enrich_q5_for_sightings(
                sightings,
                dry_run=True,
                client=None,
                fixture_path=cfg.q5_fixture_path,
            )
            source = "dry_run.q5_fixture"

    rows = []
    for s in sightings[:5]:
        vr = results.get(s.mint)
        present = 0
        gaps = None
        if vr is not None:
            present = sum(1 for c in FEATURE_SETS["+q5b"] if vr.features.get(c) is not None)
            gaps = getattr(vr, "gaps", None)
        rows.append(
            {
                "mint": s.mint,
                "mc_usd": s.mc_usd,
                "buy_vol_usd_60s": None if vr is None else vr.buy_vol_usd_60s,
                "q5a_ok": False if vr is None else vr.q5a_ok,
                "q5b_ok": False if vr is None else vr.q5b_ok,
                "complete_q5b": False if vr is None else vr.complete_q5b,
                "n_feats_non_null": present,
                "n_feats_required": len(FEATURE_SETS["+q5b"]),
                "source": None if vr is None else vr.source,
                "gaps": gaps,
            }
        )
    out = {
        "enrich_only": True,
        "feed": cfg.feed,
        "enrich_via": via,
        "source": source,
        "n_sightings": len(sightings),
        "n_complete_q5b": sum(1 for r in rows if r["complete_q5b"]),
        "n_q5b_ok": sum(1 for r in rows if r["q5b_ok"]),
        "rows": rows,
        "trading": False,
        "cost_note": (
            "hybrid helius: pump /coins poll + Enhanced txs pages/mint (+ optional creator priors); "
            "bitquery: poll+1 + trades+1 + create+1 + priors+1 ≈ 4 calls; "
            "pump-only: Q5b without buy60/Q5a"
        ),
    }
    print(json.dumps(out, indent=2, default=str))
    # Pump-only live: success if sightings + q5b_ok (Q5a not expected)
    if source.startswith("live.pump") and "helius" not in source:
        return 0 if out["n_sightings"] > 0 and out["n_q5b_ok"] > 0 else (0 if out["n_sightings"] > 0 else 1)
    # Hybrid / bitquery / dry: prefer complete +q5b
    if source.startswith("live.hybrid") or source.startswith("dry_run.helius"):
        return 0 if out["n_sightings"] > 0 and (out["n_complete_q5b"] > 0 or out["n_q5b_ok"] > 0) else 1
    return 0 if out["n_complete_q5b"] > 0 or not rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
