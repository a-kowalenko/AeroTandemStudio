import sys
import subprocess
from src.utils.path_helper import get_resource_path

"""
Zentrale Konstanten-Datei für die Anwendung.
"""

APP_VERSION = "0.0.3.1337"

# --- OS-Erkennung ---
IS_WINDOWS = (sys.platform == "win32")
IS_MACOS = (sys.platform == "darwin")
IS_LINUX = (sys.platform == "linux")


# --- Subprocess Flags ---

# Flag, um das Terminalfenster (CMD-Fenster) bei subprocess-Aufrufen
# unter Windows zu verbergen.
SUBPROCESS_CREATE_NO_WINDOW = 0
if IS_WINDOWS:
    SUBPROCESS_CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW

# --- Asset-Pfade ---
HINTERGRUND_PATH = get_resource_path("assets/hintergrund.png")
LOGO_PATH = get_resource_path("assets/logo.png")
PAYPAL_LOGO_PATH = get_resource_path("assets/paypal_logo.png")
VLC_PATH = get_resource_path("dependency_installer/vlc")

# --- Konfigurationsdatei-Pfad ---
CONFIG_FILE = get_resource_path("config/config.json")

# --- Log-Dateipfad ---
LOG_FILE = "logs/app.log"
