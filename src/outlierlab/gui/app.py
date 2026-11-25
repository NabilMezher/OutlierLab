import customtkinter as ctk

from outlierlab.core.state import ComparatorState

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

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        for name in TAB_NAMES:
            self.tabs.add(name)
            ctk.CTkLabel(self.tabs.tab(name), text=f"{name} tab coming soon").pack(
                pady=40
            )
        # Later: replace each placeholder, e.g.
        # DataTab(self.tabs.tab("Data"), self).pack(fill="both", expand=True)

    def refresh_all(self) -> None:
        """Call after the state changes so every tab can redraw."""
        self.file_label.configure(text=self.app_state.source_path or "No file loaded")


def main() -> None:
    ctk.set_appearance_mode("system")
    App().mainloop()
