# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# --- 📋 Version aus VERSION.txt lesen ---
# HINWEIS: Version wird von build.py hochgezählt, bevor PyInstaller startet
VERSION_FILE = Path("VERSION.txt")
CURRENT_VERSION = VERSION_FILE.read_text(encoding="utf-8").strip()
print(f"[BUILD] Baue Version: {CURRENT_VERSION}")

# --- 🏗️ PyInstaller Konfiguration ---

pyzbar_libs = collect_dynamic_libs("pyzbar")
print(f"[BUILD] Gesammelte pyzbar dynamische Bibliotheken: {len(pyzbar_libs)}")

tkinterdnd2_datas = collect_data_files("tkinterdnd2")
print(f"[BUILD] Gesammelte tkinterdnd2 Dateien: {len(tkinterdnd2_datas)}")

runtime_hooks = []
if sys.platform == "win32":
    runtime_hooks.append("pyinstaller_runtime_hook_pyzbar.py")

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=pyzbar_libs,
    datas=[
        ('VERSION.txt', '.'),   # Version-Datei mit einbinden
        ('assets', 'assets'),   # Assets-Ordner mitnehmen
        *tkinterdnd2_datas,
    ],
    hiddenimports=[
        'pyzbar', 'pyzbar.pyzbar', 'vlc', 'PIL._tkinter_finder',
        'tkinterdnd2', 'tkinterdnd2.TkinterDnD',
    ],
    hookspath=['.'],
    hooksconfig={},
    runtime_hooks=runtime_hooks,
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Linux: Remove libvlc from bundled binaries so python-vlc uses the system one natively
if sys.platform == 'linux':
    a.binaries = [x for x in a.binaries if not x[0].startswith('libvlc')]

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
    upx_exclude=['libtkdnd*.dll', 'libtkdnd*.so', 'libtkdnd*.dylib'],
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
    upx_exclude=['libtkdnd*.dll', 'libtkdnd*.so', 'libtkdnd*.dylib'],
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
