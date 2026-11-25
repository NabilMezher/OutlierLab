import pytest

from outlierlab.core.events import Event


def test_point_event_is_valid():
    e = Event(5, 5)
    assert e.kind == "anomaly"


def test_backwards_range_is_rejected():
    with pytest.raises(ValueError):
        Event(10, 3)
