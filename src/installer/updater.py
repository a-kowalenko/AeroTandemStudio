import json
import sys
import os
import subprocess
import tempfile
import threading
import queue
from packaging import version
import tkinter as tk
from tkinter import ttk, messagebox
import requests

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW

# Windows-API für UAC-Adminrechte
if sys.platform == "win32":
    import ctypes

# Konfiguration
GITHUB_API_URL = "https://api.github.com/repos/a-kowalenko/AeroTandemStudio/releases/latest"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "updater_settings.json")
DOWNLOAD_NAME = "setup_update.exe"


def load_settings():
    """Lädt gespeicherte Einstellungen wie ignorierte Versionen"""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Einstellungen konnten nicht geladen werden: {e}")
        return {}


def save_settings(settings):
    """Speichert Einstellungen in JSON-Datei"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Einstellungen konnten nicht gespeichert werden: {e}")


def check_for_updates_thread(root_gui, app_version, show_no_update_message=False):
    """Hintergrund-Thread für Update-Prüfung über GitHub API"""
    try:
        response = requests.get(GITHUB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Version parsing (entfernt 'v' prefix)
        latest_version_str = data.get("tag_name", "0.0.0").lstrip('v')
        latest_version = version.parse(latest_version_str)
        current_version = version.parse(app_version)

        settings = load_settings()
        ignored_version = settings.get("ignore_version", "")

        # Prüfe ob Update verfügbar und nicht ignoriert
        if latest_version > current_version and latest_version_str != ignored_version:
            release_notes = data.get("body", "Keine Details verfügbar.")  # Korrektur: 'body' statt 'release_notes'

            # Suche nach .exe Installer in den Release-Assets
            assets = data.get("assets", [])
            installer_url = ""
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    installer_url = asset.get("browser_download_url")
                    break

            if not installer_url:
                print("Update gefunden, aber keine .exe-Datei im Release.")
                if show_no_update_message:
                    root_gui.after(0, lambda: messagebox.showinfo(
                        "Update-Prüfung",
                        f"Update {latest_version_str} verfügbar, aber kein Installer gefunden."
                    ))
                return

            # Zeige Update-Dialog im Haupt-Thread
            root_gui.after(0, prompt_user_for_update, root_gui, app_version,
                           latest_version_str, release_notes, installer_url)

        else:
            # Kein Update verfügbar
            if show_no_update_message:
                if latest_version_str == ignored_version:
                    message_text = f"Version {latest_version_str} ist verfügbar, wurde aber ignoriert."
                elif latest_version <= current_version:
                    message_text = f"Sie haben bereits die neueste Version ({app_version})."
                else:
                    message_text = "Keine Updates verfügbar."

                root_gui.after(0, lambda: messagebox.showinfo(
                    "Update-Prüfung",
                    message_text
                ))

    except requests.RequestException as e:
        error_msg = f"Netzwerkfehler bei Update-Prüfung: {e}"
        print(error_msg)
        if show_no_update_message:
            root_gui.after(0, lambda: messagebox.showerror(
                "Update-Fehler",
                "Update-Prüfung fehlgeschlagen: Netzwerkfehler"
            ))
    except Exception as e:
        error_msg = f"Fehler bei Update-Prüfung: {e}"
        print(error_msg)
        if show_no_update_message:
            root_gui.after(0, lambda: messagebox.showerror(
                "Update-Fehler",
                "Update-Prüfung fehlgeschlagen"
            ))


def prompt_user_for_update(root_gui, app_version, latest_version, release_notes, installer_url):
    """Zeigt Dialog ob Update installiert werden soll"""
    dialog = AskUpdateDialog(root_gui, app_version, latest_version, release_notes)
    if dialog.result == "yes":
        UpdateProgressDialog(root_gui, installer_url)


def download_and_install_thread(installer_url, progress_queue, cancel_event):
    """Lädt Installer herunter und startet ihn mit Admin-Rechten"""
    temp_dir = tempfile.gettempdir()
    installer_path = os.path.join(temp_dir, DOWNLOAD_NAME)

    try:
        headers = {'User-Agent': 'AeroTandemStudio-Updater (requests)'}

        # Stream Download mit Timeout
        with requests.get(installer_url, stream=True, allow_redirects=True,
                          headers=headers, timeout=(10, 60)) as r:
            r.raise_for_status()

            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0

            # Download mit Fortschritts-Updates
            with open(installer_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=512 * 1024):  # 512KB chunks
                    if cancel_event.is_set():
                        raise Exception("CancelledByUser")

                    f.write(chunk)
                    downloaded_size += len(chunk)
                    progress_queue.put((downloaded_size, total_size))

        # Nochmal auf Abbruch prüfen nach Download
        if cancel_event.is_set():
            raise Exception("CancelledByUser")

        progress_queue.put("DOWNLOAD_COMPLETE")

        # Installer mit Admin-Rechten starten (Windows)
        try:
            if sys.platform == "win32":
                # ShellExecute mit "runas" für UAC Prompt
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None, "runas", installer_path, "/S", None, 1
                )
                if ret <= 32:  # Fehler bei ShellExecute
                    raise Exception("UAC_CANCELLED_OR_FAILED")
            else:
                # Fallback für Nicht-Windows
                subprocess.Popen([installer_path, "/S"], start_new_session=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            progress_queue.put("EXIT_APP")

        except Exception as e:
            if "UAC_CANCELLED_OR_FAILED" in str(e):
                progress_queue.put("Fehler: Administratorrechte wurden verweigert.")
            else:
                raise e

    except Exception as e:
        # Fehlerbehandlung und Cleanup
        if "CancelledByUser" in str(e):
            progress_queue.put("CANCELLED")
        elif isinstance(e, requests.Timeout):
            progress_queue.put("Fehler: Download-Timeout")
        else:
            progress_queue.put(f"Fehler: {e}")

        # Lösche teilweise heruntergeladene Datei
        try:
            if os.path.exists(installer_path):
                os.remove(installer_path)
        except Exception as cleanup_e:
            print(f"Fehler beim Löschen: {cleanup_e}")


def _center_dialog(dialog_window):
    """Zentriert Dialogfenster über Parent-Fenster"""
    try:
        dialog_window.update_idletasks()
        parent = dialog_window.master

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        dialog_width = dialog_window.winfo_width()
        dialog_height = dialog_window.winfo_height()

        x_pos = parent_x + (parent_width // 2) - (dialog_width // 2)
        y_pos = parent_y + (parent_height // 2) - (dialog_height // 2)

        dialog_window.geometry(f"+{x_pos}+{y_pos}")
    except Exception as e:
        print(f"Dialog konnte nicht zentriert werden: {e}")


class AskUpdateDialog(tk.Toplevel):
    """Dialog zur Update-Bestätigung mit Ignorieren-Option"""

    def __init__(self, parent, app_version, version, release_notes):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Update verfügbar!")

        self.result = None
        self.version_to_ignore = version

        # Info-Text
        text = (
            f"Eine neue Version ({version}) ist verfügbar.\n"
            f"Ihre Version: {app_version}\n\n"
            f"Änderungen:\n{release_notes}"
        )

        tk.Label(self, text=text, justify=tk.LEFT, anchor="w").pack(padx=10, pady=10)

        # Ignorieren-Checkbox
        self.ignore_var = tk.BooleanVar()
        tk.Checkbutton(self, text="Diese Version nicht mehr anzeigen",
                       variable=self.ignore_var).pack(pady=5)

        # Buttons
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Jetzt aktualisieren",
                  command=self.on_yes).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Später",
                  command=self.on_no).pack(side=tk.LEFT, padx=10)

        self.protocol("WM_DELETE_WINDOW", self.on_no)
        _center_dialog(self)
        self.wait_window()  # Modal dialog

    def on_yes(self):
        self.result = "yes"
        self.check_and_save_settings()
        self.destroy()

    def on_no(self):
        self.result = "no"
        self.check_and_save_settings()
        self.destroy()

    def check_and_save_settings(self):
        """Speichert Ignorieren-Einstellung wenn aktiviert"""
        if self.ignore_var.get():
            save_settings({"ignore_version": self.version_to_ignore})


class UpdateProgressDialog(tk.Toplevel):
    """Zeigt Download-Fortschritt und ermöglicht Abbruch"""

    def __init__(self, parent, installer_url):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Update wird heruntergeladen...")

        self.installer_url = installer_url
        self.progress_queue = queue.Queue()
        self.cancel_event = threading.Event()

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # GUI-Elemente
        self.status_label = tk.Label(self, text="Lade Update herunter...")
        self.status_label.pack(padx=20, pady=10)

        # Starte mit unbestimmter Progressbar
        self.progress_bar = ttk.Progressbar(self, orient=tk.HORIZONTAL,
                                            length=300, mode='indeterminate')
        self.progress_bar.pack(padx=20, pady=(0, 20))
        self.progress_bar.start()

        self.cancel_button = tk.Button(self, text="Abbrechen", command=self.on_cancel)
        self.cancel_button.pack(pady=(0, 10))

        _center_dialog(self)
        self.start_download()
        self.check_queue()

    def on_cancel(self):
        """Bestätigt und behandelt Abbruch durch Benutzer"""
        if messagebox.askyesno("Abbrechen?", "Möchten Sie das Update wirklich abbrechen?"):
            self.cancel_event.set()
            self.status_label.config(text="Breche ab...")
            self.cancel_button.config(state="disabled")

    def start_download(self):
        """Startet Download im separaten Thread"""
        self.download_thread = threading.Thread(
            target=download_and_install_thread,
            args=(self.installer_url, self.progress_queue, self.cancel_event),
            daemon=True
        )
        self.download_thread.start()

    def check_queue(self):
        """Verarbeitet Nachrichten vom Download-Thread (alle 100ms)"""
        msg = None
        try:
            # Hole letzte Nachricht aus Queue (leere Queue)
            while True:
                msg = self.progress_queue.get_nowait()
        except queue.Empty:
            pass

        if msg:
            if isinstance(msg, tuple):
                # Fortschrittsupdate
                downloaded, total = msg
                if total > 0:
                    # Wechsle zu bestimmter Progressbar beim ersten Mal
                    if self.progress_bar['mode'] == 'indeterminate':
                        self.progress_bar.stop()
                        self.progress_bar['mode'] = 'determinate'

                    progress_percent = int((downloaded / total) * 100)
                    self.progress_bar['value'] = progress_percent

                    # Zeige MB und Prozent
                    downloaded_mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    self.status_label.config(
                        text=f"Lade herunter... {progress_percent}% ({downloaded_mb:.1f} / {total_mb:.1f} MB)")
                else:
                    # Keine Gesamtgröße bekannt, zeige nur MB
                    downloaded_mb = downloaded / (1024 * 1024)
                    self.status_label.config(text=f"Lade herunter... ({downloaded_mb:.1f} MB)")

            elif msg == "DOWNLOAD_COMPLETE":
                self.status_label.config(text="Download abgeschlossen. Starte Installation...")
                self.cancel_button.pack_forget()  # Verstecke Abbruch-Button
                self.progress_bar.stop()
                self.progress_bar['mode'] = 'indeterminate'  # Warte-Animation
                self.progress_bar.start()

            elif msg == "EXIT_APP":
                self.status_label.config(text="Update wird ausgeführt. App wird neu gestartet.")
                self.master.after(500, self.master.destroy)  # Beende Haupt-App
                return  # Beende Queue-Checking

            elif msg == "CANCELLED":
                self.status_label.config(text="Update abgebrochen.")
                self.progress_bar.stop()
                self.after(1000, self.destroy)
                return

            elif isinstance(msg, str) and msg.startswith("Fehler:"):
                self.progress_bar.stop()
                self.cancel_button.pack_forget()
                messagebox.showerror("Update-Fehler", msg)
                self.destroy()
                return

        # Nächsten Check planen
        self.after(100, self.check_queue)


def initialize_updater(root_gui, app_version, show_no_update_message=False):
    """Startet Update-Prüfung im Hintergrund - Haupt-Einstiegspunkt"""
    update_thread = threading.Thread(
        target=check_for_updates_thread,
        args=(root_gui, app_version, show_no_update_message),
        daemon=True
    )
    update_thread.start()