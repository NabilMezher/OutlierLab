from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from outlierlab.core.detectors.base import Detector, DetectorSpec, RunResult
from outlierlab.core.detectors.changepoint import CHANGE_DETECTORS
from outlierlab.core.detectors.outlier import ANOMALY_DETECTORS
from outlierlab.core.registry import get_detector_meta

ALL_DETECTORS: dict[str, type[Detector]] = {
    **CHANGE_DETECTORS,
    **ANOMALY_DETECTORS,
}

ProgressKind = Literal["started", "detector_done", "cancelled", "finished"]


def create_detector(
    key: str,
    detectors_map: dict[str, type[Detector]] | None = None,
) -> Detector:
    """Instantiate a detector by registry key."""
    registry = detectors_map if detectors_map is not None else ALL_DETECTORS
    if key not in registry:
        raise KeyError(f"Unknown detector key: {key!r}")
    return registry[key]()


@dataclass(frozen=True)
class ProgressEvent:
    """Message pushed from the worker thread to the GUI/caller queue."""

    kind: ProgressKind
    detector_key: str = ""
    detector_name: str = ""
    index: int = 0
    total: int = 0
    result: RunResult | None = None
    message: str = ""


class TaskRunner:
    """Runs enabled detectors in a background thread with cancel and timeout support."""

    def __init__(self) -> None:
        self.progress_queue: queue.Queue[ProgressEvent] = queue.Queue()
        self.results: dict[str, RunResult] = {}
        self._cancel_event = threading.Event()
        self._thread: threading.Thread | None = None

    def is_running(self) -> bool:
        """Return True while the background worker thread is active."""
        return self._thread is not None and self._thread.is_alive()

    def cancel(self) -> None:
        """Request cancellation before the next queued detector starts."""
        self._cancel_event.set()

    def join(self, timeout: float | None = None) -> None:
        """Wait for the worker thread to finish (useful in tests and scripts)."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def start(
        self,
        specs: list[DetectorSpec],
        series: pd.Series,
        seed: int = 42,
        timeout_s: float = 60.0,
        detectors_map: dict[str, type[Detector]] | None = None,
    ) -> None:
        """Start running all enabled detectors in a daemon thread."""
        if self.is_running():
            raise RuntimeError("TaskRunner is already running")

        self._cancel_event.clear()
        self.results = {}
        while not self.progress_queue.empty():
            try:
                self.progress_queue.get_nowait()
            except queue.Empty:
                break

        enabled = [s for s in specs if s.enabled]
        self._thread = threading.Thread(
            target=self._run_all,
            args=(enabled, series, seed, timeout_s, detectors_map),
            daemon=True,
        )
        self._thread.start()

    def _run_all(
        self,
        specs: list[DetectorSpec],
        series: pd.Series,
        seed: int,
        timeout_s: float,
        detectors_map: dict[str, type[Detector]] | None,
    ) -> None:
        total = len(specs)
        for idx, spec in enumerate(specs):
            if self._cancel_event.is_set():
                self.progress_queue.put(
                    ProgressEvent(
                        kind="cancelled",
                        index=idx,
                        total=total,
                        message="Cancelled by user. Finished detectors kept their results.",
                    )
                )
                return

            self.progress_queue.put(
                ProgressEvent(
                    kind="started",
                    detector_key=spec.key,
                    detector_name=spec.name,
                    index=idx,
                    total=total,
                    message=f"Running {spec.name} ({idx + 1} of {total})",
                )
            )

            res = self._run_one(spec, series, seed, timeout_s, detectors_map)
            self.results[spec.key] = res
            self.progress_queue.put(
                ProgressEvent(
                    kind="detector_done",
                    detector_key=spec.key,
                    detector_name=spec.name,
                    index=idx,
                    total=total,
                    result=res,
                    message=f"{spec.name}: {res.status} in {res.runtime_s:.2f} s",
                )
            )

        self.progress_queue.put(
            ProgressEvent(
                kind="finished",
                index=total,
                total=total,
                message=f"Finished {total} detector(s).",
            )
        )

    def _run_one(
        self,
        spec: DetectorSpec,
        series: pd.Series,
        seed: int,
        timeout_s: float,
        detectors_map: dict[str, type[Detector]] | None,
    ) -> RunResult:
        family = get_detector_meta(spec.key).family if spec.key in ALL_DETECTORS else "anomaly"
        t0 = time.perf_counter()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            lambda: create_detector(spec.key, detectors_map).fit_detect(
                series, seed=seed, **spec.params
            )
        )
        try:
            res = future.result(timeout=timeout_s)
            executor.shutdown(wait=False, cancel_futures=True)
            return res
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            return RunResult(
                detector_key=spec.key,
                detector_name=spec.name,
                family=family,
                runtime_s=timeout_s,
                status="timed_out",
                error=f"Timed out after {timeout_s:.1f} s",
            )
        except Exception as exc:
            executor.shutdown(wait=False, cancel_futures=True)
            return RunResult(
                detector_key=spec.key,
                detector_name=spec.name,
                family=family,
                runtime_s=time.perf_counter() - t0,
                status="failed",
                error=str(exc),
            )