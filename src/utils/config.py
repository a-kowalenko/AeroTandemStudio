import os
import json


class ConfigManager:
    CONFIG_FILE = "config/config.json"

    def __init__(self):
        self.settings = self.load_settings()

    def load_settings(self):
        """Lädt die Einstellungen aus der JSON-Datei"""
        if os.path.exists(self.CONFIG_FILE):
            try:
                with open(self.CONFIG_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
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
            "videospringer": ""
        }

    def save_settings(self, settings):
        """Speichert die Einstellungen in der JSON-Datei"""
        try:
            # Stellt sicher, dass das config Verzeichnis existiert
            os.makedirs(os.path.dirname(self.CONFIG_FILE), exist_ok=True)

            with open(self.CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(settings, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Fehler beim Speichern der Einstellungen: {e}")

    def get_settings(self):
        """Gibt die aktuellen Einstellungen zurück"""
        return self.settings.copy()

    def update_setting(self, key, value):
        """Aktualisiert eine einzelne Einstellung"""
        self.settings[key] = value
        self.save_settings(self.settings)