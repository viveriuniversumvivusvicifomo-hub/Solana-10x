#!/usr/bin/env python3
"""Build parity OOS≥0.99 n=200 sample (2026-10-01). SolDatos sample step only."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OOS = ROOT / "data" / "samples" / "wf_post_q5_oos_predictions.csv"
GE12 = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_20261001.csv"
FS = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
OUT = ROOT / "data" / "samples" / "parity_oos99_n200_sample_20261001.csv"
OUT_META = ROOT / "data" / "samples" / "parity_oos99_n200_sample_20261001_meta.json"
SEED = 20261001
N = 200


def main() -> int:
    oos = pd.read_csv(OOS)
    q5b = oos[(oos["set"] == "+q5b") & (oos["score"] >= 0.99)].copy()
    # one row per mint: max score; keep that row's t0_ts, y
    idx = q5b.groupby("mint", sort=False)["score"].idxmax()
    pool = q5b.loc[idx].rename(columns={"score": "oos_score"}).reset_index(drop=True)
    pool["band"] = "high_ge0.99"

    ge = pd.read_csv(GE12)
    ge_mints = set(ge["mint"].astype(str))
    # prefer ge12 still ≥0.99 (all should be)
    ge_keep = pool[pool["mint"].isin(ge_mints)].copy()
    ge_keep["in_ge12"] = True

    fs_mints = set(pd.read_csv(FS, usecols=["mint"])["mint"].astype(str))
    pool["in_feature_store"] = pool["mint"].isin(fs_mints)
    pool["in_ge12"] = pool["mint"].isin(ge_mints)

    selected_mints: list[str] = []
    # 1) force-include ge12
    for m in ge["mint"].astype(str).tolist():
        if m in set(pool["mint"]) and m not in selected_mints:
            selected_mints.append(m)

    remaining = pool[~pool["mint"].isin(selected_mints)].copy()
    need = N - len(selected_mints)
    # Prefer feature-store overlap
    in_fs = remaining[remaining["in_feature_store"]].copy()
    out_fs = remaining[~remaining["in_feature_store"]].copy()
    rng = np.random.default_rng(SEED)

    def _sample(df: pd.DataFrame, k: int) -> list[str]:
        if k <= 0 or df.empty:
            return []
        k = min(k, len(df))
        # deterministic: shuffle with seed then take first k (stable by mint sort first)
        df = df.sort_values(["oos_score", "mint"], ascending=[False, True]).reset_index(drop=True)
        # use rng choice without replacement on positions
        pos = rng.choice(len(df), size=k, replace=False)
        pos = np.sort(pos)  # keep order stable in output relative to choice set
        # but for reproducibility of WHICH mints: use unsorted choice order from rng
        pos2 = rng.choice(len(df), size=k, replace=False) if False else pos
        # Re-draw with fresh rng state after sort-only — actually we already consumed rng.
        # Better: reseed and choose from mint list.
        return []  # placeholder — see below

    # Clean approach: reseed, choose from in_fs then out_fs
    rng = np.random.default_rng(SEED)
    picks: list[str] = list(selected_mints)
    for src in (in_fs, out_fs):
        left = N - len(picks)
        if left <= 0:
            break
        cands = src["mint"].astype(str).tolist()
        if not cands:
            continue
        k = min(left, len(cands))
        chosen = rng.choice(cands, size=k, replace=False).tolist()
        picks.extend(chosen)

    assert len(picks) == N, f"got {len(picks)} != {N}"
    assert len(set(picks)) == N

    sample = pool[pool["mint"].isin(picks)].copy()
    # preserve ge12-first then rng order
    order = {m: i for i, m in enumerate(picks)}
    sample["_ord"] = sample["mint"].map(order)
    sample = sample.sort_values("_ord").drop(columns=["_ord"]).reset_index(drop=True)
    sample = sample[
        ["mint", "t0_ts", "oos_score", "y", "band", "in_feature_store", "in_ge12"]
    ]
    # join train_buy_count for convenience
    fs = pd.read_csv(FS, usecols=lambda c: c in {"mint", "buy_count_total", "create_ts", "creator_pubkey"})
    fs = fs.drop_duplicates("mint", keep="first")
    sample = sample.merge(
        fs.rename(columns={"buy_count_total": "train_buy_count"}),
        on="mint",
        how="left",
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    sample.to_csv(OUT, index=False)

    n_fs = int(sample["in_feature_store"].sum())
    n_ge = int(sample["in_ge12"].sum())
    n_missing_fs = int((~sample["in_feature_store"]).sum())
    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "seed": SEED,
        "n": int(len(sample)),
        "source_oos": str(OOS.relative_to(ROOT)),
        "filter": "set=='+q5b' AND score>=0.99; one row/mint max score",
        "ge12_source": str(GE12.relative_to(ROOT)),
        "n_ge12_included": n_ge,
        "n_in_feature_store": n_fs,
        "n_missing_feature_store": n_missing_fs,
        "pool_unique_mints_oos99": int(len(pool)),
        "band": "high_ge0.99",
        "out_csv": str(OUT.relative_to(ROOT)),
        "oos_score_min": float(sample["oos_score"].min()),
        "oos_score_max": float(sample["oos_score"].max()),
        "oos_score_median": float(sample["oos_score"].median()),
        "y_pos": int((sample["y"] == 1).sum()) if "y" in sample else None,
        "y_neg": int((sample["y"] == 0).sum()) if "y" in sample else None,
        "scale_6_6x": False,
        "note": "Prefer ge12 then feature-store overlap; fill from +q5b OOS≥0.99 with seed.",
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
