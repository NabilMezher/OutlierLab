from __future__ import annotations

from datetime import datetime
from tkinter import ttk
from typing import Any

import customtkinter as ctk

from outlierlab.core.registry import get_detector_meta
from outlierlab.core.runner import ProgressEvent, TaskRunner
from outlierlab.gui.progress import ProgressOverlay


class RunTab(ctk.CTkFrame):
    """Tab 4: run enabled detectors in the background without freezing the GUI."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.runner = TaskRunner()
        self._total = 0

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Left sidebar
        self.sidebar = ctk.CTkFrame(
            self,
            width=270,
            corner_radius=10,
            fg_color=("#e8e8e8", "#121212"),
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        self.sidebar.grid_propagate(False)

        ctk.CTkLabel(
            self.sidebar,
            text="Run Detectors",
            font=("Roboto", 18, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(pady=(12, 4))

        self.summary_label = ctk.CTkLabel(
            self.sidebar,
            text="",
            font=("Roboto", 12),
            text_color=("#444444", "#cccccc"),
            wraplength=240,
        )
        self.summary_label.pack(padx=10, pady=(0, 10))

        self.run_button = ctk.CTkButton(
            self.sidebar,
            text="Run all detectors",
            fg_color="#0078ff",
            hover_color="#005dc1",
            command=self._start_run,
        )
        self.run_button.pack(fill="x", padx=10, pady=(0, 8))

        self.progress = ProgressOverlay(self.sidebar, on_cancel=self.runner.cancel)

        trow = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        trow.pack(fill="x", padx=10, pady=(10, 4))
        ctk.CTkLabel(trow, text="Timeout (s):").pack(side="left")
        self.timeout_entry = ctk.CTkEntry(trow, width=64)
        self.timeout_entry.insert(0, "60")
        self.timeout_entry.pack(side="right")

        # Right output panel
        self.output = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color=("#ffffff", "#1a1a1a"),
        )
        self.output.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)

        self.status_header = ctk.CTkLabel(
            self.output,
            text="Ready",
            font=("Roboto", 13, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
            anchor="w",
        )
        self.status_header.pack(fill="x", padx=14, pady=(12, 6))

        cols = ("detector", "library", "status", "time", "alarms")
        self.tree = ttk.Treeview(self.output, columns=cols, show="headings", height=8)
        for col, title, w in (
            ("detector", "Detector", 160),
            ("library", "Library", 180),
            ("status", "Status", 110),
            ("time", "Time", 90),
            ("alarms", "Alarms", 80),
        ):
            self.tree.heading(col, text=title)
            self.tree.column(col, width=w, anchor="w" if col in ("detector", "library") else "center")
        self.tree.pack(fill="x", padx=14, pady=(0, 10))

        ctk.CTkLabel(
            self.output,
            text="Log",
            font=("Roboto", 13, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(2, 4))

        self.log_box = ctk.CTkTextbox(self.output, font=("Consolas", 12))
        self.log_box.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self.log_box.configure(state="disabled")

        self.refresh()

    def refresh(self) -> None:
        """Sync summary and table with current state."""
        state = self.app.app_state
        enabled = [d for d in state.detectors if d.enabled]
        rows_txt = f"{len(state.data)} rows" if state.data is not None else "no data loaded"
        self.summary_label.configure(
            text=f"Runs {len(enabled)} enabled detector(s) on {rows_txt} with seed {state.seed}."
        )
        if not self.runner.is_running():
            self._populate_table()

    def _populate_table(self) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        state = self.app.app_state
        for spec in state.detectors:
            if not spec.enabled:
                continue
            meta = get_detector_meta(spec.key)
            res = state.results.get(spec.key)
            status = res.status.capitalize() if res else "Queued"
            runtime = f"{res.runtime_s:.2f} s" if res else "–"
            alarms = str(len(res.alarms)) if res else "–"
            self.tree.insert("", "end", iid=spec.key, values=(spec.name, meta.class_path, status, runtime, alarms))

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{stamp}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _start_run(self) -> None:
        state = self.app.app_state
        if state.data is None or not state.value_col:
            self._append_log("Cannot start: load a CSV on the Data tab first.")
            return
        enabled = [d for d in state.detectors if d.enabled]
        if not enabled:
            self._append_log("Cannot start: tick at least one detector on the Detectors tab.")
            return

        try:
            timeout_s = max(1.0, float(self.timeout_entry.get().strip()))
        except ValueError:
            timeout_s = 60.0

        self._total = len(enabled)
        self._populate_table()
        self.run_button.configure(state="disabled")
        self.progress.reset()
        self.progress.pack(fill="x", padx=10, pady=6)
        self.status_header.configure(text=f"Running {self._total} detector(s) · seed {state.seed}")
        self._append_log(f"Starting {self._total} detector(s) with seed {state.seed}")

        self.runner.start(enabled, state.series, seed=state.seed, timeout_s=timeout_s)
        self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        done = False
        while not self.runner.progress_queue.empty():
            ev: ProgressEvent = self.runner.progress_queue.get_nowait()
            if ev.kind == "started":
                self.tree.set(ev.detector_key, "status", "Running")
                self.progress.update_progress(ev.index / max(1, ev.total), ev.message)
                self._append_log(ev.message)
            elif ev.kind == "detector_done" and ev.result is not None:
                res = ev.result
                self.tree.set(ev.detector_key, "status", res.status.replace("_", " ").capitalize())
                self.tree.set(ev.detector_key, "time", f"{res.runtime_s:.2f} s")
                self.tree.set(ev.detector_key, "alarms", str(len(res.alarms)))
                self.progress.update_progress((ev.index + 1) / max(1, ev.total), ev.message)
                self._append_log(ev.message)
            elif ev.kind in ("finished", "cancelled"):
                self._append_log(ev.message)
                done = True

        if done or not self.runner.is_running():
            self.app.app_state.results = dict(self.runner.results)
            self.progress.pack_forget()
            self.run_button.configure(state="normal")
            self.status_header.configure(text=f"Last run complete · seed {self.app.app_state.seed}")
            self.app.refresh_all()
        else:
            self.after(100, self._poll_queue)