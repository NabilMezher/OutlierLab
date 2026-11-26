import pytest

from outlierlab.core.events import Event


def test_point_event_is_valid():
    e = Event(5, 5)
    assert e.kind == "anomaly"


def test_backwards_range_is_rejected():
    with pytest.raises(ValueError):
        Event(10, 3)


from outlierlab.core.events import Event, check_events, events_from_labels


def test_runs_become_intervals():
    ev = events_from_labels([0, 1, 1, 0, 0, 1])
    assert [(e.start, e.end) for e in ev] == [(1, 2), (5, 5)]


def test_no_labels_no_events():
    assert events_from_labels([0, 0, 0]) == []


def test_overlap_rejected():
    with pytest.raises(ValueError, match="overlap"):
        check_events([Event(1, 5), Event(4, 6)], n_rows=10)


def test_past_end_rejected():
    with pytest.raises(ValueError):
        check_events([Event(8, 12)], n_rows=10)
