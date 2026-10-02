"""Q5 anti look-ahead + merge protocol gates (SolQA).

See cycle0/dune-q5-qa-checklist.md.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from features.post_q5_sets import DROP_FROM_X, FEATURE_SETS, JOIN_ONLY, LEAK_COL_RE, assert_sets_safe
from verification.secrets import scan_text_for_secrets

ROOT = Path(__file__).resolve().parents[2]
EXPAND = ROOT / "data/samples/features_dune_p0_flow_expand_v2.csv"
LABELS = ROOT / "data/samples/labels_dune_expand_v2.csv"
Q5A = ROOT / "data/samples/dune_q5a_features.csv"
Q5B = ROOT / "data/samples/dune_q5b_features.csv"
JOINED = ROOT / "data/samples/features_dune_p0_q5_expand_v2.csv"
REPORT = ROOT / "data/samples/qa_q5_merge_protocol_report.json"

COMPLETE_FRAC = 0.995
T0_TOL = pd.Timedelta(seconds=2)
MIGRATED_SOFT_MAX = 0.01


def _check(name: str, ok: bool, detail: Any = None, *, soft: bool = False) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "soft": soft, "detail": detail}


def assert_no_leak_columns(columns: list[str], *, where: str) -> list[str]:
    bad = [c for c in columns if LEAK_COL_RE.search(c)]
    # labels file is allowed to have hit_/max_mc — only flag if where is features
    if where.startswith("labels"):
        return []
    return bad


def audit_feature_sets() -> dict[str, Any]:
    assert_sets_safe()
    banned = []
    for name, cols in FEATURE_SETS.items():
        if "creator_pubkey" in cols or "create_ts" in cols:
            banned.append(name)
        banned.extend(f"{name}:{c}" for c in cols if c in JOIN_ONLY or c in DROP_FROM_X)
        banned.extend(f"{name}:{c}" for c in cols if LEAK_COL_RE.search(c))
    return {
        "banned_hits": banned,
        "n_sets": len(FEATURE_SETS),
        "drop_from_x": sorted(DROP_FROM_X),
    }


def audit_pack(
    path: Path,
    *,
    pack: str,
    expand_t0: pd.Series | None,
) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not path.is_file():
        return [_check(f"{pack}.exists", False, str(path))]
    df = pd.read_csv(path)
    checks.append(_check(f"{pack}.exists", True, {"n": len(df), "ncols": len(df.columns)}))

    leak = assert_no_leak_columns(list(df.columns), where=f"features:{pack}")
    checks.append(_check(f"{pack}.leak_cols", not leak, leak))

    if "creator_pubkey" in df.columns:
        checks.append(
            _check(
                f"{pack}.creator_pubkey_join_ok",
                True,
                "present in CSV (join-only); must stay out of FEATURE_SETS",
            )
        )

    if "t0_ts" not in df.columns or "mint" not in df.columns:
        checks.append(_check(f"{pack}.keys", False, "need mint+t0_ts"))
        return checks

    t0 = pd.to_datetime(df["t0_ts"], utc=True, errors="coerce")
    if expand_t0 is not None:
        t0_pack = t0
        matched = df["mint"].map(expand_t0)
        both = matched.notna() & t0_pack.notna()
        mismatch = both & ((matched - t0_pack).abs() > T0_TOL)
        checks.append(
            _check(
                f"{pack}.t0_match_expand",
                int(mismatch.sum()) == 0,
                {"n_matched": int(both.sum()), "n_mismatch_gt_2s": int(mismatch.sum())},
            )
        )

    if pack == "q5b":
        if "create_ts" in df.columns:
            c = pd.to_datetime(df["create_ts"], utc=True, errors="coerce")
            bad = c.notna() & t0.notna() & (c > t0)
            checks.append(
                _check("q5b.create_leq_t0", int(bad.sum()) == 0, {"n_create_gt_t0": int(bad.sum()), "n_null_create": int(c.isna().sum())})
            )
        if "age_s" in df.columns:
            age = pd.to_numeric(df["age_s"], errors="coerce")
            bad = age.notna() & (age < 0)
            checks.append(_check("q5b.age_nonneg", int(bad.sum()) == 0, {"n_neg": int(bad.sum())}))

    if pack == "q5a":
        share_cols = [c for c in df.columns if "share" in c or c.endswith("_pct_proxy")]
        out = {}
        ok = True
        for c in share_cols:
            s = pd.to_numeric(df[c], errors="coerce").dropna()
            n_bad = int(((s < -1e-9) | (s > 1.0001)).sum())
            out[c] = n_bad
            if n_bad:
                ok = False
        checks.append(_check("q5a.shares_01", ok, out))
        if "progress_curve_proxy" in df.columns:
            p = pd.to_numeric(df["progress_curve_proxy"], errors="coerce").dropna()
            n_bad = int(((p < -1e-9) | (p > 2.0001)).sum())
            checks.append(
                _check(
                    "q5a.progress_clip",
                    n_bad == 0,
                    {"n_out": n_bad, "median": float(p.median()) if len(p) else None, "mean": float(p.mean()) if len(p) else None},
                )
            )
        if "migrated_pre_t0" in df.columns:
            m = pd.to_numeric(df["migrated_pre_t0"], errors="coerce").dropna()
            rate = float(m.mean()) if len(m) else 0.0
            # Column may remain in CSV for audit; must stay in DROP_FROM_X (not train X).
            in_x = any("migrated_pre_t0" in cols for cols in FEATURE_SETS.values())
            checks.append(
                _check(
                    "q5a.migrated_not_in_X",
                    not in_x,
                    {"in_feature_sets": in_x, "drop_from_x": sorted(DROP_FROM_X)},
                )
            )
            checks.append(
                _check(
                    "q5a.migrated_rate_diag",
                    True,
                    {"rate": rate, "threshold_historical": MIGRATED_SOFT_MAX, "note": "diag only; pumpswap≤T0 ≠ bonding graduation"},
                    soft=True,
                )
            )
    return checks


def audit_labels() -> dict[str, Any]:
    if not LABELS.is_file():
        return {"ok": False, "missing": str(LABELS)}
    cols = list(pd.read_csv(LABELS, nrows=0).columns)
    return {
        "ok": True,
        "columns": cols,
        "has_proxy": "hit_200k" in cols,
        "has_primary": "hit_10x_30d" in cols,
        "note": "labels frame separate; max_mc_after_t0 / label_* must never enter X",
    }


def coverage(expand_n: int, q5_n: int) -> dict[str, Any]:
    frac = float(q5_n / expand_n) if expand_n else 0.0
    return {"expand_n": expand_n, "q5_n": q5_n, "frac": frac, "complete": frac >= COMPLETE_FRAC}


def run_q5_qa(*, write_report: bool = True) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    expand_t0 = None
    expand_n = 0
    if EXPAND.is_file():
        exp = pd.read_csv(EXPAND, usecols=["mint", "t0_ts"])
        expand_n = len(exp)
        expand_t0 = pd.to_datetime(exp.set_index("mint")["t0_ts"], utc=True, errors="coerce")
        checks.append(_check("expand.exists", True, {"n": expand_n}))
        leak = assert_no_leak_columns(list(pd.read_csv(EXPAND, nrows=0).columns), where="features:expand")
        checks.append(_check("expand.leak_cols", not leak, leak))
    else:
        checks.append(_check("expand.exists", False, str(EXPAND)))

    sets_info = audit_feature_sets()
    checks.append(_check("feature_sets.safe", not sets_info["banned_hits"], sets_info))

    checks.extend(audit_pack(Q5A, pack="q5a", expand_t0=expand_t0))
    checks.extend(audit_pack(Q5B, pack="q5b", expand_t0=expand_t0))

    cov = {}
    if expand_n and Q5A.is_file():
        cov["q5a"] = coverage(expand_n, sum(1 for _ in Q5A.open()) - 1)
    if expand_n and Q5B.is_file():
        cov["q5b"] = coverage(expand_n, sum(1 for _ in Q5B.open()) - 1)
    checks.append(
        _check(
            "coverage.complete_gate",
            all(v.get("complete") for v in cov.values()) if cov else False,
            cov,
            soft=True,
        )
    )

    if JOINED.is_file():
        jn = sum(1 for _ in JOINED.open()) - 1
        checks.append(
            _check(
                "joined.cardinality",
                jn == expand_n,
                {"joined_n": jn, "expand_n": expand_n},
            )
        )
        jcols = list(pd.read_csv(JOINED, nrows=0).columns)
        # joined may contain creator_pubkey — OK; train sets must not
        leak = assert_no_leak_columns(jcols, where="features:joined")
        checks.append(_check("joined.leak_cols", not leak, leak))
    else:
        checks.append(_check("joined.exists", False, "pending BOSS merge when Q5 closes", soft=True))

    labels = audit_labels()
    checks.append(_check("labels.separate", bool(labels.get("ok")), labels))

    secret_hits: list[str] = []
    for p in (Q5A, Q5B, EXPAND, LABELS, REPORT):
        if p.is_file() and p.suffix in {".csv", ".json", ".md"}:
            secret_hits.extend(
                scan_text_for_secrets(p.read_text(encoding="utf-8", errors="ignore")[:2_000_000], path=str(p.relative_to(ROOT)))
            )
    checks.append(_check("secrets", not secret_hits, secret_hits[:10]))

    hard = [c for c in checks if not c["ok"] and not c.get("soft")]
    soft = [c for c in checks if not c["ok"] and c.get("soft")]
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ok": len(hard) == 0,
        "ok_hard": len(hard) == 0,
        "n_soft_fail": len(soft),
        "coverage": cov,
        "merge_protocol": {
            "join_key": "mint",
            "t0_tolerance_s": 2,
            "creator_pubkey_in_X": False,
            "labels_in_X": False,
            "complete_frac": COMPLETE_FRAC,
            "checklist": "cycle0/dune-q5-qa-checklist.md",
        },
        "checks": checks,
        "hard_fails": [c["name"] for c in hard],
        "soft_fails": [c["name"] for c in soft],
        "paths": {
            "expand": str(EXPAND.relative_to(ROOT)),
            "q5a": str(Q5A.relative_to(ROOT)),
            "q5b": str(Q5B.relative_to(ROOT)),
            "labels": str(LABELS.relative_to(ROOT)),
            "joined_target": str(JOINED.relative_to(ROOT)),
            "report": str(REPORT.relative_to(ROOT)),
        },
    }
    if write_report:
        REPORT.write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    r = run_q5_qa(write_report=True)
    print(json.dumps({k: r[k] for k in ("ok", "ok_hard", "n_soft_fail", "hard_fails", "soft_fails", "coverage")}, indent=2))
    print("wrote", REPORT)


if __name__ == "__main__":
    main()
