# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

# --- 📋 Version aus VERSION.txt lesen ---
# HINWEIS: Version wird von build.py hochgezählt, bevor PyInstaller startet
VERSION_FILE = Path("VERSION.txt")
CURRENT_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
print(f"[BUILD] Baue Version: {CURRENT_VERSION}")

# --- 🏗️ PyInstaller Konfiguration ---

# pyzbar DLLs werden von build.py in pyzbar_binaries.txt geschrieben
import json
pyzbar_libs = []
pyzbar_file = Path("pyzbar_binaries.txt")
if pyzbar_file.exists():
    try:
        pyzbar_libs = json.loads(pyzbar_file.read_text(encoding="utf-8"))
        print(f"[BUILD] Geladen: {len(pyzbar_libs)} pyzbar DLLs aus pyzbar_binaries.txt")
    except Exception as e:
        print(f"[BUILD] Warnung: Konnte pyzbar_binaries.txt nicht lesen: {e}")
else:
    print("[BUILD] Warnung: pyzbar_binaries.txt nicht gefunden!")

if sys.platform != 'win32':
    pyzbar_libs = []

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=pyzbar_libs,  # pyzbar DLLs von build.py
    datas=[
        ('VERSION.txt', '.'),   # Version-Datei mit einbinden
        ('assets', 'assets')    # Assets-Ordner mitnehmen
    ],
    hiddenimports=['pyzbar', 'pyzbar.pyzbar'],  # pyzbar explizit importieren
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

if sys.platform == 'win32':
    icon_path = os.path.join('assets', 'icon.ico')
    version_file = 'version_info.txt'
else:
    icon_path = os.path.join('assets', 'logo.png')
    version_file = None

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Aero Tandem Studio",  # 👈 OHNE Version im EXE-Namen (konstant!)
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[icon_path],
    version=version_file,  # 👈 Version-Metadaten einbetten! (Nur Windows)
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=f"Aero Tandem Studio v{CURRENT_VERSION}",
)

if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Aero Tandem Studio.app',
        icon=icon_path,
        bundle_identifier=None,
        version=CURRENT_VERSION,
        info_plist={
            'NSHighResolutionCapable': 'True',
            'LSBackgroundOnly': 'False',
            'NSRequiresAquaSystemAppearance': 'False'
        }
    )
