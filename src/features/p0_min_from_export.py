"""P0 mínimo desde export Capture (sin raw replay).

Solo columnas ≤ T0 disponibles en positives/negatives_pumpapi_*.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from features.whitelist import FEATURE_SET_VERSION, P0_FEATURE_NAMES
from labeling.horizons import LABEL_COLUMNS
from verification.joins_v2 import assert_all_feature_ts_leq_t0
from verification.leakage_v3 import assert_feature_label_column_disjoint, fail_if_label_like_in_features

MC_LO = 8000.0
MC_HI = 20000.0
FILLABLE = frozenset({"mc_usd_t0", "price_usd_t0", "mc_band_pos"})
# sol_usd_t0 excluded until Pyth as-of T0 (SolQA 2026-09-29)
DROPPED_UNTIL_ASOF = frozenset({"sol_usd_t0"})


def materialize_row(r: Mapping[str, Any], *, split_role: str) -> dict[str, Any]:
    t0 = r["t0"]
    mc0 = float(r["mc0"])
    p0 = float(r["p0"])
    value_cols = sorted(FILLABLE)
    assert_all_feature_ts_leq_t0([{"feature_ts": t0} for _ in value_cols], t0=t0)
    return {
        "capture_id": r["capture_id"],
        "mint": r["mint"],
        "t0": t0,
        "feature_set_version": FEATURE_SET_VERSION,
        "mc_usd_t0": mc0,
        "price_usd_t0": p0,
        "mc_band_pos": (mc0 - MC_LO) / (MC_HI - MC_LO),
        "feature_ts": {c: t0 for c in value_cols},
        "split_role": split_role,
        "feature_source": "export_capture_fields_only",
    }


def materialize_cohort(
    positives: Sequence[Mapping[str, Any]],
    negatives: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    cols = sorted(FILLABLE)
    fail_if_label_like_in_features(cols)
    assert_feature_label_column_disjoint(cols, LABEL_COLUMNS)
    assert set(cols) <= P0_FEATURE_NAMES
    out = [materialize_row(r, split_role="positive") for r in positives]
    out += [materialize_row(r, split_role="negative_provisional") for r in negatives]
    return out


def write_default_samples(out_dir: Path | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    out_dir = out_dir or (root / "data" / "samples")
    pos = json.loads((out_dir / "positives_pumpapi_replay_t0.json").read_text())["rows"]
    neg = json.loads((out_dir / "negatives_pumpapi_replay_provisional.json").read_text())["rows"]
    rows = materialize_cohort(pos, neg)
    path = out_dir / "features_p0_min_pumpapi_cohort.json"
    path.write_text(
        json.dumps(
            {
                "n": len(rows),
                "feature_set_version": FEATURE_SET_VERSION,
                "p0_filled": sorted(FILLABLE),
                "p0_pending": sorted(P0_FEATURE_NAMES - FILLABLE),
                "rows": rows,
            },
            indent=2,
        )
        + "\n"
    )
    return {"n": len(rows), "path": str(path)}
