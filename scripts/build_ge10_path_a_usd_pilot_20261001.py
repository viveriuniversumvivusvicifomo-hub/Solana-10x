#!/usr/bin/env python3
"""SolDatos: ge10 Path A USD pilot overlay for SolModelos (2026-10-01).

Offline only — reads recovery_on Path A features + Dune store; no Helius/Dune API.
Does NOT touch paper_live or joblib. Scale 6.6× OFF.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import FEATURE_SETS

STORE = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
PA = ROOT / "data/samples/helius_parity_features_ge10_recovery_on_20261001.csv"
OUT = ROOT / "data/samples/features_ge10_path_a_usd_pilot_20261001.csv"
OUT_META = ROOT / "data/samples/features_ge10_path_a_usd_pilot_20261001_meta.json"

USD_DIRECT = [
    "buy_vol_usd_60s",
    "buy_vol_first_10s",
    "buy_vol_first_5s",
    "buy_vol_usd_15m",
    "buy_vol_usd_30s",
    "buy_vol_usd_total",
    "first10_buy_vol_usd",
    "first5_buy_vol_usd",
    "first_buy_usd",
    "max_buy_usd",
    "sell_vol_usd_15m",
    "sell_vol_usd_30s",
    "sell_vol_usd_total",
]
SHARE = [
    "first5_buy_vol_share",
    "max_buy_share",
    "sniper_vol_share_5s",
    "top10_buyer_vol_share",
    "top1_buyer_vol_share",
    "top5_buyer_vol_share",
]
SOL_NATIVE = ["max_buy_sol", "net_sol_curve", "net_sol_total", "progress_curve_proxy"]


def main() -> int:
    q5b = list(FEATURE_SETS["+q5b"])
    pa = pd.read_csv(PA)
    store = pd.read_csv(STORE)
    mints = list(pa["mint"])
    base = store[store["mint"].isin(mints)].copy()
    if len(base) != len(mints):
        raise SystemExit(f"store overlap {len(base)} != path_a {len(mints)}")
    base = base.set_index("mint")
    pa_i = pa.set_index("mint")

    changed: list[str] = []
    for c in USD_DIRECT:
        if c in pa_i.columns and c in base.columns:
            base[c] = pa_i[c]
            changed.append(c)
    for c in SHARE + SOL_NATIVE:
        if c in pa_i.columns and c in base.columns:
            mask = pa_i[c].notna()
            base.loc[mask, c] = pa_i.loc[mask, c]
            if c not in changed:
                changed.append(c)

    base = base.reset_index()
    base["path_a_usd_overlay"] = 1
    base["path_a_source"] = "helius_parity_features_ge10_recovery_on_20261001"
    fsv = base["feature_set_version"].astype(str) if "feature_set_version" in base.columns else "features.dune.p0.q5.expand.v2"
    base["feature_set_version"] = fsv + "+path_a_usd_pilot"

    store_cols = list(store.columns)
    extra = [c for c in base.columns if c not in store_cols]
    base[store_cols + extra].to_csv(OUT, index=False)

    meta = {
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "owner": "SolDatos",
        "role": "ge10 Path A USD pilot template for SolModelos rebase validation",
        "n_mints": int(len(base)),
        "path_a_policy": "amount_usd = sol_amt × pyth_asof; scale 6.6× OFF",
        "source_path_a_features": str(PA.relative_to(ROOT)),
        "source_store": str(STORE.relative_to(ROOT)),
        "out_csv": str(OUT.relative_to(ROOT)),
        "usd_direct_cols_overlaid": [c for c in USD_DIRECT if c in changed],
        "share_sol_cols_overlaid": [c for c in (SHARE + SOL_NATIVE) if c in changed],
        "q5b_n_cols": len(q5b),
        "q5b_cols": q5b,
        "paper_live_touched": False,
        "joblib_touched": False,
        "scale_6_6x": False,
        "full_train_82k": "NOT built — Helius required for true Path A; see plan MD",
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"Wrote {OUT} n={len(base)}")
    print(f"Wrote {OUT_META}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
