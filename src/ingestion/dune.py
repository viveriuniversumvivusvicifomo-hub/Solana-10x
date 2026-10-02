"""Cliente Dune Analytics (free/API). Sin secrets en logs ni samples.

Auth: header X-Dune-API-Key desde env DUNE_API_KEY (.env).
Streams Helius: OFF (otro módulo).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from ingestion.env import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
API = "https://api.dune.com/api/v1"


class DuneQuotaOrAuth(RuntimeError):
    pass


def require_dune_api_key() -> str:
    load_dotenv()
    key = (os.environ.get("DUNE_API_KEY") or "").strip()
    if not key:
        raise DuneQuotaOrAuth("DUNE_API_KEY missing — UI login or set in .env")
    return key


class DuneClient:
    def __init__(self, api_key: str | None = None, *, timeout_s: float = 120.0) -> None:
        self._key = api_key or require_dune_api_key()
        self._http = httpx.Client(
            timeout=timeout_s,
            headers={"X-Dune-API-Key": self._key, "Content-Type": "application/json"},
        )

    def close(self) -> None:
        self._http.close()

    def execute_sql(self, sql: str, *, performance: str = "medium") -> dict[str, Any]:
        """Create + execute a raw SQL query (Dune API v1). May consume free credits."""
        r = self._http.post(f"{API}/sql/execute", json={"sql": sql, "performance": performance})
        if r.status_code in (401, 403, 402, 429):
            raise DuneQuotaOrAuth(f"Dune HTTP {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()

    def get_execution(self, execution_id: str) -> dict[str, Any]:
        r = self._http.get(f"{API}/execution/{execution_id}/results")
        if r.status_code in (401, 403, 402, 429):
            raise DuneQuotaOrAuth(f"Dune HTTP {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()

    def wait_results(self, execution_id: str, *, max_wait_s: float = 900.0, poll_s: float = 5.0) -> dict[str, Any]:
        t0 = time.time()
        while True:
            body = self.get_execution(execution_id)
            state = (body.get("state") or body.get("execution_status") or "").upper()
            if "COMPLETED" in state or body.get("result"):
                return body
            if "FAIL" in state or "CANCEL" in state or "ERROR" in state:
                raise RuntimeError(f"Dune execution failed: {json.dumps(body)[:500]}")
            if time.time() - t0 > max_wait_s:
                raise TimeoutError(f"Dune execution {execution_id} exceeded {max_wait_s}s")
            time.sleep(poll_s)
