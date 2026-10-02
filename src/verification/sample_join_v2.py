"""Look-ahead check sobre el primer join features↔capturas (muestra Bitquery)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from verification.errors import LookAheadError, VerificationError
from verification.joins_v2 import assert_all_feature_ts_leq_t0, assert_feature_rows_have_ts

_REPO = Path(__file__).resolve().parents[2]
_DEFAULT_SAMPLE = _REPO / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json"

# Columnas que implicarían outcome post-T0 si aparecieran en un join prematuro
_FORBIDDEN_IN_CANDIDATE_JOIN: frozenset[str] = frozenset(
    {
        "hit_10x",
        "hit_10x_1h",
        "hit_10x_6h",
        "hit_10x_24h",
        "hit_10x_7d",
        "hit_10x_30d",
        "max_mc_24h",
        "max_mc_30d",
        "max_multiple_24h",
        "max_multiple_30d",
        "time_to_10x",
        "migrated",
        "prices_after_t0",
    }
)


def audit_bitquery_candidate_sample(
    sample_path: Path | None = None,
) -> dict[str, Any]:
    """Audita el snapshot Bitquery actual (candidatos MC, aún sin CaptureEvent).

    - n y banda MC
    - ausencia de columnas label / post-T0
    - si aparecen feature rows con t0 → aplica V2
    """
    path = sample_path or _DEFAULT_SAMPLE
    if not path.is_file():
        raise VerificationError("V2", f"sample ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = list(payload.get("rows") or [])
    meta = payload.get("meta") or {}
    n = len(rows)
    if n == 0:
        raise VerificationError("V2", "sample vacío")

    keys: set[str] = set()
    for r in rows:
        keys.update(r.keys())
    leak = sorted(keys & _FORBIDDEN_IN_CANDIDATE_JOIN)
    if leak:
        raise LookAheadError(f"sample candidatos con columnas post-T0/label: {leak}")

    # MC band check
    bad_mc = [r.get("mint") for r in rows if not (8000.0 <= float(r.get("mc_usd", -1)) <= 20000.0)]
    if bad_mc:
        raise VerificationError("V1", f"mc_usd fuera de banda en mints: {bad_mc[:5]}")

    has_t0 = any("t0" in r or "t0_iso" in r for r in rows)
    join_status = "skipped_no_t0"
    if has_t0:
        # enriched path: exigir feature_ts ≤ t0
        feature_rows = []
        for r in rows:
            t0 = r.get("t0_iso") or r.get("t0")
            feats = r.get("features") or r.get("feature_rows")
            if feats:
                assert_feature_rows_have_ts(feats)
                assert_all_feature_ts_leq_t0(feats, t0=t0)
                feature_rows.extend(feats)
        join_status = "checked" if feature_rows else "t0_present_no_features"

    return {
        "sample_path": str(path),
        "n": n,
        "meta_n": meta.get("n"),
        "columns": sorted(keys),
        "has_capture_t0": has_t0,
        "join_lookahead": join_status,
        "label_columns_present": False,
        "mc_band_ok": True,
        "ok": True,
    }


def assert_first_join_no_lookahead(
    feature_rows: Sequence[Mapping[str, Any]],
    *,
    t0: datetime | str,
    slot0: int | None = None,
) -> None:
    """Gate explícita para el primer join features↔captura."""
    assert_feature_rows_have_ts(feature_rows)
    assert_all_feature_ts_leq_t0(feature_rows, t0=t0, slot0=slot0)


_DEFAULT_ENRICHED = _REPO / "data" / "samples" / "bitquery_enriched_capture_sample.json"


_DEFAULT_ENRICHED = _REPO / "data" / "samples" / "bitquery_enriched_capture_sample.json"


def audit_enriched_capture_sample(sample_path: Path | None = None) -> dict[str, Any]:
    """Audita enriched con t0/p0/prices_after_t0 (V3 window + V2 features si existen)."""
    from verification.leakage_v3 import assert_label_window_strictly_after_t0

    path = sample_path or _DEFAULT_ENRICHED
    if not path.is_file():
        raise VerificationError("V2", f"enriched ausente: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = list(payload.get("rows") or [])
    if not rows:
        raise VerificationError("V2", "enriched vacío")

    label_cols_forbidden = _FORBIDDEN_IN_CANDIDATE_JOIN - {"prices_after_t0"}
    for i, r in enumerate(rows):
        if "t0" not in r or "p0" not in r:
            raise LookAheadError(f"enriched rows[{i}] sin t0/p0")
        prices = r.get("prices_after_t0") or []
        if prices:
            assert_label_window_strictly_after_t0([p[0] for p in prices], t0=r["t0"])
        bad = sorted(set(r.keys()) & label_cols_forbidden)
        if bad:
            raise LookAheadError(f"enriched rows[{i}] con label cols: {bad}")
        feats = r.get("features") or r.get("feature_rows")
        if feats:
            assert_feature_rows_have_ts(feats)
            assert_all_feature_ts_leq_t0(feats, t0=r["t0"])

    return {
        "sample_path": str(path),
        "n": len(rows),
        "has_capture_t0": True,
        "join_lookahead": "checked_prices_window_and_optional_features",
        "ok": True,
    }
