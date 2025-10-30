"""
File utilities for handling file operations, server uploads, and path normalization.

This module provides:
- Path normalization for different server formats (SMB, UNC, local)
- File upload functionality for Windows and Unix systems
- Server connection testing
- File and directory utilities
"""

import os
import shutil
import subprocess
import platform
from typing import Tuple, Optional

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


# ============================================================================
# PATH NORMALIZATION
# ============================================================================

def normalize_server_path(server_url: str) -> Tuple[Optional[str], bool, bool]:
    r"""
    Normalize various server path formats to a unified format.

    Accepts:
        - smb://server/share          -> \\server\share (Windows UNC)
        - \\server\share              -> \\server\share (Windows UNC)
        - //server/share              -> \\server\share (Unix-Style)
        - C:\local\path               -> C:\local\path (local path)
        - /local/path                 -> /local/path (Unix local path)

    Args:
        server_url: Server path in various formats

    Returns:
        tuple: (normalized_path, is_network_path, is_smb_url)
    """
    if not server_url:
        return None, False, False

    # Check if it's an SMB URL
    is_smb_url = server_url.startswith("smb://")

    # Remove smb:// prefix if present
    if is_smb_url:
        server_url = server_url.replace("smb://", "")

    # Check if it's a network path
    is_network_path = (
        server_url.startswith("\\\\") or
        server_url.startswith("//") or
        is_smb_url
    )

    # Normalize to Windows format if network path
    if is_network_path:
        # Convert to Windows UNC path
        normalized = server_url.replace("//", "\\\\").replace("/", "\\")

        # Ensure it starts with \\
        if not normalized.startswith("\\\\"):
            normalized = "\\\\" + normalized

        return normalized, True, is_smb_url

    # Local path - return unchanged
    return server_url, False, False


# ============================================================================
# FILE AND DIRECTORY UTILITIES
# ============================================================================

def sanitize_filename(filename: str) -> str:
    """
    Remove invalid characters from a potential filename.

    Args:
        filename: Original filename

    Returns:
        Sanitized filename without invalid characters
    """
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()


def ensure_directory_exists(directory: str) -> str:
    """
    Ensure that a directory exists, creating it if necessary.

    Args:
        directory: Path to directory

    Returns:
        The directory path
    """
    if not os.path.exists(directory):
        os.makedirs(directory)
    return directory


# ============================================================================
# CREDENTIAL HANDLING
# ============================================================================

def _get_credentials(settings: dict) -> Tuple[str, str]:
    """
    Extract login and password from settings.

    Args:
        settings: Settings dictionary

    Returns:
        tuple: (login, password) - returns empty strings if not configured
    """
    login = settings.get("server_login", "")
    password = settings.get("server_password", "")

    # Ensure we have strings, in case None was stored
    if login is None:
        login = ""
    if password is None:
        password = ""

    # Trim login, keep password exact
    return login.strip(), password


# ============================================================================
# MAIN UPLOAD FUNCTION
# ============================================================================

def upload_to_server_simple(local_directory: str, config_manager) -> Tuple[bool, str, str]:
    r"""
    Simple upload method using native tools.

    Args:
        local_directory: Local source directory to upload
        config_manager: ConfigManager instance (REQUIRED) - contains server URL and credentials

    Accepts various server URL formats:
        - smb://server/share
        - \\server\share
        - C:\local\path (for testing)

    Returns:
        tuple: (success, message, path)
    """
    try:
        # Config Manager is required
        if not config_manager:
            return False, "Config Manager fehlt - upload_to_server_simple benötigt config_manager Parameter", ""

        # Get settings from config
        settings = config_manager.get_settings()
        server_url = settings.get("server_url", "smb://169.254.169.254/aktuell")

        # Normalize server path (accepts smb://, \\, local paths)
        normalized_path, is_network, was_smb = normalize_server_path(server_url)

        if not normalized_path:
            return False, "Ungültige Server-URL", ""

        # If it's a local path, use direct copying
        if not is_network:
            print(f"Lokaler Pfad erkannt: {normalized_path}")
            return upload_to_server_python(local_directory, server_url=normalized_path)

        # For Windows: Use net use and robocopy (better than xcopy)
        if platform.system() == "Windows":
            return _upload_windows_robocopy(local_directory, normalized_path, settings)
        else:
            # For other systems: Use smbclient if available
            return _upload_unix_smbclient(local_directory, normalized_path, settings)

    except Exception as e:
        return False, f"Upload Fehler: {str(e)}", ""


# ============================================================================
# WINDOWS UPLOAD FUNCTIONS
# ============================================================================

def _upload_windows_robocopy(local_directory: str, server_path: str, settings: dict) -> Tuple[bool, str, str]:
    r"""
    Upload for Windows using robocopy (more reliable than xcopy).

    Args:
        local_directory: Local source directory
        server_path: Normalized server path (already in UNC format \\server\share or local path)
        settings: Settings with optional credentials

    Returns:
        tuple: (success, message, path)
    """
    try:
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        print(f"Versuche auf Server zu kopieren: {local_directory} -> {target_path}")

        # Check if local directory exists
        if not os.path.exists(local_directory):
            return False, f"Lokales Verzeichnis existiert nicht: {local_directory}", ""

        # Check if local directory is empty
        if not os.listdir(local_directory):
            return False, f"Lokales Verzeichnis ist leer: {local_directory}", ""

        # Check if server_path is a local path (e.g., C:\... or doesn't start with \\)
        is_local_path = (
            not server_path.startswith("\\\\") and
            not server_path.startswith("//")
        )

        if is_local_path:
            # Local path - use direct Python copying
            print(f"Lokaler Pfad erkannt, verwende direktes Kopieren...")
            return upload_to_server_python(local_directory, server_url=server_path)

        # Network path - always use credentials for network shares
        # Even if server is accessible, we need proper authentication to create directories
        return _upload_windows_with_credentials(local_directory, server_path, settings)

    except Exception as e:
        return False, f"Windows Upload Fehler: {str(e)}", ""


def _upload_windows_with_credentials(local_directory: str, server_path: str, settings: dict) -> Tuple[bool, str, str]:
    r"""
    Upload for Windows with explicit credentials.

    Args:
        local_directory: Local source directory
        server_path: Normalized UNC path (e.g., \\server\share)
        settings: Settings with credentials

    Returns:
        tuple: (success, message, path)
    """
    try:
        # Extract server and share from UNC path
        # \\server\share -> server, share
        if not server_path.startswith("\\\\"):
            return False, f"Ungültiger UNC-Pfad: {server_path}", ""

        # Remove leading \\
        path_without_slashes = server_path[2:]
        parts = path_without_slashes.split("\\", 1)

        if len(parts) < 2:
            return False, f"Ungültiger Server-Pfad: {server_path}", ""

        server, share = parts
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        # Get credentials from settings
        login, password = _get_credentials(settings)

        # IMPORTANT: Use net use for authentication, but WITHOUT drive letter
        # This authenticates the connection without mapping a drive
        # Then robocopy can directly use the UNC path

        # Disconnect existing connection if present
        subprocess.run(
            f'net use "{server_path}" /delete /y',
            shell=True,
            capture_output=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        # Connect to server with credentials (WITHOUT drive letter!)
        if login:
            # Connect with specific credentials
            net_use_cmd = f'net use "{server_path}" "{password}" /user:{login}'
        else:
            # Connect without specific credentials (uses current Windows credentials)
            net_use_cmd = f'net use "{server_path}"'

        print(f"Authentifiziere Verbindung zu {server_path}...")
        result = subprocess.run(
            net_use_cmd,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            # More detailed error message
            error_msg = result.stderr or result.stdout
            if "Systemfehler 1326" in error_msg or "1326" in error_msg:
                error_msg = "Verbindung fehlgeschlagen: Ungültiger Benutzername oder Passwort."
            elif "Systemfehler 53" in error_msg or "53" in error_msg:
                error_msg = "Verbindung fehlgeschlagen: Server nicht gefunden (Netzwerkpfad nicht gefunden)."
            elif "Systemfehler 1219" in error_msg or "1219" in error_msg:
                # Fehler 1219: Mehrfache Verbindungen mit unterschiedlichen Credentials
                # Automatisch alle Verbindungen trennen und nochmal versuchen
                print(f"⚠️  Fehler 1219 erkannt: Trenne bestehende Verbindungen...")

                # Trenne ALLE Verbindungen zum Server
                subprocess.run(
                    f'net use "{server_path}" /delete /y',
                    shell=True,
                    capture_output=True,
                    creationflags=SUBPROCESS_CREATE_NO_WINDOW
                )

                # Warte kurz
                import time
                time.sleep(0.5)

                # Versuche erneut
                print(f"Versuche erneut zu verbinden...")
                result2 = subprocess.run(
                    net_use_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    creationflags=SUBPROCESS_CREATE_NO_WINDOW
                )

                if result2.returncode != 0:
                    error_msg2 = result2.stderr or result2.stdout
                    return False, (
                        f"Verbindung fehlgeschlagen (Fehler 1219 - Mehrfache Verbindungen):\n"
                        f"{error_msg2}\n\n"
                        f"Lösungen:\n"
                        f"1. Trenne alle Verbindungen: net use * /delete /y\n"
                        f"2. Starte den Upload erneut\n"
                        f"3. Für localhost: Nutze KEINE Credentials (du bist bereits angemeldet)"
                    ), ""
                else:
                    print(f"✅ Verbindung erfolgreich nach erneutem Versuch")
            else:
                error_msg = f"Verbindung zum Server fehlgeschlagen (Code {result.returncode}): {error_msg}"
                return False, error_msg, ""
        else:
            print(f"✅ Verbindung authentifiziert")

        # TEST: Verifiziere Schreibrechte auf dem Share BEVOR wir versuchen, Verzeichnisse zu erstellen
        test_file_path = os.path.join(server_path, f".write_test_{os.getpid()}.tmp")
        try:
            print(f"Teste Schreibrechte auf {server_path}...")
            with open(test_file_path, 'w') as f:
                f.write("test")
            os.remove(test_file_path)
            print(f"✅ Schreibrechte auf Share verifiziert")
        except Exception as write_test_error:
            return False, (
                f"Keine Schreibrechte auf Server-Share: {server_path}\n"
                f"Fehler: {str(write_test_error)}\n\n"
                f"Die Verbindung wurde authentifiziert, aber der Benutzer '{login or 'aktueller Benutzer'}' "
                f"hat keine Schreibrechte auf dem Share.\n\n"
                f"Lösungen:\n"
                f"1. Prüfe Share-Berechtigungen: net share {share}\n"
                f"2. Setze Share-Berechtigungen: net share {share} /GRANT:{login or 'Jeder'},FULL\n"
                f"3. Setze NTFS-Berechtigungen: icacls \"<server-pfad>\" /grant {login or 'Jeder'}:(OI)(CI)F\n"
            ), ""

        # Create target directory using authenticated connection
        # IMPORTANT: Do this BEFORE the finally block, while net use is still active
        try:
            print(f"Erstelle Zielverzeichnis: {target_path}")

            # First check if directory already exists
            if os.path.exists(target_path):
                print(f"Zielverzeichnis existiert bereits: {target_path}")
            else:
                # Try Python os.makedirs FIRST (nutzt die authentifizierte net use Verbindung!)
                # Das ist besser als mkdir, weil es die Windows-Credentials direkt verwendet
                try:
                    os.makedirs(target_path, exist_ok=True)
                    print(f"✅ Zielverzeichnis erstellt (os.makedirs)")
                except PermissionError as perm_error:
                    # Wenn Python fehlschlägt, versuche Windows mkdir
                    print(f"   os.makedirs fehlgeschlagen, versuche Windows mkdir...")
                    mkdir_result = subprocess.run(
                        f'mkdir "{target_path}"',
                        shell=True,
                        capture_output=True,
                        text=True,
                        creationflags=SUBPROCESS_CREATE_NO_WINDOW
                    )

                    if mkdir_result.returncode != 0:
                        error_output = mkdir_result.stderr or mkdir_result.stdout
                        # Prüfe ob Verzeichnis trotzdem existiert
                        if os.path.exists(target_path):
                            print(f"✅ Zielverzeichnis existiert (trotz mkdir-Fehler)")
                        elif "already exists" in error_output.lower() or "bereits vorhanden" in error_output.lower():
                            print(f"✅ Zielverzeichnis existiert bereits")
                        else:
                            # Beide Methoden fehlgeschlagen - detaillierte Fehlermeldung
                            return False, (
                                f"Kann Zielverzeichnis nicht erstellen: {target_path}\n"
                                f"Python-Fehler: {str(perm_error)}\n"
                                f"mkdir-Fehler: {error_output.strip()}\n\n"
                                f"Mögliche Ursachen:\n"
                                f"- NTFS-Berechtigungen auf Server fehlen\n"
                                f"- Share-Berechtigungen sind Read-Only\n"
                                f"- Benutzer '{login}' hat keine Schreibrechte\n\n"
                                f"Prüfe auf dem Server:\n"
                                f"  icacls \"{server_path}\" /grant {login}:(OI)(CI)F"
                            ), ""
                    else:
                        print(f"✅ Zielverzeichnis erstellt (mkdir)")
                except Exception as other_error:
                    return False, f"Unerwarteter Fehler beim Erstellen: {str(other_error)}", ""

            # Final verification: Stelle sicher, dass Verzeichnis existiert
            if not os.path.exists(target_path):
                return False, (
                    f"Verzeichnis konnte nicht erstellt oder verifiziert werden: {target_path}\n"
                    f"Die net use Verbindung ist authentifiziert, aber das Verzeichnis ist nicht erreichbar."
                ), ""

            print(f"✅ Zielverzeichnis bereit: {target_path}")

        except Exception as e:
            return False, f"Fehler bei Verzeichniserstellung: {target_path} - {str(e)}", ""

        # IMPORTANT: robocopy MUST be executed here, BEFORE finally disconnects!
        try:
            print(f"Kopiere Dateien mit robocopy...")

            # robocopy command with optimal parameters for media upload
            robocopy_cmd = [
                "robocopy",
                local_directory,
                target_path,
                "/E",        # Include subdirectories
                "/COPY:DAT", # Copy Data, Attributes, Timestamps
                "/R:3",      # 3 retry attempts
                "/W:5",      # 5 seconds wait between attempts
                "/NP",       # No progress display
                "/NFL",      # No file list
                "/NDL"       # No directory list
            ]

            result = subprocess.run(
                robocopy_cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes timeout
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            # robocopy exit codes: 0-7 = success, 8+ = error, 16 = FATAL
            if result.returncode < 8:
                success_message = f"Erfolgreich auf Server kopiert: {target_path}"
                if result.returncode > 0:
                    success_message += f" (robocopy Code: {result.returncode})"
                return True, success_message, target_path
            elif result.returncode == 16:
                error_detail = result.stdout if result.stdout else result.stderr
                return False, f"robocopy FATAL ERROR (Code 16): Zugriff verweigert oder ungültiger Pfad. Details: {error_detail}", ""
            else:
                error_detail = result.stdout if result.stdout else result.stderr
                return False, f"robocopy Fehler (Code {result.returncode}): {error_detail}", ""

        except subprocess.TimeoutExpired:
            return False, "Upload timeout - Server nicht erreichbar oder zu langsam", ""
        except Exception as e:
            return False, f"robocopy Ausführungsfehler: {str(e)}", ""
        finally:
            # Disconnect (ONLY here, AFTER robocopy)
            subprocess.run(
                f'net use "{server_path}" /delete /y',
                shell=True,
                capture_output=True,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

    except Exception as e:
        return False, f"Upload mit Anmeldedaten fehlgeschlagen: {str(e)}", ""


def _execute_robocopy(local_directory: str, target_path: str) -> Tuple[bool, str, str]:
    """
    Execute robocopy (helper function - for paths without authentication).

    Args:
        local_directory: Local source directory
        target_path: Target path on server

    Returns:
        tuple: (success, message, path)
    """
    try:
        print(f"Kopiere nach: {target_path} (ohne Authentifizierung)")

        # robocopy command with optimal parameters for media upload
        # /COPY:DAT explained:
        #   D = Data (file content) - THE VIDEO/PHOTO FILE ITSELF ✅
        #   A = Attributes (file attributes like Read-only, Hidden) ✅
        #   T = Timestamps (creation/modification date) ✅
        #
        # NOT copied (and not needed for media):
        #   S = Security (NTFS permissions) - not necessary
        #   O = Owner info (owner) - not necessary
        #   U = Auditing info (audit logs) - not necessary, would cause errors!
        #
        # → PERFECT for video/photo upload, NO data loss!
        robocopy_cmd = [
            "robocopy",
            local_directory,
            target_path,
            "/E",        # Include subdirectories
            "/COPY:DAT", # Copy Data, Attributes, Timestamps (sufficient for media!)
            "/R:3",      # 3 retry attempts
            "/W:5",      # 5 seconds wait between attempts
            "/NP",       # No progress display (reduces output)
            "/NFL",      # No file list
            "/NDL"       # No directory list
        ]

        # Execute robocopy
        result = subprocess.run(
            robocopy_cmd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minutes timeout
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        # robocopy returns special exit codes:
        # 0 = No files copied, no errors
        # 1 = Files successfully copied
        # 2 = Extra files or directories found
        # 4 = Some files don't match
        # 8 = Some files or directories could not be copied (retry limit)
        # 16 = FATAL ERROR - robocopy couldn't copy at all
        if result.returncode < 8:
            # Success - codes 0-7 are OK
            success_message = f"Erfolgreich auf Server kopiert: {target_path}"
            if result.returncode > 0:
                success_message += f" (robocopy Code: {result.returncode})"
            return True, success_message, target_path
        elif result.returncode == 16:
            # FATAL ERROR - e.g., access denied, invalid path
            error_detail = result.stdout if result.stdout else result.stderr
            return False, f"robocopy FATAL ERROR (Code 16): Zugriff verweigert oder ungültiger Pfad. Details: {error_detail}", ""
        else:
            # Other errors (8 or higher)
            error_detail = result.stdout if result.stdout else result.stderr
            return False, f"robocopy Fehler (Code {result.returncode}): {error_detail}", ""

    except subprocess.TimeoutExpired:
        return False, "Upload timeout - Server nicht erreichbar oder zu langsam", ""
    except Exception as e:
        return False, f"robocopy Ausführungsfehler: {str(e)}", ""


# ============================================================================
# UNIX/LINUX/MACOS UPLOAD FUNCTIONS
# ============================================================================

def _upload_unix_smbclient(local_directory: str, server_url: str, settings: dict) -> Tuple[bool, str, str]:
    """
    Upload for macOS and Linux systems using smbclient.

    Args:
        local_directory: Local source directory
        server_url: Server URL
        settings: Settings with credentials

    Returns:
        tuple: (success, message, path)
    """
    try:
        # Normalize server path
        normalized_path, is_network, was_smb = normalize_server_path(server_url)

        if not normalized_path:
            return False, "Ungültige Server-URL", ""

        # If it's a local path, use direct copying
        if not is_network:
            print(f"Lokaler Pfad erkannt (nicht-Windows), verwende direktes Kopieren...")
            return upload_to_server_python(local_directory, server_url=normalized_path)

        # Check if smbclient is available
        result = subprocess.run(
            ["which", "smbclient"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return False, "smbclient nicht verfügbar - kann nicht auf Server uploaden", ""

        # Extract server and share from normalized path
        # For Unix-like systems: //server/share
        server_share = normalized_path
        if server_share.startswith("\\\\"):
            # Convert Windows UNC to Unix format for smbclient
            server_share = server_share.replace("\\\\", "//", 1).replace("\\", "/")

        parts = server_share.lstrip("/").split("/", 1)
        if len(parts) < 2:
            return False, f"Ungültige Server-URL: {server_url}", ""

        server, share = parts

        # Use smbclient with credentials
        return _upload_smbclient_with_auth(local_directory, server, share, settings)

    except Exception as e:
        return False, f"Upload Fehler (nicht-Windows): {str(e)}", ""


def _upload_smbclient_with_auth(local_directory: str, server: str, share: str, settings: dict) -> Tuple[bool, str, str]:
    """
    Upload using smbclient with authentication.

    Args:
        local_directory: Local source directory
        server: Server name/IP
        share: Share name
        settings: Settings with credentials

    Returns:
        tuple: (success, message, path)
    """
    try:
        dir_name = os.path.basename(local_directory)

        # Get credentials from settings
        login, password = _get_credentials(settings)

        auth_cmd = []
        if login:
            # With user and password
            auth_string = f"{login}%{password}"
            auth_cmd = ["-U", auth_string]
        else:
            # Anonymous / no credentials
            auth_cmd = ["-N"]

        # Command for smbclient with authentication
        # -U: Username and password
        # -c: Execute commands
        cmd = [
            "smbclient",
            f"//{server}/{share}",
        ] + auth_cmd + [
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
            if "NT_STATUS_LOGON_FAILURE" in error_msg:
                error_msg = "smbclient Fehler: Ungültiger Benutzername oder Passwort."
            elif "NT_STATUS_BAD_NETWORK_NAME" in error_msg:
                error_msg = f"smbclient Fehler: Server oder Freigabe '{share}' nicht gefunden."
            elif "NT_STATUS_ACCESS_DENIED" in error_msg:
                error_msg = "smbclient Fehler: Zugriff verweigert (ggf. mkdir)."
            else:
                error_msg = f"smbclient Fehler: {error_msg}"
            return False, error_msg, ""

    except subprocess.TimeoutExpired:
        return False, "Upload timeout - Server nicht erreichbar", ""
    except Exception as e:
        return False, f"smbclient Authentifizierungsfehler: {str(e)}", ""


# ============================================================================
# PYTHON-BASED UPLOAD (FALLBACK)
# ============================================================================

def upload_to_server_python(local_directory: str, server_url: str = "smb://169.254.169.254/aktuell") -> Tuple[bool, str, str]:
    """
    Pure Python solution without external tools (Windows only).

    Args:
        local_directory: Local source directory
        server_url: Server URL (default: smb://169.254.169.254/aktuell)

    Returns:
        tuple: (success, message, path)
    """
    try:
        if platform.system() != "Windows":
            return False, "Python-only Upload nur unter Windows verfügbar", ""

        server_path = server_url.replace("smb://", "\\\\").replace("/", "\\")
        dir_name = os.path.basename(local_directory)
        target_path = os.path.join(server_path, dir_name)

        # Check if server is reachable
        if not os.path.exists(server_path):
            return False, f"Server nicht erreichbar: {server_path}", ""

        # Copy with shutil
        if os.path.exists(target_path):
            shutil.rmtree(target_path)  # Delete existing

        shutil.copytree(local_directory, target_path)
        return True, f"Erfolgreich auf Server kopiert: {target_path}", target_path

    except Exception as e:
        return False, f"Python Upload Fehler: {str(e)}", ""


# ============================================================================
# SERVER CONNECTION TESTING
# ============================================================================

def test_server_connection(config_manager=None) -> Tuple[bool, str]:
    """
    Test the connection to the server with credentials.

    Args:
        config_manager: ConfigManager instance (optional)

    Returns:
        tuple: (success, message)
    """
    try:
        settings = {}
        server_url = "smb://169.254.169.254/aktuell"  # Default

        if config_manager:
            settings = config_manager.get_settings()
            server_url = settings.get("server_url", server_url)

        # Normalize server path (accepts all formats)
        normalized_path, is_network, was_smb = normalize_server_path(server_url)

        if not normalized_path:
            return False, "Ungültige Server-URL"

        # If it's a local path, just test if it exists
        if not is_network:
            if os.path.exists(normalized_path):
                return True, f"Lokaler Pfad erreichbar: {normalized_path}"
            else:
                return False, f"Lokaler Pfad nicht gefunden: {normalized_path}"

        # Get credentials from settings
        login, password = _get_credentials(settings)

        # Extract server and share from normalized UNC path
        # \\server\share -> server, share
        if not normalized_path.startswith("\\\\"):
            return False, f"Ungültiger Netzwerkpfad: {normalized_path}"

        path_without_slashes = normalized_path[2:]
        parts = path_without_slashes.split("\\", 1)

        if len(parts) < 2:
            return False, f"Ungültiger Server-Pfad: {normalized_path}"

        server, share = parts

        if platform.system() == "Windows":
            # Test with net use on Windows
            return _test_connection_windows(server, share, login, password)
        else:
            # Test with smbclient on other systems
            return _test_connection_unix(server, share, login, password)

    except Exception as e:
        return False, f"Verbindungstest fehlgeschlagen: {str(e)}"


def _test_connection_windows(server: str, share: str, login: str, password: str) -> Tuple[bool, str]:
    """
    Test connection on Windows using net use.

    Args:
        server: Server name/IP
        share: Share name
        login: Username
        password: Password

    Returns:
        tuple: (success, message)
    """
    try:
        drive_letter = "T:"  # Test drive letter

        # Disconnect existing connection
        subprocess.run(
            f"net use {drive_letter} /delete /y",
            shell=True,
            capture_output=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        # Test connection
        if login:
            # Test connection with user
            net_use_cmd = f'net use {drive_letter} "\\\\{server}\\{share}" "{password}" /user:{login}'
        else:
            # Test connection without user
            net_use_cmd = f'net use {drive_letter} "\\\\{server}\\{share}"'

        result = subprocess.run(
            net_use_cmd,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        # Disconnect
        subprocess.run(
            f"net use {drive_letter} /delete /y",
            shell=True,
            capture_output=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        if result.returncode == 0:
            return True, "Verbindung zum Server erfolgreich"
        else:
            error_msg = result.stderr or result.stdout
            if "1326" in error_msg:
                error_msg = "Verbindung fehlgeschlagen: Ungültiger Benutzername oder Passwort."
            elif "53" in error_msg:
                error_msg = "Verbindung fehlgeschlagen: Server nicht gefunden."
            else:
                error_msg = f"Verbindung fehlgeschlagen: {error_msg}"
            return False, error_msg

    except Exception as e:
        return False, f"Windows Verbindungstest fehlgeschlagen: {str(e)}"


def _test_connection_unix(server: str, share: str, login: str, password: str) -> Tuple[bool, str]:
    """
    Test connection on Unix/Linux/macOS using smbclient.

    Args:
        server: Server name/IP
        share: Share name
        login: Username
        password: Password

    Returns:
        tuple: (success, message)
    """
    try:
        auth_cmd = []
        if login:
            auth_string = f"{login}%{password}"
            auth_cmd = ["-U", auth_string]
        else:
            auth_cmd = ["-N"]

        cmd = ["smbclient", f"//{server}/{share}"] + auth_cmd + ["-c", "ls"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0:
            return True, "Verbindung zum Server erfolgreich"
        else:
            error_msg = result.stderr or result.stdout
            if "NT_STATUS_LOGON_FAILURE" in error_msg:
                error_msg = "Verbindung fehlgeschlagen: Ungültiger Benutzername oder Passwort."
            elif "NT_STATUS_BAD_NETWORK_NAME" in error_msg:
                error_msg = f"Verbindung fehlgeschlagen: Server oder Freigabe '{share}' nicht gefunden."
            else:
                error_msg = f"Verbindung fehlgeschlagen: {error_msg}"
            return False, error_msg

    except Exception as e:
        return False, f"Unix Verbindungstest fehlgeschlagen: {str(e)}"
