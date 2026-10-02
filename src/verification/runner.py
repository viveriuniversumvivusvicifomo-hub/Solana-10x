"""Runner: ejecuta gates implementadas y reporta JSON por run_id."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from verification.checklist import ALL_ITEMS, checklist_summary
from verification.capture_v1 import assert_oracle_frozen
from verification.sample_join_v2 import audit_bitquery_candidate_sample, audit_enriched_capture_sample
from verification.secrets import assert_bitquery_sample_auth_redacted, assert_no_secret_leakage
from verification.dry_v5 import assert_constants_module, assert_mc_single_impl, assert_no_denylist_dupes
from verification.errors import VerificationError


@dataclass
class GateResult:
    name: str
    protocol: str
    ok: bool
    detail: str = ""


def _run(name: str, protocol: str, fn: Callable[[], None]) -> GateResult:
    try:
        fn()
        return GateResult(name=name, protocol=protocol, ok=True)
    except VerificationError as exc:
        return GateResult(name=name, protocol=protocol, ok=False, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — reportar cualquier fallo de gate
        return GateResult(name=name, protocol=protocol, ok=False, detail=f"unexpected: {exc!r}")


def run_static_gates() -> list[GateResult]:
    """Gates que no necesitan fixtures ni datos live."""
    return [
        _run("V5.constants_module", "V5", assert_constants_module),
        _run("V5.mc_single_impl", "V5", assert_mc_single_impl),
        _run("V5.denylist", "V5", lambda: assert_no_denylist_dupes() and None),
        _run("V1.oracle_pyth", "V1", assert_oracle_frozen),
        _run("V5.secrets_no_leak", "V5", lambda: assert_no_secret_leakage() and None),
        _run("V5.bitquery_auth_redacted", "V5", assert_bitquery_sample_auth_redacted),
        _run("V2.first_join_sample", "V2", lambda: audit_bitquery_candidate_sample() and None),
        _run("V2.enriched_lookahead", "V2", lambda: audit_enriched_capture_sample() and None),
    ]


def build_report(*, run_id: str, gates: list[GateResult] | None = None) -> dict[str, Any]:
    results = gates if gates is not None else run_static_gates()
    failed = [asdict(g) for g in results if not g.ok]
    return {
        "run_id": run_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "checklist_summary": checklist_summary(),
        "checklist_n": len(ALL_ITEMS),
        "gates": [asdict(g) for g in results],
        "ok": len(failed) == 0,
        "failed": failed,
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    run_id = "local"
    out_path: Path | None = None
    i = 0
    while i < len(argv):
        if argv[i] == "--run-id" and i + 1 < len(argv):
            run_id = argv[i + 1]
            i += 2
        elif argv[i] == "--out" and i + 1 < len(argv):
            out_path = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    report = build_report(run_id=run_id)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
