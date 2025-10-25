import tkinter as tk
from tkinter import ttk
import math


class ProgressHandler:
    def __init__(self, parent, second_parent=None):
        self.parent = parent
        if second_parent is not None:
            self.progress_bar = ttk.Progressbar(second_parent, orient='horizontal', mode='determinate', length=280)
            self.eta_label = tk.Label(second_parent, text="", font=("Arial", 10))
        else:
            self.progress_bar = ttk.Progressbar(parent, orient='horizontal', mode='determinate', length=280)
            self.eta_label = tk.Label(parent, text="", font=("Arial", 10))
        self.status_label = tk.Label(parent, text="Status: Bereit.", font=("Arial", 10),
                                     bd=1, relief=tk.SUNKEN, anchor=tk.W)

    def pack_progress_bar(self):
        self.progress_bar.pack(pady=5)
        self.eta_label.pack(pady=2)

    def pack_status_label(self):
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X)

    def update_progress(self, step, total_steps=7):
        progress = (step / total_steps) * 100
        self.progress_bar['value'] = progress
        self.eta_label.config(text=f"{math.floor(progress)}%")
        self.parent.update_idletasks()

    def reset(self):
        self.progress_bar.pack_forget()
        self.eta_label.pack_forget()
        self.status_label.config(text="Status: Bereit.")

    def set_status(self, text):
        self.status_label.config(text=text)