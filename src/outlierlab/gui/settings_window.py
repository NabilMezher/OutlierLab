from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from outlierlab.core.state import ComparatorState


class SettingsWindow(ctk.CTkToplevel):
    """Modal dialog for global random seed and light/dark theme."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        state: ComparatorState,
        on_save: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.state = state
        self.on_save = on_save

        self.title("Settings")
        self.geometry("380x270")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        title_lbl = ctk.CTkLabel(
            self,
            text="Settings",
            font=("Roboto", 16, "bold"),
            text_color=("#0062cc", "#6ea8fe"),
        )
        title_lbl.pack(pady=(14, 10))

        form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="x", padx=20)
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Random seed:").grid(row=0, column=0, sticky="w", pady=6)
        self.seed_entry = ctk.CTkEntry(form, width=100)
        self.seed_entry.insert(0, str(self.state.seed))
        self.seed_entry.grid(row=0, column=1, sticky="w", padx=(12, 0), pady=6)

        ctk.CTkLabel(
            form,
            text="One seed for every random step (saved with each run).",
            font=("Roboto", 11),
            text_color=("#666666", "#a3a3a3"),
            wraplength=320,
            justify="left",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ctk.CTkLabel(form, text="Theme:").grid(row=2, column=0, sticky="w", pady=6)
        current_mode = ctk.get_appearance_mode().lower()
        if current_mode not in ("system", "light", "dark"):
            current_mode = "system"
        self.theme_menu = ctk.CTkOptionMenu(
            form,
            values=["system", "light", "dark"],
            width=120,
        )
        self.theme_menu.set(current_mode)
        self.theme_menu.grid(row=2, column=1, sticky="w", padx=(12, 0), pady=6)

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            font=("Roboto", 11),
            text_color=("#c62828", "#ff6b6b"),
        )
        self.error_label.pack(pady=(4, 0))

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=20, pady=(10, 14))
        ctk.CTkButton(
            btns,
            text="Cancel",
            width=90,
            fg_color=("#a0a0a0", "#444444"),
            hover_color=("#888888", "#333333"),
            command=self.destroy,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btns,
            text="Save",
            width=90,
            fg_color="#0078ff",
            hover_color="#005dc1",
            command=self._save,
        ).pack(side="right")

    def _save(self) -> None:
        raw = self.seed_entry.get().strip()
        try:
            seed = int(raw)
        except ValueError:
            self.error_label.configure(text="Seed must be an integer (e.g. 42).")
            return

        self.state.seed = seed
        ctk.set_appearance_mode(self.theme_menu.get())
        if self.on_save is not None:
            self.on_save()
        self.destroy()