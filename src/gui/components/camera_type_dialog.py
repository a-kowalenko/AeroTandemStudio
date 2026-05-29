"""Dialog zur Auswahl Handcam vs. Outside mit optionalem Timeout."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional


class CameraTypeChoiceDialog(tk.Toplevel):
    """Nicht-blockierender Dialog; ruft Callback bei Wahl oder Timeout auf."""

    TIMEOUT_MS = 30_000

    def __init__(
        self,
        master,
        *,
        on_choice: Callable[[str], None],
        on_timeout: Callable[[], None],
        timeout_ms: int = TIMEOUT_MS,
    ):
        super().__init__(master)
        self.withdraw()
        self.title("Kamera-Typ")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._on_choice = on_choice
        self._on_timeout = on_timeout
        self._resolved = False
        self._timeout_job = None

        root = tk.Frame(self, padx=20, pady=16, bg="#f5f6f8")
        root.pack(fill="both", expand=True)

        tk.Label(
            root,
            text="Handelt es sich um Handcam- oder Outside-Aufnahmen?",
            font=("Arial", 11, "bold"),
            bg="#f5f6f8",
            wraplength=420,
            justify="center",
        ).pack(pady=(0, 8))

        self._countdown_label = tk.Label(
            root,
            text="Automatische Erkennung in 30 s …",
            font=("Arial", 9),
            fg="#555555",
            bg="#f5f6f8",
        )
        self._countdown_label.pack(pady=(0, 12))

        btn_row = tk.Frame(root, bg="#f5f6f8")
        btn_row.pack()
        tk.Button(
            btn_row,
            text="Handcam",
            width=14,
            bg="#2d89ef",
            fg="white",
            font=("Arial", 10, "bold"),
            command=lambda: self._choose("handcam"),
        ).pack(side="left", padx=6)
        tk.Button(
            btn_row,
            text="Outside",
            width=14,
            bg="#5c6bc0",
            fg="white",
            font=("Arial", 10, "bold"),
            command=lambda: self._choose("outside"),
        ).pack(side="left", padx=6)

        self._remaining_sec = max(1, timeout_ms // 1000)
        self._tick_countdown()
        self._timeout_job = self.after(timeout_ms, self._fire_timeout)

        self.update_idletasks()
        self._center_over_parent(master)
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._fire_timeout)

    def _center_over_parent(self, master) -> None:
        width = self.winfo_width()
        height = self.winfo_height()
        try:
            master.update_idletasks()
            x = master.winfo_rootx() + max(0, (master.winfo_width() - width) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - height) // 2)
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2)
        self.geometry(f"+{x}+{y}")

    def _tick_countdown(self) -> None:
        if self._resolved or not self.winfo_exists():
            return
        self._countdown_label.config(
            text=f"Automatische Erkennung in {self._remaining_sec} s …"
        )
        self._remaining_sec -= 1
        if self._remaining_sec >= 0:
            self.after(1000, self._tick_countdown)

    def _cancel_timeout(self) -> None:
        if self._timeout_job is not None:
            try:
                self.after_cancel(self._timeout_job)
            except Exception:
                pass
            self._timeout_job = None

    def _choose(self, camera_type: str) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._cancel_timeout()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
        self._on_choice(camera_type)

    def _fire_timeout(self) -> None:
        if self._resolved:
            return
        self._resolved = True
        self._cancel_timeout()
        try:
            self.grab_release()
        except Exception:
            pass
        if self.winfo_exists():
            self.destroy()
        self._on_timeout()
