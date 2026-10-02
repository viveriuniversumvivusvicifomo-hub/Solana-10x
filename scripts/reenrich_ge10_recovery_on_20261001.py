#!/usr/bin/env python3
"""SolDatos: ge12 Path A re-enrich with recovery helpers ON (2026-10-01).

NEW distinct paths (dump-only ge10_reenrich_* untouched for audit).
Strategy: dump parse-by-sig baseline + fetch_create_to_t0_txs (RPC+slot) merge;
keep the path with more buys (never regress BZof/4M3g/2hCEWY).
Path A pyth_asof, scale OFF, fixed T0, le_t0 false→0. No paper_live/joblib.
"""
from __future__ import annotations

import csv
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
from ingestion.helius_enhanced import (
    HeliusEnhanced,
    fetch_create_to_t0_txs,
    filter_txs_le_t0,
    merge_tx_lists,
)
from ingestion.helius_rpc import HeliusRpc
from ingestion.helius_trade_parse import parse_helius_enhanced_txs as parse_ingestion
from ingestion.sol_usd_oracle import (
    apply_dune_helius_usd_scale_enabled,
    maybe_scale_usd,
    resolve_sol_usd_for_scoring,
)
from paper_live.helius_enrich import buy_vol_60s_from_trades, parse_helius_enhanced_txs
from paper_live.q5a_agg import aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, q5b_from_create

GE_PRIOR = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_post_recovery_20261001.csv"
BEFORE_FEAT = ROOT / "data" / "samples" / "helius_parity_features_ge10_reenrich_20261001.csv"
DUMP_GE = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_20261001.csv"
DUMP_2H = ROOT / "data" / "samples" / "helius_parity_tx_dump_2hCEWY_20261001.csv"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"

OUT_FEAT = ROOT / "data" / "samples" / "helius_parity_features_ge10_recovery_on_20261001.csv"
OUT_META = ROOT / "data" / "samples" / "helius_parity_features_ge10_recovery_on_20261001_meta.json"
OUT_MINT = ROOT / "data" / "samples" / "helius_parity_enrich_ge10_recovery_on_20261001.csv"
OUT_TX = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_recovery_on_20261001.csv"
OUT_TX_META = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_recovery_on_20261001_meta.json"
OUT_MD = ROOT / "cycle0" / "diagnostics" / "ge10-reenrich-recovery-on-20261001.md"

MINT_2H = "2hCEWYZcFZNWV59a6Coyo3czTa9MMpdjxnVhXagjpump"
Q5B_COLS = list(FEATURE_SETS["+q5b"])
DUMP_COLS = [
    "mint", "tx_sig", "ts", "t0_ts", "le_t0", "source", "side",
    "sol_amt", "parsed_as_trade", "addr_source",
]


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "+00:00").replace("Z", "+00:00").strip()
    return _aware(datetime.fromisoformat(s))


def _iso_utc(dt: datetime) -> str:
    return _aware(dt).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _iso_from_unix(ts: int | float) -> str:
    return _iso_utc(datetime.fromtimestamp(int(ts), tz=timezone.utc))


def _parse_by_sigs(helius: HeliusEnhanced, sigs: list[str]) -> list[dict]:
    key = helius._api_key  # noqa: SLF001
    url = "https://api.helius.xyz/v0/transactions/"
    out: list[dict] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(sigs), 100):
            chunk = sigs[i : i + 100]
            for attempt in range(10):
                helius._throttle()  # noqa: SLF001
                resp = client.post(url, params={"api-key": key}, json={"transactions": chunk})
                helius.log.n_calls += 1
                helius.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, list):
                    out.extend(body)
                break
            else:
                raise RuntimeError("parse 429 exhausted")
    return out


def _count_buys(txs_le: list[dict], *, mint: str, bc: str, sol_px: float, t0: datetime) -> tuple[list, int, int]:
    trades = parse_helius_enhanced_txs(txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0)
    trades_use = [x for x in trades if x.ts <= t0]
    n_buys = sum(1 for t in trades_use if t.side == "buy")
    return trades_use, len(trades_use), n_buys


def _build_dump_rows(
    txs_le: list[dict], *, mint: str, bc: str, sol_px: float, t0: datetime, t0_ts_raw: str
) -> list[dict[str, Any]]:
    t0u = int(_aware(t0).timestamp())
    by_sig: dict[str, Any] = {}
    if len(txs_le) <= 100:
        for tx in txs_le:
            sig = str(tx.get("signature") or "")
            if not sig:
                continue
            one = parse_ingestion([tx], mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=None)
            if one:
                by_sig[sig] = max(one, key=lambda r: (r.side == "buy", r.amount_usd))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tx in txs_le:
        sig = str(tx.get("signature") or "")
        if not sig or sig in seen:
            continue
        seen.add(sig)
        ts_raw = tx.get("timestamp")
        if ts_raw is None:
            continue
        try:
            ts_i = int(ts_raw)
        except (TypeError, ValueError):
            continue
        le = ts_i <= t0u
        tr = by_sig.get(sig)
        rows.append({
            "mint": mint,
            "tx_sig": sig,
            "ts": _iso_from_unix(ts_i),
            "t0_ts": str(t0_ts_raw),
            "le_t0": bool(le),
            "source": str(tx.get("source") or ""),
            "side": getattr(tr, "side", "") if tr else "",
            "sol_amt": getattr(tr, "sol_amt", "") if tr else "",
            "parsed_as_trade": bool(tr),
            "addr_source": "recovery_on",
        })
    return rows


def enrich_one(
    helius: HeliusEnhanced,
    rpc: HeliusRpc,
    *,
    mint: str,
    t0_ts_raw: str,
    oos_score: float,
    y: Any,
    train: Any,
    dump_sigs: list[str],
    dump_source: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    t0 = _parse_t0(t0_ts_raw)
    create_ts = t0
    creator = None
    train_buys = None
    if train is not None:
        if getattr(train, "create_ts", None) and str(train.create_ts) not in ("nan", "None"):
            try:
                create_ts = _parse_t0(str(train.create_ts))
            except Exception:
                pass
        cp = getattr(train, "creator_pubkey", None)
        if cp and str(cp) != "nan":
            creator = str(cp)
        try:
            train_buys = float(getattr(train, "buy_count_total", None) or 0)
        except (TypeError, ValueError):
            train_buys = None

    q_score, reason = None, "unset"
    for attempt in range(4):
        q_score, reason = resolve_sol_usd_for_scoring(
            as_of=t0, allow_network=True, require_pyth=True
        )
        if q_score is not None:
            break
        time.sleep(0.8 * (attempt + 1))
    if q_score is None:
        skip = {
            "mint": mint, "t0_ts": t0_ts_raw, "oos_score": oos_score,
            "scoreable": False, "skip_reason": f"pyth:{reason}",
            "sol_usd_source": None, "n_le_t0_false": 0,
            "n_trades_le_t0": 0, "n_buys_le_t0": 0, "buy_vol_usd_60s": None,
            "train_buy_count": train_buys, "fetch_mode": None, "trades_exact": False,
            "dump_source": dump_source,
        }
        return {}, skip, []

    sol_px = float(q_score.price)
    sol_src = str(q_score.source)
    bc = str(bonding_curve_pda(mint))
    gaps: list[str] = []

    # --- A) dump parse-by-sig baseline ---
    txs_dump: list[dict] = []
    if dump_sigs:
        txs_dump = _parse_by_sigs(helius, dump_sigs)
        gaps.append(f"dump_sigs={len(dump_sigs)} parsed={len(txs_dump)}")
    txs_dump_le = filter_txs_le_t0(txs_dump, t0)
    trades_d, n_tr_d, n_buy_d = _count_buys(txs_dump_le, mint=mint, bc=bc, sol_px=sol_px, t0=t0)
    gaps.append(f"dump_buys={n_buy_d}")

    # --- B) recovery helpers ON (Enhanced + RPC + slot) ---
    age0 = abs((_aware(t0) - _aware(create_ts)).total_seconds()) <= 120.0
    enh_pages = 20 if age0 else 40
    rpc_pages = 40 if age0 else 30
    txs_rec, gaps_rec = fetch_create_to_t0_txs(
        helius, mint, t0=t0, create_ts=create_ts, bonding_curve=bc,
        rpc=rpc, max_pages_enhanced=enh_pages, max_pages_rpc=rpc_pages,
    )
    gaps.extend(gaps_rec[-10:])
    txs_rec_le = filter_txs_le_t0(txs_rec, t0)
    trades_r, n_tr_r, n_buy_r = _count_buys(txs_rec_le, mint=mint, bc=bc, sol_px=sol_px, t0=t0)
    gaps.append(f"recovery_buys={n_buy_r}")

    # --- C) merge dump+recovery txs, take best buy count ---
    txs_merged = merge_tx_lists(txs_dump_le, txs_rec_le)
    txs_merged_le = filter_txs_le_t0(txs_merged, t0)
    trades_m, n_tr_m, n_buy_m = _count_buys(txs_merged_le, mint=mint, bc=bc, sol_px=sol_px, t0=t0)
    gaps.append(f"merged_buys={n_buy_m}")

    candidates = [
        ("dump_parse_by_sig", txs_dump_le, trades_d, n_tr_d, n_buy_d),
        ("enhanced+rpc_sig_window+slot", txs_rec_le, trades_r, n_tr_r, n_buy_r),
        ("dump+recovery_merged", txs_merged_le, trades_m, n_tr_m, n_buy_m),
    ]
    # Prefer exact train match; else max buys; tie-break more txs
    def _key(c):
        mode, txs, trades, n_tr, n_buy = c
        exact = 1 if (train_buys is not None and int(n_buy) == int(float(train_buys))) else 0
        return (exact, n_buy, n_tr, len(txs))

    fetch_mode, txs_le, trades_use, n_tr, n_buys = max(candidates, key=_key)
    # If recovery alone had slot in gaps, stamp mode
    if fetch_mode.startswith("enhanced") and any("slot" in g for g in gaps_rec):
        fetch_mode = "enhanced+rpc_sig_window+slot"
    elif fetch_mode.startswith("enhanced"):
        fetch_mode = "enhanced+rpc_sig_window"

    t0u = int(_aware(t0).timestamp())
    le_false = 0
    for tx in txs_le:
        raw = tx.get("timestamp")
        if raw is None:
            continue
        try:
            if int(raw) > t0u:
                le_false += 1
        except (TypeError, ValueError):
            continue

    buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
    buy60 = maybe_scale_usd(float(buy60))
    q5a = aggregate_q5a_for_mint(trades_use, t0)
    create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
    q5b = q5b_from_create(create, t0, prior_creates=[])
    age_s = max(0.0, (_aware(t0) - _aware(create_ts)).total_seconds())
    scoreable = len(trades_use) >= 1 and sol_src.startswith("pyth")
    dump_rows = _build_dump_rows(
        txs_le, mint=mint, bc=bc, sol_px=sol_px, t0=t0, t0_ts_raw=t0_ts_raw
    )

    feats: dict[str, Any] = {
        "mint": mint,
        "t0_ts": str(t0_ts_raw),
        "oos_score": oos_score,
        "y": y,
        "sol_usd": sol_px,
        "sol_usd_source": sol_src,
        "usd_reason": reason,
        "scoreable": scoreable,
        "n_trades_le_t0": len(trades_use),
        "n_buys_le_t0": n_buys,
        "n_txs_le_t0": len(txs_le),
        "n_dump_sigs": len(dump_rows),
        "n_le_t0_false": le_false,
        "train_buy_count": train_buys,
        "dump_source": dump_source,
        "fetch_mode": fetch_mode,
        "apply_dune_helius_usd_scale": False,
        "gaps": "|".join(str(g) for g in gaps[-14:]),
        "dump_buys": n_buy_d,
        "recovery_buys": n_buy_r,
        "merged_buys": n_buy_m,
        **{c: q5b.get(c) for c in q5b},
        **q5a,
        "buy_vol_usd_60s": float(buy60),
        "buy_count_60s": int(buy_n),
        "age_s": age_s if age_s is not None else q5b.get("age_s"),
    }
    for c in Q5B_COLS:
        feats.setdefault(c, None)

    exact = train_buys is not None and int(n_buys) == int(float(train_buys))
    mint_row = {
        "mint": mint,
        "t0_ts": str(t0_ts_raw),
        "oos_score": oos_score,
        "n_trades_le_t0": len(trades_use),
        "n_buys_le_t0": n_buys,
        "buy_vol_usd_60s": float(buy60),
        "sol_usd": sol_px,
        "sol_usd_source": sol_src,
        "fetch_mode": fetch_mode,
        "scoreable": scoreable,
        "skip_reason": None if scoreable else "no_trades_le_t0",
        "n_le_t0_false": le_false,
        "train_buy_count": train_buys,
        "dump_source": dump_source,
        "dump_buys": n_buy_d,
        "recovery_buys": n_buy_r,
        "merged_buys": n_buy_m,
        "trades_exact": exact,
    }
    return feats, mint_row, dump_rows


def main() -> int:
    load_dotenv()
    os.environ["APPLY_DUNE_HELIUS_USD_SCALE"] = "0"
    assert apply_dune_helius_usd_scale_enabled() is False

    prior = pd.read_csv(GE_PRIOR)
    before: dict[str, dict[str, Any]] = {}
    if BEFORE_FEAT.exists():
        bf = pd.read_csv(BEFORE_FEAT)
        for r in bf.itertuples(index=False):
            before[str(r.mint)] = {
                "n_trades": int(r.n_trades_le_t0),
                "n_buys": int(r.n_buys_le_t0),
                "train": float(r.train_buy_count) if pd.notna(r.train_buy_count) else None,
            }

    dump_ge = pd.read_csv(DUMP_GE)
    dump_2h = pd.read_csv(DUMP_2H) if DUMP_2H.exists() else pd.DataFrame()
    parts = [dump_ge[dump_ge["mint"] != MINT_2H]]
    if len(dump_2h):
        parts.append(dump_2h)
    else:
        parts.append(dump_ge[dump_ge["mint"] == MINT_2H])
    dump = pd.concat(parts, ignore_index=True)
    dump_by = {m: g for m, g in dump.groupby("mint")}

    need = {"mint", "create_ts", "creator_pubkey", "buy_count_total", "buy_vol_usd_60s", "mc_usd_t0", "age_s"}
    fs = pd.read_csv(FS_PATH, usecols=lambda c: c in need)
    fs_by = {r.mint: r for r in fs.itertuples(index=False)}

    rows_feat: list[dict[str, Any]] = []
    rows_mint: list[dict[str, Any]] = []
    all_dump: list[dict[str, Any]] = []
    n_le_false = 0
    n_pyth = 0

    with HeliusEnhanced(
        max_calls=8000, max_retries_429=14, min_interval_s=0.8
    ) as helius, HeliusRpc(min_interval_s=0.25) as rpc:
        for i, prow in enumerate(prior.itertuples(index=False), 1):
            mint = str(prow.mint)
            oos = float(prow.oos_score)
            y = getattr(prow, "y", None)
            dg = dump_by.get(mint)
            sigs: list[str] = []
            if dg is not None and len(dg):
                sigs = [str(s) for s in dg["tx_sig"].dropna().unique().tolist() if s]
            dsrc = "2hCEWY_dedicated" if mint == MINT_2H and len(dump_2h) else "ge10_dump"
            print(f"[{i}/{len(prior)}] {mint[:16]}… recovery_on dump_sigs={len(sigs)}", flush=True)
            t0s = time.monotonic()
            feats, mint_row, dump_rows = enrich_one(
                helius, rpc,
                mint=mint,
                t0_ts_raw=str(prow.t0_ts),
                oos_score=oos,
                y=y,
                train=fs_by.get(mint),
                dump_sigs=sigs,
                dump_source=dsrc,
            )
            elapsed = time.monotonic() - t0s
            if feats:
                rows_feat.append(feats)
                if str(feats.get("sol_usd_source", "")).startswith("pyth"):
                    n_pyth += 1
                n_le_false += int(feats.get("n_le_t0_false") or 0)
            rows_mint.append(mint_row)
            all_dump.extend(dump_rows)
            print(
                f"  buys={mint_row.get('n_buys_le_t0')}/{mint_row.get('train_buy_count')} "
                f"dump={mint_row.get('dump_buys')} rec={mint_row.get('recovery_buys')} "
                f"merged={mint_row.get('merged_buys')} mode={mint_row.get('fetch_mode')} "
                f"exact={mint_row.get('trades_exact')} {elapsed:.1f}s",
                flush=True,
            )
            time.sleep(1.2)  # polite vs n=200

    df = pd.DataFrame(rows_feat)
    meta_cols = [
        "mint", "t0_ts", "oos_score", "y", "sol_usd", "sol_usd_source", "usd_reason",
        "scoreable", "n_trades_le_t0", "n_buys_le_t0", "n_txs_le_t0", "n_dump_sigs",
        "n_le_t0_false", "train_buy_count", "dump_source", "fetch_mode",
        "apply_dune_helius_usd_scale", "buy_count_60s", "dump_buys", "recovery_buys",
        "merged_buys", "gaps",
    ]
    cols = meta_cols + [c for c in Q5B_COLS if c not in meta_cols]
    extra = [c for c in df.columns if c not in cols]
    df = df[[c for c in cols + extra if c in df.columns]]
    OUT_FEAT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_FEAT, index=False)
    pd.DataFrame(rows_mint).to_csv(OUT_MINT, index=False)

    with OUT_TX.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DUMP_COLS, extrasaction="ignore")
        w.writeheader()
        for row in all_dump:
            out = dict(row)
            out["le_t0"] = "true" if row["le_t0"] else "false"
            w.writerow(out)

    n_ok = int(df["scoreable"].sum()) if len(df) else 0
    n_exact = sum(1 for r in rows_mint if r.get("trades_exact"))
    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_mints": int(len(prior)),
        "n_feature_rows": int(len(df)),
        "n_scoreable": n_ok,
        "n_trades_exact_vs_train": n_exact,
        "n_pyth_asof": n_pyth,
        "n_le_t0_false": int(n_le_false),
        "path_a": "require_pyth / amount_usd=sol_amt×pyth_asof",
        "scale_6_6x": False,
        "recovery": "dump baseline + fetch_create_to_t0_txs Enhanced+RPC+slot (ON all 12); best-of merge",
        "features_csv": str(OUT_FEAT.relative_to(ROOT)),
        "mint_enrich_csv": str(OUT_MINT.relative_to(ROOT)),
        "tx_dump_csv": str(OUT_TX.relative_to(ROOT)),
        "dump_only_audit_untouched": [
            str(BEFORE_FEAT.relative_to(ROOT)),
            str(DUMP_GE.relative_to(ROOT)),
        ],
        "q5b_cols": len(Q5B_COLS),
        "buy_vol_semantics": "buy_vol_60s_from_trades Path A (paper_live.helius_enrich)",
        "paper_live_touched": False,
        "joblib_touched": False,
        "n200_paths_untouched": True,
    }
    OUT_META.write_text(json.dumps(meta, indent=2) + "\n")
    OUT_TX_META.write_text(json.dumps({
        "kind": "helius_parity_tx_dump_ge10_recovery_on",
        "generated_at": meta["created_at_utc"],
        "n_mints": len(prior),
        "n_dump_rows": len(all_dump),
        "n_le_t0_false": sum(1 for r in all_dump if not r["le_t0"]),
        "out_csv": str(OUT_TX.relative_to(ROOT)),
        "note": "NEW path; dump-only helius_parity_tx_dump_ge10_20261001.csv untouched",
    }, indent=2) + "\n")

    md = [
        "# ge10 Path A re-enrich — recovery helpers ON — 2026-10-01",
        "",
        "SolDatos interrupt for SolQA/SolAuditor. **NEW paths** (dump-only audit trail kept).",
        "",
        "## Paths",
        f"- Features: `{OUT_FEAT.relative_to(ROOT)}`",
        f"- Mint enrich: `{OUT_MINT.relative_to(ROOT)}`",
        f"- Meta: `{OUT_META.relative_to(ROOT)}`",
        f"- Tx dump (recovery_on): `{OUT_TX.relative_to(ROOT)}`",
        f"- Dump-only audit (untouched): `{BEFORE_FEAT.relative_to(ROOT)}` + `{DUMP_GE.relative_to(ROOT)}`",
        "",
        "## Counts",
        f"- n_mints: **{len(prior)}**",
        f"- n_scoreable: **{n_ok}**",
        f"- n_trades_exact_vs_train: **{n_exact}/12**",
        f"- n_pyth_asof: **{n_pyth}**",
        f"- n_le_t0_false: **{n_le_false}**",
        "",
        "## Method",
        "- USD Path A: `resolve_sol_usd_for_scoring(require_pyth=True)` → sol_amt × pyth_asof",
        "- Scale 6.6×: **OFF**",
        "- Fetch: dump parse-by-sig **baseline** + `fetch_create_to_t0_txs` Enhanced+RPC+slot (**ON all 12**); best-of / merge",
        "- Parse: WSOL multi-leg + BC multi-buyer → `helius_trade_parse`",
        "- buy_vol_usd_60s: `buy_vol_60s_from_trades` window [t0−60s, t0]",
        "- Fixed T0 from ge10 prior / OOS t0_ts",
        "- paper_live / n=200 outputs: **not touched**",
        "",
        "## Before → after (trades/buys vs train)",
        "",
        "| mint | before trades/buys | after trades/buys | train | dump→rec→merged | fetch_mode | exact |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for r in rows_mint:
        m = r["mint"]
        b = before.get(m, {})
        bt = b.get("n_trades", "?")
        bb = b.get("n_buys", "?")
        md.append(
            f"| `{m[:12]}…` | {bt}/{bb} | {r.get('n_trades_le_t0')}/{r.get('n_buys_le_t0')} | "
            f"{r.get('train_buy_count')} | {r.get('dump_buys')}→{r.get('recovery_buys')}→{r.get('merged_buys')} | "
            f"{r.get('fetch_mode')} | {r.get('trades_exact')} |"
        )
    md.extend([
        "",
        "## Per-mint buy_vol_usd_60s (Path A)",
        "",
        "| mint | trades | buys | buy60 | sol_src | scoreable |",
        "|---|---:|---:|---:|---|---|",
    ])
    for r in rows_mint:
        md.append(
            f"| `{r['mint'][:12]}…` | {r.get('n_trades_le_t0')} | {r.get('n_buys_le_t0')} | "
            f"{r.get('buy_vol_usd_60s')} | {r.get('sol_usd_source')} | {r.get('scoreable')} |"
        )
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(md) + "\n")
    print(json.dumps(meta, indent=2), flush=True)
    print(f"wrote {OUT_FEAT}", flush=True)
    print(f"wrote {OUT_MD}", flush=True)
    return 0 if n_exact == 12 else 2


if __name__ == "__main__":
    raise SystemExit(main())
