from __future__ import annotations

import pytest

from models import ModelStub
from verification.errors import LeakageError


def test_fit_rejects_label_column():
    m = ModelStub()
    with pytest.raises(LeakageError):
        m.fit([{"mc_usd_t0": 1.0, "hit_10x_24h": 1}], [1])


def test_fit_and_predict_ok():
    m = ModelStub()
    X = [{"mc_usd_t0": 9000.0, "age_s": 120.0}]
    m.fit(X, [0])
    assert m.fitted
    assert m.predict_proba(X) == [0.5]
