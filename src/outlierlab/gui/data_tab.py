from __future__ import annotations

from tkinter import filedialog, messagebox, ttk
from typing import Any

import customtkinter as ctk

from outlierlab.core.events import events_from_labels
from outlierlab.core.preprocess import handle_missing, missing_summary
from outlierlab.io.loader import DataError, load_csv, sampling_interval

NO_LABELS = "(none)"
POLICIES = ["interpolate", "drop", "gaps"]


class DataTab(ctk.CTkFrame):
    """Tab 1: open a CSV, pick the value column, choose how to treat missing values."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.raw = (
            None  # DataFrame straight from load_csv, before missing-value handling
        )

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---------- left sidebar (same look as Sira's tabs) ----------
        side = ctk.CTkFrame(
            self, width=270, corner_radius=10, fg_color=("#e8e8e8", "#121212")
        )
        side.grid(row=0, column=0, sticky="nsew", padx=(4, 6), pady=4)
        side.grid_propagate(False)

        ctk.CTkLabel(
            side,
            text="Load Data",
            font=("Roboto", 18, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(pady=(12, 8))
        ctk.CTkButton(
            side,
            text="📂 Open CSV…",
            fg_color="#0078ff",
            hover_color="#005dc1",
            command=self.open_csv,
        ).pack(fill="x", padx=10)

        self._label(side, "Value column:")
        self.value_menu = ctk.CTkOptionMenu(
            side, values=["–"], command=lambda _: self.apply()
        )
        self.value_menu.pack(fill="x", padx=10)

        self._label(side, "Event labels (optional):")
        self.label_menu = ctk.CTkOptionMenu(
            side, values=[NO_LABELS], command=lambda _: self.apply()
        )
        self.label_menu.pack(fill="x", padx=10)
        self._hint(
            side,
            "Pick a 0/1 column if your file already marks events. "
            "They appear on the Events tab.",
        )

        self._label(side, "Missing values:")
        self.missing = ctk.CTkSegmentedButton(
            side, values=POLICIES, command=lambda _: self.apply()
        )
        self.missing.set("interpolate")
        self.missing.pack(fill="x", padx=10)
        self._hint(
            side,
            "Gaps can look like anomalies to a detector. "
            "Interpolate unless the gaps are the events.",
        )

        ctk.CTkButton(
            side,
            text="Next: mark events",
            fg_color="#0078ff",
            hover_color="#005dc1",
            command=lambda: self.app.tabs.set("Events"),
        ).pack(side="bottom", fill="x", padx=10, pady=12)

        # ---------- right output panel ----------
        out = ctk.CTkFrame(self, corner_radius=10, fg_color=("#ffffff", "#1a1a1a"))
        out.grid(row=0, column=1, sticky="nsew", padx=(6, 4), pady=4)

        ctk.CTkLabel(
            out,
            text="Data quality",
            font=("Roboto", 14, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(anchor="w", padx=12, pady=(10, 2))
        self.summary = ctk.CTkLabel(
            out, text="Open a CSV to start.", justify="left", anchor="w"
        )
        self.summary.pack(fill="x", padx=12)

        ctk.CTkLabel(
            out,
            text="Preview (first 50 rows)",
            font=("Roboto", 14, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(anchor="w", padx=12, pady=(12, 2))
        table_box = ctk.CTkFrame(out, fg_color="transparent")
        table_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.table = ttk.Treeview(table_box, show="headings")
        scroll = ttk.Scrollbar(table_box, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        self.table.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

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

    # ---------- actions ----------
    def open_csv(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if not path:
            return
        try:
            self.raw = load_csv(path)
        except DataError as exc:
            messagebox.showerror("Cannot load this file", str(exc))
            return

        state = self.app.app_state
        state.source_path = path
        state.events = []  # events belong to the old file
        state.results = {}  # so do old detector results

        cols = list(self.raw.columns)
        self.value_menu.configure(values=cols)
        self.value_menu.set(cols[0])
        self.label_menu.configure(values=[NO_LABELS, *cols])
        self.label_menu.set(NO_LABELS)
        self.apply()

    def apply(self) -> None:
        """Re-run missing-value handling and write the result into the shared state."""
        if self.raw is None:
            return
        state = self.app.app_state
        previous_analysis = (state.value_col, state.missing_policy)
        state.value_col = self.value_menu.get()
        state.missing_policy = self.missing.get()

        before = missing_summary(self.raw[state.value_col])
        cleaned = self.raw.copy()
        cleaned[state.value_col] = handle_missing(
            cleaned[state.value_col], state.missing_policy
        )
        if state.missing_policy == "drop":
            cleaned = cleaned.dropna(subset=[state.value_col])
        state.data = cleaned
        if previous_analysis != (state.value_col, state.missing_policy):
            state.results.clear()
            state.scores.clear()

        label_col = self.label_menu.get()
        if label_col != NO_LABELS and label_col != state.value_col:
            state.events = events_from_labels(cleaned[label_col])

        self._show_summary(before)
        self.app.refresh_all()  # header, Detectors, Run, Events… all redraw

    def refresh(self) -> None:
        """Called by App.refresh_all(). Nothing to redraw here: apply() already did it."""

    # ---------- display ----------
    def _show_summary(self, before: dict) -> None:
        state = self.app.app_state
        data = state.data
        step, regular = sampling_interval(data.index)
        series = data[state.value_col]
        self.summary.configure(
            text=(
                f"Rows {len(data)}    Columns {len(data.columns)}    "
                f"Missing {before['missing']} ({before['percent']}%) → {state.missing_policy}\n"
                f"Start {data.index[0]}    End {data.index[-1]}    "
                f"Interval {step}{'' if regular else ' (irregular!)'}\n"
                f"Range {series.min():.2f} to {series.max():.2f}    "
                f"Mean ± sd {series.mean():.2f} ± {series.std():.2f}    "
                f"Events from labels: {len(state.events)}"
            )
        )
        self._fill_table(data.head(50))

    def _fill_table(self, df) -> None:
        cols = [df.index.name or "time", *df.columns]
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=cols)
        for c in cols:
            self.table.heading(c, text=c)
            self.table.column(c, width=160 if c == cols[0] else 110, anchor="w")
        for ts, row in df.iterrows():
            self.table.insert(
                "", "end", values=[str(ts), *[round(v, 3) for v in row.tolist()]]
            )
