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


def upload_to_server_simple(local_directory, server_url="smb://169.254.169.254/aktuell"):
    """
    Einfache Upload-Methode die mit Python-Bordmitteln arbeitet
    """
    try:
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

        # Prüfe ob Server erreichbar ist
        try:
            # Versuche auf Server zuzugreifen
            if not os.path.exists(server_path):
                return False, f"Server nicht erreichbar: {server_path}", ""
        except:
            return False, f"Kann nicht auf Server zugreifen: {server_path}", ""

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
        return False, f"Windows Upload Fehler: {str(e)}", ""


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

        # Erstelle temporäres Verzeichnis für den Upload
        import tempfile
        temp_dir = tempfile.mkdtemp()

        try:
            # Mount Befehl (versuchsweise)
            mount_point = os.path.join(temp_dir, "mount")
            os.makedirs(mount_point, exist_ok=True)

            # Versuche mit smbclient direkt zu arbeiten (ohne mount)
            # Erstelle tar Archiv und sende es per smbclient
            tar_file = os.path.join(temp_dir, "upload.tar")
            tar_cmd = f'tar -cf "{tar_file}" -C "{local_directory}" .'
            subprocess.run(tar_cmd, shell=True, check=True, capture_output=True)

            # Upload mit smbclient
            smb_cmd = f'smbclient "//{server}/{share}" -N -c "prompt; put {tar_file} {os.path.basename(local_directory)}.tar"'
            result = subprocess.run(smb_cmd, shell=True, capture_output=True, text=True)

            if result.returncode == 0:
                return True, f"Erfolgreich auf Server kopiert als Archiv", f"//{server}/{share}"
            else:
                # Fallback: Versuche Verzeichnis rekursiv zu kopieren
                return _upload_smbclient_recursive(local_directory, server, share)

        finally:
            # Aufräumen
            try:
                shutil.rmtree(temp_dir)
            except:
                pass

    except Exception as e:
        return False, f"Upload Fehler (nicht-Windows): {str(e)}", ""


def _upload_smbclient_recursive(local_directory, server, share):
    """Versucht rekursiv mit smbclient zu uploaden"""
    try:
        # Erstelle Befehl für rekursives Upload
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