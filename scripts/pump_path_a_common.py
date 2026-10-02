#!/usr/bin/env python3
"""Shared Path A Pump trade-cache helpers (SolDatos lane).

Canonical caches (stamp YYYYMMDD):
  pilot500  → data/samples/pump_pilot500_trades_{stamp}/
  mcband    → data/samples/pump_mcband_trades_extra_{stamp}/
  livelike  → data/samples/pump_livelike_trades_{stamp}/

Quarantined ORPHAN (D-07, NO-GO incomplete) — NOT in default cache order:
  scale / scale_deep → archive/quarantine/mcband_scale_{stamp}/
  Opt-in only: ordered_cache_dirs(..., reuse_orphan_scale=True)
               or env REUSE_ORPHAN_SCALE=1 / CLI --reuse-orphan-scale

Invariants (forever):
  - Path A USD live = sol_amt × pyth_asof (APPLY_DUNE_HELIUS_USD_SCALE OFF)
  - 0 Dune API in rebuild scripts
  - Never overwrite q5b_last / q5b_calibration.json
  - Never kill/restart paper_live PID
  - Scale 6.6× OFF forever (not the mcband_scale *recipe* name — that is n-scale sample)

ORPHAN: build_pump_mcband_scale.py never produced features/usable matrix;
  artifacts quarantined under archive/quarantine/mcband_scale_* (NO-GO).
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

# --- invariants ----------------------------------------------------------------

PATH_A_USD_FORMULA = "sol_amt * pyth_asof"  # live Path A
PUMP_FRONTEND_USD = "valueUsd"  # train offline Pump path (no 6.6×)
USD_SCALE_6_6_OFF_FOREVER = True
APPLY_DUNE_HELIUS_USD_SCALE_DEFAULT = False
DUNE_API_ALLOWED = False

ORPHAN_SCRIPTS = {
    "build_pump_mcband_scale.py": {
        "status": "ORPHAN_INCOMPLETE",
        "reason": (
            "incomplete fetch (~1.3k/2.8k); no features_pump_path_a_mcband_scale_* "
            "nor usable matrix; superseded by livelike; quarantined NO-GO"
        ),
        "keep_cache": False,
        "quarantined": True,
        "quarantine_dir": "archive/quarantine/mcband_scale_20261002",
        "do_not_train_on": True,
    },
}

QUARANTINE_MCBAND_SCALE_DIRNAME = "mcband_scale_20261002"  # D-07 stamp folder
REUSE_ORPHAN_SCALE_ENV = "REUSE_ORPHAN_SCALE"

CANONICAL_TRAIN_ENTRY = "scripts/build_pump_path_a_livelike.py"
CANONICAL_CLI = "scripts/build_pump_path_a.py"
LIVE_ENTRY = "python -m paper_live --feed pump --enrich-via pump"  # do not restart here


def path_a_invariants() -> dict[str, Any]:
    return {
        "usd_live": PATH_A_USD_FORMULA,
        "usd_pump_frontend": PUMP_FRONTEND_USD,
        "usd_scale_6_6_off_forever": USD_SCALE_6_6_OFF_FOREVER,
        "apply_dune_helius_usd_scale_default": APPLY_DUNE_HELIUS_USD_SCALE_DEFAULT,
        "dune_api_allowed": DUNE_API_ALLOWED,
        "canonical_train_entry": CANONICAL_TRAIN_ENTRY,
        "canonical_cli": CANONICAL_CLI,
        "live_entry": LIVE_ENTRY,
        "orphan_scripts": ORPHAN_SCRIPTS,
    }


# --- cache catalog -------------------------------------------------------------

# Default prod order — scale ORPHAN paths excluded (D-07 quarantine).
CACHE_KIND_ORDER = (
    "livelike",
    "mcband_extra",
    "pilot500",
)

# Opt-in only when reuse_orphan_scale / REUSE_ORPHAN_SCALE
CACHE_KIND_ORDER_WITH_ORPHAN_SCALE = (
    "livelike",
    "scale_deep",
    "scale",
    "mcband_extra",
    "pilot500",
)


def quarantine_mcband_scale_dir(*, root: Path | None = None, stamp: str = "20261002") -> Path:
    """D-07 quarantine folder for incomplete mcband_scale artifacts."""
    r = root or ROOT
    # Prefer stamp-specific folder; fall back to canonical 20261002 dir name.
    preferred = r / "archive" / "quarantine" / f"mcband_scale_{stamp}"
    if preferred.is_dir():
        return preferred
    return r / "archive" / "quarantine" / QUARANTINE_MCBAND_SCALE_DIRNAME


def _env_reuse_orphan_scale() -> bool:
    import os

    v = (os.environ.get(REUSE_ORPHAN_SCALE_ENV) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def cache_dirs_for_stamp(
    stamp: str,
    *,
    root: Path | None = None,
    include_livelike: bool = True,
    reuse_orphan_scale: bool | None = None,
) -> dict[str, Path]:
    """Named trade-cache directories for a stamp (may or may not exist on disk).

    Scale / scale_deep resolve under quarantine when present; they are only
    included in ordered_cache_dirs when reuse_orphan_scale is enabled.
    """
    r = root or ROOT
    base = r / "data" / "samples"
    q = quarantine_mcband_scale_dir(root=r, stamp=stamp)
    # Prefer quarantined locations; fall back to legacy samples paths (pre-move).
    scale = q / f"pump_mcband_scale_trades_{stamp}"
    scale_deep = q / f"pump_mcband_scale_trades_deep_{stamp}"
    if not scale.is_dir():
        scale = base / f"pump_mcband_scale_trades_{stamp}"
    if not scale_deep.is_dir():
        scale_deep = base / f"pump_mcband_scale_trades_deep_{stamp}"
    out: dict[str, Path] = {
        "pilot500": base / f"pump_pilot500_trades_{stamp}",
        "mcband_extra": base / f"pump_mcband_trades_extra_{stamp}",
        "scale": scale,
        "scale_deep": scale_deep,
    }
    if include_livelike:
        out["livelike"] = base / f"pump_livelike_trades_{stamp}"
    return out


def ordered_cache_dirs(
    stamp: str,
    *,
    root: Path | None = None,
    include_livelike: bool = True,
    reuse_orphan_scale: bool | None = None,
) -> list[Path]:
    """Priority order for mint lookup (newest / most specific first).

    Default excludes scale quarantine paths so prod livelike cannot silently
    depend on incomplete orphan cache. Pass reuse_orphan_scale=True or set
    REUSE_ORPHAN_SCALE=1 / CLI --reuse-orphan-scale to include them.
    """
    if reuse_orphan_scale is None:
        reuse_orphan_scale = _env_reuse_orphan_scale()
    named = cache_dirs_for_stamp(
        stamp,
        root=root,
        include_livelike=include_livelike,
        reuse_orphan_scale=reuse_orphan_scale,
    )
    order = CACHE_KIND_ORDER_WITH_ORPHAN_SCALE if reuse_orphan_scale else CACHE_KIND_ORDER
    return [named[k] for k in order if k in named]


def resolve_scale_sample_csv(stamp: str, *, root: Path | None = None) -> Path | None:
    """Locate pump_mcband_scale_sample_*.csv (quarantine first, then samples/)."""
    r = root or ROOT
    q = quarantine_mcband_scale_dir(root=r, stamp=stamp)
    candidates = [
        q / f"pump_mcband_scale_sample_{stamp}.csv",
        r / "data" / "samples" / f"pump_mcband_scale_sample_{stamp}.csv",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def cache_inventory(stamp: str, *, root: Path | None = None) -> dict[str, Any]:
    """Count JSON trade files per cache; mark scale orphan / quarantine status."""
    named = cache_dirs_for_stamp(stamp, root=root, include_livelike=True)
    # drop internal annotation key if present
    named = {k: v for k, v in named.items() if not str(k).startswith("_")}
    inv: dict[str, Any] = {"stamp": stamp, "caches": {}}
    r = root or ROOT
    for kind, path in named.items():
        n = len(list(path.glob("*.json"))) if path.is_dir() else 0
        try:
            rel = str(path.relative_to(r))
        except ValueError:
            rel = str(path)
        inv["caches"][kind] = {
            "path": rel,
            "exists": path.is_dir(),
            "n_trade_files": n,
            "orphan": kind in ("scale", "scale_deep"),
            "quarantined": kind in ("scale", "scale_deep") and "quarantine" in rel,
        }
    samples = r / "data" / "samples"
    q = quarantine_mcband_scale_dir(root=r, stamp=stamp)
    sample_path = resolve_scale_sample_csv(stamp, root=r)
    inv["matrices"] = {
        "pilot500": (samples / f"features_pump_path_a_pilot500_{stamp}.csv").is_file(),
        "mcband": (samples / f"features_pump_path_a_mcband_{stamp}.csv").is_file(),
        "livelike": (samples / f"features_pump_path_a_livelike_{stamp}.csv").is_file(),
        "mcband_scale": (samples / f"features_pump_path_a_mcband_scale_{stamp}.csv").is_file(),
    }
    inv["usable"] = {
        "livelike": (samples / f"pump_livelike_usable_{stamp}.csv").is_file(),
        "mcband_scale": (
            (samples / f"pump_mcband_scale_usable_{stamp}.csv").is_file()
            or (q / f"pump_mcband_scale_usable_{stamp}.csv").is_file()
        ),
    }
    inv["default_cache_excludes_scale"] = True
    inv["quarantine_mcband_scale"] = {
        "dir": str(q.relative_to(r)) if q.is_absolute() else str(q),
        "exists": q.is_dir(),
        "readme": (q / "NO-GO_INCOMPLETE.md").is_file(),
    }
    inv["orphan_mcband_scale"] = {
        **ORPHAN_SCRIPTS["build_pump_mcband_scale.py"],
        "has_sample": sample_path is not None,
        "sample_path": (
            str(sample_path.relative_to(r)) if sample_path is not None else None
        ),
        "has_matrix": inv["matrices"]["mcband_scale"],
        "has_usable": inv["usable"]["mcband_scale"],
        "n_trades": inv["caches"]["scale"]["n_trade_files"],
        "n_deep": inv["caches"]["scale_deep"]["n_trade_files"],
    }
    return inv


TRADE_CACHE_REQUIRED_TOP_KEYS = ("mint", "trades")
TRADE_CACHE_OPTIONAL_TOP_KEYS = ("n_raw", "fetch_meta", "fetched_at", "t0_ts")
TRADE_ROW_KEY_CANDIDATES = ("blockTimeMs", "timestamp", "side", "valueUsd", "priceUsd")


def validate_trade_cache_doc(doc: dict[str, Any]) -> list[str]:
    """Return list of schema problems (empty = OK)."""
    errs: list[str] = []
    for k in TRADE_CACHE_REQUIRED_TOP_KEYS:
        if k not in doc:
            errs.append(f"missing_top_key:{k}")
    trades = doc.get("trades")
    if trades is None:
        errs.append("trades_null")
    elif not isinstance(trades, list):
        errs.append("trades_not_list")
    elif trades:
        tr = trades[0]
        if not isinstance(tr, dict):
            errs.append("trade0_not_dict")
        else:
            if not any(k in tr for k in ("blockTimeMs", "timestamp", "blockTime")):
                errs.append("trade0_missing_time")
            if not any(k in tr for k in ("valueUsd", "amount_usd", "priceUsd", "valueNative")):
                errs.append("trade0_missing_usd_or_px")
    return errs


# --- IO helpers ----------------------------------------------------------------

def utcnow() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def save_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(path)


def resolve_trades_path(mint: str, cache_dirs: list[Path]) -> Path | None:
    for d in cache_dirs:
        p = d / f"{mint}.json"
        if p.is_file():
            return p
    return None


def load_raw(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.is_file():
        return []
    try:
        return list(json.loads(path.read_text()).get("trades") or [])
    except Exception:  # noqa: BLE001
        return []


# Aliases matching prior script private names (compat)
_resolve_trades_path = resolve_trades_path
_load_raw = load_raw
_load_json = load_json
_save_json = save_json
_utcnow = utcnow


def fetch_missing_band_aware(
    mints: list[str],
    *,
    t0_expand_by_mint: dict[str, datetime | None],
    trades_dir: Path,
    checkpoint: Path,
    cache_dirs: list[Path],
    max_pages: int = 10,
    max_http: int = 10000,
    min_interval_s: float = 1.0,
    max_429_retries_total: int = 60,
    max_fail_frac: float = 0.25,
    max_consec_hard_fail: int = 15,
    root: Path | None = None,
    checkpoint_kind: str = "pump_path_a_fetch_checkpoint",
) -> dict[str, Any]:
    """Fetch trades for mints lacking any cache; paginate until band or expand T0.

    Shared by livelike (and legacy scale). Does not call Dune.
    """
    from build_pump_mcband_pilot import deep_fetch_trades  # local recipe helper
    from ingestion.pump_frontend import PumpFrontendClient

    root = root or ROOT
    trades_dir.mkdir(parents=True, exist_ok=True)
    ck = load_json(checkpoint)
    done: dict[str, Any] = dict(ck.get("done") or {})
    client = PumpFrontendClient(min_interval_s=min_interval_s, max_retries_429=5)
    consec_hard = 0
    stopped = False
    stop_reason = None
    t0_wall = time.time()
    skipped_cached = 0
    try:
        for i, mint in enumerate(mints):
            existing = resolve_trades_path(mint, cache_dirs + [trades_dir])
            if existing is not None and (done.get(mint) or {}).get("ok") is not False:
                if mint not in done:
                    try:
                        rel = str(existing.relative_to(root))
                    except ValueError:
                        rel = str(existing)
                    done[mint] = {
                        "ok": True,
                        "reused": True,
                        "path": rel,
                        "n_raw": len(load_raw(existing)),
                    }
                skipped_cached += 1
                consec_hard = 0
                continue
            if done.get(mint, {}).get("ok"):
                skipped_cached += 1
                continue
            if client.log.n_calls >= max_http:
                stopped, stop_reason = True, f"http_budget>={max_http}"
                break
            try:
                target = t0_expand_by_mint.get(mint)
                raw, fmeta = deep_fetch_trades(
                    mint,
                    client=client,
                    target_ts=target,
                    max_pages=max_pages,
                    pre_band_s=120.0,
                )
                out_path = trades_dir / f"{mint}.json"
                out_path.write_text(
                    json.dumps(
                        {
                            "mint": mint,
                            "n_raw": len(raw),
                            "fetch_meta": fmeta,
                            "fetched_at": utcnow(),
                            "trades": raw,
                        }
                    )
                )
                try:
                    rel = str(out_path.relative_to(root))
                except ValueError:
                    rel = str(out_path)
                done[mint] = {
                    "ok": True,
                    "reused": False,
                    "found_band": bool(fmeta.get("found_band")),
                    "n_raw": len(raw),
                    "n_pages": fmeta.get("n_pages"),
                    "path": rel,
                    "http_calls_so_far": client.log.n_calls,
                    "n_retries_429_so_far": client.log.n_retries_429,
                }
                consec_hard = 0
            except Exception as e:  # noqa: BLE001
                err_s = f"{type(e).__name__}: {e}"[:300]
                done[mint] = {"ok": False, "error": err_s}
                consec_hard += 1

            n_attempted = sum(1 for v in done.values() if not v.get("reused"))
            n_fail = sum(1 for v in done.values() if not v.get("ok"))
            fail_frac = n_fail / max(1, len(done))
            stats = {
                "n_done": len(done),
                "n_ok": sum(1 for v in done.values() if v.get("ok")),
                "n_fail": n_fail,
                "n_reused": sum(1 for v in done.values() if v.get("reused")),
                "skipped_cached_loop": skipped_cached,
                "fail_frac": fail_frac,
                "http_calls": client.log.n_calls,
                "n_retries_429": client.log.n_retries_429,
                "consec_hard_fail": consec_hard,
                "elapsed_s": round(time.time() - t0_wall, 1),
                "last_i": i,
            }
            ck_doc = {
                "kind": checkpoint_kind,
                "updated_at": utcnow(),
                "done": done,
                "stats": stats,
                "client_log": client.log.to_dict(),
            }
            save_json(checkpoint, ck_doc)

            if client.log.n_retries_429 >= max_429_retries_total:
                stopped, stop_reason = True, f"429_retries>={max_429_retries_total}"
            elif consec_hard >= max_consec_hard_fail:
                stopped, stop_reason = True, f"consec_hard_fail>={max_consec_hard_fail}"
            elif n_attempted >= 40 and fail_frac >= max_fail_frac:
                stopped, stop_reason = True, f"fail_frac={fail_frac:.2f}>={max_fail_frac}"
            elif client.log.n_calls >= max_http:
                stopped, stop_reason = True, f"http_budget>={max_http}"
            if stopped:
                ck_doc["stopped"] = True
                ck_doc["stop_reason"] = stop_reason
                save_json(checkpoint, ck_doc)
                break
            if (i + 1) % 25 == 0:
                print(json.dumps({"fetch_progress": i + 1, "of": len(mints), **stats}), flush=True)
    finally:
        client.close()

    ck = load_json(checkpoint)
    ck["finished_at"] = utcnow()
    if stopped:
        ck["stopped"] = True
        ck["stop_reason"] = stop_reason
    ck["stats"] = {**(ck.get("stats") or {}), "skipped_cached_loop": skipped_cached}
    save_json(checkpoint, ck)
    return ck


def assert_usd_scale_off() -> None:
    """Raise if APPLY_DUNE_HELIUS_USD_SCALE is enabled (pipeline must stay OFF)."""
    from ingestion.sol_usd_oracle import apply_dune_helius_usd_scale_enabled, maybe_scale_usd

    if apply_dune_helius_usd_scale_enabled():
        raise RuntimeError(
            "APPLY_DUNE_HELIUS_USD_SCALE is ON — Path A requires scale 6.6× OFF forever"
        )
    # identity check
    if maybe_scale_usd(100.0) != 100.0:
        raise RuntimeError("maybe_scale_usd is not identity while scale should be OFF")
