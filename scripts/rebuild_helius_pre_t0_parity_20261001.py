#!/usr/bin/env python3
"""Rebuild ≤T0 Helius features with SolDatos ingestion helpers (2026-10-01).

Uses OOS t0_ts as fixed T0 (refine_t0=False — no look-ahead). Scale Dune 6.6× OFF.
Does NOT edit paper_live; imports parse/q5a for feature columns only.

Outputs:
  data/samples/helius_rebuild_pre_t0_parity_20261001.csv
  data/samples/helius_rebuild_pre_t0_parity_20261001_meta.json
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.chdir(ROOT)

from ingestion.bonding_curve import bonding_curve_pda
from ingestion.env import load_dotenv
from ingestion.helius_enhanced import (
    DEFAULT_MAX_PAGES_PRE_T0,
    HeliusEnhanced,
    fetch_pre_t0_enhanced_txs,
    filter_txs_le_t0,
    merge_tx_lists,
)
from ingestion.helius_rpc import HeliusRpc
from ingestion.sol_usd_oracle import (
    apply_dune_helius_usd_scale_enabled,
    maybe_scale_usd,
    resolve_sol_usd,
)
from paper_live.helius_enrich import buy_vol_60s_from_trades, parse_helius_enhanced_txs
from paper_live.q5a_agg import aggregate_q5a_for_mint
from paper_live.q5b_agg import CreateRow, q5b_from_create

import httpx

ROBUST_CSV = ROOT / "cycle0" / "artifacts" / "helius_historical_replay_robust.csv"
# Fallback path mentioned in task
ROBUST_CSV_ALT = ROOT / "cycle0" / "diagnostics" / "helius_historical_replay_robust.csv"
FS_PATH = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
SAMPLE_TRAIN = ROOT / "cycle0" / "artifacts" / "sample_train_rescore.csv"
OUT_CSV = ROOT / "data" / "samples" / "helius_rebuild_pre_t0_parity_20261001.csv"
OUT_META = ROOT / "data" / "samples" / "helius_rebuild_pre_t0_parity_20261001_meta.json"
NOTE_MD = ROOT / "cycle0" / "live-helius-rebuild-parity-20261001.md"

# Prefer highs first, then mid/low if budget allows
BAND_ORDER = {"high_ge0.99": 0, "mid_~0.5": 1, "low_~0.1": 2}


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "+00:00").replace("Z", "+00:00").strip()
    return _aware(datetime.fromisoformat(s))


def _load_robust() -> list[dict[str, str]]:
    path = ROBUST_CSV if ROBUST_CSV.exists() else ROBUST_CSV_ALT
    with path.open() as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: BAND_ORDER.get(str(r.get("band") or ""), 9))
    return rows


def _load_train_store(mints: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not FS_PATH.exists():
        return out
    want = {
        "mint",
        "t0_ts",
        "create_ts",
        "creator_pubkey",
        "buy_vol_usd_60s",
        "net_sol_curve",
        "buy_count_total",
        "age_s",
        "mc_usd_t0",
        "sniper_vol_share_5s",
        "progress_curve_proxy",
    }
    with FS_PATH.open() as f:
        reader = csv.DictReader(f)
        cols = [c for c in (reader.fieldnames or []) if c in want]
        for row in reader:
            m = row.get("mint")
            if m in mints:
                out[m] = {c: row.get(c) for c in cols}
    return out


def _load_sample_train(mints: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not SAMPLE_TRAIN.exists():
        return out
    with SAMPLE_TRAIN.open() as f:
        for row in csv.DictReader(f):
            m = row.get("mint")
            if m in mints:
                out[m] = row
    return out


def _tx_ts_stats(txs: list[dict[str, Any]], t0: datetime) -> dict[str, Any]:
    t0u = int(_aware(t0).timestamp())
    ts_list: list[int] = []
    n_gt = 0
    for tx in txs:
        raw = tx.get("timestamp")
        if raw is None:
            continue
        try:
            tsi = int(raw)
        except (TypeError, ValueError):
            continue
        ts_list.append(tsi)
        if tsi > t0u:
            n_gt += 1
    return {
        "n_txs_gt_t0": n_gt,
        "max_tx_ts": max(ts_list) if ts_list else None,
        "min_tx_ts": min(ts_list) if ts_list else None,
        "t0_unix": t0u,
    }


def _parse_gaps_meta(gaps: list[str]) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "gaps": gaps[:20],
        "partial_429": any("partial" in g for g in gaps),
        "sources_merged": any("helius_merged" in g for g in gaps),
        "bc_pages": None,
        "mint_pages": None,
        "bc_stop": None,
        "mint_stop": None,
        "reached_floor": False,
        "max_pages_cap": DEFAULT_MAX_PAGES_PRE_T0,
    }
    for g in gaps:
        if g.startswith("helius_bc:pages="):
            # helius_bc:pages=N stop=REASON
            try:
                rest = g[len("helius_bc:pages=") :]
                pages_s, _, stop_part = rest.partition(" stop=")
                meta["bc_pages"] = int(pages_s.split()[0])
                meta["bc_stop"] = stop_part.split()[0] if stop_part else None
                if "floor" in stop_part:
                    meta["reached_floor"] = True
            except ValueError:
                pass
        elif g.startswith("helius_mint:pages="):
            try:
                rest = g[len("helius_mint:pages=") :]
                pages_s, _, stop_part = rest.partition(" stop=")
                meta["mint_pages"] = int(pages_s.split()[0])
                meta["mint_stop"] = stop_part.split()[0] if stop_part else None
                if "floor" in stop_part:
                    meta["reached_floor"] = True
            except ValueError:
                pass
    return meta



def _parse_by_sigs(helius: HeliusEnhanced, sigs: list[str]) -> list[dict[str, Any]]:
    """Enhanced parse-transactions by signature (≤100/chunk)."""
    key = helius._api_key  # noqa: SLF001 — rebuild only; never logged
    url = "https://api.helius.xyz/v0/transactions/"
    out: list[dict[str, Any]] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(sigs), 100):
            chunk = sigs[i : i + 100]
            for attempt in range(5):
                helius._throttle()  # noqa: SLF001
                resp = client.post(url, params={"api-key": key}, json={"transactions": chunk})
                helius.log.n_calls += 1
                helius.log.status_codes.append(resp.status_code)
                if resp.status_code == 429:
                    helius.log.n_retries_429 += 1
                    time.sleep(min(20.0, 0.8 * (2 ** attempt)))
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, list):
                    out.extend(body)
                break
            else:
                # keep partial
                break
    return out


def _rpc_window_txs(
    mint: str,
    *,
    t0: datetime,
    create_ts: datetime,
    helius: HeliusEnhanced,
    rpc: HeliusRpc,
    max_pages: int = 40,
) -> tuple[list[dict[str, Any]], str]:
    hi = int(_aware(t0).timestamp())
    lo = int(_aware(create_ts).timestamp()) - 5
    sigs, reason = rpc.collect_signatures_in_window(
        mint,
        max_block_time=hi,
        min_block_time=lo,
        max_pages=max_pages,
        page_limit=1000,
    )
    if not sigs:
        return [], f"rpc_empty:{reason}"
    sig_list = [str(s["signature"]) for s in sigs if s.get("signature")]
    txs = _parse_by_sigs(helius, sig_list)
    return txs, f"rpc_window n_sigs={len(sig_list)} reason={reason}"


def rebuild_one(
    client: HeliusEnhanced,
    rpc: HeliusRpc,
    *,
    mint: str,
    band: str,
    t0_ts_raw: str,
    robust: dict[str, str],
    train: dict[str, Any] | None,
    sample_tr: dict[str, Any] | None,
) -> dict[str, Any]:
    t0 = _parse_t0(t0_ts_raw)
    create_ts = None
    creator = None
    if train:
        cts = train.get("create_ts")
        if cts:
            try:
                create_ts = _parse_t0(str(cts))
            except Exception:
                create_ts = None
        cp = train.get("creator_pubkey")
        if cp:
            creator = str(cp)
    if create_ts is None:
        # age≈0 snipers: create ≈ t0 (matches train store for highs)
        create_ts = t0

    bc = str(bonding_curve_pda(mint))
    quote = resolve_sol_usd(None, allow_network=True, as_of=t0)
    sol_px = float(quote.price)
    sol_src = str(quote.source)

    assert apply_dune_helius_usd_scale_enabled() is False

    # Age≈0 snipers: mint Enhanced crawl is buried under post-T0 — cap mint pages;
    # prefer BC + RPC signature window [create, t0] recovery (live T0≈now does not need this).
    age0 = abs((_aware(t0) - _aware(create_ts)).total_seconds()) <= 2.0
    mint_pages = 5 if age0 else DEFAULT_MAX_PAGES_PRE_T0
    t_fetch0 = time.monotonic()
    txs_le, gaps = fetch_pre_t0_enhanced_txs(
        client,
        mint,
        t0=t0,
        create_ts=create_ts,
        bonding_curve=bc,
        max_pages=mint_pages,
        limit=100,
    )
    fetch_mode = "enhanced_pre_t0"
    if len(txs_le) < 5:
        extra, why = _rpc_window_txs(
            mint, t0=t0, create_ts=create_ts, helius=client, rpc=rpc, max_pages=45
        )
        gaps.append(why)
        if extra:
            txs_le = filter_txs_le_t0(merge_tx_lists(txs_le, extra), t0)
            fetch_mode = "enhanced+rpc_sig_window"
            gaps.append(f"after_rpc_merge le_t0={len(txs_le)}")
    fetch_s = time.monotonic() - t_fetch0
    gap_meta = _parse_gaps_meta(gaps)
    gap_meta["fetch_mode"] = fetch_mode
    gap_meta["max_pages_cap"] = mint_pages

    # QA: helper already filtered; re-check + also verify raw-style stats on kept set
    qa = _tx_ts_stats(txs_le, t0)
    # Double-filter to be sure
    txs_le2 = filter_txs_le_t0(txs_le, t0)
    assert len(txs_le2) == len(txs_le)

    trades = parse_helius_enhanced_txs(
        txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
    )
    # refine_t0=False: keep OOS t0
    trades_use = [tr for tr in trades if tr.ts <= t0]
    q5a = aggregate_q5a_for_mint(trades_use, t0)
    buy60, buy_n = buy_vol_60s_from_trades(trades_use, t0)
    buy60 = maybe_scale_usd(float(buy60))  # identity when scale OFF

    create = CreateRow(mint=mint, creator_pubkey=creator, create_ts=create_ts)
    q5b = q5b_from_create(create, t0, prior_creates=[])

    # age_s from create→t0
    age_s = max(0.0, (_aware(t0) - _aware(create_ts)).total_seconds()) if create_ts else None

    train_buy60 = None
    train_net = None
    train_buy_n = None
    if train:
        try:
            train_buy60 = float(train["buy_vol_usd_60s"]) if train.get("buy_vol_usd_60s") not in (None, "") else None
        except (TypeError, ValueError):
            train_buy60 = None
        try:
            train_net = float(train["net_sol_curve"]) if train.get("net_sol_curve") not in (None, "") else None
        except (TypeError, ValueError):
            train_net = None
        try:
            train_buy_n = float(train["buy_count_total"]) if train.get("buy_count_total") not in (None, "") else None
        except (TypeError, ValueError):
            train_buy_n = None

    oos_score = None
    train_store_rescore = None
    if sample_tr:
        try:
            oos_score = float(sample_tr.get("oos_score") or sample_tr.get("score") or "")
        except (TypeError, ValueError):
            oos_score = None
        try:
            train_store_rescore = float(sample_tr.get("train_store_rescore") or "")
        except (TypeError, ValueError):
            train_store_rescore = None
    if oos_score is None:
        try:
            oos_score = float(robust.get("oos_score") or "")
        except (TypeError, ValueError):
            oos_score = None
    if train_store_rescore is None:
        try:
            train_store_rescore = float(robust.get("train_store_rescore") or "")
        except (TypeError, ValueError):
            train_store_rescore = None

    old_n_trades = None
    try:
        old_n_trades = int(float(robust.get("n_trades_pre_t0") or ""))
    except (TypeError, ValueError):
        old_n_trades = None
    old_buy_vol = None
    try:
        old_buy_vol = float(robust.get("buy_vol_live") or "")
    except (TypeError, ValueError):
        old_buy_vol = None

    max_tx_iso = None
    if qa["max_tx_ts"] is not None:
        max_tx_iso = datetime.fromtimestamp(int(qa["max_tx_ts"]), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.000 UTC"
        )

    rec: dict[str, Any] = {
        "mint": mint,
        "band": band,
        "t0_ts": t0_ts_raw,
        "t0_unix": qa["t0_unix"],
        "refine_t0": False,
        "create_ts": create_ts.strftime("%Y-%m-%d %H:%M:%S.000 UTC") if create_ts else None,
        "bonding_curve": bc,
        "sol_usd": sol_px,
        "sol_usd_source": sol_src,
        "apply_dune_helius_usd_scale": False,
        "n_txs_le_t0": len(txs_le),
        "n_trades_le_t0": len(trades_use),
        "n_buys_le_t0": sum(1 for tr in trades_use if tr.side == "buy"),
        "n_sells_le_t0": sum(1 for tr in trades_use if tr.side == "sell"),
        "buy_vol_usd_60s": float(buy60),
        "buy_count_60s": int(buy_n),
        "net_sol_curve": q5a.get("net_sol_curve"),
        "buy_count_total": q5a.get("buy_count_total"),
        "sell_count_total": q5a.get("sell_count_total"),
        "buy_vol_usd_total": q5a.get("buy_vol_usd_total"),
        "buy_vol_usd_30s": q5a.get("buy_vol_usd_30s"),
        "buy_vol_usd_15m": q5a.get("buy_vol_usd_15m"),
        "unique_buyers_total": q5a.get("unique_buyers_total"),
        "unique_sellers_total": q5a.get("unique_sellers_total"),
        "max_buy_usd": q5a.get("max_buy_usd"),
        "max_buy_sol": q5a.get("max_buy_sol"),
        "sniper_vol_share_5s": q5a.get("sniper_vol_share_5s"),
        "first5_buy_vol_share": q5a.get("first5_buy_vol_share"),
        "progress_curve_proxy": q5a.get("progress_curve_proxy"),
        "age_proxy_s": q5a.get("age_proxy_s"),
        "age_s": age_s if age_s is not None else q5b.get("age_s"),
        "migrated_pre_t0": q5a.get("migrated_pre_t0"),
        # Q5b stubs (no Pump live priors in this rebuild)
        "name_len": q5b.get("name_len"),
        "symbol_len": q5b.get("symbol_len"),
        "creator_prior_mints_all_in_window": q5b.get("creator_prior_mints_all_in_window"),
        # QA anti look-ahead
        "n_txs_gt_t0": qa["n_txs_gt_t0"],
        "max_tx_ts": max_tx_iso,
        "min_tx_ts_unix": qa["min_tx_ts"],
        "max_tx_ts_unix": qa["max_tx_ts"],
        # meta pages
        "max_pages": gap_meta["max_pages_cap"],
        "fetch_mode": gap_meta.get("fetch_mode"),
        "bc_pages": gap_meta["bc_pages"],
        "mint_pages": gap_meta["mint_pages"],
        "bc_stop": gap_meta["bc_stop"],
        "mint_stop": gap_meta["mint_stop"],
        "reached_floor": gap_meta["reached_floor"],
        "sources_merged": gap_meta["sources_merged"],
        "partial_429": gap_meta["partial_429"],
        "gaps_joined": " | ".join(gaps[:12]),
        "fetch_s": round(fetch_s, 2),
        "helius_calls_after": client.n_calls,
        "n_retries_429": client.log.n_retries_429,
        # comparison vs old robust / train
        "old_robust_n_trades_pre_t0": old_n_trades,
        "old_robust_buy_vol_live": old_buy_vol,
        "train_buy_vol_usd_60s": train_buy60,
        "train_net_sol_curve": train_net,
        "train_buy_count_total": train_buy_n,
        "oos_score": oos_score,
        "train_store_rescore": train_store_rescore,
    }
    return rec


def main() -> int:
    load_dotenv()
    # Force scale OFF for this rebuild regardless of ambient env mistakes
    os.environ["APPLY_DUNE_HELIUS_USD_SCALE"] = "0"
    assert apply_dune_helius_usd_scale_enabled() is False

    robust_rows = _load_robust()
    mints = {r["mint"] for r in robust_rows}
    train_by = _load_train_store(mints)
    sample_by = _load_sample_train(mints)

    # Timebox: all 5 from robust if budget allows; highs are required
    picks = list(robust_rows)  # already sorted high→mid→low
    max_calls = 500  # soft budget across all mints
    results: list[dict[str, Any]] = []
    started = time.time()
    soft_deadline_s = 25 * 60  # 25 min wall clock

    print(
        f"rebuild start n_picks={len(picks)} scale_off={not apply_dune_helius_usd_scale_enabled()} "
        f"max_pages={DEFAULT_MAX_PAGES_PRE_T0}",
        flush=True,
    )

    with HeliusEnhanced(max_calls=max_calls, max_retries_429=6, min_interval_s=0.3) as client, HeliusRpc() as rpc:
        for i, row in enumerate(picks):
            elapsed = time.time() - started
            # Always finish the 3 highs; skip mid/low if timeboxing
            if i >= 3 and elapsed > soft_deadline_s * 0.7:
                print(f"timebox skip remaining from {row['mint'][:12]}…", flush=True)
                break
            mint = row["mint"]
            print(f"[{i+1}/{len(picks)}] {mint[:16]}… band={row.get('band')} t0={row.get('t0_ts')}", flush=True)
            try:
                rec = rebuild_one(
                    client,
                    rpc,
                    mint=mint,
                    band=str(row.get("band") or ""),
                    t0_ts_raw=str(row["t0_ts"]),
                    robust=row,
                    train=train_by.get(mint),
                    sample_tr=sample_by.get(mint),
                )
            except Exception as e:  # noqa: BLE001
                rec = {
                    "mint": mint,
                    "band": row.get("band"),
                    "t0_ts": row.get("t0_ts"),
                    "error": str(e)[:240],
                    "n_txs_gt_t0": None,
                    "n_trades_le_t0": None,
                    "sol_usd_source": None,
                    "helius_calls_after": client.n_calls,
                    "n_retries_429": client.log.n_retries_429,
                }
                print(f"  ERR {e}", flush=True)
            else:
                print(
                    f"  trades={rec['n_trades_le_t0']} txs={rec['n_txs_le_t0']} "
                    f"buy60={rec['buy_vol_usd_60s']:.2f} (train={rec.get('train_buy_vol_usd_60s')}) "
                    f"gt_t0={rec['n_txs_gt_t0']} sol={rec['sol_usd']:.2f}({rec['sol_usd_source']}) "
                    f"bc_p={rec.get('bc_pages')} mint_p={rec.get('mint_pages')} "
                    f"partial={rec.get('partial_429')} calls={rec['helius_calls_after']}",
                    flush=True,
                )
            results.append(rec)
            # Ensure minima: if we have 3 highs done and calls high, may continue for mid/low
            if client.n_calls >= max_calls - 20:
                print("call budget near cap — stop", flush=True)
                break

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    # Flatten for CSV
    if results:
        # stable column order: union of keys
        keys: list[str] = []
        seen: set[str] = set()
        preferred = [
            "mint",
            "band",
            "t0_ts",
            "refine_t0",
            "sol_usd",
            "sol_usd_source",
            "n_txs_le_t0",
            "n_trades_le_t0",
            "buy_vol_usd_60s",
            "net_sol_curve",
            "n_txs_gt_t0",
            "max_tx_ts",
            "t0_unix",
            "max_pages",
            "reached_floor",
            "sources_merged",
            "partial_429",
            "old_robust_n_trades_pre_t0",
            "train_buy_vol_usd_60s",
            "oos_score",
        ]
        for k in preferred:
            if any(k in r for r in results) and k not in seen:
                keys.append(k)
                seen.add(k)
        for r in results:
            for k in r:
                if k not in seen:
                    keys.append(k)
                    seen.add(k)
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            for r in results:
                w.writerow({k: r.get(k) for k in keys})

    ok = [r for r in results if r.get("error") is None and r.get("n_trades_le_t0") is not None]
    qa_all_zero = all(int(r.get("n_txs_gt_t0") or 0) == 0 for r in ok) if ok else False
    meta = {
        "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_mints": len(results),
        "n_ok": len(ok),
        "n_txs_gt_t0_all_zero": qa_all_zero,
        "refine_t0": False,
        "apply_dune_helius_usd_scale": False,
        "max_pages_default": DEFAULT_MAX_PAGES_PRE_T0,
        "streams": "OFF",
        "dune": "OFF",
        "helpers": [
            "ingestion.helius_enhanced.fetch_pre_t0_enhanced_txs",
            "ingestion.sol_usd_oracle.resolve_sol_usd(as_of=...)",
            "paper_live.helius_enrich.parse_helius_enhanced_txs (import only)",
            "paper_live.q5a_agg.aggregate_q5a_for_mint (import only)",
        ],
        "paper_live_edited": False,
        "inputs": {
            "robust_csv": str(ROBUST_CSV if ROBUST_CSV.exists() else ROBUST_CSV_ALT),
            "feature_store": str(FS_PATH),
        },
        "outputs": {"csv": str(OUT_CSV), "meta": str(OUT_META)},
        "helius_calls_total": results[-1].get("helius_calls_after") if results else 0,
        "n_retries_429_total": results[-1].get("n_retries_429") if results else 0,
        "sol_usd_sources": sorted({str(r.get("sol_usd_source")) for r in ok if r.get("sol_usd_source")}),
        "per_mint": [
            {
                "mint": r.get("mint"),
                "band": r.get("band"),
                "n_trades_le_t0": r.get("n_trades_le_t0"),
                "old_robust_n_trades_pre_t0": r.get("old_robust_n_trades_pre_t0"),
                "n_txs_le_t0": r.get("n_txs_le_t0"),
                "n_txs_gt_t0": r.get("n_txs_gt_t0"),
                "buy_vol_usd_60s": r.get("buy_vol_usd_60s"),
                "train_buy_vol_usd_60s": r.get("train_buy_vol_usd_60s"),
                "sol_usd_source": r.get("sol_usd_source"),
                "partial_429": r.get("partial_429"),
                "bc_pages": r.get("bc_pages"),
                "mint_pages": r.get("mint_pages"),
                "error": r.get("error"),
            }
            for r in results
        ],
        # no secrets
    }
    OUT_META.write_text(json.dumps(meta, indent=2))

    # Short note
    lines = [
        "# Helius pre-T0 rebuild parity — 2026-10-01",
        "",
        "**Owner:** SolDatos. **paper_live:** not edited (BOSS owns wiring).",
        "",
        "## What",
        "",
        f"- Rebuilt ≤T0 features for **{len(results)}** mints from `cycle0/artifacts/helius_historical_replay_robust.csv`.",
        "- Helpers: `fetch_pre_t0_enhanced_txs`, `resolve_sol_usd(as_of=t0)`.",
        "- **refine_t0=False** — filled OOS `t0_ts` (no look-ahead).",
        "- **APPLY_DUNE_HELIUS_USD_SCALE=OFF** (6.6× not applied).",
        "- Streams OFF; no Dune.",
        "",
        "## Outputs",
        "",
        f"- `{OUT_CSV.relative_to(ROOT)}`",
        f"- `{OUT_META.relative_to(ROOT)}`",
        "",
        "## QA",
        "",
        f"- `n_txs_gt_t0==0` for all ok rows: **{qa_all_zero}**",
        "",
        "| mint | band | n_trades_le_t0 | old_robust | buy60_live | buy60_train | sol_src | gt_t0 |",
        "|------|------|----------------|------------|------------|-------------|---------|-------|",
    ]
    for r in results:
        m = str(r.get("mint") or "")[:20]
        lines.append(
            f"| {m}… | {r.get('band')} | {r.get('n_trades_le_t0')} | "
            f"{r.get('old_robust_n_trades_pre_t0')} | {r.get('buy_vol_usd_60s')} | "
            f"{r.get('train_buy_vol_usd_60s')} | {r.get('sol_usd_source')} | {r.get('n_txs_gt_t0')} |"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Partial 429 undercount flagged in `partial_429` / gaps.",
            "- Q5b name/symbol/priors are stubs (no Pump frontend in this pass); Q5a + buy60 from Enhanced ≤T0.",
            "- SolModelos can rescore from CSV; SolQA: assert `n_txs_gt_t0==0`.",
            "",
        ]
    )
    NOTE_MD.write_text("\n".join(lines))
    print(json.dumps({"n": len(results), "qa_zero": qa_all_zero, "csv": str(OUT_CSV)}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
