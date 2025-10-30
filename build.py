#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vollständiger Build-Prozess für Aero Tandem Studio
Verwendung:
    python build.py              # Nur PyInstaller Build (Build-Version +1)
    python build.py setup        # PyInstaller + NSIS Installer (Build-Version +1)
    python build.py minor        # Nur PyInstaller (Minor-Version +1)
    python build.py minor setup  # PyInstaller + Installer (Minor-Version +1)
    python build.py patch setup  # PyInstaller + Installer (Patch-Version +1)
    python build.py major setup  # PyInstaller + Installer (Major-Version +1)
"""
import os
import sys
import subprocess
import shutil
from pathlib import Path

def bump_version(level="build"):
    """
    Liest VERSION.txt, erhöht die gewählte Versionskomponente und schreibt sie zurück.

    Args:
        level: "major", "minor", "patch" oder "build"

    Returns:
        Die neue Version als String
    """
    version_file = Path("VERSION.txt")
    version = version_file.read_text(encoding="utf-8").strip()
    parts = [int(p) for p in version.split(".")]
    while len(parts) < 4:
        parts.append(0)

    major, minor, patch, build = parts

    if level == "major":
        major += 1
        minor = patch = build = 0
    elif level == "minor":
        minor += 1
        patch = build = 0
    elif level == "patch":
        patch += 1
        build = 0
    elif level == "build":
        build += 1
    else:
        raise ValueError(f"Unknown level '{level}', use: major | minor | patch | build")

    new_version = f"{major}.{minor}.{patch}.{build}"
    version_file.write_text(new_version + "\n", encoding="utf-8")
    print(f"   Version: {version} → {new_version}")
    return new_version

def find_pyzbar_dlls():
    """
    Findet pyzbar DLLs im site-packages Verzeichnis.
    Schreibt die Pfade in pyzbar_binaries.txt für PyInstaller.
    """
    import site
    import glob

    pyzbar_libs = []
    for site_dir in site.getsitepackages():
        pyzbar_path = os.path.join(site_dir, 'pyzbar')
        if os.path.exists(pyzbar_path):
            # Alle .dll Dateien im pyzbar Ordner finden
            dll_files = glob.glob(os.path.join(pyzbar_path, '*.dll'))
            for dll in dll_files:
                pyzbar_libs.append((dll, 'pyzbar'))
            print(f"   ✅ Gefunden: {len(dll_files)} pyzbar DLLs in {pyzbar_path}")
            break

    if not pyzbar_libs:
        print("   ⚠️  Warnung: Keine pyzbar DLLs gefunden!")

    # Schreibe in temporäre Datei für .spec
    binaries_file = Path("pyzbar_binaries.txt")
    import json
    binaries_file.write_text(json.dumps(pyzbar_libs), encoding="utf-8")

    return pyzbar_libs

def update_version_info():
    """
    Aktualisiert version_info.txt mit der aktuellen Version aus VERSION.txt
    Diese Datei wird von PyInstaller für Windows-Metadaten verwendet.
    """
    # Version aus VERSION.txt lesen
    version_file = Path("VERSION.txt")
    version_str = version_file.read_text(encoding="utf-8").strip()

    # Version in Tuple konvertieren (z.B. "0.1.0.1" → (0, 1, 0, 1))
    version_parts = tuple(int(x) for x in version_str.split('.'))

    # Auf 4 Teile auffüllen falls nötig
    while len(version_parts) < 4:
        version_parts = version_parts + (0,)

    # version_info.txt Template
    version_info_content = f'''# UTF-8
#
# Version Information für Aero Tandem Studio
# Diese Datei wird von PyInstaller in die .exe eingebettet
# AUTOMATISCH GENERIERT - Nicht manuell bearbeiten!
#

VSVersionInfo(
  ffi=FixedFileInfo(
    # filevers und prodvers müssen als Tuple mit 4 Zahlen angegeben werden
    filevers={version_parts},
    prodvers={version_parts},
    # Enthält eine Bitmaske, die verschiedene Flags spezifiziert
    mask=0x3f,
    flags=0x0,
    # Betriebssystem für das diese Datei bestimmt ist
    OS=0x40004,
    # Allgemeiner Dateityp
    fileType=0x1,
    # Funktion der Datei
    subtype=0x0,
    # Erstellungsdatum der Datei
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        u'040704B0',  # Deutsch (0x0407), Unicode (0x04B0)
        [StringStruct(u'CompanyName', u'Andreas Kowalenko'),
        StringStruct(u'FileDescription', u'Aero Tandem Studio'),
        StringStruct(u'FileVersion', u'{version_str}'),
        StringStruct(u'InternalName', u'AeroTandemStudio'),
        StringStruct(u'LegalCopyright', u'Copyright © 2025 Andreas Kowalenko'),
        StringStruct(u'OriginalFilename', u'Aero Tandem Studio.exe'),
        StringStruct(u'ProductName', u'Aero Tandem Studio'),
        StringStruct(u'ProductVersion', u'{version_str}')])
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [0x0407, 0x04B0])])  # Deutsch, Unicode
  ]
)
'''

    # Schreibe aktualisierte version_info.txt
    version_info_file = Path("version_info.txt")
    version_info_file.write_text(version_info_content, encoding="utf-8")

    print(f"   ✅ version_info.txt aktualisiert mit Version {version_str}")

def find_makensis():
    """Findet makensis.exe in üblichen Installationspfaden"""
    possible_paths = [
        r"C:\Program Files (x86)\NSIS\makensis.exe",
        r"C:\Program Files\NSIS\makensis.exe",
        shutil.which("makensis"),  # Im PATH
    ]

    for path in possible_paths:
        if path and Path(path).exists():
            return path

    return None

def main():
    print("=" * 70)
    print("🚀 Aero Tandem Studio - Build-Prozess")
    print("=" * 70)
    print()

    # 1. Parameter analysieren
    args = [arg.lower() for arg in sys.argv[1:]]

    # Prüfe ob 'setup' Parameter übergeben wurde
    create_installer = 'setup' in args

    # Entferne 'setup' aus den Args, um Build-Level zu bestimmen
    build_levels = [arg for arg in args if arg != 'setup']
    level = build_levels[0] if build_levels else "build"

    # Validiere Build-Level
    valid_levels = ["build", "minor", "patch", "major"]
    if level not in valid_levels:
        print(f"❌ Ungültiger Build-Level: '{level}'")
        print(f"   Gültige Werte: {', '.join(valid_levels)}")
        return 1

    print(f"📋 Build-Level: {level}")
    print(f"📦 Installer erstellen: {'Ja' if create_installer else 'Nein'}")
    print()

    # 2. Version hochzählen
    print("📋 Aktualisiere Version...")
    new_version = bump_version(level)

    # 3. Version Info aktualisieren
    update_version_info()

    # 4. pyzbar DLLs finden
    print("📋 Suche pyzbar DLLs...")
    find_pyzbar_dlls()
    print()

    # 5. PyInstaller Build
    total_steps = 2 if create_installer else 1
    print(f"🔨 Schritt 1/{total_steps}: PyInstaller Build")
    print("-" * 70)

    try:
        subprocess.run(["pyinstaller", "Aero Tandem Studio.spec"], check=True)
        print()
        print("✅ PyInstaller Build erfolgreich!")
        print()
    except subprocess.CalledProcessError as e:
        print()
        print(f"❌ PyInstaller Build fehlgeschlagen: {e}")
        return 1

    # 6. NSIS Installer erstellen (nur wenn 'setup' Parameter übergeben wurde)
    if not create_installer:
        print("ℹ️  NSIS Installer wird NICHT erstellt (kein 'setup' Parameter)")
        print("   Zum Erstellen des Installers verwenden Sie: python build.py setup")
        print()
    else:
        print(f"📦 Schritt 2/{total_steps}: NSIS Installer erstellen")
        print("-" * 70)

        makensis_path = find_makensis()

        if not makensis_path:
            print("⚠️  NSIS (makensis.exe) nicht gefunden!")
            print()
            print("Der PyInstaller Build war erfolgreich, aber der Installer konnte")
            print("nicht erstellt werden.")
            print()
            print("Bitte installieren Sie NSIS von: https://nsis.sourceforge.io/")
            print()
            print("Sie können den Installer auch manuell erstellen mit:")
            print("  makensis installer.nsi")
            print()
            return 0  # Kein Fehler, nur Warnung

        print(f"NSIS gefunden: {makensis_path}")

        try:
            result = subprocess.run(
                [makensis_path, "installer.nsi"],
                capture_output=True,
                text=True,
                encoding='cp850'  # Windows Konsolen-Encoding
            )

            # NSIS gibt manchmal Exit-Code 0 auch bei Warnungen zurück
            if result.returncode == 0:
                print()
                print("✅ NSIS Installer erfolgreich erstellt!")
                print()

                # Zeige wo der Installer liegt
                version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
                installer_name = f"AeroTandemStudio_Installer_v{version}.exe"

                if Path(installer_name).exists():
                    installer_size = Path(installer_name).stat().st_size / (1024 * 1024)
                    print(f"📦 Installer: {installer_name} ({installer_size:.1f} MB)")

                print()
            else:
                print()
                print(f"❌ NSIS Installer Build fehlgeschlagen (Exit Code: {result.returncode})")
                if result.stderr:
                    print("Fehlerausgabe:")
                    print(result.stderr)
                return 1

        except Exception as e:
            print()
            print(f"❌ Fehler beim Erstellen des Installers: {e}")
            return 1

    # 7. Erfolgsmeldung
    print("=" * 70)
    print("🎉 Build-Prozess erfolgreich abgeschlossen!")
    print("=" * 70)
    print()

    # Zeige erstellte Dateien
    version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
    build_dir = Path(f"dist/Aero Tandem Studio v{version}")
    installer_file = Path(f"AeroTandemStudio_Installer_v{version}.exe")

    print("📁 Erstellte Dateien:")
    print()
    if build_dir.exists():
        exe_path = build_dir / "Aero Tandem Studio.exe"
        if exe_path.exists():
            exe_size = exe_path.stat().st_size / (1024 * 1024)
            print(f"  ✅ {exe_path}")
            print(f"     ({exe_size:.1f} MB)")

    if create_installer and installer_file.exists():
        installer_size = installer_file.stat().st_size / (1024 * 1024)
        print(f"  ✅ {installer_file}")
        print(f"     ({installer_size:.1f} MB)")

    print()

    if create_installer:
        print("🚀 Bereit zur Verteilung!")
    else:
        print("💡 Tipp: Verwenden Sie 'python build.py setup' um auch den Installer zu erstellen")

    print()

    return 0

if __name__ == "__main__":
    sys.exit(main())
