#!/usr/bin/env python3
"""Sample firmas: Dune amount_usd vs live sol_amt × pyth_asof (SolDatos Path A).

Compares train-store max_buy / buy60 implied USD/SOL vs oracle for ge10 parity
mints. Writes cycle0/artifacts/dune_helius_usd_firmas_compare_20261001.csv

Does NOT enable blind 6.6×. Path A = amount_usd := sol_amt * pyth_asof.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ingestion.sol_usd_oracle import (
    USD_RECALIB_PLAN,
    amount_usd_dune_compatible,
    require_pyth_asof,
    resolve_sol_usd_for_scoring,
)

ROOT = Path(__file__).resolve().parents[1]
FS = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
PARITY = ROOT / "cycle0/artifacts/helius_parity_replay_ge10_20261001.csv"
OUT = ROOT / "cycle0/artifacts/dune_helius_usd_firmas_compare_20261001.csv"


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "").strip()
    dt = pd.to_datetime(s, utc=True)
    return dt.to_pydatetime()


def main() -> int:
    print("USD_RECALIB_PLAN", USD_RECALIB_PLAN["chosen"])
    parity = pd.read_csv(PARITY)
    mints = parity["mint"].tolist()
    cols = [
        "mint",
        "t0_ts",
        "buy_vol_usd_60s",
        "max_buy_usd",
        "max_buy_sol",
        "net_sol_curve",
        "buy_count_total",
    ]
    use = [c for c in cols if c in pd.read_csv(FS, nrows=0).columns]
    chunks = []
    for chunk in pd.read_csv(FS, usecols=use, chunksize=50_000):
        sub = chunk[chunk["mint"].isin(mints)]
        if len(sub):
            chunks.append(sub)
    train = pd.concat(chunks).drop_duplicates("mint") if chunks else pd.DataFrame()

    rows = []
    for r in parity.itertuples(index=False):
        mint = str(r.mint)
        t0 = _parse_t0(r.t0_ts)
        tr = train[train["mint"] == mint]
        if tr.empty:
            continue
        tr = tr.iloc[0]
        max_buy_usd = float(tr["max_buy_usd"] or 0)
        max_buy_sol = float(tr["max_buy_sol"] or 0)
        dune_implied = (max_buy_usd / max_buy_sol) if max_buy_sol > 0 else None
        q, why = resolve_sol_usd_for_scoring(t0, require_pyth=True)
        if q is None:
            # diagnostic fallback for CSV only (scoring still refuses)
            q_fb, why_fb = resolve_sol_usd_for_scoring(t0, require_pyth=False)
            px = float(q_fb.price) if q_fb else None
            src = f"FALLBACK:{why_fb}" if q_fb else why
        else:
            px = float(q.price)
            src = q.source
        live_usd = (
            amount_usd_dune_compatible(max_buy_sol, px) if px and max_buy_sol else None
        )
        ratio = (live_usd / max_buy_usd) if live_usd and max_buy_usd else None
        rows.append(
            {
                "mint": mint,
                "t0_ts": r.t0_ts,
                "dune_max_buy_usd": max_buy_usd,
                "dune_max_buy_sol": max_buy_sol,
                "dune_implied_usd_per_sol": dune_implied,
                "oracle_px": px,
                "oracle_source": src,
                "live_amount_usd_sol_x_oracle": live_usd,
                "live_over_dune_usd": ratio,
                "buy_vol_train": float(tr["buy_vol_usd_60s"] or 0),
                "buy_vol_live_parity": float(getattr(r, "buy_vol_live", 0) or 0),
                "n_trades_pre_t0_parity": int(getattr(r, "n_trades_pre_t0", 0) or 0),
                "plan": USD_RECALIB_PLAN["chosen"],
            }
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["mint"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote n={len(rows)} → {OUT}")
    if rows:
        ratios = [r["live_over_dune_usd"] for r in rows if r["live_over_dune_usd"]]
        if ratios:
            import statistics as stats

            print(
                f"live/dune max_buy_usd ratio med={stats.median(ratios):.4f} "
                f"min={min(ratios):.4f} max={max(ratios):.4f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
