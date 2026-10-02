#!/usr/bin/env python3
"""Build dune_cohort_v1 positive/negative cohort from Dune Q1+Q2 CSVs.

Idempotent: re-running overwrites the same output paths under data/samples/.

Inputs (read-only):
  data/samples/dune_pump_mc200k_30d.csv   (Q1)
  data/samples/dune_pump_t0_labels_30d.csv (Q2)

Outputs:
  data/samples/dune_cohort_v1_positives.csv
  data/samples/dune_cohort_v1_negatives.csv
  data/samples/dune_cohort_v1_labels.csv
  data/samples/dune_cohort_v1_meta.json

Frozen rules (definicion-captura-v0 / dune-wire / task):
  - Capture band MC $8k–$20k Pump.fun
  - PRIMARY label hit_10x_30d; positives via max_mc_after_t0 >= ~$200k (hit_200k)
  - Prefer mints ending with 'pump'
  - Labels/meta never go into a feature store file
  - Outliers: absurd max_mc OR volume tiny vs MC
  - Right-censor: primary_ready requires followup_days_available >= 7d
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"

Q1_PATH = SAMPLES / "dune_pump_mc200k_30d.csv"
Q2_PATH = SAMPLES / "dune_pump_t0_labels_30d.csv"

OUT_POS = SAMPLES / "dune_cohort_v1_positives.csv"
OUT_NEG = SAMPLES / "dune_cohort_v1_negatives.csv"
OUT_LABELS = SAMPLES / "dune_cohort_v1_labels.csv"
OUT_META = SAMPLES / "dune_cohort_v1_meta.json"

DEFINITION_VERSION = "dune_cohort_v1"

# Nominal Q2 window end (~30d lookback ending ~2026-09-29; see dune exports).
WINDOW_END_UTC = pd.Timestamp("2026-09-29 23:59:59", tz="UTC")

# Outlier thresholds (documented in meta + dune-cohort-v1.md).
MAX_MC_ABSURD_USD = 10_000_000_000.0  # $10B — dust/wrong-side pricing spikes
VOL_OVER_MC_MIN = 1e-4  # volume_usd_30d / max_mc_usd_30d below this = suspicious

# Right-censor gate for PRIMARY-ready training rows.
MIN_FOLLOWUP_DAYS_PRIMARY = 7.0

# Negatives: keep all if output would stay under this; else stratified sample.
NEG_SAMPLE_MAX_BYTES = 50 * 1024 * 1024
NEG_SAMPLE_CAP = 5000
NEG_SAMPLE_SEED = 42

MC_HIT_USD = 200_000.0
MC_BAND = (8000.0, 20000.0)


def _parse_ts(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, utc=True, format="mixed")


def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not Q1_PATH.is_file():
        raise FileNotFoundError(Q1_PATH)
    if not Q2_PATH.is_file():
        raise FileNotFoundError(Q2_PATH)
    q1 = pd.read_csv(Q1_PATH)
    q2 = pd.read_csv(Q2_PATH)
    required_q1 = {
        "mint",
        "max_mc_usd_30d",
        "volume_usd_30d",
        "n_trades_30d",
        "reached_pumpswap",
    }
    required_q2 = {
        "mint",
        "t0_ts",
        "max_mc_after_t0",
        "reached_pumpswap_after_t0",
        "hit_200k",
        "hit_10x_from_band_top_hint",
    }
    missing_q1 = required_q1 - set(q1.columns)
    missing_q2 = required_q2 - set(q2.columns)
    if missing_q1:
        raise ValueError(f"Q1 missing columns: {sorted(missing_q1)}")
    if missing_q2:
        raise ValueError(f"Q2 missing columns: {sorted(missing_q2)}")
    return q1, q2


def build_cohort(q1: pd.DataFrame, q2: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    n_raw_q1 = len(q1)
    n_raw_q2 = len(q2)

    # Q1-side outlier flags (used when mint joins).
    q1_f = q1.copy()
    q1_f["mint"] = q1_f["mint"].astype(str)
    q1_f["q1_absurd_mc"] = q1_f["max_mc_usd_30d"] > MAX_MC_ABSURD_USD
    vol_ratio = q1_f["volume_usd_30d"] / q1_f["max_mc_usd_30d"].clip(lower=1.0)
    q1_f["q1_tiny_vol_vs_mc"] = vol_ratio < VOL_OVER_MC_MIN
    q1_f["q1_vol_over_mc"] = vol_ratio
    q1_f["q1_outlier"] = q1_f["q1_absurd_mc"] | q1_f["q1_tiny_vol_vs_mc"]
    q1_cols = q1_f[
        [
            "mint",
            "max_mc_usd_30d",
            "volume_usd_30d",
            "n_trades_30d",
            "reached_pumpswap",
            "q1_absurd_mc",
            "q1_tiny_vol_vs_mc",
            "q1_vol_over_mc",
            "q1_outlier",
        ]
    ].rename(
        columns={
            "max_mc_usd_30d": "q1_max_mc_usd_30d",
            "volume_usd_30d": "q1_volume_usd_30d",
            "n_trades_30d": "q1_n_trades_30d",
            "reached_pumpswap": "q1_reached_pumpswap",
        }
    )

    steps: list[dict[str, Any]] = []
    df = q2.copy()
    df["mint"] = df["mint"].astype(str)
    df["t0"] = _parse_ts(df["t0_ts"])
    df["hit_200k"] = df["hit_200k"].astype(int)
    df["reached_pumpswap_after_t0"] = df["reached_pumpswap_after_t0"].astype(int)
    df["hit_10x_from_band_top_hint"] = df["hit_10x_from_band_top_hint"].astype(int)
    df["label_primary_hint"] = df["hit_10x_from_band_top_hint"]

    n0 = len(df)
    steps.append({"step": "raw_q2", "n_in": n0, "n_out": n0, "n_dropped": 0})

    # Prefer Pump.fun convention: mint suffix 'pump'.
    df["ends_with_pump"] = df["mint"].str.endswith("pump")
    n_before = len(df)
    dropped_pump = int((~df["ends_with_pump"]).sum())
    df = df.loc[df["ends_with_pump"]].copy()
    steps.append(
        {
            "step": "prefer_mint_endswith_pump",
            "n_in": n_before,
            "n_out": len(df),
            "n_dropped": dropped_pump,
            "rule": "mint.endswith('pump')",
        }
    )

    # Absurd max MC on Q2 label column.
    df["flag_absurd_mc_q2"] = df["max_mc_after_t0"] > MAX_MC_ABSURD_USD
    n_before = len(df)
    dropped_mc = int(df["flag_absurd_mc_q2"].sum())
    df = df.loc[~df["flag_absurd_mc_q2"]].copy()
    steps.append(
        {
            "step": "drop_absurd_max_mc_after_t0",
            "n_in": n_before,
            "n_out": len(df),
            "n_dropped": dropped_mc,
            "threshold_usd": MAX_MC_ABSURD_USD,
            "rule": "max_mc_after_t0 > 1e10 USD",
        }
    )

    # Join Q1 for volume / Q1-MC outlier filter (only where mint present in Q1).
    df = df.merge(q1_cols, on="mint", how="left")
    df["in_q1"] = df["q1_max_mc_usd_30d"].notna()
    df["flag_q1_outlier"] = df["q1_outlier"].fillna(False).astype(bool)
    n_before = len(df)
    n_with_q1_before = int(df["in_q1"].sum())
    dropped_vol = int(df["flag_q1_outlier"].sum())
    dropped_vol_absurd = int((df["q1_absurd_mc"].fillna(False) & df["flag_q1_outlier"]).sum())
    dropped_vol_ratio = int((df["q1_tiny_vol_vs_mc"].fillna(False) & df["flag_q1_outlier"]).sum())
    df = df.loc[~df["flag_q1_outlier"]].copy()
    steps.append(
        {
            "step": "drop_q1_outlier_when_joined",
            "n_in": n_before,
            "n_out": len(df),
            "n_dropped": dropped_vol,
            "n_with_q1_join_before_drop": n_with_q1_before,
            "n_dropped_q1_absurd_mc": dropped_vol_absurd,
            "n_dropped_q1_tiny_vol_vs_mc": dropped_vol_ratio,
            "n_with_q1_join_after_drop": int(df["in_q1"].sum()) if len(df) else 0,
            "thresholds": {
                "max_mc_usd_30d_gt": MAX_MC_ABSURD_USD,
                "volume_over_max_mc_lt": VOL_OVER_MC_MIN,
            },
            "rule": (
                "if mint in Q1: drop when q1_max_mc_usd_30d > 1e10 "
                "OR (q1_volume_usd_30d / q1_max_mc_usd_30d) < 1e-4; "
                "mints not in Q1 keep (Q1 is MC>=200k universe only)"
            ),
            "q1_global_n_absurd_mc": int(q1_f["q1_absurd_mc"].sum()),
            "q1_global_n_tiny_vol_vs_mc": int(q1_f["q1_tiny_vol_vs_mc"].sum()),
            "q1_global_n_outlier_union": int(q1_f["q1_outlier"].sum()),
            "q1_pump_n_outlier_union": int(
                q1_f.loc[q1_f["mint"].str.endswith("pump"), "q1_outlier"].sum()
            ),
        }
    )

    # Follow-up / right-censor.
    df["followup_days_available"] = (
        (WINDOW_END_UTC - df["t0"]).dt.total_seconds() / 86400.0
    )
    df["primary_ready"] = df["followup_days_available"] >= MIN_FOLLOWUP_DAYS_PRIMARY
    df["filter_ok"] = True  # survived all hard filters above

    # Consistency sanity (do not invent labels): hit_200k must match max_mc threshold.
    inconsistent = (
        ((df["hit_200k"] == 1) & (df["max_mc_after_t0"] < MC_HIT_USD))
        | ((df["hit_200k"] == 0) & (df["max_mc_after_t0"] >= MC_HIT_USD))
    )
    n_inconsistent = int(inconsistent.sum())
    if n_inconsistent:
        # Keep CSV truth; flag only.
        df["flag_hit_mc_inconsistent"] = inconsistent
    else:
        df["flag_hit_mc_inconsistent"] = False

    n_pos = int((df["hit_200k"] == 1).sum())
    n_neg = int((df["hit_200k"] == 0).sum())
    n_pos_pr = int(((df["hit_200k"] == 1) & df["primary_ready"]).sum())
    n_neg_pr = int(((df["hit_200k"] == 0) & df["primary_ready"]).sum())

    meta: dict[str, Any] = {
        "definition_version": DEFINITION_VERSION,
        "created_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "window_end_utc": WINDOW_END_UTC.isoformat(),
        "window_note": (
            "Q2 ~30d lookback ending ~2026-09-29; "
            "T0 near window end are right-censored for 30d follow-up"
        ),
        "mc_band_t0_usd": list(MC_BAND),
        "mc_hit_usd": MC_HIT_USD,
        "primary_label": "hit_10x_30d",
        "positive_definition": (
            "hit_200k==1 after filters (max_mc_after_t0 >= 200000); "
            "proxy for hit_10x from band top ($20k * 10)"
        ),
        "inputs": {
            "q1_path": str(Q1_PATH.relative_to(ROOT)),
            "q2_path": str(Q2_PATH.relative_to(ROOT)),
            "n_raw_q1": n_raw_q1,
            "n_raw_q2": n_raw_q2,
        },
        "thresholds": {
            "max_mc_absurd_usd": MAX_MC_ABSURD_USD,
            "vol_over_mc_min": VOL_OVER_MC_MIN,
            "min_followup_days_primary_ready": MIN_FOLLOWUP_DAYS_PRIMARY,
            "prefer_mint_suffix": "pump",
        },
        "filter_steps": steps,
        "n_after_filters": len(df),
        "n_positives": n_pos,
        "n_negatives": n_neg,
        "n_primary_ready": int(df["primary_ready"].sum()),
        "n_positives_primary_ready": n_pos_pr,
        "n_negatives_primary_ready": n_neg_pr,
        "n_hit_mc_inconsistent_rows": n_inconsistent,
        "t0_min_utc": df["t0"].min().isoformat() if len(df) else None,
        "t0_max_utc": df["t0"].max().isoformat() if len(df) else None,
        "streams_helius": "OFF",
        "secrets": False,
        "notes": [
            "Labels/max_mc_*/hit_* live only in labels/cohort files — never feature store.",
            "Q1 used for outlier volume/MC when mint overlaps; most Q2 negatives are not in Q1.",
            "primary_ready=False when followup_days_available < 7; rows still kept in all split.",
        ],
    }
    # attach clean q1 count for reference
    meta["n_q1_after_outlier_filters"] = int((~q1_f["q1_outlier"]).sum())
    meta["n_q1_ends_pump"] = int(q1_f["mint"].str.endswith("pump").sum())
    return df, meta


def _labels_frame(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "mint",
        "t0_ts",
        "hit_200k",
        "max_mc_after_t0",
        "reached_pumpswap_after_t0",
        "ends_with_pump",
        "flag_absurd_mc_q2",
        "in_q1",
        "flag_q1_outlier",
        "filter_ok",
        "followup_days_available",
        "primary_ready",
        "label_primary_hint",
        "flag_hit_mc_inconsistent",
    ]
    # flag_absurd_mc_q2 / flag_q1_outlier are False for survivors; still document.
    out = df.copy()
    if "flag_absurd_mc_q2" not in out.columns:
        out["flag_absurd_mc_q2"] = False
    if "flag_q1_outlier" not in out.columns:
        out["flag_q1_outlier"] = False
    out["flag_absurd_mc_q2"] = False  # survivors
    out["flag_q1_outlier"] = False
    out["t0_ts"] = out["t0"].dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3] + " UTC"
    return out[cols]


def _pos_neg_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["t0_ts"] = out["t0"].dt.strftime("%Y-%m-%d %H:%M:%S.%f").str[:-3] + " UTC"
    cols = [
        "mint",
        "t0_ts",
        "hit_200k",
        "max_mc_after_t0",
        "reached_pumpswap_after_t0",
        "followup_days_available",
        "primary_ready",
        "label_primary_hint",
        "in_q1",
        "q1_max_mc_usd_30d",
        "q1_volume_usd_30d",
        "q1_vol_over_mc",
    ]
    return out[cols]


def maybe_sample_negatives(
    neg: pd.DataFrame, meta: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Keep all negatives if projected CSV < 50MB; else stratified sample by t0 week."""
    # Estimate from labels-sized write of current frame.
    tmp_estimate = len(neg.to_csv(index=False).encode("utf-8"))
    meta["negatives_full_n"] = len(neg)
    meta["negatives_estimated_csv_bytes"] = tmp_estimate
    if tmp_estimate < NEG_SAMPLE_MAX_BYTES and len(neg) <= 10**9:
        meta["negatives_sampling"] = {
            "applied": False,
            "reason": f"estimated CSV {tmp_estimate} bytes < {NEG_SAMPLE_MAX_BYTES}",
            "n_written": len(neg),
        }
        return neg, meta

    neg = neg.copy()
    neg["_t0_week"] = neg["t0"].dt.tz_convert("UTC").dt.to_period("W-SUN").astype(str)
    # Stratified sample up to NEG_SAMPLE_CAP.
    n_cap = min(NEG_SAMPLE_CAP, len(neg))
    # Proportional per week, at least 1 from weeks that have rows when possible.
    weeks = neg["_t0_week"].value_counts()
    alloc = (weeks / weeks.sum() * n_cap).round().astype(int).clip(lower=1)
    # Fix rounding to exact n_cap.
    while alloc.sum() > n_cap:
        alloc.loc[alloc.idxmax()] -= 1
    while alloc.sum() < n_cap:
        alloc.loc[alloc.idxmax()] += 1
    parts = []
    for week, k in alloc.items():
        part = neg.loc[neg["_t0_week"] == week]
        take = min(int(k), len(part))
        parts.append(part.sample(n=take, random_state=NEG_SAMPLE_SEED))
    sampled = pd.concat(parts, ignore_index=True).drop(columns=["_t0_week"])
    meta["negatives_sampling"] = {
        "applied": True,
        "reason": f"estimated CSV {tmp_estimate} bytes >= {NEG_SAMPLE_MAX_BYTES}",
        "n_full": len(neg),
        "n_written": len(sampled),
        "cap": NEG_SAMPLE_CAP,
        "strata": "t0 week (W-SUN UTC)",
        "seed": NEG_SAMPLE_SEED,
        "per_week_alloc": {str(k): int(v) for k, v in alloc.items()},
    }
    return sampled, meta


def write_outputs(df: pd.DataFrame, meta: dict[str, Any]) -> dict[str, Any]:
    SAMPLES.mkdir(parents=True, exist_ok=True)

    pos = df.loc[df["hit_200k"] == 1].copy()
    neg = df.loc[df["hit_200k"] == 0].copy()
    neg_out, meta = maybe_sample_negatives(neg, meta)

    labels = _labels_frame(df)
    pos_csv = _pos_neg_frame(pos)
    neg_csv = _pos_neg_frame(neg_out)

    labels.to_csv(OUT_LABELS, index=False)
    pos_csv.to_csv(OUT_POS, index=False)
    neg_csv.to_csv(OUT_NEG, index=False)

    meta["outputs"] = {
        "positives": str(OUT_POS.relative_to(ROOT)),
        "negatives": str(OUT_NEG.relative_to(ROOT)),
        "labels": str(OUT_LABELS.relative_to(ROOT)),
        "meta": str(OUT_META.relative_to(ROOT)),
        "n_positives_rows_written": len(pos_csv),
        "n_negatives_rows_written": len(neg_csv),
        "n_labels_rows_written": len(labels),
        "positives_bytes": OUT_POS.stat().st_size if OUT_POS.exists() else None,
        "negatives_bytes": OUT_NEG.stat().st_size if OUT_NEG.exists() else None,
        "labels_bytes": OUT_LABELS.stat().st_size if OUT_LABELS.exists() else None,
    }
    # Fill byte sizes after write
    meta["outputs"]["positives_bytes"] = OUT_POS.stat().st_size
    meta["outputs"]["negatives_bytes"] = OUT_NEG.stat().st_size
    meta["outputs"]["labels_bytes"] = OUT_LABELS.stat().st_size

    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    return meta


def main() -> None:
    q1, q2 = load_inputs()
    df, meta = build_cohort(q1, q2)
    meta = write_outputs(df, meta)
    summary = {
        "definition_version": meta["definition_version"],
        "n_raw_q1": meta["inputs"]["n_raw_q1"],
        "n_raw_q2": meta["inputs"]["n_raw_q2"],
        "n_after_filters": meta["n_after_filters"],
        "n_positives": meta["n_positives"],
        "n_negatives": meta["n_negatives"],
        "n_primary_ready": meta["n_primary_ready"],
        "n_positives_primary_ready": meta["n_positives_primary_ready"],
        "n_negatives_primary_ready": meta["n_negatives_primary_ready"],
        "thresholds": meta["thresholds"],
        "outputs": meta["outputs"],
        "negatives_sampling": meta.get("negatives_sampling"),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
