from dataclasses import asdict
from pathlib import Path
import subprocess
import sys

import matplotlib

matplotlib.use("Agg")

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pytest

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import match_alarms
from outlierlab.core.plotting import (
    FALSE_ALARM_COLOR,
    MATCH_COLOR,
    build_comparison_figure,
)


@pytest.fixture
def series():
    return pd.Series(
        np.arange(40, dtype=float), name="Sensor",
        index=pd.date_range("2026-01-01", periods=40, freq="min"),
    )


def result(alarms=(), family="anomaly", status="done", name="Detector"):
    return RunResult("test", name, family, list(alarms), status=status)


def alarm_artists(axis):
    return {
        artist.get_gid(): artist
        for artist in [*axis.lines, *axis.patches]
        if (artist.get_gid() or "").startswith("alarm-")
    }


def test_signal_and_detector_rows_render_and_export(series, tmp_path):
    runs = {"a": result([(10, 12), (30, 30)]), "b": result([(20, 20)], "change")}
    events = [Event(10, 12), Event(20, 20, "change")]
    figure = build_comparison_figure(series, runs, events, tolerance=0)
    assert isinstance(figure, Figure)
    assert len(figure.axes) == 3
    np.testing.assert_array_equal(figure.axes[0].lines[0].get_xdata(), np.arange(40))
    np.testing.assert_array_equal(figure.axes[0].lines[0].get_ydata(), series.to_numpy())
    assert figure.axes[-1].get_xlabel() == "Sample (row position)"
    assert figure.axes[-1].get_xlim() == (-0.5, 39.5)
    FigureCanvasAgg(figure).draw()
    png = tmp_path / "comparison.png"
    figure.savefig(png)
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_alarm_colors_and_indices_follow_metrics_including_duplicates(series):
    run = result([(30, 30), (10, 12), (10, 12)])
    events = [Event(10, 12)]
    figure = build_comparison_figure(series, {"a": run}, events, 0)
    artists = alarm_artists(figure.axes[1])
    matched = {match.alarm_index for match in match_alarms(run, events, 0)}
    for i, (start, end) in enumerate(run.alarms):
        hit = i in matched
        artist = artists[f"alarm-{i}-{'matched' if hit else 'false'}"]
        color = MATCH_COLOR if hit else FALSE_ALARM_COLOR
        if start == end:
            assert to_rgba(artist.get_color()) == to_rgba(color)
            assert list(artist.get_xdata()) == [start, start]
        else:
            assert to_rgba(artist.get_facecolor()) == to_rgba(color)
            bounds = artist.get_path().get_extents(artist.get_patch_transform())
            assert bounds.xmin == start - 0.5
            assert bounds.xmax == end + 0.5


def test_event_types_and_tolerance_change_alarm_classification(series):
    events = [Event(10, 10), Event(30, 30, "change")]
    run = result([(16, 16), (30, 30)])
    strict = build_comparison_figure(series, {"a": run}, events, 0)
    relaxed = build_comparison_figure(series, {"a": run}, events, 6)
    assert set(alarm_artists(strict.axes[1])) == {"alarm-0-false", "alarm-1-false"}
    assert set(alarm_artists(relaxed.axes[1])) == {"alarm-0-matched", "alarm-1-false"}
    assert {a.get_gid() for a in relaxed.axes[0].lines} >= {"event-0", "event-1"}
    assert "event-1" not in {a.get_gid() for a in relaxed.axes[1].lines}


def test_zoom_does_not_rescore_only_visible_events(series):
    # The broad alarm matches event 0 outside the view. Zoom must not
    # reclassify it using only the later event visible in the viewport.
    events = [Event(5, 5), Event(25, 25)]
    runs = {"a": result([(0, 30), (26, 26)])}
    full = build_comparison_figure(series, runs, events, 1)
    zoom = build_comparison_figure(series, runs, events, 1, sample_range=(20, 35))
    assert set(alarm_artists(full.axes[1])) == set(alarm_artists(zoom.axes[1]))
    for axis in zoom.axes:
        assert axis.get_xlim() == (19.5, 35.5)


def test_detector_selection_controls_order_and_hides_rows(series):
    runs = {key: result(name=key) for key in ("a", "b", "c")}
    figure = build_comparison_figure(series, runs, [], detector_keys=["c", "a"])
    assert len(figure.axes) == 3
    assert [a.get_yticklabels()[0].get_text() for a in figure.axes[1:]] == ["c", "a"]
    assert len(build_comparison_figure(series, runs, [], detector_keys=[]).axes) == 1


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
def test_incomplete_runs_show_status_without_classified_alarms(series, status):
    figure = build_comparison_figure(series, {"a": result([(10, 10)], status=status)}, [])
    axis = figure.axes[1]
    assert not alarm_artists(axis)
    assert f"{status.replace('_', ' ')} (unscored)" in [t.get_text() for t in axis.texts]
    FigureCanvasAgg(figure).draw()


def test_signal_only_and_completed_run_without_alarms(series):
    assert len(build_comparison_figure(series, {}, []).axes) == 1
    figure = build_comparison_figure(series, {"a": result()}, [])
    assert [t.get_text() for t in figure.axes[1].texts] == ["No alarms"]


def test_single_sample_and_missing_values_render():
    for data in ([1.0], [np.nan], [1.0, np.nan, 3.0]):
        series = pd.Series(data)
        figure = build_comparison_figure(series, {}, [Event(0, 0)])
        FigureCanvasAgg(figure).draw()
        np.testing.assert_equal(figure.axes[0].lines[0].get_ydata(), data)


def test_nullable_pandas_series_keeps_gaps():
    series = pd.Series([1.0, pd.NA, 3.0], dtype="Float64")
    figure = build_comparison_figure(series, {}, [])
    np.testing.assert_equal(figure.axes[0].lines[0].get_ydata(), [1, np.nan, 3])


@pytest.mark.parametrize("data", [[], ["bad", "data"], [np.inf], [-np.inf]])
def test_invalid_signal_is_rejected(data):
    with pytest.raises(ValueError, match="series"):
        build_comparison_figure(pd.Series(data, dtype=object), {}, [])


@pytest.mark.parametrize("tolerance", [-1, 1.5, True])
def test_invalid_tolerance_is_rejected_even_without_results(series, tolerance):
    with pytest.raises(ValueError, match="tolerance"):
        build_comparison_figure(series, {}, [], tolerance)


@pytest.mark.parametrize("span", [(-1, 5), (1, 40), (10, 9), (1.5, 10), (True, 10)])
def test_out_of_bounds_or_non_integer_positions_are_rejected(series, span):
    with pytest.raises(ValueError, match="sample_range"):
        build_comparison_figure(series, {}, [], sample_range=span)
    event = Event(0, 0)
    event.start, event.end = span
    with pytest.raises(ValueError, match="Event"):
        build_comparison_figure(series, {}, [event])
    run = result()
    run.alarms.append(span)
    with pytest.raises(ValueError, match="Alarm"):
        build_comparison_figure(series, {"a": run}, [])


def test_unknown_or_duplicate_keys_and_invalid_types_are_rejected(series):
    with pytest.raises(ValueError, match="Unknown detector"):
        build_comparison_figure(series, {}, [], detector_keys=["absent"])
    with pytest.raises(ValueError, match="duplicates"):
        build_comparison_figure(series, {"a": result()}, [], detector_keys=["a", "a"])
    with pytest.raises(ValueError, match="kind"):
        build_comparison_figure(series, {}, [Event(0, 0, "unknown")])
    with pytest.raises(ValueError, match="status"):
        build_comparison_figure(series, {"a": result(status="unknown")}, [])


def test_figure_building_does_not_modify_shared_inputs(series):
    original_series = series.copy(deep=True)
    run = result([(20, 20), (5, 5)])
    events = [Event(20, 20), Event(5, 5)]
    before = (asdict(run), [asdict(event) for event in events])
    build_comparison_figure(series, {"a": run}, events)
    pd.testing.assert_series_equal(series, original_series)
    assert (asdict(run), [asdict(event) for event in events]) == before


def test_importing_plotting_does_not_load_gui_or_pyplot():
    # Use a clean interpreter so other tests cannot mask an accidental import.
    code = """
import sys
from outlierlab.core.plotting import build_comparison_figure
assert 'tkinter' not in sys.modules
assert 'customtkinter' not in sys.modules
assert 'matplotlib.pyplot' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        cwd=Path(__file__).resolve().parents[1] / "src",
    )
    assert completed.returncode == 0, completed.stderr
