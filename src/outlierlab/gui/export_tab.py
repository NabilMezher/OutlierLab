"""Session previews and background exports using the existing IO API."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import gc
import json
from pathlib import Path
import queue
import threading
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from outlierlab.core.state import ComparatorState
from outlierlab.io.export import build_report, export_session, reproduction_script

EXPORT_OPTIONS = (
    ("include_script", "Reproduction script", "reproduce_run.py"),
    ("include_environment", "Environment details", "environment.txt"),
    ("include_pip_freeze", "pip freeze", "pip_freeze.txt"),
    ("include_plot", "Comparison plot (PNG)", "comparison.png"),
)
PREVIEW_LIMIT = 30_000


def _manifest(options: dict[str, bool]) -> list[str]:
    return ["report.json", *[filename for key, _, filename in EXPORT_OPTIONS if options[key]]]


@dataclass
class _Preview:
    state: ComparatorState
    report: dict[str, Any]
    json_text: str
    script_text: str


def _prepare_preview(snapshot: ComparatorState) -> _Preview:
    report = build_report(snapshot)
    return _Preview(snapshot, report, json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    reproduction_script())


def _worker(requests: queue.Queue, responses: queue.Queue) -> None:
    """Never read Tk variables or live app state from this worker."""
    while True:
        request = requests.get()
        if request is None:
            return
        kind, revision, snapshot, destination, options = request
        try:
            result = _prepare_preview(snapshot) if kind == "preview" else export_session(snapshot, destination, **options)
            responses.put((kind, revision, result, ""))
        except Exception as exc:
            responses.put((kind, revision, None, str(exc)))


class ExportTab(ctk.CTkFrame):
    """Tab 7: inspect, copy and save an analysis snapshot without freezing Tk."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self._closed = False
        self._busy = False
        self._waiting_for_run = False
        self._preview_pending = False
        self._revision = 0
        self._signature: tuple | None = None
        self._preview: _Preview | None = None
        self._last_paths: dict[str, Path] = {}
        self._include_vars = {key: ctk.BooleanVar(value=True) for key, _, _ in EXPORT_OPTIONS}
        self._requests: queue.Queue = queue.Queue(maxsize=1)
        self._responses: queue.Queue = queue.Queue()
        self._poll_id: str | None = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        sidebar = ctk.CTkFrame(self, width=270, fg_color=("#e8e8e8", "#121212"))
        sidebar.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        sidebar.grid_propagate(False)
        ctk.CTkLabel(sidebar, text="Export session", font=("Roboto", 18, "bold"),
                     text_color=("#0062cc", "#6ea8fe")).pack(pady=(12, 8))
        ctk.CTkLabel(sidebar, text="JSON report is always included.", anchor="w").pack(fill="x", padx=12)
        self._option_widgets = []
        for key, label, _ in EXPORT_OPTIONS:
            checkbox = ctk.CTkCheckBox(sidebar, text=label, variable=self._include_vars[key], command=self._render_preview)
            checkbox.pack(anchor="w", padx=12, pady=7)
            self._option_widgets.append(checkbox)
        ctk.CTkLabel(sidebar, text="Destination folder", anchor="w").pack(fill="x", padx=12, pady=(12, 2))
        self.destination_entry = ctk.CTkEntry(sidebar, placeholder_text="New or empty folder")
        self.destination_entry.pack(fill="x", padx=12, pady=4)
        self.destination_entry.bind("<FocusOut>", lambda event: self._render_preview())
        self.browse_button = ctk.CTkButton(sidebar, text="Choose folder...", command=self._choose_folder)
        self.browse_button.pack(fill="x", padx=12, pady=4)
        ctk.CTkLabel(sidebar, text="Use a new or empty folder. Existing files are never overwritten.",
                     wraplength=240, justify="left", anchor="w", font=("Roboto", 11)).pack(fill="x", padx=12, pady=6)
        self.refresh_button = ctk.CTkButton(sidebar, text="Refresh preview", command=lambda: self.refresh(force=True))
        self.refresh_button.pack(fill="x", padx=12, pady=(6, 4))
        self.export_button = ctk.CTkButton(sidebar, text="Export session", command=self._start_export)
        self.export_button.pack(fill="x", padx=12, pady=4)
        self.progress = ctk.CTkProgressBar(sidebar, mode="indeterminate")

        output = ctk.CTkFrame(self, fg_color=("#ffffff", "#1a1a1a"))
        output.grid(row=0, column=1, sticky="nsew", padx=4, pady=4)
        output.grid_columnconfigure(0, weight=1)
        output.grid_rowconfigure(2, weight=1)
        header = ctk.CTkFrame(output, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 4))
        self.preview_mode = ctk.CTkSegmentedButton(
            header, values=["Summary", "JSON", "Python script"], command=lambda value: self._render_preview(),
        )
        self.preview_mode.set("Summary")
        self.preview_mode.pack(side="left")
        self.copy_button = ctk.CTkButton(header, text="Copy preview", width=110, command=self._copy_preview)
        self.copy_button.pack(side="right", padx=(8, 0))
        self.status_label = ctk.CTkLabel(output, text="", anchor="w", justify="left", wraplength=650)
        self.status_label.grid(row=1, column=0, sticky="ew", padx=12, pady=4)
        self.preview_box = ctk.CTkTextbox(output, font=("Consolas", 12), wrap="word")
        self.preview_box.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self.preview_box.configure(state="disabled")
        threading.Thread(target=_worker, args=(self._requests, self._responses), daemon=True).start()
        self._poll_id = self.after(50, self._poll)
        self.refresh()

    def _running_detectors(self) -> bool:
        run_tab = getattr(self.app, "tab_frames", {}).get("Run")
        runner = getattr(run_tab, "runner", None)
        return runner is not None and runner.is_running()

    def _state_signature(self) -> tuple:
        state = self.app.app_state
        return (
            id(state.data), state.source_path, state.value_col, state.missing_policy, state.seed, state.tolerance,
            tuple((e.start, e.end, e.kind, e.note) for e in state.events),
            tuple((d.key, d.name, d.enabled, repr(d.params)) for d in state.detectors),
            tuple((key, id(r), r.detector_name, r.family, r.status, r.runtime_s, r.error,
                   tuple(tuple(interval) for interval in r.alarms), id(r.scores), r.threshold)
                  for key, r in state.results.items()),
        )

    def _selected_options(self) -> dict[str, bool]:
        return {key: variable.get() for key, variable in self._include_vars.items()}

    def _queue_latest(self, request: tuple | None) -> None:
        try:
            self._requests.get_nowait()
        except queue.Empty:
            pass
        gc.collect()
        self._requests.put_nowait(request)

    def _update_controls(self) -> None:
        has_data = self.app.app_state.data is not None and bool(self.app.app_state.value_col)
        available = has_data and not self._busy and not self._running_detectors()
        self.refresh_button.configure(state="normal" if available else "disabled")
        ready = (available and self._preview is not None and not self._preview_pending
                 and self._signature == self._state_signature())
        self.export_button.configure(state="normal" if ready else "disabled")
        self.copy_button.configure(state="normal" if self._preview is not None and not self._preview_pending else "disabled")
        for widget in [*self._option_widgets, self.destination_entry, self.browse_button]:
            widget.configure(state="disabled" if self._busy else "normal")
        if self._busy or self._preview_pending:
            self.progress.pack(fill="x", padx=12, pady=10)
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def refresh(self, force: bool = False) -> None:
        if self._closed or self._busy:
            return
        state = self.app.app_state
        if self._running_detectors():
            self._waiting_for_run = True
            self.status_label.configure(text="Detectors are running. Preview and export are available after the run finishes.")
            self._update_controls()
            return
        force = force or self._waiting_for_run
        self._waiting_for_run = False
        signature = self._state_signature()
        if signature == self._signature and not force:
            self._update_controls()
            return
        self._signature = signature
        self._revision += 1
        self._preview = None
        self._last_paths = {}
        if state.data is None or not state.value_col:
            self._preview_pending = False
            self.status_label.configure(text="Load an analysis signal on Data before exporting.")
            self._set_preview_text("A session report, reproduction script and comparison image will be available here.")
            self._update_controls()
            return
        self._preview_pending = True
        self.status_label.configure(text="Preparing a preview of the current session...")
        self._set_preview_text("Preparing preview...")
        self._update_controls()
        # Capture on the Tk thread before allowing subsequent UI edits. The
        # worker receives no widgets, Tk variables or live shared state.
        self._queue_latest(("preview", self._revision, copy.deepcopy(state), None, None))

    def _set_preview_text(self, text: str) -> None:
        if len(text) > PREVIEW_LIMIT:
            text = text[:PREVIEW_LIMIT] + "\n\n[Preview shortened. Copy includes the complete text; export writes the complete file.]"
        self.preview_box.configure(state="normal")
        self.preview_box.delete("1.0", "end")
        self.preview_box.insert("1.0", text)
        self.preview_box.configure(state="disabled")

    def _full_preview_text(self) -> str:
        if self._preview is None:
            return ""
        mode = self.preview_mode.get()
        if mode == "JSON":
            return self._preview.json_text
        if mode == "Python script":
            return self._preview.script_text
        report = self._preview.report
        settings = report["settings"]
        completed = sum(result["status"] == "done" for result in report["results"].values())
        text = (
            f"OutlierLab session export\n\n"
            f"Signal: {settings['value_col']} ({len(report['signal']['values'])} samples)\n"
            f"Events: {len(report['events'])}\nCompleted detectors: {completed}\n"
            f"Other run statuses: {len(report['results']) - completed}\n"
            f"Seed: {settings['seed']}\nTolerance: {settings['tolerance']} samples\n\n"
            f"Destination: {self.destination_entry.get().strip() or '(choose a folder)'}\n\nFiles:\n"
        )
        text += "".join(f"  {name}\n" for name in _manifest(self._selected_options()))
        text += "\nScores (precision / recall / F1):\n"
        for key, metrics in report["scores"].items():
            text += (f"  {key}: {metrics['precision']:.3f} / {metrics['recall']:.3f} / {metrics['f1']:.3f}\n"
                     if metrics is not None else f"  {key}: unscored\n")
        text += "\nThe bundle includes the analysis signal; the original CSV is not required for reproduction.\n"
        if not report["results"]:
            text += "No detector runs are present. This export saves data and settings only.\n"
        return text

    def _render_preview(self) -> None:
        if self._preview is not None:
            self._set_preview_text(self._full_preview_text())

    def _copy_preview(self) -> None:
        text = self._full_preview_text()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_label.configure(text=f"Copied complete {self.preview_mode.get().lower()} preview.")

    def _choose_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self.winfo_toplevel(), title="Choose a new or empty export folder", mustexist=False)
        if folder:
            self.destination_entry.delete(0, "end")
            self.destination_entry.insert(0, folder)
            self._render_preview()

    def _start_export(self) -> None:
        if self._busy or self._preview_pending or self._preview is None:
            return
        if self._running_detectors():
            self.status_label.configure(text="Wait for the current detector run to finish before exporting.")
            self._update_controls()
            return
        if self._signature != self._state_signature():
            self.refresh()
            return
        destination = self.destination_entry.get().strip()
        if not destination:
            self.status_label.configure(text="Choose a new or empty destination folder first.")
            return
        self._busy = True
        self._last_paths = {}
        self.status_label.configure(text="Exporting the previewed session snapshot. You can continue using the other tabs.")
        self._update_controls()
        self._queue_latest(("export", self._revision, self._preview.state, Path(destination).expanduser(), self._selected_options()))

    def _poll(self) -> None:
        self._poll_id = None
        while True:
            try:
                kind, revision, result, error = self._responses.get_nowait()
            except queue.Empty:
                break
            if revision != self._revision or self._closed:
                continue
            if kind == "preview":
                self._preview_pending = False
                if self._signature != self._state_signature():
                    self.refresh()
                    continue
                self._preview = result
                if error:
                    self.status_label.configure(text=f"Cannot prepare export: {error}")
                    self._set_preview_text("Correct the session settings or rerun detectors, then refresh the preview.")
                else:
                    self.status_label.configure(text="Preview ready. Select files and choose a destination folder.")
                    self._render_preview()
                if self._running_detectors():
                    self._waiting_for_run = True
                    self.status_label.configure(text="Detectors are running. Preview and export are available after the run finishes.")
            else:
                self._busy = False
                self._last_paths = result or {}
                if error:
                    self.status_label.configure(text=f"Export failed: {error}")
                else:
                    folder = next(iter(result.values())).parent
                    self.status_label.configure(text=f"Exported {len(result)} files to {folder}. Run reproduce_run.py there to verify the saved scores."
                                                if "reproduce_run.py" in result else f"Exported {len(result)} files to {folder}.")
                    if self._signature != self._state_signature():
                        self.status_label.configure(text=self.status_label.cget("text") + " The current session has changed; refresh its preview before exporting again.")
            self._update_controls()
        if not self._closed:
            self._poll_id = self.after(50, self._poll)

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
        self.progress.stop()
        self._queue_latest(None)
        for checkbox in self._option_widgets:
            checkbox.configure(variable=None)
        self._include_vars.clear()
        super().destroy()
