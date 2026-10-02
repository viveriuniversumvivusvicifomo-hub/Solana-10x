"""Helius Parsed Streams / webhooks — stub.

Streams consumen créditos de forma continua. No activar hasta presupuesto Sinck OK.
API de wire prevista: ``start_pump_trade_stream(handler)`` filtrando program Pump.
"""

from __future__ import annotations

STREAMS_ENABLED = False


def assert_streams_allowed() -> None:
    if not STREAMS_ENABLED:
        raise RuntimeError(
            "Helius streams desactivados (STREAMS_ENABLED=False). "
            "Activar solo con OK de presupuesto Sinck."
        )


def start_pump_trade_stream(*_args, **_kwargs):  # noqa: ANN001
    assert_streams_allowed()
    raise NotImplementedError("Cycle 1+: Parsed Streams wire pendiente")
