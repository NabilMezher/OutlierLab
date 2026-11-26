import copy
from dataclasses import asdict
import json
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import score
from outlierlab.core.registry import make_default_spec
from outlierlab.core.runner import create_detector
from outlierlab.core.state import ComparatorState
from outlierlab.io import export
from outlierlab.io.export import build_report, capture_environment, export_session


@pytest.fixture(scope="module")
def completed_session():
    rng = np.random.default_rng(17)
    values = rng.normal(0, 0.1, 80)
    values[40:] += 4
    values[10:13] += 6
    data = pd.DataFrame(
        {"sensor": values},
        index=pd.date_range("2026-10-25", periods=80, freq="5min", tz="Europe/Paris"),
    )
    specs = [make_default_spec("pelt"), make_default_spec("iforest")]
    specs[0].params.update(model="l2", pen=5, jump=1)
    specs[1].params.update(n_estimators=10, window=5, contamination=0.1)
    state = ComparatorState(
        data=data, value_col="sensor", source_path="/no-longer-available/original.csv",
        seed=17, tolerance=3,
        events=[Event(40, 40, "change"), Event(10, 12, note="Pump arrêt — علامه")],
        detectors=specs + [make_default_spec("knn", enabled=False)],
    )
    state.results = {
        spec.key: create_detector(spec.key).fit_detect(state.series, seed=state.seed, **spec.params)
        for spec in specs
    }
    return state


@pytest.fixture
def session(completed_session):
    return copy.deepcopy(completed_session)


def minimal_export(state, folder):
    return export_session(
        state, folder, include_plot=False, include_environment=False, include_pip_freeze=False,
    )


def run_script(folder, cwd):
    return subprocess.run(
        [sys.executable, str(folder / "reproduce_run.py")],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )


def test_report_round_trip_and_scores_use_core_not_cached_state(session):
    session.scores = {"pelt": {"f1": -100}}
    report = build_report(session)
    assert json.loads(json.dumps(report, allow_nan=False)) == report
    assert report["schema_version"] == 1
    assert report["settings"]["seed"] == 17
    assert report["settings"]["tolerance"] == 3
    assert report["settings"]["missing_policy"] == "interpolate"
    assert report["events"] == [asdict(event) for event in session.events]
    assert report["signal"]["values"] == session.series.tolist()
    assert report["signal"]["timezone"] == "Europe/Paris"
    assert len(report["signal"]["timestamps"]) == 80
    assert report["results"]["pelt"]["alarms"] == [list(a) for a in session.results["pelt"].alarms]
    for key, result in session.results.items():
        assert report["scores"][key] == asdict(score(result, session.events, session.tolerance))
    assert session.scores == {"pelt": {"f1": -100}}


@pytest.mark.parametrize("freeze_output", [None, "numpy @ file:///conda-build/numpy/work\n"])
def test_default_bundle_has_all_files_and_real_environment(session, tmp_path, monkeypatch, freeze_output):
    if freeze_output is not None:
        monkeypatch.setattr(export, "_pip_freeze", lambda: freeze_output.encode("utf-8"))
    paths = export_session(session, tmp_path / "bundle")
    assert set(paths) == {
        "report.json", "reproduce_run.py", "environment.txt", "pip_freeze.txt", "comparison.png",
    }
    report = json.loads(paths["report.json"].read_text(encoding="utf-8"))
    assert report["events"][1]["note"] == session.events[1].note
    assert paths["comparison.png"].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    freeze_lines = paths["pip_freeze.txt"].read_text(encoding="utf-8").splitlines()
    assert any(line.startswith(("numpy==", "numpy @ ")) for line in freeze_lines)
    assert "Python:" in paths["environment.txt"].read_text(encoding="utf-8")
    assert sys.executable in paths["environment.txt"].read_text(encoding="utf-8")


def test_reproduction_reruns_real_detectors_after_bundle_is_moved(session, tmp_path):
    original = tmp_path / "original export"
    minimal_export(session, original)
    folder = original.rename(tmp_path / "moved bundle é")
    completed = run_script(folder, cwd=tmp_path)
    assert completed.returncode == 0, completed.stderr
    assert "Reproduced scores for 2" in completed.stdout
    expected = build_report(session)["scores"]
    actual = json.loads((folder / "reproduced_scores.json").read_text(encoding="utf-8"))
    assert actual == {"scores": expected, "skipped": {}}


def test_script_reports_mismatches_instead_of_claiming_success(session, tmp_path):
    folder = tmp_path / "bundle"
    minimal_export(session, folder)
    path = folder / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["scores"]["pelt"]["f1"] = -1
    path.write_text(json.dumps(report), encoding="utf-8")
    completed = run_script(folder, tmp_path)
    assert completed.returncode != 0
    assert "Reproduced scores differ" in completed.stderr
    assert (folder / "reproduced_scores.json").is_file()


def test_failed_timed_out_and_cancelled_runs_are_saved_and_skipped(session, tmp_path):
    for key, status in [("ecod", "failed"), ("lof", "timed_out"), ("ocsvm", "cancelled")]:
        session.detectors.append(make_default_spec(key))
        session.results[key] = RunResult(key, key, "anomaly", status=status, error="reason")
    # An enabled detector with no result has not run and must not be replayed.
    session.detectors.append(make_default_spec("window"))
    folder = tmp_path / "bundle"
    paths = minimal_export(session, folder)
    report = json.loads(paths["report.json"].read_text(encoding="utf-8"))
    for key in ("ecod", "lof", "ocsvm"):
        assert report["scores"][key] is None
        assert report["results"][key]["error"] == "reason"
    completed = run_script(folder, tmp_path)
    assert completed.returncode == 0, completed.stderr
    actual = json.loads((folder / "reproduced_scores.json").read_text(encoding="utf-8"))
    assert set(actual["scores"]) == {"pelt", "iforest"}
    assert actual["skipped"] == {"ecod": "failed", "lof": "timed_out", "ocsvm": "cancelled"}


def test_report_captures_resolved_defaults_without_mutating_inputs(session):
    session.detectors[0].params = {"pen": np.int64(8)}
    before = copy.deepcopy(session.detectors[0])
    report = build_report(session)
    assert report["detectors"][0]["params"]["pen"] == 8
    assert report["detectors"][0]["params"]["model"] == "rbf"
    assert session.detectors[0] == before
    session.events[0].note = "changed later"
    session.detectors[0].params["pen"] = 99
    assert report["events"][0]["note"] == ""
    assert report["detectors"][0]["params"]["pen"] == 8


def test_minimal_report_only_and_empty_existing_folder(session, tmp_path):
    folder = tmp_path / "empty"
    folder.mkdir()
    paths = export_session(
        session, folder, include_script=False, include_plot=False,
        include_environment=False, include_pip_freeze=False,
    )
    assert set(paths) == {"report.json"}
    assert list(folder.iterdir()) == [paths["report.json"]]


def test_nonempty_destination_is_never_overwritten(session, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("Keep this", encoding="utf-8")
    with pytest.raises(FileExistsError, match="empty"):
        export_session(session, tmp_path)
    assert path.read_text(encoding="utf-8") == "Keep this"
    assert list(tmp_path.iterdir()) == [path]
    with pytest.raises(FileExistsError):
        export_session(session, path)


@pytest.mark.parametrize("failure", [subprocess.TimeoutExpired("pip", 30),
                                   subprocess.CalledProcessError(1, "pip"), OSError("pip missing")])
def test_pip_capture_failure_leaves_no_bundle(session, tmp_path, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(export.subprocess, "run", fail)
    folder = tmp_path / "bundle"
    with pytest.raises(RuntimeError, match="pip freeze"):
        export_session(session, folder)
    assert not folder.exists()


def test_missing_values_and_nonfinite_point_scores_become_json_null(session):
    session.data.iloc[0, 0] = np.nan
    session.results["iforest"].scores[:3] = [np.nan, np.inf, -np.inf]
    report = build_report(session)
    assert report["signal"]["values"][0] is None
    assert report["results"]["iforest"]["scores"][:3] == [None, None, None]
    json.dumps(report, allow_nan=False)


def test_no_results_and_positional_index_can_be_reproduced(tmp_path):
    state = ComparatorState(data=pd.DataFrame({"x": [0.12345678912345678, np.nan]}), value_col="x")
    folder = tmp_path / "bundle"
    minimal_export(state, folder)
    report = build_report(state)
    assert report["signal"]["values"][0] == state.series.iloc[0]
    assert report["signal"]["timestamps"] is None
    assert run_script(folder, tmp_path).returncode == 0


@pytest.mark.parametrize("value", [-1, True, 1.5])
@pytest.mark.parametrize("name", ["seed", "tolerance"])
def test_invalid_settings_are_rejected(session, name, value):
    setattr(session, name, value)
    with pytest.raises(ValueError, match=name):
        build_report(session)


@pytest.mark.parametrize("data", [None, pd.DataFrame({"sensor": []}),
                                  pd.DataFrame({"sensor": ["bad"]}),
                                  pd.DataFrame({"sensor": [np.inf]})])
def test_invalid_signal_is_rejected(session, data):
    session.data = data
    with pytest.raises(ValueError, match="signal"):
        build_report(session)


def test_invalid_ranges_and_event_kinds_are_rejected(session):
    session.events.append(Event(80, 80))
    with pytest.raises(ValueError, match="within"):
        build_report(session)
    session.events[-1] = Event(1, 1, "unknown")
    with pytest.raises(ValueError, match="kind"):
        build_report(session)


def test_missing_disabled_duplicate_and_mismatched_configs_are_rejected(session):
    session.detectors[0].enabled = False
    with pytest.raises(ValueError, match="enabled"):
        build_report(session)
    session.detectors.pop(0)
    with pytest.raises(ValueError, match="configuration"):
        build_report(session)
    session.detectors = [make_default_spec("pelt"), make_default_spec("pelt")]
    with pytest.raises(ValueError, match="Duplicate"):
        build_report(session)


@pytest.mark.parametrize("field,value", [("detector_key", "wrong"), ("family", "anomaly"),
                                        ("status", "unknown"), ("runtime_s", np.nan)])
def test_invalid_result_metadata_is_rejected(session, field, value):
    setattr(session.results["pelt"], field, value)
    with pytest.raises(ValueError):
        build_report(session)


def test_invalid_score_length_and_nonfinite_params_are_rejected_before_writing(session, tmp_path):
    session.results["iforest"].scores = np.array([1, 2])
    with pytest.raises(ValueError, match="one value"):
        build_report(session)
    session.results["iforest"].scores = None
    session.detectors[0].params["pen"] = np.nan
    with pytest.raises(ValueError):
        minimal_export(session, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_environment_records_missing_distributions_as_null(monkeypatch):
    def missing(name):
        raise export.metadata.PackageNotFoundError(name)
    monkeypatch.setattr(export.metadata, "version", missing)
    environment = capture_environment()
    assert environment["python"]
    assert environment["packages"] == dict.fromkeys(export.PACKAGE_NAMES)


def test_plot_and_report_share_snapshot_if_state_changes_during_export(session, tmp_path, monkeypatch):
    from outlierlab.core import plotting

    original_builder = plotting.build_comparison_figure
    captured = {}

    def change_state():
        session.data.iloc[:, 0] = 100
        session.events.clear()
        session.results.clear()
        session.tolerance = 99
        return b"frozen environment\n"

    def capture_figure(series, results, events, tolerance):
        captured.update(values=series.tolist(), keys=list(results), events=events, tolerance=tolerance)
        return original_builder(series, results, events, tolerance)

    monkeypatch.setattr(export, "_pip_freeze", change_state)
    monkeypatch.setattr(plotting, "build_comparison_figure", capture_figure)
    paths = export_session(session, tmp_path / "bundle")
    report = json.loads(paths["report.json"].read_text(encoding="utf-8"))
    assert captured["values"] == report["signal"]["values"]
    assert captured["keys"] == list(report["results"])
    assert [asdict(event) for event in captured["events"]] == report["events"]
    assert captured["tolerance"] == report["settings"]["tolerance"] == 3
