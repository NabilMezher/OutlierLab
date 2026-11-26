from __future__ import annotations

from typing import Callable

import customtkinter as ctk


class ProgressOverlay(ctk.CTkFrame):
    """Inline sidebar progress bar, status label, and Cancel button (NLP Pilot pattern)."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        on_cancel: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, corner_radius=8)
        self._on_cancel = on_cancel

        self.progressbar = ctk.CTkProgressBar(self)
        self.progressbar.set(0.0)
        self.progressbar.pack(fill="x", padx=10, pady=(10, 4))

        self.message_label = ctk.CTkLabel(
            self,
            text="Working…",
            font=("Roboto", 11),
            wraplength=210,
        )
        self.message_label.pack(padx=10, pady=(0, 6))

        self.cancel_button = ctk.CTkButton(
            self,
            text="Cancel",
            width=90,
            height=28,
            fg_color=("#a0a0a0", "#444444"),
            hover_color=("#888888", "#333333"),
            command=self._handle_cancel,
        )
        self.cancel_button.pack(pady=(0, 10))

    def _handle_cancel(self) -> None:
        self.cancel_button.configure(state="disabled")
        self.message_label.configure(text="Cancelling…")
        if self._on_cancel is not None:
            self._on_cancel()

    def update_progress(self, fraction: float, message: str) -> None:
        """Update bar progress (0.0–1.0) and status message."""
        self.progressbar.set(max(0.0, min(1.0, fraction)))
        self.message_label.configure(text=message)

    def reset(self) -> None:
        """Reset controls for a new run."""
        self.progressbar.set(0.0)
        self.message_label.configure(text="Working…")
        self.cancel_button.configure(state="normal")