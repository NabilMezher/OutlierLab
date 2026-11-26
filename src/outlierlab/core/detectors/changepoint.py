from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
import ruptures as rpt

from outlierlab.core.detectors.base import AlarmInterval, Detector, RunResult
from outlierlab.core.registry import default_params


def _prepare_signal(series: pd.Series) -> np.ndarray:
    """Convert a pandas Series to a clean 1-D float array."""
    x = series.to_numpy(dtype=float)
    if x.ndim != 1 or len(x) == 0:
        raise ValueError("Series must be a non-empty 1-D array")
    if np.isnan(x).any():
        raise ValueError("Series contains NaN values; clean missing data before running detectors")
    return x


def _bkps_to_alarms(bkps: list[int], length: int) -> list[AlarmInterval]:
    """Convert ruptures breakpoint indices (dropping trailing length) to AlarmIntervals."""
    points = sorted({min(length - 1, max(0, int(b))) for b in bkps if b < length})
    return [(b, b) for b in points]


class _BaseRupturesDetector(Detector):
    family = "change"
    uses_seed = False

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        raise NotImplementedError

    def fit_detect(
        self,
        series: pd.Series,
        seed: int = 42,
        **params: Any,
    ) -> RunResult:
        merged = {**default_params(self.key), **params}
        x = _prepare_signal(series)
        t0 = time.perf_counter()
        bkps = self._predict_bkps(x, merged)
        runtime_s = time.perf_counter() - t0
        return RunResult(
            detector_key=self.key,
            detector_name=self.name,
            family="change",
            alarms=_bkps_to_alarms(bkps, len(x)),
            runtime_s=runtime_s,
            status="done",
        )


class PeltDetector(_BaseRupturesDetector):
    key = "pelt"
    name = "PELT"

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        algo = rpt.Pelt(
            model=str(params["model"]),
            min_size=int(params["min_size"]),
            jump=int(params["jump"]),
        ).fit(x)
        return algo.predict(pen=float(params["pen"]))


class BinsegDetector(_BaseRupturesDetector):
    key = "binseg"
    name = "Binseg"

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        algo = rpt.Binseg(
            model=str(params["model"]),
            min_size=int(params["min_size"]),
            jump=int(params["jump"]),
        ).fit(x)
        return algo.predict(n_bkps=int(params["n_bkps"]))


class BottomUpDetector(_BaseRupturesDetector):
    key = "bottomup"
    name = "Bottom-up"

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        algo = rpt.BottomUp(
            model=str(params["model"]),
            min_size=int(params["min_size"]),
            jump=int(params["jump"]),
        ).fit(x)
        return algo.predict(n_bkps=int(params["n_bkps"]))


class WindowDetector(_BaseRupturesDetector):
    key = "window"
    name = "Window"

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        algo = rpt.Window(
            width=int(params["width"]),
            model=str(params["model"]),
            jump=int(params["jump"]),
        ).fit(x)
        return algo.predict(n_bkps=int(params["n_bkps"]))


class KernelCPDDetector(_BaseRupturesDetector):
    key = "kernel"
    name = "KernelCPD"

    def _predict_bkps(self, x: np.ndarray, params: dict[str, Any]) -> list[int]:
        algo = rpt.KernelCPD(
            kernel=str(params["kernel"]),
            min_size=int(params["min_size"]),
        ).fit(x)
        return algo.predict(pen=float(params["pen"]))


CHANGE_DETECTORS: dict[str, type[Detector]] = {
    "pelt": PeltDetector,
    "binseg": BinsegDetector,
    "bottomup": BottomUpDetector,
    "window": WindowDetector,
    "kernel": KernelCPDDetector,
}