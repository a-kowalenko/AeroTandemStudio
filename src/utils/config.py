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
                    return settings
            except (json.JSONDecodeError, FileNotFoundError):
                return self.get_default_settings()
        return self.get_default_settings()

    def get_default_settings(self):
        """Gibt die Standardeinstellungen zurück"""
        return {
            "speicherort": "",
            "ort": "Calden",
            "dauer": 8,
            "outside_video": False,
            "tandemmaster": "",
            "videospringer": "",
            "upload_to_server": False,
            "server_url": "smb://169.254.169.254/aktuell",  # Neue Standard-URL
            "qr_check_enabled": False,  # QR-Code Prüfung standardmäßig aus
            # SD-Karten Backup Einstellungen
            "sd_backup_folder": "",
            "sd_auto_backup": False,
            "sd_clear_after_backup": False,
            "sd_auto_import": False,
            "sd_skip_processed": False,  # Nur neue Dateien sichern/importieren
            "sd_skip_processed_manual": False,  # Auch manuellen Import prüfen
            # Hardware-Beschleunigung
            "hardware_acceleration_enabled": True,  # Hardware-Beschleunigung standardmäßig aktiviert
            # Paralleles Processing
            "parallel_processing_enabled": True,  # Paralleles Processing standardmäßig aktiviert
            # Codec-Auswahl
            "video_codec": "auto"  # auto, h264, h265, vp9, av1
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
