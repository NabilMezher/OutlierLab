"""Comparison figures for embedding and export, with no GUI or pyplot imports."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Integral

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import match_alarms

MATCH_COLOR = "#1f8a3b"
FALSE_ALARM_COLOR = "#c62828"
ANOMALY_COLOR = "#d97706"
CHANGE_COLOR = "#7b4fb5"


def _check_interval(start: int, end: int, length: int, label: str) -> None:
    if (
        isinstance(start, bool)
        or isinstance(end, bool)
        or not isinstance(start, Integral)
        or not isinstance(end, Integral)
        or not 0 <= start <= end < length
    ):
        raise ValueError(f"{label} must use integer row positions within the series")


def _draw_interval(
    axis: Axes, start: int, end: int, color: str, *, gid: str,
    ymin: float = 0.0, ymax: float = 1.0, alpha: float = 1.0,
) -> None:
    if start == end:
        axis.axvline(
            start, ymin=ymin, ymax=ymax, color=color, alpha=alpha,
            linewidth=2, gid=gid,
        )
    else:
        # A sample occupies a cell of width one; intervals are inclusive.
        axis.axvspan(
            start - 0.5, end + 0.5, ymin=ymin, ymax=ymax,
            color=color, alpha=alpha, linewidth=0, gid=gid,
        )


def build_comparison_figure(
    series: pd.Series,
    results: Mapping[str, RunResult],
    events: Sequence[Event],
    tolerance: int = 6,
    *,
    detector_keys: Sequence[str] | None = None,
    sample_range: tuple[int, int] | None = None,
) -> Figure:
    """Return a signal plot above one row per selected detector.

    Use the same cleaned series supplied to the detectors. All intervals
    and the optional inclusive sample_range use row positions, regardless
    of the Series index. NaNs remain visible as gaps. detector_keys selects
    and orders rows; None uses mapping order, and [] shows just the signal.

    Completed runs use match_alarms() over the full session to color matched
    alarms green and unmatched alarms red. Zooming only changes the view.
    Other run statuses display a message and no classified alarms. Relevant
    ground-truth events appear faintly behind each completed detector row.

    This function neither sets a backend nor creates a Tk window. The caller
    can embed the returned Figure in a canvas or use Figure.savefig().
    """
    if not isinstance(series, pd.Series) or series.empty:
        raise ValueError("series must be a non-empty pandas Series")
    try:
        values = series.to_numpy(dtype=float, na_value=np.nan)
    except (TypeError, ValueError) as exc:
        raise ValueError("series must contain numeric values or missing values") from exc
    if np.isinf(values).any():
        raise ValueError("series must not contain infinite values")
    if isinstance(tolerance, bool) or not isinstance(tolerance, Integral) or tolerance < 0:
        raise ValueError("tolerance must be a non-negative integer number of samples")

    length = len(series)
    for event in events:
        _check_interval(event.start, event.end, length, "Event")
        if event.kind not in ("anomaly", "change"):
            raise ValueError(f"Unknown event kind: {event.kind!r}")
    if sample_range is not None:
        _check_interval(*sample_range, length, "sample_range")

    keys = list(results) if detector_keys is None else list(detector_keys)
    if len(set(keys)) != len(keys):
        raise ValueError("detector_keys must not contain duplicates")
    unknown = [key for key in keys if key not in results]
    if unknown:
        raise ValueError(f"Unknown detector keys: {unknown}")

    # Validate and classify before allocating a figure. Indices refer to each
    # original RunResult.alarms list, including duplicates and unsorted alarms.
    matched_indices: dict[str, set[int]] = {}
    for key in keys:
        result = results[key]
        if result.status not in ("done", "failed", "timed_out", "cancelled"):
            raise ValueError(f"Unknown run status: {result.status!r}")
        if result.status == "done":
            for start, end in result.alarms:
                _check_interval(start, end, length, "Alarm")
            matched_indices[key] = {
                match.alarm_index for match in match_alarms(result, events, tolerance)
            }

    figure = Figure(
        figsize=(11, 3.8 + 0.85 * len(keys)), constrained_layout=True,
        facecolor="white",
    )
    axes = figure.subplots(
        len(keys) + 1, 1, sharex=True, squeeze=False,
        gridspec_kw={"height_ratios": [3] + [1] * len(keys)},
    )[:, 0]
    figure.suptitle(
        f"OutlierLab detector comparison | Tolerance: {tolerance} samples", fontsize=13,
    )
    signal_axis = axes[0]
    signal_axis.plot(np.arange(length), values, color="#1f77b4", linewidth=1.2, gid="signal")
    signal_axis.set_ylabel(str(series.name) if series.name is not None else "Value")
    signal_axis.grid(axis="both", color="#ececec")
    for i, event in enumerate(events):
        _draw_interval(
            signal_axis, event.start, event.end,
            ANOMALY_COLOR if event.kind == "anomaly" else CHANGE_COLOR,
            gid=f"event-{i}", alpha=0.35,
        )
    signal_axis.legend(
        handles=[
            Line2D([], [], color=ANOMALY_COLOR, linewidth=3, label="Marked anomaly"),
            Line2D([], [], color=CHANGE_COLOR, linewidth=3, label="Marked change"),
            Line2D([], [], color=MATCH_COLOR, linewidth=3, label="Matched alarm"),
            Line2D([], [], color=FALSE_ALARM_COLOR, linewidth=3, label="False alarm"),
        ],
        loc="lower left", bbox_to_anchor=(0, 1.02), ncol=4, frameon=False, fontsize=9,
    )

    for axis, key in zip(axes[1:], keys):
        result = results[key]
        axis.set_ylim(0, 1)
        axis.set_yticks([0.5], labels=[result.detector_name])
        axis.tick_params(axis="y", length=0)
        axis.grid(axis="x", color="#ececec")
        if result.status != "done":
            axis.text(
                0.02, 0.5, f"{result.status.replace('_', ' ')} (unscored)",
                transform=axis.transAxes, va="center", color="#566273",
            )
            continue
        for i, event in enumerate(events):
            if event.kind == result.family:
                _draw_interval(
                    axis, event.start, event.end, "#566273",
                    gid=f"event-{i}", alpha=0.15,
                )
        for i, (start, end) in enumerate(result.alarms):
            matched = i in matched_indices[key]
            _draw_interval(
                axis, start, end, MATCH_COLOR if matched else FALSE_ALARM_COLOR,
                gid=f"alarm-{i}-{'matched' if matched else 'false'}", ymin=0.25, ymax=0.75,
            )
        if not result.alarms:
            axis.text(
                0.02, 0.5, "No alarms", transform=axis.transAxes,
                va="center", color="#566273",
            )

    start, end = sample_range if sample_range is not None else (0, length - 1)
    axes[-1].set_xlim(start - 0.5, end + 0.5)
    axes[-1].set_xlabel("Sample (row position)")
    return figure
