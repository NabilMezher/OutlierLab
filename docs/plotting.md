# Comparison figures

`outlierlab.core.plotting.build_comparison_figure()` builds a Matplotlib
`Figure` for the Compare tab and image exports. It runs without Tkinter,
CustomTkinter or `pyplot`, and does not change the Matplotlib backend.

Pass the same cleaned Series used by the detectors, the results mapping,
the user-marked events and the scoring tolerance. With the shared state:

```python
from outlierlab.core.plotting import build_comparison_figure

figure = build_comparison_figure(
    state.series,
    state.results,
    state.events,
    state.tolerance,
)
figure.savefig("comparison.png", dpi=150)
```

The signal appears above one row per detector. Marked anomalies are orange
and marked changes are purple. Relevant annotations also appear faintly in
each completed detector's row. Matched alarms are green and unmatched alarms
are red. Colors come from the same `match_alarms()` used by the scorer; a
duplicate or broad alarm follows the one-to-one rules in [Event scoring](metrics.md).
Failed, timed-out and cancelled runs display their status without classified
alarms. Completed runs that found nothing display “No alarms”.

All horizontal coordinates use sample positions, even when the Series has a
DatetimeIndex. Event and alarm endpoints are inclusive. A point appears as
a vertical line; an interval fills its sample cells. Missing values remain
gaps in the signal. Empty, nonnumeric and infinite-valued signals are rejected,
as are event and completed-alarm intervals outside the series.

Use `detector_keys` to select and order the visible rows, and `sample_range`
for an inclusive zoom range:

```python
figure = build_comparison_figure(
    state.series,
    state.results,
    state.events,
    state.tolerance,
    detector_keys=["pelt", "iforest"],  # keys must exist in state.results
    sample_range=(100, 250),  # requires at least 251 samples
)
```

Omit `detector_keys` to preserve the results mapping's order. An empty list
shows the signal alone. Zooming changes the view only: matching always uses
the full event and alarm lists, so panning cannot change an alarm's color.

For GUI integration, attach the returned figure to `FigureCanvasTkAgg` in
the GUI layer. For a headless script, call `savefig()` directly. The caller
owns the figure's lifetime and can release it after use; this builder does
not register figures with `pyplot`.

Run the focused tests with:

```sh
python -m pytest tests/test_plotting.py
```
