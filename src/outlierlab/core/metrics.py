"""Event-level scoring shared by the GUI, reports and reproduction scripts.

All intervals include both endpoints and use row positions, not timestamps.
Only events of the detector's family contribute to its recall denominator.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from numbers import Integral
from typing import Sequence

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event


@dataclass(frozen=True)
class AlarmMatch:
    """A matched pair, with indices into the original alarms and events lists."""

    alarm_index: int
    event_index: int
    delay: int


@dataclass(frozen=True)
class Score:
    """Event metrics; mean_delay is None when no event was detected."""

    found_events: int
    missed_events: int
    false_alarms: int
    precision: float
    recall: float
    f1: float
    mean_delay: float | None


def _validate_interval(start: int, end: int) -> None:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, Integral)
        or not isinstance(end, Integral)
        or start < 0
        or end < start
    ):
        raise ValueError("Interval endpoints must be non-negative integer row positions")


def match_alarms(
    result: RunResult, events: Sequence[Event], tolerance: int = 6
) -> list[AlarmMatch]:
    """Find a deterministic maximum-cardinality, one-to-one event matching.

    An alarm [a, b] can match [s, e] when a <= e + tolerance and
    b >= s - tolerance, and result.family equals event.kind. Each alarm and
    event may appear at most once. Duplicate alarms therefore incur false
    alarms, and a single broad alarm cannot claim several events.

    Events are visited chronologically, with candidate alarms in start/end
    order (original index breaks ties). Augmenting paths avoid losing hits
    when a greedy choice would block another event. Ties are deterministic;
    the matching maximizes the hit count, not a separate delay objective.

    Delay is max(0, alarm.start - event.start), in samples. An alarm already
    active at event onset has delay zero. Non-completed runs are rejected.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, Integral) or tolerance < 0:
        raise ValueError("tolerance must be a non-negative integer number of samples")
    if result.status != "done":
        raise ValueError(f"Cannot score a run with status {result.status!r}")
    if result.family not in ("anomaly", "change"):
        raise ValueError(f"Unknown detector family: {result.family!r}")
    for start, end in result.alarms:
        _validate_interval(start, end)
    for event in events:
        _validate_interval(event.start, event.end)
        if event.kind not in ("anomaly", "change"):
            raise ValueError(f"Unknown event kind: {event.kind!r}")

    event_indices = sorted(
        (i for i, event in enumerate(events) if event.kind == result.family),
        key=lambda i: (events[i].start, events[i].end, i),
    )
    alarm_indices = sorted(
        range(len(result.alarms)), key=lambda i: (*result.alarms[i], i)
    )
    candidates = {
        i: [
            j for j in alarm_indices
            if result.alarms[j][0] <= events[i].end + tolerance
            and result.alarms[j][1] >= events[i].start - tolerance
        ]
        for i in event_indices
    }
    alarm_to_event: dict[int, int] = {}
    event_to_alarm: dict[int, int] = {}
    for root in event_indices:
        queue = deque([root])
        visited_events = {root}
        # Records the alternating path used to reach each alarm.
        parents: dict[int, int] = {}
        free_alarm = None
        while queue and free_alarm is None:
            event_index = queue.popleft()
            for alarm_index in candidates[event_index]:
                if alarm_index in parents:
                    continue
                parents[alarm_index] = event_index
                if alarm_index not in alarm_to_event:
                    free_alarm = alarm_index
                    break
                owner = alarm_to_event[alarm_index]
                if owner not in visited_events:
                    visited_events.add(owner)
                    queue.append(owner)
        while free_alarm is not None:
            event_index = parents[free_alarm]
            previous_alarm = event_to_alarm.get(event_index)
            alarm_to_event[free_alarm] = event_index
            event_to_alarm[event_index] = free_alarm
            free_alarm = previous_alarm

    return [
        AlarmMatch(
            alarm_index=alarm_index,
            event_index=event_index,
            delay=max(0, int(result.alarms[alarm_index][0] - events[event_index].start)),
        )
        for event_index, alarm_index in sorted(event_to_alarm.items())
    ]


def score(result: RunResult, events: Sequence[Event], tolerance: int = 6) -> Score:
    """Score one completed run using match_alarms as the source of truth.

    Precision = matched alarms / all alarms; recall = matched events / events
    of this detector's family. A zero denominator gives 0.0, including F1.
    Runs without relevant annotations cannot establish detector quality;
    their alarms are unmatched, and all three rates are defined as zero.
    """
    matches = match_alarms(result, events, tolerance)
    found = len(matches)
    relevant_events = sum(event.kind == result.family for event in events)
    precision = found / len(result.alarms) if result.alarms else 0.0
    recall = found / relevant_events if relevant_events else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Score(
        found_events=found,
        missed_events=relevant_events - found,
        false_alarms=len(result.alarms) - found,
        precision=precision,
        recall=recall,
        f1=f1,
        mean_delay=sum(match.delay for match in matches) / found if found else None,
    )
