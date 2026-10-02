#!/usr/bin/env python3
"""SolDatos: Helius parity tx dump + recovery for ge10 highs (2026-10-01).

Non-blocking vs paper_live. Scale 6.6× OFF. No secrets in outputs.

Outputs:
  data/samples/helius_parity_tx_dump_ge10_20261001.csv
  data/samples/helius_parity_tx_dump_ge10_20261001_meta.json
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
    min_ts_floor_pre_t0,
)
from ingestion.helius_rpc import HeliusRpc
from ingestion.sol_usd_oracle import (
    apply_dune_helius_usd_scale_enabled,
    resolve_sol_usd,
)
from ingestion.helius_trade_parse import parse_helius_enhanced_txs
from ingestion.helius_enhanced import fetch_create_to_t0_txs
from ingestion.helius_rpc import collect_signatures_around_slot

PARITY_CSV = ROOT / "cycle0" / "artifacts" / "helius_parity_replay_ge10_20261001.csv"
FEATURES_CSV = ROOT / "data" / "samples" / "features_dune_p0_q5_expand_v2.csv"
LABELS_CSV = ROOT / "data" / "samples" / "dune_cohort_v1_labels_with_t0_mc.csv"
OUT_CSV = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_20261001.csv"
OUT_META = ROOT / "data" / "samples" / "helius_parity_tx_dump_ge10_20261001_meta.json"

# Prefixes of the two n_trades_pre_t0=1 failures
FAIL_PREFIXES = ("BZofTtkyrBM2", "4M3gYZ2dQ39K", "2hCEWYZcFZNW")

DUMP_COLS = [
    "mint",
    "tx_sig",
    "ts",
    "t0_ts",
    "le_t0",
    "source",
    "side",
    "sol_amt",
    "parsed_as_trade",
    "addr_source",  # mint|bc|rpc_mint|rpc_bc
]


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_t0(s: str) -> datetime:
    s = str(s).replace(" UTC", "+00:00").replace("Z", "+00:00").strip()
    return _aware(datetime.fromisoformat(s))


def _iso_utc(dt: datetime) -> str:
    dt = _aware(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _iso_from_unix(ts: int | float) -> str:
    return _iso_utc(datetime.fromtimestamp(int(ts), tz=timezone.utc))


def _load_parity() -> list[dict[str, str]]:
    with PARITY_CSV.open() as f:
        return list(csv.DictReader(f))


def _load_create_map(mints: set[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    with FEATURES_CSV.open() as f:
        for r in csv.DictReader(f):
            m = r.get("mint") or ""
            if m in mints:
                out[m] = {
                    "create_ts": r.get("create_ts"),
                    "buy_count_total": r.get("buy_count_total"),
                    "trade_count_total": r.get("trade_count_total"),
                    "buy_vol_usd_60s": r.get("buy_vol_usd_60s"),
                    "migrated_pre_t0": r.get("migrated_pre_t0"),
                    "age_s": r.get("age_s"),
                }
    with LABELS_CSV.open() as f:
        for r in csv.DictReader(f):
            m = r.get("mint") or ""
            if m in mints and m in out:
                out[m]["tx_id_t0"] = r.get("tx_id_t0")
    return out


def _tag_addr_source(tx: dict[str, Any], mint: str, bc: str) -> str:
    """Best-effort: which address likely produced this Enhanced tx."""
    # Enhanced payloads don't always stamp the query address; use account presence.
    accounts = set()
    for ad in tx.get("accountData") or []:
        a = ad.get("account")
        if a:
            accounts.add(str(a))
    # feePayer / transfers also mention mint rarely as account
    if bc and bc in accounts:
        return "bc"
    if mint in accounts:
        return "mint"
    return "unknown"


def _parse_by_sigs(helius: HeliusEnhanced, sigs: list[str]) -> list[dict[str, Any]]:
    """Enhanced parse-transactions by signature (≤100/chunk). Never log key."""
    if not sigs:
        return []
    return helius.get_transactions_by_signatures(sigs)


def _rpc_window(
    rpc: HeliusRpc,
    helius: HeliusEnhanced,
    address: str,
    *,
    t0: datetime,
    create_ts: datetime,
    max_pages: int = 40,
    pad_s: int = 30,
) -> tuple[list[dict[str, Any]], str]:
    hi = int(_aware(t0).timestamp())
    lo = int(_aware(create_ts).timestamp()) - pad_s
    sigs, reason = rpc.collect_signatures_in_window(
        address,
        max_block_time=hi,
        min_block_time=lo,
        max_pages=max_pages,
        page_limit=1000,
    )
    if not sigs:
        return [], f"rpc_empty:{address[:8]}:{reason}"
    sig_list = [str(s["signature"]) for s in sigs if s.get("signature")]
    txs = _parse_by_sigs(helius, sig_list)
    return txs, f"rpc_window addr={address[:8]}… n_sigs={len(sig_list)} n_parsed={len(txs)} reason={reason}"


def _trade_lookup(
    txs: list[dict[str, Any]],
    *,
    mint: str,
    bc: str,
    sol_usd: float,
    t0: datetime,
) -> dict[str, dict[str, Any]]:
    """Map signature → parsed trade fields (side, sol_amt). Parse without t0 filter
    so we can still annotate gt_t0 rows if any slip in."""
    # Parse with t0=None to get all; then we flag le_t0 ourselves.
    trades = parse_helius_enhanced_txs(
        txs, mint=mint, bonding_curve=bc, sol_usd=sol_usd, t0=None
    )
    # parse doesn't keep signature — rematch by (ts, side, sol_amt) is fragile.
    # Instead: re-run per-tx parse.
    by_sig: dict[str, dict[str, Any]] = {}
    for tx in txs:
        sig = str(tx.get("signature") or "")
        if not sig:
            continue
        one = parse_helius_enhanced_txs(
            [tx], mint=mint, bonding_curve=bc, sol_usd=sol_usd, t0=None
        )
        if one:
            # Prefer buy leg with largest usd for dump annotation; n_trades uses full parse
            tr = max(one, key=lambda r: (r.side == "buy", r.amount_usd))
            by_sig[sig] = {
                "side": tr.side,
                "sol_amt": tr.sol_amt,
                "amount_usd": tr.amount_usd,
                "project": tr.project,
                "n_legs": len(one),
                "n_buy_legs": sum(1 for r in one if r.side == "buy"),
            }
    return by_sig



def _rpc_anchor_around_t0(
    rpc: HeliusRpc,
    helius: HeliusEnhanced,
    address: str,
    *,
    t0_sig: str,
    t0: datetime,
    create_ts: datetime,
    max_older_pages: int = 5,
) -> tuple[list[dict[str, Any]], str]:
    """Jump to t0 via known signature — skip post-T0 mint spam.

    1) Parse t0_sig itself
    2) Page older than t0_sig until below create−pad
    """
    lo = int(_aware(create_ts).timestamp()) - 120
    hi = int(_aware(t0).timestamp())
    sigs: list[dict[str, Any]] = [{"signature": t0_sig, "blockTime": hi}]
    before = t0_sig
    reason = "anchor_ok"
    for page_i in range(max(1, max_older_pages)):
        try:
            page = rpc.get_signatures_for_address(address, limit=1000, before=before)
        except RuntimeError as e:
            reason = f"anchor_rpc_error@{page_i}:{str(e)[:60]}"
            break
        if not page:
            reason = f"anchor_empty@{page_i}"
            break
        oldest_bt = None
        for s in page:
            bt = s.get("blockTime")
            if bt is None:
                continue
            try:
                bti = int(bt)
            except (TypeError, ValueError):
                continue
            oldest_bt = bti if oldest_bt is None else min(oldest_bt, bti)
            if lo <= bti <= hi:
                sigs.append(s)
        before = str(page[-1].get("signature") or "") or None
        if not before:
            break
        if oldest_bt is not None and oldest_bt < lo:
            reason = f"anchor_floor@page{page_i + 1}"
            break
        if len(page) < 1000:
            reason = f"anchor_short@page{page_i + 1}"
            break
    else:
        reason = f"anchor_max_pages={max_older_pages}"
    # dedupe sigs
    seen: set[str] = set()
    uniq: list[str] = []
    for s in sigs:
        sig = str(s.get("signature") or "")
        if sig and sig not in seen:
            seen.add(sig)
            uniq.append(sig)
    txs = _parse_by_sigs(helius, uniq) if uniq else []
    return txs, f"rpc_anchor addr={address[:8]}… n_sigs={len(uniq)} n_parsed={len(txs)} reason={reason}"


def process_mint(
    helius: HeliusEnhanced,
    rpc: HeliusRpc,
    *,
    mint: str,
    t0_ts_raw: str,
    create_ts: datetime | None,
    create_sig: str | None,
    is_fail: bool,
    prior_n_trades: int | None,
    train_buy_n: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    t0 = _parse_t0(t0_ts_raw)
    if create_ts is None:
        create_ts = t0
    bc = str(bonding_curve_pda(mint))
    quote = resolve_sol_usd(None, allow_network=True, as_of=t0)
    sol_px = float(quote.price)
    assert apply_dune_helius_usd_scale_enabled() is False

    age0 = abs((_aware(t0) - _aware(create_ts)).total_seconds()) <= 2.0
    # Failures: push pages hard. Others: keep cheap (age0 mint pages low).
    if is_fail:
        # Mint newest→oldest rarely reaches age≈0 t0; cap pages, lean on BC+RPC.
        max_pages = max(40, min(DEFAULT_MAX_PAGES_PRE_T0, 60))
    elif age0:
        max_pages = 8
    else:
        max_pages = 40

    floor = min_ts_floor_pre_t0(t0, create_ts)
    t_fetch0 = time.monotonic()
    txs_le, gaps = fetch_pre_t0_enhanced_txs(
        helius,
        mint,
        t0=t0,
        create_ts=create_ts,
        bonding_curve=bc,
        max_pages=max_pages,
        limit=100,
        create_signature=create_sig,
    )
    fetch_mode = "enhanced_pre_t0"
    # Keep a pre-filter merged snapshot for dump QA (gt_t0 check): re-fetch is
    # expensive; helper already filtered. We'll dump txs_le (+ recovery extras)
    # and mark le_t0 accurately. If recovery adds raw txs, merge then filter.

    recovery_extra: list[dict[str, Any]] = []
    # RPC recovery only for the 2 fail targets (others: Enhanced dump is enough / cheap).
    if is_fail:
        # RPC signature window on mint + BC (create−pad … t0)
        for label, addr in (("rpc_mint", mint), ("rpc_bc", bc)):
            pad = 120 if is_fail else 30
            extra, why = _rpc_window(
                rpc, helius, addr, t0=t0, create_ts=create_ts, max_pages=60, pad_s=pad
            )
            gaps.append(why)
            if extra:
                for tx in extra:
                    tx["_addr_source"] = label
                recovery_extra.extend(extra)
        # Failures: also jump via known t0 signature (skip post-T0 spam)
        if is_fail and create_sig:
            for label, addr in (("rpc_anchor_mint", mint), ("rpc_anchor_bc", bc)):
                extra, why = _rpc_anchor_around_t0(
                    rpc, helius, addr, t0_sig=create_sig, t0=t0, create_ts=create_ts
                )
                gaps.append(why)
                if extra:
                    for tx in extra:
                        tx["_addr_source"] = label
                    recovery_extra.extend(extra)
        # Create-slot getBlock (±1): catches post-grad AMM buys missed by BC/mint crawl
        create_anchor = None
        for tx in list(txs_le) + recovery_extra:
            if str(tx.get("type") or "").upper() == "CREATE" and tx.get("signature"):
                create_anchor = str(tx.get("signature"))
                break
        if create_anchor is None and create_sig:
            create_anchor = create_sig
        if create_anchor:
            try:
                txr = rpc.call(
                    "getTransaction",
                    [
                        create_anchor,
                        {"encoding": "json", "maxSupportedTransactionVersion": 0},
                    ],
                )
                slot = (txr.result or {}).get("slot") if txr.result else None
            except Exception as e:  # noqa: BLE001
                gaps.append(f"slot_anchor_failed:{str(e)[:80]}")
                slot = None
            if slot is not None:
                sig_list, sgaps = collect_signatures_around_slot(
                    rpc, center_slot=int(slot), slot_radius=1
                )
                gaps.extend(sgaps)
                if sig_list:
                    try:
                        extra = _parse_by_sigs(helius, sig_list)
                    except Exception as e:  # noqa: BLE001
                        gaps.append(f"slot_parse_failed:{str(e)[:80]}")
                        extra = []
                    n_mint = 0
                    for tx in extra:
                        # keep mint-related only
                        involves = any(
                            str(t.get("mint") or "") == mint
                            for t in (tx.get("tokenTransfers") or [])
                        )
                        if not involves:
                            continue
                        tx["_addr_source"] = "rpc_slot"
                        recovery_extra.append(tx)
                        n_mint += 1
                    gaps.append(
                        f"slot_window slot={slot} n_sigs={len(sig_list)} mint_hit={n_mint}"
                    )

        if recovery_extra:
            merged = merge_tx_lists(txs_le, recovery_extra)
            # Intentionally keep ALL merged for dump, then flag le_t0
            all_for_dump = merged
            txs_le = filter_txs_le_t0(merged, t0)
            fetch_mode = "enhanced+rpc_sig_window+slot"
            gaps.append(f"after_rpc_merge le_t0={len(txs_le)} dump_candidates={len(all_for_dump)}")
        else:
            all_for_dump = list(txs_le)
    else:
        all_for_dump = list(txs_le)

    fetch_s = time.monotonic() - t_fetch0

    # Also retain any recovery txs with ts > t0 so QA can fail the gate
    t0_unix = int(_aware(t0).timestamp())
    dump_pool = list(all_for_dump)
    # Ensure every le_t0 tx is present
    seen = {str(t.get("signature") or "") for t in dump_pool}
    for tx in txs_le:
        sig = str(tx.get("signature") or "")
        if sig and sig not in seen:
            dump_pool.append(tx)
            seen.add(sig)

    trade_by_sig = _trade_lookup(
        dump_pool, mint=mint, bc=bc, sol_usd=sol_px, t0=t0
    )

    # Trades that enter features = parsed AND ts <= t0
    trades_use = parse_helius_enhanced_txs(
        txs_le, mint=mint, bonding_curve=bc, sol_usd=sol_px, t0=t0
    )
    n_trades = len(trades_use)
    n_buys = sum(1 for tr in trades_use if tr.side == "buy")

    rows: list[dict[str, Any]] = []
    n_le_false = 0
    # Dump: all txs in dump_pool that either parse as trade OR are in le_t0 set
    # (feature-window candidates). Prefer trade rows; include non-trade le_t0 for audit.
    for tx in dump_pool:
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
        le = ts_i <= t0_unix
        if not le:
            n_le_false += 1
        tr_info = trade_by_sig.get(sig)
        # Include if: parsed as trade OR le_t0 (would be fed to parse)
        if tr_info is None and not le:
            continue  # skip post-t0 non-trades (noise)
        addr_src = tx.get("_addr_source") or _tag_addr_source(tx, mint, bc)
        rows.append(
            {
                "mint": mint,
                "tx_sig": sig,
                "ts": _iso_from_unix(ts_i),
                "t0_ts": _iso_utc(t0),
                "le_t0": bool(le),
                "source": str(tx.get("source") or ""),
                "side": (tr_info or {}).get("side") or "",
                "sol_amt": (tr_info or {}).get("sol_amt") if tr_info else "",
                "parsed_as_trade": bool(tr_info),
                "addr_source": addr_src,
            }
        )

    # Deduplicate dump rows by tx_sig (keep first)
    dedup: list[dict[str, Any]] = []
    seen_sig: set[str] = set()
    for r in rows:
        if r["tx_sig"] in seen_sig:
            continue
        seen_sig.add(r["tx_sig"])
        dedup.append(r)
    rows = dedup
    n_le_false = sum(1 for r in rows if not r["le_t0"])

    meta = {
        "mint": mint,
        "t0_ts": t0_ts_raw,
        "create_ts": _iso_utc(create_ts),
        "bonding_curve": bc,
        "age0": age0,
        "is_fail_target": is_fail,
        "floor_unix": floor,
        "max_pages": max_pages,
        "fetch_mode": fetch_mode,
        "gaps": gaps,
        "n_txs_le_t0": len(txs_le),
        "n_trades_le_t0": n_trades,
        "n_buys_le_t0": n_buys,
        "prior_parity_n_trades_pre_t0": prior_n_trades,
        "train_buy_count_total": train_buy_n,
        "recovery_improved": (
            (n_buys > (prior_n_trades or 0)) if is_fail else None
        ),
        "n_dump_rows": len(rows),
        "n_le_t0_false": n_le_false,
        "sol_usd": sol_px,
        "sol_usd_source": str(quote.source),
        "fetch_s": round(fetch_s, 2),
        "helius_calls_so_far": helius.n_calls,
        "create_signature_used": bool(create_sig),
    }
    return rows, meta


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Helius parity tx dump + recovery")
    ap.add_argument(
        "--only-fail",
        action="store_true",
        help="Process only BZof/4M3g fail targets (targeted recovery)",
    )
    ap.add_argument(
        "--out-suffix",
        default="",
        help="Optional suffix for out csv/meta (e.g. _fail2)",
    )
    args = ap.parse_args()

    load_dotenv()
    assert apply_dune_helius_usd_scale_enabled() is False

    parity = _load_parity()
    mints = {r["mint"] for r in parity}
    create_map = _load_create_map(mints)

    fail_mints = {
        m for m in mints if any(m.startswith(p) for p in FAIL_PREFIXES)
    }
    if args.only_fail:
        parity = [r for r in parity if r["mint"] in fail_mints]
    print(f"parity n={len(parity)} fail_targets={sorted(fail_mints)} only_fail={args.only_fail}", flush=True)

    out_csv = OUT_CSV
    out_meta = OUT_META
    if args.out_suffix:
        out_csv = OUT_CSV.with_name(OUT_CSV.stem + args.out_suffix + OUT_CSV.suffix)
        out_meta = OUT_META.with_name(OUT_META.stem + args.out_suffix + OUT_META.suffix)

    all_rows: list[dict[str, Any]] = []
    mint_metas: list[dict[str, Any]] = []

    # Be gentle to live: 0.4s between Enhanced calls
    # Fail-only: slower Enhanced pacing to reduce 429s
    enh_interval = 0.7 if args.only_fail else 0.4
    with HeliusEnhanced(
        min_interval_s=enh_interval, max_calls=8000, max_retries_429=12
    ) as helius, HeliusRpc(min_interval_s=0.12) as rpc:
        for i, r in enumerate(parity):
            mint = r["mint"]
            is_fail = mint in fail_mints
            info = create_map.get(mint) or {}
            create_ts = None
            if info.get("create_ts"):
                try:
                    create_ts = _parse_t0(str(info["create_ts"]))
                except Exception:
                    create_ts = None
            create_sig = (info.get("tx_id_t0") or None) if is_fail else None
            # For failures, tx_id_t0 is the OOS t0 sighting tx — useful as stop
            # only if it equals create; still pass it as create_signature stop.
            prior_n = None
            try:
                prior_n = int(float(r.get("n_trades_pre_t0") or ""))
            except (TypeError, ValueError):
                prior_n = None
            print(
                f"[{i+1}/{len(parity)}] {mint[:12]}… fail={is_fail} "
                f"prior_n={prior_n}",
                flush=True,
            )
            rows, meta = process_mint(
                helius,
                rpc,
                mint=mint,
                t0_ts_raw=r["t0_ts"],
                create_ts=create_ts,
                create_sig=str(create_sig) if create_sig else None,
                is_fail=is_fail,
                prior_n_trades=prior_n,
                train_buy_n=info.get("buy_count_total"),
            )
            all_rows.extend(rows)
            mint_metas.append(meta)
            print(
                f"  → trades={meta['n_trades_le_t0']} buys={meta.get('n_buys_le_t0')} "
                f"txs_le={meta['n_txs_le_t0']} "
                f"dump={meta['n_dump_rows']} le_false={meta['n_le_t0_false']} "
                f"improved={meta['recovery_improved']} mode={meta['fetch_mode']}",
                flush=True,
            )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DUMP_COLS, extrasaction="ignore")
        w.writeheader()
        for row in all_rows:
            out = dict(row)
            out["le_t0"] = "true" if row["le_t0"] else "false"
            w.writerow(out)

    fail_metas = [m for m in mint_metas if m.get("is_fail_target")]
    meta_out = {
        "kind": "helius_parity_tx_dump_ge10",
        "generated_at": _iso_utc(datetime.now(tz=timezone.utc)),
        "source_parity_csv": str(PARITY_CSV.relative_to(ROOT)),
        "out_csv": str(out_csv.relative_to(ROOT)),
        "apply_dune_helius_usd_scale": False,
        "n_mints": len(mint_metas),
        "n_dump_rows": len(all_rows),
        "n_le_t0_false": sum(1 for r in all_rows if not r["le_t0"]),
        "fail_targets": [
            {
                "mint": m["mint"],
                "prior_parity_n_trades_pre_t0": m["prior_parity_n_trades_pre_t0"],
                "n_trades_le_t0": m["n_trades_le_t0"],
                "n_buys_le_t0": m.get("n_buys_le_t0"),
                "n_txs_le_t0": m["n_txs_le_t0"],
                "train_buy_count_total": m["train_buy_count_total"],
                "recovery_improved": m["recovery_improved"],
                "n_dump_rows": m["n_dump_rows"],
                "n_le_t0_false": m["n_le_t0_false"],
                "fetch_mode": m["fetch_mode"],
                "gaps": m["gaps"],
                "stuck_rpc_gap": (
                    (m.get("n_buys_le_t0") or m["n_trades_le_t0"])
                    <= (m["prior_parity_n_trades_pre_t0"] or 0)
                ),
            }
            for m in fail_metas
        ],
        "per_mint": [
            {
                "mint": m["mint"],
                "n_trades_le_t0": m["n_trades_le_t0"],
                "n_txs_le_t0": m["n_txs_le_t0"],
                "n_dump_rows": m["n_dump_rows"],
                "n_le_t0_false": m["n_le_t0_false"],
                "fetch_mode": m["fetch_mode"],
                "is_fail_target": m["is_fail_target"],
            }
            for m in mint_metas
        ],
        "notes": [
            "Dump rows = Enhanced/RPC txs in ≤T0 feature window (le_t0) plus any "
            "parsed trades with le_t0=false (QA hard-gate evidence).",
            "Recovery for 2 failures: max_pages≥120, BC-first helper, create floor, "
            "create_signature stop (tx_id_t0), RPC sig window on mint+BC (create−30s…t0).",
            "If n_trades still 1 vs Dune 3–4: likely RPC/Enhanced gap on age≈0 "
            "migrated_pre_t0 snipers (post-grad volume not on BC; mint crawl buried).",
        ],
    }
    out_meta.write_text(json.dumps(meta_out, indent=2) + "\n")
    print(f"Wrote {out_csv} rows={len(all_rows)}", flush=True)
    print(f"Wrote {out_meta}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
