"""Gate no-fuga de secrets (Helius / Bitquery / genéricos).

Escanea el árbol del repo (src, tests, cycle0, data) buscando tokens
pegados, headers Authorization con valor real, o .env tracked.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from verification.errors import VerificationError

_REPO = Path(__file__).resolve().parents[2]

# Placeholders permitidos en docs / meta de samples
_ALLOWED_PLACEHOLDERS = (
    "<BITQUERY_TOKEN>",
    "<HELIUS_API_KEY>",
    "Bearer <BITQUERY_TOKEN>",
    "YOUR_API_KEY",
)

# Patrones de fuga (valores reales, no nombres de env)
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "bearer_token",
        re.compile(r"(?i)Authorization\s*[:=]\s*Bearer\s+(?!<BITQUERY_TOKEN>)([A-Za-z0-9._\-]{16,})"),
    ),
    (
        "helius_url_key",
        re.compile(r"helius-rpc\.com/\?api-key=([A-Za-z0-9_\-]{16,})"),
    ),
    (
        "env_assignment",
        re.compile(
            r"(?im)^(?:export\s+)?(?:HELIUS_API_KEY|BITQUERY_TOKEN|BIRDEYE_API_KEY|JUPITER_API_KEY)\s*=\s*['\"]?([^\s'\"]{8,})"
        ),
    ),
    (
        "jwt_like",
        re.compile(r"\beyJ[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),
    ),
)

_SKIP_DIR_NAMES = {".venv", "__pycache__", ".git", "egg-info", "node_modules", ".pytest_cache"}
_SCAN_ROOTS = ("src", "tests", "cycle0", "data")
_TEXT_SUFFIXES = {".py", ".md", ".json", ".yml", ".yaml", ".toml", ".txt", ".env", ".example", ".csv"}


class SecretsLeakError(VerificationError):
    def __init__(self, message: str) -> None:
        super().__init__("SECRETS", message)


def _iter_files(roots: Iterable[Path]) -> list[Path]:
    out: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            out.append(root)
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIR_NAMES or part.endswith(".egg-info") for part in p.parts):
                continue
            if p.suffix.lower() in _TEXT_SUFFIXES or p.name in {".env", ".env.example"}:
                out.append(p)
    return out


def _is_placeholder_match(text: str, start: int, end: int) -> bool:
    window = text[max(0, start - 40) : end + 40]
    return any(ph in window for ph in _ALLOWED_PLACEHOLDERS)


def scan_text_for_secrets(text: str, *, path: str = "<memory>") -> list[str]:
    hits: list[str] = []
    for name, pat in _PATTERNS:
        for m in pat.finditer(text):
            if _is_placeholder_match(text, m.start(), m.end()):
                continue
            # env_assignment: allow empty / placeholder values
            if name == "env_assignment":
                val = m.group(1)
                if val.startswith("<") or val in {"changeme", "xxx", "TODO"}:
                    continue
            hits.append(f"{path}:{name}:{m.group(0)[:48]}")
    return hits


def assert_no_secret_leakage(
    *,
    repo_root: Path | None = None,
    extra_paths: Iterable[Path] | None = None,
) -> dict[str, int]:
    """Falla si encuentra secretos reales fuera de .env (que debe estar gitignored)."""
    root = repo_root or _REPO
    roots = [root / r for r in _SCAN_ROOTS]
    if extra_paths:
        roots.extend(extra_paths)

    # .env en disco OK si gitignored; nunca debe estar bajo src/cycle0/tests committed content
    env_path = root / ".env"
    gitignore = root / ".gitignore"
    if env_path.is_file():
        gi = gitignore.read_text(encoding="utf-8") if gitignore.is_file() else ""
        if ".env" not in gi:
            raise SecretsLeakError(".env existe pero no está en .gitignore")

    hits: list[str] = []
    n_files = 0
    for path in _iter_files(roots):
        # No escanear el contenido de .env (sí exigir gitignore)
        if path.name == ".env" or path.name.startswith(".env."):
            if path.name == ".env.example":
                pass
            else:
                continue
        n_files += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
        hits.extend(scan_text_for_secrets(text, path=rel))

    if hits:
        raise SecretsLeakError("posible fuga de secrets: " + "; ".join(hits[:20]))
    return {"files_scanned": n_files, "hits": 0}


def assert_bitquery_sample_auth_redacted(sample_path: Path | None = None) -> None:
    """Meta del sample debe documentar Bearer como placeholder, nunca token real."""
    path = sample_path or (_REPO / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json")
    if not path.is_file():
        raise SecretsLeakError(f"sample Bitquery ausente: {path}")
    text = path.read_text(encoding="utf-8")
    if "Bearer <BITQUERY_TOKEN>" not in text and "<BITQUERY_TOKEN>" not in text:
        # Si no menciona auth, OK; si menciona Bearer con valor real, falla vía scan
        pass
    hits = scan_text_for_secrets(text, path=str(path))
    if hits:
        raise SecretsLeakError("sample Bitquery con secret: " + "; ".join(hits))
