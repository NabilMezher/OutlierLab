from __future__ import annotations

import time
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from pyod.models.ecod import ECOD
from pyod.models.iforest import IForest
from pyod.models.knn import KNN
from pyod.models.lof import LOF
from pyod.models.ocsvm import OCSVM
from sklearn.preprocessing import StandardScaler

from outlierlab.core.detectors.base import AlarmInterval, Detector, RunResult
from outlierlab.core.registry import default_params
from outlierlab.core.seeding import set_global_seed


def build_windows(series: pd.Series, window: int) -> np.ndarray:
    """Turn a 1-D series into standardised sliding-window feature rows."""
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    x = series.to_numpy(dtype=float)
    if x.ndim != 1 or len(x) == 0:
        raise ValueError("Series must be a non-empty 1-D array")
    if np.isnan(x).any():
        raise ValueError("Series contains NaN values; clean missing data before running detectors")

    pad_left = window // 2
    pad_right = window - 1 - pad_left
    padded = np.pad(x, (pad_left, pad_right), mode="edge")
    windows = sliding_window_view(padded, window).astype(float)
    return StandardScaler().fit_transform(windows)


def _labels_to_alarms(labels: np.ndarray, max_gap: int = 1) -> list[AlarmInterval]:
    """Group flagged binary labels (1) into contiguous AlarmIntervals."""
    flagged = np.flatnonzero(np.asarray(labels) == 1)
    if len(flagged) == 0:
        return []
    alarms: list[list[int]] = [[int(flagged[0]), int(flagged[0])]]
    for idx in flagged[1:]:
        i = int(idx)
        if i - alarms[-1][1] <= max_gap:
            alarms[-1][1] = i
        else:
            alarms.append([i, i])
    return [(start, end) for start, end in alarms]


class _BasePyODDetector(Detector):
    family = "anomaly"
    uses_seed = False

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        raise NotImplementedError

    def fit_detect(
        self,
        series: pd.Series,
        seed: int = 42,
        **params: Any,
    ) -> RunResult:
        merged = {**default_params(self.key), **params}
        if self.uses_seed:
            set_global_seed(seed)
        features = build_windows(series, int(merged["window"]))
        model = self._build_model(merged, len(features), seed)

        t0 = time.perf_counter()
        model.fit(features)
        runtime_s = time.perf_counter() - t0

        scores = np.asarray(model.decision_scores_, dtype=float)
        threshold = float(model.threshold_)
        alarms = _labels_to_alarms(model.labels_)
        return RunResult(
            detector_key=self.key,
            detector_name=self.name,
            family="anomaly",
            alarms=alarms,
            scores=scores,
            threshold=threshold,
            runtime_s=runtime_s,
            status="done",
        )


class IForestDetector(_BasePyODDetector):
    key = "iforest"
    name = "IForest"
    uses_seed = True

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        return IForest(
            n_estimators=int(params["n_estimators"]),
            contamination=float(params["contamination"]),
            random_state=seed,
        )


class LOFDetector(_BasePyODDetector):
    key = "lof"
    name = "LOF"

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        n_neighbors = min(int(params["n_neighbors"]), max(1, n_samples - 1))
        return LOF(
            n_neighbors=n_neighbors,
            contamination=float(params["contamination"]),
        )


class KNNDetector(_BasePyODDetector):
    key = "knn"
    name = "KNN"

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        n_neighbors = min(int(params["n_neighbors"]), max(1, n_samples - 1))
        return KNN(
            n_neighbors=n_neighbors,
            method=str(params["method"]),
            contamination=float(params["contamination"]),
        )


class ECODDetector(_BasePyODDetector):
    key = "ecod"
    name = "ECOD"

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        return ECOD(contamination=float(params["contamination"]))


class OCSVMDetector(_BasePyODDetector):
    key = "ocsvm"
    name = "OCSVM"

    def _build_model(self, params: dict[str, Any], n_samples: int, seed: int) -> Any:
        return OCSVM(
            kernel=str(params["kernel"]),
            nu=float(params["nu"]),
            contamination=float(params["contamination"]),
        )


ANOMALY_DETECTORS: dict[str, type[Detector]] = {
    "iforest": IForestDetector,
    "lof": LOFDetector,
    "knn": KNNDetector,
    "ecod": ECODDetector,
    "ocsvm": OCSVMDetector,
}