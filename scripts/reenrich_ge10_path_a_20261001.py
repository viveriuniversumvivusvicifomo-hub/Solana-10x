#!/usr/bin/env python3
"""SolDatos: ge10(+2hCEWY) Path A re-enrich from existing tx dumps (2026-10-01).

Prefer dump parse-by-sig. Path A require_pyth. Scale OFF. No paper_live / no joblib.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from features.post_q5_sets import FEATURE_SETS
from ingestion.bonding_curve import bonding_curve_pda
from ingestion.env import load_dotenv
from ingestion.helius_enhanced import HeliusEnhanced, filter_txs_le_t0
from ingestion.sol_usd_oracle import (
    apply_dune_helius_usd_scale_enabled,
    maybe_scale_usd,
    resolve_sol_usd_for_scoring,
)
from paper_live.helius_enrich import buy_vol_60s_from_trades, parse_helius_enhanced_txs
from paper_live.q5a_agg import aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, q5b_from_create

GE_PRIOR = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_20261001.csv"
DUMP_GE = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_20261001.csv"
DUMP_2H = ROOT / "data" / "samples" / "helius_parity_tx_dump_2hCEWY_20261001.csv"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
OUT_FEAT = ROOT / "data" / "samples" / "helius_parity_features_ge10_reenrich_20261001.csv"
OUT_META = ROOT / "data" / "samples" / "helius_parity_features_ge10_reenrich_20261001_meta.json"
OUT_MINT = ROOT / "data" / "samples" / "helius_parity_enrich_ge10_reenrich_20261001.csv"
OUT_MD = ROOT / "cycle0" / "diagnostics" / "ge10-reenrich-path-a-20261001.md"

MINT_2H = "2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump"
Q5B_COLS = list(FEATURE_SETS["+q5b"])


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "+00:00").replace("Z", "+00:00").strip()
    return _aware(datetime.fromisoformat(s))


def _parse_by_sigs(helius: HeliusEnhanced, sigs: list[str]) -> list[dict]:
    key = helius._api_key  # noqa: SLF001
    url = "https://api.helius.xyz/v0/transactions/"
    out: list[dict] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(sigs), 100):
            chunk = sigs[i : i + 100]
            for attempt in range(8):
                helius._throttle()  # noqa: SLF001
                resp = client.post(url, params={"api-key": key}, json={"transactions": chunk})
                helius.log.n_calls += 1
                helius.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    time.sleep(1.2 * (attempt + 1))
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, list):
                    out.extend(body)
                break
            else:
                raise RuntimeError("parse 429 exhausted")
    return out


def main() -> int:
    load_dotenv()
    os.environ["APPLY_DUNE_HELIUS_USD_SCALE"] = "0"
    assert apply_dune_helius_usd_scale_enabled() is False

    prior = pd.read_csv(GE_PRIOR)
    dump_ge = pd.read_csv(DUMP_GE)
    dump_2h = pd.read_csv(DUMP_2H) if DUMP_2H.exists() else pd.DataFrame()

    # Prefer dedicated 2hCEWY dump for that mint
    parts = [dump_ge[dump_ge["mint"] != MINT_2H]]
    if len(dump_2h):
        parts.append(dump_2h)
    else:
        parts.append(dump_ge[dump_ge["mint"] == MINT_2H])
    dump = pd.concat(parts, ignore_index=True)

    need = {"mint", "create_ts", "creator_pubkey", "buy_count_total", "buy_vol_usd_60s", "mc_usd_t0", "age_s"}
    fs = pd.read_csv(FS_PATH, usecols=lambda c: c in need)
    fs_by = {r.mint: r for r in fs.itertuples(index=False)}

    dump_by = {m: g for m, g in dump.groupby("mint")}
    rows_feat: list[dict[str, Any]] = []
    rows_mint: list[dict[str, Any]] = []
    n_le_false = 0
    n_pyth = 0

    with HeliusEnhanced(max_calls=400, max_retries_429=10, min_interval_s=0.2) as helius:
        for i, prow in enumerate(prior.itertuples(index=False), 1):
            mint = str(prow.mint)
            t0 = _parse_t0(str(prow.t0_ts))
            oos = float(prow.oos_score)
            print(f"[{i}/{len(prior)}] {mint[:16]}…", flush=True)

            tr = fs_by.get(mint)
            create_ts = t0
            creator = None
            train_buys = None
            if tr is not None:
                if getattr(tr, "create_ts", None) and str(tr.create_ts) not in ("nan", "None"):
                    try:
                        create_ts = _parse_t0(str(tr.create_ts))
                    except Exception:
                        pass
                cp = getattr(tr, "creator_pubkey", None)
                if cp and str(cp) != "nan":
                    creator = str(cp)
                try:
                    train_buys = float(getattr(tr, "buy_count_total", None) or 0)
                except (TypeError, ValueError):
                    train_buys = None

            q_score, reason = None, "unset"
            for attempt in range(4):
                q_score, reason = resolve_sol_usd_for_scoring(
                    as_of=t0, allow_network=True, require_pyth=True
                )
                if q_score is not None:
                    break
                time.sleep(0.6 * (attempt + 1))
            if q_score is None:
                rows_mint.append({
                    "mint": mint, "t0_ts": prow.t0_ts, "oos_score": oos,
                    "scoreable": False, "skip_reason": f"pyth:{reason}",
                    "sol_usd_source": None, "n_le_t0_false": 0,
                })
                print(f"  SKIP pyth {reason}", flush=True)
                continue

            sol_px = float(q_score.price)
            sol_src = str(q_score.source)
            if sol_src.startswith("pyth"):
                n_pyth += 1

            dg = dump_by.get(mint)
            sigs = []
            if dg is not None and len(dg):
                sigs = [str(s) for s in dg["tx_sig"].dropna().unique().tolist() if s]
            txs = _parse_by_sigs(helius, sigs) if sigs else []
            txs_le = filter_txs_le_t0(txs, t0)
            t0u = int(_aware(t0).timestamp())
            le_false = sum(
                1 for tx in txs_le
                if tx.get("timestamp") is not None and int(tx["timestamp"]) > t0u
            )
            n_le_false += le_false

            bc = str(bonding_curve_pda(mint))
            trades = parse_helius_enhanced_txs(
                txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
            )
            trades_use = [x for x in trades if x.ts <= t0]
            buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
            buy60 = maybe_scale_usd(float(buy60))
            q5a = aggregate_q5a_for_mint(trades_use, t0)
            create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
            q5b = q5b_from_create(create, t0, prior_creates=[])
            age_s = max(0.0, (_aware(t0) - _aware(create_ts)).total_seconds())

            scoreable = len(trades_use) >= 1 and sol_src.startswith("pyth")
            feats: dict[str, Any] = {
                "mint": mint,
                "t0_ts": str(prow.t0_ts),
                "oos_score": oos,
                "y": getattr(prow, "y", None),
                "sol_usd": sol_px,
                "sol_usd_source": sol_src,
                "usd_reason": reason,
                "scoreable": scoreable,
                "n_trades_le_t0": len(trades_use),
                "n_buys_le_t0": sum(1 for t in trades_use if t.side == "buy"),
                "n_txs_le_t0": len(txs_le),
                "n_dump_sigs": len(sigs),
                "n_le_t0_false": le_false,
                "train_buy_count": train_buys,
                "dump_source": "2hCEWY_dedicated" if mint == MINT_2H and len(dump_2h) else "ge10_dump",
                "fetch_mode": "dump_parse_by_sig",
                "apply_dune_helius_usd_scale": False,
                **{c: q5b.get(c) for c in q5b},
                **q5a,
                "buy_vol_usd_60s": float(buy60),
                "buy_count_60s": int(buy_n),
                "age_s": age_s if age_s is not None else q5b.get("age_s"),
            }
            for c in Q5B_COLS:
                feats.setdefault(c, None)
            rows_feat.append(feats)
            rows_mint.append({
                "mint": mint,
                "t0_ts": str(prow.t0_ts),
                "oos_score": oos,
                "n_trades_le_t0": len(trades_use),
                "n_buys_le_t0": feats["n_buys_le_t0"],
                "buy_vol_usd_60s": float(buy60),
                "sol_usd": sol_px,
                "sol_usd_source": sol_src,
                "fetch_mode": "dump_parse_by_sig",
                "scoreable": scoreable,
                "skip_reason": None if scoreable else "no_trades_le_t0",
                "n_le_t0_false": le_false,
                "train_buy_count": train_buys,
                "dump_source": feats["dump_source"],
            })
            print(
                f"  trades={len(trades_use)} buy60={buy60:.2f} sol={sol_src} "
                f"scoreable={scoreable} le_false={le_false}",
                flush=True,
            )

    df = pd.DataFrame(rows_feat)
    # column order: meta + q5b recipe
    meta_cols = [
        "mint", "t0_ts", "oos_score", "y", "sol_usd", "sol_usd_source", "usd_reason",
        "scoreable", "n_trades_le_t0", "n_buys_le_t0", "n_txs_le_t0", "n_dump_sigs",
        "n_le_t0_false", "train_buy_count", "dump_source", "fetch_mode",
        "apply_dune_helius_usd_scale", "buy_count_60s",
    ]
    cols = meta_cols + [c for c in Q5B_COLS if c not in meta_cols]
    extra = [c for c in df.columns if c not in cols]
    df = df[[c for c in cols + extra if c in df.columns]]
    df.to_csv(OUT_FEAT, index=False)
    pd.DataFrame(rows_mint).to_csv(OUT_MINT, index=False)

    n_ok = int(df["scoreable"].sum()) if len(df) else 0
    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_mints": int(len(prior)),
        "n_feature_rows": int(len(df)),
        "n_scoreable": n_ok,
        "n_pyth_asof": n_pyth,
        "n_le_t0_false": int(n_le_false),
        "path_a": "require_pyth / amount_usd=sol_amt×pyth_asof",
        "scale_6_6x": False,
        "dump_ge10": str(DUMP_GE.relative_to(ROOT)),
        "dump_2hCEWY": str(DUMP_2H.relative_to(ROOT)),
        "features_csv": str(OUT_FEAT.relative_to(ROOT)),
        "mint_enrich_csv": str(OUT_MINT.relative_to(ROOT)),
        "q5b_cols": len(Q5B_COLS),
        "buy_vol_semantics": "buy_vol_60s_from_trades Path A (paper_live.helius_enrich)",
        "paper_live_touched": False,
        "joblib_touched": False,
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")

    md = [
        "# ge10 Path A re-enrich — 2026-10-01",
        "",
        "SolDatos interrupt package for SolModelos re-score. Dump-driven; no paper_live.",
        "",
        "## Paths",
        f"- Features: `{OUT_FEAT.relative_to(ROOT)}`",
        f"- Mint enrich: `{OUT_MINT.relative_to(ROOT)}`",
        f"- Meta: `{OUT_META.relative_to(ROOT)}`",
        f"- Dumps: `{DUMP_GE.relative_to(ROOT)}` + `{DUMP_2H.relative_to(ROOT)}` (2hCEWY preferred)",
        "",
        "## Counts",
        f"- n_mints: **{len(prior)}**",
        f"- n_scoreable: **{n_ok}**",
        f"- n_pyth_asof: **{n_pyth}**",
        f"- n_le_t0_false: **{n_le_false}**",
        "",
        "## Method",
        "- USD Path A: `resolve_sol_usd_for_scoring(require_pyth=True)` → sol_amt × pyth_asof",
        "- Scale 6.6×: **OFF**",
        "- Fetch: dump `tx_sig` → Helius parse-by-sig → `filter_txs_le_t0`",
        "- Parse: WSOL multi-leg via paper wrapper → ingestion `helius_trade_parse`",
        "- buy_vol_usd_60s: `buy_vol_60s_from_trades` (Q5a-aligned window [t0−60s, t0])",
        "- Fixed T0 from ge10 prior / OOS t0_ts",
        "",
        "## Per-mint buy_vol_usd_60s (Path A)",
        "",
        "| mint | trades | buy60 | sol_src | scoreable |",
        "|---|---:|---:|---|---|",
    ]
    for r in rows_mint:
        md.append(
            f"| `{r['mint'][:12]}…` | {r.get('n_trades_le_t0')} | "
            f"{r.get('buy_vol_usd_60s')} | {r.get('sol_usd_source')} | {r.get('scoreable')} |"
        )
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md) + "\n")
    print(json.dumps(meta, indent=2), flush=True)
    print(f"wrote {OUT_FEAT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
