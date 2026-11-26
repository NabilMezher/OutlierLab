from __future__ import annotations

from typing import Any

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from outlierlab.core.detectors.base import DetectorSpec
from outlierlab.core.registry import (
    DETECTOR_REGISTRY,
    default_params,
    get_detector_meta,
    list_detectors,
    make_default_spec,
)
from outlierlab.core.runner import create_detector
from outlierlab.gui.progress import ProgressOverlay  # noqa: F401 (shared style)

DEFAULT_KEYS = ("pelt", "binseg", "window", "iforest", "lof")


class DetectorsTab(ctk.CTkFrame):
    """Tab 3: choose detectors, tune parameters, and preview on the loaded series."""

    def __init__(self, master: ctk.CTkBaseClass, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.selected_idx: int = 0
        self._preview_after_id: str | None = None
        self._canvas: FigureCanvasTkAgg | None = None

        if not self.app.app_state.detectors:
            self.app.app_state.detectors = [make_default_spec(k) for k in DEFAULT_KEYS]

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
            text="Detectors",
            font=("Roboto", 18, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(pady=(12, 4))

        ctk.CTkLabel(
            self.sidebar,
            text="Tick detectors to run. Click one to edit settings.",
            font=("Roboto", 11),
            text_color=("#666666", "#a3a3a3"),
            wraplength=240,
        ).pack(padx=10, pady=(0, 8))

        self.list_frame = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.list_frame.pack(fill="both", expand=True, padx=6, pady=4)

        add_choices = [f"{m.short_name} ({m.library})" for m in list_detectors()]
        self._choice_to_key = {
            f"{m.short_name} ({m.library})": m.key for m in list_detectors()
        }
        self.add_menu = ctk.CTkOptionMenu(
            self.sidebar,
            values=["+ Add detector", *add_choices],
            fg_color="#0078ff",
            button_color="#005dc1",
            command=self._on_add_detector,
        )
        self.add_menu.set("+ Add detector")
        self.add_menu.pack(fill="x", padx=10, pady=(6, 4))

        ctk.CTkButton(
            self.sidebar,
            text="Remove selected",
            fg_color=("#a0a0a0", "#444444"),
            hover_color=("#888888", "#333333"),
            command=self._on_remove_selected,
        ).pack(fill="x", padx=10, pady=(0, 8))

        self.seed_label = ctk.CTkLabel(
            self.sidebar,
            text=f"Random seed: {self.app.app_state.seed}",
            font=("Roboto", 12, "bold"),
        )
        self.seed_label.pack(padx=10, pady=(2, 10))

        # Right output panel
        self.output = ctk.CTkFrame(
            self,
            corner_radius=10,
            fg_color=("#ffffff", "#1a1a1a"),
        )
        self.output.grid(row=0, column=1, sticky="nsew", padx=(4, 4), pady=4)

        self.refresh()

    def refresh(self) -> None:
        """Rebuild sidebar list, parameter form, and preview."""
        self.seed_label.configure(text=f"Random seed: {self.app.app_state.seed}")
        self._build_detector_list()
        self._build_detail_panel()

    def _build_detector_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()

        specs = self.app.app_state.detectors
        if specs and self.selected_idx >= len(specs):
            self.selected_idx = len(specs) - 1

        for family, heading in (("change", "Change point (ruptures)"), ("anomaly", "Anomaly (PyOD)")):
            ctk.CTkLabel(
                self.list_frame,
                text=heading,
                font=("Roboto", 12, "bold"),
                text_color=("#0062cc", "#6ea8fe"),
            ).pack(anchor="w", padx=4, pady=(6, 2))

            for idx, spec in enumerate(specs):
                if get_detector_meta(spec.key).family != family:
                    continue
                row = ctk.CTkFrame(
                    self.list_frame,
                    fg_color=("#0078ff", "#1f538d") if idx == self.selected_idx else "transparent",
                    corner_radius=6,
                )
                row.pack(fill="x", pady=2)

                var = ctk.BooleanVar(value=spec.enabled)
                chk = ctk.CTkCheckBox(
                    row,
                    text="",
                    width=22,
                    variable=var,
                    command=lambda i=idx, v=var: self._toggle_enabled(i, v.get()),
                )
                chk.pack(side="left", padx=(4, 2), pady=4)

                btn = ctk.CTkButton(
                    row,
                    text=spec.name,
                    anchor="w",
                    fg_color="transparent",
                    hover_color=("#cccccc", "#333333"),
                    text_color=("#ffffff" if idx == self.selected_idx else ("#111111", "#ffffff")),
                    command=lambda i=idx: self._select_detector(i),
                )
                btn.pack(side="left", fill="x", expand=True, padx=(0, 4), pady=2)

    def _build_detail_panel(self) -> None:
        for child in self.output.winfo_children():
            child.destroy()
        self._canvas = None

        specs = self.app.app_state.detectors
        if not specs:
            ctk.CTkLabel(self.output, text="Add a detector from the sidebar to begin.").pack(pady=40)
            return

        spec = specs[self.selected_idx]
        meta = get_detector_meta(spec.key)

        hdr = ctk.CTkFrame(self.output, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12, 2))
        ctk.CTkLabel(
            hdr,
            text=f"{meta.name}  ({meta.class_path})",
            font=("Roboto", 15, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(side="left")

        if meta.uses_seed:
            ctk.CTkLabel(
                hdr,
                text=f"uses seed {self.app.app_state.seed}",
                font=("Roboto", 11),
                text_color=("#0062cc", "#6ea8fe"),
            ).pack(side="right", padx=6)

        ctk.CTkLabel(
            self.output,
            text=meta.description,
            font=("Roboto", 12),
            text_color=("#444444", "#cccccc"),
            anchor="w",
        ).pack(fill="x", padx=16, pady=(0, 10))

        form = ctk.CTkFrame(self.output, fg_color="transparent")
        form.pack(fill="x", padx=16)
        form.grid_columnconfigure(1, weight=1)

        for r, p in enumerate(meta.params):
            ctk.CTkLabel(form, text=p.label, width=150, anchor="w").grid(
                row=r, column=0, sticky="w", pady=4
            )
            cur = spec.params.get(p.key, p.default)
            if p.kind == "choice":
                menu = ctk.CTkOptionMenu(
                    form,
                    values=list(p.choices),
                    command=lambda val, k=p.key: self._update_param(spec, k, val),
                )
                menu.set(str(cur))
                menu.grid(row=r, column=1, sticky="w", padx=8, pady=4)
            else:
                cell = ctk.CTkFrame(form, fg_color="transparent")
                cell.grid(row=r, column=1, sticky="ew", padx=8, pady=4)
                val_text = f"{cur * 100:.1f}%" if p.is_percent else str(cur)
                val_lbl = ctk.CTkLabel(cell, text=val_text, width=56, anchor="e")
                val_lbl.pack(side="right")

                steps = None
                if p.min_val is not None and p.max_val is not None and p.step:
                    steps = max(1, int(round((p.max_val - p.min_val) / p.step)))

                slider = ctk.CTkSlider(
                    cell,
                    from_=float(p.min_val or 0),
                    to=float(p.max_val or 100),
                    number_of_steps=steps,
                )
                slider.set(float(cur))
                slider.configure(
                    command=lambda v, k=p.key, kind=p.kind, pct=p.is_percent, lbl=val_lbl: self._on_slider(
                        spec, k, v, kind, pct, lbl
                    )
                )
                slider.pack(side="left", fill="x", expand=True, padx=(0, 8))

            ctk.CTkLabel(
                form,
                text=p.hint,
                font=("Roboto", 11),
                text_color=("#666666", "#a3a3a3"),
                anchor="w",
            ).grid(row=r, column=2, sticky="w", padx=(8, 0), pady=4)

        bar = ctk.CTkFrame(self.output, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkLabel(
            bar,
            text="Preview with these settings",
            font=("Roboto", 13, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        ).pack(side="left")
        ctk.CTkButton(
            bar,
            text="Reset to defaults",
            width=130,
            height=28,
            fg_color=("#a0a0a0", "#444444"),
            hover_color=("#888888", "#333333"),
            command=lambda s=spec: self._reset_defaults(s),
        ).pack(side="right")

        self.preview_host = ctk.CTkFrame(self.output, fg_color="transparent")
        self.preview_host.pack(fill="both", expand=True, padx=12, pady=(0, 10))
        self._draw_preview(spec)

    def _toggle_enabled(self, idx: int, enabled: bool) -> None:
        self.app.app_state.detectors[idx].enabled = enabled

    def _select_detector(self, idx: int) -> None:
        self.selected_idx = idx
        self.refresh()

    def _on_add_detector(self, choice: str) -> None:
        self.add_menu.set("+ Add detector")
        key = self._choice_to_key.get(choice)
        if key is None:
            return
        self.app.app_state.detectors.append(make_default_spec(key))
        self.selected_idx = len(self.app.app_state.detectors) - 1
        self.refresh()

    def _on_remove_selected(self) -> None:
        specs = self.app.app_state.detectors
        if not specs:
            return
        specs.pop(self.selected_idx)
        self.selected_idx = max(0, min(self.selected_idx, len(specs) - 1))
        self.refresh()

    def _update_param(self, spec: DetectorSpec, key: str, value: Any) -> None:
        spec.params[key] = value
        self._schedule_preview(spec)

    def _on_slider(
        self,
        spec: DetectorSpec,
        key: str,
        raw: float,
        kind: str,
        is_percent: bool,
        lbl: ctk.CTkLabel,
    ) -> None:
        val: int | float = int(round(raw)) if kind == "int" else round(float(raw), 4)
        spec.params[key] = val
        lbl.configure(text=f"{val * 100:.1f}%" if is_percent else f"{val:.3g}")
        self._schedule_preview(spec)

    def _reset_defaults(self, spec: DetectorSpec) -> None:
        spec.params = default_params(spec.key)
        self.refresh()

    def _schedule_preview(self, spec: DetectorSpec) -> None:
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
        self._preview_after_id = self.after(60, lambda: self._draw_preview(spec))

    def _draw_preview(self, spec: DetectorSpec) -> None:
        self._preview_after_id = None
        for child in self.preview_host.winfo_children():
            child.destroy()

        state = self.app.app_state
        if state.data is None or not state.value_col:
            ctk.CTkLabel(
                self.preview_host,
                text="Load a CSV on the Data tab to see a live preview.",
                text_color=("#666666", "#a3a3a3"),
            ).pack(pady=40)
            return

        series = state.series
        res = create_detector(spec.key).fit_detect(series, seed=state.seed, **spec.params)

        fig = Figure(figsize=(7.2, 2.8), dpi=100)
        if res.family == "change" or res.scores is None:
            ax = fig.add_subplot(111)
            ax.plot(series.to_numpy(dtype=float), color="#9aa3ad", linewidth=1.1)
            for start, _ in res.alarms:
                ax.axvline(start, color="#1f77b4", linestyle="--", linewidth=1.5)
            ax.set_ylabel(state.value_col)
            ax.set_title(f"{spec.name} preview ({len(res.alarms)} change points)", fontsize=10)
        else:
            ax1, ax2 = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [1.3, 1.0]})
            vals = series.to_numpy(dtype=float)
            ax1.plot(vals, color="#9aa3ad", linewidth=1.0)
            pts = [i for s, e in res.alarms for i in range(s, e + 1)]
            if pts:
                ax1.scatter(pts, vals[pts], color="#1f77b4", s=16, zorder=3)
            ax1.set_ylabel(state.value_col)
            ax2.plot(res.scores, color="#1f77b4", linewidth=1.0)
            if res.threshold is not None:
                ax2.axhline(res.threshold, color="#c62828", linestyle="--", linewidth=1.1)
            ax2.set_ylabel("score")
            ax1.set_title(f"{spec.name} preview ({len(res.alarms)} alarms)", fontsize=10)

        fig.tight_layout()
        canvas = FigureCanvasTkAgg(fig, master=self.preview_host)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._canvas = canvas