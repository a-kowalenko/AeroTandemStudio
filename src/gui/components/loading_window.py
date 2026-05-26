import tkinter as tk
from tkinter import ttk
from typing import Callable, List, Optional


class LoadingWindow(tk.Toplevel):
    """
    Ein einfaches "modal" Fenster, das eine Ladeanimation anzeigt,
    während im Hintergrund ein Thread arbeitet.
    """

    def __init__(
        self,
        master,
        text="Bitte warten...",
        on_cancel: Optional[Callable[[], None]] = None,
        *,
        detail_mode: bool = False,
    ):
        super().__init__(master)
        self.title("Verarbeitung")
        self._on_cancel = on_cancel
        self._detail_mode = detail_mode

        width = 520 if detail_mode else 300
        height = 220 if detail_mode and on_cancel else (195 if detail_mode else (155 if on_cancel else 120))
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)

        self.transient(master)
        self.grab_set()

        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        self.geometry(
            f"+{master_x + (master_w - width) // 2}+{master_y + (master_h - height) // 2}"
        )

        if detail_mode:
            self.status_label = tk.Label(
                self,
                text="Prüfe Video auf QR-Code",
                padx=20,
                pady=2,
                font=("Helvetica", 10),
            )
            self.status_label.pack(pady=(10, 0))

            self.progress_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 9),
                fg="#555555",
            )
            self.progress_label.pack()

            self.file_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 11, "bold"),
                wraplength=480,
                justify="center",
            )
            self.file_label.pack(pady=(4, 0))

            self.active_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 10),
                wraplength=480,
                justify="center",
                fg="#333333",
            )
            self._active_label_packed = False
        else:
            self.label = tk.Label(self, text=text, padx=20, pady=10, font=("Helvetica", 10))
            self.label.pack(pady=(10, 0))

        bar_width = 460 if detail_mode else 260
        self.progress = ttk.Progressbar(self, mode="indeterminate", length=bar_width)
        self.progress.pack(pady=10, padx=20, fill="x")
        self.progress.start(15)

        if on_cancel is not None:
            self.cancel_button = tk.Button(
                self,
                text="Abbrechen",
                command=self._handle_cancel,
                width=12,
            )
            self.cancel_button.pack(pady=(0, 10))

        if detail_mode:
            primary = ""
            if text:
                primary = text.split("\n")[-1] if "\n" in text else text
            self.update_qr_progress(
                "Prüfe Video auf QR-Code",
                "Clip 1 von 1",
                primary or "—",
            )

        self.update_idletasks()

    def _handle_cancel(self):
        if self._on_cancel is not None:
            self._on_cancel()
        if hasattr(self, "cancel_button"):
            self.cancel_button.config(state=tk.DISABLED)

    def update_text(self, text: str):
        """Aktualisiert den angezeigten Ladetext (einfacher Modus)."""
        if self._detail_mode and hasattr(self, "file_label"):
            lines = text.split("\n")
            primary = lines[-1] if lines else text
            status = lines[0] if len(lines) > 1 else "Bitte warten..."
            self.update_qr_progress(status, "", primary)
            return
        if hasattr(self, "label"):
            self.label.config(text=text)
        self.update_idletasks()

    def update_qr_progress(
        self,
        status: str,
        progress_text: str,
        primary_file: str,
        active_files: Optional[List[str]] = None,
    ):
        """Detail-Anzeige für QR-Suche (aktueller Clip / parallele Clips)."""
        if not self._detail_mode:
            combined = status
            if progress_text:
                combined += f"\n{progress_text}"
            if primary_file:
                combined += f"\n{primary_file}"
            self.update_text(combined)
            return

        self.status_label.config(text=status)
        self.progress_label.config(text=progress_text)

        active = [f for f in (active_files or []) if f]
        if len(active) > 1:
            self.file_label.config(text=active[0])
            self.active_label.config(text="\n".join(active[1:]))
            if not self._active_label_packed:
                self.active_label.pack(pady=(0, 4))
                self._active_label_packed = True
        else:
            display_name = primary_file or (active[0] if active else "")
            self.file_label.config(text=display_name)
            if self._active_label_packed:
                self.active_label.pack_forget()
                self._active_label_packed = False

        self.update_idletasks()
