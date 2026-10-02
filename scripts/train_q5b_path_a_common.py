#!/usr/bin/env python3
"""Shared helpers for Path A q5b candidate training (SolModelos).

Canonical entry: scripts/train_q5b_path_a_candidate_wf.py
Recipe: cycle0/recipe-path-a-train-canonical-20261002.md
GO:     cycle0/go-criterion-q5b-candidate-vs-last-20261002.md

Never overwrite q5b_last.joblib / q5b_calibration.json.
0 Dune API. USD scale OFF. Paper untouched.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "data/paper_live/models"
Q5B_LAST = MODEL_DIR / "q5b_last.joblib"
Q5B_CALIB = MODEL_DIR / "q5b_calibration.json"

FORBIDDEN_MODEL_NAMES = frozenset(
    {
        "q5b_last.joblib",
        "q5b_calibration.json",
    }
)

ARCHIVE_NOGO_MSG = (
    "NO-GO / archived: historical train_q5b_pump_* scripts are quarantined.\n"
    "Use canonical: scripts/train_q5b_path_a_candidate_wf.py\n"
    "Recipe: cycle0/recipe-path-a-train-canonical-20261002.md\n"
    "GO: cycle0/go-criterion-q5b-candidate-vs-last-20261002.md\n"
    "Quarantine joblibs: cycle0/quarantine-q5b-pump-joblibs-20261002.md\n"
    "Set SOLMODELOS_ARCHIVE_FORCE=1 only for archaeology (still never writes q5b_last)."
)


def utcnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def jsonable(o: Any) -> Any:
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(x) for x in o]
    if isinstance(o, (np.floating, float)):
        return float(o)
    if isinstance(o, (np.integer, int)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if o is None or isinstance(o, (str, bool)):
        return o
    return str(o)


def is_forbidden_model_path(path: Path) -> bool:
    """True if path is (or resolves to) producción q5b_last / calib."""
    p = Path(path)
    if p.name in FORBIDDEN_MODEL_NAMES:
        return True
    try:
        resolved = p.resolve()
    except OSError:
        resolved = p
    for forbidden in (Q5B_LAST, Q5B_CALIB):
        try:
            if resolved == forbidden.resolve():
                return True
        except OSError:
            if resolved == forbidden:
                return True
    return False


def refuse_if_q5b_last(path: Path, *, label: str = "--out") -> int | None:
    """Return exit code 2 with message if path would clobber q5b_last/calib; else None."""
    if is_forbidden_model_path(path):
        print(
            json.dumps(
                {
                    "status": "REFUSE",
                    "reason": "would_overwrite_q5b_last_or_calibration",
                    "label": label,
                    "path": str(path),
                    "message": (
                        f"REFUSE: {label} resolves to producción artifact "
                        f"(q5b_last.joblib / q5b_calibration.json). "
                        "Export only q5b_path_a_candidate_*.joblib "
                        "(see cycle0/recipe-path-a-train-canonical-20261002.md)."
                    ),
                },
                indent=2,
            )
        )
        return 2
    return None


def default_candidate_joblib(stamp: str, *, profile: str | None = None) -> Path:
    if profile and profile not in ("livelike", "default", ""):
        return MODEL_DIR / f"q5b_path_a_candidate_{profile}_{stamp}.joblib"
    return MODEL_DIR / f"q5b_path_a_candidate_{stamp}.joblib"


def rescore_journal_pump(
    pipe,
    feature_names: list[str],
    *,
    journal: Path | None = None,
    since: str = "2026-10-02",
    limit: int = 200,
) -> dict[str, Any]:
    """Score a small Path A Pump journal slice with candidate vs q5b_last."""
    import sqlite3

    journal = journal or (ROOT / "data/paper_live/paper_journal.sqlite")
    con = sqlite3.connect(str(journal))
    con.row_factory = sqlite3.Row
    rows = list(
        con.execute(
            "SELECT mint, score, features_json, created_at FROM sightings "
            "WHERE created_at >= ? ORDER BY rowid DESC LIMIT ?",
            (since, limit * 3),
        )
    )
    con.close()
    vectors: list[dict[str, Any]] = []
    for r in rows:
        if not r["features_json"]:
            continue
        try:
            feats = json.loads(r["features_json"])
        except json.JSONDecodeError:
            continue
        if feats.get("t0_definition") != "pump_mc_band_sighting_v1":
            continue
        if not feats.get("capture_scoreable"):
            continue
        vectors.append(
            {
                "mint": r["mint"],
                "score_logged": r["score"],
                "created_at": r["created_at"],
                **{c: feats.get(c) for c in feature_names},
            }
        )
        if len(vectors) >= limit:
            break
    if not vectors:
        return {"available": False, "reason": "no_pump_scoreable_rows"}
    df = pd.DataFrame(vectors)
    X = df.reindex(columns=feature_names).to_numpy(dtype=float)
    proba = pipe.predict_proba(X)[:, 1]
    out: dict[str, Any] = {
        "available": True,
        "n": int(len(df)),
        "pilot": {
            "median": float(np.median(proba)),
            "mean": float(np.mean(proba)),
            "max": float(proba.max()),
            "min": float(proba.min()),
            "frac_ge_0.9": float((proba >= 0.9).mean()),
            "p90": float(np.quantile(proba, 0.9)),
            "p99": float(np.quantile(proba, 0.99)),
        },
    }
    if Q5B_LAST.is_file():
        blob = joblib.load(Q5B_LAST)
        pipe_l = blob["pipeline"]
        names_l = list(blob["feature_names"])
        Xl = df.reindex(columns=names_l).to_numpy(dtype=float)
        pl = pipe_l.predict_proba(Xl)[:, 1]
        out["q5b_last"] = {
            "median": float(np.median(pl)),
            "mean": float(np.mean(pl)),
            "max": float(pl.max()),
            "min": float(pl.min()),
            "frac_ge_0.9": float((pl >= 0.9).mean()),
            "p90": float(np.quantile(pl, 0.9)),
            "p99": float(np.quantile(pl, 0.99)),
        }
        out["lift_max"] = float(proba.max() - pl.max())
        out["lift_median"] = float(np.median(proba) - np.median(pl))
        out["lift_frac_ge_0.9"] = float((proba >= 0.9).mean() - (pl >= 0.9).mean())
    return out


def archive_refuse_or_continue() -> int | None:
    """If invoked without SOLMODELOS_ARCHIVE_FORCE, print NO-GO and return 2."""
    import os

    if os.environ.get("SOLMODELOS_ARCHIVE_FORCE", "").strip() in ("1", "true", "yes"):
        return None
    print(ARCHIVE_NOGO_MSG)
    return 2
