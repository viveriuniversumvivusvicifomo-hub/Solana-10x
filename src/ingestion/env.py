"""Carga de secretos de proyecto. Nunca loguear valores."""

from __future__ import annotations

import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _ROOT / ".env"


def load_dotenv(path: Path | None = None) -> None:
    """Carga KEY=VALUE de .env al entorno si la key aún no está definida."""
    env_path = path or _ENV_FILE
    if not env_path.is_file():
        return
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def require_helius_api_key() -> str:
    load_dotenv()
    key = os.environ.get("HELIUS_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "HELIUS_API_KEY ausente. Ponla en el entorno o en /workspace/solana-10x/.env"
        )
    return key


def require_bitquery_token() -> str:
    load_dotenv()
    import os
    key = os.environ.get("BITQUERY_TOKEN", "").strip()
    if not key:
        raise RuntimeError(
            "BITQUERY_TOKEN ausente. Ponla en el entorno o en /workspace/solana-10x/.env"
        )
    return key
