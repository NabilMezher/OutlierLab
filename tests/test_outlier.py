import numpy as np
import pandas as pd
import pytest

from outlierlab.core.detectors.outlier import (
    ANOMALY_DETECTORS,
    IForestDetector,
    build_windows,
)
from outlierlab.core.seeding import set_global_seed


def _spike_series() -> pd.Series:
    rng = set_global_seed(7)
    x = rng.normal(0.0, 0.3, size=200)
    x[98:103] += 8.0 
    return pd.Series(x)


@pytest.mark.parametrize("key", list(ANOMALY_DETECTORS))
def test_anomaly_detectors_return_valid_result_and_find_spike(key: str):
    series = _spike_series()
    detector = ANOMALY_DETECTORS[key]()
    res = detector.fit_detect(series, seed=42)

    assert res.detector_key == key
    assert res.family == "anomaly"
    assert res.status == "done"
    assert res.runtime_s >= 0.0
    assert res.scores is not None and len(res.scores) == len(series)
    assert res.threshold is not None
    assert len(res.alarms) >= 1
    for start, end in res.alarms:
        assert 0 <= start <= end < len(series)
    assert any(start - 15 <= 100 <= end + 15 for start, end in res.alarms)


def test_iforest_seed_reproducibility():
    series = _spike_series()
    r1 = IForestDetector().fit_detect(series, seed=42)
    r2 = IForestDetector().fit_detect(series, seed=42)
    r3 = IForestDetector().fit_detect(series, seed=99)

    assert r1.alarms == r2.alarms
    assert np.allclose(r1.scores, r2.scores)
    assert not np.allclose(r1.scores, r3.scores)


def test_build_windows_validation():
    with pytest.raises(ValueError, match="window"):
        build_windows(pd.Series([1.0, 2.0, 3.0]), window=0)
    with pytest.raises(ValueError, match="NaN"):
        build_windows(pd.Series([1.0, np.nan, 3.0]), window=3)