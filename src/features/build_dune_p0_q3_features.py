"""Build Dune P0 Q3-only feature store from primary_ready stratified sample.

Available-now features only (mc/price/project at T0). No flow, no holders, no Pyth.
Labels never enter the feature CSV. Streams Helius OFF. No paid APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

MC_LO = 8000.0
MC_HI = 20000.0
SEED = 42
TARGET_POS = 1000
TARGET_NEG = 1000
FEATURE_SET_VERSION = "features.dune.p0.q3.v1"
DEFINITION_VERSION = "dune_cohort_v1"

_LEAK_COL_RE = re.compile(r"(max_mc|hit_|label_|after_t0)", re.IGNORECASE)

SAMPLE_ID_COLS = [
    "mint",
    "t0_ts",
    "hit_200k",
    "mc_usd_t0",
    "price_usd_t0",
    "primary_ready",
    "project_at_t0",
    "tx_id_t0",
]

FEATURE_VALUE_COLS = [
    "mc_usd_t0",
    "price_usd_t0",
    "mc_band_pos",
    "log1p_mc_usd_t0",
    "is_pumpdotfun",
]

FEATURE_META_COLS = ["mint", "t0_ts", "feature_set_version"]

LABEL_COLS = ["mint", "hit_200k", "max_mc_after_t0", "label_primary_hint"]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parse_t0(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, errors="coerce")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _row_keys(frame: pd.DataFrame) -> set[tuple[str, str]]:
    return set(zip(frame["mint"].astype(str), frame["t0_ts"].astype(str)))


def load_cohort(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {
        "mint",
        "t0_ts",
        "hit_200k",
        "primary_ready",
        "mc_usd_t0",
        "price_usd_t0",
        "max_mc_after_t0",
        "label_primary_hint",
        "project_at_t0",
    }
    missing = required - set(df.columns)
    if missing:
        raise SystemExit(f"cohort missing columns: {sorted(missing)}")
    return df


def filter_primary_ready_with_mc(df: pd.DataFrame) -> pd.DataFrame:
    pr = df["primary_ready"]
    if pr.dtype == object:
        pr_ok = pr.astype(str).str.lower().isin(["true", "1", "1.0"])
    else:
        pr_ok = pr.astype(bool)
    has_mc = df["mc_usd_t0"].notna() & df["price_usd_t0"].notna()
    out = df.loc[pr_ok & has_mc].copy()
    out["hit_200k"] = out["hit_200k"].astype(int)
    out["t0_dt"] = _parse_t0(out["t0_ts"])
    out["t0_week"] = out["t0_dt"].dt.tz_convert("UTC").dt.strftime("%Y-W%W")
    return out.reset_index(drop=True)


def _proportional_week_counts(weeks: pd.Series, n: int) -> pd.Series:
    """Largest-remainder allocation of n slots across week value_counts."""
    if n <= 0 or weeks.empty:
        return weeks.iloc[0:0].astype(int)
    raw = (weeks / weeks.sum() * n).astype(float)
    base = raw.astype(int)
    rem = n - int(base.sum())
    frac = (raw - base).sort_values(ascending=False)
    for w in frac.index[:rem]:
        base[w] += 1
    return base.astype(int)


def _sample_by_week_targets(
    frame: pd.DataFrame,
    week_target: pd.Series,
    *,
    rng: int,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for w, k in week_target.items():
        k = int(k)
        if k <= 0:
            continue
        sub = frame.loc[frame["t0_week"] == w]
        if sub.empty:
            continue
        parts.append(sub.sample(n=min(k, len(sub)), random_state=rng))
    if not parts:
        return frame.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True)


def _top_up(frame: pd.DataFrame, taken: pd.DataFrame, n: int, *, rng: int) -> pd.DataFrame:
    if len(taken) >= n:
        return taken.iloc[:n].reset_index(drop=True)
    used = _row_keys(taken)
    leftover = frame.loc[
        ~frame.apply(lambda r: (str(r["mint"]), str(r["t0_ts"])) in used, axis=1)
    ]
    need = n - len(taken)
    if need > 0 and not leftover.empty:
        taken = pd.concat(
            [taken, leftover.sample(n=min(need, len(leftover)), random_state=rng)],
            ignore_index=True,
        )
    return taken.reset_index(drop=True)


def stratified_sample(
    pool: pd.DataFrame,
    *,
    n_pos: int = TARGET_POS,
    n_neg: int = TARGET_NEG,
    seed: int = SEED,
) -> pd.DataFrame:
    """~n_pos positives + ~n_neg negatives, stratified by t0_week when possible.

    If fewer positives than n_pos: take all primary_ready+mc positives and match
    negatives 1:1 (still preferring week match).
    """
    pos = pool.loc[pool["hit_200k"] == 1].copy()
    neg = pool.loc[pool["hit_200k"] == 0].copy()
    rng = seed

    n_pos_take = min(n_pos, len(pos))
    # If short on positives, match negs 1:1 to pos count; else target n_neg.
    n_neg_take = min(len(neg), n_pos_take if n_pos_take < n_pos else n_neg)

    pos_weeks = pos["t0_week"].value_counts().sort_index()
    pos_s = _sample_by_week_targets(pos, _proportional_week_counts(pos_weeks, n_pos_take), rng=rng)
    pos_s = _top_up(pos, pos_s, n_pos_take, rng=rng)

    # Negatives: mirror positive week mix when possible
    if n_neg_take > 0 and not pos_s.empty:
        mirror = pos_s["t0_week"].value_counts().sort_index()
        neg_targets = _proportional_week_counts(mirror, n_neg_take)
        # Cap by available negs per week
        avail = neg["t0_week"].value_counts()
        capped = neg_targets.copy()
        for w in capped.index:
            capped[w] = min(int(capped[w]), int(avail.get(w, 0)))
        neg_s = _sample_by_week_targets(neg, capped, rng=rng)
        neg_s = _top_up(neg, neg_s, n_neg_take, rng=rng)
    else:
        neg_s = neg.iloc[0:0].copy()

    sample = pd.concat([pos_s, neg_s], ignore_index=True)
    return sample.sample(frac=1.0, random_state=rng).reset_index(drop=True)


def build_features(sample: pd.DataFrame) -> pd.DataFrame:
    mc = sample["mc_usd_t0"].astype(float)
    price = sample["price_usd_t0"].astype(float)
    proj = sample["project_at_t0"].astype(str).str.lower()
    return pd.DataFrame(
        {
            "mint": sample["mint"].astype(str),
            "t0_ts": sample["t0_ts"],
            "mc_usd_t0": mc,
            "price_usd_t0": price,
            "mc_band_pos": (mc - MC_LO) / (MC_HI - MC_LO),
            "log1p_mc_usd_t0": mc.map(lambda x: math.log1p(float(x))),
            "is_pumpdotfun": (proj == "pumpdotfun").astype(int),
            "feature_set_version": FEATURE_SET_VERSION,
        }
    )


def build_labels(sample: pd.DataFrame) -> pd.DataFrame:
    # label_primary_hint ≈ hit_200k for now; true hit_10x_30d needs 30d follow-up.
    hint = sample["label_primary_hint"]
    if hint.isna().any():
        hint = sample["hit_200k"]
    return pd.DataFrame(
        {
            "mint": sample["mint"].astype(str),
            "hit_200k": sample["hit_200k"].astype(int),
            "max_mc_after_t0": sample["max_mc_after_t0"].astype(float),
            "label_primary_hint": hint.fillna(sample["hit_200k"]).astype(int),
        }
    )


def build_sample_csv(sample: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in SAMPLE_ID_COLS if c in sample.columns]
    out = sample[cols].copy()
    out["hit_200k"] = out["hit_200k"].astype(int)
    out["primary_ready"] = True
    return out


def qa_features(
    features: pd.DataFrame,
    sample: pd.DataFrame,
    *,
    sample_path: Path,
    features_path: Path,
    labels_path: Path,
) -> dict[str, Any]:
    issues: list[str] = []
    cols = list(features.columns)
    leak_cols = [c for c in cols if _LEAK_COL_RE.search(c)]
    if leak_cols:
        issues.append(f"leakage columns in features: {leak_cols}")

    n_feat = len(features)
    n_sample = len(sample)
    if n_feat != n_sample:
        issues.append(f"n_features={n_feat} != n_sample={n_sample}")

    mc = features["mc_usd_t0"].astype(float)
    outside = int(((mc < MC_LO) | (mc > MC_HI)).sum())
    if outside:
        issues.append(f"mc_usd_t0 outside [{MC_LO},{MC_HI}]: {outside}")

    if set(features["mint"].astype(str)) != set(sample["mint"].astype(str)):
        issues.append("mint set mismatch features vs sample")

    for c in FEATURE_VALUE_COLS:
        if features[c].isna().any():
            issues.append(f"NaN in feature column {c}")

    return {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "ok": len(issues) == 0,
        "n_sample": n_sample,
        "n_features": n_feat,
        "n_pos": int((sample["hit_200k"] == 1).sum()),
        "n_neg": int((sample["hit_200k"] == 0).sum()),
        "feature_columns": cols,
        "feature_value_columns": FEATURE_VALUE_COLS,
        "leak_col_regex": _LEAK_COL_RE.pattern,
        "leak_cols_found": leak_cols,
        "mc_band_usd": [MC_LO, MC_HI],
        "mc_min": float(mc.min()) if len(mc) else None,
        "mc_max": float(mc.max()) if len(mc) else None,
        "mc_outside_band": outside,
        "is_pumpdotfun_rate": float(features["is_pumpdotfun"].mean()) if len(features) else None,
        "assertions": {
            "no_leak_columns": len(leak_cols) == 0,
            "mc_in_band": outside == 0,
            "n_rows_match_sample": n_feat == n_sample,
        },
        "paths": {
            "sample": str(sample_path),
            "features": str(features_path),
            "labels": str(labels_path),
        },
        "issues": issues,
        "feature_set_version": FEATURE_SET_VERSION,
        "definition_version": DEFINITION_VERSION,
        "streams_helius": "OFF",
        "caveats": [
            "P0 Q3-only: no flow windows until Dune Q4",
            "no holders / no Pyth sol_usd_t0",
            "PRIMARY still proxy via hit_200k / label_primary_hint",
            "true hit_10x_30d needs 30d post-T0 follow-up",
        ],
    }


def run(
    *,
    cohort_path: Path | None = None,
    out_dir: Path | None = None,
    n_pos: int = TARGET_POS,
    n_neg: int = TARGET_NEG,
    seed: int = SEED,
) -> dict[str, Any]:
    root = _repo_root()
    out_dir = out_dir or (root / "data" / "samples")
    cohort_path = cohort_path or (out_dir / "dune_cohort_v1_labels_with_t0_mc.csv")

    sample_path = out_dir / "dune_sample_primary_ready_v1.csv"
    features_path = out_dir / "features_dune_p0_q3_sample_v1.csv"
    features_meta_path = out_dir / "features_dune_p0_q3_sample_v1.json"
    labels_path = out_dir / "labels_dune_sample_v1.csv"
    qa_path = out_dir / "qa_features_dune_p0_q3_sample_v1.json"

    df = load_cohort(cohort_path)
    pool = filter_primary_ready_with_mc(df)
    sample = stratified_sample(pool, n_pos=n_pos, n_neg=n_neg, seed=seed)

    sample_csv = build_sample_csv(sample)
    features = build_features(sample)
    labels = build_labels(sample)

    sample_csv.to_csv(sample_path, index=False)
    features.to_csv(features_path, index=False)
    labels.to_csv(labels_path, index=False)

    week_hit = (
        sample.groupby(["t0_week", "hit_200k"]).size().unstack(fill_value=0)
        if "t0_week" in sample.columns
        else pd.DataFrame()
    )
    week_counts: dict[str, Any] = {}
    if not week_hit.empty:
        for hit_val in week_hit.columns:
            week_counts[str(int(hit_val))] = {
                str(w): int(week_hit.loc[w, hit_val]) for w in week_hit.index
            }

    def _rel(p: Path) -> str:
        try:
            return str(p.relative_to(root))
        except ValueError:
            return str(p)

    meta = {
        "feature_set_version": FEATURE_SET_VERSION,
        "definition_version": DEFINITION_VERSION,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "streams_helius": "OFF",
        "paid_apis": False,
        "source_cohort": _rel(cohort_path),
        "source_cohort_sha256": _sha256_file(cohort_path),
        "pool_primary_ready_with_mc": len(pool),
        "pool_pos": int((pool["hit_200k"] == 1).sum()),
        "pool_neg": int((pool["hit_200k"] == 0).sum()),
        "n_sample": len(sample),
        "n_pos": int((sample["hit_200k"] == 1).sum()),
        "n_neg": int((sample["hit_200k"] == 0).sum()),
        "seed": seed,
        "target_pos": n_pos,
        "target_neg": n_neg,
        "stratify_by": "t0_week",
        "week_counts_by_hit200k": week_counts,
        "feature_value_columns": FEATURE_VALUE_COLS,
        "feature_meta_columns": FEATURE_META_COLS,
        "mc_band_usd": [MC_LO, MC_HI],
        "mc_band_pos_def": "(mc_usd_t0 - 8000) / (20000 - 8000)",
        "is_pumpdotfun_def": "1 iff project_at_t0 == 'pumpdotfun' (else 0; pumpswap→0)",
        "no_lookahead": True,
        "labels_excluded_from_features": True,
        "pending": [
            "flow windows 60s/5m (Dune Q4)",
            "holders",
            "sol_usd_t0 Pyth as-of T0",
            "true hit_10x_30d (30d follow-up)",
        ],
        "outputs": {
            "sample": _rel(sample_path),
            "features": _rel(features_path),
            "features_meta": _rel(features_meta_path),
            "labels": _rel(labels_path),
            "qa": _rel(qa_path),
        },
    }
    features_meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    qa = qa_features(
        features,
        sample,
        sample_path=sample_path,
        features_path=features_path,
        labels_path=labels_path,
    )
    qa["sample_sha256"] = _sha256_file(sample_path)
    qa["features_sha256"] = _sha256_file(features_path)
    qa["labels_sha256"] = _sha256_file(labels_path)
    qa_path.write_text(json.dumps(qa, indent=2) + "\n")

    if not qa["ok"]:
        raise SystemExit(f"QA FAILED: {qa['issues']}")

    return {
        "ok": True,
        "n_sample": len(sample),
        "n_pos": int((sample["hit_200k"] == 1).sum()),
        "n_neg": int((sample["hit_200k"] == 0).sum()),
        "paths": meta["outputs"],
        "qa_path": _rel(qa_path),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cohort", type=Path, default=None)
    p.add_argument("--out-dir", type=Path, default=None)
    p.add_argument("--n-pos", type=int, default=TARGET_POS)
    p.add_argument("--n-neg", type=int, default=TARGET_NEG)
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)
    root = _repo_root()
    src = str(root / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    result = run(
        cohort_path=args.cohort,
        out_dir=args.out_dir,
        n_pos=args.n_pos,
        n_neg=args.n_neg,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
