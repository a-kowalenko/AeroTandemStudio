import tkinter as tk
from tkinterdnd2 import DND_FILES
import os
from tkinter import messagebox


class DragDropFrame:
    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent, relief="sunken", borderwidth=2, padx=10, pady=10)
        self.dropped_video_path_var = tk.StringVar()
        self.create_widgets()

    def create_widgets(self):
        self.drop_label = tk.Label(self.frame,
                                   text="Geschnittene .mp4 Datei hierher ziehen",
                                   font=("Arial", 12))
        self.drop_label.pack(expand=True)
        self.setup_drag_drop()

    def setup_drag_drop(self):
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        filepath = event.data.strip('{}')

        if os.path.isfile(filepath) and filepath.lower().endswith('.mp4'):
            self.dropped_video_path_var.set(filepath)
            self.drop_label.config(text=f"Datei: {os.path.basename(filepath)}", fg="green")
        else:
            self.dropped_video_path_var.set("")
            self.drop_label.config(text="Ungültig! Bitte nur eine einzelne .mp4 Datei ablegen.", fg="red")
            messagebox.showerror("Ungültiger Dateityp", "Bitte ziehen Sie nur .mp4-Dateien in das Feld.")

    def get_video_path(self):
        return self.dropped_video_path_var.get()

    def reset(self):
        self.dropped_video_path_var.set("")
        self.drop_label.config(text="Geschnittene .mp4 Datei hierher ziehen", fg="black")

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)