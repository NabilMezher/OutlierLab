from dataclasses import asdict
from itertools import product
import json

import pytest

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import AlarmMatch, match_alarms, score


def run(alarms=(), family="anomaly", status="done"):
    return RunResult("test", "Test detector", family, list(alarms), status=status)


def test_hand_worked_metrics():
    result = run([(12, 12), (29, 29), (70, 70), (90, 90)])
    events = [Event(10, 10), Event(30, 32), Event(50, 50)]
    actual = score(result, events, tolerance=2)
    assert actual.found_events == 2
    assert actual.missed_events == 1
    assert actual.false_alarms == 2
    assert actual.precision == pytest.approx(1 / 2)
    assert actual.recall == pytest.approx(2 / 3)
    assert actual.f1 == pytest.approx(4 / 7)
    assert actual.mean_delay == 1.0


@pytest.mark.parametrize("alarm,hit", [(4, True), (16, True), (3, False), (17, False)])
def test_tolerance_boundary_is_inclusive(alarm, hit):
    events = [Event(10, 10)]
    assert score(run([(alarm, alarm)]), events, 6).found_events == int(hit)
    assert score(run([(alarm, alarm)]), events, 0).found_events == 0


@pytest.mark.parametrize("alarm", [(10, 10), (20, 20), (12, 15), (5, 25)])
def test_interval_overlap_at_zero_tolerance(alarm):
    assert score(run([alarm]), [Event(10, 20)], 0).found_events == 1


@pytest.mark.parametrize("family", ["anomaly", "change"])
def test_only_same_kind_events_are_eligible(family):
    other = "change" if family == "anomaly" else "anomaly"
    events = [Event(10, 10, family), Event(30, 30, other)]
    actual = score(run([(10, 10), (30, 30)], family), events, 0)
    assert actual.found_events == 1
    assert actual.false_alarms == 1
    assert actual.missed_events == 0
    assert actual.recall == 1.0
    assert score(run([(30, 30)], family), events, 0).found_events == 0


def test_duplicate_alarms_are_false_alarms():
    result = run([(10, 10), (10, 10), (11, 11)])
    assert match_alarms(result, [Event(10, 10)], 1) == [AlarmMatch(0, 0, 0)]
    assert score(result, [Event(10, 10)], 1).false_alarms == 2


def test_broad_alarm_can_match_only_one_event():
    actual = score(run([(0, 100)]), [Event(10, 10), Event(30, 30)], 0)
    assert actual.found_events == 1
    assert actual.recall == 0.5


def test_matching_reassigns_an_alarm_to_avoid_a_greedy_miss():
    # Event 0 accepts either alarm; event 1 can only use alarm 0.
    result = run([(0, 20), (10, 10)])
    events = [Event(10, 10), Event(20, 20)]
    assert match_alarms(result, events, 0) == [AlarmMatch(1, 0, 0), AlarmMatch(0, 1, 0)]
    assert score(result, events, 0).f1 == 1.0


def test_matches_retain_original_indices_for_unsorted_inputs():
    result = run([(32, 32), (11, 11)])
    events = [Event(30, 30), Event(10, 10)]
    assert match_alarms(result, events, 2) == [AlarmMatch(0, 0, 2), AlarmMatch(1, 1, 1)]


@pytest.mark.parametrize("alarm,delay", [((8, 8), 0), ((8, 14), 0), ((14, 14), 4)])
def test_delay_is_measured_from_event_start(alarm, delay):
    assert score(run([alarm]), [Event(10, 12)], 2).mean_delay == delay


@pytest.mark.parametrize(
    "alarms,events,missed,false_alarms",
    [([], [], 0, 0), ([], [Event(10, 10)], 1, 0), ([(10, 10)], [], 0, 1),
     ([(10, 10)], [Event(30, 30)], 1, 1)],
)
def test_empty_and_no_match_cases(alarms, events, missed, false_alarms):
    actual = score(run(alarms), events, 0)
    assert actual.found_events == 0
    assert actual.missed_events == missed
    assert actual.false_alarms == false_alarms
    assert (actual.precision, actual.recall, actual.f1) == (0.0, 0.0, 0.0)
    assert actual.mean_delay is None
    # Export must be able to use strict JSON, without NaN or Infinity.
    assert json.loads(json.dumps(asdict(actual), allow_nan=False))["mean_delay"] is None


@pytest.mark.parametrize("tolerance", [-1, 1.5, True, "6", None])
def test_invalid_tolerance_is_rejected(tolerance):
    with pytest.raises(ValueError, match="tolerance"):
        score(run(), [], tolerance)


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
def test_incomplete_runs_are_not_scored(status):
    with pytest.raises(ValueError, match="status"):
        score(run(status=status), [])


def test_invalid_families_are_rejected():
    with pytest.raises(ValueError, match="family"):
        score(run(family="unknown"), [])
    with pytest.raises(ValueError, match="kind"):
        score(run(), [Event(1, 1, "unknown")])


@pytest.mark.parametrize("start,end", [(-1, 2), (3, 2), (1.5, 2), (True, 2)])
def test_invalid_mutated_intervals_are_rejected(start, end):
    result = run()
    result.alarms.append((start, end))
    with pytest.raises(ValueError, match="row positions"):
        score(result, [])
    event = Event(0, 0)
    event.start, event.end = start, end
    with pytest.raises(ValueError, match="row positions"):
        score(run(), [event])


def test_matching_does_not_modify_inputs():
    result = run([(20, 20), (10, 10)])
    events = [Event(20, 20), Event(10, 10)]
    before = (asdict(result), [asdict(event) for event in events])
    assert match_alarms(result, events) == match_alarms(result, events)
    assert (asdict(result), [asdict(event) for event in events]) == before


def test_hit_count_matches_exhaustive_small_interval_cases():
    # Independent brute-force oracle guards the matching algorithm, including
    # overlapping annotations and alarms that need multiple reassignments.
    intervals = [(0, 0), (1, 1), (2, 2), (0, 2)]

    def best_count(alarms, events, index=0, used=frozenset()):
        if index == len(events):
            return 0
        best = best_count(alarms, events, index + 1, used)
        event = events[index]
        for i, (start, end) in enumerate(alarms):
            if i not in used and start <= event.end and end >= event.start:
                best = max(best, 1 + best_count(alarms, events, index + 1, used | {i}))
        return best

    for alarms in product(intervals, repeat=3):
        for spans in product(intervals, repeat=3):
            events = [Event(*span) for span in spans]
            matches = match_alarms(run(alarms), events, 0)
            assert len(matches) == best_count(alarms, events)
            assert len({m.alarm_index for m in matches}) == len(matches)
            assert len({m.event_index for m in matches}) == len(matches)
