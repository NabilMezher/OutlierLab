# Exporting a session

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
```
