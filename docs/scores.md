# Scores tab

Scores displays one row per detector result, including runs that failed,
timed out or were cancelled. The tab calls the core `score()` function used
by Compare and JSON reports. It does not run detectors again.

The columns show the detector name, event type, run status, found and missed
events, false alarms, precision, recall, F1, mean delay in samples and runtime
in seconds. Failed and invalid runs show `--` for unavailable event metrics
and retain their status. Select a row to inspect its error or event-count
details. Delay is unavailable when no event matched.

## Sorting and best values

Click any column heading to sort. Click it again to reverse the order. Counts,
metrics, delay and runtime sort by their underlying numbers, so 2 sorts before
10. Unavailable values stay last in either direction. Sorting uses the full
numeric precision even though the table displays three decimal places. The
default ordering is descending F1.

An asterisk marks the best value in a column, including ties. Best values
are compared within the detector's event type because change and anomaly
detectors are evaluated against different ground-truth events. Higher is
better for found events, precision, recall and F1. Lower is better for missed
events, false alarms, delay and runtime. Only successfully scored runs receive
best-value markers.

Without annotations of the relevant type, the core zero-denominator
conventions still apply. The tab labels those quality values as provisional
and does not mark them best. Runtime can still be compared. This avoids
treating missing ground truth as evidence of detector performance.

## Updates and integration

Adjust tolerance in Compare, then return to Scores. Activating a tab refreshes
its view. Scores also refreshes when the app receives new data, events or run
results. The table preserves the sort column and direction across updates.
Hiding a detector in Compare does not remove its Scores row.

Scoring runs on a worker thread with detached alarm and event inputs. Newer
inputs replace queued work, and stale responses cannot overwrite a newer
request. Cached results are reused only when the data identity, value column,
events, tolerance and result metadata/alarms match. Compare notifications do
not create an endless rescore loop. The tab publishes actual `Score` objects
to `state.scores`; unavailable scores are omitted.

Changes to the Data tab's value column or missing-value policy invalidate old
detector results and scores. Rerun the detectors after changing either option.
Changing only the label selection preserves detector results so they can be
scored against the current annotations.

The app registers this view as `app.tab_frames["Scores"]`. Standalone GUI
tests use a temporary Tk application in an isolated interpreter; data
preparation, numeric sorting and best-value selection are also tested without
a display.

```sh
python -m pytest tests/test_scores_tab.py
```
