"""Extract pre-T0 flow / age / authority features from pumpapi replay JSONL.zst.

Streams zstd line-by-line; keeps only the requested mint set in memory.
Windows end at each capture's T0. Age is first-seen-in-replay-window, not
on-chain create age. Holders are unavailable in free replay (no Bitquery/Helius).

Streams Helius: OFF. No secrets in outputs.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import zstandard as zstd

EPS = 1e-12
WINDOWS_S: tuple[tuple[str, int | None], ...] = (
    ("60s", 60),
    ("5m", 300),
    ("all", None),
)
FEATURE_NAMES = (
    # flow windows
    "buy_count_60s",
    "sell_count_60s",
    "buy_vol_sol_60s",
    "sell_vol_sol_60s",
    "unique_buyers_60s",
    "unique_sellers_60s",
    "buy_sell_ratio_vol_60s",
    "net_flow_sol_60s",
    "buy_count_5m",
    "sell_count_5m",
    "buy_vol_sol_5m",
    "sell_vol_sol_5m",
    "unique_buyers_5m",
    "unique_sellers_5m",
    "buy_sell_ratio_vol_5m",
    "net_flow_sol_5m",
    "buy_count_all",
    "sell_count_all",
    "buy_vol_sol_all",
    "sell_vol_sol_all",
    "unique_buyers_all",
    "unique_sellers_all",
    "buy_sell_ratio_vol_all",
    "net_flow_sol_all",
    # totals / rate
    "trade_count_total",
    "unique_traders_total",
    "buys_per_min",
    # age (replay-window proxy)
    "t_first_event_ms",
    "age_s_replay",
    "time_since_first_trade_s",
    # authorities
    "mint_authority_none",
    "freeze_authority_none",
    # holders (unavailable)
    "holder_count",
    "top1_pct",
    "top5_pct",
    "top10_pct",
)


def parse_t0_to_ms(t0: str | datetime) -> int:
    """Parse ISO T0 to UTC epoch milliseconds."""
    if isinstance(t0, datetime):
        dt = t0
    else:
        s = str(t0).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return int(dt.timestamp() * 1000)


def _safe_float(v: Any, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def iter_trade_legs(
    obj: Mapping[str, Any],
) -> Iterable[tuple[str, float, str | None, bool]]:
    """Yield (action, quote_sol, trader, counts_as_trade) for buy/sell legs.

    Prefer ``breakdown`` when present (handles multi-leg / create initial buy).
    Else use top-level buy/sell once; extra tradersInvolved keys only expand
    the unique set (counts_as_trade=False, vol=0).
    """
    bd = obj.get("breakdown")
    if isinstance(bd, list) and bd:
        for leg in bd:
            if not isinstance(leg, Mapping):
                continue
            action = leg.get("action")
            if action not in ("buy", "sell"):
                continue
            trader = leg.get("trader")
            if not isinstance(trader, str) or not trader:
                trader = None
            yield action, _safe_float(leg.get("quoteAmount")), trader, True
        return

    action = obj.get("action")
    if action not in ("buy", "sell"):
        return
    qa = _safe_float(obj.get("quoteAmount"))
    traders: list[str] = []
    ti = obj.get("tradersInvolved")
    if isinstance(ti, dict) and ti:
        traders = [k for k in ti.keys() if isinstance(k, str) and k]
    if not traders:
        sig = obj.get("txSigner")
        if isinstance(sig, str) and sig:
            traders = [sig]
    if traders:
        yield action, qa, traders[0], True
        for extra in traders[1:]:
            yield action, 0.0, extra, False
    else:
        yield action, qa, None, True


@dataclass
class _WindowAcc:
    buy_count: int = 0
    sell_count: int = 0
    buy_vol: float = 0.0
    sell_vol: float = 0.0
    buyers: set[str] = field(default_factory=set)
    sellers: set[str] = field(default_factory=set)

    def add(
        self, action: str, vol: float, trader: str | None, *, counts: bool = True
    ) -> None:
        if action == "buy":
            if counts:
                self.buy_count += 1
                self.buy_vol += vol
            elif vol:
                self.buy_vol += vol
            if trader:
                self.buyers.add(trader)
        elif action == "sell":
            if counts:
                self.sell_count += 1
                self.sell_vol += vol
            elif vol:
                self.sell_vol += vol
            if trader:
                self.sellers.add(trader)


@dataclass
class MintAccum:
    capture_id: str
    mint: str
    t0: str
    t0_ms: int
    t_first_event_ms: int | None = None
    t_first_trade_ms: int | None = None
    mint_authority_seen: bool = False
    mint_authority: Any = None
    freeze_authority_seen: bool = False
    freeze_authority: Any = None
    win_60s: _WindowAcc = field(default_factory=_WindowAcc)
    win_5m: _WindowAcc = field(default_factory=_WindowAcc)
    win_all: _WindowAcc = field(default_factory=_WindowAcc)
    n_events_pre_t0: int = 0

    def observe_event(self, obj: Mapping[str, Any], ts: int) -> None:
        if ts > self.t0_ms:
            return
        self.n_events_pre_t0 += 1
        if self.t_first_event_ms is None or ts < self.t_first_event_ms:
            self.t_first_event_ms = ts

        if "mintAuthority" in obj:
            self.mint_authority_seen = True
            self.mint_authority = obj.get("mintAuthority")
        if "freezeAuthority" in obj:
            self.freeze_authority_seen = True
            self.freeze_authority = obj.get("freezeAuthority")

        legs = list(iter_trade_legs(obj))
        if not legs:
            return

        if self.t_first_trade_ms is None or ts < self.t_first_trade_ms:
            self.t_first_trade_ms = ts

        in_60 = ts >= self.t0_ms - 60_000
        in_5m = ts >= self.t0_ms - 300_000
        for action, vol, trader, counts in legs:
            self.win_all.add(action, vol, trader, counts=counts)
            if in_5m:
                self.win_5m.add(action, vol, trader, counts=counts)
            if in_60:
                self.win_60s.add(action, vol, trader, counts=counts)


def _window_features(prefix: str, w: _WindowAcc) -> dict[str, Any]:
    sell_vol = w.sell_vol
    buy_vol = w.buy_vol
    return {
        f"buy_count_{prefix}": w.buy_count,
        f"sell_count_{prefix}": w.sell_count,
        f"buy_vol_sol_{prefix}": buy_vol,
        f"sell_vol_sol_{prefix}": sell_vol,
        f"unique_buyers_{prefix}": len(w.buyers),
        f"unique_sellers_{prefix}": len(w.sellers),
        f"buy_sell_ratio_vol_{prefix}": buy_vol / max(sell_vol, EPS),
        f"net_flow_sol_{prefix}": buy_vol - sell_vol,
    }


def row_from_accum(acc: MintAccum) -> dict[str, Any]:
    missing = acc.n_events_pre_t0 == 0
    out: dict[str, Any] = {
        "capture_id": acc.capture_id,
        "mint": acc.mint,
        "t0": acc.t0,
        "feature_ts": acc.t0,
        "missing_pre_t0": missing,
        "holders_status": "unavailable_in_replay_free",
        "holder_count": None,
        "top1_pct": None,
        "top5_pct": None,
        "top10_pct": None,
        "age_source": "replay_first_seen_in_window",
        "streams_helius": "OFF",
    }

    if missing:
        for name in FEATURE_NAMES:
            if name.startswith(("holder", "top")):
                continue
            out[name] = None
        out["mint_authority_none"] = None
        out["freeze_authority_none"] = None
        return out

    out.update(_window_features("60s", acc.win_60s))
    out.update(_window_features("5m", acc.win_5m))
    out.update(_window_features("all", acc.win_all))

    trade_total = acc.win_all.buy_count + acc.win_all.sell_count
    unique_total = len(acc.win_all.buyers | acc.win_all.sellers)
    out["trade_count_total"] = trade_total
    out["unique_traders_total"] = unique_total

    t_first = acc.t_first_event_ms
    out["t_first_event_ms"] = t_first
    if t_first is not None:
        age_s = (acc.t0_ms - t_first) / 1000.0
        out["age_s_replay"] = age_s
        # buys_per_min: buy_count_all / max((t0 - t_first)/60, eps)
        span_min = max((acc.t0_ms - t_first) / 1000.0 / 60.0, EPS)
        out["buys_per_min"] = acc.win_all.buy_count / span_min
    else:
        out["age_s_replay"] = None
        out["buys_per_min"] = None

    if acc.t_first_trade_ms is not None:
        out["time_since_first_trade_s"] = (acc.t0_ms - acc.t_first_trade_ms) / 1000.0
    else:
        out["time_since_first_trade_s"] = None

    if acc.mint_authority_seen:
        out["mint_authority_none"] = acc.mint_authority is None
    else:
        out["mint_authority_none"] = None
    if acc.freeze_authority_seen:
        out["freeze_authority_none"] = acc.freeze_authority is None
    else:
        out["freeze_authority_none"] = None

    return out


def load_cohort(path: Path) -> list[MintAccum]:
    data = json.loads(path.read_text())
    rows = data["rows"] if isinstance(data, dict) and "rows" in data else data
    accs: list[MintAccum] = []
    for r in rows:
        t0 = r["t0"]
        accs.append(
            MintAccum(
                capture_id=r["capture_id"],
                mint=r["mint"],
                t0=t0,
                t0_ms=parse_t0_to_ms(t0),
            )
        )
    return accs


def stream_zstd_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    dctx = zstd.ZstdDecompressor()
    with path.open("rb") as fh, dctx.stream_reader(fh) as reader:
        text = io.TextIOWrapper(reader, encoding="utf-8")
        for line in text:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def extract_from_replay(
    cohort: Sequence[MintAccum],
    replay_paths: Sequence[Path],
    *,
    progress_every: int = 500_000,
) -> dict[str, Any]:
    by_mint: dict[str, MintAccum] = {a.mint: a for a in cohort}
    if len(by_mint) != len(cohort):
        raise ValueError("cohort mints must be unique for this extractor")
    mint_set = set(by_mint.keys())

    n_lines = 0
    n_matched = 0
    t0 = time.perf_counter()

    for rpath in replay_paths:
        for obj in stream_zstd_jsonl(rpath):
            n_lines += 1
            if progress_every and n_lines % progress_every == 0:
                elapsed = time.perf_counter() - t0
                print(
                    f"  … {n_lines:,} lines ({elapsed:.1f}s) matched_events={n_matched:,}",
                    file=sys.stderr,
                    flush=True,
                )
            mint = obj.get("mint")
            if not isinstance(mint, str) or mint not in mint_set:
                continue
            ts = obj.get("timestamp")
            if not isinstance(ts, (int, float)):
                continue
            ts_i = int(ts)
            acc = by_mint[mint]
            if ts_i > acc.t0_ms:
                continue
            n_matched += 1
            acc.observe_event(obj, ts_i)

    rows = [row_from_accum(a) for a in cohort]
    n_with = sum(1 for r in rows if not r["missing_pre_t0"])
    n_missing = sum(1 for r in rows if r["missing_pre_t0"])
    elapsed = time.perf_counter() - t0

    meta = {
        "hours_used": [p.name.removesuffix(".jsonl.zst") for p in replay_paths],
        "replay_paths": [str(p) for p in replay_paths],
        "n_cohort": len(rows),
        "n_with_pre_t0_events": n_with,
        "n_missing_pre_t0": n_missing,
        "n_lines_scanned": n_lines,
        "n_matched_mint_pre_t0_events": n_matched,
        "elapsed_s": round(elapsed, 3),
        "feature_names_filled": list(FEATURE_NAMES),
        "windows_s": {"60s": 60, "5m": 300, "all": "t_first_to_t0"},
        "streams_helius": "OFF",
        "secrets": False,
        "holders_status": "unavailable_in_replay_free",
        "caveats": [
            "age_s_replay is first-seen-in-4h-replay-window, NOT on-chain create age",
            "4h window ≠ 30d label horizon",
            "no holders (holder_count/top*_pct null; holders_status=unavailable_in_replay_free)",
            "no sol_usd_t0 / max_mc_* / label_* / PRIMARY in this extract",
            "authorities from last replay event ≤T0 that carried the fields",
        ],
        "feature_source": "pumpapi_replay_pre_t0",
        "feature_set_version": "features.mvp.v0",
    }
    return {"meta": meta, "rows": rows}


def default_paths(root: Path | None = None) -> tuple[Path, list[Path], Path]:
    root = root or Path(__file__).resolve().parents[2]
    cohort = root / "data" / "samples" / "features_p0_min_pumpapi_cohort.json"
    replay_dir = root / "data" / "samples" / "pumpapi_replay"
    hours = [replay_dir / f"{h}.jsonl.zst" for h in (15, 16, 17, 18)]
    out = root / "data" / "samples" / "features_replay_pre_t0_cohort200.json"
    return cohort, hours, out


def run(
    *,
    cohort_path: Path | None = None,
    replay_paths: Sequence[Path] | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    c_default, r_default, o_default = default_paths()
    cohort_path = cohort_path or c_default
    replay_paths = list(replay_paths) if replay_paths is not None else r_default
    out_path = out_path or o_default

    for p in replay_paths:
        if not p.is_file():
            raise FileNotFoundError(f"missing replay file (do not re-download): {p}")

    print(f"loading cohort {cohort_path}", file=sys.stderr)
    cohort = load_cohort(cohort_path)
    print(f"n_cohort={len(cohort)} streaming {len(replay_paths)} files…", file=sys.stderr)

    result = extract_from_replay(cohort, replay_paths)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"wrote {out_path}", file=sys.stderr)
    print(json.dumps(result["meta"], indent=2), file=sys.stderr)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument(
        "--replay",
        type=Path,
        nargs="*",
        default=None,
        help="jsonl.zst paths (default: hours 15-18 under data/samples/pumpapi_replay)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    run(cohort_path=args.cohort, replay_paths=args.replay, out_path=args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
