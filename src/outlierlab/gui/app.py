from __future__ import annotations

import customtkinter as ctk

from outlierlab.core.state import ComparatorState
from outlierlab.gui.compare_tab import CompareTab
from outlierlab.gui.detectors_tab import DetectorsTab
from outlierlab.gui.run_tab import RunTab
from outlierlab.gui.settings_window import SettingsWindow

TAB_NAMES = ["Data", "Events", "Detectors", "Run", "Compare", "Scores", "Export"]


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Anomaly Comparator")
        self.geometry("1180x720")
        # Not "self.state": Tk windows already have a state() method.
        self.app_state = ComparatorState()

        header = ctk.CTkFrame(self, corner_radius=0)
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text="Anomaly Comparator",
            text_color="#0062cc",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(side="left", padx=12, pady=6)
        self.file_label = ctk.CTkLabel(header, text="No file loaded")
        self.file_label.pack(side="left", padx=8)

        ctk.CTkButton(
            header,
            text="⚙",
            width=34,
            height=28,
            fg_color=("#d0d0d0", "#444444"),
            text_color=("#222222", "#ffffff"),
            hover_color=("#bbbbbb", "#333333"),
            command=self._open_settings,
        ).pack(side="right", padx=10, pady=6)

        self.seed_chip = ctk.CTkLabel(header, text=f"Seed {self.app_state.seed}")
        self.seed_chip.pack(side="right", padx=6)

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for name in TAB_NAMES:
            self.tabs.add(name)

        self.tab_frames: dict[str, object] = {}
        self.tab_frames["Detectors"] = DetectorsTab(self.tabs.tab("Detectors"), self)
        self.tab_frames["Detectors"].pack(fill="both", expand=True)
        self.tab_frames["Run"] = RunTab(self.tabs.tab("Run"), self)
        self.tab_frames["Run"].pack(fill="both", expand=True)
        self.tab_frames["Compare"] = CompareTab(self.tabs.tab("Compare"), self)
        self.tab_frames["Compare"].pack(fill="both", expand=True)

        for name in ("Data", "Events", "Scores", "Export"):
            ctk.CTkLabel(self.tabs.tab(name), text=f"{name} tab coming soon").pack(
                pady=40
            )

    def _open_settings(self) -> None:
        SettingsWindow(self, self.app_state, on_save=self.refresh_all)

    def refresh_all(self) -> None:
        """Call after the state changes so every tab can redraw."""
        self.file_label.configure(text=self.app_state.source_path or "No file loaded")
        self.seed_chip.configure(text=f"Seed {self.app_state.seed}")
        for frame in self.tab_frames.values():
            if hasattr(frame, "refresh"):
                frame.refresh()


def main() -> None:
    ctk.set_appearance_mode("system")
    App().mainloop()
