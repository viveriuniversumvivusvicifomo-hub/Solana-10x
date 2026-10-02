"""V4 — walk-forward / splits por tiempo de T0 + embargo."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from verification.errors import WalkForwardError


def _as_utc(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise WalkForwardError(f"{field} tipo inválido: {type(value)!r}")
    if dt.tzinfo is None:
        raise WalkForwardError(f"{field} debe ser timezone-aware UTC")
    return dt.astimezone(timezone.utc)


def assert_walk_forward_order(
    *,
    train_t0s: Sequence[Any],
    val_t0s: Sequence[Any],
    test_t0s: Sequence[Any] | None = None,
    embargo: timedelta,
) -> None:
    """train_end + embargo <= val_start (+ test después de val)."""
    if not train_t0s or not val_t0s:
        raise WalkForwardError("train y val deben ser no vacíos")

    train = sorted(_as_utc(t, field="train.t0") for t in train_t0s)
    val = sorted(_as_utc(t, field="val.t0") for t in val_t0s)
    train_end = train[-1]
    val_start = val[0]
    if train_end + embargo > val_start:
        raise WalkForwardError(
            f"embargo roto: max(train.t0)+embargo={train_end + embargo} > min(val.t0)={val_start}"
        )

    if test_t0s:
        test = sorted(_as_utc(t, field="test.t0") for t in test_t0s)
        val_end = val[-1]
        test_start = test[0]
        if val_end + embargo > test_start:
            raise WalkForwardError(
                f"embargo val→test roto: max(val.t0)+embargo={val_end + embargo} > min(test.t0)={test_start}"
            )


def assert_mint_single_split(
    assignments: Sequence[Mapping[str, str]],
    *,
    mint_key: str = "mint",
    split_key: str = "split",
) -> None:
    """Un mint no puede aparecer en más de un split."""
    seen: dict[str, str] = {}
    for row in assignments:
        mint = row[mint_key]
        split = row[split_key]
        prev = seen.get(mint)
        if prev is not None and prev != split:
            raise WalkForwardError(f"mint {mint} en splits {prev!r} y {split!r}")
        seen[mint] = split
