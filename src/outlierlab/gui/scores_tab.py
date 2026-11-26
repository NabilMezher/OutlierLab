"""Sortable event metrics backed by the core scoring API."""

from __future__ import annotations

from dataclasses import dataclass, replace
import gc
import math
import queue
import threading
from tkinter import ttk
from typing import Any

import customtkinter as ctk

from outlierlab.core.detectors.base import RunResult
from outlierlab.core.events import Event
from outlierlab.core.metrics import Score, score

COLUMNS = (
    ("name", "Detector", 155), ("family", "Type", 80), ("status", "Status", 100),
    ("found_events", "Found", 65), ("missed_events", "Missed", 65),
    ("false_alarms", "False alarms", 95), ("precision", "Precision", 80),
    ("recall", "Recall", 75), ("f1", "F1", 75),
    ("mean_delay", "Delay (samples)", 115), ("runtime", "Runtime (s)", 100),
)
HIGHER_IS_BETTER = {"found_events", "precision", "recall", "f1"}
LOWER_IS_BETTER = {"missed_events", "false_alarms", "mean_delay", "runtime"}


@dataclass(frozen=True)
class _Row:
    key: str
    name: str
    family: str
    status: str
    runtime: float | None
    event_count: int
    metrics: Score | None = None
    error: str = ""

    def value(self, column: str) -> str | int | float | None:
        if column in ("name", "family", "status", "runtime"):
            return getattr(self, column)
        return getattr(self.metrics, column) if self.metrics is not None else None


def _prepare_rows(
    results: dict[str, RunResult], events: list[Event], tolerance: int, n_rows: int,
) -> list[_Row]:
    """Score detached runs, retaining failures without fabricated metrics."""
    rows = []
    for key, result in results.items():
        runtime = result.runtime_s if math.isfinite(result.runtime_s) and result.runtime_s >= 0 else None
        event_count = sum(event.kind == result.family for event in events)
        metrics = None
        status, error = result.status, result.error
        try:
            if status not in ("done", "failed", "timed_out", "cancelled"):
                raise ValueError(f"Unknown run status: {status}")
            if runtime is None:
                raise ValueError("Runtime must be finite and non-negative")
            if status == "done":
                metrics = score(result, events, tolerance)
                if any(event.end >= n_rows for event in events) or any(end >= n_rows for _, end in result.alarms):
                    raise ValueError("Event or alarm positions are outside the loaded signal")
        except (TypeError, ValueError) as exc:
            status, error, metrics = "invalid", str(exc), None
        rows.append(_Row(key, result.detector_name, result.family, status, runtime, event_count, metrics, error))
    return rows


def _best_cells(rows: list[_Row]) -> set[tuple[str, str]]:
    """Compare like event types; quality needs ground-truth annotations."""
    best = set()
    for family in {row.family for row in rows}:
        for column in HIGHER_IS_BETTER | LOWER_IS_BETTER:
            candidates = [
                row for row in rows if row.family == family and row.metrics is not None
                and (column == "runtime" or row.event_count > 0) and row.value(column) is not None
            ]
            if not candidates:
                continue
            values = [row.value(column) for row in candidates]
            target = max(values) if column in HIGHER_IS_BETTER else min(values)
            for row in candidates:
                if math.isclose(row.value(column), target, rel_tol=1e-12, abs_tol=1e-12):
                    best.add((row.key, column))
    return best


def _sort_rows(rows: list[_Row], column: str, descending: bool) -> list[_Row]:
    present = [row for row in rows if row.value(column) is not None]
    missing = [row for row in rows if row.value(column) is None]
    def key(row: _Row):
        value = row.value(column)
        return value.casefold() if isinstance(value, str) else value
    return sorted(present, key=key, reverse=descending) + missing


def _worker(requests: queue.Queue, responses: queue.Queue) -> None:
    while True:
        request = requests.get()
        if request is None:
            return
        revision, results, events, tolerance, n_rows = request
        try:
            responses.put((revision, _prepare_rows(results, events, tolerance, n_rows), ""))
        except Exception as exc:
            responses.put((revision, [], str(exc)))


class ScoresTab(ctk.CTkFrame):
    """Tab 6: sort metrics and inspect the status of each detector run."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._closed = False
        self._revision = 0
        self._signature: tuple | None = None
        self._pending = False
        self._rows: list[_Row] = []
        self._sort_column = "f1"
        self._descending = True
        self._requests: queue.Queue = queue.Queue(maxsize=1)
        self._responses: queue.Queue = queue.Queue()
        self._poll_id: str | None = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ctk.CTkLabel(header, text="Scores", font=("Roboto", 18, "bold"),
                     text_color=("#0062cc", "#6ea8fe")).pack(side="left")
        ctk.CTkButton(header, text="Adjust tolerance in Compare", width=220,
                      command=lambda: self.app.tabs.set("Compare")).pack(side="right")
        self.summary_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1050)
        self.summary_label.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        ctk.CTkLabel(
            self, text="* Best value within detector type (ties included). Click a heading to sort; select a row for details.",
            anchor="w", justify="left", wraplength=1050,
        ).grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 6))
        table_box = ctk.CTkFrame(self, fg_color="transparent")
        table_box.grid(row=3, column=0, sticky="nsew", padx=12, pady=4)
        table_box.grid_columnconfigure(0, weight=1)
        table_box.grid_rowconfigure(0, weight=1)
        self._style_name = f"Scores{id(self)}.Treeview"
        self.tree = ttk.Treeview(table_box, columns=[c[0] for c in COLUMNS], show="headings", style=self._style_name)
        for column, title, width in COLUMNS:
            self.tree.heading(column, text=title, command=lambda col=column: self._sort(col))
            self.tree.column(column, width=width, minwidth=width, stretch=column == "name",
                             anchor="w" if column in ("name", "family", "status") else "e")
        vertical = ttk.Scrollbar(table_box, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.detail_label = ctk.CTkLabel(self, text="", anchor="w", justify="left", wraplength=1050)
        self.detail_label.grid(row=4, column=0, sticky="ew", padx=12, pady=(6, 12))
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        threading.Thread(target=_worker, args=(self._requests, self._responses), daemon=True).start()
        self._poll_id = self.after(50, self._poll)
        self.refresh()

    def _input_signature(self) -> tuple:
        state = self.app.app_state
        return (
            id(state.data), state.value_col, len(state.data) if state.data is not None else 0,
            state.tolerance, tuple((e.start, e.end, e.kind) for e in state.events),
            tuple((key, r.detector_name, r.family, r.status, r.runtime_s, r.error,
                   tuple(tuple(interval) for interval in r.alarms)) for key, r in state.results.items()),
        )

    def _queue_latest(self, request: tuple | None) -> None:
        try:
            self._requests.get_nowait()
        except queue.Empty:
            pass
        gc.collect()  # Keep discarded Tk font cycles out of the worker's collector.
        self._requests.put_nowait(request)

    def refresh(self) -> None:
        if self._closed:
            return
        dark = ctk.get_appearance_mode() == "Dark"
        ttk.Style(self).configure(self._style_name, rowheight=28, background="#242424" if dark else "white",
                                  fieldbackground="#242424" if dark else "white", foreground="white" if dark else "#17202b")
        self.tree.tag_configure("unscored", foreground="#a3a3a3" if dark else "#666666")
        signature = self._input_signature()
        if signature == self._signature:
            if not self._pending:
                self._publish_scores()
            return
        self._signature = signature
        self._revision += 1
        state = self.app.app_state
        self._rows = []
        state.scores.clear()
        self._render_table()
        self.detail_label.configure(text="")
        if state.data is None or not state.value_col or state.data.empty:
            self._pending = False
            self.summary_label.configure(text="Load a signal on Data, then run detectors to view scores.")
            return
        if not state.results:
            self._pending = False
            self.summary_label.configure(text="No detector results yet. Choose detectors and start a run on Run.")
            return
        self._pending = True
        self.summary_label.configure(text=f"Calculating scores with tolerance {state.tolerance} samples...")
        self._queue_latest((
            self._revision,
            {key: replace(result, alarms=list(result.alarms), scores=None) for key, result in state.results.items()},
            [replace(event) for event in state.events], state.tolerance, len(state.data),
        ))

    def _publish_scores(self) -> None:
        self.app.app_state.scores = {row.key: row.metrics for row in self._rows if row.metrics is not None}

    def _poll(self) -> None:
        self._poll_id = None
        while True:
            try:
                revision, rows, error = self._responses.get_nowait()
            except queue.Empty:
                break
            if revision != self._revision or self._closed:
                continue
            if self._signature != self._input_signature():
                self.refresh()
                continue
            self._pending = False
            self._rows = rows
            self._publish_scores()
            self._render_table()
            if error:
                self.summary_label.configure(text=f"Cannot score results: {error}")
                continue
            count = sum(row.metrics is not None for row in rows)
            message = f"{count} scored; {len(rows) - count} unscored | Tolerance: {self.app.app_state.tolerance} samples."
            missing = sorted({row.family for row in rows if row.metrics is not None and not row.event_count})
            if missing:
                message += f" No ground truth for {', '.join(missing)}: quality values are provisional and not marked best."
            self.summary_label.configure(text=message)
        if not self._closed:
            self._poll_id = self.after(50, self._poll)

    def _sort(self, column: str) -> None:
        self._descending = not self._descending if column == self._sort_column else column in HIGHER_IS_BETTER
        self._sort_column = column
        self._render_table()

    def _render_table(self) -> None:
        selection = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        best = _best_cells(self._rows)
        for column, title, _ in COLUMNS:
            suffix = (" v" if self._descending else " ^") if column == self._sort_column else ""
            self.tree.heading(column, text=title + suffix)
        for row in _sort_rows(self._rows, self._sort_column, self._descending):
            values = []
            for column, _, _ in COLUMNS:
                value = row.value(column)
                if value is None:
                    text = "--"
                elif column in ("precision", "recall", "f1", "mean_delay", "runtime"):
                    text = f"{value:.3f}"
                else:
                    text = str(value).replace("_", " ") if column == "status" else str(value)
                values.append(("* " if (row.key, column) in best else "") + text)
            self.tree.insert("", "end", iid=row.key, values=values,
                             tags=() if row.metrics is not None else ("unscored",))
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
            self._show_details()

    def _show_details(self, event: Any = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        row = next((row for row in self._rows if row.key == selected[0]), None)
        if row is None:
            return
        detail = row.error or f"{row.name}: evaluated against {row.event_count} marked {row.family} events."
        if row.metrics is not None and row.metrics.mean_delay is None:
            detail += " Mean delay is unavailable because no event matched."
        self.detail_label.configure(text=detail)

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self._queue_latest(None)
        super().destroy()
