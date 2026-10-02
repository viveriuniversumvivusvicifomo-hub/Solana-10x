"""Live feature recipe MUST equal WF train ``FEATURE_SETS['+q5b']``.

Single source of truth: ``features.post_q5_sets``. Joblib ``feature_names``
must match that tuple (order + membership). ``DROP_FROM_X`` never enters X.

USD definition (live, after SolDatos oracle parity):
  amount_usd = sol_amt * sol_usd_asof_t0  (Pyth preferred; document source)
Train Dune used AmountInUSD — scale drift is a data issue, not a column-recipe issue.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from features.post_q5_sets import DROP_FROM_X, FEATURE_SETS, JOIN_ONLY
from paper_live.config import MODEL_Q5B_PATH

LIVE_SCORE_SET = "+q5b"
TRAIN_RECIPE_COLS: tuple[str, ...] = FEATURE_SETS[LIVE_SCORE_SET]


@dataclass(frozen=True)
class RecipeParityReport:
    ok: bool
    set_name: str
    n_recipe: int
    n_joblib: int | None
    missing_in_joblib: tuple[str, ...]
    extra_in_joblib: tuple[str, ...]
    order_match: bool | None
    drop_leaked: tuple[str, ...]
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "set_name": self.set_name,
            "n_recipe": self.n_recipe,
            "n_joblib": self.n_joblib,
            "missing_in_joblib": list(self.missing_in_joblib),
            "extra_in_joblib": list(self.extra_in_joblib),
            "order_match": self.order_match,
            "drop_leaked": list(self.drop_leaked),
            "detail": self.detail,
            "recipe_cols": list(TRAIN_RECIPE_COLS),
        }


def strip_non_x(feats: dict[str, Any]) -> dict[str, Any]:
    """Remove join-only + DROP_FROM_X keys from a scoring copy."""
    return {
        k: v
        for k, v in feats.items()
        if k not in JOIN_ONLY and k not in DROP_FROM_X
    }


def vector_for_score(
    feats: dict[str, Any],
    *,
    feature_names: Sequence[str] | None = None,
) -> list[float | None]:
    """Ordered X row for HistGB; None → nan at predict time."""
    names = list(feature_names) if feature_names is not None else list(TRAIN_RECIPE_COLS)
    leaked = [c for c in names if c in DROP_FROM_X or c in JOIN_ONLY]
    if leaked:
        raise AssertionError(f"non-X columns in score recipe: {leaked}")
    cleaned = strip_non_x(feats)
    return [cleaned.get(c) for c in names]


def assert_recipe_matches_joblib(
    *,
    model_path: Path | None = None,
    feature_names: Sequence[str] | None = None,
) -> RecipeParityReport:
    """Gate: joblib feature_names == FEATURE_SETS['+q5b'] (order)."""
    recipe = list(TRAIN_RECIPE_COLS)
    names: list[str] | None
    if feature_names is not None:
        names = list(feature_names)
        src = "provided"
    else:
        path = model_path or MODEL_Q5B_PATH
        if not path.is_file():
            return RecipeParityReport(
                ok=False,
                set_name=LIVE_SCORE_SET,
                n_recipe=len(recipe),
                n_joblib=None,
                missing_in_joblib=tuple(recipe),
                extra_in_joblib=(),
                order_match=None,
                drop_leaked=(),
                detail=f"missing joblib: {path}",
            )
        import joblib

        blob = joblib.load(path)
        names = list(blob["feature_names"])
        src = str(path)

    missing = tuple(c for c in recipe if c not in names)
    extra = tuple(c for c in names if c not in recipe)
    order = names == recipe
    drop = tuple(c for c in names if c in DROP_FROM_X or c in JOIN_ONLY)
    ok = not missing and not extra and order and not drop
    return RecipeParityReport(
        ok=ok,
        set_name=LIVE_SCORE_SET,
        n_recipe=len(recipe),
        n_joblib=len(names),
        missing_in_joblib=missing,
        extra_in_joblib=extra,
        order_match=order,
        drop_leaked=drop,
        detail=("PASS recipe==joblib " if ok else "FAIL ") + src,
    )


def assert_feats_cover_recipe(feats: dict[str, Any], *, allow_null_ok: Iterable[str] = ()) -> list[str]:
    """Return missing required cols (excluding known null-ok)."""
    from paper_live.features_t0 import NULL_OK_Q5B, NULL_OK_WHEN_NO_BUYS, required_buy60_present

    allow = set(allow_null_ok) | set(NULL_OK_Q5B)
    no_buys = float(feats.get("buy_count_total") or 0) == 0 and feats.get("buy_count_total") is not None
    if no_buys:
        allow |= set(NULL_OK_WHEN_NO_BUYS)
    missing: list[str] = []
    if not required_buy60_present(feats):
        missing.append("buy_vol_usd_60s")
    for c in TRAIN_RECIPE_COLS:
        if c in allow:
            continue
        if feats.get(c) is None:
            missing.append(c)
    return missing
