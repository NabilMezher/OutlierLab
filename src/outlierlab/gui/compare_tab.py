"""Interactive comparison view; analysis stays in the core library."""

from __future__ import annotations

from dataclasses import dataclass, replace
import gc
import math
import queue
import threading
from typing import Any

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.widgets import SpanSelector
import numpy as np
import pandas as pd

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import Score, score
from outlierlab.core.plotting import build_comparison_figure


@dataclass
class _Request:
    revision: int
    series: pd.Series
    results: dict[str, RunResult]
    events: list[Event]
    tolerance: int
    visible: list[str]
    sample_range: tuple[int, int] | None


@dataclass
class _Response:
    revision: int
    figure: Figure | None = None
    scores: dict[str, Score] | None = None
    error: str = ""


def _prepare_comparison(request: _Request) -> _Response:
    """Prepare a detached view without accessing Tk or live app state."""
    try:
        scores = {
            key: score(result, request.events, request.tolerance)
            for key, result in request.results.items() if result.status == "done"
        }
        figure = build_comparison_figure(
            request.series, request.results, request.events, request.tolerance,
            detector_keys=request.visible, sample_range=request.sample_range,
        )
        return _Response(request.revision, figure, scores)
    except Exception as exc:
        return _Response(request.revision, error=str(exc))


def _worker(requests: queue.Queue, responses: queue.Queue) -> None:
    while True:
        request = requests.get()
        if request is None:
            return
        responses.put(_prepare_comparison(request))


class CompareTab(ctk.CTkFrame):
    """Tab 5: view alarms, adjust tolerance and inspect a sample range."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._closed = False
        self._revision = 0
        self._debounce_id: str | None = None
        self._poll_id: str | None = None
        self._requests: queue.Queue = queue.Queue(maxsize=1)
        self._responses: queue.Queue = queue.Queue()
        self._visible: dict[str, ctk.BooleanVar] = {}
        self._list_signature: tuple = ()
        self._data_signature: tuple | None = None
        self._length = 0
        self._sample_range: tuple[int, int] | None = None
        self._setting_limits = False
        self._plot_canvas: FigureCanvasTkAgg | None = None
        self._toolbar: NavigationToolbar2Tk | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        sidebar = ctk.CTkFrame(self, width=245, fg_color=("#e8e8e8", "#121212"))
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        sidebar.grid_propagate(False)
        ctk.CTkLabel(
            sidebar, text="Compare", font=("Roboto", 18, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(pady=(12, 6))
        ctk.CTkLabel(sidebar, text="Tolerance (samples)", anchor="w").pack(fill="x", padx=12)
        self.tolerance_label = ctk.CTkLabel(sidebar, text="")
        self.tolerance_label.pack()
        self.tolerance_slider = ctk.CTkSlider(
            sidebar, from_=0, to=60, number_of_steps=60, command=self._on_tolerance,
        )
        self.tolerance_slider.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkLabel(
            sidebar, text="Matches use events of the same type. Green: matched alarm. Red: false alarm.",
            wraplength=215, justify="left", font=("Roboto", 11),
        ).pack(fill="x", padx=12, pady=(0, 10))
        self.summary_label = ctk.CTkLabel(sidebar, text="", wraplength=215, justify="left", anchor="w")
        self.summary_label.pack(fill="x", padx=12, pady=(0, 6))
        actions = ctk.CTkFrame(sidebar, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=4)
        self.show_all_button = ctk.CTkButton(actions, text="Show all", width=100, command=lambda: self._show_all(True))
        self.show_all_button.pack(side="left", padx=(0, 4))
        self.hide_all_button = ctk.CTkButton(actions, text="Hide all", width=100, command=lambda: self._show_all(False))
        self.hide_all_button.pack(side="left")
        self.detector_list = ctk.CTkScrollableFrame(sidebar, fg_color="transparent")
        self.detector_list.pack(fill="both", expand=True, padx=6, pady=6)
        self.full_range_button = ctk.CTkButton(sidebar, text="Full range", command=self._full_range)
        self.full_range_button.pack(fill="x", padx=12, pady=(6, 12))

        output = ctk.CTkFrame(self, fg_color=("#ffffff", "#1a1a1a"))
        output.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        output.grid_columnconfigure(0, weight=1)
        output.grid_rowconfigure(2, weight=1)
        self.status_label = ctk.CTkLabel(output, text="", anchor="w", justify="left", wraplength=700)
        self.status_label.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 2))
        self.toolbar_frame = ctk.CTkFrame(output, fg_color="transparent", height=32)
        self.toolbar_frame.grid(row=1, column=0, sticky="ew", padx=8)
        self.plot_frame = ctk.CTkScrollableFrame(output, fg_color="white")
        self.plot_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)
        self.range_label = ctk.CTkLabel(output, text="Drag on the overview to zoom; use the toolbar to pan.", anchor="w")
        self.range_label.grid(row=3, column=0, sticky="ew", padx=12)
        overview_frame = ctk.CTkFrame(output, fg_color="white", height=85)
        overview_frame.grid(row=4, column=0, sticky="ew", padx=8, pady=(0, 8))
        self._overview = Figure(figsize=(7, 0.85), layout="constrained")
        self._overview_axis = self._overview.subplots()
        self._overview_line, = self._overview_axis.plot([], [], color="#1f77b4", linewidth=0.8)
        self._overview_axis.set_yticks([])
        self._overview_canvas = FigureCanvasTkAgg(self._overview, overview_frame)
        self._overview_canvas.get_tk_widget().configure(height=85)
        self._overview_canvas.get_tk_widget().pack(fill="x", expand=True)
        self._selector = SpanSelector(
            self._overview_axis, self._on_span, "horizontal", useblit=True,
            interactive=True, drag_from_anywhere=True,
            props={"facecolor": "#0062cc", "alpha": 0.2},
        )
        threading.Thread(target=_worker, args=(self._requests, self._responses), daemon=True).start()
        self._poll_id = self.after(50, self._poll)
        self.refresh()

    def _queue_latest(self, request: _Request | None) -> None:
        try:
            self._requests.get_nowait()
        except queue.Empty:
            pass
        # Destroyed CTk widgets may retain cyclic Font/Image references.
        # Collect those on the Tk thread before the worker allocates a new
        # figure and can otherwise trigger their Tcl-backed destructors.
        gc.collect()
        self._requests.put_nowait(request)

    def _sync_detectors(self) -> None:
        results = self.app.app_state.results
        signature = tuple((key, result.detector_name, result.status) for key, result in results.items())
        if signature == self._list_signature:
            return
        self._list_signature = signature
        previous = {key: variable.get() for key, variable in self._visible.items()}
        self._visible = {}
        for child in self.detector_list.winfo_children():
            if isinstance(child, ctk.CTkCheckBox):
                child.configure(variable=None)
            child.destroy()
        for key, result in results.items():
            variable = ctk.BooleanVar(value=previous.get(key, True))
            self._visible[key] = variable
            label = result.detector_name
            if result.status != "done":
                label += f" ({result.status.replace('_', ' ')})"
            ctk.CTkCheckBox(
                self.detector_list, text=label, variable=variable, command=self.refresh,
            ).pack(anchor="w", fill="x", padx=4, pady=5)

    def refresh(self) -> None:
        """Capture shared state and schedule a coalesced background update."""
        if self._closed:
            return
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
            self._debounce_id = None
        self._revision += 1
        state = self.app.app_state
        state.scores.clear()
        self._sync_detectors()
        maximum = max(60, state.tolerance)
        self.tolerance_slider.configure(to=maximum, number_of_steps=maximum)
        self.tolerance_slider.set(state.tolerance)
        self.tolerance_label.configure(text=f"{state.tolerance} samples either side")
        completed = sum(result.status == "done" for result in state.results.values())
        self.summary_label.configure(text=f"{completed} completed; {len(state.results) - completed} unscored\n{len(state.events)} marked events")
        enabled = "normal" if state.data is not None and state.value_col else "disabled"
        self.tolerance_slider.configure(state=enabled)
        self.full_range_button.configure(state=enabled)
        for button in (self.show_all_button, self.hide_all_button):
            button.configure(state="normal" if state.results else "disabled")
        try:
            series = state.series.copy(deep=True)
            if series.empty:
                raise ValueError("The analysis signal is empty.")
            signature = (id(state.data), state.value_col, len(series))
            self._length = len(series)
            if signature != self._data_signature:
                self._data_signature = signature
                self._sample_range = None
            request = _Request(
                self._revision, series,
                {key: replace(result, alarms=list(result.alarms), scores=None) for key, result in state.results.items()},
                [replace(event) for event in state.events], state.tolerance,
                [key for key, variable in self._visible.items() if variable.get()], self._sample_range,
            )
            self._overview_line.set_data(np.arange(self._length), series.to_numpy(dtype=float, na_value=np.nan))
            self._overview_axis.relim()
            self._overview_axis.autoscale_view()
            self._overview_axis.set_xlim(-0.5, self._length - 0.5)
            self._update_range_display()
        except (RuntimeError, KeyError, TypeError, ValueError) as exc:
            self._length = 0
            self._sample_range = None
            self._dispose_plot()
            self._overview_line.set_data([], [])
            self._selector.set_visible(False)
            self._overview_canvas.draw_idle()
            self.range_label.configure(text="Load a signal to use the overview.")
            self.tolerance_slider.configure(state="disabled")
            self.full_range_button.configure(state="disabled")
            self.status_label.configure(text=f"Load a signal on Data to compare results. {exc}")
            return
        self.status_label.configure(text="Updating comparison...")
        self._queue_latest(request)

    def _on_tolerance(self, value: float) -> None:
        self.app.app_state.tolerance = int(round(value))
        self.app.app_state.scores.clear()
        self.tolerance_label.configure(text=f"{self.app.app_state.tolerance} samples either side")
        self._revision += 1  # Ignore older work immediately, even during debounce.
        self.status_label.configure(text="Updating tolerance...")
        if self._debounce_id is not None:
            self.after_cancel(self._debounce_id)
        self._debounce_id = self.after(150, self.refresh)

    def _show_all(self, visible: bool) -> None:
        for variable in self._visible.values():
            variable.set(visible)
        self.refresh()

    def _poll(self) -> None:
        self._poll_id = None
        while True:
            try:
                response = self._responses.get_nowait()
            except queue.Empty:
                break
            if response.revision != self._revision or self._closed:
                if response.figure is not None:
                    response.figure.clear()
                continue
            self._dispose_plot()
            if response.error:
                self.status_label.configure(text=f"Cannot compare results: {response.error}")
                continue
            self.app.app_state.scores = response.scores or {}
            self._plot_canvas = FigureCanvasTkAgg(response.figure, self.plot_frame)
            self._plot_canvas.get_tk_widget().configure(height=max(320, 220 + 70 * (len(response.figure.axes) - 1)))
            self._plot_canvas.get_tk_widget().pack(fill="x", expand=True)
            self._toolbar = NavigationToolbar2Tk(self._plot_canvas, self.toolbar_frame, pack_toolbar=False)
            self._toolbar.pack(fill="x")
            response.figure.axes[0].callbacks.connect("xlim_changed", self._on_axes_xlim)
            # A newer zoom may have been chosen while the figure was prepared.
            self._apply_limits()
            self._plot_canvas.draw_idle()
            if not self.app.app_state.results:
                message = "Signal ready. Run detectors on Run to add comparison rows."
            elif not self.app.app_state.events:
                message = "No marked events: mark ground truth on Events before interpreting false alarms."
            else:
                message = "Comparison ready. Hidden detectors remain included in scoring."
            self.status_label.configure(text=message)
            for name in ("Scores", "Export"):
                frame = getattr(self.app, "tab_frames", {}).get(name)
                if frame is not None and hasattr(frame, "refresh"):
                    frame.refresh()
        if not self._closed:
            self._poll_id = self.after(50, self._poll)

    def _on_span(self, left: float, right: float) -> None:
        if not self._length or right <= left:
            return
        self._sample_range = (
            max(0, min(self._length - 1, math.floor(left))),
            max(0, min(self._length - 1, math.ceil(right))),
        )
        self._apply_limits()

    def _full_range(self) -> None:
        self._sample_range = None
        self._apply_limits()

    def _apply_limits(self) -> None:
        if self._plot_canvas is not None and self._length:
            start, end = self._sample_range or (0, self._length - 1)
            self._setting_limits = True
            try:
                for axis in self._plot_canvas.figure.axes:
                    axis.set_xlim(start - 0.5, end + 0.5)
            finally:
                self._setting_limits = False
            self._plot_canvas.draw_idle()
        self._update_range_display()

    def _on_axes_xlim(self, axis: Any) -> None:
        if self._setting_limits or not self._length:
            return
        left, right = sorted(axis.get_xlim())
        start = max(0, min(self._length - 1, math.ceil(left)))
        end = max(start, min(self._length - 1, math.floor(right)))
        self._sample_range = None if (start, end) == (0, self._length - 1) else (start, end)
        self._update_range_display()

    def _update_range_display(self) -> None:
        if not self._length:
            return
        start, end = self._sample_range or (0, self._length - 1)
        self.range_label.configure(text=f"Samples {start} to {end} of {self._length} | Drag on overview to zoom")
        if self._sample_range is None:
            self._selector.set_visible(False)
        else:
            self._selector.extents = (start - 0.5, end + 0.5)
            self._selector.set_visible(True)
        self._overview_canvas.draw_idle()

    @staticmethod
    def _cancel_draw(canvas: FigureCanvasTkAgg) -> None:
        if canvas._idle_draw_id is not None:
            canvas.get_tk_widget().after_cancel(canvas._idle_draw_id)
            canvas._idle_draw_id = None

    def _dispose_plot(self) -> None:
        if self._plot_canvas is not None:
            self._cancel_draw(self._plot_canvas)
            # Figure.clear() updates its toolbar; detach it before destroying
            # the Tk buttons so cleanup cannot call a dead widget.
            self._plot_canvas.toolbar = None
        if self._toolbar is not None:
            self._toolbar.destroy()
            # Drop Tcl-backed objects on the Tk thread. Otherwise a later
            # collection in the preparation worker can run their destructors
            # on that worker and stall a redraw.
            for button in self._toolbar._buttons.values():
                for name in ("_ntimage", "_ntimage_alt", "var"):
                    if hasattr(button, name):
                        setattr(button, name, None)
            self._toolbar.message = None
            self._toolbar._label_font = None
            self._toolbar._buttons.clear()
            self._toolbar = None
        if self._plot_canvas is not None:
            self._plot_canvas.get_tk_widget().destroy()
            self._plot_canvas._tkphoto = None
            self._plot_canvas.figure.clear()
            self._plot_canvas.figure.set_canvas(None)
            self._plot_canvas = None

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        for callback in (self._debounce_id, self._poll_id):
            if callback is not None:
                self.after_cancel(callback)
        self._queue_latest(None)
        self._selector.disconnect_events()
        self._dispose_plot()
        self._cancel_draw(self._overview_canvas)
        self._overview_canvas.get_tk_widget().destroy()
        self._overview_canvas._tkphoto = None
        self._overview.clear()
        self._overview.set_canvas(None)
        for child in self.detector_list.winfo_children():
            if isinstance(child, ctk.CTkCheckBox):
                child.configure(variable=None)
            child.destroy()
        self._visible.clear()
        super().destroy()
