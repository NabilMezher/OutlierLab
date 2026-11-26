from __future__ import annotations

from typing import Any

import customtkinter as ctk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter, MaxNLocator
from matplotlib.widgets import SpanSelector

from outlierlab.core.events import Event, check_events

COLORS = {"anomaly": "#e07000", "change": "#7b4fb5"}
KIND_LABELS = {"Anomaly": "anomaly", "Level change": "change"}


class EventsTab(ctk.CTkFrame):
    """Tab 2: mark the ground truth by clicking (point) or dragging (range) on the plot."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.span: SpanSelector | None = None

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------- left sidebar ----------
        side = ctk.CTkFrame(
            self, width=270, corner_radius=10, fg_color=("#e8e8e8", "#121212")
        )
        side.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        side.grid_propagate(False)

        ctk.CTkLabel(
            side,
            text="Mark Events",
            font=("Roboto", 18, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(pady=(12, 8))

        self._label(side, "Event type:")
        self.kind = ctk.CTkSegmentedButton(side, values=list(KIND_LABELS))
        self.kind.set("Anomaly")
        self.kind.pack(fill="x", padx=10)

        self._label(side, "How to mark:")
        self.mode = ctk.CTkSegmentedButton(
            side, values=["Point", "Range"], command=self._on_mode
        )
        self.mode.set("Point")
        self.mode.pack(fill="x", padx=10)
        self._hint(
            side,
            "Point: click once on the plot (a spike).\n"
            "Range: click and drag (a dropout or a period).",
        )

        self.count_label = ctk.CTkLabel(
            side, text="Marked events (0)", anchor="w", font=("Roboto", 13, "bold")
        )
        self.count_label.pack(fill="x", padx=10, pady=(14, 2))
        self.list_frame = ctk.CTkScrollableFrame(
            side, fg_color="transparent", height=180
        )
        self.list_frame.pack(fill="both", expand=True, padx=6)

        ctk.CTkButton(
            side,
            text="Next: detectors",
            fg_color="#0078ff",
            hover_color="#005dc1",
            command=lambda: self.app.tabs.set("Detectors"),
        ).pack(side="bottom", fill="x", padx=10, pady=(4, 12))
        ctk.CTkButton(
            side,
            text="Clear all events",
            fg_color=("#a0a0a0", "#444444"),
            hover_color=("#888888", "#333333"),
            command=self.clear_all,
        ).pack(side="bottom", fill="x", padx=10, pady=4)

        # ---------- right output panel ----------
        out = ctk.CTkFrame(self, corner_radius=10, fg_color=("#ffffff", "#1a1a1a"))
        out.grid(row=0, column=1, sticky="nsew", padx=(6, 4), pady=4)
        self.status = ctk.CTkLabel(out, text="", anchor="w", justify="left")
        self.status.pack(fill="x", padx=12, pady=(8, 0))

        self.fig = Figure(figsize=(8, 4), dpi=100)
        self.ax = self.fig.add_subplot()
        self.canvas = FigureCanvasTkAgg(self.fig, master=out)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self.canvas.mpl_connect("button_press_event", self.on_click)

        self.refresh()

    # ---------- small helpers ----------
    @staticmethod
    def _label(parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, anchor="w").pack(
            fill="x", padx=10, pady=(12, 2)
        )

    @staticmethod
    def _hint(parent, text: str) -> None:
        ctk.CTkLabel(
            parent,
            text=text,
            font=("Roboto", 11),
            text_color=("#666666", "#a3a3a3"),
            wraplength=240,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(4, 0))

    def _has_data(self) -> bool:
        state = self.app.app_state
        return state.data is not None and bool(state.value_col)

    def _row(self, x: float) -> int:
        return int(np.clip(round(x), 0, len(self.app.app_state.data) - 1))

    def _kind(self) -> str:
        return KIND_LABELS[self.kind.get()]

    def _time(self, i: int) -> str:
        return str(self.app.app_state.data.index[i])[:16]

    # ---------- mouse ----------
    def _on_mode(self, mode: str) -> None:
        if self.span is not None:
            self.span.set_active(mode == "Range")

    def on_click(self, event) -> None:
        if (
            self.mode.get() != "Point"
            or not self._has_data()
            or event.inaxes is not self.ax
            or event.xdata is None
        ):
            return
        i = self._row(event.xdata)
        self.add(Event(i, i, self._kind(), "point"))

    def on_span(self, xmin: float, xmax: float) -> None:
        if not self._has_data():
            return
        a, b = self._row(xmin), self._row(xmax)
        if b > a:
            self.add(Event(a, b, self._kind(), "range"))

    # ---------- changing the events ----------
    def add(self, ev: Event) -> None:
        state = self.app.app_state
        try:
            check_events([*state.events, ev], len(state.data))
        except ValueError as exc:
            self.status.configure(text=f"⚠ Not added: {exc}", text_color="#c62828")
            return
        state.events.append(ev)
        state.events.sort(key=lambda e: e.start)
        self.app.refresh_all()  # redraws this tab, and Compare sees the new ground truth

    def delete(self, ev: Event) -> None:
        self.app.app_state.events.remove(ev)
        self.app.refresh_all()

    def clear_all(self) -> None:
        self.app.app_state.events.clear()
        self.app.refresh_all()

    # ---------- drawing ----------
    def refresh(self) -> None:
        """Called by App.refresh_all() whenever the shared state changes."""
        self._draw_plot()
        self._draw_list()

    def _draw_plot(self) -> None:
        state = self.app.app_state
        self.ax.clear()
        if not self._has_data():
            self.ax.text(
                0.5,
                0.5,
                "Load a CSV on the Data tab first",
                ha="center",
                va="center",
                transform=self.ax.transAxes,
                color="#888888",
            )
            self.ax.set_xticks([])
            self.ax.set_yticks([])
            self.status.configure(text="", text_color=("#111111", "#ffffff"))
            self.canvas.draw_idle()
            return

        y = state.series.to_numpy()
        x = np.arange(len(y))
        self.ax.plot(x, y, lw=1, color="#1f77b4")
        for e in state.events:
            if e.start == e.end:
                self.ax.axvline(e.start, color=COLORS[e.kind], lw=2)
            else:
                self.ax.axvspan(
                    e.start - 0.5, e.end + 0.5, color=COLORS[e.kind], alpha=0.25
                )
        self.ax.set_xlim(0, len(y) - 1)
        self.ax.set_ylabel(state.value_col)
        self.ax.grid(alpha=0.3)
        # x positions are row numbers; label the ticks with the real times
        self.ax.xaxis.set_major_locator(MaxNLocator(6, integer=True))
        self.ax.xaxis.set_major_formatter(
            FuncFormatter(lambda v, _: self._time(int(v)) if 0 <= v < len(y) else "")
        )
        self.fig.tight_layout()

        # ax.clear() removes the old selector's shapes, so make a fresh one each redraw.
        # Keep the reference in self.span, or it gets garbage-collected and stops working.
        if self.span is not None:
            self.span.disconnect_events()
        self.span = SpanSelector(
            self.ax,
            self.on_span,
            "horizontal",
            useblit=True,
            props=dict(alpha=0.2, facecolor=COLORS[self._kind()]),
        )
        self.span.set_active(self.mode.get() == "Range")

        self.status.configure(
            text=f"{len(state.events)} events marked · orange = anomaly · purple = level change",
            text_color=("#111111", "#ffffff"),
        )
        self.canvas.draw_idle()

    def _draw_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        events = self.app.app_state.events
        self.count_label.configure(text=f"Marked events ({len(events)})")
        if not self._has_data():
            return
        for ev in events:
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", pady=1)
            where = f"{ev.start}" if ev.start == ev.end else f"{ev.start}–{ev.end}"
            ctk.CTkLabel(
                row,
                text=f"● {self._time(ev.start)}  rows {where}",
                text_color=COLORS[ev.kind],
                anchor="w",
                font=("Roboto", 11),
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row,
                text="✕",
                width=26,
                height=22,
                fg_color=("#a0a0a0", "#444444"),
                command=lambda e=ev: self.delete(e),
            ).pack(side="right")
