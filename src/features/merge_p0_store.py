"""Merge capture P0-min + replay pre-T0 into feature store (no sol_usd_t0 / no fake age_s)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from features.whitelist import FEATURE_SET_VERSION, P0_FEATURE_NAMES
from labeling.horizons import LABEL_COLUMNS
from verification.joins_v2 import assert_all_feature_ts_leq_t0
from verification.leakage_v3 import assert_feature_label_column_disjoint, fail_if_label_like_in_features

MC_LO = 8000.0
MC_HI = 20000.0


def _flow_cols() -> list[str]:
    out: list[str] = []
    for w in ("60s", "5m"):
        for stem in (
            "buy_count",
            "sell_count",
            "buy_vol_sol",
            "sell_vol_sol",
            "unique_buyers",
            "unique_sellers",
            "buy_sell_ratio_vol",
            "net_flow_sol",
        ):
            out.append(f"{stem}_{w}")
    return out


TRAIN_FROM_PRE = _flow_cols() + [
    "trade_count_total",
    "unique_traders_total",
    "buys_per_min",
    "time_since_first_trade_s",
    "mint_authority_none",
    "freeze_authority_none",
]
CAPTURE = ["mc_usd_t0", "price_usd_t0", "mc_band_pos"]
TRAIN_COLUMNS = CAPTURE + TRAIN_FROM_PRE


def merge_default_samples(out_dir: Path | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    out_dir = out_dir or (root / "data" / "samples")
    base = json.loads((out_dir / "features_p0_min_pumpapi_cohort.json").read_text())
    pre = json.loads((out_dir / "features_replay_pre_t0_cohort200.json").read_text())
    assert set(TRAIN_FROM_PRE) <= P0_FEATURE_NAMES
    fail_if_label_like_in_features(TRAIN_COLUMNS)
    assert_feature_label_column_disjoint(TRAIN_COLUMNS, LABEL_COLUMNS)

    base_by = {r["capture_id"]: r for r in base["rows"]}
    pre_by = {r["capture_id"]: r for r in pre["rows"]}
    rows: list[dict[str, Any]] = []
    for cid, b in base_by.items():
        p = pre_by[cid]
        t0 = b["t0"]
        assert_all_feature_ts_leq_t0([{"feature_ts": t0} for _ in TRAIN_COLUMNS], t0=t0)
        row: dict[str, Any] = {
            "capture_id": cid,
            "mint": b["mint"],
            "t0": t0,
            "feature_set_version": FEATURE_SET_VERSION,
            "split_role": b["split_role"],
            "mc_usd_t0": b["mc_usd_t0"],
            "price_usd_t0": b["price_usd_t0"],
            "mc_band_pos": b["mc_band_pos"],
        }
        for c in TRAIN_FROM_PRE:
            row[c] = p.get(c)
        row["age_s_replay"] = p.get("age_s_replay")  # proxy only
        row["feature_ts"] = {c: t0 for c in TRAIN_COLUMNS}
        rows.append(row)
    path = out_dir / "features_p0_store_cohort200.json"
    path.write_text(
        json.dumps(
            {
                "n": len(rows),
                "train_columns": TRAIN_COLUMNS,
                "feature_set_version": FEATURE_SET_VERSION,
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    return {"n": len(rows), "n_train_columns": len(TRAIN_COLUMNS), "path": str(path)}
