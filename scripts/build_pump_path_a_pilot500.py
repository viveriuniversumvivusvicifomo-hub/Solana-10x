#!/usr/bin/env python3
"""GO-1 pilot: ~500 expand mints × Pump frontend trades → labeled partial matrix.

Hard constraints (enforced):
- 0 Dune API calls
- Cap ~500 mints; STOP if rate-limits/errors explode
- Never overwrite q5b_last / q5b_calibration.json
- Never touch paper_live PID
- Lite OFF; USD scale OFF

T0 policy (explicit): **expand_t0_ts**
  Labels are defined vs expand ``t0_ts``. Filter Pump trades with ts ≤ expand t0_ts.
  Live captura uses ``pump_mc_band_sighting_v1`` — residual mismatch accepted for pilot;
  rebasing to Pump MC band needs MC history we do not have offline.

Sample rule (documented):
  Frame = expand ⋈ labels with t0_ts ≥ 2026-09-01 (fold-friendly / recent).
  Stratified by hit_10x_30d to preserve frame base rate; random_state=42; n=500.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from features.post_q5_sets import FEATURE_SETS, Q5A_COLS, Q5B_COLS  # noqa: E402

STAMP_DEFAULT = datetime.now().strftime("%Y%m%d")
T0_POLICY = "expand_t0_ts"
SAMPLE_RULE = (
    "frame=expand⋈labels with t0_ts>=2026-09-01; stratify hit_10x_30d "
    "preserve frame base-rate; random_state=42; n≈500"
)
# STOP fences
MAX_FAIL_FRAC = 0.25
MAX_CONSEC_HARD_FAIL = 15
MAX_429_RETRIES_TOTAL = 80
MIN_INTERVAL_S = 1.0  # slightly gentler than default 0.8
MAX_HTTP_BUDGET = 5500  # hard STOP; well below ~410k full-expand


def _utcnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sample_expand_mints(
    feat_path: Path,
    lab_path: Path,
    *,
    n: int = 500,
    t0_min: str = "2026-09-01",
    seed: int = 42,
) -> pd.DataFrame:
    """Stratified recent expand sample with labels + store Q5b cols."""
    usecols = (
        ["mint", "t0_ts", "mc_usd_t0", "create_ts", "creator_pubkey"]
        + [c for c in FEATURE_SETS["+q5b"] if True]
    )
    # Read features — only needed cols that exist
    header = pd.read_csv(feat_path, nrows=0).columns.tolist()
    cols = [c for c in usecols if c in header]
    feat = pd.read_csv(feat_path, usecols=cols)
    lab = pd.read_csv(lab_path)
    if "hit_10x_30d" not in lab.columns:
        raise SystemExit("labels missing hit_10x_30d")
    merge_cols = ["mint", "hit_10x_30d"]
    if "hit_200k" in lab.columns:
        merge_cols.append("hit_200k")
    df = feat.merge(lab[merge_cols], on="mint", how="inner", validate="one_to_one")
    df["t0"] = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    df = df.dropna(subset=["t0"])
    df["hit_10x_30d"] = df["hit_10x_30d"].astype(int)
    frame = df[df["t0"] >= pd.Timestamp(t0_min, tz="UTC")].copy()
    if len(frame) < n:
        frame = df.copy()  # fall back to full expand
    # Stratified sample
    rng = np.random.default_rng(seed)
    pos = frame[frame["hit_10x_30d"] == 1]
    neg = frame[frame["hit_10x_30d"] == 0]
    rate = float(frame["hit_10x_30d"].mean())
    n_pos = int(round(n * rate))
    n_pos = max(1, min(n_pos, len(pos), n - 1))
    n_neg = min(n - n_pos, len(neg))
    # Prefer recent within stratum: weight by rank of t0
    def _pick(sub: pd.DataFrame, k: int) -> pd.DataFrame:
        if k >= len(sub):
            return sub
        sub = sub.sort_values("t0", ascending=False).reset_index(drop=True)
        # 70% from most-recent half, 30% from older half
        mid = max(1, len(sub) // 2)
        recent = sub.iloc[:mid]
        older = sub.iloc[mid:]
        k_r = min(int(round(k * 0.7)), len(recent))
        k_o = min(k - k_r, len(older))
        k_r = k - k_o  # fill remainder from recent if older short
        k_r = min(k_r, len(recent))
        idx_r = rng.choice(len(recent), size=k_r, replace=False)
        parts = [recent.iloc[idx_r]]
        if k_o > 0:
            idx_o = rng.choice(len(older), size=k_o, replace=False)
            parts.append(older.iloc[idx_o])
        out = pd.concat(parts, ignore_index=True)
        # if still short (edge), top-up from leftover
        if len(out) < k:
            left = sub[~sub["mint"].isin(out["mint"])]
            need = k - len(out)
            if len(left) > 0:
                idx = rng.choice(len(left), size=min(need, len(left)), replace=False)
                out = pd.concat([out, left.iloc[idx]], ignore_index=True)
        return out

    picked = pd.concat([_pick(pos, n_pos), _pick(neg, n_neg)], ignore_index=True)
    picked = picked.sample(frac=1.0, random_state=seed).reset_index(drop=True)
    if len(picked) > n:
        picked = picked.iloc[:n].reset_index(drop=True)
    picked.attrs["sample_meta"] = {
        "sample_rule": SAMPLE_RULE,
        "t0_policy": T0_POLICY,
        "n_requested": n,
        "n_sampled": len(picked),
        "frame_n": len(frame),
        "frame_t0_min": t0_min,
        "frame_hit_rate": rate,
        "sample_hit_rate": float(picked["hit_10x_30d"].mean()),
        "n_pos": int((picked["hit_10x_30d"] == 1).sum()),
        "n_neg": int((picked["hit_10x_30d"] == 0).sum()),
        "seed": seed,
        "t0_min_sampled": str(picked["t0"].min()),
        "t0_max_sampled": str(picked["t0"].max()),
    }
    return picked


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"done": {}, "errors": {}, "stats": {}}
    return json.loads(path.read_text())


def _save_checkpoint(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2))
    tmp.replace(path)



def fetch_trades_until_t0(
    mint: str,
    t0: datetime,
    *,
    client: Any,
    max_pages: int = 12,
    page_limit: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Cursor-paginate Pump trades newest→oldest until oldest ≤ t0 or cap.

    Unlike ``fetch_trades_for_mint(limit=200)`` which truncates at 200 rows
    (often all post-t0 for still-traded mints), this keeps walking until the
    expand T0 window is reached or ``max_pages`` is hit.
    """
    from urllib.parse import quote
    from ingestion.pump_frontend import SOLANA_MAINNET_CHAIN_ID, TRADES_PAGE_MAX

    if t0.tzinfo is None:
        t0 = t0.replace(tzinfo=timezone.utc)
    t0_ms = t0.timestamp() * 1000.0
    path = f"/trades/{quote(SOLANA_MAINNET_CHAIN_ID, safe='')}/{mint}"
    out: list[dict[str, Any]] = []
    cursor: str | None = None
    n_pages = 0
    oldest_ms: float | None = None
    reached_t0 = False
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
            ts_raw = tr.get("blockTimeMs") or tr.get("timestamp") or tr.get("blockTime")
            if ts_raw is None:
                continue
            try:
                ts = float(ts_raw)
            except (TypeError, ValueError):
                continue
            if ts < 1e12:
                ts *= 1000.0
            page_oldest = ts if page_oldest is None else min(page_oldest, ts)
            if ts <= t0_ms + 1.0:
                reached_t0 = True
        if page_oldest is not None:
            oldest_ms = page_oldest if oldest_ms is None else min(oldest_ms, page_oldest)
        if not cursor:
            break
        # Once we have ≥15m of pre-t0 coverage, further pages add little for
        # windowed Q5a (30s/15m); totals/age_proxy may still be partial — pilot OK.
        if (
            reached_t0
            and page_oldest is not None
            and page_oldest <= t0_ms - 15 * 60 * 1000.0
        ):
            break
    meta = {
        "n_pages": n_pages,
        "n_raw": len(out),
        "reached_t0": reached_t0,
        "oldest_ms": oldest_ms,
    }
    return out, meta


def fetch_pilot_trades(
    mints: list[str],
    t0_by_mint: dict[str, datetime],
    *,
    checkpoint: Path,
    trades_dir: Path,
    max_pages: int = 12,
    limit: int = 200,  # unused; kept for CLI compat
    min_interval_s: float = MIN_INTERVAL_S,
) -> dict[str, Any]:
    """Fetch Pump trades for mints; checkpoint progress; STOP on error explosion."""
    from ingestion.pump_frontend import PumpFrontendClient

    del limit  # pagination is until-t0 / max_pages, not a hard row cap
    trades_dir.mkdir(parents=True, exist_ok=True)
    ck = _load_checkpoint(checkpoint)
    done: dict[str, Any] = dict(ck.get("done") or {})
    errors: dict[str, Any] = dict(ck.get("errors") or {})
    client = PumpFrontendClient(min_interval_s=min_interval_s, max_retries_429=5)
    consec_hard = 0
    stopped = False
    stop_reason = None
    t0_wall = time.time()
    try:
        for i, mint in enumerate(mints):
            if mint in done and done[mint].get("ok"):
                consec_hard = 0
                continue
            try:
                t0 = t0_by_mint[mint]
                raw, fmeta = fetch_trades_until_t0(
                    mint, t0, client=client, max_pages=max_pages
                )
                out_path = trades_dir / f"{mint}.json"
                out_path.write_text(
                    json.dumps(
                        {
                            "mint": mint,
                            "t0_ts": t0.isoformat(),
                            "n_raw": len(raw or []),
                            "fetch_meta": fmeta,
                            "fetched_at": _utcnow(),
                            "trades": raw or [],
                        }
                    )
                )
                done[mint] = {
                    "ok": True,
                    "n_raw": len(raw or []),
                    "reached_t0": bool(fmeta.get("reached_t0")),
                    "n_pages": int(fmeta.get("n_pages") or 0),
                    "path": str(out_path.relative_to(ROOT)),
                    "http_calls_so_far": client.log.n_calls,
                    "n_retries_429_so_far": client.log.n_retries_429,
                }
                errors.pop(mint, None)
                consec_hard = 0
            except Exception as e:  # noqa: BLE001
                err_s = f"{type(e).__name__}: {e}"[:300]
                errors[mint] = {"ok": False, "error": err_s, "at": _utcnow()}
                done[mint] = {"ok": False, "error": err_s}
                consec_hard += 1
                hard = "429" in err_s or "rate limit" in err_s.lower() or "HTTP 5" in err_s
                if not hard:
                    # non-rate errors still count toward fail frac
                    pass

            n_attempted = len(done)
            n_fail = sum(1 for v in done.values() if not v.get("ok"))
            fail_frac = n_fail / max(1, n_attempted)
            stats = {
                "n_attempted": n_attempted,
                "n_ok": sum(1 for v in done.values() if v.get("ok")),
                "n_fail": n_fail,
                "fail_frac": fail_frac,
                "http_calls": client.log.n_calls,
                "n_retries_429": client.log.n_retries_429,
                "consec_hard_fail": consec_hard,
                "elapsed_s": round(time.time() - t0_wall, 1),
                "last_mint_i": i,
            }
            ck = {
                "kind": "pump_pilot500_checkpoint",
                "updated_at": _utcnow(),
                "t0_policy": T0_POLICY,
                "done": done,
                "errors": errors,
                "stats": stats,
                "client_log": client.log.to_dict(),
            }
            _save_checkpoint(checkpoint, ck)

            # STOP fences
            if client.log.n_retries_429 >= MAX_429_RETRIES_TOTAL:
                stopped, stop_reason = True, f"429_retries>={MAX_429_RETRIES_TOTAL}"
            elif consec_hard >= MAX_CONSEC_HARD_FAIL:
                stopped, stop_reason = True, f"consec_hard_fail>={MAX_CONSEC_HARD_FAIL}"
            elif n_attempted >= 40 and fail_frac >= MAX_FAIL_FRAC:
                stopped, stop_reason = True, f"fail_frac={fail_frac:.2f}>={MAX_FAIL_FRAC}"
            elif client.log.n_calls >= MAX_HTTP_BUDGET:
                stopped, stop_reason = True, f"http_budget>={MAX_HTTP_BUDGET}"
            if stopped:
                ck["stopped"] = True
                ck["stop_reason"] = stop_reason
                _save_checkpoint(checkpoint, ck)
                break

            if (i + 1) % 25 == 0:
                print(
                    json.dumps(
                        {
                            "progress": i + 1,
                            "of": len(mints),
                            **stats,
                        }
                    ),
                    flush=True,
                )
    finally:
        client.close()

    ck = _load_checkpoint(checkpoint)
    ck["finished_at"] = _utcnow()
    if stopped:
        ck["stopped"] = True
        ck["stop_reason"] = stop_reason
    _save_checkpoint(checkpoint, ck)
    return ck


def build_matrix_from_trades(
    sample: pd.DataFrame,
    trades_dir: Path,
    checkpoint: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Overlay Pump Q5a/buy60 onto expand Q5b/priors; join labels."""
    from paper_live.pump_enrich import buy_vol_60s_from_trades, parse_pump_frontend_trades
    from paper_live.q5a_agg import aggregate_q5a_for_mint

    done = checkpoint.get("done") or {}
    rows: list[dict[str, Any]] = []
    n_ok = n_fail = n_empty = 0
    for _, sr in sample.iterrows():
        mint = str(sr["mint"])
        st = done.get(mint) or {}
        base: dict[str, Any] = {
            "mint": mint,
            "t0_ts": sr["t0_ts"],
            "mc_usd_t0": sr.get("mc_usd_t0"),
            "hit_10x_30d": int(sr["hit_10x_30d"]),
            "hit_200k": int(sr["hit_200k"]) if "hit_200k" in sr.index and pd.notna(sr.get("hit_200k")) else int(sr["hit_10x_30d"]),
            "t0_policy": T0_POLICY,
            "label_source": "labels_dune_expand_v2",
            "sol_usd_source": "pump_frontend",
            "feature_overlay": "pump_trades_q5a_buy60",
        }
        # Keep Q5b / age / name / priors from expand store
        for c in Q5B_COLS:
            base[c] = sr[c] if c in sr.index else None
        # Also keep store copies for delta diagnostics
        for c in list(Q5A_COLS) + ["buy_vol_usd_60s"]:
            if c in sr.index:
                base[f"store_{c}"] = sr[c]

        if not st.get("ok"):
            n_fail += 1
            base["fetch_ok"] = 0
            base["n_trades_pre_t0"] = 0
            base["fetch_error"] = st.get("error")
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None
            rows.append(base)
            continue

        trades_path = ROOT / st["path"] if not Path(st["path"]).is_absolute() else Path(st["path"])
        try:
            payload = json.loads(trades_path.read_text())
            raw = payload.get("trades") or []
            t0 = pd.Timestamp(sr["t0_ts"])
            if t0.tzinfo is None:
                t0 = t0.tz_localize("UTC")
            t0_dt = t0.to_pydatetime()
            trades = parse_pump_frontend_trades(raw, mint=mint, t0=t0_dt, sol_usd=0.0)
            q5a = aggregate_q5a_for_mint(trades, t0_dt) if trades else {c: None for c in Q5A_COLS}
            buy60, buy_n = buy_vol_60s_from_trades(trades, t0_dt) if trades else (None, None)
            for c in Q5A_COLS:
                base[c] = q5a.get(c)
            base["buy_vol_usd_60s"] = buy60
            base["buy_count_60s"] = buy_n
            base["n_trades_pre_t0"] = len(trades)
            base["n_raw_trades"] = len(raw)
            base["fetch_ok"] = 1
            if not trades:
                n_empty += 1
            else:
                n_ok += 1
        except Exception as e:  # noqa: BLE001
            n_fail += 1
            base["fetch_ok"] = 0
            base["n_trades_pre_t0"] = 0
            base["fetch_error"] = f"build:{type(e).__name__}:{e}"[:300]
            for c in Q5A_COLS:
                base[c] = None
            base["buy_vol_usd_60s"] = None
        rows.append(base)

    mat = pd.DataFrame(rows)
    # Ensure +q5b cols present
    for c in FEATURE_SETS["+q5b"]:
        if c not in mat.columns:
            mat[c] = np.nan
    meta = {
        "n_rows": len(mat),
        "n_fetch_ok_with_trades": n_ok,
        "n_fetch_ok_empty_pre_t0": n_empty,
        "n_fetch_fail": n_fail,
        "label_rate": float(mat["hit_10x_30d"].mean()) if len(mat) else None,
        "t0_policy": T0_POLICY,
        "sample_rule": SAMPLE_RULE,
    }
    return mat, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--stamp", default=STAMP_DEFAULT)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--t0-min", default="2026-09-01")
    ap.add_argument("--max-pages", type=int, default=12)
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--min-interval-s", type=float, default=MIN_INTERVAL_S)
    ap.add_argument(
        "--sample-only",
        action="store_true",
        help="Write sample list and exit (no network)",
    )
    ap.add_argument(
        "--build-only",
        action="store_true",
        help="Skip fetch; build matrix from existing checkpoint/trades",
    )
    ap.add_argument(
        "--fetch-only",
        action="store_true",
        help="Sample+fetch; skip matrix CSV write",
    )
    args = ap.parse_args()

    if args.n > 2000:
        print("REFUSE: n>2000 approaches scale fence; cap pilot ≤2000")
        return 2

    feat_path = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
    lab_path = ROOT / "data/samples/labels_dune_expand_v2.csv"
    out_dir = ROOT / "data/samples"
    ck_path = ROOT / f"cycle0/artifacts/pump_pilot500_checkpoint_{args.stamp}.json"
    trades_dir = ROOT / f"data/samples/pump_pilot500_trades_{args.stamp}"
    sample_path = out_dir / f"pump_pilot500_sample_{args.stamp}.csv"
    matrix_path = out_dir / f"features_pump_path_a_pilot500_{args.stamp}.csv"
    meta_path = ROOT / f"cycle0/artifacts/pump_pilot500_build_meta_{args.stamp}.json"

    sample = sample_expand_mints(
        feat_path, lab_path, n=args.n, t0_min=args.t0_min, seed=args.seed
    )
    sample_meta = dict(sample.attrs.get("sample_meta") or {})
    sample.to_csv(sample_path, index=False)
    print(json.dumps({"sample": sample_meta, "sample_path": str(sample_path)}, indent=2))

    if args.sample_only:
        return 0

    mints = sample["mint"].astype(str).tolist()
    if not args.build_only:
        print(
            json.dumps(
                {
                    "fetch_start": _utcnow(),
                    "n_mints": len(mints),
                    "max_pages": args.max_pages,
                    "limit": args.limit,
                    "est_http_upper": len(mints) * args.max_pages,
                    "min_interval_s": args.min_interval_s,
                }
            ),
            flush=True,
        )
        t0_by_mint: dict[str, datetime] = {}
        for _, r in sample.iterrows():
            ts = pd.Timestamp(r["t0_ts"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            t0_by_mint[str(r["mint"])] = ts.to_pydatetime()
        ck = fetch_pilot_trades(
            mints,
            t0_by_mint,
            checkpoint=ck_path,
            trades_dir=trades_dir,
            max_pages=args.max_pages,
            limit=args.limit,
            min_interval_s=args.min_interval_s,
        )
        if ck.get("stopped"):
            print(
                json.dumps(
                    {
                        "status": "STOPPED",
                        "stop_reason": ck.get("stop_reason"),
                        "stats": ck.get("stats"),
                        "checkpoint": str(ck_path),
                    },
                    indent=2,
                )
            )
            # Still try to build partial matrix from what we have
        else:
            print(json.dumps({"fetch_done": ck.get("stats"), "checkpoint": str(ck_path)}, indent=2))
    else:
        ck = _load_checkpoint(ck_path)

    if args.fetch_only:
        meta_path.write_text(
            json.dumps(
                {
                    "sample": sample_meta,
                    "checkpoint": str(ck_path),
                    "stats": ck.get("stats"),
                    "stopped": ck.get("stopped"),
                    "stop_reason": ck.get("stop_reason"),
                    "dune_api_calls": 0,
                    "generated_at": _utcnow(),
                },
                indent=2,
            )
            + "\n"
        )
        return 0 if not ck.get("stopped") else 3

    mat, build_meta = build_matrix_from_trades(sample, trades_dir, ck)
    mat.to_csv(matrix_path, index=False)
    doc = {
        "kind": "pump_path_a_pilot500_build",
        "generated_at": _utcnow(),
        "t0_policy": T0_POLICY,
        "sample_rule": SAMPLE_RULE,
        "sample": sample_meta,
        "build": build_meta,
        "matrix_path": str(matrix_path),
        "matrix_shape": list(mat.shape),
        "checkpoint": str(ck_path),
        "fetch_stats": ck.get("stats"),
        "stopped": ck.get("stopped", False),
        "stop_reason": ck.get("stop_reason"),
        "dune_api_calls": 0,
        "apply_dune_helius_usd_scale": False,
        "lite": False,
        "paper_live_untouched": True,
    }
    meta_path.write_text(json.dumps(doc, indent=2) + "\n")
    print(json.dumps(doc, indent=2))
    return 0 if not ck.get("stopped") else 3


if __name__ == "__main__":
    raise SystemExit(main())
