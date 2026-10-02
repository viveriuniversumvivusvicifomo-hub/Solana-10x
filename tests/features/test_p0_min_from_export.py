from __future__ import annotations

import json
from pathlib import Path

from features.p0_min_from_export import FILLABLE, materialize_cohort
from verification.joins_v2 import assert_all_feature_ts_leq_t0
from verification.leakage_v3 import fail_if_label_like_in_features


def test_materialize_cohort_gates():
    root = Path("/workspace/solana-10x/data/samples")
    pos = json.loads((root / "positives_pumpapi_replay_t0.json").read_text())["rows"][:2]
    neg = json.loads((root / "negatives_pumpapi_replay_provisional.json").read_text())["rows"][:2]
    rows = materialize_cohort(pos, neg)
    assert len(rows) == 4
    cols = sorted(FILLABLE)
    fail_if_label_like_in_features(cols)
    for r in rows:
        assert_all_feature_ts_leq_t0([{"feature_ts": r["feature_ts"][c]} for c in cols], t0=r["t0"])
        assert "max_mc_after_t0_in_sample" not in r
