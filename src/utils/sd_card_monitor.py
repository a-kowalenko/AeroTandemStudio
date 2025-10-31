"""
SD-Karten Monitor
Überwacht USB/SD-Karten Anschlüsse und führt automatische Backups durch.
"""
import os
import time
import threading
import shutil
import string

try:
    import win32api
    import win32file
    import win32con
    WINDOWS_API_AVAILABLE = True
except ImportError:
    WINDOWS_API_AVAILABLE = False
    print("Warnung: pywin32 nicht verfügbar. SD-Karten Monitor wird nicht funktionieren.")


class SDCardMonitor:
    """Überwacht SD-Karten und führt automatische Backups durch"""

    def __init__(self, config_manager, on_backup_complete=None, on_progress_update=None, on_status_change=None):
        """
        Initialisiert den SD-Karten Monitor

        Args:
            config_manager: ConfigManager Instanz für Settings
            on_backup_complete: Callback-Funktion wenn Backup abgeschlossen ist
                               Wird aufgerufen mit (backup_path, success)
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

    def start_monitoring(self):
        """Startet die Überwachung von SD-Karten"""
        if not WINDOWS_API_AVAILABLE:
            print("SD-Karten Monitor kann nicht gestartet werden: pywin32 nicht verfügbar")
            return

        if self.monitoring:
            return

        settings = self.config.get_settings()
        if not settings.get("sd_auto_backup", False):
            print("SD-Karten Auto-Backup ist deaktiviert")
            return

        self.monitoring = True
        self.known_drives = self._get_available_drives()
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
        if not WINDOWS_API_AVAILABLE:
            return False
        try:
            drive_type = win32file.GetDriveType(drive + "\\")
            return drive_type == win32con.DRIVE_REMOVABLE
        except:
            return False

    def _is_action_cam_sd_card(self, drive):
        """
        Prüft ob das Laufwerk eine Action-Cam SD-Karte ist
        Kriterium: DCIM Ordner vorhanden
        """
        try:
            dcim_path = os.path.join(drive, "DCIM")
            return os.path.isdir(dcim_path)
        except:
            return False

    def _monitor_loop(self):
        """Hauptschleife für die Überwachung"""
        while self.monitoring:
            try:
                current_drives = self._get_available_drives()
                new_drives = current_drives - self.known_drives
                print('---------------')
                print('current_drives:', current_drives)
                print('known_drives:', self.known_drives)
                print('new_drives:', new_drives)
                print('---------------')
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

                self.known_drives = current_drives
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

        try:
            # Erstelle Backup
            backup_path = self._create_backup(drive, backup_folder)

            if backup_path:
                print(f"Backup erfolgreich: {backup_path}")

                # Leere SD-Karte wenn gewünscht
                if settings.get("sd_clear_after_backup", False):
                    # Status-Callback: Leerung gestartet
                    if self.on_status_change:
                        self.on_status_change('clearing_started', drive)

                    self._clear_sd_card(drive)

                    # Status-Callback: Leerung beendet
                    if self.on_status_change:
                        self.on_status_change('clearing_finished', drive)

                # Werfe SD-Karte aus (optional, erstmal deaktiviert da komplex in Windows)
                # self._eject_drive(drive)

                # Rufe Callback auf
                if self.on_backup_complete:
                    self.on_backup_complete(backup_path, True)
            else:
                print("Backup fehlgeschlagen")
                if self.on_backup_complete:
                    self.on_backup_complete(None, False)

        except Exception as e:
            print(f"Fehler beim Backup: {e}")
            if self.on_backup_complete:
                self.on_backup_complete(None, False)
        finally:
            self.backup_in_progress = False

            # Status-Callback: Backup beendet
            if self.on_status_change:
                self.on_status_change('backup_finished', backup_path if backup_path else None)

    def _create_backup(self, drive, backup_folder):
        """
        Erstellt ein Backup von der SD-Karte
        Kopiert nur vollwertige Mediendateien direkt in den Backup-Ordner (flache Struktur)

        Returns:
            Pfad zum Backup-Ordner oder None bei Fehler
        """
        backup_path = None
        try:
            # Erstelle Zeitstempel-basierten Ordnernamen
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_folder, f"SD_Backup_{timestamp}")

            print(f"Starte Backup von {drive} nach {backup_path}...")

            # DCIM Ordner
            dcim_source = os.path.join(drive, "DCIM")

            if not os.path.isdir(dcim_source):
                print(f"DCIM Ordner nicht gefunden: {dcim_source}")
                return None

            # Erstelle Backup-Ordner
            os.makedirs(backup_path, exist_ok=True)

            # Definiere erlaubte Mediendatei-Endungen
            valid_video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.webm'}
            valid_photo_extensions = {'.jpg', '.jpeg', '.png', '.tif', '.tiff', '.bmp', '.gif', '.webp', '.heic', '.raw', '.cr2', '.nef', '.arw', '.dng'}
            valid_extensions = valid_video_extensions | valid_photo_extensions

            # Sammle alle Mediendateien
            media_files = []
            for root, dirs, files in os.walk(dcim_source):
                for file in files:
                    file_lower = file.lower()
                    file_ext = os.path.splitext(file_lower)[1]

                    # Nur vollwertige Mediendateien (keine .lrf, .thm, etc.)
                    if file_ext in valid_extensions:
                        src_file = os.path.join(root, file)
                        media_files.append(src_file)

            if not media_files:
                print("Keine Mediendateien gefunden")
                return None

            # Berechne Gesamtgröße
            total_size = 0
            for file_path in media_files:
                try:
                    total_size += os.path.getsize(file_path)
                except:
                    pass

            total_mb = total_size / (1024 * 1024)
            print(f"Gefunden: {len(media_files)} Mediendateien ({total_mb:.1f} MB)")

            # Kopiere mit Progress-Tracking
            copied_size = 0
            copied_count = 0
            start_time = time.time()

            # Behandle Dateinamen-Duplikate
            used_filenames = set()

            for src_file in media_files:
                try:
                    # Original-Dateiname
                    original_name = os.path.basename(src_file)
                    dst_filename = original_name

                    # Bei Duplikaten: Füge Suffix hinzu
                    counter = 1
                    name_without_ext, ext = os.path.splitext(original_name)
                    while dst_filename.lower() in used_filenames:
                        dst_filename = f"{name_without_ext}_{counter}{ext}"
                        counter += 1

                    used_filenames.add(dst_filename.lower())
                    dst_file = os.path.join(backup_path, dst_filename)

                    # Kopiere Datei
                    file_size = os.path.getsize(src_file)
                    shutil.copy2(src_file, dst_file)
                    copied_size += file_size
                    copied_count += 1

                    # Progress-Update
                    if self.on_progress_update and total_size > 0:
                        current_mb = copied_size / (1024 * 1024)
                        elapsed_time = time.time() - start_time
                        speed_mbps = current_mb / elapsed_time if elapsed_time > 0 else 0
                        self.on_progress_update(current_mb, total_mb, speed_mbps)

                except Exception as e:
                    print(f"Fehler beim Kopieren von {src_file}: {e}")

            print(f"Backup abgeschlossen: {copied_count} Mediendateien kopiert")

            return backup_path

        except Exception as e:
            print(f"Fehler beim Erstellen des Backups: {e}")
            # Aufräumen bei Fehler
            if backup_path and os.path.isdir(backup_path):
                try:
                    shutil.rmtree(backup_path)
                except:
                    pass
            return None

    def _clear_sd_card(self, drive):
        """Löscht den Inhalt des DCIM Ordners auf der SD-Karte"""
        try:
            dcim_path = os.path.join(drive, "DCIM")
            if not os.path.isdir(dcim_path):
                return

            print(f"Lösche DCIM Ordner auf {drive}...")

            # Lösche alle Unterordner und Dateien im DCIM Ordner
            for item in os.listdir(dcim_path):
                item_path = os.path.join(dcim_path, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                except Exception as e:
                    print(f"Konnte {item_path} nicht löschen: {e}")

            print("SD-Karte geleert")

        except Exception as e:
            print(f"Fehler beim Leeren der SD-Karte: {e}")

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

