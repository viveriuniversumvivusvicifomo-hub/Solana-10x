#!/usr/bin/env python3
"""Canonical Path A Pump data-pipeline entrypoint (thin dispatcher).

Recipes
-------
  inventory   — list trade caches + matrix completeness for a stamp
  livelike    — train matrix with live-like geometry (CANONICAL train rebuild)
  mcband      — MC-band T0 rebase pilot (historical; kept)
  pilot500    — expand_t0_ts GO-1 pilot (historical; kept)
  offline     — journal/smoke features (0 HTTP or capped smoke)
  scale       — ORPHAN incomplete; refuse by default (use --force-orphan)

Never: Dune API · paper_live restart · overwrite q5b_last · USD 6.6× scale.
"""
from __future__ import annotations

import argparse
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from pump_path_a_common import (  # noqa: E402
    assert_usd_scale_off,
    cache_inventory,
    path_a_invariants,
)

RECIPES = {
    "livelike": "build_pump_path_a_livelike.py",
    "mcband": "build_pump_mcband_pilot.py",
    "pilot500": "build_pump_path_a_pilot500.py",
    "offline": "build_pump_true_features_offline.py",
    "scale": "build_pump_mcband_scale.py",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "recipe",
        choices=["inventory", *RECIPES.keys()],
        help="Pipeline recipe or inventory",
    )
    ap.add_argument("--stamp", default="20261002")
    ap.add_argument(
        "--force-orphan",
        action="store_true",
        help="Allow dispatching ORPHAN scale recipe",
    )
    ap.add_argument(
        "recipe_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded to underlying script (prefix with --)",
    )
    args = ap.parse_args(argv)

    assert_usd_scale_off()
    inv = path_a_invariants()

    if args.recipe == "inventory":
        doc = {
            "invariants": inv,
            "inventory": cache_inventory(args.stamp),
        }
        print(json.dumps(doc, indent=2))
        return 0

    if args.recipe == "scale" and not args.force_orphan:
        print(
            json.dumps(
                {
                    "status": "refused_orphan",
                    "orphan": inv["orphan_scripts"]["build_pump_mcband_scale.py"],
                    "hint": "use recipe=livelike; scale quarantined at archive/quarantine/mcband_scale_20261002; --force-orphan only for forensic legacy",
                },
                indent=2,
            )
        )
        return 2

    script = ROOT / "scripts" / RECIPES[args.recipe]
    fwd = list(args.recipe_args)
    if fwd and fwd[0] == "--":
        fwd = fwd[1:]
    sys.argv = [str(script), *fwd]
    runpy.run_path(str(script), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
