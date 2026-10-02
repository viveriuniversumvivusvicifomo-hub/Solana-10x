"""V6 — golden path E2E offline (stub Cycle 0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from verification.errors import VerificationError

_FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "captures"


def run_golden_e2e(*, fixture_dir: Path | None = None) -> dict[str, Any]:
    """Corre pipeline offline contra fixtures.

    Cycle 0: verifica que el directorio de fixtures existe; pipeline real en C1.
    """
    d = fixture_dir or _FIXTURES
    if not d.is_dir():
        raise VerificationError("V6", f"falta directorio fixtures: {d}")
    # Placeholder: cuando haya tar/golden JSON, comparar aquí.
    return {
        "status": "stub",
        "fixture_dir": str(d),
        "message": "E2E golden pendiente de fixtures reales (Cycle 1)",
    }
