#!/usr/bin/env python3
"""Build Pump-true / Pump-path feature matrix offline (0 Dune credits).

Modes
-----
1. ``journal`` (default, no network): extract Path A Pump scoreable rows from
   ``paper_journal.sqlite`` → ``features_pump_path_a_journal_YYYYMMDD.csv``.
   Join labels by mint when present (usually 0 for live cohort).
2. ``smoke`` (≤20 mints, Pump frontend only): re-fetch trades for journal mints,
   re-aggregate Q5a/buy60 via ``parse_pump_frontend_trades`` + ``aggregate_q5a_for_mint``,
   write ``features_pump_path_a_smoke_YYYYMMDD.csv``. Proves pipeline; STOP before scale.
3. ``plan-only``: print full expand rebuild API volume estimate and exit (no network).

Never calls Dune. Never overwrites ``q5b_last.joblib``. Never touches paper_live PID.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS  # noqa: E402

JOIN_COLS = ("mint", "t0_ts", "mc_usd_t0", "label_hit_10x_30d", "label_hit_200k", "label_source")
META_COLS = (
    "sol_usd_source",
    "sol_usd_t0",
    "creator_prior_source",
    "meta_source",
    "t0_definition",
    "capture_scoreable",
    "n_trades_pre_t0",
    "features_complete_q5b",
    "buy_vol_usd_60s",
    "journal_created_at",
    "score_mode_logged",
    "score_logged",
)

# Column taxonomy: live Pump enrich vs train expand / +q5b
COLUMN_MAP: dict[str, dict[str, Any]] = {}


def _utcnow_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def build_column_map() -> dict[str, Any]:
    """Classify +q5b + expand-only vs live Pump construction."""
    q5b = list(FEATURE_SETS["+q5b"])
    identical = [
        # Windowed Q5a / buy60: same q5a_agg / buy_vol windows; input trades differ
        "buy_vol_usd_60s",
        "buy_count_15m",
        "buy_count_30s",
        "buy_count_total",
        "buy_vol_first_10s",
        "buy_vol_first_5s",
        "buy_vol_usd_15m",
        "buy_vol_usd_30s",
        "buy_vol_usd_total",
        "first10_buy_vol_usd",
        "first5_buy_vol_share",
        "first5_buy_vol_usd",
        "first_buy_usd",
        "max_buy_share",
        "max_buy_sol",
        "max_buy_usd",
        "n_holders_proxy",
        "sell_count_15m",
        "sell_count_30s",
        "sell_count_total",
        "sell_vol_usd_15m",
        "sell_vol_usd_30s",
        "sell_vol_usd_total",
        "sniper_vol_share_5s",
        "top10_buyer_vol_share",
        "top10_holder_pct_proxy",
        "top1_buyer_vol_share",
        "top1_holder_pct_proxy",
        "top5_buyer_vol_share",
        "top5_holder_pct_proxy",
        "unique_buyers_first5",
        "unique_buyers_first_5s",
        "unique_buyers_total",
        "unique_sellers_total",
        "unique_traders_15m",
        "unique_traders_30s",
    ]
    remapped = {
        "age_s": "Pump create_ts vs Dune CreateEvent; same age_s_from_create helper",
        "age_min": "derived from age_s",
        "age_proxy_s": "LIVE OVERWRITE: set to age_s (create→T0); TRAIN Q5a: t0−first_trade",
        "has_creator": "Pump coin.creator vs Dune create row",
        "name_len": "Pump sighting/coin name vs CreateEvent",
        "name_missing": "same",
        "symbol_len": "Pump sighting/coin symbol vs CreateEvent",
        "symbol_missing": "same",
        "creator_prior_mints_7d": "dune_cohort exact/recompute/empty (post A); was Pump frontend until restart",
        "creator_prior_mints_30d": "same",
        "creator_prior_mints_cohort": "same",
        "progress_curve_proxy": "LIVE: Pump coin curve overlay OVERWRITES trade agg; TRAIN: trade net_sol/85",
        "net_sol_curve": "LIVE: Pump coin overlay; TRAIN: sum signed sol pumpdotfun≤T0",
        "net_sol_total": "LIVE: setdefault from coin overlay if missing; TRAIN: all-project signed sol",
        "max_buy_usd": "USD source: Pump valueUsd vs Dune amount_usd (scale OFF)",
        # buy_vol_usd_60s stays in identical_agg_windows; USD source note below covers all USD legs
    }
    null_on_live = {
        "creator_prior_mints_all_in_window": "always None live+train (~99.99% null train)",
    }
    pump_only_meta = [
        "sol_usd_source",
        "sol_usd_t0",
        "capture_quality",
        "capture_scoreable",
        "t0_definition",
        "t0_refined",
        "mc_usd_t0_capture",
        "n_trades_pre_t0",
        "helius_trade_refine_required",
        "creator_prior_source",
        "creator_priors_incomplete",
        "meta_source",
        "age_from_create_ok",
        "age_from_create_reason",
        "score_reject_reason",
        "buy_vol_source",
        "features_complete_buy60",
        "features_complete_q5b",
    ]
    dune_only_expand = [
        "mc_usd_t0",
        "price_usd_t0",
        "mc_band_pos",
        "log1p_mc_usd_t0",
        "is_pumpdotfun",
        "buy_count_60s",
        "sell_count_60s",
        "sell_vol_usd_60s",
        "unique_traders_60s",
        "buy_count_5m",
        "sell_count_5m",
        "buy_vol_usd_5m",
        "sell_vol_usd_5m",
        "unique_traders_5m",
        "trade_count_total",
        "unique_traders_total",
        "time_since_first_trade_s",
        "migrated_pre_t0",  # banned from X
    ]
    # buy_vol listed in identical; note USD remap separately
    identical_set = [c for c in identical if c not in remapped]
    remapped_only = {k: v for k, v in remapped.items() if k != "buy_vol_usd_60s"}
    return {
        "recipe": "+q5b",
        "n_recipe": len(q5b),
        "identical_agg_windows": identical_set,
        "remapped": remapped_only,
        "usd_source_note": (
            "All USD legs on Pump path use frontend valueUsd (or sol×sol_usd if missing); "
            "train uses Dune amount_usd. APPLY_DUNE_HELIUS_USD_SCALE stays OFF."
        ),
        "null_on_live": null_on_live,
        "pump_only_meta_not_in_X": pump_only_meta,
        "dune_only_expand_not_in_+q5b_X": dune_only_expand,
        "coverage_check": {
            "identical_plus_remapped_plus_null": sorted(
                set(identical_set) | set(remapped_only) | set(null_on_live)
            ),
            "missing_from_taxonomy": sorted(
                set(q5b)
                - set(identical_set)
                - set(remapped_only)
                - set(null_on_live)
            ),
        },
    }


def _load_label_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    with path.open(newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            m = row.get("mint")
            if not m:
                continue
            out[m] = {
                "hit_10x_30d": row.get("hit_10x_30d"),
                "hit_200k": row.get("hit_200k"),
            }
    return out


def _is_pump_path_a(feats: dict[str, Any]) -> bool:
    return feats.get("t0_definition") == "pump_mc_band_sighting_v1"


def extract_journal_rows(
    db_path: Path,
    *,
    scoreable_only: bool = True,
    since: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    sql = "SELECT mint, t0_ts, mc_usd_t0, score, score_mode, features_json, created_at FROM sightings"
    clauses: list[str] = []
    args: list[Any] = []
    if since:
        clauses.append("created_at >= ?")
        args.append(since)
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY rowid DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows_out: list[dict[str, Any]] = []
    for r in con.execute(sql, args):
        if not r["features_json"]:
            continue
        try:
            feats = json.loads(r["features_json"])
        except json.JSONDecodeError:
            continue
        if not _is_pump_path_a(feats):
            continue
        if scoreable_only and not feats.get("capture_scoreable"):
            continue
        row: dict[str, Any] = {
            "mint": r["mint"],
            "t0_ts": r["t0_ts"] or feats.get("t0_ts"),
            "mc_usd_t0": r["mc_usd_t0"] if r["mc_usd_t0"] is not None else feats.get("mc_usd_t0_capture"),
            "journal_created_at": r["created_at"],
            "score_mode_logged": r["score_mode"],
            "score_logged": r["score"],
        }
        for c in FEATURE_SETS["+q5b"]:
            row[c] = feats.get(c)
        for c in META_COLS:
            if c in row:
                continue
            row[c] = feats.get(c)
        rows_out.append(row)
    con.close()
    # newest-first; keep first occurrence per mint
    seen: set[str] = set()
    dedup: list[dict[str, Any]] = []
    for row in rows_out:
        m = row["mint"]
        if m in seen:
            continue
        seen.add(m)
        dedup.append(row)
    return dedup


def join_labels(
    rows: list[dict[str, Any]], labels: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    n_hit = 0
    for row in rows:
        lab = labels.get(row["mint"])
        if lab:
            n_hit += 1
            row["label_hit_10x_30d"] = lab.get("hit_10x_30d")
            row["label_hit_200k"] = lab.get("hit_200k")
            row["label_source"] = "labels_dune_expand_v2"
        else:
            row["label_hit_10x_30d"] = None
            row["label_hit_200k"] = None
            row["label_source"] = None
    return rows, {"n_rows": len(rows), "n_label_join": n_hit}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(JOIN_COLS) + list(FEATURE_SETS["+q5b"]) + [
        c for c in META_COLS if c not in JOIN_COLS and c != "buy_vol_usd_60s"
    ]
    # buy_vol already in +q5b
    fieldnames = list(dict.fromkeys(fieldnames))
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def estimate_full_rebuild() -> dict[str, Any]:
    """API volume fence for expand-scale Pump trades rebuild — STOP before run."""
    n_expand = 0
    expand = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    if expand.is_file():
        with expand.open() as f:
            n_expand = sum(1 for _ in f) - 1
    # Empirical: live smoke ~110–200 trades/mint, max_pages=5, limit=200 → ≤1000 rows/mint
    pages_per_mint = 5
    req_per_mint = pages_per_mint  # sequential cursor pages
    return {
        "target": "features_pump_path_a_expand_v1.csv joined to labels_dune_expand_v2 by mint",
        "n_expand_mints": n_expand,
        "api": "GET https://frontend-api-v3.pump.fun/trades/{urlencoded solana:5eykt4Us…}/{mint}?limit=200&cursor=",
        "pages_per_mint_cap": pages_per_mint,
        "estimated_http_requests": n_expand * req_per_mint,
        "estimated_trade_rows_upper": n_expand * pages_per_mint * 200,
        "dune_credits": 0,
        "cost_fence": (
            f"~{n_expand * req_per_mint:,} Pump frontend HTTP GETs "
            f"(~{n_expand:,} mints × {pages_per_mint} pages). "
            "No Dune. STOP — do not run at this scale without Sinck GO + rate-limit plan."
        ),
        "recommended_pilot": "n=200–2000 expand mints with create_ts near train_t0_max, or journal smoke ≤20",
        "blockers": [
            "Historical Pump trades availability for old expand mints unknown (API may truncate)",
            "Pump T0 (MC band sighting) ≠ expand t0_ts (C1–C6 / Dune) — need T0 rebase policy",
            "Live mints have Pump features but 0 label overlap with expand",
            "USD: valueUsd vs Dune amount_usd residual remains even after rebuild",
        ],
    }


def run_smoke(mints: list[str], *, max_mints: int = 20) -> list[dict[str, Any]]:
    """Re-fetch ≤max_mints via Pump frontend and rebuild +q5b trade legs."""
    from datetime import datetime as dt
    from ingestion.pump_frontend import PumpFrontendClient, fetch_trades_for_mint
    from paper_live.pump_enrich import (
        buy_vol_60s_from_trades,
        parse_pump_frontend_trades,
    )
    from paper_live.q5a_agg import aggregate_q5a_for_mint

    mints = mints[: max(0, min(int(max_mints), 20))]
    if not mints:
        return []
    client = PumpFrontendClient()
    out: list[dict[str, Any]] = []
    try:
        for mint in mints:
            try:
                raw = fetch_trades_for_mint(mint, limit=200, client=client, max_pages=3)
            except Exception as e:  # noqa: BLE001
                out.append({"mint": mint, "error": str(e)[:200], "n_trades_pre_t0": 0})
                continue
            # Use latest trade time as synthetic T0 upper bound for smoke (journal T0 preferred upstream)
            t0 = dt.now(timezone.utc)
            trades = parse_pump_frontend_trades(raw or [], mint=mint, t0=t0, sol_usd=0.0)
            if trades:
                t0 = max(tr.ts for tr in trades)
                trades = parse_pump_frontend_trades(raw or [], mint=mint, t0=t0, sol_usd=0.0)
            q5a = aggregate_q5a_for_mint(trades, t0) if trades else {c: None for c in Q5A_COLS}
            buy60, buy_n = buy_vol_60s_from_trades(trades, t0) if trades else (None, None)
            row: dict[str, Any] = {
                "mint": mint,
                "t0_ts": t0.isoformat(),
                "n_trades_pre_t0": len(trades),
                "buy_vol_usd_60s": buy60,
                "buy_count_60s": buy_n,
                "sol_usd_source": "pump_frontend",
                "smoke_note": "T0=max(trade.ts) when journal T0 not passed — pipeline proof only",
            }
            for c in Q5A_COLS:
                row[c] = q5a.get(c)
            for c in Q5B_COLS:
                row.setdefault(c, None)
            out.append(row)
    finally:
        client.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--mode",
        choices=("journal", "smoke", "plan-only", "column-map"),
        default="journal",
    )
    ap.add_argument(
        "--stamp",
        default=datetime.now().strftime("%Y%m%d"),
    )
    ap.add_argument(
        "--journal",
        type=Path,
        default=ROOT / "data/paper_live/paper_journal.sqlite",
    )
    ap.add_argument(
        "--labels",
        type=Path,
        default=ROOT / "data/samples/labels_dune_expand_v2.csv",
    )
    ap.add_argument("--since", default="2026-10-02", help="journal created_at lower bound")
    ap.add_argument("--smoke-n", type=int, default=5, help="≤20; default 5")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=ROOT / "data/samples",
    )
    ap.add_argument(
        "--inventory-out",
        type=Path,
        default=ROOT / "cycle0/artifacts/pump_true_feature_inventory_20261002.json",
    )
    args = ap.parse_args()

    colmap = build_column_map()
    plan = estimate_full_rebuild()

    if args.mode == "column-map":
        print(json.dumps(colmap, indent=2))
        return 0
    if args.mode == "plan-only":
        print(json.dumps(plan, indent=2))
        return 0

    labels = _load_label_index(args.labels)
    journal_rows = extract_journal_rows(
        args.journal, scoreable_only=True, since=args.since
    )
    journal_rows, join_stats = join_labels(journal_rows, labels)

    out_journal = args.out_dir / f"features_pump_path_a_journal_{args.stamp}.csv"
    write_csv(out_journal, journal_rows)

    smoke_rows: list[dict[str, Any]] = []
    out_smoke: Path | None = None
    if args.mode == "smoke":
        n = min(max(args.smoke_n, 0), 20)
        mints = [r["mint"] for r in journal_rows[:n]]
        if not mints:
            # fallback: any recent pump scoreable without since filter
            mints = [
                r["mint"]
                for r in extract_journal_rows(args.journal, scoreable_only=True, since=None)[:n]
            ]
        print(f"[smoke] fetching ≤{n} mints via Pump frontend (0 Dune): {mints}")
        smoke_rows = run_smoke(mints, max_mints=n)
        smoke_rows, smoke_join = join_labels(smoke_rows, labels)
        out_smoke = args.out_dir / f"features_pump_path_a_smoke_{args.stamp}.csv"
        write_csv(out_smoke, smoke_rows)
        join_stats["smoke"] = smoke_join
        join_stats["smoke_n_ok"] = sum(1 for r in smoke_rows if r.get("n_trades_pre_t0", 0) > 0)

    # Inventory artifact
    helius_paths = sorted(
        str(p.relative_to(ROOT))
        for p in (ROOT / "data/samples").glob("helius_parity_features_*.csv")
    )
    pump_samples = [
        "data/samples/pump_frontend_mc_8k_20k_sample.json",
        "data/samples/pump_frontend_mc200k_current.json",
        "cycle0/artifacts/pump_trades_smoke_rebuild_20261002.json",
        "cycle0/artifacts/pump_trades_smoke_20261002.json",
    ]
    inv = {
        "kind": "pump_true_feature_inventory",
        "generated_at": _utcnow_local(),
        "zone": "Europe/Madrid",
        "dune_calls": 0,
        "paper_live_pid_untouched": True,
        "q5b_last_md5_expected": "4df6d5a8dff6bf66528d4ee4cf6641b2",
        "column_map": colmap,
        "local_sources": {
            "journal_sqlite": str(args.journal.relative_to(ROOT)) if args.journal.is_relative_to(ROOT) else str(args.journal),
            "journal_pump_scoreable_rows": len(journal_rows),
            "journal_label_joins": join_stats.get("n_label_join", 0),
            "expand_features": "data/samples/features_dune_p0_q5_expand_v2.csv",
            "labels": "data/samples/labels_dune_expand_v2.csv",
            "dune_q5a": "data/samples/dune_q5a_features.csv",
            "dune_q5b": "data/samples/dune_q5b_features.csv",
            "helius_parity_feature_csvs": helius_paths,
            "helius_note": "Helius dumps overlap expand (~65 mints) but are Helius-scale USD — not Pump-true",
            "pump_samples": [p for p in pump_samples if (ROOT / p).exists()],
            "pump_trades_fixture_usable": True,
        },
        "outputs": {
            "journal_csv": str(out_journal.relative_to(ROOT)),
            "smoke_csv": (
                str(out_smoke.relative_to(ROOT))
                if out_smoke
                else (
                    str((args.out_dir / f"features_pump_path_a_smoke_{args.stamp}.csv").relative_to(ROOT))
                    if (args.out_dir / f"features_pump_path_a_smoke_{args.stamp}.csv").is_file()
                    else None
                )
            ),
            "full_expand_csv": None,
            "full_expand_status": "BLOCKED — see full_rebuild_plan; STOP before scale",
        },
        "join_stats": join_stats,
        "full_rebuild_plan": plan,
        "gaps": [
            "Live Pump journal mints ∉ expand labels (0 join) — cannot WF on journal alone",
            "No historical Pump trades store for expand mints on disk",
            "Pump T0 definition ≠ expand t0_ts — rebuild must pick T0 policy",
            "age_proxy_s live overwrite vs train first-trade definition",
            "progress_curve_proxy / net_sol_curve Pump coin overlay vs trade-only train",
        ],
    }
    args.inventory_out.parent.mkdir(parents=True, exist_ok=True)
    args.inventory_out.write_text(json.dumps(inv, indent=2))
    summary = {
        "mode": args.mode,
        "journal_rows": len(journal_rows),
        "label_joins": join_stats.get("n_label_join", 0),
        "out_journal": str(out_journal),
        "out_smoke": str(out_smoke) if out_smoke else None,
        "smoke_rows": len(smoke_rows),
        "inventory": str(args.inventory_out),
        "dune_calls": 0,
        "full_rebuild_estimate_http": plan["estimated_http_requests"],
        "stop_before_scale": True,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
