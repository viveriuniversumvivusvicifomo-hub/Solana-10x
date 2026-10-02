#!/usr/bin/env python3
"""Offline Q4→Q5a buy_vol hygiene for local parity CSVs (no Dune credits).

When Q4 buy_count_60s ≠ Q5a buy_count_total (or |vol ratio−1| > 1%), rewrite
buy_vol_usd_60s / buy_count_60s from Q5a buy_vol_usd_total / buy_count_total.
Also patches buy_vol_usd_5m / buy_count_5m the same way when those windows
equal the 60s window on short-lived mints (optional; default: 60s only).

Authoritative policy:
  cycle0/diagnostics/usd-q4-q5a-parity-anchor-20261001.md

Default ge10 overlay:
  data/samples/features_buy_vol_q5a_overlay_ge10_20261001.csv

Does NOT call Dune. Does NOT touch paper_live.
"""
from __future__ import annotations

import argparse
import csv
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OVERLAY = ROOT / "data/samples/features_buy_vol_q5a_overlay_ge10_20261001.csv"
DEFAULT_TARGETS = [
    ROOT / "data/samples/dune_q4_flow_expand_v2.csv",
    ROOT / "data/samples/features_dune_p0_flow_expand_v2.csv",
    ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv",
]


def load_overlay(path: Path) -> dict[str, dict[str, str]]:
    with path.open(newline="") as f:
        return {r["mint"].strip(): r for r in csv.DictReader(f) if r.get("mint")}


def patch_csv(
    path: Path,
    overlay: dict[str, dict[str, str]],
    *,
    only_flagged: bool,
    dry_run: bool,
    patch_5m: bool,
) -> dict[str, int]:
    if not path.exists():
        return {"missing": 1}

    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    vol_col = "buy_vol_usd_60s"
    cnt_col = "buy_count_60s"
    if vol_col not in fieldnames:
        return {"skipped_no_col": 1}

    n_touch = 0
    for row in rows:
        mint = (row.get("mint") or "").strip()
        ov = overlay.get(mint)
        if not ov:
            continue
        if only_flagged and ov.get("use_q5a_for_parity") != "1":
            continue
        new_vol = ov["buy_vol_usd_q5a"]
        new_cnt = ov["buy_count_q5a"]
        if row.get(vol_col) != new_vol or (cnt_col in fieldnames and row.get(cnt_col) != new_cnt):
            row[vol_col] = new_vol
            if cnt_col in fieldnames:
                row[cnt_col] = new_cnt
            if patch_5m:
                if "buy_vol_usd_5m" in fieldnames:
                    row["buy_vol_usd_5m"] = new_vol
                if "buy_count_5m" in fieldnames:
                    row["buy_count_5m"] = new_cnt
            n_touch += 1

    stats = {"rows": len(rows), "patched": n_touch, "path": str(path)}
    if dry_run or n_touch == 0:
        return stats

    bak = path.with_suffix(path.suffix + f".bak_pre_q5a_{datetime.now(timezone.utc).strftime('%Y%m%d')}")
    if not bak.exists():
        shutil.copy2(path, bak)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    stats["backup"] = str(bak)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--overlay", type=Path, default=DEFAULT_OVERLAY)
    ap.add_argument(
        "--targets",
        type=Path,
        nargs="*",
        default=DEFAULT_TARGETS,
        help="Local CSVs whose buy_vol_usd_60s should be overlaid from Q5a",
    )
    ap.add_argument(
        "--all-overlay-mints",
        action="store_true",
        help="Patch every mint in overlay (default: only use_q5a_for_parity=1)",
    )
    ap.add_argument("--patch-5m", action="store_true", help="Also overwrite 5m buy_* from Q5a")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true", help="Write changes (default is dry-run)")
    args = ap.parse_args()

    dry = not args.apply
    if args.dry_run:
        dry = True

    overlay = load_overlay(args.overlay)
    print(f"overlay={args.overlay} mints={len(overlay)} dry_run={dry}")
    only_flagged = not args.all_overlay_mints
    for t in args.targets:
        st = patch_csv(
            t,
            overlay,
            only_flagged=only_flagged,
            dry_run=dry,
            patch_5m=args.patch_5m,
        )
        print(st)
    if dry:
        print("dry-run only; pass --apply to write (creates .bak_pre_q5a_YYYYMMDD once)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
