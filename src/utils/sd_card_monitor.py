"""
SD-Karten Monitor
Überwacht USB/SD-Karten Anschlüsse und führt automatische Backups durch.
"""
import os
import re
import secrets
import time
import threading
import shutil
import string
import sys
import platform
import subprocess

try:
    import win32api
    import win32file
    import win32con
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False
    print("Warnung: pywin32 nicht verfügbar. SD-Karten Monitor Windows-Features werden nicht funktionieren.")

try:
    import pyudev
    PYUDEV_AVAILABLE = True
except ImportError:
    PYUDEV_AVAILABLE = False
    if sys.platform == "linux":
        print("Hinweis: pyudev nicht verfügbar. Es wird der psutil-basierte Linux-Fallback verwendet.")

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

LINUX_API_AVAILABLE = True

from src.utils.media_history import MediaHistoryStore, get_media_type_from_filename
from src.utils.dji_media_paths import (
    expand_files_for_sd_clear,
    filter_media_paths_for_backup,
    MEDIA_EXTENSIONS,
    PHOTO_EXTENSIONS,
    resolve_drive_dcim_path,
    resolve_timelapse_session_active_for_paths,
    VIDEO_EXTENSIONS,
    write_backup_manifest,
)
from src.utils.file_utils import normalize_server_path
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class SDCardMonitor:
    """Überwacht SD-Karten und führt automatische Backups durch"""

    def __init__(self, config_manager, on_backup_complete=None, on_progress_update=None, on_status_change=None):
        """
        Initialisiert den SD-Karten Monitor

        Args:
            config_manager: ConfigManager Instanz für Settings
            on_backup_complete: Callback-Funktion wenn Backup abgeschlossen ist
                               Wird aufgerufen mit (backup_path, success, error_message)
                               - backup_path: Pfad zum Backup oder None bei Fehler
                               - success: True bei Erfolg, False bei Fehler
                               - error_message: Fehlermeldung bei Fehler, None bei Erfolg
            on_progress_update: Callback für Progress-Updates während Backup
                               Wird aufgerufen mit (current_mb, total_mb, speed_mbps)
            on_status_change: Callback wenn sich der Status ändert
                             Wird aufgerufen mit (status_type, data)
                             status_type kann sein: 'monitoring_started', 'sd_detected',
                             'backup_started', 'backup_finished'
        """
        self.config = config_manager
        self.on_backup_complete = on_backup_complete
        self.on_progress_update = on_progress_update
        self.on_status_change = on_status_change
        self.monitoring = False
        self.monitor_thread = None
        self.known_drives = set()
        self.backup_in_progress = False
        self.history = MediaHistoryStore.instance()  # NEU

        # NEU: Event-System für Größen-Limit-Dialog
        self.size_limit_decision_event = threading.Event()
        self.size_limit_decision = None  # Wird vom Haupt-Thread gesetzt
        self.pending_files_info = None  # Gespeicherte Datei-Infos für Dialog

    def start_monitoring(self):
        """Startet die Überwachung von SD-Karten"""
        if sys.platform == "win32" and not WINDOWS_API_AVAILABLE:
            print("SD-Karten Monitor kann nicht gestartet werden: pywin32 nicht verfügbar")
            return
            
        if sys.platform == "linux" and not LINUX_API_AVAILABLE:
            print("SD-Karten Monitor kann nicht gestartet werden: psutil nicht verfügbar")
            return

        if sys.platform == "darwin" and not PSUTIL_AVAILABLE:
            print("SD-Karten Monitor kann nicht gestartet werden: psutil nicht verfügbar")
            return

        if self.monitoring:
            return

        settings = self.config.get_settings()
        if not settings.get("sd_auto_backup", False):
            print("SD-Karten Auto-Backup ist deaktiviert")
            return

        self.monitoring = True
        # Initialisiere nur mit bereiten Laufwerken
        all_drives = self._get_available_drives()
        self.known_drives = {drive for drive in all_drives if self._is_drive_ready(drive)}
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        print("SD-Karten Überwachung gestartet")

        # Status-Callback
        if self.on_status_change:
            self.on_status_change('monitoring_started', True)

    def stop_monitoring(self):
        """Stoppt die Überwachung"""
        self.monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        print("SD-Karten Überwachung gestoppt")

        # Status-Callback
        if self.on_status_change:
            self.on_status_change('monitoring_stopped', False)

    def _get_available_drives(self):
        """Gibt alle verfügbaren Laufwerke zurück"""
        if sys.platform in ("linux", "darwin") and PSUTIL_AVAILABLE:
            drives = set()
            for part in psutil.disk_partitions(all=False):
                if '/snap/' not in part.mountpoint and '/boot' not in part.mountpoint:
                    drives.add(part.mountpoint)
            return drives

        # Linux-Fallback ohne psutil: typische Mount-Pfade prüfen
        if sys.platform == "linux":
            drives = set()
            candidate_roots = ("/media", "/run/media", "/mnt")
            for root in candidate_roots:
                if not os.path.isdir(root):
                    continue
                try:
                    for entry in os.listdir(root):
                        path = os.path.join(root, entry)
                        if os.path.isdir(path):
                            drives.add(path)
                            # /run/media/<user>/<label> hat oft eine zusätzliche Ebene
                            try:
                                for sub_entry in os.listdir(path):
                                    sub_path = os.path.join(path, sub_entry)
                                    if os.path.isdir(sub_path):
                                        drives.add(sub_path)
                            except Exception:
                                pass
                except Exception:
                    continue
            return drives
            
        if not WINDOWS_API_AVAILABLE:
            return set()
        drives = set()
        bitmask = win32api.GetLogicalDrives()
        for letter in string.ascii_uppercase:
            if bitmask & 1:
                drives.add(f"{letter}:")
            bitmask >>= 1
        return drives

    def _is_removable_drive(self, drive):
        """Prüft ob ein Laufwerk ein Wechseldatenträger ist"""
        if sys.platform in ("linux", "darwin") and PSUTIL_AVAILABLE:
            # Unter Linux/Mac greifen wir heuristisch auf typische Einhängepunkte zurück
            return drive.startswith('/media/') or drive.startswith('/run/media/') or drive.startswith('/mnt/') or drive.startswith('/Volumes/')
            
        if not WINDOWS_API_AVAILABLE:
            return False
        try:
            drive_type = win32file.GetDriveType(drive + "\\")
            return drive_type == win32con.DRIVE_REMOVABLE
        except Exception:
            return False

    def _is_drive_ready(self, drive):
        """
        Prüft ob ein Laufwerk bereit und zugreifbar ist.
        Das ist wichtig für SD-Karten, die zwar als Laufwerk erkannt werden,
        aber noch nicht bereit sind (z.B. Kamera muss erst in Datatransfer-Modus).
        """
        try:
            # Versuche auf das Root-Verzeichnis zuzugreifen
            drive_path = drive if sys.platform != "win32" else drive + "\\"
            os.listdir(drive_path)
            return True
        except (OSError, PermissionError):
            # Laufwerk existiert, ist aber nicht bereit oder nicht zugreifbar
            return False
        except Exception:
            return False

    def _is_action_cam_sd_card(self, drive):
        """
        Prüft ob das Laufwerk eine Action-Cam SD-Karte ist
        Kriterium: DCIM Ordner vorhanden
        """
        try:
            dcim_path = resolve_drive_dcim_path(drive)
            return os.path.isdir(dcim_path)
        except:
            return False

    def _monitor_loop(self):
        """Hauptschleife für die Überwachung"""
        while self.monitoring:
            try:
                current_drives = self._get_available_drives()

                # Filtere nur bereite Laufwerke (auf die zugegriffen werden kann)
                ready_drives = {drive for drive in current_drives if self._is_drive_ready(drive)}

                # Neue Laufwerke sind nur solche, die bereit UND noch nicht bekannt sind
                new_drives = ready_drives - self.known_drives

                # Prüfe neue Laufwerke
                for drive in new_drives:
                    if self._is_removable_drive(drive):
                        if self._is_action_cam_sd_card(drive):
                            print(f"Action-Cam SD-Karte erkannt: {drive}")

                            # Status-Callback: SD erkannt
                            if self.on_status_change:
                                self.on_status_change('sd_detected', drive)

                            # Warte kurz damit das Laufwerk vollständig bereit ist
                            time.sleep(1)
                            self._handle_new_sd_card(drive)

                # Aktualisiere known_drives nur mit bereiten Laufwerken
                # Laufwerke, die nicht mehr bereit sind, werden automatisch entfernt
                self.known_drives = ready_drives
                time.sleep(2)  # Prüfe alle 2 Sekunden

            except Exception as e:
                print(f"Fehler in SD-Karten Monitor: {e}")
                time.sleep(2)

    def _handle_new_sd_card(self, drive):
        """Behandelt eine neu eingesteckte SD-Karte"""
        if self.backup_in_progress:
            print("Backup läuft bereits, überspringe...")
            return

        settings = self.config.get_settings()
        backup_folder = settings.get("sd_backup_folder", "")

        if not backup_folder or not os.path.isdir(backup_folder):
            print(f"Ungültiger Backup-Ordner: {backup_folder}")
            return

        self.backup_in_progress = True

        # Status-Callback: Backup gestartet
        if self.on_status_change:
            self.on_status_change('backup_started', drive)

        # Variable für Backup-Typ
        backup_type = "full"  # "full", "selective", "cancelled", "failed"
        selected_files = None

        try:
            # NEU: Prüfe Größen-Limit bevor Backup startet
            if settings.get("sd_size_limit_enabled", False):
                result = self._check_size_limit_and_select_files(drive, settings)

                if result == "cancel":
                    # User hat abgebrochen - KEINE Fehlermeldung anzeigen
                    print("Backup abgebrochen durch User (Größen-Limit)")
                    backup_type = "cancelled"
                    # Rufe Callback auf aber ohne Fehlermeldung (stiller Abbruch)
                    # on_backup_complete wird NICHT aufgerufen bei User-Abbruch
                    return
                elif result == "proceed_all":
                    # User will alle Dateien importieren (trotz Limit)
                    selected_files = None
                    backup_type = "full"
                elif isinstance(result, list):
                    # User hat Dateien ausgewählt
                    selected_files = result
                    backup_type = "selective"
                    print(f"User hat {len(selected_files)} Dateien ausgewählt")
                else:
                    # Unter Limit oder Fehler - normal weitermachen
                    selected_files = None
                    backup_type = "full"
            else:
                selected_files = None
                backup_type = "full"

            # Erstelle Backup (mit optionaler Dateiauswahl)
            backup_path, error_message, copied_files, backup_info = self._create_backup(drive, backup_folder, selected_files)

            if backup_path:
                print(f"Backup erfolgreich: {backup_path}")

                # Lösche erfolgreich gesicherte Dateien von SD-Karte wenn gewünscht
                if settings.get("sd_clear_after_backup", False) and copied_files:
                    # Status-Callback: Leerung gestartet
                    if self.on_status_change:
                        self.on_status_change('clearing_started', drive)

                    self._clear_sd_files(copied_files)

                    # Status-Callback: Leerung beendet
                    if self.on_status_change:
                        self.on_status_change('clearing_finished', drive)
                elif settings.get("sd_clear_after_backup", False) and not copied_files:
                    # Keine Dateien zum Löschen
                    print("Keine Dateien zum Löschen (keine Dateien wurden kopiert)")

                # Werfe SD-Karte aus (optional, erstmal deaktiviert da komplex in Windows)
                # self._eject_drive(drive)

                # Rufe Callback auf mit Erfolg
                if self.on_backup_complete:
                    self.on_backup_complete(backup_path, True, None, backup_info)
            else:
                # Backup fehlgeschlagen
                print(f"Backup fehlgeschlagen: {error_message}")
                backup_type = "failed"
                if self.on_backup_complete:
                    self.on_backup_complete(None, False, error_message, None)

        except Exception as e:
            error_message = f"Fehler beim Backup: {str(e)}"
            print(error_message)
            backup_type = "failed"
            if self.on_backup_complete:
                self.on_backup_complete(None, False, error_message, None)
        finally:
            # Setze backup_in_progress IMMER zurück (auch bei Fehler oder SD-Entfernung)
            self.backup_in_progress = False

            # Status-Callback: Backup beendet (auch bei Fehler/Abbruch)
            # Übergebe backup_type und Anzahl der Dateien als Data
            if self.on_status_change:
                self.on_status_change('backup_finished', {
                    'type': backup_type,
                    'file_count': len(selected_files) if selected_files else None
                })

            # Entferne Drive aus known_drives, damit es beim nächsten Einstecken neu erkannt wird
            try:
                if drive in self.known_drives:
                    self.known_drives.discard(drive)
                    print(f"Drive {drive} aus known_drives entfernt")
            except:
                pass

    def _check_size_limit_and_select_files(self, drive, settings):
        """
        Prüft Größen-Limit und zeigt ggf. Dateiauswahl-Dialog via Haupt-Thread.

        Returns:
            "cancel": User hat abgebrochen
            "proceed_all": Alle Dateien importieren
            list: Liste der ausgewählten Dateipfade
            None: Unter Limit, normal fortfahren
        """
        try:
            limit_mb = settings.get("sd_size_limit_mb", 2000)
            # Scanne Dateien
            dcim_source = resolve_drive_dcim_path(drive)
            if not os.path.isdir(dcim_source):
                return None  # Kein DCIM Ordner, normal fortfahren

            # Sammle alle Mediendateien
            valid_video_extensions = VIDEO_EXTENSIONS
            valid_photo_extensions = PHOTO_EXTENSIONS
            valid_extensions = MEDIA_EXTENSIONS

            exclude_timelapse = settings.get("sd_exclude_timelapse_videos", True)
            all_paths = []
            for root, dirs, files in os.walk(dcim_source):
                for file in files:
                    file_lower = file.lower()
                    file_ext = os.path.splitext(file_lower)[1]
                    if file_ext in valid_extensions:
                        all_paths.append(os.path.join(root, file))
            filtered_paths, _ = filter_media_paths_for_backup(
                all_paths, dcim_source, exclude_timelapse_videos=exclude_timelapse,
            )

            files_info = []
            total_size = 0
            for file_path in filtered_paths:
                file = os.path.basename(file_path)
                file_ext = os.path.splitext(file.lower())[1]
                try:
                    size_bytes = os.path.getsize(file_path)
                    files_info.append({
                        'path': file_path,
                        'filename': file,
                        'size_bytes': size_bytes,
                        'is_video': file_ext in valid_video_extensions
                    })
                    total_size += size_bytes
                except Exception as e:
                    print(f"Fehler beim Lesen von {file_path}: {e}")
                    continue

            if not files_info:
                return None  # Keine Dateien, normal fortfahren

            total_size_mb = total_size / (1024 * 1024)
            print(f"Gesamtgröße der importierbaren Dateien: {total_size_mb:.1f} MB (Limit: {limit_mb} MB)")

            # Prüfe Limit
            if total_size_mb <= limit_mb:
                return None  # Unter Limit, normal fortfahren

            # Über Limit - benachrichtige Haupt-Thread via Callback
            print(f"⚠️ Größen-Limit überschritten! Warte auf User-Entscheidung...")

            # Speichere Datei-Infos für späteren Zugriff
            self.pending_files_info = files_info

            # Reset Event und Decision
            self.size_limit_decision_event.clear()
            self.size_limit_decision = None

            # Sende Callback an Haupt-Thread
            if self.on_status_change:
                self.on_status_change('size_limit_exceeded', {
                    'files_info': files_info,
                    'total_size_mb': total_size_mb,
                    'limit_mb': limit_mb
                })

            # Warte auf User-Entscheidung (kein Timeout - User entscheidet!)
            print("Warte auf User-Entscheidung...")
            self.size_limit_decision_event.wait()  # Kein Timeout, warte unbegrenzt

            decision = self.size_limit_decision
            print(f"User-Entscheidung erhalten: {decision}")

            return decision

        except Exception as e:
            print(f"Fehler bei Größen-Prüfung: {e}")
            import traceback
            traceback.print_exc()
            return None  # Bei Fehler normal fortfahren

    def set_size_limit_decision(self, decision):
        """
        Wird vom Haupt-Thread aufgerufen um die User-Entscheidung zu setzen.

        Args:
            decision: "cancel", "proceed_all" oder liste von Dateipfaden
        """
        self.size_limit_decision = decision
        self.size_limit_decision_event.set()
        print(f"Size-Limit-Entscheidung gesetzt: {type(decision).__name__}")


    def _create_backup(self, drive, backup_folder, selected_files=None):
        """
        Erstellt ein Backup von der SD-Karte
        Kopiert nur vollwertige Mediendateien direkt in den Backup-Ordner (flache Struktur)

        Args:
            drive: Laufwerksbuchstabe
            backup_folder: Zielordner
            selected_files: Optional Liste von Dateipfaden die kopiert werden sollen.
                           Wenn None, werden alle Dateien kopiert.

        Returns:
            Tuple (backup_path, error_message, copied_files, backup_info):
                - backup_path: Pfad zum lokalen Backup-Ordner oder None bei Fehler
                - error_message: Fehlermeldung oder None bei Erfolg
                - copied_files: Liste der erfolgreich kopierten Quelldateien (Pfade auf SD-Karte)
                - backup_info: Zusatzinfos zum optionalen Server-Backup
        """
        backup_path = None
        copied_source_files = []
        server_cleanup = None
        try:
            settings = self.config.get_settings()
            raw_pc_name = (settings.get("sd_pc_name") or "").strip()
            safe_pc_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", raw_pc_name)[:32]
            pc_part = f"[{safe_pc_name}]" if safe_pc_name else ""
            short_hash = secrets.token_hex(2)
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_dir_name = f"SD_Backup_{timestamp}{pc_part}_{short_hash}"
            backup_path = os.path.join(backup_folder, backup_dir_name)

            print(f"Starte Backup von {drive} nach {backup_path}...")
            if selected_files:
                print(f"  → Nur {len(selected_files)} ausgewählte Dateien werden kopiert")

            dcim_source = resolve_drive_dcim_path(drive)
            if not os.path.isdir(dcim_source):
                error_msg = f"DCIM Ordner nicht gefunden: {dcim_source}"
                print(error_msg)
                return None, error_msg, [], None

            os.makedirs(backup_path, exist_ok=True)

            valid_video_extensions = VIDEO_EXTENSIONS
            valid_photo_extensions = PHOTO_EXTENSIONS
            valid_extensions = MEDIA_EXTENSIONS

            media_files = []
            if selected_files:
                for file_path in selected_files:
                    if os.path.exists(file_path):
                        media_files.append(file_path)
            else:
                for root, dirs, files in os.walk(dcim_source):
                    for file in files:
                        file_ext = os.path.splitext(file.lower())[1]
                        if file_ext in valid_extensions:
                            media_files.append(os.path.join(root, file))

            if not media_files:
                error_msg = "Keine Mediendateien auf der SD-Karte gefunden"
                print(error_msg)
                return None, error_msg, [], None

            exclude_timelapse = settings.get("sd_exclude_timelapse_videos", True)
            media_files, timelapse_skipped = filter_media_paths_for_backup(
                media_files, dcim_source, exclude_timelapse_videos=exclude_timelapse,
            )
            if timelapse_skipped:
                print(f"DJI Timelapse-Filter: {timelapse_skipped} Video(s) in DJI_* übersprungen")
            if not media_files:
                error_msg = "Keine Mediendateien nach Timelapse-Filter übrig"
                print(error_msg)
                return None, error_msg, [], None

            skip_processed = settings.get("sd_skip_processed", False)
            filtered_files = []
            skipped_count = 0
            if skip_processed:
                print("Duplikat-Filter aktiv: Prüfe bereits verarbeitete Dateien...")
                for src_file in media_files:
                    ident = self.history.compute_identity(src_file)
                    if not ident:
                        filtered_files.append(src_file)
                        continue
                    identity_hash, _ = ident
                    if self.history.contains(identity_hash):
                        skipped_count += 1
                    else:
                        filtered_files.append(src_file)
            else:
                filtered_files = media_files

            if not filtered_files:
                error_msg = f"Keine neuen Dateien zum Sichern. Übersprungen: {skipped_count}"
                print(error_msg)
                return None, error_msg, [], None

            total_size = 0
            for file_path in filtered_files:
                try:
                    total_size += os.path.getsize(file_path)
                except Exception:
                    pass
            total_mb = total_size / (1024 * 1024)
            print(f"Gefunden: {len(media_files)} Mediendateien ({total_mb:.1f} MB), neu: {len(filtered_files)}, übersprungen: {skipped_count}")

            server_backup_enabled = bool(settings.get("sd_server_backup_enabled", False))
            server_backup_mode = settings.get("sd_server_backup_mode", "direct_dual_write")
            if server_backup_mode not in ("direct_dual_write", "local_then_server"):
                server_backup_mode = "direct_dual_write"
            server_backup_root = (settings.get("sd_server_backup_path") or "").strip()
            server_backup_path = None
            server_warning_message = None
            server_success = False

            if server_backup_enabled and server_backup_root:
                server_backup_path, server_cleanup, server_error = self._prepare_server_backup_target(
                    server_backup_root, backup_dir_name, settings
                )
                if server_error:
                    server_warning_message = f"Server-Backup deaktiviert (Lokal bleibt erfolgreich): {server_error}"
                    print(f"⚠️ {server_warning_message}")
                    server_backup_enabled = False

            copied_size = 0
            copied_count = 0
            start_time = time.time()
            used_filenames = set()
            local_to_server_map = []
            manifest_entries = []

            for src_file in filtered_files:
                try:
                    original_name = os.path.basename(src_file)
                    dst_filename = original_name
                    counter = 1
                    name_without_ext, ext = os.path.splitext(original_name)
                    while dst_filename.lower() in used_filenames:
                        dst_filename = f"{name_without_ext}_{counter}{ext}"
                        counter += 1
                    used_filenames.add(dst_filename.lower())

                    local_dst_file = os.path.join(backup_path, dst_filename)
                    file_size = os.path.getsize(src_file)
                    shutil.copy2(src_file, local_dst_file)
                    copied_source_files.append(src_file)
                    manifest_entries.append({
                        "dest": dst_filename,
                        "src": src_file,
                        "media_type": get_media_type_from_filename(original_name),
                    })
                    copied_size += file_size
                    copied_count += 1

                    if server_backup_enabled and server_backup_mode == "direct_dual_write" and server_backup_path:
                        try:
                            server_dst_file = os.path.join(server_backup_path, dst_filename)
                            shutil.copy2(src_file, server_dst_file)
                            server_success = True
                        except Exception as server_copy_error:
                            server_warning_message = (
                                f"Server-Backup teilweise fehlgeschlagen: {server_copy_error}"
                            )
                            server_backup_enabled = False
                    elif server_backup_enabled and server_backup_mode == "local_then_server":
                        local_to_server_map.append((local_dst_file, dst_filename))

                    ident = self.history.compute_identity(src_file)
                    if ident:
                        identity_hash, size_bytes = ident
                        media_type = get_media_type_from_filename(original_name)
                        self.history.upsert(
                            identity_hash, original_name, size_bytes, media_type,
                            backed_up_at=time.strftime('%Y-%m-%dT%H:%M:%S')
                        )

                    if self.on_progress_update and total_size > 0:
                        current_mb = copied_size / (1024 * 1024)
                        elapsed_time = time.time() - start_time
                        speed_mbps = current_mb / elapsed_time if elapsed_time > 0 else 0
                        self.on_progress_update(current_mb, total_mb, speed_mbps)

                except (IOError, OSError, FileNotFoundError) as e:
                    error_msg = f"SD-Karte wurde während des Backups entfernt: {str(e)}"
                    print(f"  ⚠️ {error_msg}")
                    return None, error_msg, copied_source_files, None
                except Exception as e:
                    print(f"  ⚠️ Fehler beim Kopieren von {src_file}: {e}")

            if server_backup_enabled and server_backup_mode == "local_then_server" and server_backup_path:
                for local_file, dst_filename in local_to_server_map:
                    try:
                        shutil.copy2(local_file, os.path.join(server_backup_path, dst_filename))
                        server_success = True
                    except Exception as server_copy_error:
                        server_warning_message = (
                            f"Server-Backup teilweise fehlgeschlagen: {server_copy_error}"
                        )
                        break

            if server_backup_enabled and server_backup_path and server_warning_message is None and not server_success:
                # Fall: aktiv, aber keine Datei kopiert (z. B. keine neuen Dateien). Kein harter Fehler.
                server_success = False

            print(f"Backup abgeschlossen: {copied_count} neue Mediendateien kopiert")
            if manifest_entries:
                session_active = resolve_timelapse_session_active_for_paths(
                    dcim_source,
                    copied_source_files,
                )
                write_backup_manifest(
                    backup_path,
                    dcim_source,
                    manifest_entries,
                    timelapse_session_active=session_active,
                )
            backup_info = {
                "server_backup_enabled": bool(settings.get("sd_server_backup_enabled", False)),
                "server_backup_mode": server_backup_mode,
                "server_backup_path": server_backup_path,
                "server_backup_success": server_success and server_warning_message is None,
                "server_warning_message": server_warning_message,
            }
            return backup_path, None, copied_source_files, backup_info

        except Exception as e:
            error_msg = f"Fehler beim Erstellen des Backups: {str(e)}"
            print(error_msg)
            if backup_path and os.path.isdir(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except Exception:
                    pass
            return None, error_msg, [], None
        finally:
            if server_cleanup:
                try:
                    server_cleanup()
                except Exception:
                    pass

    def _prepare_server_backup_target(self, server_target_root, backup_dir_name, settings):
        """Bereitet den Zielordner für optionales Server-Backup vor."""
        normalized_path, is_network_path, _ = normalize_server_path(server_target_root)
        if not normalized_path:
            return None, None, "Ungültiger Server-Backup-Pfad."

        cleanup_fn = None
        if is_network_path and platform.system() == "Windows":
            share_root = self._extract_unc_share_root(normalized_path)
            if not share_root:
                return None, None, f"Ungültiger UNC-Pfad: {normalized_path}"
            ok, message = self._connect_windows_share(share_root, settings)
            if not ok:
                return None, None, message
            cleanup_fn = lambda: self._disconnect_windows_share(share_root)

        backup_target = os.path.join(normalized_path, backup_dir_name)
        try:
            os.makedirs(backup_target, exist_ok=True)
        except Exception as e:
            if cleanup_fn:
                cleanup_fn()
                cleanup_fn = None
            return None, None, f"Server-Zielordner konnte nicht erstellt werden: {e}"
        return backup_target, cleanup_fn, None

    def _extract_unc_share_root(self, unc_path):
        """Extrahiert aus \\server\\share\\unterordner den Teil \\server\\share."""
        if not unc_path.startswith("\\\\"):
            return None
        trimmed = unc_path[2:]
        parts = trimmed.split("\\")
        if len(parts) < 2:
            return None
        return f"\\\\{parts[0]}\\{parts[1]}"

    def _connect_windows_share(self, share_root, settings):
        """Authentifiziert einen Windows-Share via net use."""
        login = (settings.get("server_login") or "").strip()
        password = settings.get("server_password") or ""
        subprocess.run(
            f'net use "{share_root}" /delete /y',
            shell=True,
            capture_output=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )
        if login:
            connect_cmd = f'net use "{share_root}" "{password}" /user:{login}'
        else:
            connect_cmd = f'net use "{share_root}"'
        result = subprocess.run(
            connect_cmd,
            shell=True,
            capture_output=True,
            text=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            return True, None
        error = (result.stderr or result.stdout or "").strip()
        return False, f"Server-Authentifizierung fehlgeschlagen: {error}"

    def _disconnect_windows_share(self, share_root):
        """Trennt eine zuvor geöffnete Windows-Share-Verbindung."""
        subprocess.run(
            f'net use "{share_root}" /delete /y',
            shell=True,
            capture_output=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

    def _clear_sd_files(self, files_to_delete):
        """
        Löscht spezifische Dateien von der SD-Karte

        Args:
            files_to_delete: Liste von Dateipfaden die gelöscht werden sollen
        """
        if not files_to_delete:
            print("Keine Dateien zum Löschen angegeben")
            return

        expanded_files = expand_files_for_sd_clear(files_to_delete)
        sidecar_count = len(expanded_files) - len(files_to_delete)
        deleted_count = 0
        error_count = 0

        if sidecar_count > 0:
            print(
                f"Lösche {len(expanded_files)} Dateien von SD-Karte "
                f"({len(files_to_delete)} Mediendateien + {sidecar_count} Sidecar(s))..."
            )
        else:
            print(f"Lösche {len(expanded_files)} erfolgreich gesicherte Dateien von SD-Karte...")

        for file_path in expanded_files:
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    deleted_count += 1
                    print(f"  ✓ Gelöscht: {os.path.basename(file_path)}")
                else:
                    print(f"  ⚠️ Datei nicht gefunden: {file_path}")
            except Exception as e:
                error_count += 1
                print(f"  ✗ Fehler beim Löschen von {file_path}: {e}")

        print(f"Löschen abgeschlossen: {deleted_count} Dateien gelöscht, {error_count} Fehler")

        # Optional: Lösche leere Verzeichnisse
        try:
            deleted_dirs = self._clean_empty_directories(expanded_files)
            if deleted_dirs > 0:
                print(f"  ℹ️ {deleted_dirs} leere Verzeichnisse entfernt")
        except Exception as e:
            print(f"  ⚠️ Fehler beim Aufräumen leerer Verzeichnisse: {e}")

    def _clean_empty_directories(self, file_paths):
        """
        Entfernt leere Verzeichnisse nach dem Löschen von Dateien

        Args:
            file_paths: Liste der gelöschten Dateipfade

        Returns:
            Anzahl der gelöschten Verzeichnisse
        """
        # Sammle alle parent directories
        directories = set()
        for file_path in file_paths:
            parent_dir = os.path.dirname(file_path)
            if parent_dir:
                directories.add(parent_dir)

        deleted_count = 0
        # Sortiere nach Tiefe (tiefste zuerst) um von unten nach oben zu löschen
        sorted_dirs = sorted(directories, key=lambda x: x.count(os.sep), reverse=True)

        for directory in sorted_dirs:
            try:
                # Nur löschen wenn Verzeichnis leer ist
                if os.path.isdir(directory) and not os.listdir(directory):
                    os.rmdir(directory)
                    deleted_count += 1
            except Exception:
                pass  # Ignoriere Fehler beim Löschen von Verzeichnissen

        return deleted_count

    def _eject_drive(self, drive):
        """
        Wirft das Laufwerk aus (optional, komplex in Windows)
        Aktuell nicht implementiert - würde ctypes und komplexe Win32 API benötigen
        """
        # TODO: Implementierung mit win32file.DeviceIoControl und IOCTL_STORAGE_EJECT_MEDIA
        pass

    def manual_backup(self, drive_letter=None):
        """
        Führt ein manuelles Backup durch

        Args:
            drive_letter: Optional - spezifisches Laufwerk (z.B. "E:")
                         Wenn None, wird das erste gefundene Action-Cam Laufwerk verwendet
        """
        if self.backup_in_progress:
            print("Backup läuft bereits")
            return False

        # Finde Laufwerk
        if drive_letter:
            drives = [drive_letter]
        else:
            drives = [d for d in self._get_available_drives()
                     if self._is_removable_drive(d) and self._is_action_cam_sd_card(d)]

        if not drives:
            print("Keine Action-Cam SD-Karte gefunden")
            return False

        # Verwende erstes gefundenes Laufwerk
        drive = drives[0]
        self._handle_new_sd_card(drive)
        return True
