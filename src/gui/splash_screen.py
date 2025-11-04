"""
Splash Screen für Aero Tandem Studio
Zeigt einen Lade-Bildschirm während des App-Starts
"""
import tkinter as tk
import os
from .components.circular_spinner import CircularSpinner

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class SplashScreen:
    """Einfacher Splash-Screen mit Spinner für App-Start"""

    def __init__(self, parent_root, version="1.0.0"):
        """
        Args:
            parent_root: Das Hauptfenster (tk.Tk()) - wird für Toplevel benötigt
            version: Version der App
        """
        # Verwende Toplevel statt eigenem Root (verhindert Image-Probleme)
        self.window = tk.Toplevel(parent_root)
        self.window.title("")
        self.window.overrideredirect(True)  # Kein Fensterrahmen

        # Fenstergröße
        width = 400
        height = 350  # Erhöht für Logo

        # Zentriere das Fenster
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = (screen_width - width) // 2
        y = (screen_height - height) // 2

        self.window.geometry(f"{width}x{height}+{x}+{y}")
        self.window.configure(bg='white')

        # Bringe Fenster in den Vordergrund
        self.window.lift()
        self.window.attributes('-topmost', True)

        # Container
        container = tk.Frame(self.window, bg='white')
        container.place(relx=0.5, rely=0.5, anchor='center')

        # Logo (falls vorhanden)
        logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo.png"))
        if os.path.exists(logo_path) and PIL_AVAILABLE:
            try:
                img = Image.open(logo_path)
                # Skaliere Logo auf 80x80
                img = img.resize((80, 80), Image.Resampling.LANCZOS)
                self.logo_image = ImageTk.PhotoImage(img)
                logo_label = tk.Label(container, image=self.logo_image, bg='white', bd=0)
                logo_label.pack(pady=(0, 10))
            except Exception as e:
                print(f"Konnte Logo nicht laden: {e}")
                self.logo_image = None
        else:
            self.logo_image = None

        # Titel
        title = tk.Label(
            container,
            text="Aero Tandem Studio",
            font=("Arial", 20, "bold"),
            bg='white',
            fg='#009d8b'  # Gleiche Farbe wie in der App
        )
        title.pack(pady=(0, 20))

        # Spinner
        self.spinner = CircularSpinner(container, size=50, line_width=5)
        self.spinner.pack(pady=20)

        # Lade-Text
        self.loading_label = tk.Label(
            container,
            text="Wird geladen...",
            font=("Arial", 11),
            bg='white',
            fg='#666666'
        )
        self.loading_label.pack(pady=(10, 0))

        # Version
        version_label = tk.Label(
            container,
            text=f"Version {version}",
            font=("Arial", 9),
            bg='white',
            fg='#999999'
        )
        version_label.pack(pady=(5, 0))

        # Spinner starten
        self.spinner.start()

        # Forciere Darstellung
        self.window.update()

    def update_status(self, text):
        """Aktualisiert den Status-Text"""
        self.loading_label.config(text=text)
        self.window.update()

    def destroy(self):
        """Schließt den Splash-Screen"""
        if self.spinner:
            self.spinner.stop()
        self.window.destroy()

