#!/usr/bin/env python3
"""Offline: % of mints with dune_cohort exact meta in local prior index (no Dune)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mints-json", type=Path, help="JSON list of mints or {rows:[{mint:}]}")
    ap.add_argument("--sample", type=Path, default=ROOT / "data/samples/pump_frontend_mc_8k_20k_sample.json")
    ap.add_argument("-o", type=Path, default=ROOT / "cycle0/artifacts/pump_prior_coverage.json")
    args = ap.parse_args()
    from paper_live.creator_priors import load_creator_prior_index

    mints: list[str] = []
    src = args.mints_json or args.sample
    data = json.loads(src.read_text())
    if isinstance(data, list):
        mints = [str(x if isinstance(x, str) else x.get("mint")) for x in data]
    else:
        rows = data.get("rows") or data.get("mints") or []
        mints = [str(r.get("mint") if isinstance(r, dict) else r) for r in rows]
    mints = [m for m in mints if m and m != "None"]
    idx = load_creator_prior_index()
    n_hit = 0
    for m in mints:
        meta = idx.exact_meta_for_mint(m) if hasattr(idx, "exact_meta_for_mint") else None
        if meta:
            n_hit += 1
    out = {
        "n": len(mints),
        "n_exact_meta": n_hit,
        "frac": (n_hit / len(mints)) if mints else None,
        "source": str(src),
        "dune_calls": 0,
    }
    args.o.parent.mkdir(parents=True, exist_ok=True)
    args.o.write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
