import pytest

from outlierlab.core.detectors import Detector, DetectorSpec, RunResult
from outlierlab.core.registry import (
    DETECTOR_REGISTRY,
    default_params,
    get_detector_meta,
    list_detectors,
    make_default_spec,
)


def test_detector_abc_requires_fit_detect():
    with pytest.raises(TypeError):
        Detector()  # type: ignore[abstract]


def test_detector_spec_rejects_empty_fields():
    with pytest.raises(ValueError):
        DetectorSpec(key="", name="PELT")
    with pytest.raises(ValueError):
        DetectorSpec(key="pelt", name=" ")


def test_run_result_validates_alarms_and_runtime():
    res = RunResult(
        detector_key="pelt",
        detector_name="PELT",
        family="changepoint",
        alarms=[(10, 10), (20, 25)],
        runtime_s=0.12,
    )
    assert res.status == "done"

    with pytest.raises(ValueError):
        RunResult("pelt", "PELT", "changepoint", alarms=[(-1, 2)])
    with pytest.raises(ValueError):
        RunResult("pelt", "PELT", "changepoint", alarms=[(10, 5)])
    with pytest.raises(ValueError):
        RunResult("pelt", "PELT", "changepoint", runtime_s=-0.1)


def test_registry_contains_five_changepoint_and_five_anomaly():
    assert len(DETECTOR_REGISTRY) == 10
    assert len(list_detectors("changepoint")) == 5
    assert len(list_detectors("anomaly")) == 5
    assert get_detector_meta("iforest").uses_seed is True


@pytest.mark.parametrize("key", list(DETECTOR_REGISTRY))
def test_registry_defaults_are_within_bounds(key: str):
    meta = get_detector_meta(key)
    params = default_params(key)
    spec = make_default_spec(key)
    assert spec.params == params

    for p in meta.params:
        val = params[p.key]
        if p.kind == "choice":
            assert val in p.choices
        else:
            assert p.min_val is not None and p.max_val is not None
            assert p.min_val <= val <= p.max_val