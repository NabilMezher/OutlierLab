from dataclasses import replace
import os
import queue
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import customtkinter as ctk
import numpy as np
import pandas as pd
import pytest

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import score
from outlierlab.core.state import ComparatorState
from outlierlab.gui.compare_tab import CompareTab, _prepare_comparison, _Request, _worker


@pytest.fixture
def request_data():
    return _Request(
        revision=1, series=pd.Series(np.arange(30, dtype=float), name="Sensor"),
        results={
            "change": RunResult("change", "Change detector", "change", [(12, 12), (25, 25)]),
            "anomaly": RunResult("anomaly", "Anomaly detector", "anomaly", [(5, 6)]),
            "failed": RunResult("failed", "Failed detector", "anomaly", status="failed"),
        },
        events=[Event(10, 10, "change"), Event(5, 6)],
        tolerance=0, visible=["change"], sample_range=None,
    )


def test_background_preparation_scores_all_completed_runs_including_hidden(request_data):
    response = _prepare_comparison(request_data)
    assert not response.error
    assert response.revision == request_data.revision
    assert len(response.figure.axes) == 2
    assert set(response.scores) == {"change", "anomaly"}
    for key in response.scores:
        assert response.scores[key] == score(request_data.results[key], request_data.events, 0)


def test_tolerance_changes_classification_and_scores(request_data):
    strict = _prepare_comparison(request_data)
    relaxed = _prepare_comparison(replace(request_data, tolerance=3))
    assert strict.scores["change"].found_events == 0
    assert relaxed.scores["change"].found_events == 1
    assert {line.get_gid() for line in relaxed.figure.axes[1].lines} >= {"alarm-0-matched"}


def test_zoom_and_hiding_rows_do_not_change_scores(request_data):
    full = _prepare_comparison(request_data)
    cropped = _prepare_comparison(replace(request_data, sample_range=(20, 29), visible=[]))
    assert cropped.scores == full.scores
    assert len(cropped.figure.axes) == 1
    assert cropped.figure.axes[0].get_xlim() == (19.5, 29.5)


def test_invalid_data_produces_a_displayable_error(request_data):
    response = _prepare_comparison(replace(request_data, events=[Event(99, 99)]))
    assert response.figure is None
    assert response.scores is None
    assert response.error


def test_worker_handles_requests_and_shutdown_without_tk(request_data):
    requests, responses = queue.Queue(), queue.Queue()
    worker = threading.Thread(target=_worker, args=(requests, responses), daemon=True)
    worker.start()
    requests.put(request_data)
    requests.put(None)
    response = responses.get(timeout=10)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert not response.error
    assert response.revision == request_data.revision


@pytest.fixture(scope="module")
def root():
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        pytest.skip("Tk widget checks need a display; worker tests run headlessly")
    try:
        window = ctk.CTk()
    except Exception as exc:
        pytest.skip(f"Tk is unavailable: {exc}")
    window.withdraw()
    callback_errors = []
    window.report_callback_exception = lambda kind, value, traceback: callback_errors.append(value)
    yield window
    window.destroy()
    assert not callback_errors, callback_errors


def wait_for(root, predicate):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.01)
    pytest.fail("Compare tab did not finish updating")


@pytest.fixture
def tab(root, request_data):
    state = ComparatorState(
        data=request_data.series.to_frame(), value_col="Sensor", tolerance=0,
        results=request_data.results, events=request_data.events,
    )
    app = SimpleNamespace(app_state=state, tab_frames={})
    frame = CompareTab(root, app)
    frame.pack(fill="both", expand=True)
    wait_for(root, lambda: frame._plot_canvas is not None)
    yield frame
    frame.destroy()


def test_widget_tolerance_and_detector_selection_update_shared_scores(root, tab):
    tab._on_tolerance(1)
    tab._on_tolerance(3)
    wait_for(root, lambda: tab.app.app_state.scores.get("change") is not None
             and tab.app.app_state.scores["change"].found_events == 1)
    assert tab.app.app_state.tolerance == 3
    tab._visible["anomaly"].set(False)
    tab.refresh()
    wait_for(root, lambda: tab._plot_canvas is not None and len(tab._plot_canvas.figure.axes) == 3
             and bool(tab.app.app_state.scores))
    assert "anomaly" in tab.app.app_state.scores
    tab._show_all(False)
    wait_for(root, lambda: tab._plot_canvas is not None and len(tab._plot_canvas.figure.axes) == 1)
    assert set(tab.app.app_state.scores) == {"change", "anomaly"}


def test_widget_overview_zoom_and_reset_preserve_scores(root, tab):
    before = dict(tab.app.app_state.scores)
    tab._on_span(7.2, 15.1)
    for axis in tab._plot_canvas.figure.axes:
        assert axis.get_xlim() == (6.5, 16.5)
    assert tab.app.app_state.scores == before
    tab.refresh()
    wait_for(root, lambda: bool(tab.app.app_state.scores))
    assert tab._plot_canvas.figure.axes[0].get_xlim() == (6.5, 16.5)
    tab._full_range()
    assert tab._plot_canvas.figure.axes[0].get_xlim() == (-0.5, 29.5)


def test_widget_data_replacement_resets_zoom_and_missing_data_clears_plot(root, tab):
    tab._on_span(7, 15)
    tab.app.app_state.data = tab.app.app_state.data.copy()
    tab.refresh()
    wait_for(root, lambda: bool(tab.app.app_state.scores))
    assert tab._sample_range is None
    tab.app.app_state.data = None
    tab.refresh()
    assert tab._plot_canvas is None
    assert not tab.app.app_state.scores
    assert "Load a signal" in tab.status_label.cget("text")


def test_widget_invalid_events_show_error_instead_of_crashing(root, tab):
    tab.app.app_state.events.append(Event(99, 99))
    tab.refresh()
    wait_for(root, lambda: tab.status_label.cget("text").startswith("Cannot compare"))
    assert tab._plot_canvas is None
    assert not tab.app.app_state.scores


def test_widget_shutdown_cancels_pending_callbacks(root, tab):
    tab._on_tolerance(4)
    tab.destroy()
    root.update()
    assert tab._closed


def test_widget_controls_fit_the_default_window(root, tab):
    root.geometry("1180x720")
    root.deiconify()
    root.update()
    for widget in (tab.tolerance_slider, tab.full_range_button, tab.status_label,
                   tab.range_label, tab._overview_canvas.get_tk_widget()):
        left = widget.winfo_rootx() - root.winfo_rootx()
        top = widget.winfo_rooty() - root.winfo_rooty()
        assert 0 <= left < root.winfo_width()
        assert 0 <= top < root.winfo_height()
        assert left + widget.winfo_width() <= root.winfo_width()
        assert top + widget.winfo_height() <= root.winfo_height()
    root.withdraw()


def test_repeated_redraws_release_tk_images_on_the_main_thread(root, tab):
    for tolerance in range(8):
        tab._on_tolerance(tolerance)
        try:
            wait_for(root, lambda: bool(tab.app.app_state.scores)
                     and tab._plot_canvas is not None
                     and f"Tolerance: {tolerance} samples" in tab._plot_canvas.figure._suptitle.get_text())
        except pytest.fail.Exception:
            pytest.fail(f"Redraw at tolerance {tolerance}: {tab.status_label.cget('text')}")


def test_app_registers_compare_and_switches_from_detectors_without_redraw_errors(root):
    # App owns a Tk root, so use an isolated interpreter rather than creating
    # another Tk application inside the widget fixture's interpreter.
    code = """
from outlierlab.gui.app import App
app = App()
errors = []
app.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
assert "Compare" in app.tab_frames
app.tabs.set("Detectors")
app.update()
app.tabs.set("Compare")
app.update()
assert "Load a signal" in app.tab_frames["Compare"].status_label.cget("text")
app.destroy()
assert not errors, errors
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "Exception in Tkinter callback" not in completed.stderr
