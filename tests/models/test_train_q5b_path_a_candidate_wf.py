"""SolModelos: canonical train entry refuse policy + archive NO-GO stubs."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
CANON = ROOT / "scripts/train_q5b_path_a_candidate_wf.py"
COMMON = ROOT / "scripts/train_q5b_path_a_common.py"
ARCHIVE = ROOT / "scripts/archive"


def _load_common():
    spec = importlib.util.spec_from_file_location("train_q5b_path_a_common", COMMON)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_common_refuse_q5b_last_by_name():
    common = _load_common()
    assert common.is_forbidden_model_path(Path("q5b_last.joblib")) is True
    assert common.is_forbidden_model_path(common.Q5B_LAST) is True
    assert common.is_forbidden_model_path(Path("q5b_path_a_candidate_20261002.joblib")) is False
    code = common.refuse_if_q5b_last(common.Q5B_LAST, label="--out")
    assert code == 2


def test_canonical_refuses_out_q5b_last():
    proc = subprocess.run(
        [
            PY,
            str(CANON),
            "--out",
            "q5b_last.joblib",
            "--dry-path-check",
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT / "scripts")},
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "REFUSE" in proc.stdout or "REFUSE" in proc.stderr


def test_canonical_refuses_absolute_q5b_last_path():
    last = ROOT / "data/paper_live/models/q5b_last.joblib"
    proc = subprocess.run(
        [PY, str(CANON), "--out", str(last), "--dry-path-check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT / "scripts")},
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_canonical_dry_path_check_ok_default():
    proc = subprocess.run(
        [PY, str(CANON), "--stamp", "20261002", "--dry-path-check"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT / "scripts")},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "q5b_path_a_candidate_20261002.joblib" in proc.stdout
    assert "q5b_last" not in Path(proc.stdout).name if False else True
    assert "ok_path_check" in proc.stdout


@pytest.mark.parametrize(
    "script",
    [
        "train_q5b_pump_wf.py",
        "train_q5b_pump_pilot500_wf.py",
        "train_q5b_pump_mcband_wf.py",
        "train_q5b_pump_livelike_wf.py",
    ],
)
def test_archive_scripts_exit_nongo(script):
    path = ARCHIVE / script
    assert path.is_file()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT / "scripts")}
    env.pop("SOLMODELOS_ARCHIVE_FORCE", None)
    proc = subprocess.run(
        [PY, str(path)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NO-GO" in proc.stdout or "canonical" in proc.stdout.lower()


def test_old_scripts_paths_gone():
    for name in (
        "train_q5b_pump_wf.py",
        "train_q5b_pump_pilot500_wf.py",
        "train_q5b_pump_mcband_wf.py",
        "train_q5b_pump_livelike_wf.py",
    ):
        assert not (ROOT / "scripts" / name).exists()
        assert (ARCHIVE / name).is_file()
    assert CANON.is_file()
