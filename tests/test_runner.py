import time
from typing import Any

import numpy as np
import pandas as pd

from outlierlab.core.detectors.base import Detector, DetectorSpec, RunResult
from outlierlab.core.registry import make_default_spec
from outlierlab.core.runner import ProgressEvent, TaskRunner
from outlierlab.core.seeding import set_global_seed


def _drain_queue(runner: TaskRunner) -> list[ProgressEvent]:
    events: list[ProgressEvent] = []
    while not runner.progress_queue.empty():
        events.append(runner.progress_queue.get_nowait())
    return events


def _sample_series() -> pd.Series:
    rng = set_global_seed(7)
    x = rng.normal(0.0, 0.3, size=120)
    x[60:] += 5.0
    return pd.Series(x)


def test_runner_executes_enabled_detectors_and_skips_disabled():
    specs = [
        make_default_spec("pelt", enabled=True),
        make_default_spec("binseg", enabled=False),
        make_default_spec("iforest", enabled=True),
    ]
    runner = TaskRunner()
    runner.start(specs, _sample_series(), seed=42)
    runner.join(timeout=15)

    assert not runner.is_running()
    assert set(runner.results) == {"pelt", "iforest"}
    assert runner.results["pelt"].status == "done"
    assert runner.results["iforest"].status == "done"

    events = _drain_queue(runner)
    kinds = [e.kind for e in events]
    assert kinds[-1] == "finished"
    assert kinds.count("detector_done") == 2


def test_runner_marks_slow_detector_as_timed_out():
    class SlowDetector(Detector):
        key = "pelt"
        name = "Slow"
        family = "change"

        def fit_detect(self, series: pd.Series, seed: int = 42, **params: Any) -> RunResult:
            time.sleep(0.35)
            return RunResult("pelt", "Slow", "change")

    runner = TaskRunner()
    specs = [DetectorSpec(key="pelt", name="Slow")]
    runner.start(specs, _sample_series(), timeout_s=0.05, detectors_map={"pelt": SlowDetector})
    runner.join(timeout=5)

    res = runner.results["pelt"]
    assert res.status == "timed_out"
    assert "Timed out" in res.error


def test_runner_catches_detector_errors_without_crashing():
    class BrokenDetector(Detector):
        key = "pelt"
        name = "Broken"
        family = "change"

        def fit_detect(self, series: pd.Series, seed: int = 42, **params: Any) -> RunResult:
            raise RuntimeError("boom")

    runner = TaskRunner()
    specs = [DetectorSpec(key="pelt", name="Broken")]
    runner.start(specs, _sample_series(), detectors_map={"pelt": BrokenDetector})
    runner.join(timeout=5)

    res = runner.results["pelt"]
    assert res.status == "failed"
    assert "boom" in res.error


def test_runner_cancel_stops_before_next_detector_and_keeps_finished():
    class MediumDetector(Detector):
        key = "pelt"
        name = "Medium"
        family = "change"

        def fit_detect(self, series: pd.Series, seed: int = 42, **params: Any) -> RunResult:
            time.sleep(0.12)
            return RunResult("pelt", "Medium", "change", alarms=[(60, 60)], runtime_s=0.12)

    runner = TaskRunner()
    specs = [
        DetectorSpec(key="pelt", name="Medium"),
        DetectorSpec(key="iforest", name="Second"),
    ]
    runner.start(
        specs,
        _sample_series(),
        detectors_map={"pelt": MediumDetector, "iforest": MediumDetector},
    )
    time.sleep(0.03)
    runner.cancel()
    runner.join(timeout=5)

    assert "pelt" in runner.results
    assert "iforest" not in runner.results
    events = _drain_queue(runner)
    assert events[-1].kind == "cancelled"