"""D-06 — pc1=158 Bitquery/stub legacy quarantine + entry-metrics filter."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from paper_live.legacy_candidates import (
    LEGACY_TABLE,
    PATH_A_PUMP_RESTART_ISO,
    PC1_NOT_SELECTIVITY,
    entry_metrics_from_candidate_rows,
    entry_metrics_from_sqlite,
    export_legacy_quarantine,
    filter_path_a_pump_candidates,
    is_pc1_legacy_stock,
    is_stub_legacy_candidate,
)


def _row(
    *,
    mint: str,
    score_mode: str,
    entered_at: str,
    score: float | None = 0.5,
    fsv: str | None = None,
    bvs: str | None = None,
) -> dict:
    feats: dict = {}
    if fsv is not None:
        feats["feature_set_version"] = fsv
    if bvs is not None:
        feats["buy_vol_source"] = bvs
    return {
        "mint": mint,
        "t0_ts": entered_at,
        "mc_usd_t0": 12_000.0,
        "score": score,
        "score_mode": score_mode,
        "rank_at_entry": 1,
        "features_json": json.dumps(feats),
        "entered_at": entered_at,
    }


def test_stub_and_pc1_legacy_predicates():
    stub = _row(
        mint="stub1",
        score_mode="rule_buy60",
        entered_at="2026-10-01T10:23:01.126+02:00",
        score=100.0,
        fsv="paper_live_v0_stub",
        bvs="dry_run.hash_stub",
    )
    early = _row(
        mint="early1",
        score_mode="histgb_q5b",
        entered_at="2026-10-01T11:00:00+02:00",
        score=0.05,
        fsv="paper_live_v0_+q5b",
        bvs="bitquery.q5",
    )
    path_a = _row(
        mint="patha1",
        score_mode="histgb_q5b",
        entered_at="2026-10-02T12:30:00+02:00",
        score=0.91,
        fsv="paper_live_v0_+q5b",
        bvs="pump.frontend",
    )
    assert is_stub_legacy_candidate(stub) is True
    assert is_pc1_legacy_stock(stub) is True
    assert is_stub_legacy_candidate(early) is False
    assert is_pc1_legacy_stock(early) is True  # pre-restart
    assert is_pc1_legacy_stock(path_a) is False
    kept = filter_path_a_pump_candidates([stub, early, path_a])
    assert [r["mint"] for r in kept] == ["patha1"]


def test_entry_metrics_exclude_stub_and_pc1_legacy():
    """Selectivity / entry metrics must not treat pc1 stub stock as Path A signal."""
    rows = [
        _row(
            mint=f"stub{i}",
            score_mode="rule_buy60",
            entered_at="2026-10-01T10:23:01+02:00",
            score=10_000.0 + i,
            fsv="paper_live_v0_stub",
            bvs="dry_run.hash_stub",
        )
        for i in range(20)
    ] + [
        _row(
            mint=f"early{i}",
            score_mode="histgb_q5b",
            entered_at="2026-10-01T10:40:00+02:00",
            score=0.05,
            fsv="paper_live_v0_+q5b",
            bvs="bitquery.q5",
        )
        for i in range(138)
    ] + [
        _row(
            mint="post1",
            score_mode="histgb_q5b",
            entered_at="2026-10-02T13:00:00+02:00",
            score=0.95,
            fsv="paper_live_v0_+q5b",
            bvs="pump.frontend",
        )
    ]
    em = entry_metrics_from_candidate_rows(rows)
    assert em.n_raw == 159
    assert em.n_stub_legacy == 20
    assert em.n_pc1_legacy == 158
    assert em.n_path_a_pump == 1
    assert em.scores_path_a_pump == (0.95,)
    d = em.as_dict()
    assert d["pc1_not_selectivity_claim"] is True
    assert d["path_a_pump_restart_iso"] == PATH_A_PUMP_RESTART_ISO
    assert "NOT a Path A Pump" in PC1_NOT_SELECTIVITY or "NOT" in PC1_NOT_SELECTIVITY


def test_export_quarantine_copies_without_deleting(tmp_path: Path):
    db = tmp_path / "paper_journal.sqlite"
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE paper_candidates (
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
    rows = [
        _row(
            mint="stubA",
            score_mode="rule_buy60",
            entered_at="2026-10-01T10:23:01+02:00",
            score=50.0,
            fsv="paper_live_v0_stub",
            bvs="dry_run.hash_stub",
        ),
        _row(
            mint="earlyB",
            score_mode="histgb_q5b",
            entered_at="2026-10-01T10:50:00+02:00",
            score=0.04,
            fsv="paper_live_v0_+q5b",
            bvs="bitquery.q5",
        ),
        _row(
            mint="liveC",
            score_mode="histgb_q5b",
            entered_at="2026-10-02T14:00:00+02:00",
            score=0.92,
            fsv="paper_live_v0_+q5b",
            bvs="pump.frontend",
        ),
    ]
    for r in rows:
        con.execute(
            "INSERT INTO paper_candidates VALUES (?,?,?,?,?,?,?,?)",
            (
                r["mint"],
                r["t0_ts"],
                r["mc_usd_t0"],
                r["score"],
                r["score_mode"],
                r["rank_at_entry"],
                r["features_json"],
                r["entered_at"],
            ),
        )
    con.commit()
    con.close()

    csv_path = tmp_path / "paper_candidates_legacy_20261001.csv"
    meta = export_legacy_quarantine(db, csv_path=csv_path)
    assert meta["deleted_live_rows"] is False
    assert meta["n_quarantined"] == 2
    assert meta["n_paper_candidates_live_unchanged"] == 3
    assert meta["n_stub_legacy"] == 1
    assert csv_path.is_file()
    text = csv_path.read_text()
    assert "stubA" in text and "earlyB" in text and "liveC" not in text

    con = sqlite3.connect(db)
    n_live = con.execute("SELECT COUNT(*) FROM paper_candidates").fetchone()[0]
    n_q = con.execute(f"SELECT COUNT(*) FROM {LEGACY_TABLE}").fetchone()[0]
    mints_q = {
        r[0]
        for r in con.execute(f"SELECT mint FROM {LEGACY_TABLE}").fetchall()
    }
    con.close()
    assert n_live == 3  # never deleted
    assert n_q == 2
    assert mints_q == {"stubA", "earlyB"}

    em = entry_metrics_from_sqlite(db)
    assert em.n_raw == 3
    assert em.n_path_a_pump == 1
    assert em.scores_path_a_pump == (0.92,)
