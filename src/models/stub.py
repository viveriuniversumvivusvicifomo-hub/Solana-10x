"""Offline Cycle-0 model stub — fit/predict_proba contract, no real training.

**Not used on the live paper path** (``paper_live`` score/entry/loop).
Live scoring loads joblib HistGB via ``paper_live.score``. This module exists
for early verification / offline WF scaffolding and ``tests/models/test_stub.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

from features.whitelist import P0_FEATURE_NAMES
from verification.leakage_v3 import (
    assert_feature_label_column_disjoint,
    assert_train_columns_whitelisted,
    fail_if_label_like_in_features,
)


@dataclass
class ModelStub:
    """Interfaz congelada: feature_names ⊂ whitelist P0; no label-like."""

    feature_names: tuple[str, ...] = field(default_factory=tuple)
    fitted: bool = False

    def fit(self, X: Sequence[Mapping[str, float]], y: Sequence[int]) -> ModelStub:
        if not X:
            raise ValueError("X vacío")
        cols = tuple(sorted(X[0].keys()))
        fail_if_label_like_in_features(cols)
        assert_feature_label_column_disjoint(cols)
        assert_train_columns_whitelisted(cols, P0_FEATURE_NAMES)
        if len(y) != len(X):
            raise ValueError("len(X) != len(y)")
        # No entrena de verdad en C0 — solo congela columnas tras gates V3
        self.feature_names = cols
        self.fitted = True
        return self

    def predict_proba(self, X: Sequence[Mapping[str, float]]) -> list[float]:
        if not self.fitted:
            raise RuntimeError("ModelStub no fitted; V1–V4 deben pasar antes de entrenar")
        for row in X:
            missing = [c for c in self.feature_names if c not in row]
            if missing:
                raise KeyError(f"faltan features frozen: {missing}")
            extra = [c for c in row if c not in self.feature_names]
            if extra:
                raise KeyError(f"features no frozen en predict: {extra}")
        # Stub: probabilidad constante 0.5 (sin lógica fingida de edge)
        return [0.5] * len(X)
