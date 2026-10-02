"""V5 — DRY: una sola impl de MC, constantes, denylist de nombres."""

from __future__ import annotations

import ast
from pathlib import Path

from verification.errors import DryError

# Raíz del repo relativa a este archivo: src/verification/dry_v5.py → ../..
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "src"

ALLOWED_MC_FILE = _SRC / "capture" / "math.py"
CONSTANTS_FILE = _SRC / "ingestion" / "pump_constants.py"

# Nombres prohibidos fuera de capture/math.py
DENYLIST_FUNCS: frozenset[str] = frozenset(
    {
        "compute_market_cap",
        "bonding_curve_price",
        "market_cap_usd",  # solo permitido en capture/math.py
        "mc_usd",
    }
)


def assert_constants_module() -> None:
    if not CONSTANTS_FILE.is_file():
        raise DryError(f"falta módulo único de constantes: {CONSTANTS_FILE}")


def assert_mc_single_impl() -> None:
    if not ALLOWED_MC_FILE.is_file():
        raise DryError(f"falta implementación canónica MC: {ALLOWED_MC_FILE}")
    # market_cap_usd debe existir ahí
    text = ALLOWED_MC_FILE.read_text(encoding="utf-8")
    if "def market_cap_usd" not in text:
        raise DryError("capture/math.py no define market_cap_usd")


def _iter_py_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*.py") if p.is_file() and "__pycache__" not in p.parts]


def assert_no_denylist_dupes(*, src_root: Path | None = None) -> list[str]:
    """Falla si funciones denylist aparecen fuera de capture/math.py.

    Returns lista vacía si OK (útil para tests).
    """
    root = src_root or _SRC
    allowed = ALLOWED_MC_FILE.resolve()
    offenders: list[str] = []
    for path in _iter_py_files(root):
        if path.resolve() == allowed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            raise DryError(f"syntax error en {path}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in DENYLIST_FUNCS:
                offenders.append(f"{path.relative_to(root)}:{node.lineno} def {node.name}")
    if offenders:
        raise DryError("funciones duplicadas / denylist fuera de capture/math.py: " + ", ".join(offenders))
    return offenders
