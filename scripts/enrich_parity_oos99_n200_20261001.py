#!/usr/bin/env python3
"""SolDatos: enrich parity OOS≥0.99 n=200 cohort (2026-10-01).

Path A require_pyth. Recovery helpers ON (fetch_create_to_t0_txs / WSOL / slot±1).
Scale 6.6× OFF. Fixed OOS t0_ts. No paper_live process touch. No joblib scoring.
Checkpointed for restart.
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from features.post_q5_sets import FEATURE_SETS
from ingestion.bonding_curve import bonding_curve_pda
from ingestion.env import load_dotenv
from ingestion.helius_enhanced import HeliusEnhanced, fetch_create_to_t0_txs, filter_txs_le_t0
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

SAMPLE = ROOT / "data" / "samples" / "parity_oos99_n200_sample_20261001.csv"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
CKPT_DIR = ROOT / "data" / "samples" / "parity_oos99_n200_ckpt_20261001"
CKPT_JSONL = CKPT_DIR / "enrich_rows.jsonl"
CKPT_DONE = CKPT_DIR / "done_mints.txt"
CKPT_TX_DIR = CKPT_DIR / "tx_dumps"
OUT_ENRICH = ROOT / "data" / "samples" / "helius_parity_enrich_oos99_n200_20261001.csv"
OUT_ENRICH_META = ROOT / "data" / "samples" / "helius_parity_enrich_oos99_n200_20261001_meta.json"
OUT_TX = ROOT / "data" / "samples" / "helius_parity_tx_dump_oos99_n200_20261001.csv"
OUT_TX_META = ROOT / "data" / "samples" / "helius_parity_tx_dump_oos99_n200_20261001_meta.json"
OUT_FEAT = ROOT / "data" / "samples" / "helius_parity_features_oos99_n200_20261001.csv"
OUT_FEAT_META = ROOT / "data" / "samples" / "helius_parity_features_oos99_n200_20261001_meta.json"
OUT_MD = ROOT / "cycle0" / "diagnostics" / "parity-oos99-n200-enrich-20261001.md"

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


def _load_done() -> set[str]:
    if not CKPT_DONE.exists():
        return set()
    return {ln.strip() for ln in CKPT_DONE.read_text().splitlines() if ln.strip()}


def _append_done(mint: str) -> None:
    with CKPT_DONE.open("a") as f:
        f.write(mint + "\n")


def _append_row(row: dict[str, Any]) -> None:
    with CKPT_JSONL.open("a") as f:
        f.write(json.dumps(row, default=str) + "\n")


def _load_ckpt_rows() -> list[dict[str, Any]]:
    if not CKPT_JSONL.exists():
        return []
    rows = []
    for ln in CKPT_JSONL.read_text().splitlines():
        if ln.strip():
            rows.append(json.loads(ln))
    return rows


def _load_fs(mints: set[str]) -> dict[str, dict[str, Any]]:
    want = {
        "mint", "t0_ts", "create_ts", "creator_pubkey", "buy_vol_usd_60s",
        "buy_count_total", "net_sol_curve", "age_s", "mc_usd_t0",
        "name_len", "symbol_len",
    }
    out: dict[str, dict[str, Any]] = {}
    with FS_PATH.open() as f:
        reader = csv.DictReader(f)
        cols = [c for c in (reader.fieldnames or []) if c in want]
        for row in reader:
            m = row.get("mint")
            if m in mints:
                out[m] = {c: row.get(c) for c in cols}
    return out


def enrich_one(
    helius: HeliusEnhanced,
    rpc: HeliusRpc,
    *,
    mint: str,
    t0_ts_raw: str,
    oos_score: float,
    y: Any,
    train: dict[str, Any] | None,
    dump_txs: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    t0 = _parse_t0(t0_ts_raw)
    create_ts = t0
    creator = None
    train_buy_count = None
    if train:
        cts = train.get("create_ts")
        if cts and str(cts) not in ("", "nan", "None"):
            try:
                create_ts = _parse_t0(str(cts))
            except Exception:
                create_ts = t0
        cp = train.get("creator_pubkey")
        if cp and str(cp) not in ("", "nan", "None"):
            creator = str(cp)
        try:
            train_buy_count = float(train["buy_count_total"]) if train.get("buy_count_total") not in (None, "") else None
        except (TypeError, ValueError):
            train_buy_count = None

    bc = str(bonding_curve_pda(mint))

    q_score, reason = None, "unset"
    for _pyth_try in range(4):
        q_score, reason = resolve_sol_usd_for_scoring(
            as_of=t0, allow_network=True, require_pyth=True
        )
        if q_score is not None:
            break
        time.sleep(0.8 * (_pyth_try + 1))
    if q_score is None:
        rec = {
            "mint": mint,
            "t0_ts": t0_ts_raw,
            "oos_score": oos_score,
            "y": y,
            "n_trades_le_t0": 0,
            "n_buys_le_t0": 0,
            "buy_vol_usd_60s": None,
            "sol_usd": None,
            "sol_usd_source": None,
            "fetch_mode": None,
            "scoreable": False,
            "skip_reason": f"pyth_required:{reason}",
            "n_le_t0_false": 0,
            "train_buy_count": train_buy_count,
            "n_txs_le_t0": 0,
            "usd_reason": reason,
            "gaps": "",
            "error": None,
        }
        return rec, [], None

    sol_px = float(q_score.price)
    sol_src = str(q_score.source)
    assert apply_dune_helius_usd_scale_enabled() is False

    age0 = abs((_aware(t0) - _aware(create_ts)).total_seconds()) <= 120.0
    # Age≈0: mint Enhanced newest→oldest is mostly post-T0 spam — lean on BC+RPC+slot.
    # Escalate RPC/slot only when Enhanced under-recovers vs train buy count (BZof/4M3g path).
    enh_pages = 10 if age0 else 30
    rpc_pages = 30 if age0 else 20
    t_fetch0 = time.monotonic()
    txs, gaps = fetch_create_to_t0_txs(
        helius,
        mint,
        t0=t0,
        create_ts=create_ts,
        bonding_curve=bc,
        rpc=None,  # phase-1 Enhanced only
        max_pages_enhanced=enh_pages,
        max_pages_rpc=rpc_pages,
    )
    txs_le = filter_txs_le_t0(txs, t0)
    # Quick trade count probe (no USD needed for count; use sol_px already resolved)
    _probe = parse_helius_enhanced_txs(
        txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
    )
    n_probe = len([tr for tr in _probe if tr.ts <= t0])
    target = 2
    if train_buy_count is not None:
        try:
            target = max(2, int(float(train_buy_count)) - 1)
        except (TypeError, ValueError):
            target = 2
    fetch_mode = "enhanced_pre_t0"
    if n_probe < target or n_probe < 2:
        txs2, gaps2 = fetch_create_to_t0_txs(
            helius,
            mint,
            t0=t0,
            create_ts=create_ts,
            bonding_curve=bc,
            rpc=rpc,
            max_pages_enhanced=max(enh_pages, 20),
            max_pages_rpc=rpc_pages,
        )
        gaps = gaps + ["escalate_rpc"] + gaps2
        txs = txs2
        txs_le = filter_txs_le_t0(txs, t0)
        fetch_mode = "fetch_create_to_t0+rpc"
        if any("slot" in g for g in gaps2):
            fetch_mode = "fetch_create_to_t0+rpc+slot"
    fetch_s = time.monotonic() - t_fetch0

    t0_unix = int(_aware(t0).timestamp())
    n_le_false = 0
    for tx in txs_le:
        raw = tx.get("timestamp")
        if raw is None:
            continue
        try:
            if int(raw) > t0_unix:
                n_le_false += 1
        except (TypeError, ValueError):
            continue

    # Feature trades via paper wrapper (ingestion WSOL multi-leg under the hood)
    trades = parse_helius_enhanced_txs(
        txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
    )
    trades_use = [tr for tr in trades if tr.ts <= t0]
    buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
    buy60 = maybe_scale_usd(float(buy60))  # identity when scale OFF
    q5a = aggregate_q5a_for_mint(trades_use, t0)
    create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
    q5b = q5b_from_create(create, t0, prior_creates=[])
    age_s = max(0.0, (_aware(t0) - _aware(create_ts)).total_seconds())

    n_buys = sum(1 for tr in trades_use if tr.side == "buy")
    scoreable = len(trades_use) >= 1 and sol_src.startswith("pyth")
    skip_reason = None
    if not scoreable:
        if len(trades_use) < 1:
            skip_reason = "no_trades_le_t0"
        elif not sol_src.startswith("pyth"):
            skip_reason = f"sol_src_not_pyth:{sol_src}"

    rec: dict[str, Any] = {
        "mint": mint,
        "t0_ts": t0_ts_raw,
        "oos_score": oos_score,
        "y": y,
        "n_trades_le_t0": len(trades_use),
        "n_buys_le_t0": n_buys,
        "buy_vol_usd_60s": float(buy60),
        "buy_count_60s": int(buy_n),
        "sol_usd": sol_px,
        "sol_usd_source": sol_src,
        "fetch_mode": fetch_mode,
        "scoreable": bool(scoreable),
        "skip_reason": skip_reason,
        "n_le_t0_false": int(n_le_false),
        "train_buy_count": train_buy_count,
        "n_txs_le_t0": len(txs_le),
        "create_ts": create_ts.strftime("%Y-%m-%d %H:%M:%S.000 UTC"),
        "creator_pubkey": creator,
        "age_s": age_s,
        "net_sol_curve": q5a.get("net_sol_curve"),
        "buy_count_total": q5a.get("buy_count_total"),
        "usd_reason": reason,
        "fetch_s": round(fetch_s, 2),
        "helius_calls": helius.n_calls,
        "n_retries_429": helius.log.n_retries_429,
        "gaps": " | ".join(gaps[:12]),
        "error": None,
        "apply_dune_helius_usd_scale": False,
    }

    # Feature row for SolModelos
    feats: dict[str, Any] = {
        "mint": mint,
        "t0_ts": t0_ts_raw,
        "oos_score": oos_score,
        "y": y,
        "sol_usd": sol_px,
        "sol_usd_source": sol_src,
        "scoreable": bool(scoreable),
        **{c: q5b.get(c) for c in q5b},
        **q5a,
        "buy_vol_usd_60s": float(buy60),
        "age_s": age_s if age_s is not None else q5b.get("age_s"),
    }
    # Ensure all +q5b cols present
    for c in Q5B_COLS:
        feats.setdefault(c, None)

    dump_rows: list[dict[str, Any]] = []
    # Prefer dump for scoreable (or empty for QA). Skip bulky non-scoreable with txs.
    if dump_txs and (scoreable or len(trades_use) == 0):
        parsed_all = parse_ingestion(
            txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=None
        )
        # Map by approximating: re-parse is heavy; instead annotate from trades_use + sigs
        # Build sig→trade from per-tx only for ≤80 txs (typical create→t0 snipers)
        by_sig: dict[str, Any] = {}
        if len(txs_le) <= 80:
            for tx in txs_le:
                sig = str(tx.get("signature") or "")
                if not sig:
                    continue
                one = parse_ingestion([tx], mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=None)
                if one:
                    by_sig[sig] = max(one, key=lambda r: (r.side == "buy", r.amount_usd))
        for tx in txs_le:
            sig = str(tx.get("signature") or "")
            if not sig:
                continue
            ts_raw = tx.get("timestamp")
            if ts_raw is None:
                continue
            try:
                ts_i = int(ts_raw)
            except (TypeError, ValueError):
                continue
            if ts_i > t0_unix:
                continue
            tr = by_sig.get(sig)
            dump_rows.append({
                "mint": mint,
                "tx_sig": sig,
                "ts": _iso_from_unix(ts_i),
                "t0_ts": t0_ts_raw,
                "le_t0": True,
                "source": str(tx.get("source") or ""),
                "side": getattr(tr, "side", "") if tr else "",
                "sol_amt": getattr(tr, "sol_amt", "") if tr else "",
                "parsed_as_trade": bool(tr),
                "addr_source": "create_to_t0",
            })

    return rec, dump_rows, feats


def _write_outputs(
    enrich_rows: list[dict[str, Any]],
    *,
    n_sample: int,
    started: float,
    partial: bool,
) -> None:
    # Dedupe by mint keeping last
    by_mint: dict[str, dict] = {}
    for r in enrich_rows:
        by_mint[str(r["mint"])] = r
    rows = list(by_mint.values())

    # Stable order by sample
    sample = list(csv.DictReader(SAMPLE.open()))
    order = {r["mint"]: i for i, r in enumerate(sample)}
    rows.sort(key=lambda r: order.get(str(r["mint"]), 10**9))

    fieldnames = [
        "mint", "t0_ts", "oos_score", "y", "n_trades_le_t0", "n_buys_le_t0",
        "buy_vol_usd_60s", "buy_count_60s", "sol_usd", "sol_usd_source",
        "fetch_mode", "scoreable", "skip_reason", "n_le_t0_false",
        "train_buy_count", "n_txs_le_t0", "create_ts", "creator_pubkey",
        "age_s", "net_sol_curve", "buy_count_total", "usd_reason",
        "fetch_s", "helius_calls", "n_retries_429", "gaps", "error",
        "apply_dune_helius_usd_scale",
    ]
    with OUT_ENRICH.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    n_done = len(rows)
    n_ok = sum(1 for r in rows if r.get("scoreable"))
    n_pyth = sum(1 for r in rows if str(r.get("sol_usd_source") or "").startswith("pyth"))
    n_le_false = sum(int(r.get("n_le_t0_false") or 0) for r in rows)
    skip_modes: dict[str, int] = {}
    for r in rows:
        if not r.get("scoreable"):
            k = str(r.get("skip_reason") or r.get("error") or "unknown")
            skip_modes[k] = skip_modes.get(k, 0) + 1
    src_counts: dict[str, int] = {}
    for r in rows:
        s = str(r.get("sol_usd_source") or "none")
        src_counts[s] = src_counts.get(s, 0) + 1

    # Merge tx dumps from ckpt dir
    tx_paths = sorted(CKPT_TX_DIR.glob("*.csv")) if CKPT_TX_DIR.exists() else []
    n_tx_rows = 0
    n_tx_mints = 0
    n_tx_le_false = 0
    if tx_paths:
        with OUT_TX.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=DUMP_COLS)
            w.writeheader()
            seen_m = set()
            for p in tx_paths:
                with p.open() as rf:
                    for row in csv.DictReader(rf):
                        w.writerow({c: row.get(c, "") for c in DUMP_COLS})
                        n_tx_rows += 1
                        seen_m.add(row.get("mint"))
                        if str(row.get("le_t0")).lower() in ("false", "0"):
                            n_tx_le_false += 1
            n_tx_mints = len(seen_m)
        OUT_TX_META.write_text(json.dumps({
            "n_rows": n_tx_rows,
            "n_mints": n_tx_mints,
            "n_le_t0_false": n_tx_le_false,
            "partial": partial,
            "out": str(OUT_TX.relative_to(ROOT)),
        }, indent=2) + "\n")

    # Feature matrix from ckpt feat jsonl if present
    feat_path = CKPT_DIR / "features.jsonl"
    n_feat = 0
    if feat_path.exists():
        feat_rows = []
        for ln in feat_path.read_text().splitlines():
            if ln.strip():
                feat_rows.append(json.loads(ln))
        # dedupe
        fb: dict[str, dict] = {}
        for r in feat_rows:
            fb[str(r["mint"])] = r
        feat_list = sorted(fb.values(), key=lambda r: order.get(str(r["mint"]), 10**9))
        # columns: mint + meta + Q5B
        cols = ["mint", "t0_ts", "oos_score", "y", "sol_usd", "sol_usd_source", "scoreable"] + Q5B_COLS
        # also keep extras present
        extra = sorted({k for r in feat_list for k in r.keys() if k not in cols})
        all_cols = cols + extra
        with OUT_FEAT.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=all_cols, extrasaction="ignore")
            w.writeheader()
            for r in feat_list:
                w.writerow(r)
                n_feat += 1
        OUT_FEAT_META.write_text(json.dumps({
            "n_rows": n_feat,
            "n_q5b_cols": len(Q5B_COLS),
            "partial": partial,
            "out": str(OUT_FEAT.relative_to(ROOT)),
        }, indent=2) + "\n")

    meta = {
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_sample": n_sample,
        "n_done": n_done,
        "n_enriched_ok": n_ok,
        "n_scoreable": n_ok,
        "n_pyth_asof": n_pyth,
        "n_le_t0_false": n_le_false,
        "partial": partial,
        "sol_usd_sources": src_counts,
        "skip_reasons": skip_modes,
        "elapsed_s": round(time.time() - started, 1),
        "scale_6_6x": False,
        "path_a": "require_pyth",
        "recovery": "fetch_create_to_t0_txs (WSOL multi-leg + slot±1)",
        "sample_csv": str(SAMPLE.relative_to(ROOT)),
        "enrich_csv": str(OUT_ENRICH.relative_to(ROOT)),
        "tx_dump_csv": str(OUT_TX.relative_to(ROOT)) if OUT_TX.exists() else None,
        "features_csv": str(OUT_FEAT.relative_to(ROOT)) if OUT_FEAT.exists() else None,
        "n_tx_rows": n_tx_rows,
        "n_tx_mints": n_tx_mints,
        "n_tx_le_t0_false": n_tx_le_false,
        "n_feat_rows": n_feat,
        "checkpoint_dir": str(CKPT_DIR.relative_to(ROOT)),
    }
    OUT_ENRICH_META.write_text(json.dumps(meta, indent=2) + "\n")

    # MD report
    lines = [
        "# Parity OOS≥0.99 n=200 enrich — 2026-10-01",
        "",
        f"- Sample: `{SAMPLE.relative_to(ROOT)}` (n={n_sample})",
        f"- Enrich: `{OUT_ENRICH.relative_to(ROOT)}` (n_done={n_done}, partial={partial})",
        f"- Tx dump: `{OUT_TX.relative_to(ROOT) if OUT_TX.exists() else 'pending'}`",
        f"- Features: `{OUT_FEAT.relative_to(ROOT) if OUT_FEAT.exists() else 'pending'}`",
        f"- Checkpoint: `{CKPT_DIR.relative_to(ROOT)}`",
        "",
        "## Counts",
        f"- n_sample: **{n_sample}**",
        f"- n_done / enriched: **{n_done}**",
        f"- n_scoreable: **{n_ok}**",
        f"- n_pyth_asof: **{n_pyth}**",
        f"- n_le_t0_false (mint-level): **{n_le_false}**",
        f"- n_tx_le_t0_false (dump): **{n_tx_le_false}**",
        f"- elapsed_s: {meta['elapsed_s']}",
        "",
        "## Path A / ops",
        "- USD: `resolve_sol_usd_for_scoring(require_pyth=True)` → amount_usd = sol_amt × pyth_asof",
        "- Scale 6.6×: **OFF**",
        "- Recovery: `fetch_create_to_t0_txs` (BC Enhanced + RPC window + getBlock±1)",
        "- Parse: `helius_trade_parse` WSOL multi-leg (via paper wrapper + direct for dump)",
        "- Fixed T0 from OOS `t0_ts` (no refine look-ahead)",
        "- Paper live: **not touched**; SolModelos joblib: **not touched**",
        "",
        "## sol_usd_source",
        "```",
        json.dumps(src_counts, indent=2),
        "```",
        "",
        "## skip / failure modes",
        "```",
        json.dumps(skip_modes, indent=2),
        "```",
        "",
        "## Paths",
        f"- `{OUT_ENRICH.relative_to(ROOT)}`",
        f"- `{OUT_ENRICH_META.relative_to(ROOT)}`",
    ]
    if OUT_TX.exists():
        lines.append(f"- `{OUT_TX.relative_to(ROOT)}`")
        lines.append(f"- `{OUT_TX_META.relative_to(ROOT)}`")
    if OUT_FEAT.exists():
        lines.append(f"- `{OUT_FEAT.relative_to(ROOT)}`")
        lines.append(f"- `{OUT_FEAT_META.relative_to(ROOT)}`")
    lines.append(f"- `{OUT_MD.relative_to(ROOT)}`")
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text("\n".join(lines) + "\n")
    print(json.dumps(meta, indent=2), flush=True)


def main() -> int:
    load_dotenv()
    os.environ["APPLY_DUNE_HELIUS_USD_SCALE"] = "0"
    assert apply_dune_helius_usd_scale_enabled() is False

    CKPT_DIR.mkdir(parents=True, exist_ok=True)
    CKPT_TX_DIR.mkdir(parents=True, exist_ok=True)

    sample = list(csv.DictReader(SAMPLE.open()))
    n_sample = len(sample)
    assert n_sample == 200, n_sample
    mints = {r["mint"] for r in sample}
    train_by = _load_fs(mints)
    done = _load_done()
    started = time.time()
    soft_deadline_s = float(os.environ.get("PARITY_ENRICH_DEADLINE_S", str(110 * 60)))

    print(
        f"enrich start n={n_sample} done={len(done)} scale_off "
        f"deadline_s={soft_deadline_s}",
        flush=True,
    )

    # Dump txs for scoreable (or all until rate-limit); start with all, trim if needed
    dump_all = True

    with HeliusEnhanced(max_calls=20000, max_retries_429=12, min_interval_s=0.25) as helius, HeliusRpc() as rpc:
        for i, row in enumerate(sample, 1):
            mint = row["mint"]
            if mint in done:
                continue
            elapsed = time.time() - started
            if elapsed > soft_deadline_s:
                print(f"timebox stop at {i}/{n_sample} elapsed={elapsed:.0f}s", flush=True)
                break
            oos = float(row["oos_score"])
            y = row.get("y")
            t0_ts = row["t0_ts"]
            print(f"[{i}/{n_sample}] {mint[:16]}… oos={oos:.4f}", flush=True)
            try:
                rec, dump_rows, feats = enrich_one(
                    helius,
                    rpc,
                    mint=mint,
                    t0_ts_raw=t0_ts,
                    oos_score=oos,
                    y=y,
                    train=train_by.get(mint),
                    dump_txs=dump_all and True,  # dump while building; prioritize scoreable later
                )
            except Exception as e:  # noqa: BLE001
                rec = {
                    "mint": mint,
                    "t0_ts": t0_ts,
                    "oos_score": oos,
                    "y": y,
                    "n_trades_le_t0": 0,
                    "n_buys_le_t0": 0,
                    "buy_vol_usd_60s": None,
                    "sol_usd": None,
                    "sol_usd_source": None,
                    "fetch_mode": None,
                    "scoreable": False,
                    "skip_reason": f"exception:{type(e).__name__}",
                    "n_le_t0_false": 0,
                    "train_buy_count": (train_by.get(mint) or {}).get("buy_count_total"),
                    "n_txs_le_t0": 0,
                    "error": str(e)[:240],
                    "gaps": traceback.format_exc()[-400:],
                    "apply_dune_helius_usd_scale": False,
                }
                dump_rows, feats = [], None
                print(f"  ERR {e}", flush=True)
            else:
                print(
                    f"  trades={rec['n_trades_le_t0']} buys={rec['n_buys_le_t0']} "
                    f"buy60={rec.get('buy_vol_usd_60s')} sol={rec.get('sol_usd_source')} "
                    f"scoreable={rec['scoreable']} le_false={rec['n_le_t0_false']} "
                    f"calls={helius.n_calls}",
                    flush=True,
                )

            _append_row(rec)
            _append_done(mint)
            if feats is not None:
                with (CKPT_DIR / "features.jsonl").open("a") as ff:
                    ff.write(json.dumps(feats, default=str) + "\n")
            if dump_rows:
                # Prefer dump for scoreable; also dump non-scoreable for QA of failures
                if rec.get("scoreable") or len(dump_rows) <= 500:
                    tp = CKPT_TX_DIR / f"{mint}.csv"
                    with tp.open("w", newline="") as tf:
                        w = csv.DictWriter(tf, fieldnames=DUMP_COLS)
                        w.writeheader()
                        w.writerows(dump_rows)

            # periodic flush of aggregate outputs
            if i % 10 == 0 or i == n_sample:
                rows_so_far = _load_ckpt_rows()
                _write_outputs(
                    rows_so_far,
                    n_sample=n_sample,
                    started=started,
                    partial=len(rows_so_far) < n_sample,
                )

    rows_final = _load_ckpt_rows()
    partial = len({r["mint"] for r in rows_final}) < n_sample
    _write_outputs(rows_final, n_sample=n_sample, started=started, partial=partial)
    print(f"done n_ckpt={len(rows_final)} partial={partial}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
