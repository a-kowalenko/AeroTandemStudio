import sys
import os


def get_resource_path(relative_path):
    """
    Ermittelt den korrekten Pfad zu einer Ressource,
    egal ob im IDE-Modus, als --onefile EXE oder als --onedir EXE.
    """
    if getattr(sys, 'frozen', False):
        # Fall 1: App ist "eingefroren" (gepackt von PyInstaller)

        if hasattr(sys, '_MEIPASS'):
            # Fall 1a: --onefile Bundle
            # Assets werden in _MEIPASS (einem Temp-Ordner) extrahiert.
            # Dieser Fall tritt ein, wenn Sie --add-data mit --onefile verwenden.
            base_path = sys._MEIPASS
        else:
            # Fall 1b: --onedir Bundle (Ihr neuer Anwendungsfall)
            # Die EXE liegt im Stammverzeichnis der Installation.
            # sys.executable ist der Pfad zu C:\Programme\Aero...\AeroTandemStudio.exe
            base_path = os.path.dirname(os.path.abspath(sys.executable))

    else:
        # Fall 2: App läuft im IDE-Modus (nicht "eingefroren")
        # Annahme: Diese Datei (path_helper.py) liegt in /app/utils/
        # Wir wollen das Haupt-Projektverzeichnis (das über /app/ liegt)
        base_path = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

    return os.path.join(base_path, relative_path)
