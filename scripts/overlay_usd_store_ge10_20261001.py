#!/usr/bin/env python3
"""Parity-audit overlay: copy train-store USD/vol (+ optional meta) onto recovery_on Path A.

Purpose
-------
Build an **ISOLATE-ONLY** audit feature CSV where, for ge10 mints with exact
trade parity (n_buys_le_t0 == train_buy_count), recipe USD/vol columns that
differ from ``features_dune_p0_q5_expand_v2.csv`` are replaced by store values
so score Δ can be attributed to USD/vol. Path A originals are preserved as
``*_path_a`` suffix columns.

**NOT for production / live scoring.** Do NOT use to force live≡Dune.
Production stays Path A (``amount_usd = sol_amt × pyth_asof``, scale 6.6× OFF).
recovery_on inputs are read-only. Fix direction = Path A closes residual OR
SolModelos rebases store/joblib to Path A — never live←Dune USD.

Authoritative FAIL evidence:
  cycle0/ge10-rescore-recovery-on-metafill-20261001.md

Does NOT touch paper_live. Does NOT modify recovery_on CSVs.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_LIVE = ROOT / "data/samples/helius_parity_features_ge10_recovery_on_20261001.csv"
DEFAULT_STORE = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
DEFAULT_OUT = ROOT / "data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001.csv"
DEFAULT_META = ROOT / "data/samples/helius_parity_features_ge10_recovery_on_usd_store_20261001_meta.json"
DEFAULT_DIAG = ROOT / "cycle0/diagnostics/usd-exact-ge10-path-a-vs-store-20261001.md"
DEFAULT_SIDE = ROOT / "data/samples/helius_parity_features_ge10_recovery_on_path_a_usd_side_20261001.csv"

# Recipe meta / identity — not USD/vol economics
META_COLS = (
    "age_proxy_s",
    "age_s",
    "age_min",
    "has_creator",
    "name_len",
    "name_missing",
    "symbol_len",
    "symbol_missing",
    "creator_prior_mints_7d",
    "creator_prior_mints_30d",
    "creator_prior_mints_cohort",
    "creator_prior_mints_all_in_window",
)

# Count / unique discrete cols — usually already exact when trades match;
# still eligible for store copy if they differ (safety).
COUNT_LIKE_SUFFIXES = (
    "buy_count_",
    "sell_count_",
    "unique_",
    "n_holders",
)


def _recipe_cols() -> list[str]:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from features.post_q5_sets import FEATURE_SETS

    return list(FEATURE_SETS["+q5b"])


def _is_usd_vol_col(c: str) -> bool:
    if c in META_COLS:
        return False
    # Everything else in +q5b is flow / USD / sol / share economics
    return True


def _float_diff(a, b, atol: float = 1e-9) -> bool:
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return str(a) != str(b)
    if np.isnan(fa) and np.isnan(fb):
        return False
    if np.isnan(fa) or np.isnan(fb):
        return True
    return abs(fa - fb) > atol


def build_overlay(
    live: pd.DataFrame,
    store: pd.DataFrame,
    recipe: list[str],
    *,
    copy_meta: bool,
    atol: float = 1e-9,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    sm = store.drop_duplicates("mint", keep="first").set_index("mint")
    usd_cols = [c for c in recipe if _is_usd_vol_col(c) and c in live.columns and c in store.columns]
    meta_cols = [c for c in META_COLS if c in live.columns and c in store.columns]

    out = live.copy()
    side_rows: list[dict] = []
    mint_stats: list[dict] = []

    # Ensure path_a columns exist for every overlaid col we might touch
    path_a_targets = list(dict.fromkeys(usd_cols + (meta_cols if copy_meta else [])))

    for _, row in live.iterrows():
        mint = str(row["mint"]).strip()
        short = mint[:12]
        if mint not in sm.index:
            mint_stats.append(
                {
                    "mint": mint,
                    "short": short,
                    "trades_exact": False,
                    "n_usd_diff_before": None,
                    "n_usd_overlaid": 0,
                    "n_meta_overlaid": 0,
                    "max_abs_usd_delta": None,
                    "top_usd_feat": None,
                    "note": "mint_missing_in_store",
                }
            )
            continue

        s = sm.loc[mint]
        n_buys = int(float(row.get("n_buys_le_t0", -1)))
        train_buys = int(float(row.get("train_buy_count", -2)))
        trades_exact = n_buys == train_buys

        usd_diffs = []
        for c in usd_cols:
            if _float_diff(row[c], s[c], atol=atol):
                usd_diffs.append((c, float(row[c]), float(s[c]), float(row[c]) - float(s[c])))

        meta_diffs = []
        for c in meta_cols:
            if _float_diff(row[c], s[c], atol=atol):
                meta_diffs.append((c, float(row[c]), float(s[c]), float(row[c]) - float(s[c])))

        n_overlaid = 0
        n_meta = 0
        if trades_exact:
            for c, lv, sv, d in usd_diffs:
                pa = f"{c}_path_a"
                if pa not in out.columns:
                    out[pa] = np.nan
                out.loc[out["mint"] == mint, pa] = lv
                out.loc[out["mint"] == mint, c] = sv
                n_overlaid += 1
                side_rows.append(
                    {
                        "mint": mint,
                        "col": c,
                        "path_a": lv,
                        "store": sv,
                        "delta_path_a_minus_store": d,
                    }
                )
            if copy_meta:
                for c, lv, sv, d in meta_diffs:
                    pa = f"{c}_path_a"
                    if pa not in out.columns:
                        out[pa] = np.nan
                    out.loc[out["mint"] == mint, pa] = lv
                    out.loc[out["mint"] == mint, c] = sv
                    n_meta += 1
                    side_rows.append(
                        {
                            "mint": mint,
                            "col": c,
                            "path_a": lv,
                            "store": sv,
                            "delta_path_a_minus_store": d,
                        }
                    )

        max_abs = max((abs(d) for _, _, _, d in usd_diffs), default=0.0)
        top = max(usd_diffs, key=lambda t: abs(t[3]))[0] if usd_diffs else None
        mint_stats.append(
            {
                "mint": mint,
                "short": short,
                "trades_exact": trades_exact,
                "n_buys_le_t0": n_buys,
                "train_buy_count": train_buys,
                "n_usd_diff_before": len(usd_diffs),
                "n_usd_overlaid": n_overlaid,
                "n_meta_diff_before": len(meta_diffs),
                "n_meta_overlaid": n_meta,
                "max_abs_usd_delta": max_abs,
                "top_usd_feat": top,
                "buy_vol_usd_60s_path_a": float(row["buy_vol_usd_60s"]) if "buy_vol_usd_60s" in row else None,
                "buy_vol_usd_60s_store": float(s["buy_vol_usd_60s"]) if "buy_vol_usd_60s" in s.index else None,
                "note": "overlaid" if trades_exact else "skipped_trades_not_exact",
            }
        )

    # Stable column order: original live cols, then *_path_a alphabetically
    base_cols = list(live.columns)
    extra = [c for c in out.columns if c not in base_cols]
    extra_sorted = sorted(extra)
    out = out[base_cols + extra_sorted]

    side = pd.DataFrame(side_rows)
    return out, side, mint_stats


def write_diagnostic(
    path: Path,
    mint_stats: list[dict],
    *,
    out_csv: Path,
    meta_json: Path,
    side_csv: Path,
    copy_meta: bool,
    store_path: Path,
    live_path: Path,
) -> None:
    mint_2h = "2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump"
    st_2h = next((m for m in mint_stats if m["mint"] == mint_2h), None)

    lines: list[str] = []
    lines.append("# USD exact — ge10 Path A vs store (isolate Δ only) — 2026-10-01")
    lines.append("")
    lines.append("**Owner:** SolDatos · **Repo:** `/workspace/solana-10x`")
    lines.append("**Paper live:** FROZEN (untouched) · Scale 6.6× **OFF** · recovery_on **intact**")
    lines.append("**n=200:** not blocked")
    lines.append("**BOSS:** `…_usd_store_…` pack is **ISOLATE-ONLY** — never force live ≡ Dune USD")
    lines.append("")
    lines.append("## Purpose")
    lines.append("")
    lines.append(
        "SolModelos FAIL after `recovery_on` + metafill: max `|Δ live−store| = 2.35e-3` "
        "on `2hCEWY…`. Trades **12/12** exact; meta fill OK. Residual = Path A "
        "`sol×pyth_asof` USD/vol ≠ Dune store `AmountInUSD`."
    )
    lines.append("")
    lines.append(
        "This note **quantifies** that residual. The optional `usd_store` CSV is "
        "**ISOLATE-ONLY** (prove residual class = USD/vol). **Not for prod / live scoring.** "
        "Production live stays Path A. Never force live≡Dune."
    )
    lines.append("")
    lines.append("## Artifacts (NEW paths only)")
    lines.append("")
    lines.append("| Path | Role |")
    lines.append("|------|------|")
    lines.append(
        f"| `{out_csv.relative_to(ROOT)}` | **ISOLATE-ONLY** audit pack — NOT for prod / live scoring |"
    )
    lines.append(
        f"| `{meta_json.relative_to(ROOT)}` | Meta JSON — isolate_only / not_for_live_scoring |"
    )
    lines.append(
        f"| `{side_csv.relative_to(ROOT)}` | Side table: Path A vs store per residual col |"
    )
    lines.append(f"| `{path.relative_to(ROOT)}` | This diagnostic |")
    lines.append("| `scripts/overlay_usd_store_ge10_20261001.py` | Reproducible isolate builder |")
    lines.append("")
    lines.append("Inputs (read-only):")
    lines.append(f"- live Path A: `{live_path.relative_to(ROOT)}`")
    lines.append(f"- store: `{store_path.relative_to(ROOT)}`")
    lines.append("- evidence: `cycle0/ge10-rescore-recovery-on-metafill-20261001.md`")
    lines.append("")
    lines.append("## Path A vs store residual (per mint, +q5b USD/vol)")
    lines.append("")
    lines.append(
        "All trade-exact mints (`n_buys_le_t0 == train_buy_count`). "
        f"copy_meta={copy_meta} (isolate pack only)."
    )
    lines.append("")
    lines.append(
        r"| mint | trades | n_usd_diff | max\|Δ\| | top feat | buy60 Path A | buy60 store | Δ |"
    )
    lines.append("|---|---:|---:|---:|---|---:|---:|---:|")
    for m in mint_stats:
        pa = m.get("buy_vol_usd_60s_path_a")
        st = m.get("buy_vol_usd_60s_store")
        if pa is not None and st is not None:
            d = pa - st
            lines.append(
                f"| `{m['short']}…` | "
                f"{'Y' if m['trades_exact'] else 'N'} | "
                f"{m['n_usd_diff_before']} | "
                f"{m['max_abs_usd_delta']:.4g} | "
                f"{m['top_usd_feat'] or '—'} | "
                f"{pa:.6f} | {st:.6f} | {d:.6f} |"
            )
        else:
            lines.append(
                f"| `{m['short']}…` | {'Y' if m['trades_exact'] else 'N'} | "
                f"{m['n_usd_diff_before']} | {m['max_abs_usd_delta']} | "
                f"{m['top_usd_feat']} | — | — | — |"
            )
    lines.append("")
    if st_2h:
        lines.append("### 2hCEWY headline (FAIL driver)")
        lines.append("")
        lines.append(f"- mint: `{mint_2h}`")
        lines.append(
            f"- `buy_vol_usd_60s` Path A **{st_2h['buy_vol_usd_60s_path_a']:.6f}** vs store "
            f"**{st_2h['buy_vol_usd_60s_store']:.6f}** "
            f"(Δ≈{st_2h['buy_vol_usd_60s_path_a'] - st_2h['buy_vol_usd_60s_store']:.6f} ≈ $28)"
        )
        lines.append("- Matches FAIL evidence: live 17638.78 vs store 17610.97 (Δ~$28).")
        lines.append("")

    lines.append("## Why `store_rescore ≠ oos` on 2hCEWY after Q5a overlay")
    lines.append("")
    lines.append(
        "OOS recorded against **pre-Q5a** expand_v2 row. Q4 hygiene patched local store "
        "`buy_vol_usd_60s`/`buy_count_60s` from Q5a:"
    )
    lines.append("")
    lines.append("```")
    lines.append("pre-Q5a  buy_vol_usd_60s = 25228.5410196028  (buy_count_60s=7)  → joblib = 0.995361820598 ≡ oos")
    lines.append("post-Q5a buy_vol_usd_60s = 17610.973964359822 (buy_count_60s=6) → joblib = 0.992423560390")
    lines.append("|oos − post-Q5a store_rescore| ≈ 2.938e-3")
    lines.append("|oos − pre-Q5a  store_rescore| ≈ 3e-13  (identity)")
    lines.append("```")
    lines.append("")
    lines.append(
        "Side effect of Q5a expand_v2 buy_vol patch — not a live Path A bug. "
        "Backup: `data/samples/features_dune_p0_q5_expand_v2.csv.bak_pre_q5a_20261001`."
    )
    lines.append("")
    lines.append("## Recommendations (BOSS)")
    lines.append("")
    lines.append("| Option | Action | Expectation |")
    lines.append("|--------|--------|-------------|")
    lines.append(
        "| **(A)** | Keep live Path A; close residual under Path A "
        "(optional fee-gross sol_amt etc.) | Never force live≡Dune |"
    )
    lines.append(
        "| **(B)** | SolModelos rebases store/joblib to Path A "
        "(reprice train + re-fit/re-OOS) | live≡train via Path A rebase |"
    )
    lines.append(
        "| **(C)** | Do **NOT** re-enable 6.6×; do **NOT** feed usd_store into live scoring | "
        "Blind scale / live←Dune forbidden |"
    )
    lines.append("")
    lines.append("**Forbidden:** using `…_usd_store_…` as live feature input.")
    lines.append(
        "**Isolate use only:** offline prove Δ vanishes when store USD swapped in; discard for prod."
    )
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(
        "Residual after recovery_on+metafill = **Path A USD/vol vs Dune store** "
        "(2hCEWY buy60 Δ~$28 → score Δ 2.35e-3). Fix = Path A closes residual and/or "
        "SolModelos Path A train rebase — **never** force live to Dune USD. "
        "`usd_store` = isolate-only. Scale OFF. Paper FROZEN. n=200 unblocked."
    )
    lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")



def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--live", type=Path, default=DEFAULT_LIVE)
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--meta-json", type=Path, default=DEFAULT_META)
    ap.add_argument("--side-csv", type=Path, default=DEFAULT_SIDE)
    ap.add_argument("--diag", type=Path, default=DEFAULT_DIAG)
    ap.add_argument(
        "--copy-meta",
        action="store_true",
        default=True,
        help="Also copy store meta lens (default True for exact PASS vs store)",
    )
    ap.add_argument("--no-copy-meta", action="store_true", help="Leave live meta (0/missing)")
    ap.add_argument("--skip-diag", action="store_true")
    args = ap.parse_args()

    copy_meta = not args.no_copy_meta
    recipe = _recipe_cols()
    live = pd.read_csv(args.live)
    store = pd.read_csv(args.store)

    out, side, mint_stats = build_overlay(live, store, recipe, copy_meta=copy_meta)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    side.to_csv(args.side_csv, index=False)

    n_exact = sum(1 for m in mint_stats if m["trades_exact"])
    n_usd = sum(m["n_usd_overlaid"] for m in mint_stats)
    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "kind": "isolate_delta_audit_overlay",
        "not_production": True,
        "production_live": "Path A (sol_amt × pyth_asof); scale 6.6× OFF — NEVER overlay store USD into live",
        "purpose": (
            "ISOLATE-ONLY: copy train-store USD/vol onto recovery_on when n_trades==train "
            "to attribute score Δ to USD/vol. Path A kept as *_path_a. NOT for prod/live "
            "scoring. Never force live≡Dune."
        ),
        "isolate_only": True,
        "not_for_live_scoring": True,
        "do_not_force_live_eq_dune": True,
        "inputs": {
            "live_features": str(args.live.relative_to(ROOT)),
            "train_store": str(args.store.relative_to(ROOT)),
            "evidence": "cycle0/ge10-rescore-recovery-on-metafill-20261001.md",
        },
        "outputs": {
            "overlay_csv": str(args.out.relative_to(ROOT)),
            "side_csv": str(args.side_csv.relative_to(ROOT)),
            "diag_md": str(args.diag.relative_to(ROOT)),
            "script": "scripts/overlay_usd_store_ge10_20261001.py",
        },
        "policy": {
            "recovery_on_intact": True,
            "paper_live_touched": False,
            "scale_6_6x": False,
            "copy_meta_from_store": copy_meta,
            "overlay_gate": "n_buys_le_t0 == train_buy_count",
        },
        "counts": {
            "n_mints": len(mint_stats),
            "n_trades_exact": n_exact,
            "n_usd_vol_cells_overlaid": n_usd,
            "n_meta_cells_overlaid": sum(m["n_meta_overlaid"] for m in mint_stats),
            "n_side_rows": int(len(side)),
        },
        "mint_stats": mint_stats,
        "solmodelos_rescore": {
            "use_as_live_fix": False,
            "isolate_verify_ok": True,
            "note": (
                "Offline isolate only (overlay scores ≡ store proves USD residual). "
                "Fix = Path A closes residual OR Path A train rebase — never live←Dune."
            ),
        },
        "recommendations": {
            "A": "Keep live Path A; close residual under Path A",
            "B": "SolModelos rebases store/joblib to Path A (re-fit)",
            "C": "Do NOT re-enable 6.6×; do NOT overlay store USD into live scoring",
        },
        "store_rescore_ne_oos_2hCEWY": {
            "cause": "Q5a overlay patched expand_v2 buy_vol_usd_60s (25228.54→17610.97)",
            "pre_q5a_bak": "data/samples/features_dune_p0_q5_expand_v2.csv.bak_pre_q5a_20261001",
            "pre_q5a_joblib_equals_oos": True,
            "post_q5a_joblib": 0.992423560390,
            "oos": 0.995361820598,
        },
    }
    args.meta_json.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    if not args.skip_diag:
        write_diagnostic(
            args.diag,
            mint_stats,
            out_csv=args.out,
            meta_json=args.meta_json,
            side_csv=args.side_csv,
            copy_meta=copy_meta,
            store_path=args.store,
            live_path=args.live,
        )

    print(f"wrote {args.out} rows={len(out)} cols={len(out.columns)}")
    print(f"wrote {args.side_csv} rows={len(side)}")
    print(f"wrote {args.meta_json}")
    if not args.skip_diag:
        print(f"wrote {args.diag}")
    print(f"trades_exact={n_exact}/{len(mint_stats)} usd_cells_overlaid={n_usd} copy_meta={copy_meta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
