#!/usr/bin/env python3
"""Post-recovery ge10 parity replay (2026-10-01).

Uses merged SolQA-PASS dump sigs → Helius parse-by-sig (sparingly).
Falls back to fetch_create_to_t0_txs when dump under-recovers vs prior ≥0.99.
Path A USD: sol×pyth_asof. Scale 6.6× OFF. Paper live FROZEN — no touch.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from features.post_q5_sets import FEATURE_SETS
from ingestion.bonding_curve import bonding_curve_pda
from ingestion.env import load_dotenv
from ingestion.helius_enhanced import HeliusEnhanced, fetch_create_to_t0_txs
from ingestion.helius_rpc import HeliusRpc
from ingestion.sol_usd_oracle import (
    apply_dune_helius_usd_scale_enabled,
    resolve_sol_usd_for_scoring,
)
from ingestion.t0_capture import find_t0_c1_c6_train_aligned
from paper_live.creator_priors import load_creator_prior_index
from paper_live.helius_enrich import buy_vol_60s_from_trades, parse_helius_enhanced_txs
from paper_live.q5a_agg import aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, fill_meta_from_dune_store_exact, q5b_from_create

PRIOR_CSV = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_20261001.csv"
DUMP_CSV = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_20261001.csv"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
MODEL_PATH = ROOT / "data" / "paper_live" / "models" / "q5b_last.joblib"
OUT_CSV = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_20261001.csv"
OUT_MD = ROOT / "cycle0" / "live-parity-replay-post-recovery-20261001.md"
OUT_JSON = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_20261001.json"
OUT_SUMMARY = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_summary.json"

FAIL_MINTS = {
    "BZofTtkyrBM2EDdRBN6GCavdWvxd61xbLTVFnoPgpump",
    "4M3gYZ2dQ39KuBuJYVmQi5qrtFfMpMWHpJhhx7Wapump",
}


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "+00:00").replace("Z", "+00:00").strip()
    return _aware(datetime.fromisoformat(s))


def _parse_by_sigs(helius: HeliusEnhanced, sigs: list[str]) -> list[dict]:
    key = helius._api_key  # noqa: SLF001
    url = "https://api.helius.xyz/v0/transactions/"
    out: list[dict] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(sigs), 100):
            chunk = sigs[i : i + 100]
            for attempt in range(6):
                helius._throttle()  # noqa: SLF001
                resp = client.post(url, params={"api-key": key}, json={"transactions": chunk})
                helius.log.n_calls += 1
                helius.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                out.extend(resp.json())
                break
            else:
                raise RuntimeError("parse 429 exhausted")
    return out


def _vec(feats: dict, cols: list[str]) -> np.ndarray:
    row = []
    for c in cols:
        v = feats.get(c)
        if v is None or (isinstance(v, float) and not np.isfinite(v)):
            row.append(np.nan)
        else:
            try:
                row.append(float(v))
            except (TypeError, ValueError):
                row.append(np.nan)
    return np.asarray(row, dtype=float).reshape(1, -1)


def _score_mint(
    *,
    mint: str,
    t0: datetime,
    create_ts: datetime,
    creator: str | None,
    mc0: float,
    txs: list[dict],
    sol_px: float,
    sol_src: str,
    model,
    cols: list[str],
    prior_idx,
) -> tuple[float, dict]:
    bc = str(bonding_curve_pda(mint))
    trades = parse_helius_enhanced_txs(txs, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0)
    trades_use = [x for x in trades if x.ts <= t0]
    create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
    priors = (
        prior_idx.priors_for(creator, this_mint=mint, as_of=create_ts, window_days=30)
        if creator and prior_idx.n_rows
        else []
    )
    q5b = q5b_from_create(create, t0, prior_creates=priors)
    # Fill name_len/symbol_* from train store when CreateRow lacks token_name (parity)
    q5b = fill_meta_from_dune_store_exact(q5b, prior_idx.exact_meta_for_mint(mint))
    q5a = aggregate_q5a_for_mint(trades_use, t0)
    buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
    feats = {**{c: q5b.get(c) for c in q5b}, **q5a, "buy_vol_usd_60s": float(buy60)}
    proba = float(model.predict_proba(_vec(feats, cols))[0, 1])
    cap = find_t0_c1_c6_train_aligned(
        trades,
        sighting_t0=t0,
        sighting_mc=mc0,
        sol_usd=sol_px,
        sol_usd_source=sol_src,
        create_ts=create_ts,
        complete_false=True,
    )
    meta = {
        "buy_vol_live": float(buy60),
        "buy_n_live": int(buy_n),
        "n_trades_pre_t0": len(trades_use),
        "n_txs_le_t0": len(txs),
        "n_priors": len(priors),
        "prior_source": prior_idx.source,
        "t0_refine_detail": cap.detail,
        "capture_quality": cap.capture_quality,
    }
    return proba, meta


def main() -> int:
    load_dotenv()
    assert apply_dune_helius_usd_scale_enabled() is False
    print("scale_off OK; dump=", DUMP_CSV.name, flush=True)

    prior = pd.read_csv(PRIOR_CSV)
    dump = pd.read_csv(DUMP_CSV)
    dump_by = {m: g for m, g in dump.groupby("mint")}

    need = list(
        set(FEATURE_SETS["+q5b"])
        | {"mint", "create_ts", "creator_pubkey", "buy_vol_usd_60s", "buy_count_total", "mc_usd_t0", "age_s"}
    )
    fs = pd.read_csv(FS_PATH, usecols=lambda c: c in need)
    fs_by = {r.mint: r for r in fs.itertuples(index=False)}
    _bundle = joblib.load(MODEL_PATH)
    model = _bundle["pipeline"] if isinstance(_bundle, dict) else _bundle
    cols = (
        list(_bundle.get("feature_names") or FEATURE_SETS["+q5b"])
        if isinstance(_bundle, dict)
        else list(FEATURE_SETS["+q5b"])
    )
    prior_idx = load_creator_prior_index()
    print(f"priors={prior_idx.source} n={prior_idx.n_rows} features={len(cols)}", flush=True)

    results = []
    with HeliusEnhanced(max_calls=800, max_retries_429=8) as helius, HeliusRpc() as rpc:
        for i, row in enumerate(prior.itertuples(index=False), 1):
            mint = str(row.mint)
            t0 = _parse_t0(row.t0_ts)
            oos = float(row.oos_score)
            before_live = float(row.live_rebuild_score)
            before_trades = int(row.n_trades_pre_t0)
            print(f"[{i}/12] {mint[:16]}… oos={oos:.4f} before={before_live:.4f}", flush=True)

            tr = fs_by.get(mint)
            if tr is None:
                results.append({"mint": mint, "error": "no_train", "oos_score": oos})
                continue
            create_ts = t0
            if getattr(tr, "create_ts", None) and str(tr.create_ts) not in ("nan", "None"):
                try:
                    create_ts = _parse_t0(str(tr.create_ts))
                except Exception:
                    pass
            creator = getattr(tr, "creator_pubkey", None)
            creator = str(creator) if creator and str(creator) != "nan" else None
            mc0 = float(getattr(tr, "mc_usd_t0", 12000) or 12000)
            train_buys = float(getattr(tr, "buy_count_total", 0) or 0)

            q_score, reason = resolve_sol_usd_for_scoring(
                as_of=t0, allow_network=True, require_pyth=True
            )
            if q_score is None:
                q_score, reason = resolve_sol_usd_for_scoring(
                    as_of=t0, allow_network=True, require_pyth=False
                )
            if q_score is None:
                results.append({"mint": mint, "error": f"usd:{reason}", "oos_score": oos})
                continue
            sol_px, sol_src = float(q_score.price), q_score.source

            dg = dump_by.get(mint)
            fetch_mode = "dump_parse_by_sig"
            gaps: list[str] = [f"sol={sol_px:.4f}/{sol_src}", f"usd_reason={reason}"]
            txs: list[dict] = []
            if dg is not None and len(dg):
                sigs = [str(s) for s in dg["tx_sig"].dropna().unique().tolist() if s]
                txs = _parse_by_sigs(helius, sigs)
                gaps.append(f"dump_sigs={len(sigs)} parsed={len(txs)}")
            else:
                gaps.append("dump_missing")

            proba, meta = _score_mint(
                mint=mint,
                t0=t0,
                create_ts=create_ts,
                creator=creator,
                mc0=mc0,
                txs=txs,
                sol_px=sol_px,
                sol_src=sol_src,
                model=model,
                cols=cols,
                prior_idx=prior_idx,
            )

            # Fallback: dump under-recovered a prior passer, or fail mint still weak
            need_fetch = False
            if mint in FAIL_MINTS and meta["n_trades_pre_t0"] < max(2, int(train_buys) - 1):
                need_fetch = True
                gaps.append("fallback:fail_trades_low")
            elif before_live >= 0.99 and proba < 0.99:
                need_fetch = True
                gaps.append("fallback:regressed_below_0.99")
            elif meta["n_trades_pre_t0"] < before_trades and before_live >= 0.99:
                # keep dump score if still ≥0.99; else fetch
                if proba < 0.99:
                    need_fetch = True
                    gaps.append("fallback:fewer_trades_than_prior")

            if need_fetch:
                bc = str(bonding_curve_pda(mint))
                txs2, egaps = fetch_create_to_t0_txs(
                    helius,
                    mint,
                    t0=t0,
                    create_ts=create_ts,
                    bonding_curve=bc,
                    rpc=rpc,
                    max_pages_enhanced=80,
                    max_pages_rpc=80,
                )
                gaps.extend(egaps[:8])
                fetch_mode = "enhanced+rpc(+slot)_fallback"
                proba2, meta2 = _score_mint(
                    mint=mint,
                    t0=t0,
                    create_ts=create_ts,
                    creator=creator,
                    mc0=mc0,
                    txs=txs2,
                    sol_px=sol_px,
                    sol_src=sol_src,
                    model=model,
                    cols=cols,
                    prior_idx=prior_idx,
                )
                # Prefer higher trade count / better score path
                if meta2["n_trades_pre_t0"] >= meta["n_trades_pre_t0"]:
                    proba, meta = proba2, meta2
                    gaps.append(
                        f"fallback_used trades={meta['n_trades_pre_t0']} score={proba:.4f}"
                    )
                else:
                    gaps.append("fallback_worse_kept_dump")

            train_feats = {c: getattr(tr, c, None) for c in cols}
            train_rescore = float(model.predict_proba(_vec(train_feats, cols))[0, 1])

            rec = {
                "mint": mint,
                "band": row.band,
                "t0_ts": row.t0_ts,
                "oos_score": oos,
                "train_store_rescore": train_rescore,
                "live_rebuild_score": proba,
                "before_recovery_score": before_live,
                "before_n_trades_pre_t0": before_trades,
                "delta_oos_minus_live": oos - proba,
                "buy_vol_train": float(getattr(tr, "buy_vol_usd_60s", 0) or 0),
                "buy_vol_live": meta["buy_vol_live"],
                "buy_n_live": meta["buy_n_live"],
                "n_trades_pre_t0": meta["n_trades_pre_t0"],
                "n_txs_le_t0": meta["n_txs_le_t0"],
                "train_buy_count_total": train_buys,
                "sol_usd": sol_px,
                "sol_usd_source": sol_src,
                "fetch_mode": fetch_mode,
                "prior_source": meta["prior_source"],
                "n_priors": meta["n_priors"],
                "pass_ge_0.99": bool(proba >= 0.99),
                "pass_ge_0.89": bool(proba >= 0.89),
                "is_fail_recovery_target": mint in FAIL_MINTS,
                "gaps": gaps[:12],
                "helius_calls": helius.n_calls,
            }
            results.append(rec)
            print(
                f"  live={proba:.4f} before={before_live:.4f} trades={meta['n_trades_pre_t0']}"
                f"/{int(train_buys)} mode={fetch_mode} pass99={proba>=0.99}",
                flush=True,
            )

    df = pd.DataFrame(results)
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False)
    OUT_JSON.write_text(json.dumps(results, indent=2, default=str))

    ok = df.dropna(subset=["live_rebuild_score"]) if "live_rebuild_score" in df.columns else df
    n_pass = int((ok["live_rebuild_score"] >= 0.99).sum()) if len(ok) else 0
    summary = {
        "n": int(len(ok)),
        "n_ge_0.99": n_pass,
        "pct_ge_0.99": float((ok["live_rebuild_score"] >= 0.99).mean()) if len(ok) else None,
        "pct_ge_0.89": float((ok["live_rebuild_score"] >= 0.89).mean()) if len(ok) else None,
        "median_live": float(ok["live_rebuild_score"].median()) if len(ok) else None,
        "mean_live": float(ok["live_rebuild_score"].mean()) if len(ok) else None,
        "scale_enabled": False,
        "sol_usd_sources": sorted(ok["sol_usd_source"].dropna().unique().tolist())
        if "sol_usd_source" in ok
        else [],
        "threshold_product": 0.99,
        "threshold_note": "Sinck product abs 0.99; trainQ top1%~0.9998 / top5% / top10% fold thr 0.66–0.92",
        "dump": str(DUMP_CSV),
        "csv": str(OUT_CSV),
        "qa_merged": "data/samples/qa_helius_parity_tx_dump_merged_le_t0_report.json",
        "paper_live": "FROZEN_untouched",
    }
    # fail mint detail
    fail_detail = {}
    for m in FAIL_MINTS:
        sub = ok[ok["mint"] == m]
        if len(sub):
            r = sub.iloc[0]
            fail_detail[m[:12]] = {
                "before": float(r["before_recovery_score"]),
                "after": float(r["live_rebuild_score"]),
                "n_trades_before": int(r["before_n_trades_pre_t0"]),
                "n_trades_after": int(r["n_trades_pre_t0"]),
                "pass_ge_0.99": bool(r["pass_ge_0.99"]),
            }
    summary["fail_targets"] = fail_detail
    OUT_SUMMARY.write_text(json.dumps(summary, indent=2) + "\n")

    # Markdown report (built as md_body below)

        # Rewrite per-mint table correctly (itertuples renames)
    # Rebuild MD from dataframe without itertuples alias issues
    md_body = [
        "# Live parity replay post-recovery — 2026-10-01",
        "",
        "Paper live: **FROZEN** (untouched). Scale 6.6×: **OFF**. Path A: `amount_usd = sol_amt × pyth_asof`.",
        "",
        "## Sources",
        "",
        f"- Merged dump (SolQA PASS): `{DUMP_CSV.relative_to(ROOT)}`",
        "- QA gate: `data/samples/qa_helius_parity_tx_dump_merged_le_t0_report.json`",
        f"- Prior replay (10/12): `{PRIOR_CSV.relative_to(ROOT)}`",
        f"- Model: `{MODEL_PATH.relative_to(ROOT)}` + `FEATURE_SETS['+q5b']`",
        "- Threshold: **0.99** abs (Sinck product); trainQ top1% ≈0.9998 / top5% / top10% fold thr ~0.66–0.92 (note only)",
        "",
        "## Result",
        "",
        "| metric | value |",
        "|--------|------:|",
        f"| n | {summary['n']} |",
        f"| live ≥ 0.99 | **{n_pass}/{summary['n']}** |",
        f"| live ≥ 0.89 | {int((ok['live_rebuild_score']>=0.89).sum())}/{summary['n']} |",
        f"| median live | {summary['median_live']:.6f} |",
        f"| sol_usd_source | {', '.join(summary['sol_usd_sources'])} |",
        "",
        "## Fail-target before → after",
        "",
        "| mint | before score | after score | trades before→after | ≥0.99 |",
        "|------|-------------:|------------:|--------------------:|:-----:|",
    ]
    for m in sorted(FAIL_MINTS):
        sub = ok[ok["mint"] == m]
        if not len(sub):
            continue
        r = sub.iloc[0]
        md_body.append(
            f"| {m[:12]}… | {r['before_recovery_score']:.4f} | **{r['live_rebuild_score']:.4f}** | "
            f"{int(r['before_n_trades_pre_t0'])}→{int(r['n_trades_pre_t0'])} | "
            f"{'YES' if r['pass_ge_0.99'] else 'NO'} |"
        )
    md_body += [
        "",
        "## Per-mint",
        "",
        "| mint | oos | live | before | n_trades | sol_src | prior_src | pass≥0.99 |",
        "|------|----:|-----:|-------:|---------:|---------|-----------|:---------:|",
    ]
    for _, r in ok.iterrows():
        md_body.append(
            f"| {str(r['mint'])[:12]}… | {r['oos_score']:.4f} | {r['live_rebuild_score']:.4f} | "
            f"{r['before_recovery_score']:.4f} | {int(r['n_trades_pre_t0'])} | {r['sol_usd_source']} | "
            f"{r['prior_source']} | {'Y' if r['pass_ge_0.99'] else 'N'} |"
        )
    fails = ok[ok["live_rebuild_score"] < 0.99]
    md_body += ["", "## Residual mismatches", ""]
    if len(fails) == 0:
        md_body.append("None — all 12 live ≥ 0.99.")
    else:
        md_body.append("| mint | oos | live | Δ | trades | train_buys | notes |")
        md_body.append("|------|----:|-----:|--:|-------:|-----------:|-------|")
        for _, r in fails.iterrows():
            notes = "fail_recovery" if r["mint"] in FAIL_MINTS else "incomplete_vs_train"
            md_body.append(
                f"| {str(r['mint'])[:12]}… | {r['oos_score']:.4f} | {r['live_rebuild_score']:.4f} | "
                f"{r['delta_oos_minus_live']:.4f} | {int(r['n_trades_pre_t0'])} | "
                f"{int(r['train_buy_count_total'])} | {notes} |"
            )
    md_body += [
        "",
        "## Artifacts",
        "",
        f"- CSV: `{OUT_CSV.relative_to(ROOT)}`",
        f"- JSON: `{OUT_JSON.relative_to(ROOT)}`",
        f"- Summary: `{OUT_SUMMARY.relative_to(ROOT)}`",
        "",
        "## Method",
        "",
        "1. Load 12 OOS≥0.99 mints from prior ge10 CSV.",
        "2. Resolve Path A USD via `resolve_sol_usd_for_scoring(..., require_pyth=True)` → pyth_asof.",
        "3. Prefer merged dump tx_sigs → Enhanced parse-by-sig (no re-getBlock).",
        "4. Parse with SolDatos WSOL multi-leg path; aggregate Q5a/Q5b; score `q5b_last.joblib`.",
        "5. Fallback `fetch_create_to_t0_txs` only if dump under-recovers a prior passer or fail target.",
        "",
    ]
    OUT_MD.write_text("\n".join(md_body) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    print("wrote", OUT_CSV, OUT_MD, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
