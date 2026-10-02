"""Materializar labels desde sample Bitquery — solo si hay precios > T0.

La 1ª pasada SolDatos (`bitquery_pump_mc_8k_20k_sample.json`) es candidatas MC,
sin CaptureEvent (t0/p0) ni OHLCV post-T0. Este módulo:
- audita el snapshot
- escribe informe (n, n_labeled, base_rate o bloqueo)
- cuando llegue ``price_series`` por mint, materializa hit_10x_* vía hit_10x.py
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from labeling.hit_10x import materialize_label_record
from labeling.horizons import PRIMARY_HORIZON, SECONDARY_HORIZONS

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE = ROOT / "data" / "samples" / "bitquery_pump_mc_8k_20k_sample.json"
DEFAULT_REPORT = ROOT / "data" / "samples" / "labels_hit10x_report.json"


@dataclass(frozen=True)
class LabelBatchReport:
    n_candidates: int
    n_labeled: int
    n_skipped: int
    primary_horizon: str
    secondary_horizons: tuple[str, ...]
    base_rate_primary: float | None
    base_rates_secondary: dict[str, float | None]
    blocker: str | None
    sample_path: str
    label_rows_path: str | None
    notes: str


def audit_candidate_sample(sample: Mapping[str, Any]) -> tuple[int, list[str]]:
    """Devuelve (n, missing_fields_for_labels)."""
    rows = list(sample.get("rows") or [])
    required_for_label = ("t0", "p0", "prices_after_t0")
    # snapshot actual solo tiene mint/mc/price_mean
    present = set(rows[0].keys()) if rows else set()
    missing = [f for f in required_for_label if f not in present]
    return len(rows), missing


def materialize_from_enriched(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, float | None]]:
    """Cada row: capture_id, mint, t0, p0, prices=[(ts, px), ...]."""
    out: list[dict[str, Any]] = []
    hits: dict[str, list[bool]] = {PRIMARY_HORIZON: []}
    for h in SECONDARY_HORIZONS:
        hits[h] = []

    for row in rows:
        prices_raw = row["prices_after_t0"]
        prices: list[tuple[datetime, float]] = []
        for ts, px in prices_raw:
            if isinstance(ts, datetime):
                prices.append((ts, float(px)))
            else:
                prices.append(
                    (datetime.fromisoformat(str(ts).replace("Z", "+00:00")), float(px))
                )
        t0 = row["t0"]
        if isinstance(t0, str):
            t0 = datetime.fromisoformat(t0.replace("Z", "+00:00"))
        rec = materialize_label_record(
            capture_id=str(row.get("capture_id") or row["mint"]),
            mint=str(row["mint"]),
            t0=t0,
            p0=float(row["p0"]),
            prices=prices,
            price_source=str(row.get("price_source", "bitquery")),
        )
        flat = rec.flat_columns()
        out.append(flat)
        for h, vals in hits.items():
            v = flat.get(f"hit_10x_{h}")
            if isinstance(v, bool):
                vals.append(v)

    rates = {
        h: (sum(vals) / len(vals) if vals else None) for h, vals in hits.items()
    }
    return out, rates


def write_report_from_sample(
    sample_path: Path = DEFAULT_SAMPLE,
    report_path: Path = DEFAULT_REPORT,
) -> LabelBatchReport:
    sample = json.loads(sample_path.read_text())
    n, missing = audit_candidate_sample(sample)
    blocker = None
    rates_sec: dict[str, float | None] = {h: None for h in SECONDARY_HORIZONS}
    base = None
    n_labeled = 0
    labels_path = None
    notes = ""

    if missing:
        blocker = (
            "snapshot sin CaptureEvent ni series post-T0; "
            f"faltan campos {missing}. "
            "Necesario: t0/p0 (captura v0.3) + precios ts>t0 (Bitquery OHLCV, N mínimo)."
        )
        notes = (
            "No se inventan labels ni base_rate. "
            "Candidatas MC OK para SolDatos; labeling espera enriched rows."
        )
    else:
        # Enriched sample: rows ya traen t0/p0/prices_after_t0
        flats, rates = materialize_from_enriched(sample["rows"])
        n_labeled = len(flats)
        base = rates.get(PRIMARY_HORIZON)
        rates_sec = {h: rates.get(h) for h in SECONDARY_HORIZONS}
        labels_path_p = report_path.with_name("labels_hit10x_rows.json")
        labels_path_p.write_text(json.dumps({"n": n_labeled, "rows": flats}, indent=2))
        labels_path = str(labels_path_p)

    report = LabelBatchReport(
        n_candidates=n,
        n_labeled=n_labeled,
        n_skipped=n - n_labeled,
        primary_horizon=PRIMARY_HORIZON,
        secondary_horizons=SECONDARY_HORIZONS,
        base_rate_primary=base,
        base_rates_secondary=rates_sec,
        blocker=blocker,
        sample_path=str(sample_path),
        label_rows_path=labels_path,
        notes=notes,
    )
    payload = asdict(report)
    payload["generated_at"] = datetime.now(timezone.utc).isoformat()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2) + "\n")
    return report


def main() -> None:
    r = write_report_from_sample()
    print(json.dumps(asdict(r), indent=2))


if __name__ == "__main__":
    main()
