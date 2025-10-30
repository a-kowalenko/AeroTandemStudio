import tkinter as tk
from tkinter import ttk


class LoadingWindow(tk.Toplevel):
    """
    Ein einfaches "modal" Fenster, das eine Ladeanimation anzeigt,
    während im Hintergrund ein Thread arbeitet.
    """

    def __init__(self, master, text="Bitte warten..."):
        super().__init__(master)
        self.title("Verarbeitung")
        self.geometry("300x120")
        self.resizable(False, False)

        # Machen Sie das Fenster "modal" (blockiert andere Fenster)
        self.transient(master)
        self.grab_set()

        # Zentrieren Sie das Fenster relativ zum Hauptfenster
        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        self.geometry(f"+{master_x + (master_w - 300) // 2}+{master_y + (master_h - 120) // 2}")

        self.label = tk.Label(self, text=text, padx=20, pady=10, font=("Helvetica", 10))
        self.label.pack(pady=(10, 0))

        self.progress = ttk.Progressbar(self, mode='indeterminate', length=260)
        self.progress.pack(pady=10, padx=20, fill='x')
        self.progress.start(15)  # Startet die "schwebende" Animation

        self.update_idletasks()  # Stellt sicher, dass das Fenster sofort gezeichnet wird

