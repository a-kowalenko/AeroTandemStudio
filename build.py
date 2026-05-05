#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vollständiger Build-Prozess für Aero Tandem Studio
Verwendung:
    python build.py              # Nur PyInstaller Build (Build-Version +1)
    python build.py setup        # PyInstaller + NSIS Installer (Build-Version +1)
    python build.py build setup  # Explizit Build-Level "build" + Installer
    python build.py minor        # Nur PyInstaller (Minor-Version +1)
    python build.py minor setup  # PyInstaller + Installer (Minor-Version +1)
    python build.py patch setup  # PyInstaller + Installer (Patch-Version +1)
    python build.py major setup  # PyInstaller + Installer (Major-Version +1)
    python build.py major alpha setup                  # Legacy: setze Pre-Release auf "alpha"
    python build.py major -alpha setup                 # Legacy Kurzform: setze Pre-Release auf "alpha"
    python build.py major --prerelease alpha setup     # Empfohlen
    python build.py build --prerelease beta.3 setup    # Empfohlen
    python build.py none --clear-prerelease setup      # Entfernt Pre-Release ohne Versionsbump
"""
import os
import sys
import subprocess
import shutil
import re
from pathlib import Path

UNSET = object()

SEMVER_PATTERN = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:\.(?P<build>0|[1-9]\d*))?"
    r"(?:-(?P<prerelease>[0-9A-Za-z.-]+))?"
    r"(?:\+(?P<metadata>[0-9A-Za-z.-]+))?$"
)

def parse_version(version):
    """
    Parst SemVer-ähnliche Versionen:
      MAJOR.MINOR.PATCH[.BUILD][-PRERELEASE][+METADATA]
    """
    match = SEMVER_PATTERN.match(version)
    if not match:
        raise ValueError(
            f"Ungültige Version '{version}'. Erwartet: "
            "MAJOR.MINOR.PATCH[.BUILD][-PRERELEASE][+METADATA]"
        )

    return {
        "major": int(match.group("major")),
        "minor": int(match.group("minor")),
        "patch": int(match.group("patch")),
        "build": int(match.group("build")) if match.group("build") is not None else None,
        "prerelease": match.group("prerelease"),
        "metadata": match.group("metadata"),
    }

def format_version(version_data):
    """Formatiert Version aus geparsten Bestandteilen zurück in String."""
    version = f"{version_data['major']}.{version_data['minor']}.{version_data['patch']}"
    if version_data["build"] is not None:
        version += f".{version_data['build']}"
    if version_data["prerelease"]:
        version += f"-{version_data['prerelease']}"
    if version_data["metadata"]:
        version += f"+{version_data['metadata']}"
    return version

def get_windows_version_tuple(version_data):
    """
    Liefert numerische 4er-Version für Windows/NSIS.
    Pre-Release/Metadata werden hier absichtlich ignoriert.
    """
    return (
        version_data["major"],
        version_data["minor"],
        version_data["patch"],
        version_data["build"] if version_data["build"] is not None else 0,
    )

def write_windows_version_for_nsis(version_data):
    """Schreibt numerische 4er-Version für NSIS VIProductVersion."""
    numeric_version = ".".join(str(part) for part in get_windows_version_tuple(version_data))
    Path("VERSION_WINDOWS.txt").write_text(numeric_version + "\n", encoding="utf-8")
    print(f"   ✅ VERSION_WINDOWS.txt aktualisiert mit {numeric_version}")

def validate_semver_identifier(value, field_name):
    """Validiert Pre-Release/Metadata Identifier."""
    if value is None:
        return None
    if not re.fullmatch(r"[0-9A-Za-z.-]+", value):
        raise ValueError(
            f"Ungültiger {field_name}-Wert '{value}'. Erlaubt sind nur [0-9A-Za-z.-]"
        )
    return value

def parse_cli_args(raw_args):
    """
    CLI Parsing mit Rückwärtskompatibilität.
    Unterstützt:
      - Level: build|minor|patch|major|none
      - setup (an beliebiger Position)
      - Legacy: <level> <prerelease> setup oder <level> -<prerelease> setup
      - Empfohlen: --prerelease / --metadata / --clear-*
    """
    valid_levels = {"build", "minor", "patch", "major", "none"}
    level = None
    create_installer = False
    prerelease_override = UNSET
    metadata_override = UNSET

    i = 0
    while i < len(raw_args):
        arg = raw_args[i]
        lower_arg = arg.lower()

        if lower_arg == "setup":
            create_installer = True
        elif lower_arg in valid_levels:
            if level is not None:
                raise ValueError(f"Build-Level mehrfach angegeben: '{level}' und '{arg}'")
            level = lower_arg
        elif arg in ("--prerelease", "-p"):
            if i + 1 >= len(raw_args):
                raise ValueError(f"{arg} benötigt einen Wert, z.B. --prerelease alpha.1")
            i += 1
            prerelease_override = validate_semver_identifier(raw_args[i], "prerelease")
        elif arg.startswith("--prerelease="):
            prerelease_override = validate_semver_identifier(
                arg.split("=", 1)[1], "prerelease"
            )
        elif arg == "--clear-prerelease":
            prerelease_override = None
        elif arg in ("--metadata", "-m"):
            if i + 1 >= len(raw_args):
                raise ValueError(f"{arg} benötigt einen Wert, z.B. --metadata build.42")
            i += 1
            metadata_override = validate_semver_identifier(raw_args[i], "metadata")
        elif arg.startswith("--metadata="):
            metadata_override = validate_semver_identifier(arg.split("=", 1)[1], "metadata")
        elif arg == "--clear-metadata":
            metadata_override = None
        elif arg.startswith("-") and len(arg) > 1 and prerelease_override is UNSET:
            # Legacy Kurzform, z.B. "major -alpha setup"
            prerelease_override = validate_semver_identifier(arg[1:], "prerelease")
        elif prerelease_override is UNSET:
            # Legacy positional, z.B. "major alpha setup"
            prerelease_override = validate_semver_identifier(arg, "prerelease")
        else:
            raise ValueError(f"Unbekannter Parameter: '{arg}'")

        i += 1

    return {
        "level": level or "build",
        "create_installer": create_installer,
        "prerelease_override": prerelease_override,
        "metadata_override": metadata_override,
    }

def bump_version(level="build", prerelease_override=UNSET, metadata_override=UNSET):
    """
    Liest VERSION.txt, erhöht die gewählte Versionskomponente und schreibt sie zurück.

    Args:
        level: "major", "minor", "patch", "build" oder "none"
        prerelease_override: Neuer Pre-Release-Wert, None zum Entfernen, UNSET für unverändert
        metadata_override: Neue Build-Metadata, None zum Entfernen, UNSET für unverändert

    Returns:
        Die neue Version als String
    """
    version_file = Path("VERSION.txt")
    version = version_file.read_text(encoding="utf-8").strip()
    parsed = parse_version(version)
    major = parsed["major"]
    minor = parsed["minor"]
    patch = parsed["patch"]
    build = parsed["build"]
    prerelease = parsed["prerelease"]
    metadata = parsed["metadata"]

    if level == "major":
        major += 1
        minor = patch = 0
        build = 0
        prerelease = None
        metadata = None
    elif level == "minor":
        minor += 1
        patch = 0
        build = 0
        prerelease = None
        metadata = None
    elif level == "patch":
        patch += 1
        build = 0
        prerelease = None
        metadata = None
    elif level == "build":
        build = 1 if build is None else build + 1
    elif level == "none":
        print(f"   Version bleibt unverändert: {version}")
    else:
        raise ValueError(f"Unknown level '{level}', use: major | minor | patch | build | none")

    if prerelease_override is not UNSET:
        prerelease = prerelease_override
    if metadata_override is not UNSET:
        metadata = metadata_override

    new_version_data = {
        "major": major,
        "minor": minor,
        "patch": patch,
        "build": build,
        "prerelease": prerelease,
        "metadata": metadata,
    }
    new_version = format_version(new_version_data)
    version_file.write_text(new_version + "\n", encoding="utf-8")
    write_windows_version_for_nsis(new_version_data)
    print(f"   Version: {version} → {new_version}")
    return new_version

def check_pyzbar_installation():
    """
    Prüft, ob pyzbar installiert und grundsätzlich ladbar ist.
    Die eigentliche DLL-Sammlung übernimmt die .spec direkt via
    PyInstaller collect_dynamic_libs('pyzbar').
    """
    try:
        import pyzbar  # noqa: F401
        print("   ✅ pyzbar ist installiert (DLL-Sammlung erfolgt über die .spec).")
        return True
    except Exception as exc:
        print(f"   ⚠️  Warnung: pyzbar konnte nicht importiert werden: {exc}")
        return False

def update_version_info():
    """
    Aktualisiert version_info.txt mit der aktuellen Version aus VERSION.txt
    Diese Datei wird von PyInstaller für Windows-Metadaten verwendet.
    """
    if sys.platform != 'win32':
        return

    # Version aus VERSION.txt lesen
    version_file = Path("VERSION.txt")
    version_str = version_file.read_text(encoding="utf-8").strip()

    parsed_version = parse_version(version_str)
    version_parts = get_windows_version_tuple(parsed_version)

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
    if sys.platform != 'win32':
        # makensis kann theoretisch auch unter Linux laufen,
        # wir machen aber eine tarball.
        return None
        
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
    try:
        cli = parse_cli_args(sys.argv[1:])
    except ValueError as exc:
        print(f"❌ Ungültige Parameter: {exc}")
        return 1
    create_installer = cli["create_installer"]
    level = cli["level"]
    prerelease_override = cli["prerelease_override"]
    metadata_override = cli["metadata_override"]

    # Verhindere automatischen Version-Bump in GitHub Actions
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print("ℹ️  GitHub Actions erkannt: Version wird nicht hochgezählt.")
        level = "none"

    print(f"📋 Build-Level: {level}")
    if prerelease_override is UNSET:
        print("🏷️  Pre-Release: unverändert")
    elif prerelease_override is None:
        print("🏷️  Pre-Release: wird entfernt")
    else:
        print(f"🏷️  Pre-Release: {prerelease_override}")
    if metadata_override is UNSET:
        print("🧩 Metadata: unverändert")
    elif metadata_override is None:
        print("🧩 Metadata: wird entfernt")
    else:
        print(f"🧩 Metadata: {metadata_override}")
    print(f"📦 Installer erstellen: {'Ja' if create_installer else 'Nein'}")
    print()

    # 2. Version hochzählen
    print("📋 Aktualisiere Version...")
    new_version = bump_version(
        level,
        prerelease_override=prerelease_override,
        metadata_override=metadata_override,
    )

    # 3. Version Info aktualisieren
    update_version_info()

    # 4. pyzbar Installation prüfen
    print("📋 Prüfe pyzbar Installation...")
    check_pyzbar_installation()
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
    elif sys.platform == 'linux':
        print(f"📦 Schritt 2/{total_steps}: Linux Tarball erstellen")
        print("-" * 70)
        
        version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
        build_dir = Path(f"dist/Aero Tandem Studio v{version}")
        
        if build_dir.exists():
            tarball_name = f"AeroTandemStudio_Installer_v{version}_linux"
            try:
                shutil.make_archive(tarball_name, 'gztar', "dist", f"Aero Tandem Studio v{version}")
                print()
                print("✅ Linux Tarball erfolgreich erstellt!")
                print()
            except Exception as e:
                print()
                print(f"❌ Fehler beim Erstellen des Tarballs: {e}")
                return 1
        else:
            print("❌ Build Directory für Tarball nicht gefunden!")
            return 1
    elif sys.platform == 'darwin':
        print(f"📦 Schritt 2/{total_steps}: MacOS DMG erstellen")
        print("-" * 70)

        version = Path("VERSION.txt").read_text(encoding="utf-8").strip()
        build_dir = Path(f"dist/Aero Tandem Studio v{version}")
        app_path = Path("dist/Aero Tandem Studio.app")

        if app_path.exists():
            dmg_name = f"AeroTandemStudio_Installer_v{version}_mac.dmg"
            try:
                # Info-ReadMe für den Nutzer anlegen
                readme_path = Path("dist") / "WICHTIG - BITTE LESEN.txt"
                readme_path.write_text("WICHTIGER HINWEIS:\n\nDa diese App kein teures Apple-Entwicklerzertifikat nutzt, zeigt macOS beim ersten Start möglicherweise eine Sicherheitswarnung ('App kann nicht geöffnet werden, da sie nicht von einem verifizierten Entwickler stammt').\n\nLÖSUNG:\nMachen Sie einen Rechtsklick (oder Control+Klick) auf 'Aero Tandem Studio.app' und wählen Sie 'Öffnen'. Bestätigen Sie den Vorgang mit einem weiteren Klick auf 'Öffnen'. Dies muss nur ein einziges Mal durchgeführt werden!\n", encoding="utf-8")

                print("Erstelle MacOS DMG...")
                dmg_staging = Path("dmg_staging")
                if dmg_staging.exists():
                    shutil.rmtree(dmg_staging)
                dmg_staging.mkdir()

                # Verschiebe App und Readme in Staging
                shutil.copytree(app_path, dmg_staging / "Aero Tandem Studio.app")
                shutil.copy2(readme_path, dmg_staging / "WICHTIG - BITTE LESEN.txt")

                if shutil.which("create-dmg"):
                    # create-dmg von Homebrew nutzen für schicke Installation
                    subprocess.run([
                        "create-dmg",
                        "--volname", "Aero Tandem Studio",
                        "--window-pos", "200", "120",
                        "--window-size", "600", "400",
                        "--icon-size", "100",
                        "--app-drop-link", "400", "150",
                        "--icon", "Aero Tandem Studio.app", "150", "150",
                        dmg_name,
                        str(dmg_staging)
                    ], check=True)
                else:
                    print("⚠️  'create-dmg' nicht installiert. Erstelle stattdessen ZIP Fallback...")
                    tarball_name = f"AeroTandemStudio_Installer_v{version}_mac"
                    # Zip the staging directory
                    shutil.make_archive(tarball_name, 'zip', str(dmg_staging))

                shutil.rmtree(dmg_staging)
                print()
                print("✅ MacOS Release erfolgreich erstellt!")
                print()
            except Exception as e:
                print()
                print(f"❌ Fehler beim Erstellen des MacOS Releases: {e}")
                return 1
        else:
            print("❌ App Bundle für MacOS nicht gefunden!")
            return 1
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
        
    if sys.platform == 'linux' and create_installer:
        tarball_file = Path(f"AeroTandemStudio_Installer_v{version}_linux.tar.gz")
        if tarball_file.exists():
            installer_size = tarball_file.stat().st_size / (1024 * 1024)
            print(f"  ✅ {tarball_file}")
            print(f"     ({installer_size:.1f} MB)")

    if sys.platform == 'darwin' and create_installer:
        dmg_file = Path(f"AeroTandemStudio_Installer_v{version}_mac.dmg")
        zip_file = Path(f"AeroTandemStudio_Installer_v{version}_mac.zip")

        for mac_file in [dmg_file, zip_file]:
            if mac_file.exists():
                installer_size = mac_file.stat().st_size / (1024 * 1024)
                print(f"  ✅ {mac_file}")
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
