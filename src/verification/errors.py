"""Errores de verificación — fallos de look-ahead / leakage bloquean train."""

from __future__ import annotations


class VerificationError(Exception):
    """Fallo genérico de un protocolo V1–V8."""

    def __init__(self, protocol: str, message: str) -> None:
        self.protocol = protocol
        super().__init__(f"[{protocol}] {message}")


class LookAheadError(VerificationError):
    """Dato o join con timestamp/slot > T0."""

    def __init__(self, message: str) -> None:
        super().__init__("V2", message)


class LeakageError(VerificationError):
    """Columna label en features / merge indebido."""

    def __init__(self, message: str) -> None:
        super().__init__("V3", message)


class CaptureSchemaError(VerificationError):
    def __init__(self, message: str) -> None:
        super().__init__("V1", message)


class WalkForwardError(VerificationError):
    def __init__(self, message: str) -> None:
        super().__init__("V4", message)


class DryError(VerificationError):
    def __init__(self, message: str) -> None:
        super().__init__("V5", message)


class ReproError(VerificationError):
    def __init__(self, message: str) -> None:
        super().__init__("V7", message)
