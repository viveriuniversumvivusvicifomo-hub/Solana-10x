"""V7 — reproducibilidad: seed, versiones en artefacto, repro_check CLI stub."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from verification.errors import ReproError


def assert_seed_set(seed: int | None) -> None:
    if seed is None:
        raise ReproError("SEED no fijado")


def assert_artifact_versions(artifact: Mapping[str, Any]) -> None:
    required = ("definition_version", "feature_set_version", "code_git_sha")
    missing = [k for k in required if not artifact.get(k)]
    if missing:
        raise ReproError(f"artefacto sin versiones: {missing}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def repro_check(*, run_id: str, manifest_path: Path | None = None) -> dict[str, Any]:
    """python -m verification.repro_check --run-id ...

    Cycle 0: requiere manifest opcional; sin él devuelve stub OK estructural.
    """
    if not run_id:
        raise ReproError("run_id vacío")
    result: dict[str, Any] = {"run_id": run_id, "status": "ok", "checks": []}
    if manifest_path is None:
        result["status"] = "stub"
        result["checks"].append({"name": "manifest", "status": "skipped", "detail": "sin manifest"})
        return result
    if not manifest_path.is_file():
        raise ReproError(f"manifest no encontrado: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert_artifact_versions(manifest) if all(
        k in manifest for k in ("definition_version", "feature_set_version", "code_git_sha")
    ) else None
    # Si hay lista de archivos con hash esperado, verificar
    files = manifest.get("files") or []
    for entry in files:
        path = Path(entry["path"])
        expected = entry["sha256"]
        if not path.is_file():
            raise ReproError(f"archivo del manifest ausente: {path}")
        actual = sha256_file(path)
        if actual != expected:
            raise ReproError(f"hash mismatch {path}: {actual} != {expected}")
        result["checks"].append({"name": str(path), "status": "ok"})
    return result
