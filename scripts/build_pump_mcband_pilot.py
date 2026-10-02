#!/usr/bin/env python3
"""Rebuild Path A pilot with T0 = first Pump trade MC ∈ [8k,20k] + relabel hit_10x.

Hard constraints:
- 0 Dune API · Lite OFF · USD scale OFF
- Never overwrite q5b_last / q5b_calibration.json
- Never restart / touch paper_live PID
- Reuse pump_pilot500 trades cache; fetch only missing / non-reconstructable (capped)

T0 recipe (frozen):
  Implied MC = float(priceUsd) * 1e9  (Pump UI supply = 1B)
  T0 = timestamp of first chronological trade with MC ∈ [8000, 20000]
  Scoreable via find_t0_pump_mc_sighting(create_ts from expand, mc, t0)
  Proxies (documented, non-exact):
    - deep_fetch: extra pagination when cache never enters band
    - expand_create_proxy: ONLY if still no band after deep fetch AND expand
      mc_usd_t0 ∈ [8k,20k] — features may be empty-pre-T0; flagged reconstruct_method
  Non-reconstructable: no trades / never band / expand mc out of band → excluded from WF matrix

Label recipe (frozen, local only):
  hit_10x_30d = 1 iff max_mc_after_new_t0 >= 10 * mc_t0 within 30d
  max_mc_after_new_t0 =
    max(implied MC from Pump trades with new_t0 < ts <= new_t0+30d)
    ∪ expand labels_dune_expand_v2.max_mc_after_t0
      when expand_t0 >= new_t0  (valid lower bound; no pre-T0 leakage)
      OR |new_t0 - expand_t0| <= 1h (near-parity T0; documented slack)
  Anti look-ahead: Q5a/buy60 only from trades with ts <= new_t0; labels only post-T0.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS  # noqa: E402
from ingestion.pump_constants import MC_HI_USD, MC_LO_USD  # noqa: E402
from ingestion.t0_capture import (  # noqa: E402
    PUMP_MC_SIGHTING_DEF,
    find_t0_pump_mc_sighting,
    is_scoreable_pump_capture,
)

STAMP_DEFAULT = datetime.now().strftime("%Y%m%d")
T0_POLICY = "pump_mc_band_from_trades_v1"
UI_SUPPLY = 1_000_000_000.0  # priceUsd * UI_SUPPLY = implied MC USD
HIT_MULTIPLE = 10.0
LABEL_HORIZON = timedelta(days=30)
EXPAND_T0_SLACK = timedelta(hours=1)
MAX_DEEP_PAGES = 40
MAX_DEEP_MINTS = 80
MIN_INTERVAL_S = 1.0
MAX_HTTP_BUDGET_DEEP = 2500


def _utcnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _aware_dt(v: Any) -> datetime | None:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    ts = pd.Timestamp(v)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.to_pydatetime()


def _trade_ts_mc(tr: dict[str, Any]) -> tuple[datetime, float, float] | None:
    ts_raw = tr.get("blockTimeMs") or tr.get("timestamp") or tr.get("blockTime")
    if ts_raw is None:
        return None
    try:
        ts = float(ts_raw)
    except (TypeError, ValueError):
        return None
    if ts < 1e12:
        ts *= 1000.0
    px = tr.get("priceUsd")
    if px is None:
        return None
    try:
        px_f = float(px)
    except (TypeError, ValueError):
        return None
    if px_f <= 0:
        return None
    dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
    return dt, px_f * UI_SUPPLY, px_f


def series_from_raw(raw: list[dict[str, Any]]) -> list[tuple[datetime, float, float]]:
    out: list[tuple[datetime, float, float]] = []
    for tr in raw or []:
        if not isinstance(tr, dict):
            continue
        r = _trade_ts_mc(tr)
        if r:
            out.append(r)
    out.sort(key=lambda x: x[0])
    return out


def find_band_t0(
    series: list[tuple[datetime, float, float]],
) -> tuple[datetime, float, float, str] | None:
    """Return (t0, mc, price, method) for first MC∈[8k,20k] trade."""
    for ts, mc, px in series:
        if MC_LO_USD <= mc <= MC_HI_USD:
            return ts, mc, px, "pump_trade_mc_band"
    return None


def relabel_hit_10x(
    *,
    t0: datetime,
    mc0: float,
    series: list[tuple[datetime, float, float]],
    expand_t0: datetime | None,
    expand_max_mc: float | None,
) -> dict[str, Any]:
    end = t0 + LABEL_HORIZON
    post = [(ts, mc) for ts, mc, _ in series if t0 < ts <= end]
    trade_max = max((m for _, m in post), default=None)
    use_expand = False
    if expand_max_mc is not None and expand_t0 is not None and expand_max_mc > 0:
        if expand_t0 >= t0 or abs((expand_t0 - t0).total_seconds()) <= EXPAND_T0_SLACK.total_seconds():
            use_expand = True
    combined = trade_max
    if use_expand:
        combined = max(combined or 0.0, float(expand_max_mc))
    hit = None
    max_mult = None
    if combined is not None and mc0 > 0:
        max_mult = float(combined) / float(mc0)
        hit = int(max_mult >= HIT_MULTIPLE)
    elif trade_max is None and not use_expand:
        hit = 0  # no post-T0 evidence in local sources → treat as non-hit (document)
        max_mult = None
    return {
        "hit_10x_30d": hit if hit is not None else 0,
        "max_mc_after_t0_local": trade_max,
        "max_mc_after_t0_combined": combined,
        "max_multiple_30d": max_mult,
        "label_used_expand_max": int(use_expand),
        "n_trades_post_t0_30d": len(post),
        "label_source": (
            "pump_trades+expand_max"
            if use_expand and trade_max is not None
            else ("expand_max_mc_after_t0" if use_expand else "pump_trades_post_t0")
        ),
    }


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def _save_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(path)


def deep_fetch_trades(
    mint: str,
    *,
    client: Any,
    target_ts: datetime | None,
    max_pages: int = MAX_DEEP_PAGES,
    page_limit: int = 100,
    pre_band_s: float = 15 * 60.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Paginate newest→oldest until band entry found or oldest ≤ target_ts or cap.

    pre_band_s: once band is found, keep paginating until oldest is this many
    seconds before band T0 (default 15m). Scale jobs may pass a smaller value
    to raise mint throughput under HTTP budget.
    """
    from urllib.parse import quote

    from ingestion.pump_frontend import SOLANA_MAINNET_CHAIN_ID, TRADES_PAGE_MAX

    path = f"/trades/{quote(SOLANA_MAINNET_CHAIN_ID, safe='')}/{mint}"
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    n_pages = 0
    oldest_ms: float | None = None
    found_band = False
    target_ms = target_ts.timestamp() * 1000.0 if target_ts else None
    pl = max(1, min(int(page_limit), TRADES_PAGE_MAX))
    for _ in range(max(1, int(max_pages))):
        params: dict[str, Any] = {"limit": pl}
        if cursor:
            params["cursor"] = cursor
        data = client.get_json(path, params=params)
        n_pages += 1
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]
            cursor = None
        elif isinstance(data, dict):
            rows = [r for r in (data.get("trades") or []) if isinstance(r, dict)]
            nxt = data.get("cursor")
            cursor = str(nxt) if nxt else None
        else:
            raise RuntimeError(f"Unexpected /trades payload: {type(data)}")
        if not rows:
            break
        out.extend(rows)
        page_oldest = None
        for tr in rows:
            r = _trade_ts_mc(tr)
            if r is None:
                continue
            ts, mc, _ = r
            ts_ms = ts.timestamp() * 1000.0
            page_oldest = ts_ms if page_oldest is None else min(page_oldest, ts_ms)
            if MC_LO_USD <= mc <= MC_HI_USD:
                found_band = True
        if page_oldest is not None:
            oldest_ms = page_oldest if oldest_ms is None else min(oldest_ms, page_oldest)
        pre_ms = float(pre_band_s) * 1000.0
        if found_band and oldest_ms is not None:
            # keep ≥pre_band_s pre-band coverage if possible
            band_series = series_from_raw(out)
            band = find_band_t0(band_series)
            if band and oldest_ms <= band[0].timestamp() * 1000.0 - pre_ms:
                break
        if target_ms is not None and oldest_ms is not None and oldest_ms <= target_ms - pre_ms:
            break
        if not cursor:
            break
    meta = {
        "n_pages": n_pages,
        "n_raw": len(out),
        "found_band": found_band,
        "oldest_ms": oldest_ms,
    }
    return out, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--pilot-stamp", default="20261002", help="pilot500 cache stamp to reuse")
    ap.add_argument("--deep-fetch", action="store_true", default=True)
    ap.add_argument("--no-deep-fetch", action="store_false", dest="deep_fetch")
    ap.add_argument("--max-deep-pages", type=int, default=MAX_DEEP_PAGES)
    ap.add_argument("--max-deep-mints", type=int, default=MAX_DEEP_MINTS)
    ap.add_argument("--allow-expand-proxy", action="store_true", default=False,
                    help="If set, use expand t0/mc when Pump band not reconstructable")
    args = ap.parse_args()

    sample_path = ROOT / f"data/samples/pump_pilot500_sample_{args.pilot_stamp}.csv"
    trades_dir = ROOT / f"data/samples/pump_pilot500_trades_{args.pilot_stamp}"
    ck_path = ROOT / f"cycle0/artifacts/pump_pilot500_checkpoint_{args.pilot_stamp}.json"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"

    out_sample = ROOT / f"data/samples/pump_mcband_sample_{args.stamp}.csv"
    out_matrix = ROOT / f"data/samples/features_pump_path_a_mcband_{args.stamp}.csv"
    out_t0 = ROOT / f"cycle0/artifacts/pump_mcband_t0_recon_{args.stamp}.csv"
    out_meta = ROOT / f"cycle0/artifacts/pump_mcband_build_meta_{args.stamp}.json"
    deep_ck = ROOT / f"cycle0/artifacts/pump_mcband_deep_fetch_{args.stamp}.json"
    deep_trades_dir = ROOT / f"data/samples/pump_mcband_trades_extra_{args.stamp}"

    if not sample_path.is_file():
        print(json.dumps({"status": "missing_sample", "path": str(sample_path)}))
        return 1

    sample = pd.read_csv(sample_path)
    lab = pd.read_csv(lab_path)
    lab_cols = ["mint", "max_mc_after_t0", "max_multiple_30d", "followup_days_available", "hit_10x_30d", "hit_200k"]
    lab_cols = [c for c in lab_cols if c in lab.columns]
    sample = sample.merge(lab[lab_cols], on="mint", how="left", suffixes=("", "_lab"))
    if "hit_10x_30d_lab" in sample.columns:
        # keep original expand label as hit_10x_30d_expand
        sample = sample.rename(columns={"hit_10x_30d_lab": "hit_10x_30d_expand"})
    if "hit_10x_30d" in sample.columns and "hit_10x_30d_expand" not in sample.columns:
        sample["hit_10x_30d_expand"] = sample["hit_10x_30d"]

    # Ensure create_ts / creator from sample or features
    if "create_ts" not in sample.columns or sample["create_ts"].isna().all():
        header = pd.read_csv(feat_path, nrows=0).columns.tolist()
        extra = [c for c in ["mint", "create_ts", "creator_pubkey"] + list(Q5B_COLS) if c in header]
        feat = pd.read_csv(feat_path, usecols=extra)
        sample = sample.drop(columns=[c for c in feat.columns if c != "mint" and c in sample.columns], errors="ignore")
        sample = sample.merge(feat, on="mint", how="left")

    ck = _load_json(ck_path)
    done = dict(ck.get("done") or {})

    # --- Pass 1: reconstruct from cache ---
    recon_rows: list[dict[str, Any]] = []
    need_deep: list[str] = []
    for _, sr in sample.iterrows():
        mint = str(sr["mint"])
        st = done.get(mint) or {}
        path = trades_dir / f"{mint}.json"
        raw: list[dict[str, Any]] = []
        cache_ok = bool(st.get("ok") and path.is_file())
        if cache_ok:
            payload = json.loads(path.read_text())
            raw = list(payload.get("trades") or [])
        series = series_from_raw(raw)
        expand_t0 = _aware_dt(sr.get("t0_ts"))
        create_ts = _aware_dt(sr.get("create_ts"))
        expand_mc = float(sr["mc_usd_t0"]) if pd.notna(sr.get("mc_usd_t0")) else None
        expand_max = float(sr["max_mc_after_t0"]) if pd.notna(sr.get("max_mc_after_t0")) else None
        band = find_band_t0(series) if series else None
        row: dict[str, Any] = {
            "mint": mint,
            "expand_t0_ts": expand_t0.isoformat() if expand_t0 else None,
            "expand_mc_usd_t0": expand_mc,
            "create_ts": create_ts.isoformat() if create_ts else None,
            "cache_ok": int(cache_ok),
            "n_raw_cache": len(raw),
            "hit_10x_30d_expand": int(sr["hit_10x_30d_expand"]) if pd.notna(sr.get("hit_10x_30d_expand")) else None,
        }
        if band:
            t0, mc, px, method = band
            row.update(
                {
                    "reconstructable": 1,
                    "reconstruct_method": method,
                    "t0_ts": t0.isoformat(),
                    "mc_usd_t0": mc,
                    "price_usd_t0": px,
                    "needs_deep": 0,
                }
            )
        else:
            row.update(
                {
                    "reconstructable": 0,
                    "reconstruct_method": "none",
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "price_usd_t0": None,
                    "needs_deep": 1 if cache_ok or not cache_ok else 1,
                }
            )
            need_deep.append(mint)
        recon_rows.append(row)

    # --- Pass 2: deep fetch for non-reconstructable ---
    deep_stats: dict[str, Any] = {
        "attempted": 0,
        "ok": 0,
        "found_band": 0,
        "http_calls": 0,
        "skipped": 0,
    }
    deep_done = _load_json(deep_ck)
    deep_done.setdefault("done", {})
    # seed stats from checkpoint for resume
    deep_stats["skipped"] = 0
    deep_stats["found_band"] = sum(
        1 for v in (deep_done.get("done") or {}).values() if v.get("ok") and v.get("found_band")
    )
    deep_stats["ok"] = sum(1 for v in (deep_done.get("done") or {}).values() if v.get("ok"))
    if args.deep_fetch and need_deep:
        from ingestion.pump_frontend import PumpFrontendClient

        deep_trades_dir.mkdir(parents=True, exist_ok=True)
        client = PumpFrontendClient(min_interval_s=MIN_INTERVAL_S, max_retries_429=5)
        try:
            for mint in need_deep[: args.max_deep_mints]:
                if client.log.n_calls >= MAX_HTTP_BUDGET_DEEP:
                    deep_stats["stopped"] = "http_budget"
                    break
                prev = deep_done["done"].get(mint)
                if prev and prev.get("ok"):
                    deep_stats["skipped"] += 1
                    if prev.get("found_band"):
                        deep_stats["found_band"] = deep_stats.get("found_band", 0)  # recount later
                    continue
                sr = sample[sample["mint"] == mint].iloc[0]
                expand_t0 = _aware_dt(sr.get("t0_ts"))
                deep_stats["attempted"] += 1
                try:
                    raw, fmeta = deep_fetch_trades(
                        mint,
                        client=client,
                        target_ts=expand_t0,
                        max_pages=args.max_deep_pages,
                    )
                    out_path = deep_trades_dir / f"{mint}.json"
                    out_path.write_text(
                        json.dumps(
                            {
                                "mint": mint,
                                "n_raw": len(raw),
                                "fetch_meta": fmeta,
                                "fetched_at": _utcnow(),
                                "trades": raw,
                            }
                        )
                    )
                    deep_done["done"][mint] = {
                        "ok": True,
                        "found_band": bool(fmeta.get("found_band")),
                        "n_raw": len(raw),
                        "n_pages": fmeta.get("n_pages"),
                        "path": str(out_path.relative_to(ROOT)),
                    }
                    deep_stats["ok"] += 1
                    if fmeta.get("found_band"):
                        deep_stats["found_band"] += 1
                except Exception as e:  # noqa: BLE001
                    deep_done["done"][mint] = {
                        "ok": False,
                        "error": f"{type(e).__name__}: {e}"[:300],
                    }
                deep_stats["http_calls"] = client.log.n_calls
                deep_done["stats"] = deep_stats
                deep_done["updated_at"] = _utcnow()
                _save_json(deep_ck, deep_done)
                if deep_stats["attempted"] % 10 == 0:
                    print(json.dumps({"deep_progress": deep_stats}), flush=True)
        finally:
            client.close()
            deep_stats["http_calls"] = client.log.n_calls
            deep_done["stats"] = deep_stats
            deep_done["finished_at"] = _utcnow()
            _save_json(deep_ck, deep_done)

    # Merge deep results into recon + trades lookup
    trades_by_mint: dict[str, list[dict[str, Any]]] = {}
    recon_by_mint = {r["mint"]: r for r in recon_rows}
    for mint, r in recon_by_mint.items():
        path = trades_dir / f"{mint}.json"
        raw: list[dict[str, Any]] = []
        if path.is_file():
            raw = list(json.loads(path.read_text()).get("trades") or [])
        cache_band = find_band_t0(series_from_raw(raw))
        dprev = (deep_done.get("done") or {}).get(mint)
        if dprev and dprev.get("ok"):
            dpath = ROOT / dprev["path"] if not Path(dprev["path"]).is_absolute() else Path(dprev["path"])
            if dpath.is_file():
                draw = list(json.loads(dpath.read_text()).get("trades") or [])
                if len(draw) >= len(raw):
                    raw = draw
        trades_by_mint[mint] = raw
        series = series_from_raw(raw)
        band = find_band_t0(series)
        if band:
            t0, mc, px, _ = band
            method = "pump_trade_mc_band" if cache_band else "pump_trade_mc_band_deep"
            r.update(
                {
                    "reconstructable": 1,
                    "reconstruct_method": method,
                    "t0_ts": t0.isoformat(),
                    "mc_usd_t0": mc,
                    "price_usd_t0": px,
                    "needs_deep": 0,
                    "n_raw_final": len(raw),
                }
            )
        elif args.allow_expand_proxy:
            expand_t0 = _aware_dt(r.get("expand_t0_ts"))
            expand_mc = r.get("expand_mc_usd_t0")
            create_ts = _aware_dt(r.get("create_ts"))
            if (
                expand_t0
                and expand_mc is not None
                and MC_LO_USD <= float(expand_mc) <= MC_HI_USD
                and create_ts is not None
            ):
                r.update(
                    {
                        "reconstructable": 1,
                        "reconstruct_method": "expand_create_proxy",
                        "t0_ts": expand_t0.isoformat(),
                        "mc_usd_t0": float(expand_mc),
                        "price_usd_t0": float(expand_mc) / UI_SUPPLY,
                        "n_raw_final": len(raw),
                    }
                )
            else:
                r.update({"reconstructable": 0, "reconstruct_method": "unreconstructable",
                          "t0_ts": None, "mc_usd_t0": None, "n_raw_final": len(raw)})
        else:
            reason = "no_trades" if not raw else "never_in_band"
            r.update(
                {
                    "reconstructable": 0,
                    "reconstruct_method": reason,
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "n_raw_final": len(raw),
                }
            )

    # Scoreable gate + relabel
    from paper_live.pump_enrich import buy_vol_60s_from_trades, parse_pump_frontend_trades
    from paper_live.q5a_agg import aggregate_q5a_for_mint

    matrix_rows: list[dict[str, Any]] = []
    for _, sr in sample.iterrows():
        mint = str(sr["mint"])
        r = recon_by_mint[mint]
        create_ts = _aware_dt(sr.get("create_ts"))
        expand_t0 = _aware_dt(sr.get("t0_ts"))
        expand_max = float(sr["max_mc_after_t0"]) if pd.notna(sr.get("max_mc_after_t0")) else None
        raw = trades_by_mint.get(mint) or []
        series = series_from_raw(raw)

        base: dict[str, Any] = {
            "mint": mint,
            "t0_policy": T0_POLICY,
            "t0_definition": PUMP_MC_SIGHTING_DEF,
            "reconstruct_method": r.get("reconstruct_method"),
            "reconstructable": int(r.get("reconstructable") or 0),
            "hit_10x_30d_expand": r.get("hit_10x_30d_expand"),
            "expand_t0_ts": r.get("expand_t0_ts"),
            "expand_mc_usd_t0": r.get("expand_mc_usd_t0"),
            "sol_usd_source": "pump_frontend",
            "feature_overlay": "pump_trades_q5a_buy60",
            "label_source": None,
        }
        # Q5b from expand store first
        for c in Q5B_COLS:
            base[c] = sr[c] if c in sr.index else None

        if not r.get("reconstructable"):
            base.update(
                {
                    "t0_ts": None,
                    "mc_usd_t0": None,
                    "hit_10x_30d": None,
                    "fetch_ok": 0,
                    "n_trades_pre_t0": 0,
                    "capture_scoreable": False,
                }
            )
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None
            matrix_rows.append(base)
            r["hit_10x_30d"] = None
            r["capture_scoreable"] = 0
            continue

        t0 = _aware_dt(r["t0_ts"])
        mc0 = float(r["mc_usd_t0"])
        assert t0 is not None
        cap = find_t0_pump_mc_sighting(
            sighting_t0=t0,
            sighting_mc=mc0,
            create_ts=create_ts,
            complete=False,
            sol_usd=0.0,
            sol_usd_source="pump_frontend",
        )
        scoreable = is_scoreable_pump_capture(cap, allow_med=True)

        lab_info = relabel_hit_10x(
            t0=t0,
            mc0=mc0,
            series=series,
            expand_t0=expand_t0,
            expand_max_mc=expand_max,
        )
        # Recompute age from create→new T0 (live parity)
        if create_ts is not None:
            age_s = (t0 - create_ts).total_seconds()
            base["age_s"] = age_s
            base["age_min"] = age_s / 60.0

        base.update(
            {
                "t0_ts": t0.isoformat(),
                "mc_usd_t0": mc0,
                "price_usd_t0": r.get("price_usd_t0"),
                "capture_scoreable": bool(scoreable),
                "capture_quality": cap.capture_quality,
                "capture_detail": cap.detail,
                "hit_10x_30d": lab_info["hit_10x_30d"],
                "hit_200k": int(lab_info["hit_10x_30d"]) if lab_info.get("max_mc_after_t0_combined") and lab_info["max_mc_after_t0_combined"] >= 200_000 else int(sr["hit_200k"]) if pd.notna(sr.get("hit_200k")) else int(lab_info["hit_10x_30d"]),
                "max_mc_after_t0_local": lab_info["max_mc_after_t0_local"],
                "max_mc_after_t0_combined": lab_info["max_mc_after_t0_combined"],
                "max_multiple_30d": lab_info["max_multiple_30d"],
                "label_used_expand_max": lab_info["label_used_expand_max"],
                "label_source": lab_info["label_source"],
                "n_trades_post_t0_30d": lab_info["n_trades_post_t0_30d"],
            }
        )
        # Features ≤ T0
        try:
            trades = parse_pump_frontend_trades(raw, mint=mint, t0=t0, sol_usd=0.0)
            q5a = aggregate_q5a_for_mint(trades, t0) if trades else {c: None for c in Q5A_COLS}
            buy60, buy_n = buy_vol_60s_from_trades(trades, t0) if trades else (None, None)
            for c in Q5A_COLS:
                base[c] = q5a.get(c)
            base["buy_vol_usd_60s"] = buy60
            base["buy_count_60s"] = buy_n
            base["n_trades_pre_t0"] = len(trades)
            base["n_raw_trades"] = len(raw)
            base["fetch_ok"] = 1
        except Exception as e:  # noqa: BLE001
            base["fetch_ok"] = 0
            base["fetch_error"] = f"{type(e).__name__}:{e}"[:300]
            base["n_trades_pre_t0"] = 0
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None

        matrix_rows.append(base)
        r.update(
            {
                "hit_10x_30d": lab_info["hit_10x_30d"],
                "max_multiple_30d": lab_info["max_multiple_30d"],
                "label_source": lab_info["label_source"],
                "capture_scoreable": int(scoreable),
                "n_trades_pre_t0": base.get("n_trades_pre_t0"),
                "dt_vs_expand_h": (
                    (t0 - expand_t0).total_seconds() / 3600.0 if expand_t0 else None
                ),
            }
        )

    recon_df = pd.DataFrame(list(recon_by_mint.values()))
    mat = pd.DataFrame(matrix_rows)
    for c in FEATURE_SETS["+q5b"]:
        if c not in mat.columns:
            mat[c] = np.nan

    # WF-ready subset: reconstructable + scoreable + fetch_ok + label not null
    usable = mat[
        (mat["reconstructable"] == 1)
        & (mat["capture_scoreable"] == True)  # noqa: E712
        & (mat["fetch_ok"] == 1)
        & (mat["hit_10x_30d"].notna())
    ].copy()

    n_recon = int((recon_df["reconstructable"] == 1).sum())
    n_exact = int(recon_df["reconstruct_method"].isin(["pump_trade_mc_band", "pump_trade_mc_band_deep"]).sum())
    label_rate = float(usable["hit_10x_30d"].mean()) if len(usable) else None
    empty_pre = int((usable["n_trades_pre_t0"].fillna(0) <= 0).sum()) if len(usable) else 0

    out_sample_df = usable[["mint", "t0_ts", "mc_usd_t0", "hit_10x_30d", "reconstruct_method"]].copy()
    out_sample_df.to_csv(out_sample, index=False)
    mat.to_csv(out_matrix, index=False)
    recon_df.to_csv(out_t0, index=False)

    meta = {
        "kind": "pump_mcband_pilot_build",
        "generated_at": _utcnow(),
        "t0_policy": T0_POLICY,
        "t0_definition": PUMP_MC_SIGHTING_DEF,
        "t0_recipe": {
            "implied_mc": "priceUsd * 1e9",
            "band": [MC_LO_USD, MC_HI_USD],
            "t0": "first chronological Pump trade with MC in band",
            "proxies": {
                "deep_fetch": True,
                "expand_create_proxy": bool(args.allow_expand_proxy),
            },
            "non_reconstructable": "never_in_band or no_trades after deep fetch",
        },
        "label_recipe": {
            "hit": "max_mc_after_t0 >= 10 * mc_t0 within 30d",
            "local_trades": "implied MC from Pump trades (t0, t0+30d]",
            "expand_max": (
                "labels_dune_expand_v2.max_mc_after_t0 when expand_t0>=new_t0 "
                f"or |Δ|<= {EXPAND_T0_SLACK}"
            ),
            "dune_api": 0,
        },
        "anti_lookahead": {
            "features": "Q5a/buy60 from trades with ts <= new_t0 only",
            "labels": "only post-T0 prices/MC; expand max only if expand_t0>=new_t0 or ≤1h slack",
        },
        "n_sample": int(len(sample)),
        "n_reconstructable": n_recon,
        "n_reconstructable_trade_band": n_exact,
        "n_unreconstructable": int((recon_df["reconstructable"] == 0).sum()),
        "reconstruct_method_counts": recon_df["reconstruct_method"].value_counts().to_dict(),
        "n_matrix_rows": int(len(mat)),
        "n_usable_wf": int(len(usable)),
        "label_rate_usable": label_rate,
        "label_rate_all_recon": float(
            mat.loc[mat["reconstructable"] == 1, "hit_10x_30d"].mean()
        )
        if (mat["reconstructable"] == 1).any()
        else None,
        "n_empty_pre_t0_usable": empty_pre,
        "frac_empty_pre_t0_usable": float(empty_pre / len(usable)) if len(usable) else None,
        "deep_fetch": deep_stats,
        "paths": {
            "matrix": str(out_matrix),
            "sample_usable": str(out_sample),
            "t0_recon": str(out_t0),
            "trades_cache_reused": str(trades_dir),
            "deep_trades": str(deep_trades_dir),
        },
        "dune_api_calls": 0,
        "lite": False,
        "usd_scale": False,
        "allow_expand_proxy": bool(args.allow_expand_proxy),
    }
    _save_json(out_meta, meta)
    print(json.dumps(meta, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
