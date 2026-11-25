from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EventKind = Literal["anomaly", "change"]


@dataclass
class Event:
    """One marked event. start and end are row positions in state.data."""

    start: int
    end: int  # same as start for a single point
    kind: EventKind = "anomaly"  # "anomaly" or "change" (level change)
    note: str = ""

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"Bad event range {self.start}..{self.end}")
