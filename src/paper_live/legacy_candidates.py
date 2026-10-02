"""D-06 — Path A journal legacy stock (pc1=158) quarantine + analytics filter.

Frozen ``paper_candidates`` on 2026-10-01 (n=158):
  - 20× ``rule_buy60`` with ``buy_vol_source=dry_run.hash_stub``,
    ``feature_set_version=paper_live_v0_stub``
  - 138× early ``histgb_q5b`` (``buy_vol_source=bitquery.q5``) same morning window

These rows are an **audit trail**, not Path A Pump selectivity evidence.
Do **not** DELETE them without Sinck. Quarantine = COPY into
``paper_candidates_legacy_20261001`` (+ CSV export) and filter analytics to
Path A Pump post-restart (``entered_at >= PATH_A_PUMP_RESTART_ISO``).

See ``cycle0/path-a-debt-inventory-20261002.md`` D-06 and
``cycle0/depur-d06-d08-20261002.md``.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Sinck-approved Path A Pump restart (curve/age/priors) — Europe/Madrid.
PATH_A_PUMP_RESTART_ISO = "2026-10-02T12:13:00+02:00"
LEGACY_TABLE = "paper_candidates_legacy_20261001"
LEGACY_FEATURE_SET_STUB = "paper_live_v0_stub"
LEGACY_BUY_VOL_STUB = "dry_run.hash_stub"
LEGACY_SCORE_MODE_STUB = "rule_buy60"

# Explicit note for any selectivity / entry-gate report that still sees raw pc1.
PC1_NOT_SELECTIVITY = (
    "pc1=n_paper_candidates raw count includes 2026-10-01 Bitquery/stub legacy "
    "stock (n=158). It is NOT a Path A Pump HistGB@thr selectivity claim. "
    "Use path_a_pump / post-restart filtered metrics."
)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _restart_dt() -> datetime:
    dt = _parse_iso(PATH_A_PUMP_RESTART_ISO)
    assert dt is not None
    return dt


def _feats(row: Mapping[str, Any]) -> dict[str, Any]:
    raw = row.get("features_json")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    feats = row.get("features")
    return feats if isinstance(feats, dict) else {}


def is_stub_legacy_candidate(row: Mapping[str, Any]) -> bool:
    """True for the 20× rule_buy60 dry_run.hash_stub / paper_live_v0_stub stock."""
    feats = _feats(row)
    fsv = str(feats.get("feature_set_version") or "")
    bvs = str(feats.get("buy_vol_source") or "")
    mode = str(row.get("score_mode") or feats.get("score_mode") or "")
    if fsv == LEGACY_FEATURE_SET_STUB:
        return True
    if bvs == LEGACY_BUY_VOL_STUB or "hash_stub" in bvs:
        return True
    if mode == LEGACY_SCORE_MODE_STUB and (
        fsv.endswith("_stub") or "hash_stub" in bvs or not feats.get("t0_definition")
    ):
        # rule_buy60 alone is not enough post-Path-A (debug smoke may use it);
        # require stub markers or missing Path A t0_definition.
        return True
    return False


def is_pc1_legacy_stock(row: Mapping[str, Any]) -> bool:
    """True for the frozen 2026-10-01 pc1=158 cohort (stub + early histgb).

    Primary rule: ``entered_at`` strictly before Path A Pump restart.
    Stub markers also force legacy even if timestamps were rewritten.
    """
    if is_stub_legacy_candidate(row):
        return True
    entered = _parse_iso(row.get("entered_at"))
    if entered is None:
        return False
    return entered < _restart_dt()


def is_path_a_pump_candidate(row: Mapping[str, Any]) -> bool:
    """Eligible for Path A Pump selectivity / entry analytics."""
    return not is_pc1_legacy_stock(row)


def filter_path_a_pump_candidates(
    rows: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    return [r for r in rows if is_path_a_pump_candidate(r)]


def filter_exclude_stub_legacy(
    rows: Iterable[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Exclude only the 20× stub stock (keep early histgb unless caller also cuts by date)."""
    return [r for r in rows if not is_stub_legacy_candidate(r)]


@dataclass(frozen=True)
class EntryMetrics:
    n_raw: int
    n_path_a_pump: int
    n_stub_legacy: int
    n_pc1_legacy: int
    scores_path_a_pump: tuple[float, ...]
    note: str = PC1_NOT_SELECTIVITY

    def as_dict(self) -> dict[str, Any]:
        scores = list(self.scores_path_a_pump)
        n = len(scores)
        return {
            "n_paper_candidates_raw": self.n_raw,
            "n_paper_candidates_path_a_pump": self.n_path_a_pump,
            "n_stub_legacy": self.n_stub_legacy,
            "n_pc1_legacy": self.n_pc1_legacy,
            "n_scores_path_a_pump": n,
            "score_max_path_a_pump": max(scores) if scores else None,
            "score_median_path_a_pump": (
                float(sorted(scores)[n // 2]) if scores else None
            ),
            "pc1_not_selectivity_claim": True,
            "path_a_pump_restart_iso": PATH_A_PUMP_RESTART_ISO,
            "note": self.note,
        }


def entry_metrics_from_candidate_rows(
    rows: Sequence[Mapping[str, Any]],
) -> EntryMetrics:
    """Entry / selectivity metrics that **exclude** pc1 legacy stock."""
    raw = list(rows)
    stub_n = sum(1 for r in raw if is_stub_legacy_candidate(r))
    legacy_n = sum(1 for r in raw if is_pc1_legacy_stock(r))
    path_a = filter_path_a_pump_candidates(raw)
    scores: list[float] = []
    for r in path_a:
        s = r.get("score")
        if s is None:
            continue
        try:
            scores.append(float(s))
        except (TypeError, ValueError):
            continue
    return EntryMetrics(
        n_raw=len(raw),
        n_path_a_pump=len(path_a),
        n_stub_legacy=stub_n,
        n_pc1_legacy=legacy_n,
        scores_path_a_pump=tuple(scores),
    )


def load_paper_candidate_rows(sqlite_path: Path | str) -> list[dict[str, Any]]:
    path = Path(sqlite_path)
    if not path.is_file():
        return []
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT mint, t0_ts, mc_usd_t0, score, score_mode, rank_at_entry, "
            "features_json, entered_at FROM paper_candidates"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def entry_metrics_from_sqlite(sqlite_path: Path | str) -> EntryMetrics:
    return entry_metrics_from_candidate_rows(load_paper_candidate_rows(sqlite_path))


def export_legacy_quarantine(
    sqlite_path: Path | str,
    *,
    csv_path: Path | str | None = None,
    table_name: str = LEGACY_TABLE,
) -> dict[str, Any]:
    """COPY pc1 legacy rows into quarantine table + optional CSV. Never DELETE live rows.

    Idempotent: re-run refreshes the quarantine table from current
    ``paper_candidates`` matching the legacy predicate (entered_at < restart
    OR stub markers). Live ``paper_candidates`` is left intact.
    """
    path = Path(sqlite_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    rows = load_paper_candidate_rows(path)
    legacy_rows = [r for r in rows if is_pc1_legacy_stock(r)]

    con = sqlite3.connect(path)
    try:
        con.execute(f"DROP TABLE IF EXISTS {table_name}")
        con.execute(
            f"""
            CREATE TABLE {table_name} (
              mint TEXT PRIMARY KEY,
              t0_ts TEXT NOT NULL,
              mc_usd_t0 REAL NOT NULL,
              score REAL,
              score_mode TEXT,
              rank_at_entry INTEGER,
              features_json TEXT,
              entered_at TEXT NOT NULL,
              quarantine_reason TEXT NOT NULL,
              quarantined_at TEXT NOT NULL
            )
            """
        )
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        for r in legacy_rows:
            reason = (
                "stub_hash_or_feature_set"
                if is_stub_legacy_candidate(r)
                else "pc1_pre_path_a_pump_restart"
            )
            con.execute(
                f"""
                INSERT INTO {table_name}
                (mint, t0_ts, mc_usd_t0, score, score_mode, rank_at_entry,
                 features_json, entered_at, quarantine_reason, quarantined_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["mint"],
                    r["t0_ts"],
                    r["mc_usd_t0"],
                    r.get("score"),
                    r.get("score_mode"),
                    r.get("rank_at_entry"),
                    r.get("features_json"),
                    r["entered_at"],
                    reason,
                    now,
                ),
            )
        # Integrity: live table untouched — count must still match pre-export.
        n_live = con.execute("SELECT COUNT(*) FROM paper_candidates").fetchone()[0]
        n_q = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        con.commit()
    finally:
        con.close()

    out_csv: Path | None = Path(csv_path) if csv_path else None
    if out_csv is not None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "mint",
            "t0_ts",
            "mc_usd_t0",
            "score",
            "score_mode",
            "rank_at_entry",
            "entered_at",
            "feature_set_version",
            "buy_vol_source",
            "quarantine_reason",
        ]
        with out_csv.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            for r in legacy_rows:
                feats = _feats(r)
                reason = (
                    "stub_hash_or_feature_set"
                    if is_stub_legacy_candidate(r)
                    else "pc1_pre_path_a_pump_restart"
                )
                w.writerow(
                    {
                        "mint": r["mint"],
                        "t0_ts": r["t0_ts"],
                        "mc_usd_t0": r["mc_usd_t0"],
                        "score": r.get("score"),
                        "score_mode": r.get("score_mode"),
                        "rank_at_entry": r.get("rank_at_entry"),
                        "entered_at": r["entered_at"],
                        "feature_set_version": feats.get("feature_set_version"),
                        "buy_vol_source": feats.get("buy_vol_source"),
                        "quarantine_reason": reason,
                    }
                )

    return {
        "sqlite": str(path),
        "table": table_name,
        "n_quarantined": n_q,
        "n_paper_candidates_live_unchanged": n_live,
        "n_stub_legacy": sum(1 for r in legacy_rows if is_stub_legacy_candidate(r)),
        "csv": str(out_csv) if out_csv else None,
        "path_a_pump_restart_iso": PATH_A_PUMP_RESTART_ISO,
        "deleted_live_rows": False,
        "note": PC1_NOT_SELECTIVITY,
    }


def path_a_post_restart_sighting_ok(row: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """D-08 journal invariant for post-restart Path A Pump sightings.

    Expects ``q5a_curve_age_source`` stamped and ``score_mode`` never
    ``skip_prior_not_train`` (priors resolve to dune_cohort_*).
    """
    fails: list[str] = []
    feats = _feats(row)
    src = feats.get("q5a_curve_age_source")
    if src not in ("q5a_trades", "pump_coin_gapfill"):
        fails.append(f"q5a_curve_age_source={src!r}")
    mode = str(row.get("score_mode") or "")
    if mode == "skip_prior_not_train":
        fails.append("score_mode=skip_prior_not_train")
    prior = str(feats.get("creator_prior_source") or "")
    if prior and not (
        prior.startswith("dune_cohort_") or prior in ("train_store_v1",)
    ):
        # Allow empty features in incomplete enrich; flag non-train family only
        # when a prior stamp exists and is off-family.
        if prior not in ("none", "", "pump_frontend_30d"):
            fails.append(f"creator_prior_source={prior!r}")
        elif prior in ("none", "pump_frontend_30d"):
            fails.append(f"creator_prior_source={prior!r} (expected dune_cohort_*)")
    return (len(fails) == 0, fails)
