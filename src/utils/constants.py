import os
import sys
import subprocess
from src.utils.path_helper import get_resource_path

"""
Zentrale Konstanten-Datei für die Anwendung.
"""

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VERSION_FILE = os.path.join(BASE_DIR, 'VERSION.txt')

try:
    # 'utf-8-sig' verwenden, um ein BOM (ï»¿) automatisch zu entfernen
    with open(VERSION_FILE, 'r', encoding='utf-8-sig') as f:
        APP_VERSION = f.read().strip()
except FileNotFoundError:
    print(f"WARNUNG: {VERSION_FILE} nicht gefunden. Verwende Standardversion.")
    APP_VERSION = "0.0.0-dev"

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

WASSERZEICHEN_PATH = get_resource_path("assets/skydivede_wasserzeichen.png")