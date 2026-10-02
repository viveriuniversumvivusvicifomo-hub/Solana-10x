"""D-02: GO-before-coding gate — check_go_gate + train --go-card refuse."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
CHECK = ROOT / "scripts/check_go_gate.py"
CANON = ROOT / "scripts/train_q5b_path_a_candidate_wf.py"
FIXTURES = ROOT / "tests/fixtures/go_cards"
TEMPLATE = ROOT / "cycle0/templates/GO_CARD.md"


def _load_check():
    spec = importlib.util.spec_from_file_location("check_go_gate", CHECK)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _env() -> dict:
    return {
        **os.environ,
        "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT / "scripts"),
    }


def test_template_exists_with_go_card_fence():
    assert TEMPLATE.is_file()
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "```go_card" in text
    assert "go_criterion_ref" in text
    assert "cost_fence" in text
    assert "overwrite_q5b_last" in text
    assert "paper_restart" in text
    assert "protocolos_ack" in text


def test_validate_valid_train_card():
    mod = _load_check()
    report = mod.validate_go_card(FIXTURES / "valid_train_go.md", expect_action="train")
    assert report["ok"] is True
    assert report["status"] == "PASS"
    assert report["fields"]["verdict"].upper() == "GO"


def test_validate_nogo_verdict_refuses():
    mod = _load_check()
    report = mod.validate_go_card(FIXTURES / "nogo_verdict.md")
    assert report["ok"] is False
    assert any("NO-GO" in e for e in report["errors"])


def test_validate_placeholder_cost_fence_refuses():
    mod = _load_check()
    report = mod.validate_go_card(FIXTURES / "missing_cost_fence.md")
    assert report["ok"] is False
    assert any("placeholder" in e for e in report["errors"])


def test_cli_valid_exit_0():
    proc = subprocess.run(
        [PY, str(CHECK), "--go-card", str(FIXTURES / "valid_train_go.md"), "--expect-action", "train"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["ok"] is True


def test_cli_nogo_exit_2():
    proc = subprocess.run(
        [PY, str(CHECK), "--go-card", str(FIXTURES / "nogo_verdict.md")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_train_refuses_without_go_card():
    """Real train path (not dry-path-check) must REFUSE if --go-card omitted."""
    proc = subprocess.run(
        [
            PY,
            str(CANON),
            "--stamp",
            "20261002",
            "--profile",
            "livelike",
            "--features",
            str(ROOT / "data/samples/features_pump_path_a_livelike_MISSING.csv"),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "REFUSE" in proc.stdout or "go-card" in proc.stdout.lower() or "GO_CARD" in proc.stdout
    combined = proc.stdout + proc.stderr
    assert "missing_--go-card" in combined or "requires a filled GO_CARD" in combined


def test_train_refuses_nogo_card_before_missing_features():
    proc = subprocess.run(
        [
            PY,
            str(CANON),
            "--stamp",
            "20261002",
            "--go-card",
            str(FIXTURES / "nogo_verdict.md"),
            "--features",
            str(ROOT / "data/samples/features_pump_path_a_livelike_MISSING.csv"),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "verdict_is_NO-GO" in proc.stdout or "NO-GO" in proc.stdout


def test_train_dry_path_check_still_ok_without_go_card():
    proc = subprocess.run(
        [PY, str(CANON), "--stamp", "20261002", "--dry-path-check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok_path_check"
    assert payload.get("go_card_required_for_train") is True


def test_train_accepts_valid_go_card_then_missing_features():
    """Valid card → gate PASS; then missing features returns 1 (not gate 2)."""
    proc = subprocess.run(
        [
            PY,
            str(CANON),
            "--stamp",
            "20990101",
            "--profile",
            "livelike",
            "--go-card",
            str(FIXTURES / "valid_train_go.md"),
            "--features",
            str(ROOT / "data/samples/features_pump_path_a_livelike_DOES_NOT_EXIST.csv"),
            "--no-usable-only",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "missing_features" in proc.stdout


def test_refuse_overwrite_yes_in_card():
    mod = _load_check()
    bad = FIXTURES / "_tmp_overwrite_yes.md"
    bad.write_text(
        """```go_card
action: train
go_criterion_ref: cycle0/go-criterion-q5b-candidate-vs-last-20261002.md
cost_fence: 0 Dune
api_spend: none
overwrite_q5b_last: YES
paper_restart: NO
protocolos_ack: V4
verdict: GO
```
""",
        encoding="utf-8",
    )
    try:
        report = mod.validate_go_card(bad)
        assert report["ok"] is False
        assert any("overwrite_q5b_last" in e for e in report["errors"])
    finally:
        bad.unlink(missing_ok=True)
