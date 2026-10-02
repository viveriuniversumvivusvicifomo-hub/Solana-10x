#!/usr/bin/env python3
"""Fast historical ≤T0 rebuild for OOS≥0.99 parity (2026-10-01).

SolDatos helpers:
  - resolve_sol_usd(as_of=t0)
  - fetch_pre_t0_enhanced_txs (BC-first; mint pages limited)
  - find_t0_c1_c6 (reported, scoring uses fixed OOS t0 — no look-ahead)
  - APPLY_DUNE_HELIUS_USD_SCALE default OFF

For age≈0 / hot post-T0 mints, Enhanced mint crawl cannot reach create.
RPC getSignaturesForAddress window [create,t0] + Enhanced parse-by-sig is the
recovery path (documented residual for live: live T0≈now so Enhanced suffices).
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
from ingestion.helius_enhanced import HeliusEnhanced, fetch_create_to_t0_txs, fetch_pre_t0_enhanced_txs
from ingestion.helius_rpc import HeliusRpc
from ingestion.sol_usd_oracle import apply_dune_helius_usd_scale_enabled, resolve_sol_usd
from ingestion.t0_capture import find_t0_c1_c6_train_aligned, find_t0_dune_q3
from paper_live.creator_priors import load_creator_prior_index
from paper_live.helius_enrich import buy_vol_60s_from_trades, parse_helius_enhanced_txs
from paper_live.q5a_agg import aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, fill_meta_from_dune_store_exact, q5b_from_create

OUT_DIR = ROOT / "cycle0" / "artifacts"
MODEL_PATH = ROOT / "data" / "paper_live" / "models" / "q5b_last.joblib"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
SAMPLE_PATH = OUT_DIR / "sample_mints.csv"
BEFORE_CSV = OUT_DIR / "helius_historical_replay_robust.csv"


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
            for attempt in range(4):
                helius._throttle()  # noqa: SLF001
                resp = client.post(url, params={"api-key": key}, json={"transactions": chunk})
                helius.log.n_calls += 1
                helius.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    time.sleep(1.0 * (attempt + 1))
                    continue
                resp.raise_for_status()
                out.extend(resp.json())
                break
            else:
                raise RuntimeError("parse 429 exhausted")
    return out


def _rpc_window_txs(
    mint: str,
    *,
    t0: datetime,
    create_ts: datetime,
    helius: HeliusEnhanced,
    rpc: HeliusRpc,
    max_pages: int = 40,
) -> tuple[list[dict], str]:
    hi = int(t0.timestamp())
    lo = int(_aware(create_ts).timestamp()) - 5
    sigs, reason = rpc.collect_signatures_in_window(
        mint, max_block_time=hi, min_block_time=lo, max_pages=max_pages, page_limit=1000
    )
    if not sigs:
        return [], f"rpc_empty:{reason}"
    sig_list = [str(s["signature"]) for s in sigs if s.get("signature")]
    txs = _parse_by_sigs(helius, sig_list)
    return txs, f"rpc_window n_sigs={len(sig_list)} pages_reason={reason}"


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


def main() -> int:
    load_dotenv()
    assert apply_dune_helius_usd_scale_enabled() is False
    print("scale_off OK", flush=True)

    sample = pd.read_csv(SAMPLE_PATH)
    highs = sample[sample["band"].astype(str).str.contains("high")].copy()
    highs["t0_dt"] = highs["t0_ts"].map(_parse_t0)
    picks = highs.sort_values("t0_dt", ascending=False).head(12)
    print(f"n_picks={len(picks)}", flush=True)

    # lean train store load
    need = list(
        set(FEATURE_SETS["+q5b"])
        | {"mint", "create_ts", "creator_pubkey", "buy_vol_usd_60s", "buy_count_total", "mc_usd_t0", "age_s"}
    )
    fs = pd.read_csv(FS_PATH, usecols=lambda c: c in need)
    fs_by = {r.mint: r for r in fs.itertuples(index=False)}
    _bundle = joblib.load(MODEL_PATH)
    model = _bundle["pipeline"] if isinstance(_bundle, dict) else _bundle
    cols = list(_bundle.get("feature_names") or FEATURE_SETS["+q5b"]) if isinstance(_bundle, dict) else list(FEATURE_SETS["+q5b"])
    prior_idx = load_creator_prior_index()
    print(f"priors source={prior_idx.source} n_rows={prior_idx.n_rows}", flush=True)

    before = {}
    if BEFORE_CSV.exists():
        bdf = pd.read_csv(BEFORE_CSV)
        for r in bdf.itertuples(index=False):
            before[str(r.mint)] = float(r.live_rebuild_score)

    results = []
    with HeliusEnhanced(max_calls=1500, max_retries_429=6) as helius, HeliusRpc() as rpc:
        for i, row in enumerate(picks.itertuples(index=False), 1):
            mint = str(row.mint)
            t0 = _parse_t0(row.t0_ts)
            oos = float(row.score)
            print(f"[{i}/{len(picks)}] {mint[:16]}… oos={oos:.4f}", flush=True)
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
            bc = str(bonding_curve_pda(mint))
            age_s = float(getattr(tr, "age_s", 0) or 0)

            quote = resolve_sol_usd(None, allow_network=True, as_of=t0)
            sol_px, sol_src = float(quote.price), quote.source
            gaps: list[str] = [f"sol={sol_px:.4f}/{sol_src}"]

            # Historical snipers (age≈0): skip Enhanced mint crawl (post-T0 spam);
            # RPC signature window [create,t0] + parse. Live path still uses
            # fetch_pre_t0_enhanced_txs (T0≈now). Also pull BC Enhanced (cheap).
            # SolDatos canonical: BC Enhanced + RPC window on BC then mint
            txs, egaps = fetch_create_to_t0_txs(
                helius,
                mint,
                t0=t0,
                create_ts=create_ts,
                bonding_curve=bc,
                rpc=rpc,
                max_pages_enhanced=80,
                max_pages_rpc=80,
            )
            gaps.extend(egaps)
            fetch_mode = "enhanced_pre_t0"
            if any("rpc_" in g and "window" in g for g in egaps):
                fetch_mode = "enhanced+rpc_sig_window"
            print(f"  le_t0={len(txs)} age={age_s:.0f} mode={fetch_mode}", flush=True)

            trades = parse_helius_enhanced_txs(
                txs, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
            )
            mc0 = float(getattr(tr, "mc_usd_t0", 12000) or 12000)
            cap = find_t0_c1_c6_train_aligned(
                trades,
                sighting_t0=t0,
                sighting_mc=mc0,
                sol_usd=sol_px,
                sol_usd_source=sol_src,
                create_ts=create_ts,
                complete_false=True,
            )
            trades_use = [x for x in trades if x.ts <= t0]
            create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
            priors = (
                prior_idx.priors_for(creator, this_mint=mint, as_of=create_ts, window_days=30)
                if creator and prior_idx.n_rows
                else []
            )
            q5b = q5b_from_create(create, t0, prior_creates=priors)
            q5b = fill_meta_from_dune_store_exact(q5b, prior_idx.exact_meta_for_mint(mint))
            q5a = aggregate_q5a_for_mint(trades_use, t0)
            buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
            feats = {**{c: q5b.get(c) for c in q5b}, **q5a, "buy_vol_usd_60s": float(buy60)}
            proba = float(model.predict_proba(_vec(feats, cols))[0, 1])
            train_feats = {c: getattr(tr, c, None) for c in cols}
            train_rescore = float(model.predict_proba(_vec(train_feats, cols))[0, 1])

            rec = {
                "mint": mint,
                "band": row.band,
                "t0_ts": row.t0_ts,
                "oos_score": oos,
                "train_store_rescore": train_rescore,
                "live_rebuild_score": proba,
                "before_robust_score": before.get(mint),
                "delta_oos_minus_live": oos - proba,
                "buy_vol_train": float(getattr(tr, "buy_vol_usd_60s", 0) or 0),
                "buy_vol_live": float(buy60),
                "buy_n_live": int(buy_n),
                "n_trades_pre_t0": len(trades_use),
                "n_txs_le_t0": len(txs),
                "sol_usd": sol_px,
                "sol_usd_source": sol_src,
                "fetch_mode": fetch_mode,
                "t0_refine_detail": cap.detail,
                "t0_refined": bool(cap.refined),
                "capture_quality": cap.capture_quality,
                "prior_source": prior_idx.source,
                "n_priors": len(priors),
                "gaps": gaps[:10],
                "helius_calls": helius.n_calls,
            }
            results.append(rec)
            print(
                f"  live={proba:.4f} before={before.get(mint)} buy60={buy60:.0f}/"
                f"{rec['buy_vol_train']:.0f} trades={len(trades_use)} mode={fetch_mode}",
                flush=True,
            )

    df = pd.DataFrame(results)
    out_csv = OUT_DIR / "helius_parity_replay_ge10_20261001.csv"
    out_json = OUT_DIR / "helius_parity_replay_ge10_20261001.json"
    df.to_csv(out_csv, index=False)
    out_json.write_text(json.dumps(results, indent=2, default=str))
    ok = df.dropna(subset=["live_rebuild_score"]) if "live_rebuild_score" in df else df
    summary = {
        "n": int(len(ok)),
        "pct_ge_0.99": float((ok["live_rebuild_score"] >= 0.99).mean()) if len(ok) else None,
        "pct_ge_0.89": float((ok["live_rebuild_score"] >= 0.89).mean()) if len(ok) else None,
        "median_live": float(ok["live_rebuild_score"].median()) if len(ok) else None,
        "mean_live": float(ok["live_rebuild_score"].mean()) if len(ok) else None,
        "before_median_on_overlap": float(
            ok["before_robust_score"].dropna().median()
        )
        if "before_robust_score" in ok and ok["before_robust_score"].notna().any()
        else None,
        "scale_enabled": False,
        "csv": str(out_csv),
    }
    (OUT_DIR / "helius_parity_replay_ge10_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
