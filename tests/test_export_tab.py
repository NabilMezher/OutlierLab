import copy
from dataclasses import asdict
import json
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
from outlierlab.core.registry import make_default_spec
from outlierlab.core.state import ComparatorState
from outlierlab.gui.export_tab import EXPORT_OPTIONS, _manifest, _prepare_preview, _worker
from outlierlab.io.export import reproduction_script


@pytest.fixture
def session():
    return ComparatorState(
        data=pd.DataFrame({"sensor": range(30)}), value_col="sensor", seed=42, tolerance=3,
        events=[Event(10, 10, "change", "Marked event")], detectors=[make_default_spec("pelt")],
        results={"pelt": RunResult("pelt", "PELT", "change", [(12, 12)])},
    )


def test_preview_uses_export_report_and_canonical_scores(session):
    preview = _prepare_preview(copy.deepcopy(session))
    assert json.loads(preview.json_text) == preview.report
    assert preview.report["scores"]["pelt"] == asdict(score(session.results["pelt"], session.events, 3))
    assert preview.script_text == reproduction_script()
    session.data.iloc[0, 0] = 999
    session.events[0].note = "Changed"
    session.detectors[0].params["pen"] = 999
    assert preview.report["signal"]["values"][0] == 0
    assert preview.state.events[0].note == "Marked event"
    assert preview.state.detectors[0].params["pen"] != 999


@pytest.mark.parametrize("selected", [[], ["include_script"], ["include_environment", "include_plot"],
                                     [key for key, _, _ in EXPORT_OPTIONS]])
def test_manifest_keeps_report_and_respects_file_options(selected):
    options = {key: key in selected for key, _, _ in EXPORT_OPTIONS}
    assert _manifest(options) == ["report.json", *[name for key, _, name in EXPORT_OPTIONS if key in selected]]


def test_worker_handles_preview_export_errors_and_shutdown(session, tmp_path):
    requests, responses = queue.Queue(), queue.Queue()
    worker = threading.Thread(target=_worker, args=(requests, responses), daemon=True)
    worker.start()
    options = dict.fromkeys((key for key, _, _ in EXPORT_OPTIONS), False)
    requests.put(("preview", 1, copy.deepcopy(session), None, None))
    kind, revision, preview, error = responses.get(timeout=10)
    assert (kind, revision, error) == ("preview", 1, "")
    requests.put(("export", 2, preview.state, tmp_path / "bundle", options))
    kind, revision, files, error = responses.get(timeout=10)
    assert (kind, revision, error) == ("export", 2, "")
    assert set(files) == {"report.json"}
    requests.put(("export", 3, preview.state, tmp_path / "bundle", options))
    kind, revision, files, error = responses.get(timeout=10)
    assert revision == 3 and files is None and "empty" in error
    requests.put(None)
    worker.join(timeout=10)
    assert not worker.is_alive()


def run_gui_check(code, tmp_path):
    if sys.platform not in ("win32", "darwin") and not os.environ.get("DISPLAY"):
        pytest.skip("Tk checks need a display; export worker tests run headlessly")
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)], capture_output=True,
        text=True, encoding="utf-8", errors="replace", timeout=90,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "Exception in Tkinter callback" not in completed.stderr
    assert "Exception ignored in" not in completed.stderr


def test_export_widget_options_preview_copy_errors_and_layout(tmp_path):
    run_gui_check('''
import json, sys, time
from pathlib import Path
from types import SimpleNamespace
import customtkinter as ctk
import pandas as pd
from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.registry import make_default_spec
from outlierlab.core.state import ComparatorState
from outlierlab.gui.export_tab import ExportTab, PREVIEW_LIMIT

folder = Path(sys.argv[1])
root = ctk.CTk()
root.withdraw()
errors = []
root.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
state = ComparatorState()
runner_state = {"running": False}
runner = SimpleNamespace(is_running=lambda: runner_state["running"])
app = SimpleNamespace(app_state=state, tab_frames={"Run": SimpleNamespace(runner=runner)})
tab = ExportTab(root, app)
tab.pack(fill="both", expand=True)
assert tab.export_button.cget("state") == "disabled"
def wait(predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        root.update()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError(tab.status_label.cget("text"))
state.data = pd.DataFrame({"sensor": range(30)})
state.value_col = "sensor"
state.detectors = [make_default_spec("pelt")]
state.events = [Event(10, 10, "change")]
state.results = {"pelt": RunResult("pelt", "PELT", "change", [(12, 12)])}
tab.refresh()
wait(lambda: tab._preview is not None and not tab._preview_pending)
assert "report.json" in tab.preview_box.get("1.0", "end")
tab._start_export()
assert "Choose" in tab.status_label.cget("text")
# Copy the complete selected preview without altering the user's clipboard.
copied = {}
tab.clipboard_clear = lambda: copied.clear()
tab.clipboard_append = lambda text: copied.update(text=text)
tab.preview_mode.set("JSON")
tab._render_preview()
tab._copy_preview()
assert json.loads(copied["text"])["settings"]["seed"] == 42
tab._preview.json_text = "x" * (PREVIEW_LIMIT + 100)
tab._render_preview()
assert "Preview shortened" in tab.preview_box.get("1.0", "end")
tab._copy_preview()
assert len(copied["text"]) == PREVIEW_LIMIT + 100
tab.refresh(force=True)
wait(lambda: tab._preview is not None and not tab._preview_pending)
tab.preview_mode.set("Python script")
tab._render_preview()
tab._copy_preview()
assert "def main()" in copied["text"]
# Busy detectors prevent exporting an older result snapshot.
runner_state["running"] = True
tab.refresh()
assert tab.export_button.cget("state") == "disabled"
runner_state["running"] = False
tab.refresh()
wait(lambda: not tab._preview_pending)
assert tab.export_button.cget("state") == "normal"
# A nonempty folder is rejected without changing its existing files.
occupied = folder / "occupied"
occupied.mkdir()
(occupied / "keep.txt").write_text("Keep", encoding="utf-8")
tab.destination_entry.insert(0, str(occupied))
tab._start_export()
wait(lambda: not tab._busy)
assert "Export failed" in tab.status_label.cget("text")
assert list(occupied.iterdir()) == [occupied / "keep.txt"]
# Optional sidecars can all be excluded; report.json remains mandatory.
for variable in tab._include_vars.values(): variable.set(False)
tab.preview_mode.set("Summary")
tab._render_preview()
assert "reproduce_run.py" not in tab.preview_box.get("1.0", "end")
tab.destination_entry.delete(0, "end")
tab.destination_entry.insert(0, str(folder / "report only"))
tab._start_export()
wait(lambda: not tab._busy)
assert set(tab._last_paths) == {"report.json"}
assert "Exported 1 files" in tab.status_label.cget("text")
for geometry in ("1180x720", "900x650"):
    root.geometry(geometry)
    root.deiconify()
    root.update()
    for widget in (tab.export_button, tab.copy_button, tab.preview_box):
        left = widget.winfo_rootx() - root.winfo_rootx()
        assert 0 <= left < root.winfo_width()
        assert left + widget.winfo_width() <= root.winfo_width()
        assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
state.data = None
tab.refresh()
assert tab._preview is None and tab.export_button.cget("state") == "disabled"
tab.destroy()
root.update()
root.destroy()
assert not errors, errors
''', tmp_path)


def test_full_gui_run_export_and_reproduction_preserve_snapshot(tmp_path):
    run_gui_check('''
from dataclasses import asdict
import json, subprocess, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from outlierlab.core.events import Event
from outlierlab.core.registry import make_default_spec
from outlierlab.gui.app import App, TAB_NAMES
import outlierlab.gui.data_tab as data_module

folder = Path(sys.argv[1])
rng = np.random.default_rng(42)
values = rng.normal(0, .1, 80)
values[40:] += 4
values[10:13] += 6
csv = folder / "original.csv"
pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=80, freq="min"), "sensor": values}).to_csv(csv, index=False)
app = App()
app.withdraw()
errors = []
app.report_callback_exception = lambda kind, value, tb: errors.append(str(value))
assert set(app.tab_frames) == set(TAB_NAMES)
data_module.filedialog.askopenfilename = lambda **kwargs: str(csv)
app.tab_frames["Data"].open_csv()
app.tab_frames["Events"].add(Event(40, 40, "change"))
app.tab_frames["Events"].add(Event(10, 12))
specs = [make_default_spec("pelt"), make_default_spec("iforest")]
specs[0].params.update(model="l2", pen=5, jump=1)
specs[1].params.update(n_estimators=10, window=5, contamination=.1)
app.app_state.detectors = specs
app.refresh_all()
run_tab = app.tab_frames["Run"]
export_tab = app.tab_frames["Export"]
scores_tab = app.tab_frames["Scores"]
run_tab._start_run()
def wait(predicate):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        app.update()
        if predicate(): return
        time.sleep(.01)
    raise AssertionError(export_tab.status_label.cget("text"))
wait(lambda: not run_tab.runner.is_running() and set(app.app_state.results) == {"pelt", "iforest"}
     and not scores_tab._pending and set(app.app_state.scores) == {"pelt", "iforest"}
     and export_tab._preview is not None and not export_tab._preview_pending
     and len(export_tab._preview.report["results"]) == 2)
gui_scores = {key: asdict(value) for key, value in app.app_state.scores.items()}
destination = folder / "session export"
export_tab.destination_entry.insert(0, str(destination))
export_tab._start_export()
assert export_tab._busy
# Further GUI edits must not mutate an export already in progress.
app.app_state.events.clear()
app.app_state.seed = 99
app.app_state.tolerance = 0
app.refresh_all()
wait(lambda: not export_tab._busy)
assert "Exported 5 files" in export_tab.status_label.cget("text")
report = json.loads((destination / "report.json").read_text(encoding="utf-8"))
assert report["scores"] == gui_scores
assert report["settings"]["seed"] == 42 and report["settings"]["tolerance"] == 6
assert len(report["events"]) == 2
assert (destination / "comparison.png").read_bytes().startswith(b"\\x89PNG\\r\\n\\x1a\\n")
app.destroy()
assert not errors, errors
csv.unlink()
moved = destination.rename(folder / "moved session")
completed = subprocess.run([sys.executable, str(moved / "reproduce_run.py")], cwd=folder,
                           capture_output=True, text=True, timeout=30)
assert completed.returncode == 0, completed.stderr
reproduced = json.loads((moved / "reproduced_scores.json").read_text(encoding="utf-8"))
assert reproduced["scores"] == gui_scores
''', tmp_path)
