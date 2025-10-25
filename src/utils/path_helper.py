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


def get_base_path():
    """
    Ermittelt den Basis-Pfad der Anwendung.
    Funktioniert für die IDE und für PyInstaller (--onedir und --onefile).
    """
    # PyInstaller erstellt eine temporäre Variable '_MEIPASS'
    if hasattr(sys, '_MEIPASS'):
        # Wenn gebündelt (egal ob --onedir oder --onefile)
        return sys._MEIPASS

    # Wenn wir in der IDE laufen:
    # Gehe zwei Ebenen nach oben (von app/utils -> Projekt-Root)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def get_asset_path(relative_path):
    """
    Gibt den absoluten Pfad zu einer Asset-Datei zurück.

    Beispiel: get_asset_path("assets/logo.ico")
    """
    base_path = get_base_path()
    return os.path.join(base_path, relative_path)


def setup_vlc_paths():
    """
    Weist das 'vlc'-Modul an, die DLLs im Installationsordner zu suchen.
    MUSS VOR 'import vlc' aufgerufen werden.
    """

    # Wenn wir gebündelt sind (als EXE laufen)
    if hasattr(sys, '_MEIPASS'):
        # sys._MEIPASS ist der PyInstaller-Bundle-Ordner (z.B. dist/main)
        # Wir erwarten VLC unter C:\Programme\VideoLAN\VLC
        # Diese Pfade sind Standard für VLC
        vlc_plugin_path = os.path.join("C:", "Program Files", "VideoLAN", "VLC", "plugins")
        vlc_lib_path = os.path.join("C:", "Program Files", "VideoLAN", "VLC")

        # Prüfen, ob die Pfade existieren, bevor wir sie setzen
        if os.path.isdir(vlc_lib_path):
            os.add_dll_directory(vlc_lib_path)
        if os.path.isdir(vlc_plugin_path):
            os.environ['VLC_PLUGIN_PATH'] = vlc_plugin_path

    # Wenn wir in der IDE laufen, wird VLC über den System-PATH gefunden
    # (vorausgesetzt, VLC ist normal installiert).
