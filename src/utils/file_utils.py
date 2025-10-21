import os
import shutil
import subprocess
import platform


def sanitize_filename(filename):
    """Entfernt ungültige Zeichen aus einem potenziellen Dateinamen."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()


def ensure_directory_exists(directory):
    """Stellt sicher, dass ein Verzeichnis existiert"""
    if not os.path.exists(directory):
        os.makedirs(directory)
    return directory


def upload_to_server_simple(local_directory, config_manager=None):
    """
    Einfache Upload-Methode die mit Python-Bordmitteln arbeitet
    """
    try:
        # Hole Server-URL aus Config oder verwende Standard
        if config_manager:
            settings = config_manager.get_settings()
            server_url = settings.get("server_url", "smb://169.254.169.254/aktuell")
        else:
            server_url = "smb://169.254.169.254/aktuell"

        # Für Windows: Verwende net use und robocopy (besser als xcopy)
        if platform.system() == "Windows":
            return _upload_windows_robocopy(local_directory, server_url)
        else:
            # Für andere Systeme: Verwende smbclient falls verfügbar
            return _upload_other_systems(local_directory, server_url)

    except Exception as e:
        return False, f"Upload Fehler: {str(e)}", ""


def _upload_windows_robocopy(local_directory, server_url):
    """Upload für Windows mit robocopy (zuverlässiger als xcopy)"""
    try:
        # Konvertiere SMB-URL zu Windows Netzwerkpfad
        # smb://169.254.169.254/aktuell -> \\169.254.169.254\aktuell
        server_path = server_url.replace("smb://", "\\\\").replace("/", "\\")
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        print(f"Versuche auf Server zu kopieren: {local_directory} -> {target_path}")

        # Prüfe ob lokales Verzeichnis existiert
        if not os.path.exists(local_directory):
            return False, f"Lokales Verzeichnis existiert nicht: {local_directory}", ""

        # Versuche zunächst ohne Credentials (falls bereits verbunden)
        try:
            if not os.path.exists(server_path):
                # Server nicht erreichbar, versuche mit Credentials zu verbinden
                return _upload_windows_with_credentials(local_directory, server_url)
        except:
            # Fehler beim Zugriff, versuche mit Credentials
            return _upload_windows_with_credentials(local_directory, server_url)

        # Server ist erreichbar, verwende robocopy direkt
        return _execute_robocopy(local_directory, target_path)

    except Exception as e:
        return False, f"Windows Upload Fehler: {str(e)}", ""


def _upload_windows_with_credentials(local_directory, server_url):
    """Upload für Windows mit expliziten Anmeldedaten"""
    try:
        # Extrahiere Server und Share aus URL
        server_share = server_url.replace("smb://", "")
        parts = server_share.split("/", 1)
        if len(parts) < 2:
            return False, f"Ungültige Server-URL: {server_url}", ""

        server, share = parts
        server_path = f"\\\\{server}\\{share}"
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        # Verwende net use mit Anmeldedaten
        drive_letter = "Z:"  # Temporärer Laufwerksbuchstabe

        # Trenne bestehende Verbindung falls vorhanden
        subprocess.run(f"net use {drive_letter} /delete /y",
                       shell=True, capture_output=True)

        # Verbinde mit Server und Anmeldedaten
        net_use_cmd = f'net use {drive_letter} "{server_path}" /user:aero aero'
        result = subprocess.run(net_use_cmd, shell=True, capture_output=True, text=True)

        if result.returncode != 0:
            return False, f"Verbindung zum Server fehlgeschlagen: {result.stderr}", ""

        try:
            # Jetzt mit robocopy über das gemountete Laufwerk kopieren
            local_drive_path = os.path.join(drive_letter, dir_name)
            return _execute_robocopy(local_directory, local_drive_path, drive_mounted=True)
        finally:
            # Verbindung trennen
            subprocess.run(f"net use {drive_letter} /delete /y",
                           shell=True, capture_output=True)

    except Exception as e:
        return False, f"Upload mit Anmeldedaten fehlgeschlagen: {str(e)}", ""


def _execute_robocopy(local_directory, target_path, drive_mounted=False):
    """Führt robocopy aus (Hilfsfunktion)"""
    try:
        # Verwende robocopy für zuverlässiges Kopieren
        # robocopy Quelle Ziel /E /COPYALL /R:3 /W:5
        robocopy_cmd = [
            "robocopy",
            f'"{local_directory}"',  # Quelle in Anführungszeichen für Leerzeichen
            f'"{target_path}"',  # Ziel in Anführungszeichen für Leerzeichen
            "/E",  # Inklusive Unterverzeichnisse
            "/COPYALL",  # Alle Dateiattribute kopieren
            "/R:3",  # 3 Wiederholungsversuche
            "/W:5",  # 5 Sekunden warten zwischen Versuchen
            "/NP",  # Kein Fortschrittsanzeige (reduziert Ausgabe)
            "/NFL",  # Keine Dateiliste
            "/NDL"  # Keine Verzeichnisliste
        ]

        # Führe robocopy aus
        result = subprocess.run(
            " ".join(robocopy_cmd),  # Als String für korrekte Anführungszeichen
            shell=True,
            capture_output=True,
            text=True,
            timeout=300  # 5 Minuten Timeout
        )

        # robocopy gibt spezielle Exit-Codes zurück:
        # 0-7 = Erfolg, 8+ = Fehler
        if result.returncode <= 7:
            # Erfolg - robocopy gibt auch 1 zurück wenn Dateien kopiert wurden
            success_message = f"Erfolgreich auf Server kopiert: {target_path}"
            if result.returncode > 0:
                success_message += f" (robocopy Code: {result.returncode})"
            return True, success_message, target_path
        else:
            return False, f"robocopy Fehler (Code {result.returncode}): {result.stderr}", ""

    except subprocess.TimeoutExpired:
        return False, "Upload timeout - Server nicht erreichbar oder zu langsam", ""
    except Exception as e:
        return False, f"robocopy Ausführungsfehler: {str(e)}", ""


def _upload_windows_xcopy_fallback(local_directory, server_url):
    """Fallback für Windows mit xcopy (falls robocopy nicht verfügbar)"""
    try:
        server_path = server_url.replace("smb://", "\\\\").replace("/", "\\")
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        # xcopy mit korrekter Syntax
        xcopy_cmd = f'xcopy "{local_directory}" "{target_path}" /E /I /Y /Q'

        result = subprocess.run(
            xcopy_cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            return True, f"Erfolgreich auf Server kopiert: {target_path}", target_path
        else:
            return False, f"xcopy Fehler: {result.stderr}", ""

    except Exception as e:
        return False, f"xcopy Fallback Fehler: {str(e)}", ""


def _upload_other_systems(local_directory, server_url):
    """Upload für macOS und Linux Systeme"""
    try:
        # Prüfe ob smbclient verfügbar ist
        result = subprocess.run(["which", "smbclient"], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "smbclient nicht verfügbar - kann nicht auf Server uploaden", ""

        # Extrahiere Server und Share aus URL
        server_share = server_url.replace("smb://", "")
        parts = server_share.split("/", 1)
        if len(parts) < 2:
            return False, f"Ungültige Server-URL: {server_url}", ""

        server, share = parts

        # Verwende smbclient mit Anmeldedaten
        return _upload_smbclient_with_auth(local_directory, server, share)

    except Exception as e:
        return False, f"Upload Fehler (nicht-Windows): {str(e)}", ""


def _upload_smbclient_with_auth(local_directory, server, share):
    """Upload mit smbclient und Authentifizierung"""
    try:
        dir_name = os.path.basename(local_directory)

        # Befehl für smbclient mit Authentifizierung
        # -U aero%aero: Benutzername und Passwort
        # -c: Befehle ausführen
        cmd = [
            "smbclient",
            f"//{server}/{share}",
            "-U", "aero%aero",  # Benutzername%Passwort
            "-c", f"mkdir {dir_name}; prompt; recurse; cd {dir_name}; lcd {local_directory}; mput *"
        ]

        result = subprocess.run(
            " ".join(cmd),
            shell=True,
            capture_output=True,
            text=True,
            timeout=300
        )

        if result.returncode == 0:
            target_path = f"//{server}/{share}/{dir_name}"
            return True, f"Erfolgreich auf Server kopiert: {target_path}", target_path
        else:
            error_msg = result.stderr if result.stderr else result.stdout
            return False, f"smbclient Fehler: {error_msg}", ""

    except subprocess.TimeoutExpired:
        return False, "Upload timeout - Server nicht erreichbar", ""
    except Exception as e:
        return False, f"smbclient Authentifizierungsfehler: {str(e)}", ""


def _upload_smbclient_recursive(local_directory, server, share):
    """Versucht rekursiv mit smbclient zu uploaden (ohne Auth)"""
    try:
        dir_name = os.path.basename(local_directory)
        cmd = f'smbclient "//{server}/{share}" -N -c "mkdir {dir_name}; prompt; recurse; cd {dir_name}; lcd {local_directory}; mput *"'

        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            return True, f"Erfolgreich auf Server kopiert: //{server}/{share}/{dir_name}", f"//{server}/{share}/{dir_name}"
        else:
            return False, f"smbclient Fehler: {result.stderr}", ""

    except Exception as e:
        return False, f"smbclient rekursiv Fehler: {str(e)}", ""


# Alternative: Python-only Lösung mit shutil
def upload_to_server_python(local_directory, server_url="smb://169.254.169.254/aktuell"):
    """
    Reine Python-Lösung ohne externe Tools (nur Windows)
    """
    try:
        if platform.system() != "Windows":
            return False, "Python-only Upload nur unter Windows verfügbar", ""

        server_path = server_url.replace("smb://", "\\\\").replace("/", "\\")
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        # Prüfe ob Server erreichbar
        if not os.path.exists(server_path):
            return False, f"Server nicht erreichbar: {server_path}", ""

        # Kopiere mit shutil
        if os.path.exists(target_path):
            shutil.rmtree(target_path)  # Vorhandenes löschen

        shutil.copytree(local_directory, target_path)
        return True, f"Erfolgreich auf Server kopiert: {target_path}", target_path

    except Exception as e:
        return False, f"Python Upload Fehler: {str(e)}", ""


def test_server_connection(config_manager=None):
    """Testet die Verbindung zum Server mit Anmeldedaten"""
    try:
        if config_manager:
            settings = config_manager.get_settings()
            server_url = settings.get("server_url", "smb://169.254.169.254/aktuell")
        else:
            server_url = "smb://169.254.169.254/aktuell"

        server_share = server_url.replace("smb://", "")
        parts = server_share.split("/", 1)
        if len(parts) < 2:
            return False, "Ungültige Server-URL"

        server, share = parts

        if platform.system() == "Windows":
            # Test mit net use auf Windows
            drive_letter = "T:"  # Test-Laufwerksbuchstabe

            # Bestehende Verbindung trennen
            subprocess.run(f"net use {drive_letter} /delete /y",
                           shell=True, capture_output=True)

            # Verbindung testen
            net_use_cmd = f'net use {drive_letter} "\\\\{server}\\{share}" /user:aero aero'
            result = subprocess.run(net_use_cmd, shell=True, capture_output=True, text=True)

            # Verbindung trennen
            subprocess.run(f"net use {drive_letter} /delete /y",
                           shell=True, capture_output=True)

            if result.returncode == 0:
                return True, "Verbindung zum Server erfolgreich"
            else:
                return False, f"Verbindung fehlgeschlagen: {result.stderr}"

        else:
            # Test mit smbclient auf anderen Systemen
            cmd = ["smbclient", f"//{server}/{share}", "-U", "aero%aero", "-c", "ls"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                return True, "Verbindung zum Server erfolgreich"
            else:
                return False, f"Verbindung fehlgeschlagen: {result.stderr}"

    except Exception as e:
        return False, f"Verbindungstest fehlgeschlagen: {str(e)}"