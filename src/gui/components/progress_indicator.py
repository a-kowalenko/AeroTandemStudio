import tkinter as tk
from tkinter import ttk
import math


class ProgressHandler:
    def __init__(self, parent, second_parent=None):
        self.parent = parent
        if second_parent is not None:
            self.progress_bar = ttk.Progressbar(second_parent, orient='horizontal', mode='determinate', length=280)
            self.eta_label = tk.Label(second_parent, text="", font=("Arial", 10))
            # NEU: Encoding-Details Label
            self.encoding_details_label = tk.Label(second_parent, text="", font=("Arial", 9), fg="gray")
        else:
            self.progress_bar = ttk.Progressbar(parent, orient='horizontal', mode='determinate', length=280)
            self.eta_label = tk.Label(parent, text="", font=("Arial", 10))
            # NEU: Encoding-Details Label
            self.encoding_details_label = tk.Label(parent, text="", font=("Arial", 9), fg="gray")
        self.status_label = tk.Label(parent, text="Status: Bereit.", font=("Arial", 10),
                                     bd=1, relief=tk.SUNKEN, anchor=tk.W)

    def pack_progress_bar(self):
        self.progress_bar.pack(pady=5)
        self.eta_label.pack(pady=2)
        self.encoding_details_label.pack(pady=2)  # NEU

    def pack_progress_bar_right(self):
        """Packt die Progress-Bar-Elemente rechts ausgerichtet"""
        self.progress_bar.pack(side=tk.RIGHT, padx=(10, 0))
        self.eta_label.pack(side=tk.RIGHT, padx=(5, 0))
        self.encoding_details_label.pack(side=tk.RIGHT, padx=(5, 0))

    def pack_status_label(self):
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

    def update_progress(self, step, total_steps=7):
        progress = (step / total_steps) * 100
        self.progress_bar['value'] = progress
        self.eta_label.config(text=f"{math.floor(progress)}%")
        self.parent.update_idletasks()

    def update_encoding_progress(self, task_name="Encoding", progress=None, fps=0.0, eta=None,
                                 current_time=0.0, total_time=None, task_id=None):
        """
        Aktualisiert die Encoding-Fortschrittsanzeige mit Live-Daten.

        Args:
            task_name: Name der Encoding-Aufgabe
            progress: Fortschritt in Prozent (0-100)
            fps: Aktuelle Encoding-Geschwindigkeit in FPS
            eta: Geschätzte verbleibende Zeit (formatiert als String)
            current_time: Aktuelle encodierte Zeit in Sekunden
            total_time: Gesamtdauer in Sekunden
            task_id: Optional ID für parallele Tasks
        """
        # Update Fortschrittsbalken
        if progress is not None:
            self.progress_bar['value'] = progress

        # Update ETA Label
        if eta:
            eta_text = f"{math.floor(progress if progress else 0)}% - ETA: {eta}"
        elif progress is not None:
            eta_text = f"{math.floor(progress)}%"
        else:
            eta_text = ""

        self.eta_label.config(text=eta_text)

        # Update Encoding-Details
        details_parts = []

        if task_id is not None:
            details_parts.append(f"[Task {task_id}]")

        details_parts.append(task_name)

        if fps > 0:
            details_parts.append(f"{fps:.1f} fps")

        if current_time and total_time:
            time_str = f"{self._format_time(current_time)} / {self._format_time(total_time)}"
            details_parts.append(time_str)
        elif current_time:
            time_str = f"{self._format_time(current_time)}"
            details_parts.append(time_str)

        self.encoding_details_label.config(text=" • ".join(details_parts))

        self.parent.update_idletasks()

    def _format_time(self, seconds):
        """Formatiert Sekunden zu MM:SS Format"""
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def reset(self):
        self.progress_bar.pack_forget()
        self.eta_label.pack_forget()
        self.encoding_details_label.pack_forget()  # NEU
        self.progress_bar['value'] = 0
        self.eta_label.config(text="")
        self.encoding_details_label.config(text="")  # NEU

    def set_status(self, text):
        self.status_label.config(text=text)

