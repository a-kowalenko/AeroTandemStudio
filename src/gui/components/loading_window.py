import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class LoadingWindow(tk.Toplevel):
    """
    Ein einfaches "modal" Fenster, das eine Ladeanimation anzeigt,
    während im Hintergrund ein Thread arbeitet.
    """

    def __init__(self, master, text="Bitte warten...", on_cancel: Optional[Callable[[], None]] = None):
        super().__init__(master)
        self.title("Verarbeitung")
        self._on_cancel = on_cancel
        height = 155 if on_cancel else 120
        self.geometry(f"300x{height}")
        self.resizable(False, False)

        # Machen Sie das Fenster "modal" (blockiert andere Fenster)
        self.transient(master)
        self.grab_set()

        # Zentrieren Sie das Fenster relativ zum Hauptfenster
        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        self.geometry(f"+{master_x + (master_w - 300) // 2}+{master_y + (master_h - height) // 2}")

        self.label = tk.Label(self, text=text, padx=20, pady=10, font=("Helvetica", 10))
        self.label.pack(pady=(10, 0))

        self.progress = ttk.Progressbar(self, mode='indeterminate', length=260)
        self.progress.pack(pady=10, padx=20, fill='x')
        self.progress.start(15)  # Startet die "schwebende" Animation

        if on_cancel is not None:
            self.cancel_button = tk.Button(
                self,
                text="Abbrechen",
                command=self._handle_cancel,
                width=12,
            )
            self.cancel_button.pack(pady=(0, 10))

        self.update_idletasks()  # Stellt sicher, dass das Fenster sofort gezeichnet wird

    def _handle_cancel(self):
        if self._on_cancel is not None:
            self._on_cancel()
        if hasattr(self, "cancel_button"):
            self.cancel_button.config(state=tk.DISABLED)

    def update_text(self, text: str):
        """Aktualisiert den angezeigten Ladetext (z. B. Fortschritt)."""
        self.label.config(text=text)
        self.update_idletasks()

