"""Models package.

``ModelStub`` is **offline / Cycle-0 only** (column freeze + placeholder
predict_proba). It is **not** on the live paper path — live uses joblib
HistGB via ``paper_live.score``.

Contrato (ModelStub)
--------------------
- ``fit(X, y)`` / ``predict_proba(X)`` con ``feature_names`` frozen ⊂ whitelist.
- No entrenar hasta que verification V1–V4 pasen.
- ``ModelStub`` congela columnas tras gates V3; predict_proba es placeholder.

Verification hooks
------------------
- ``assert_model_features_subset_whitelist`` / ``assert_train_columns_whitelisted`` (V3)
"""

from models.stub import ModelStub

__all__ = ["ModelStub"]
