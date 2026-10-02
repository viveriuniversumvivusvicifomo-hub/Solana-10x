"""Live↔train score calibration helpers for histgb_q5b.

Root causes of live scores << trainQ (2026-10-01 diagnosis)
----------------------------------------------------------
1. ``net_sol_curve`` / ``progress_curve_proxy`` / ``max_buy_sol`` ≈ 0 on live:
   Bitquery ``Side.Amount`` often null; ``Dex.ProgramAddress`` null → project
   not ``pumpdotfun`` so curve never accumulates. Fixed in ``parse_bitquery_trades``.
2. Q5a lookback reused poll ``hours_ago=2`` → truncated create→T0 history.
   Fixed via ``DEFAULT_Q5A_HOURS_AGO`` (48h, widen to 7d cover).
3. Trades with null USD were dropped; now derive USD↔SOL with ``DEFAULT_SOL_USD_REF``.

This module can **best-effort repair** already-journaled feature vectors (no Bitquery)
by reconstructing SOL fields from USD, then re-score. Full parity still needs a
live re-enrich after the parse/lookback fix (blocked on HTTP 402).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from features.post_q5_sets import FEATURE_SETS
from paper_live.config import CALIBRATION_Q5B_PATH, DEFAULT_SOL_USD_REF, MODEL_Q5B_PATH
from paper_live.score import PaperScorer


Q5B_COLS = list(FEATURE_SETS["+q5b"])


def repair_sol_features(
    feats: dict[str, Any],
    *,
    sol_usd: float = DEFAULT_SOL_USD_REF,
    assume_pumpdotfun: bool = True,
) -> dict[str, Any]:
    """Best-effort SOL parity when Bitquery left curve/max_buy_sol at 0.

    Uses ``amount_usd / sol_usd`` (train median ratio ≈ 103.11). When
    ``assume_pumpdotfun`` (MC 8–20k band still on curve), maps net flow onto
    ``net_sol_curve`` so progress matches Dune Q5a.
    """
    out = dict(feats)
    px = float(sol_usd) if sol_usd and sol_usd > 0 else DEFAULT_SOL_USD_REF

    def _f(key: str) -> float | None:
        v = out.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    max_usd = _f("max_buy_usd")
    max_sol = _f("max_buy_sol")
    if max_usd is not None and max_usd > 0 and (max_sol is None or max_sol <= 0):
        out["max_buy_sol"] = max_usd / px

    buy_t = _f("buy_vol_usd_total") or 0.0
    sell_t = _f("sell_vol_usd_total") or 0.0
    net_usd = buy_t - sell_t
    derived_net = net_usd / px

    cur_total = _f("net_sol_total")
    cur_curve = _f("net_sol_curve")
    need_sol = (
        (cur_curve is None or cur_curve == 0.0)
        and (cur_total is None or cur_total == 0.0)
        and (buy_t > 0 or sell_t > 0)
    )
    project_bug = (
        cur_total is not None
        and cur_total != 0.0
        and (cur_curve is None or cur_curve == 0.0)
    )

    if need_sol:
        out["net_sol_total"] = derived_net
        if assume_pumpdotfun:
            out["net_sol_curve"] = derived_net
    elif project_bug and assume_pumpdotfun:
        out["net_sol_curve"] = float(cur_total)

    curve = _f("net_sol_curve")
    if curve is not None:
        out["progress_curve_proxy"] = float(min(max(curve / 85.0, 0.0), 2.0))
    return out


@dataclass
class RecalibrateReport:
    n_histgb: int
    n_repaired: int
    thr_top1: float
    before_max: float
    after_max: float
    before_median: float
    after_median: float
    before_n_pass: int
    after_n_pass: int
    before_scores: list[float]
    after_scores: list[float]
    note: str


def recalibrate_journal_scores(
    sqlite_path: Path,
    *,
    sol_usd: float = DEFAULT_SOL_USD_REF,
    write: bool = False,
    model_path: Path | None = None,
) -> RecalibrateReport:
    """Re-score histgb_q5b sightings after SOL feature repair. Optional write-back."""
    import joblib

    path = model_path or MODEL_Q5B_PATH
    blob = joblib.load(path)
    pipe = blob["pipeline"]
    names = list(blob["feature_names"])
    calib = {}
    if CALIBRATION_Q5B_PATH.is_file():
        calib = json.loads(CALIBRATION_Q5B_PATH.read_text())
    thr = float((calib.get("thresholds") or {}).get("0.01") or 0.9998068280570067)

    conn = sqlite3.connect(str(sqlite_path))
    rows = conn.execute(
        "SELECT mint, features_json, score, score_mode FROM sightings WHERE score_mode = 'histgb_q5b'"
    ).fetchall()
    before: list[float] = []
    after: list[float] = []
    n_repaired = 0
    updates: list[tuple[str, str, float]] = []

    scorer_names = names or Q5B_COLS
    for mint, fj, score, _mode in rows:
        feats = json.loads(fj) if fj else {}
        if score is not None:
            before.append(float(score))
        repaired = repair_sol_features(feats, sol_usd=sol_usd)
        changed = any(
            repaired.get(k) != feats.get(k)
            for k in ("net_sol_curve", "net_sol_total", "progress_curve_proxy", "max_buy_sol")
        )
        if changed:
            n_repaired += 1
        row = np.array(
            [[(np.nan if repaired.get(n) is None else repaired.get(n)) for n in scorer_names]],
            dtype=float,
        )
        proba = float(pipe.predict_proba(row)[0, 1])
        after.append(proba)
        if write and changed:
            # merge repaired SOL keys into stored features; update score
            for k in ("net_sol_curve", "net_sol_total", "progress_curve_proxy", "max_buy_sol"):
                if k in repaired:
                    feats[k] = repaired[k]
            feats["calibration_repair"] = "sol_from_usd_v1"
            updates.append((json.dumps(feats), proba, mint))

    if write and updates:
        conn.executemany(
            "UPDATE sightings SET features_json = ?, score = ? WHERE mint = ?",
            updates,
        )
        conn.commit()
    conn.close()

    b = np.array(before, dtype=float) if before else np.array([0.0])
    a = np.array(after, dtype=float) if after else np.array([0.0])
    return RecalibrateReport(
        n_histgb=len(rows),
        n_repaired=n_repaired,
        thr_top1=thr,
        before_max=float(b.max()) if len(before) else float("nan"),
        after_max=float(a.max()) if len(after) else float("nan"),
        before_median=float(np.median(b)) if len(before) else float("nan"),
        after_median=float(np.median(a)) if len(after) else float("nan"),
        before_n_pass=int((b >= thr).sum()) if len(before) else 0,
        after_n_pass=int((a >= thr).sum()) if len(after) else 0,
        before_scores=before,
        after_scores=after,
        note=(
            "Partial repair only (SOL from USD). Full parity needs Bitquery re-enrich "
            "with fixed parse + q5a_hours_ago>=48. HTTP 402 blocks live re-fetch."
        ),
    )


def compare_train_live_distributions(
    train_csv: Path,
    live_feats: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Side-by-side median/null stats for FEATURE_SETS['+q5b'] columns."""
    import pandas as pd

    train = pd.read_csv(train_csv)
    live = pd.DataFrame(live_feats)
    out = []
    for c in Q5B_COLS:
        t = pd.to_numeric(train[c], errors="coerce") if c in train.columns else pd.Series(dtype=float)
        l = pd.to_numeric(live[c], errors="coerce") if c in live.columns else pd.Series(dtype=float)
        out.append(
            {
                "col": c,
                "train_med": float(t.median()) if len(t) else None,
                "live_med": float(l.median()) if len(l) else None,
                "train_null_pct": float(100 * t.isna().mean()) if len(t) else None,
                "live_null_pct": float(100 * l.isna().mean()) if len(l) else None,
                "train_mean": float(t.mean()) if len(t) else None,
                "live_mean": float(l.mean()) if len(l) else None,
            }
        )
    return out
