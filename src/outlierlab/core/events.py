from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

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


def events_from_labels(labels, kind: EventKind = "anomaly") -> list[Event]:
    """[0, 1, 1, 0, 1] -> [Event(1, 2), Event(4, 4)]"""
    flags = pd.Series(labels).fillna(0).to_numpy().astype(bool)
    events: list[Event] = []
    start = None
    for i, flag in enumerate(flags):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            events.append(Event(start, i - 1, kind))
            start = None
    if start is not None:
        events.append(Event(start, len(flags) - 1, kind))
    return events


def check_events(events: list[Event], n_rows: int) -> None:
    """Raise if an event is outside the data or two events overlap."""
    ordered = sorted(events, key=lambda e: e.start)
    for e in ordered:
        if e.end >= n_rows:
            raise ValueError(
                f"Event {e.start}..{e.end} is past the last row ({n_rows - 1})"
            )
    for a, b in zip(ordered, ordered[1:]):
        if b.start <= a.end:
            raise ValueError(
                f"Events {a.start}..{a.end} and {b.start}..{b.end} overlap"
            )
