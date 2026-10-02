"""V8 — monitoreo live (stubs; requiere connector Cycle 1+)."""

from __future__ import annotations

from typing import Any


def check_live_alerts(metrics: dict[str, Any] | None = None) -> dict[str, Any]:
    """Evalúa reglas V8 cuando existan métricas live.

    Cycle 0: no-op documentado.
    """
    return {
        "status": "stub",
        "metrics": metrics or {},
        "alerts": [],
        "message": "Monitoreo live diferido a connector (Cycle 1+)",
    }
