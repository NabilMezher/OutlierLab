"""Portable session exports and a headless reproduction script."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata
from io import BytesIO
import json
from numbers import Integral
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

import numpy as np
import pandas as pd

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import score
from outlierlab.core.registry import default_params, get_detector_meta
from outlierlab.core.state import ComparatorState

PACKAGE_NAMES = (
    "outlierlab", "numpy", "pandas", "matplotlib", "customtkinter",
    "scikit-learn", "pyod", "ruptures",
)


def capture_environment() -> dict[str, Any]:
    """Describe the interpreter, OS and installed analysis package versions."""
    versions = {}
    for name in PACKAGE_NAMES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return {
        "python": platform.python_version(),
        "executable": sys.executable,
        "platform": platform.platform(),
        "packages": versions,
    }


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Cannot export a value of type {type(value).__name__}")


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(
        value, indent=2, ensure_ascii=False, allow_nan=False, default=_json_default,
    ) + "\n").encode("utf-8")


def _nonnegative_integer(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return int(value)


def _check_interval(start: int, end: int, length: int) -> None:
    start = _nonnegative_integer(start, "Interval start")
    end = _nonnegative_integer(end, "Interval end")
    if end < start or end >= length:
        raise ValueError("Event and alarm intervals must lie within the exported signal")


def build_report(state: ComparatorState) -> dict[str, Any]:
    """Snapshot the current analysis and recompute scores through the core API.

    Pass the state used for the finished run, before changing its signal,
    seed or detector parameters. Current annotations and tolerance are used
    to recompute event scores. The current runner does not
    retain historical settings. The signal snapshot is already preprocessed;
    reproduction must not apply the missing-value policy a second time.

    Only registered detectors can be reproduced. Every stored result needs
    its enabled DetectorSpec, with a matching key and family. Disabled or
    not-yet-run detectors are recorded but not replayed. Non-completed runs
    have JSON-null scores. The returned mapping contains only JSON values.
    """
    try:
        series = state.series
    except (RuntimeError, KeyError) as exc:
        raise ValueError("Load an analysis signal before exporting") from exc
    if not isinstance(series, pd.Series) or series.empty:
        raise ValueError("The analysis signal must be a non-empty pandas Series")
    try:
        values = series.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise ValueError("The analysis signal must contain numeric values") from exc
    if np.isinf(values).any():
        raise ValueError("The analysis signal must not contain infinite values")
    seed = _nonnegative_integer(state.seed, "seed")
    tolerance = _nonnegative_integer(state.tolerance, "tolerance")
    if state.missing_policy not in ("interpolate", "drop", "gaps"):
        raise ValueError(f"Unknown missing-value policy: {state.missing_policy!r}")
    for event in state.events:
        _check_interval(event.start, event.end, len(series))
        if event.kind not in ("anomaly", "change"):
            raise ValueError(f"Unknown event kind: {event.kind!r}")

    specs = {}
    detectors = []
    for spec in state.detectors:
        if spec.key in specs:
            raise ValueError(f"Duplicate detector configuration: {spec.key}")
        specs[spec.key] = spec
        # Capture all defaults now, so a later registry update cannot silently
        # change the exported run's parameters.
        detectors.append({
            **asdict(spec), "params": {**default_params(spec.key), **spec.params},
        })

    results = {}
    scores = {}
    for key, result in state.results.items():
        if key not in specs or not specs[key].enabled:
            raise ValueError(f"Result {key!r} needs its enabled detector configuration")
        if result.detector_key != key or result.family != get_detector_meta(key).family:
            raise ValueError(f"Result {key!r} does not match its detector configuration")
        if result.status not in ("done", "failed", "timed_out", "cancelled"):
            raise ValueError(f"Unknown run status: {result.status!r}")
        if not np.isfinite(result.runtime_s) or result.runtime_s < 0:
            raise ValueError("Runtime must be finite and non-negative")
        for start, end in result.alarms:
            _check_interval(start, end, len(series))
        point_scores = None
        if result.scores is not None:
            array = np.asarray(result.scores, dtype=float)
            if array.shape != (len(series),):
                raise ValueError("Per-point scores must have one value per signal sample")
            point_scores = [float(x) if np.isfinite(x) else None for x in array]
        results[key] = {**asdict(result), "scores": point_scores}
        scores[key] = (
            asdict(score(result, state.events, tolerance)) if result.status == "done" else None
        )

    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": state.source_path,
        "settings": {
            "value_col": state.value_col, "missing_policy": state.missing_policy,
            "seed": seed, "tolerance": tolerance,
        },
        "signal": {
            "values": [float(x) if not np.isnan(x) else None for x in values],
            "timestamps": (
                [timestamp.isoformat() for timestamp in series.index]
                if isinstance(series.index, pd.DatetimeIndex) else None
            ),
            "timezone": str(series.index.tz) if isinstance(series.index, pd.DatetimeIndex)
            and series.index.tz is not None else None,
        },
        "events": [asdict(event) for event in state.events],
        "detectors": detectors,
        "results": results,
        "scores": scores,
        "environment": capture_environment(),
    }
    # Normalize numpy values and reject unsupported/non-finite parameter
    # values before creating any files. This also detaches the snapshot.
    return json.loads(_json_bytes(report))


_REPRODUCE_SCRIPT = '''"""Rerun completed OutlierLab detectors using the adjacent report.json.

Install OutlierLab and the captured dependency versions first. Run this
script from any working directory. Runtime is intentionally not compared.
"""
from dataclasses import asdict
import json
from pathlib import Path

import pandas as pd

from outlierlab.core.events import Event
from outlierlab.core.metrics import score
from outlierlab.core.runner import create_detector
from outlierlab.core.seeding import set_global_seed


def main():
    folder = Path(__file__).resolve().parent
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    if report["schema_version"] != 1:
        raise ValueError("Unsupported OutlierLab report schema")
    settings = report["settings"]
    signal = report["signal"]
    # Values already contain the analysis signal after preprocessing.
    series = pd.Series(signal["values"], dtype=float, name=settings["value_col"])
    if signal["timestamps"] is not None:
        index = pd.to_datetime(signal["timestamps"], utc=signal["timezone"] is not None)
        series.index = index.tz_convert(signal["timezone"]) if signal["timezone"] else index
    events = [Event(**event) for event in report["events"]]
    specs = {spec["key"]: spec for spec in report["detectors"]}
    actual_scores = {}
    skipped = {}
    for key, original in report["results"].items():
        if original["status"] != "done":
            skipped[key] = original["status"]
            continue
        set_global_seed(settings["seed"])
        result = create_detector(key).fit_detect(
            series, seed=settings["seed"], **specs[key]["params"]
        )
        actual_scores[key] = asdict(score(result, events, settings["tolerance"]))
    expected_scores = {key: value for key, value in report["scores"].items() if value is not None}
    output = {"scores": actual_scores, "skipped": skipped}
    (folder / "reproduced_scores.json").write_text(
        json.dumps(output, indent=2, allow_nan=False) + "\\n", encoding="utf-8"
    )
    if actual_scores != expected_scores:
        raise RuntimeError(
            "Reproduced scores differ from report.json. Check the saved data, "
            "settings and dependency versions. See reproduced_scores.json."
        )
    print(f"Reproduced scores for {len(actual_scores)} completed detector(s).")
    if skipped:
        print(f"Skipped {len(skipped)} non-completed run(s); their statuses remain in report.json.")


if __name__ == "__main__":
    main()
'''


def _pip_freeze() -> bytes:
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True, text=True, check=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise RuntimeError("Could not capture pip freeze; no export was written") from exc
    return completed.stdout.encode("utf-8")


def export_session(
    state: ComparatorState,
    destination: str | Path,
    *,
    include_script: bool = True,
    include_environment: bool = True,
    include_pip_freeze: bool = True,
    include_plot: bool = True,
) -> dict[str, Path]:
    """Write a session bundle into a new or empty folder, returning file paths.

    Always write report.json. Optional outputs are reproduce_run.py,
    environment.txt, pip_freeze.txt and comparison.png. All content is
    prepared before writing, so serialization, plotting or environment
    capture failures cannot leave a misleading report. Existing files are
    never overwritten. Call from a worker thread when used by the GUI.
    """
    folder = Path(destination)
    if folder.exists() and (not folder.is_dir() or any(folder.iterdir())):
        raise FileExistsError("Choose a new or empty export folder")
    report = build_report(state)
    payloads = {"report.json": _json_bytes(report)}
    if include_script:
        payloads["reproduce_run.py"] = _REPRODUCE_SCRIPT.encode("utf-8")
    if include_environment:
        environment = report["environment"]
        text = (
            f"Python: {environment['python']}\n"
            f"Executable: {environment['executable']}\n"
            f"Platform: {environment['platform']}\n\nPackages:\n"
        )
        text += "".join(f"{name}=={version}\n" for name, version in environment["packages"].items())
        payloads["environment.txt"] = text.encode("utf-8")
    if include_pip_freeze:
        payloads["pip_freeze.txt"] = _pip_freeze()
    if include_plot:
        from outlierlab.core.plotting import build_comparison_figure

        # Use the same frozen snapshot as report.json, even if the caller
        # changes the shared state while pip freeze or rendering is running.
        series = pd.Series(
            report["signal"]["values"], dtype=float, name=report["settings"]["value_col"],
        )
        results = {
            key: RunResult(**{**result, "scores": None})
            for key, result in report["results"].items()
        }
        events = [Event(**event) for event in report["events"]]
        figure = build_comparison_figure(series, results, events, report["settings"]["tolerance"])
        try:
            with BytesIO() as buffer:
                figure.savefig(buffer, format="png", dpi=150)
                payloads["comparison.png"] = buffer.getvalue()
        finally:
            figure.clear()
    folder.mkdir(parents=True, exist_ok=True)
    paths = {}
    try:
        for name, content in payloads.items():
            path = folder / name
            with path.open("xb") as stream:
                paths[name] = path
                stream.write(content)
    except OSError:
        for path in paths.values():
            path.unlink(missing_ok=True)
        raise
    return paths
