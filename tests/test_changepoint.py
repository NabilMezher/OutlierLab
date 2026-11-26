import numpy as np
import pandas as pd
import pytest

from outlierlab.core.detectors.changepoint import CHANGE_DETECTORS, PeltDetector
from outlierlab.core.seeding import set_global_seed


def _step_series() -> pd.Series:
    rng = set_global_seed(7)
    a = rng.normal(0.0, 0.3, size=150)
    b = rng.normal(8.0, 0.3, size=150)
    return pd.Series(np.concatenate([a, b]))


@pytest.mark.parametrize("key", list(CHANGE_DETECTORS))
def test_changepoint_detectors_return_valid_result(key: str):
    series = _step_series()
    detector = CHANGE_DETECTORS[key]()
    res = detector.fit_detect(series)

    assert res.detector_key == key
    assert res.family == "change"
    assert res.status == "done"
    assert res.runtime_s >= 0.0
    assert len(res.alarms) >= 1
    for start, end in res.alarms:
        assert 0 <= start <= end < len(series)


def test_pelt_finds_planted_level_shift():
    series = _step_series()
    res = PeltDetector().fit_detect(series, model="l2", pen=10)
    assert any(abs(start - 150) <= 10 for start, _ in res.alarms)


def test_changepoint_rejects_nan_series():
    series = pd.Series([1.0, np.nan, 2.0, 3.0])
    with pytest.raises(ValueError, match="NaN"):
        PeltDetector().fit_detect(series)