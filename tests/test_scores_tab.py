from dataclasses import asdict, replace
import os
import queue
import subprocess
import sys
import threading

import pandas as pd
import pytest

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import score
from outlierlab.gui.scores_tab import _best_cells, _prepare_rows, _sort_rows, _worker


@pytest.fixture
def inputs():
    results = {
        "pelt": RunResult("pelt", "PELT", "change", [(12, 12), (25, 25)], runtime_s=0.2),
        "binseg": RunResult("binseg", "Binseg", "change", [(10, 10)], runtime_s=0.1),
        "iforest": RunResult("iforest", "IForest", "anomaly", [(5, 6)], runtime_s=0.3),
    }
    events = [Event(10, 10, "change"), Event(5, 6)]
    return results, events


def test_rows_use_canonical_scores(inputs):
    results, events = inputs
    rows = _prepare_rows(results, events, tolerance=3, n_rows=30)
    for row in rows:
        assert row.metrics == score(results[row.key], events, 3)
        assert row.status == "done"
        assert row.event_count == 1
    assert rows[0].metrics.mean_delay == 2


@pytest.mark.parametrize("status", ["failed", "timed_out", "cancelled"])
def test_uncompleted_runs_keep_status_and_reason(inputs, status):
    results, events = inputs
    results["pelt"] = RunResult("pelt", "PELT", "change", status=status, error="Reason")
    row = _prepare_rows(results, events, 3, 30)[0]
    assert row.status == status
    assert row.metrics is None
    assert row.value("f1") is None
    assert row.error == "Reason"


def test_sorting_counts_is_numeric_and_missing_values_stay_last(inputs):
    results, events = inputs
    rows = _prepare_rows(results, events, 3, 30)
    slow = replace(rows[0], key="slow", runtime=10.0)
    fast = replace(rows[1], key="fast", runtime=2.0)
    unavailable = replace(rows[2], key="missing", runtime=None, metrics=None)
    assert [r.key for r in _sort_rows([slow, fast, unavailable], "runtime", False)] == ["fast", "slow", "missing"]
    assert [r.key for r in _sort_rows([slow, fast, unavailable], "runtime", True)] == ["slow", "fast", "missing"]
    many = replace(rows[0], key="many", metrics=replace(rows[0].metrics, false_alarms=10))
    few = replace(rows[1], key="few", metrics=replace(rows[1].metrics, false_alarms=2))
    assert [r.key for r in _sort_rows([many, few], "false_alarms", False)] == ["few", "many"]


def test_text_sorting_is_case_insensitive(inputs):
    results, events = inputs
    rows = _prepare_rows(results, events, 3, 30)
    rows = [replace(rows[0], name="zeta"), replace(rows[1], name="Alpha")]
    assert [r.name for r in _sort_rows(rows, "name", False)] == ["Alpha", "zeta"]


def test_best_values_are_per_type_with_ties_and_no_failed_winners(inputs):
    results, events = inputs
    rows = _prepare_rows(results, events, 3, 30)
    tied = replace(rows[1], key="tie", name="Tie", runtime=0.1)
    failed = replace(rows[1], key="failed", status="failed", metrics=None, runtime=0.001)
    best = _best_cells([*rows, tied, failed])
    assert ("binseg", "f1") in best and ("tie", "f1") in best
    assert ("pelt", "f1") not in best
    assert ("iforest", "f1") in best
    assert ("binseg", "runtime") in best and ("tie", "runtime") in best
    assert not any(key == "failed" for key, _ in best)


def test_no_ground_truth_does_not_mark_quality_as_best(inputs):
    results, _ = inputs
    rows = _prepare_rows(results, [], 3, 30)
    assert {column for _, column in _best_cells(rows)} == {"runtime"}
    assert all(row.metrics.f1 == 0 for row in rows)
    assert all(row.value("mean_delay") is None for row in rows)


@pytest.mark.parametrize("field,value", [("status", "unknown"), ("runtime_s", float("nan")),
                                        ("alarms", [(30, 30)])])
def test_invalid_run_does_not_hide_other_valid_runs(inputs, field, value):
    results, events = inputs
    setattr(results["pelt"], field, value)
    rows = _prepare_rows(results, events, 3, 30)
    assert rows[0].status == "invalid"
    assert rows[0].metrics is None
    assert rows[0].error
    assert all(row.metrics is not None for row in rows[1:])


def test_scores_match_json_report(inputs):
    from outlierlab.core.registry import make_default_spec
    from outlierlab.core.state import ComparatorState
    from outlierlab.io.export import build_report
    results, events = inputs
    state = ComparatorState(
        data=pd.DataFrame({"value": range(30)}), value_col="value", tolerance=3,
        results=results, events=events, detectors=[make_default_spec(key) for key in results],
    )
    rows = _prepare_rows(results, events, 3, 30)
    assert {row.key: asdict(row.metrics) for row in rows} == build_report(state)["scores"]


def test_worker_returns_revision_and_stops(inputs):
    results, events = inputs
    requests, responses = queue.Queue(), queue.Queue()
    worker = threading.Thread(target=_worker, args=(requests, responses), daemon=True)
    worker.start()
    requests.put((7, results, events, 3, 30))
    requests.put(None)
    revision, rows, error = responses.get(timeout=10)
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert revision == 7 and len(rows) == 3 and not error


def require_display():
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        pytest.skip("Tk integration needs a display; scoring and sorting tests run headlessly")


def run_gui_check(code):
    require_display()
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Exception in Tkinter callback" not in completed.stderr
    assert "Exception ignored in" not in completed.stderr


def test_scores_widget_sorting_refresh_best_cells_and_lifecycle():
    run_gui_check('''
import time
from types import SimpleNamespace
import customtkinter as ctk
import pandas as pd
from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.state import ComparatorState
from outlierlab.gui.scores_tab import ScoresTab

root = ctk.CTk()
root.withdraw()
errors = []
root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
state = ComparatorState(data=pd.DataFrame({"value": range(30)}), value_col="value", tolerance=0)
state.events = [Event(10, 10, "change"), Event(5, 6)]
state.results = {
    "pelt": RunResult("pelt", "PELT", "change", [(12, 12)], runtime_s=10),
    "iforest": RunResult("iforest", "IForest", "anomaly", [(5, 6)], runtime_s=2),
    "failed": RunResult("failed", "Failure", "anomaly", status="failed", error="Test failure"),
}
tab = ScoresTab(root, SimpleNamespace(app_state=state))
tab.pack(fill="both", expand=True)
def wait():
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        root.update()
        if not tab._pending:
            return
        time.sleep(.01)
    raise AssertionError("Scores did not finish updating")
wait()
assert state.scores["pelt"].found_events == 0
assert tab.tree.set("iforest", "f1").startswith("* ")
assert tab.tree.set("failed", "f1") == "--"
tab._sort("runtime")
assert tab.tree.get_children() == ("failed", "iforest", "pelt")
tab._sort("runtime")
assert tab.tree.get_children() == ("pelt", "iforest", "failed")
tab.tree.selection_set("failed")
tab._show_details()
assert "Test failure" in tab.detail_label.cget("text")
state.tolerance = 3
tab.refresh()
assert not state.scores
wait()
assert state.scores["pelt"].found_events == 1
assert "3 samples" in tab.summary_label.cget("text")
# A Compare refresh can replace/clear the cache without changing inputs.
state.scores.clear()
tab.refresh()
assert state.scores["pelt"].found_events == 1
state.tolerance = 0
tab.refresh()
state.tolerance = 6
tab.refresh()
wait()
assert state.scores["pelt"].found_events == 1
assert "6 samples" in tab.summary_label.cget("text")
state.events = []
tab.refresh()
wait()
assert "No ground truth" in tab.summary_label.cget("text")
assert not tab.tree.set("pelt", "f1").startswith("* ")
# Window managers may constrain the requested size to the desktop. Check
# the actual client area, including a smaller window, rather than assuming
# a fixed pixel width is available on every CI runner or DPI setting.
for geometry in ("1180x720", "820x600"):
    root.geometry(geometry)
    root.deiconify()
    root.update()
    left = tab.tree.winfo_rootx() - root.winfo_rootx()
    assert tab.tree.winfo_width() > 0
    assert 0 <= left < root.winfo_width()
    assert left + tab.tree.winfo_width() <= root.winfo_width()
    assert tab.detail_label.winfo_rooty() + tab.detail_label.winfo_height() <= root.winfo_rooty() + root.winfo_height()
    assert tab.tree.cget("xscrollcommand")
    tab.tree.xview_moveto(1)
    root.update()
    assert tab.tree.xview()[1] == 1.0
state.data = None
tab.refresh()
assert not tab.tree.get_children() and not state.scores
assert "Load a signal" in tab.summary_label.cget("text")
tab.destroy()
root.update()
root.destroy()
assert not errors, errors
''')


def test_app_data_invalidation_and_compare_scores_integration():
    run_gui_check('''
import time
import pandas as pd
from outlierlab.core.detectors.base import RunResult
from outlierlab.gui.app import App

app = App()
app.withdraw()
errors = []
app.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
data_tab = app.tab_frames["Data"]
scores_tab = app.tab_frames["Scores"]
data_tab.raw = pd.DataFrame({"x": range(30), "other": range(30), "labels": [0]*10+[1]+[0]*19},
                            index=pd.date_range("2026-01-01", periods=30, freq="min"))
data_tab.value_menu.configure(values=["x", "other"])
data_tab.value_menu.set("x")
data_tab.label_menu.configure(values=["(none)", "labels"])
data_tab.label_menu.set("labels")
data_tab.apply()
app.app_state.results = {"iforest": RunResult("iforest", "IForest", "anomaly", [(10, 10)])}
app.refresh_all()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    app.update()
    if app.app_state.scores.get("iforest") is not None and not scores_tab._pending:
        break
    time.sleep(.01)
assert app.app_state.scores["iforest"].f1 == 1
# Tolerance changes in Compare are picked up when Scores is activated.
app.app_state.results["iforest"].alarms = [(12, 12)]
app.tab_frames["Compare"]._on_tolerance(0)
app.tabs.set("Scores")
app._on_tab_changed()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    app.update()
    if not scores_tab._pending and "Tolerance: 0 samples" in scores_tab.summary_label.cget("text"):
        break
    time.sleep(.01)
assert app.app_state.scores["iforest"].found_events == 0
app.tab_frames["Compare"]._on_tolerance(3)
app._on_tab_changed()
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    app.update()
    if not scores_tab._pending and "Tolerance: 3 samples" in scores_tab.summary_label.cget("text"):
        break
    time.sleep(.01)
assert app.app_state.scores["iforest"].found_events == 1
# Changing the label selection must keep detector outputs.
data_tab.label_menu.set("(none)")
data_tab.apply()
assert "iforest" in app.app_state.results
# Changing the signal invalidates results and scores from the old signal.
data_tab.value_menu.set("other")
data_tab.apply()
assert not app.app_state.results and not app.app_state.scores
assert not scores_tab.tree.get_children()
app.app_state.results = {"iforest": RunResult("iforest", "IForest", "anomaly", [(10, 10)])}
data_tab.missing.set("drop")
data_tab.apply()
assert not app.app_state.results and not app.app_state.scores
app.tabs.set("Scores")
app._on_tab_changed()
assert "No detector results" in scores_tab.summary_label.cget("text")
app.destroy()
assert not errors, errors
''')
