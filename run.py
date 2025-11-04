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
        root = TkinterDnD.Tk()
        root.withdraw()  # Verstecke Hauptfenster vorerst

        # Zeige Splash-Screen
        splash = SplashScreen(root, version=APP_VERSION)

        # Callback für Status-Updates vom Splash
        def update_splash_status(text):
            if splash.window.winfo_exists():
                splash.update_status(text)

        # Variable um zu tracken ob Initialisierung fertig ist
        app_instance = [None]
        init_complete = [False]

        def start_app_loading():
            """Startet das Laden der App"""
            # Erstelle App mit Splash-Callback
            # Die App initialisiert sich jetzt asynchron in Schritten!
            app = VideoGeneratorApp(root=root, splash_callback=update_splash_status)
            app_instance[0] = app

            # Überwache ob Initialisierung fertig ist
            check_init_complete()

        def check_init_complete():
            """Prüft ob App-Initialisierung abgeschlossen ist"""
            # Prüfe ob _init_complete aufgerufen wurde
            # (erkennbar daran dass protocol gesetzt wurde)
            if app_instance[0] and hasattr(app_instance[0].root, '_tclCommands'):
                # App ist fertig initialisiert
                root.after(500, finish_loading)  # Kurze Pause damit man "Bereit!" sieht
            else:
                # Noch nicht fertig, prüfe in 100ms erneut
                root.after(100, check_init_complete)

        def finish_loading():
            """Beendet den Ladevorgang"""
            # Schließe Splash
            splash.destroy()

            # Zeige Hauptfenster
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