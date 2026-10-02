"""Esqueleto walk-forward por tiempo de T0 + embargo ≥ horizonte de label (V4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Sequence

from labeling.horizons import LABEL_HORIZONS, PRIMARY_HORIZON
from verification.walkforward_v4 import assert_mint_single_split, assert_walk_forward_order

SplitName = Literal["train", "val", "test"]

# Fee bonding curve documentado (fills sin look-ahead @ P0 o peor)
CURVE_FEE_BPS: int = 125  # 1.25%


@dataclass(frozen=True, slots=True)
class CaptureRef:
    capture_id: str
    mint: str
    t0: datetime


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    fold_id: str
    train: tuple[CaptureRef, ...]
    val: tuple[CaptureRef, ...]
    test: tuple[CaptureRef, ...]
    embargo: timedelta
    label_horizon: str


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("t0 debe ser timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def default_embargo(horizon: str = PRIMARY_HORIZON) -> timedelta:
    """Embargo ≥ H_label para no filtrar labels que solapan val."""
    if horizon not in LABEL_HORIZONS:
        raise KeyError(horizon)
    return LABEL_HORIZONS[horizon]


def purge_train_overlapping_val(
    train: Sequence[CaptureRef],
    *,
    val_start: datetime,
    label_horizon: timedelta,
) -> tuple[CaptureRef, ...]:
    """Purge V4: saca del train capturas cuyo (t0, t0+H] solapa val_start."""
    vs = _as_utc(val_start)
    kept = [c for c in train if _as_utc(c.t0) + label_horizon <= vs]
    return tuple(kept)


def build_assignments(
    fold: WalkForwardFold,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for split, refs in (
        ("train", fold.train),
        ("val", fold.val),
        ("test", fold.test),
    ):
        for c in refs:
            rows.append({"mint": c.mint, "split": split, "capture_id": c.capture_id})
    return rows


def validate_fold(fold: WalkForwardFold) -> None:
    """Aplica gates V4 al fold (orden + embargo + mint único)."""
    assert_walk_forward_order(
        train_t0s=[c.t0 for c in fold.train],
        val_t0s=[c.t0 for c in fold.val],
        test_t0s=[c.t0 for c in fold.test] or None,
        embargo=fold.embargo,
    )
    assert_mint_single_split(build_assignments(fold))


def build_single_fold(
    captures: Sequence[CaptureRef],
    *,
    train_end: datetime,
    val_end: datetime,
    test_end: datetime | None = None,
    label_horizon: str = PRIMARY_HORIZON,
    fold_id: str = "fold0",
) -> WalkForwardFold:
    """Parte capturas por T0 en train / val / test con embargo = H_label.

    - train: t0 <= train_end
    - val:   train_end + embargo < t0 <= val_end
    - test:  val_end + embargo < t0 <= test_end (opcional)
    """
    embargo = default_embargo(label_horizon)
    h = LABEL_HORIZONS[label_horizon]
    te = _as_utc(train_end)
    ve = _as_utc(val_end)

    sorted_caps = sorted((_as_utc(c.t0), c) for c in captures)
    raw_train = [c for t, c in sorted_caps if t <= te]
    val = [c for t, c in sorted_caps if te + embargo < t <= ve]
    if not val:
        raise ValueError("val vacío tras aplicar embargo; ajusta train_end/val_end")

    val_start = min(_as_utc(c.t0) for c in val)
    train = list(purge_train_overlapping_val(raw_train, val_start=val_start, label_horizon=h))
    if not train:
        raise ValueError("train vacío tras purge")

    test: list[CaptureRef] = []
    if test_end is not None:
        xe = _as_utc(test_end)
        val_last = max(_as_utc(c.t0) for c in val)
        test = [c for t, c in sorted_caps if val_last + embargo < t <= xe]

    fold = WalkForwardFold(
        fold_id=fold_id,
        train=tuple(train),
        val=tuple(val),
        test=tuple(test),
        embargo=embargo,
        label_horizon=label_horizon,
    )
    validate_fold(fold)
    return fold


def fill_price_after_fee(p0: float, *, fee_bps: int = CURVE_FEE_BPS) -> float:
    """Fill conservador: compra en curva paga fee → peor que P0 (sin look-ahead)."""
    if p0 <= 0:
        raise ValueError("p0 must be > 0")
    return p0 * (1.0 + fee_bps / 10_000.0)
