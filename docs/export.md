# Exporting a session

The Export tab saves a portable snapshot through the same IO API used by
scripts. It is connected to the app as the seventh tab.

## Export from the GUI

1. Finish a detector run. If you changed the signal, seed or detector
   parameters afterward, rerun the detectors before exporting.
2. Open Export and wait for the session preview. Export is disabled while
   detectors are running or a preview is being prepared.
3. Select the optional reproduction script, environment details, pip freeze
   and comparison PNG. The JSON report is always included.
4. Inspect Summary, JSON or Python script. Copy preview copies the complete
   selected text, even when a long JSON preview is shortened on screen.
5. Choose a new or empty destination folder and click Export session.
6. After export finishes, run the generated script using the matching Python
   environment to verify the saved scores.

The preview captures detached data, events, settings and results. Export uses
that snapshot, so edits made in other tabs during writing cannot change the
saved analysis. If the current session changes, refresh its preview before
starting another export. The output timestamp is recorded when saving.

Preparation, environment capture and writing run in a worker thread. Errors
appear in the tab, and the controls become available for another attempt.
The destination rule prevents accidental overwrites. An export without any
detector results is allowed, and its summary identifies it as a data/settings
snapshot rather than a completed analysis.

The Python preview uses the same `reproduction_script()` function as the file
writer. It expects `report.json` beside it. This script reproduces the final
analysis snapshot; a chronological GUI action history is not recorded.

## Core API

`outlierlab.io.export` writes a portable session bundle without opening the
GUI. It uses the same scoring and plotting functions as the core API.

```python
from outlierlab.io.export import export_session

files = export_session(state, "exports/pump-session")
print(files["report.json"])
```

The destination must be a new or empty directory. Existing files are never
overwritten. The default bundle contains:

| File | Contents |
| --- | --- |
| `report.json` | Analysis signal, timestamps, settings, events, resolved detector parameters, results, scores and environment metadata |
| `reproduce_run.py` | Script that reruns completed detectors and verifies their event metrics against the report |
| `environment.txt` | Python, interpreter path, OS and relevant package versions |
| `pip_freeze.txt` | Output of `python -m pip freeze` from the exporting interpreter |
| `comparison.png` | Full-session signal and detector comparison figure |

The report always includes the exact analysis signal as JSON numbers, with
missing values represented as `null`. The signal is already preprocessed;
the reproduction script does not apply the missing-value policy again.
The original CSV path is provenance only. Move or share the whole bundle
without needing that original path.

Choose individual sidecars with keyword options. The report is always written:

```python
files = export_session(
    state,
    "exports/report-only",
    include_script=False,
    include_environment=False,
    include_pip_freeze=False,
    include_plot=False,
)
```

For an in-memory snapshot, call `build_report(state)`. To inspect versions
without exporting, call `capture_environment()`. All three functions are
available from `outlierlab.io.export`.

## Reproducing the analysis

Install the same OutlierLab code revision and dependency versions in a Python
environment. Development installations may leave local editable paths in
`pip_freeze.txt`; those paths must be replaced with the matching source
checkout or released package on another machine.

Run the script using that environment, from any working directory:

```sh
python /path/to/pump-session/reproduce_run.py
```

It reads the adjacent `report.json`, restores the analysis signal, events and
seed, and runs each previously completed detector using its saved parameters.
Disabled detectors, detectors without results and non-completed runs are not
replayed. Failed, timed-out and cancelled statuses remain in the report with
`null` event scores. Optional per-point scores that are not finite also export
as `null`.

The script writes `reproduced_scores.json` and compares event metrics with the
original report. A mismatch raises an error instead of claiming success.
Runtime is recorded for context but is not compared because it depends on
the machine. Each rerun replaces only `reproduced_scores.json`.

## Export requirements and limits

Pass the state for the finished run before changing the signal, seed or
detector parameters. The current runner does not retain a historical settings
snapshot, so the exporter cannot infer the configuration used by an earlier
run after those fields have been edited. Event scores are always recomputed
through `score()` rather than trusting a cached scores table.

Every stored result must have its enabled detector configuration with the
same registry key and family. Duplicate keys and out-of-range intervals are
rejected. Registered detector defaults are resolved at export time and saved
explicitly. Custom detector implementations are not bundled with the script.
The caller must keep state stable while `build_report()` captures it; the
report and image then use that detached snapshot.

Content is prepared before any files are written. A failed `pip freeze`
capture raises an error; exclude that sidecar explicitly if pip is unavailable.
The GUI should call the exporter from a worker thread because environment
capture and image rendering can take time. PDF summaries and a full GUI
action history are outside this core export feature.

Run the export checks with:

```sh
python -m pytest tests/test_export.py
python -m pytest tests/test_export_tab.py
```

The GUI integration check loads a CSV, marks events, runs PELT and IForest
through Run, exports through Export, removes the source CSV, moves the bundle
and verifies that the generated script reproduces the GUI scores.
