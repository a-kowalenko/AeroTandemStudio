import os
import json

from src.utils.constants import CONFIG_FILE

class ConfigManager:
    CONFIG_FILE = CONFIG_FILE

    def __init__(self):
        self.settings = self.load_settings()

    def load_settings(self):
        """Lädt die Einstellungen aus der JSON-Datei"""
        # Stelle sicher, dass das Config-Verzeichnis existiert
        config_dir = os.path.dirname(self.CONFIG_FILE)
        if config_dir and not os.path.exists(config_dir):
            try:
                os.makedirs(config_dir, exist_ok=True)
            except Exception as e:
                print(f"Warnung: Konnte Config-Verzeichnis nicht erstellen: {e}")

        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                    # Stelle sicher, dass server_url existiert
                    if "server_url" not in settings:
                        settings["server_url"] = "smb://169.254.169.254/aktuell"
                    # Füge neuen Key für Skip Processed hinzu wenn nicht vorhanden
                    if "sd_skip_processed" not in settings:
                        settings["sd_skip_processed"] = False
                    if "sd_pc_name" not in settings:
                        settings["sd_pc_name"] = ""
                    if "sd_server_backup_enabled" not in settings:
                        settings["sd_server_backup_enabled"] = False
                    if "sd_server_backup_path" not in settings:
                        settings["sd_server_backup_path"] = ""
                    if "sd_server_backup_mode" not in settings:
                        settings["sd_server_backup_mode"] = "direct_dual_write"
                    if "gast_name" not in settings:
                        settings["gast_name"] = ""
                    if "qr_video_scan_seconds" not in settings:
                        settings["qr_video_scan_seconds"] = 5
                    if "qr_video_frame_step" not in settings:
                        settings["qr_video_frame_step"] = 10
                    if "qr_video_parallel_enabled" not in settings:
                        settings["qr_video_parallel_enabled"] = False
                    if "qr_video_parallel_workers" not in settings:
                        settings["qr_video_parallel_workers"] = 2
                    if "qr_video_scan_all_clips" not in settings:
                        settings["qr_video_scan_all_clips"] = True
                    if "qr_photo_parallel_enabled" not in settings:
                        settings["qr_photo_parallel_enabled"] = False
                    if "import_photo_parallel_enabled" not in settings:
                        settings["import_photo_parallel_enabled"] = True
                    if "oldschool_mode" not in settings:
                        settings["oldschool_mode"] = False
                    if "encoding_strategy" not in settings:
                        settings["encoding_strategy"] = "per_clip"
                    if "reencode_matching_clips" not in settings:
                        settings["reencode_matching_clips"] = False
                    if "sd_exclude_timelapse_videos" not in settings:
                        settings["sd_exclude_timelapse_videos"] = True
                    if "preview_encode_crf" not in settings:
                        settings["preview_encode_crf"] = 18
                    if "intro_enabled" not in settings:
                        settings["intro_enabled"] = True
                    if "qr_remove_photo_after_scan" not in settings:
                        settings["qr_remove_photo_after_scan"] = False
                    if "qr_remove_video_after_scan" not in settings:
                        settings["qr_remove_video_after_scan"] = False
                    if "qr_remove_video_max_duration_sec" not in settings:
                        settings["qr_remove_video_max_duration_sec"] = 10
                    if "show_prereleases" not in settings:
                        settings["show_prereleases"] = False
                    return settings
            except (json.JSONDecodeError, FileNotFoundError):
                return self.get_default_settings()
        return self.get_default_settings()

    def get_default_settings(self):
        """Gibt die Standardeinstellungen zurück"""
        return {
            "speicherort": "",
            "ort": "Calden",
            "dauer": 5,
            "intro_enabled": True,
            "outside_video": False,
            "gast_name": "",
            "tandemmaster": "",
            "videospringer": "",
            "oldschool_mode": False,
            "keep_tandemmaster_on_session_reset": False,
            "keep_videospringer_on_session_reset": False,
            "upload_to_server": False,
            "server_url": "smb://169.254.169.254/aktuell",  # Neue Standard-URL
            "qr_check_enabled": False,  # QR-Code Prüfung standardmäßig aus
            "photo_qr_check_enabled": False,  # QR-Code in Fotos standardmäßig aus
            "qr_video_scan_seconds": 5,  # Zeitfenster pro Clip für QR-Suche (Sekunden)
            "qr_video_frame_step": 10,  # Nur jeden N-ten Frame scannen (~3/s bei 30 fps)
            "qr_video_parallel_enabled": False,  # Hybrid: Clip 1 solo, Rest parallel
            "qr_video_parallel_workers": 2,  # Parallele Worker für QR (Video & Foto)
            "qr_photo_parallel_enabled": False,  # Parallel bidirektional über alle Fotos
            "import_photo_parallel_enabled": True,  # Parallele Thumbnail-Erzeugung beim Import
            "qr_video_scan_all_clips": True,  # False = nur erster Clip, True = alle bis Treffer
            "qr_remove_photo_after_scan": False,
            "qr_remove_video_after_scan": False,
            "qr_remove_video_max_duration_sec": 10,
            "show_prereleases": False,
            # SD-Karten Backup Einstellungen
            "sd_backup_folder": "",
            "sd_auto_backup": False,
            "sd_pc_name": "",
            "sd_server_backup_enabled": False,
            "sd_server_backup_path": "",
            "sd_server_backup_mode": "direct_dual_write",  # direct_dual_write | local_then_server
            "sd_clear_after_backup": False,
            "sd_auto_import": False,
            "sd_skip_processed": False,  # Nur neue Dateien sichern/importieren
            "sd_skip_processed_manual": False,  # Auch manuellen Import prüfen
            "sd_size_limit_enabled": False,  # Größen-Limit aktivieren
            "sd_size_limit_mb": 2000,  # Größen-Limit in MB
            "sd_exclude_timelapse_videos": True,  # DJI Timelapse-Videos in DJI_* überspringen
            "preview_encode_crf": 18,  # CRF für Preview-Re-Encode (niedriger = besser)
            # Hardware-Beschleunigung
            "hardware_acceleration_enabled": True,  # Hardware-Beschleunigung standardmäßig aktiviert
            # Paralleles Processing
            "parallel_processing_enabled": True,  # Paralleles Processing standardmäßig aktiviert
            # Codec-Auswahl
            "video_codec": "auto",  # auto, h264, h265, vp9, av1
            # Encoding-Strategie bei festem Codec: per_clip (a) oder combined (b)
            "encoding_strategy": "per_clip",
            # Bei festem Codec: auch neu encodieren wenn Clips bereits passen
            "reencode_matching_clips": False,
        }

    def save_settings(self, settings):
        """Speichert die Einstellungen in der JSON-Datei"""
        try:
            # Stellt sicher, dass das config Verzeichnis existiert
            os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)

            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)

            # Aktualisiere den internen Cache nach dem Speichern
            self.settings = settings.copy()
        except Exception as e:
            print(f"Fehler beim Speichern der Einstellungen: {e}")

    def get_settings(self):
        """Gibt die aktuellen Einstellungen zurück"""
        # Verwende den internen Cache, lade nur beim ersten Aufruf oder wenn Cache leer
        if not self.settings:
            self.settings = self.load_settings()
        return self.settings.copy()

    def reload_settings(self):
        """Lädt die Einstellungen neu aus der Datei"""
        self.settings = self.load_settings()
        return self.settings.copy()

    def update_setting(self, key, value):
        """Aktualisiert eine einzelne Einstellung"""
        self.settings[key] = value
        self.save_settings(self.settings)
