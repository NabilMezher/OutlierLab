# Event scoring

The core API runs without the GUI. The Compare tab, Scores tab and exports
should all use these functions for consistent results.

```python
from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import match_alarms, score

result = RunResult(
    detector_key="example",
    detector_name="Example detector",
    family="anomaly",
    alarms=[(12, 12), (29, 29), (70, 70), (90, 90)],
)
events = [Event(10, 10), Event(30, 32), Event(50, 50)]
metrics = score(result, events, tolerance=2)
matches = match_alarms(result, events, tolerance=2)
# 2 found events, 1 missed event, 2 false alarms
# precision = 1/2, recall = 2/3, F1 = 4/7, mean delay = 1 sample
```

Intervals include both endpoints. All positions, tolerance and delays use
samples (row positions), independent of the DataFrame's timestamp index.
An alarm qualifies when it overlaps an event expanded by the tolerance on
both sides. A `change` run is compared only with `change` events; an `anomaly`
run is compared only with `anomaly` events. Annotations of the other type do
not contribute to the recall denominator.

Matching maximizes the number of one-to-one pairs. Each event counts at most
once, each alarm counts at most once, and duplicate alarms left unmatched
count as false alarms. A broad alarm spanning several events can claim only
one event. For ambiguous matches, chronological event order and alarm
start/end order give deterministic results, with original list indices as
tie breakers. The algorithm does not optimize delay separately. Returned
`AlarmMatch` indices always refer to the original input lists, so plotting
can distinguish matched alarms from false alarms.

`Score` contains `found_events`, `missed_events`, `false_alarms`, `precision`,
`recall`, `f1` and `mean_delay`. Precision divides matched pairs by the alarm
count; recall divides by the number of events of the relevant type. F1 is
their harmonic mean. Zero denominators produce `0.0`. With no relevant
annotations, all alarms are unmatched and these rates do not establish
detector quality.

Delay is the alarm start minus the matched event start, clipped at zero.
An early alarm accepted through tolerance, or an alarm active at onset,
therefore has zero delay. Mean delay averages matched events only; it is
`None` when no event matched, which exports as JSON `null`. Runtime stays
in `RunResult.runtime_s`.

Only runs with status `done` are scored. Other statuses raise `ValueError`;
the GUI should display their status without numeric scores. Invalid
tolerance, interval endpoints or event types also raise `ValueError`.

Run the focused checks with:

```sh
python -m pytest tests/test_metrics.py
```
