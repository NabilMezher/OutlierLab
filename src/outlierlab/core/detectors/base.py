from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
import pandas as pd

AlarmInterval = tuple[int, int]
DetectorFamily = Literal["changepoint", "anomaly"]
RunStatus = Literal["done", "timed_out", "cancelled", "failed"]


@dataclass
class DetectorSpec:
    """Configuration for one detector instance in ComparatorState.detectors."""

    key: str
    name: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("DetectorSpec.key must not be empty")
        if not self.name.strip():
            raise ValueError("DetectorSpec.name must not be empty")


@dataclass
class RunResult:
    """Standardised output returned by every detector (B -> C handover contract)."""

    detector_key: str
    detector_name: str
    family: DetectorFamily
    alarms: list[AlarmInterval] = field(default_factory=list)
    scores: np.ndarray | None = None
    threshold: float | None = None
    runtime_s: float = 0.0
    status: RunStatus = "done"
    error: str = ""

    def __post_init__(self) -> None:
        for start, end in self.alarms:
            if start < 0 or end < start:
                raise ValueError(f"Bad alarm interval {start}..{end}")
        if self.runtime_s < 0:
            raise ValueError(f"runtime_s must be non-negative, got {self.runtime_s}")


class Detector(ABC):
    """Base interface implemented by all changepoint and anomaly detectors."""

    key: str
    name: str
    family: DetectorFamily
    uses_seed: bool = False

    @abstractmethod
    def fit_detect(
        self,
        series: pd.Series,
        seed: int = 42,
        **params: Any,
    ) -> RunResult:
        """Run detection on a 1-D series and return a RunResult."""