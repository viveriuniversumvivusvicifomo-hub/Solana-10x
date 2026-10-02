#!/usr/bin/env python3
"""D-02 GO-before-coding gate — validate a filled GO_CARD before Path A train/build/HTTP scale.

Process: cycle0/go-before-coding-gate-20261002.md
Template: cycle0/templates/GO_CARD.md
Criterion: cycle0/go-criterion-q5b-candidate-vs-last-20261002.md
Protocols: cycle0/protocolos-verificacion.md

Exit codes:
  0 — card PASS (verdict GO + all required fields)
  2 — REFUSE (missing card, incomplete fields, NO-GO, would overwrite / restart without Sinck)

CLI:
  python scripts/check_go_gate.py --go-card path/to/card.md
  python -c "from check_go_gate import validate_go_card; ..."
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_KEYS = (
    "action",
    "go_criterion_ref",
    "cost_fence",
    "api_spend",
    "overwrite_q5b_last",
    "paper_restart",
    "protocolos_ack",
    "verdict",
)

ALLOWED_ACTIONS = frozenset({"train", "build", "http_scale"})
PLACEHOLDER_RE = re.compile(r"^(TODO|TBD|FILL|FIXME|XXX|<.+>|\{.+\})$", re.I)
GO_CRITERION_NEEDLE = "go-criterion-q5b-candidate-vs-last"
SINCK_OK_RE = re.compile(r"sinck\s*(:|\s+)?\s*ok", re.I)
BLOCK_RE = re.compile(
    r"```go_card\s*\n(?P<body>.*?)```",
    re.IGNORECASE | re.DOTALL,
)
KV_RE = re.compile(r"^([A-Za-z0-9_]+)\s*:\s*(.+?)\s*$")


def _is_placeholder(value: str) -> bool:
    v = value.strip()
    if not v:
        return True
    if PLACEHOLDER_RE.match(v):
        return True
    # bare FILL- with instruction leftovers
    if v.upper().startswith("FILL"):
        return True
    return False


def parse_go_card(text: str) -> dict[str, str]:
    """Extract key:value pairs from the first ```go_card fence."""
    m = BLOCK_RE.search(text)
    if not m:
        raise ValueError("missing_go_card_fence")
    fields: dict[str, str] = {}
    for line in m.group("body").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        km = KV_RE.match(line)
        if not km:
            continue
        fields[km.group(1).strip().lower()] = km.group(2).strip()
    return fields


def validate_go_card(
    path: Path | str,
    *,
    expect_action: str | None = None,
) -> dict[str, Any]:
    """Validate a GO_CARD file. Returns a report dict; ok=True iff PASS."""
    p = Path(path)
    report: dict[str, Any] = {
        "status": "REFUSE",
        "ok": False,
        "path": str(p),
        "errors": [],
        "fields": {},
        "gate": "D-02-go-before-coding",
        "docs": {
            "process": "cycle0/go-before-coding-gate-20261002.md",
            "template": "cycle0/templates/GO_CARD.md",
            "criterion": "cycle0/go-criterion-q5b-candidate-vs-last-20261002.md",
            "protocolos": "cycle0/protocolos-verificacion.md",
        },
    }
    if not p.is_file():
        report["errors"].append(f"go_card_not_found:{p}")
        return report
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        report["errors"].append(f"go_card_read_error:{exc}")
        return report
    try:
        fields = parse_go_card(text)
    except ValueError as exc:
        report["errors"].append(str(exc))
        return report
    report["fields"] = fields

    for key in REQUIRED_KEYS:
        if key not in fields:
            report["errors"].append(f"missing_field:{key}")
            continue
        if _is_placeholder(fields[key]):
            report["errors"].append(f"placeholder_or_empty:{key}")

    action = fields.get("action", "").strip().lower()
    if action and action not in ALLOWED_ACTIONS:
        report["errors"].append(f"bad_action:{action}")
    if expect_action and action and action != expect_action.strip().lower():
        report["errors"].append(
            f"action_mismatch:expected_{expect_action}_got_{action}"
        )

    crit = fields.get("go_criterion_ref", "")
    if crit:
        crit_norm = re.sub(r"[\s_]+", "-", crit.lower())
        if GO_CRITERION_NEEDLE not in crit_norm:
            report["errors"].append("go_criterion_ref_must_cite_q5b_candidate_vs_last")

    overwrite = fields.get("overwrite_q5b_last", "").strip().upper()
    if overwrite and overwrite not in ("NO", "N", "FALSE", "0"):
        report["errors"].append("overwrite_q5b_last_must_be_NO")

    paper = fields.get("paper_restart", "").strip()
    if paper:
        paper_u = paper.upper()
        if paper_u not in ("NO", "N", "FALSE", "0") and not SINCK_OK_RE.search(paper):
            report["errors"].append("paper_restart_requires_NO_or_Sinck_OK")

    api = fields.get("api_spend", "").strip()
    if api:
        api_l = api.lower()
        if api_l not in ("none", "no", "0", "n/a", "na") and not SINCK_OK_RE.search(api):
            report["errors"].append("api_spend_requires_none_or_Sinck_OK")

    verdict = fields.get("verdict", "").strip().upper()
    if verdict and verdict not in ("GO", "NO-GO", "NOGO", "NO_GO"):
        report["errors"].append(f"bad_verdict:{fields.get('verdict')}")
    if verdict in ("NO-GO", "NOGO", "NO_GO"):
        report["errors"].append("verdict_is_NO-GO")
    elif verdict and verdict != "GO":
        report["errors"].append("verdict_must_be_GO")

    if report["errors"]:
        report["message"] = (
            "REFUSE: GO_CARD incomplete or NO-GO. "
            "Fill cycle0/templates/GO_CARD.md → pass --go-card. "
            "See cycle0/go-before-coding-gate-20261002.md."
        )
        return report

    report["status"] = "PASS"
    report["ok"] = True
    report["message"] = "GO_CARD PASS — proceed under cost fence + no q5b_last overwrite"
    return report


def refuse_unless_go_card(
    path: Path | str | None,
    *,
    expect_action: str | None = "train",
    print_json: bool = True,
) -> int | None:
    """Return exit code 2 if card missing/invalid; else None (caller continues)."""
    if path is None:
        payload = {
            "status": "REFUSE",
            "ok": False,
            "reason": "missing_--go-card",
            "message": (
                "REFUSE: Path A train/build/HTTP scale requires a filled GO_CARD. "
                "Copy cycle0/templates/GO_CARD.md, set verdict: GO, pass --go-card PATH. "
                "Process: cycle0/go-before-coding-gate-20261002.md (D-02)."
            ),
            "gate": "D-02-go-before-coding",
        }
        if print_json:
            print(json.dumps(payload, indent=2))
        return 2
    report = validate_go_card(path, expect_action=expect_action)
    if print_json:
        print(json.dumps(report, indent=2))
    return None if report["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--go-card",
        type=Path,
        required=True,
        help="Path to filled GO_CARD.md (must contain ```go_card fence)",
    )
    ap.add_argument(
        "--expect-action",
        choices=sorted(ALLOWED_ACTIONS),
        default=None,
        help="Optional: require action= train|build|http_scale",
    )
    args = ap.parse_args(argv)
    report = validate_go_card(args.go_card, expect_action=args.expect_action)
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
