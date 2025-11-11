#!/usr/bin/env python3
"""
Hauptstartskript für den Tandem Video Generator
"""

import os
import sys

# Füge den src Ordner zum Python-Pfad hinzu
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.gui.splash_screen import SplashScreen
from src.gui.app import VideoGeneratorApp
from src.utils.constants import APP_VERSION


def main():
    """Hauptfunktion der Anwendung"""
    try:
        # Erstelle verstecktes Root-Fenster
        from tkinterdnd2 import TkinterDnD
        import tkinter as tk  # Für Icon-Handling
        root = TkinterDnD.Tk()
        root.withdraw()  # Verstecke Hauptfenster vorerst

        # Setze App-Icon global, damit es von allen Dialogen/Toplevels geerbt wird
        base_dir = os.path.dirname(__file__)
        ico_path = os.path.join(base_dir, 'assets', 'icon.ico')
        png_icon_path = os.path.join(base_dir, 'assets', 'logo.png')  # PNG/GIF wird für iconphoto benötigt

        # Windows-Taskleisten-/Titelleisten-Icon (nur für dieses Fenster, aber unkritisch)
        try:
            if os.path.exists(ico_path):
                root.iconbitmap(ico_path)
        except Exception:
            pass

        # Globale Standard-Icon-Grafik für alle zukünftigen Toplevels/Dialogs setzen
        try:
            if os.path.exists(png_icon_path):
                _icon_img = tk.PhotoImage(file=png_icon_path)
                root.iconphoto(True, _icon_img)  # True => als Default für alle neuen Toplevels
                root._app_icon_img = _icon_img  # Referenz halten, damit das Bild nicht vom GC eingesammelt wird
        except Exception:
            pass

        # Zeige Splash-Screen (erbt nun das Icon automatisch)
        splash = SplashScreen(root, version=APP_VERSION)

        # Callback für Status-Updates vom Splash
        def update_splash_status(text):
            if splash.window.winfo_exists():
                splash.update_status(text)

        # Variable um App-Instanz zu speichern
        app_instance = [None]

        def start_app_loading():
            """Startet das Laden der App"""
            # Erstelle App mit Splash-Callback
            app = VideoGeneratorApp(root=root, splash_callback=update_splash_status)
            app_instance[0] = app

            # Überwache Initialisierung
            check_init_complete()

        def check_init_complete():
            """Wartet bis App vollständig initialisiert ist"""
            if app_instance[0] and app_instance[0].initialization_complete:
                # Initialisierung ist fertig!
                # Kurze Pause damit "Bereit!" sichtbar ist
                root.after(300, finish_loading)
            else:
                # Noch nicht fertig, prüfe in 50ms erneut
                root.after(50, check_init_complete)

        def finish_loading():
            """Beendet den Ladevorgang"""
            # Schließe Splash
            splash.destroy()

            # JETZT erst Hauptfenster zeigen!
            root.deiconify()

            print("🎉 App gestartet!")

        # Starte App-Laden nach kurzem Delay
        root.after(200, start_app_loading)

        # Starte Event-Loop (Spinner dreht sich!)
        root.mainloop()

    except Exception as e:
        print(f"Fehler beim Starten der Anwendung: {e}")
        import traceback
        traceback.print_exc()
        input("Drücke Enter zum Beenden...")


if __name__ == "__main__":
    main()