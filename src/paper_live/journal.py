"""Paper journal: SQLite + CSV. Solo paper; sin órdenes reales."""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paper_live.config import (
    CANDIDATES_CSV,
    CANDIDATES_LITE_CSV,
    FOLLOWUP_CSV,
    HIT_10X_MULTIPLE,
    SIGHTINGS_CSV,
    SQLITE_PATH,
    STATE_PATH,
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
  mint TEXT PRIMARY KEY,
  t0_ts TEXT NOT NULL,
  mc_usd_t0 REAL NOT NULL,
  name TEXT,
  symbol TEXT,
  source TEXT,
  features_json TEXT,
  score REAL,
  score_mode TEXT,
  scores_json TEXT,
  score_lite REAL,
  paper_candidate INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_candidates (
  mint TEXT PRIMARY KEY,
  t0_ts TEXT NOT NULL,
  mc_usd_t0 REAL NOT NULL,
  score REAL,
  score_mode TEXT,
  rank_at_entry INTEGER,
  features_json TEXT,
  entered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS followup (
  mint TEXT NOT NULL,
  polled_at TEXT NOT NULL,
  mc_usd REAL,
  max_mc_after_t0 REAL,
  multiple REAL,
  hit_10x_30d INTEGER,
  PRIMARY KEY (mint, polled_at)
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


@dataclass
class Journal:
    sqlite_path: Path = SQLITE_PATH
    state_path: Path = STATE_PATH
    candidates_csv: Path = CANDIDATES_CSV
    followup_csv: Path = FOLLOWUP_CSV
    sightings_csv: Path = SIGHTINGS_CSV
    candidates_lite_csv: Path = CANDIDATES_LITE_CSV

    def __post_init__(self) -> None:
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as con:
            con.executescript(SCHEMA)
            self._migrate(con)

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.sqlite_path)
        con.row_factory = sqlite3.Row
        return con

    # --- state / cursor ---
    def load_state(self) -> dict[str, Any]:
        if self.state_path.is_file():
            return json.loads(self.state_path.read_text())
        return {
            "seen_mints": [],
            "dry_offset": 0,
            "cycles": 0,
            "last_poll_at": None,
            "last_followup_at": None,
        }

    def save_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        # never persist secrets
        safe = {k: v for k, v in state.items() if "token" not in k.lower() and "key" not in k.lower()}
        self.state_path.write_text(json.dumps(safe, indent=2))


    def _migrate(self, con: sqlite3.Connection) -> None:
        """Additive columns for multi-scorer (safe on existing DBs)."""
        cols = {r[1] for r in con.execute("PRAGMA table_info(sightings)").fetchall()}
        if "scores_json" not in cols:
            con.execute("ALTER TABLE sightings ADD COLUMN scores_json TEXT")
        if "score_lite" not in cols:
            con.execute("ALTER TABLE sightings ADD COLUMN score_lite REAL")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_candidates_lite (
              mint TEXT PRIMARY KEY,
              t0_ts TEXT NOT NULL,
              mc_usd_t0 REAL NOT NULL,
              score REAL,
              score_mode TEXT,
              rank_at_entry INTEGER,
              features_json TEXT,
              entered_at TEXT NOT NULL
            )
            """
        )

    def known_mints(self) -> set[str]:
        with self._conn() as con:
            rows = con.execute("SELECT mint FROM sightings").fetchall()
        return {r["mint"] for r in rows}

    def record_sighting(
        self,
        *,
        mint: str,
        t0_ts: str,
        mc_usd_t0: float,
        name: str | None,
        symbol: str | None,
        source: str,
        features: dict[str, Any],
        score: float | None,
        score_mode: str | None,
        paper_candidate: bool = False,
        scores_json: dict[str, Any] | str | None = None,
        score_lite: float | None = None,
    ) -> bool:
        """Insert first sighting. Returns False if mint already known (idempotent)."""
        now = _utcnow_iso()
        feats_json = json.dumps(features, default=str)
        if isinstance(scores_json, dict):
            scores_s = json.dumps(scores_json, default=str)
        elif scores_json is None:
            scores_s = None
        else:
            scores_s = str(scores_json)
        with self._conn() as con:
            try:
                con.execute(
                    """
                    INSERT INTO sightings
                    (mint, t0_ts, mc_usd_t0, name, symbol, source, features_json,
                     score, score_mode, scores_json, score_lite, paper_candidate, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mint,
                        t0_ts,
                        mc_usd_t0,
                        name,
                        symbol,
                        source,
                        feats_json,
                        score,
                        score_mode,
                        scores_s,
                        score_lite,
                        1 if paper_candidate else 0,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        buy_vol = features.get("buy_vol_usd_60s")
        buy_vol_src = features.get("buy_vol_source")
        self._append_csv(
            self.sightings_csv,
            [
                "mint",
                "t0_ts",
                "mc_usd_t0",
                "name",
                "symbol",
                "source",
                "buy_vol_usd_60s",
                "buy_vol_source",
                "score",
                "score_mode",
                "score_lite",
                "paper_candidate",
                "created_at",
            ],
            {
                "mint": mint,
                "t0_ts": t0_ts,
                "mc_usd_t0": mc_usd_t0,
                "name": name,
                "symbol": symbol,
                "source": source,
                "buy_vol_usd_60s": buy_vol,
                "buy_vol_source": buy_vol_src,
                "score": score,
                "score_mode": score_mode,
                "score_lite": score_lite,
                "paper_candidate": int(paper_candidate),
                "created_at": now,
            },
        )
        return True

    def enter_paper(
        self,
        *,
        mint: str,
        t0_ts: str,
        mc_usd_t0: float,
        score: float,
        score_mode: str,
        rank_at_entry: int,
        features: dict[str, Any],
    ) -> bool:
        now = _utcnow_iso()
        feats_json = json.dumps(features, default=str)
        with self._conn() as con:
            try:
                con.execute(
                    """
                    INSERT INTO paper_candidates
                    (mint, t0_ts, mc_usd_t0, score, score_mode, rank_at_entry,
                     features_json, entered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mint,
                        t0_ts,
                        mc_usd_t0,
                        score,
                        score_mode,
                        rank_at_entry,
                        feats_json,
                        now,
                    ),
                )
                con.execute(
                    "UPDATE sightings SET paper_candidate=1, score=?, score_mode=? WHERE mint=?",
                    (score, score_mode, mint),
                )
            except sqlite3.IntegrityError:
                return False
        self._append_csv(
            self.candidates_csv,
            [
                "mint",
                "t0_ts",
                "mc_usd_t0",
                "score",
                "score_mode",
                "rank_at_entry",
                "entered_at",
            ],
            {
                "mint": mint,
                "t0_ts": t0_ts,
                "mc_usd_t0": mc_usd_t0,
                "score": score,
                "score_mode": score_mode,
                "rank_at_entry": rank_at_entry,
                "entered_at": now,
            },
        )
        return True


    def enter_paper_lite(
        self,
        *,
        mint: str,
        t0_ts: str,
        mc_usd_t0: float,
        score: float,
        score_mode: str,
        rank_at_entry: int,
        features: dict[str, Any],
    ) -> bool:
        """Second-lane explore enter (separate table/CSV; does not collide histgb PK)."""
        now = _utcnow_iso()
        feats_json = json.dumps(features, default=str)
        with self._conn() as con:
            try:
                con.execute(
                    """
                    INSERT INTO paper_candidates_lite
                    (mint, t0_ts, mc_usd_t0, score, score_mode, rank_at_entry,
                     features_json, entered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        mint,
                        t0_ts,
                        mc_usd_t0,
                        score,
                        score_mode,
                        rank_at_entry,
                        feats_json,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                return False
        self._append_csv(
            self.candidates_lite_csv,
            [
                "mint",
                "t0_ts",
                "mc_usd_t0",
                "score",
                "score_mode",
                "rank_at_entry",
                "entered_at",
            ],
            {
                "mint": mint,
                "t0_ts": t0_ts,
                "mc_usd_t0": mc_usd_t0,
                "score": score,
                "score_mode": score_mode,
                "rank_at_entry": rank_at_entry,
                "entered_at": now,
            },
        )
        return True

    def open_candidates(self) -> list[dict[str, Any]]:
        with self._conn() as con:
            rows = con.execute(
                "SELECT mint, t0_ts, mc_usd_t0, score, entered_at FROM paper_candidates"
            ).fetchall()
        return [dict(r) for r in rows]

    def record_followup(
        self,
        *,
        mint: str,
        mc_usd: float | None,
        mc_usd_t0: float,
        max_mc_after_t0: float | None,
    ) -> dict[str, Any]:
        now = _utcnow_iso()
        multiple = None
        hit = None
        if max_mc_after_t0 is not None and mc_usd_t0 > 0:
            multiple = max_mc_after_t0 / mc_usd_t0
            hit = 1 if multiple >= HIT_10X_MULTIPLE else 0
        with self._conn() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO followup
                (mint, polled_at, mc_usd, max_mc_after_t0, multiple, hit_10x_30d)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mint, now, mc_usd, max_mc_after_t0, multiple, hit),
            )
        row = {
            "mint": mint,
            "polled_at": now,
            "mc_usd": mc_usd,
            "max_mc_after_t0": max_mc_after_t0,
            "multiple": multiple,
            "hit_10x_30d": hit,
        }
        self._append_csv(
            self.followup_csv,
            list(row.keys()),
            row,
        )
        return row

    def recent_paper_entered_at(self, *, since_iso: str | None = None) -> list[str]:
        """Return entered_at timestamps for paper candidates (optionally since cutoff)."""
        with self._conn() as con:
            if since_iso:
                rows = con.execute(
                    "SELECT entered_at FROM paper_candidates WHERE entered_at >= ? ORDER BY entered_at",
                    (since_iso,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT entered_at FROM paper_candidates ORDER BY entered_at"
                ).fetchall()
        return [r["entered_at"] for r in rows]

    def summary(self) -> dict[str, Any]:
        with self._conn() as con:
            n_sight = con.execute("SELECT COUNT(*) c FROM sightings").fetchone()["c"]
            n_paper = con.execute("SELECT COUNT(*) c FROM paper_candidates").fetchone()["c"]
            n_fu = con.execute("SELECT COUNT(*) c FROM followup").fetchone()["c"]
            hits = con.execute(
                "SELECT COUNT(*) c FROM followup WHERE hit_10x_30d=1"
            ).fetchone()["c"]
        out: dict[str, Any] = {
            "n_sightings": n_sight,
            # Raw audit-trail count — NOT Path A Pump selectivity (see D-06).
            "n_paper_candidates": n_paper,
            "n_followup_rows": n_fu,
            "n_hit_10x_observed": hits,
            "sqlite": str(self.sqlite_path),
            "candidates_csv": str(self.candidates_csv),
        }
        try:
            from paper_live.legacy_candidates import (
                PC1_NOT_SELECTIVITY,
                entry_metrics_from_sqlite,
            )

            em = entry_metrics_from_sqlite(self.sqlite_path).as_dict()
            out["n_paper_candidates_path_a_pump"] = em["n_paper_candidates_path_a_pump"]
            out["n_paper_candidates_pc1_legacy"] = em["n_pc1_legacy"]
            out["n_paper_candidates_stub_legacy"] = em["n_stub_legacy"]
            out["pc1_not_selectivity_claim"] = True
            out["pc1_note"] = PC1_NOT_SELECTIVITY
        except Exception:  # noqa: BLE001 — summary must never crash the loop
            out["n_paper_candidates_path_a_pump"] = None
        return out

    @staticmethod
    def _append_csv(path: Path, fieldnames: list[str], row: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        new = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
