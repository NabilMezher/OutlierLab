from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from outlierlab.core.detectors.base import DetectorSpec, RunResult
from outlierlab.core.events import Event


@dataclass
class ComparatorState:
    """Everything the tabs share. Created once in App and passed to every tab."""

    # A: data and ground truth
    data: pd.DataFrame | None = None
    source_path: str = ""
    value_col: str = ""
    missing_policy: str = "interpolate"  # interpolate | drop | gaps
    events: list[Event] = field(default_factory=list)

    # B: detectors and runs
    detectors: list[DetectorSpec] = field(default_factory=list)
    seed: int = 42
    results: dict[str, RunResult] = field(default_factory=dict)

    # C: scoring
    tolerance: int = 6
    scores: dict[str, Any] = field(default_factory=dict)

    @property
    def series(self) -> pd.Series:
        """The single column every detector runs on."""
        if self.data is None or not self.value_col:
            raise RuntimeError("No data loaded yet")
        return self.data[self.value_col]