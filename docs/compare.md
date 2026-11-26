# Compare tab

Compare displays the analysis signal above the detector results. It embeds
the same core comparison figure that image exports use. Signal loading and
event annotation belong to the Data and Events tabs; Compare reads their
shared state and the results produced by Run.

## Inspect results

After loading a signal, marking events and running detectors, open Compare.
Green alarms matched a marked event; red alarms were unmatched. Marked
anomalies are orange, and marked changes are purple. Failed, timed-out and
cancelled detector runs display their status and remain unscored.

Use the detector checkboxes to select the visible rows. Show all and Hide all
change visibility together. Hiding a detector does not remove its results or
exclude it from scoring. With no detector rows visible, the signal and marked
events remain available. Scroll the plot vertically when there are many rows.

The tolerance slider changes the number of samples accepted on either side
of an event. It updates the shared tolerance and recomputes event scores via
the core `score()` function. It also recolors alarms using the core matching
rules. Event types must match the detector family. See [Event scoring](metrics.md)
for interval conventions, duplicate alarms and delay definitions.

Without marked events, unmatched alarms cannot establish detector quality;
the tab displays a reminder to annotate ground truth. With a signal but no
results, it displays the signal and directs the user to Run. Missing signals
or invalid result/event intervals produce a message instead of a crash.

## Zoom and pan

Drag across the overview strip at the bottom to select a sample range. Move
or resize the highlighted selection to inspect another range. The toolbar
also provides Matplotlib's pan, rectangle zoom and navigation controls.
Full range restores the complete signal.

Zoom changes only the view. Matching and scoring always use the complete
signal's event and alarm lists. Zoom and checkbox selections survive tolerance
updates and normal refreshes. Replacing the loaded DataFrame or changing its
value column resets the view to the full signal.

All horizontal coordinates are sample positions, independent of timestamp
spacing. The displayed range includes both endpoint samples.

## Integration and responsiveness

`App` registers the tab as `app.tab_frames["Compare"]`. Call `app.refresh_all()`
after changing `app.app_state` so the tab receives new data, events or results.
Compare writes completed detectors' `Score` objects to `state.scores` and
omits non-completed runs. Cached scores are cleared while a new view is being
prepared. Accepted results refresh the Scores and Export views when those
views are registered.

The tab captures detached inputs before preparing scores and figures on one
daemon worker. New requests replace queued requests, and revision numbers
prevent older work from replacing newer settings. Tk canvases and controls
are updated only on the main thread through `after()` polling. Rapid tolerance
changes are debounced. Closing the tab cancels its pending callbacks and
requests worker shutdown.

Run the focused tests with:

```sh
python -m pytest tests/test_compare_tab.py
```

Worker tests run without a display. Widget tests use one temporary Tk
application and run on systems with a display; they skip on headless Linux.
