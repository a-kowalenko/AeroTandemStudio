import json
import sys
import os
import subprocess
import tempfile
import threading

import requests

import queue
from packaging import version
import tkinter as tk
from tkinter import ttk, messagebox

# <<< NEU: Import für die Windows-API >>>
if sys.platform == "win32":
    import ctypes

# --- Konfiguration ---
# ... (keine Änderungen in diesem Abschnitt) ...
GITHUB_API_URL = "https://api.github.com/repos/a-kowalenko/AeroTandemStudio/releases/latest"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "updater_settings.json")
DOWNLOAD_NAME = "setup_update.exe"


# --- Einstellungs-Management ---
def load_settings():
    # ... (keine Änderungen in diesem Abschnitt) ...
    """Lädt die Einstellungen (z.B. ignorierte Version)"""
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Konnte Einstellungen nicht laden: {e}")
        return {}


def save_settings(settings):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """Speichert die Einstellungen"""
    try:
        with open(SETTINGS_FILE, 'w') as f:
            json.dump(settings, f, indent=2)
    except Exception as e:
        print(f"Konnte Einstellungen nicht speichern: {e}")


# --- Haupt-Update-Logik (Hintergrund-Thread) ---
def check_for_updates_thread(root_gui, app_version):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Fragt die GitHub API nach der neuesten Version.
    Dieser Task läuft in einem eigenen Thread.
    'root_gui' ist die Haupt-GUI-Instanz (z.B. tk.Tk() oder Ihre App-Klasse)
    """
    try:
        # GEÄNDERT: Verwendet GITHUB_API_URL statt VERSION_JSON_URL
        response = requests.get(GITHUB_API_URL, timeout=10)
        response.raise_for_status()
        data = response.json()

        latest_version_str = data.get("tag_name", "0.0.0").lstrip('v')  # 'v1.1.0' -> '1.1.0'
        latest_version = version.parse(latest_version_str)
        current_version = version.parse(app_version)

        settings = load_settings()
        ignored_version = settings.get("ignore_version", "")

        # Prüfen, ob Update verfügbar UND nicht ignoriert
        if latest_version > current_version and latest_version_str != ignored_version:
            release_notes = data.get("release_notes", "Keine Details verfügbar.")

            # GEÄNDERT: Holt die URL aus den Release-Assets
            assets = data.get("assets", [])
            installer_url = ""
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    installer_url = asset.get("browser_download_url")
                    break

            if not installer_url:
                print("Update gefunden, aber kein .exe-Asset im Release.")
                return

            # WICHTIG: GUI-Operationen müssen zurück auf den Haupt-Thread
            root_gui.after(0,
                           prompt_user_for_update,
                           root_gui,
                           app_version,
                           latest_version_str,
                           release_notes,
                           installer_url
                           )

    except requests.RequestException as e:
        print(f"Fehler bei der Update-Prüfung (Netzwerk): {e}")
    except Exception as e:
        print(f"Fehler bei der Update-Prüfung: {e}")


def prompt_user_for_update(root_gui, app_version, latest_version, release_notes, installer_url):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Diese Funktion wird vom Hintergrund-Thread über 'root.after'
    sicher im Haupt-Thread aufgerufen, um den Dialog zu zeigen.
    """
    dialog = AskUpdateDialog(root_gui, app_version, latest_version, release_notes)

    if dialog.result == "yes":
        # Nutzer hat "Ja" gesagt, starte den Progress-Dialog
        UpdateProgressDialog(root_gui, installer_url)


# --- Download- & Installations-Thread ---
def download_and_install_thread(installer_url, progress_queue, cancel_event):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Lädt den Installer herunter und meldet den Fortschritt über eine Queue.
    Startet den Installer nach Abschluss.
    """
    temp_dir = tempfile.gettempdir()
    installer_path = os.path.join(temp_dir, DOWNLOAD_NAME)

    try:
        # <<< NEUE ÄNDERUNG: Header und explizite Redirects hinzufügen >>>
        headers = {
            'User-Agent': 'AeroTandemStudio-Updater (requests)'
        }

        # <<< NEU 2/4: Timeout hinzugefügt (10s Connect, 60s Read) >>>
        # Verhindert das Hängenbleiben bei 0%
        with requests.get(installer_url, stream=True, allow_redirects=True, headers=headers, timeout=(10, 60)) as r:
            # <<< ENDE NEUE ÄNDERUNG >>>
            r.raise_for_status()

            # Gesamtgröße des Downloads für die ProgressBar
            total_size = int(r.headers.get('content-length', 0))
            downloaded_size = 0

            # <<< ÄNDERUNG 1/3: "DETERMINATE" Signal entfernt >>>
            # (Signal wird nicht mehr benötigt)

            with open(installer_path, 'wb') as f:
                # <<< KORREKTUR: Chunk-Größe von 8KB auf 512KB erhöht >>>
                # Verhindert GUI-Überflutung und beschleunigt den Download.
                for chunk in r.iter_content(chunk_size=512 * 1024):  # 512 KB
                    # <<< ENDE KORREKTUR >>>

                    # <<< NEU 3/4: Auf Abbruch-Signal prüfen >>>
                    if cancel_event.is_set():
                        raise Exception("CancelledByUser")  # Löst Cleanup aus
                    # <<< ENDE NEU 3/4 >>>

                    f.write(chunk)

                    # <<< ÄNDERUNG 2/3: Sende Tupel (bytes, total) statt Prozent >>>
                    downloaded_size += len(chunk)
                    # Sende immer den aktuellen Download-Status
                    progress_queue.put((downloaded_size, total_size))
                    # <<< ENDE ÄNDERUNG 2/3 >>>

        # <<< NEU 4/4: Erneute Prüfung auf Abbruch nach dem Loop >>>
        if cancel_event.is_set():
            raise Exception("CancelledByUser")
        # <<< ENDE NEU 4/4 >>>

        # Download abgeschlossen
        progress_queue.put("DOWNLOAD_COMPLETE")

        # --- KORREKTUR (WinError 740): UAC Elevation anfordern ---
        try:
            if sys.platform == "win32":
                # Wir rufen die Windows Shell API auf, um den Installer
                # mit dem Verb "runas" zu starten, was die UAC-Abfrage auslöst.
                ret = ctypes.windll.shell32.ShellExecuteW(
                    None,  # hwnd (Kein übergeordnetes Fenster)
                    "runas",  # lpOperation (Admin-Rechte anfordern)
                    installer_path,  # lpFile (Unser Installer)
                    "/S",  # lpParameters (Silent-Flag für NSIS)
                    None,  # lpDirectory
                    1  # nShowCmd (SW_SHOWNORMAL)
                )

                if ret <= 32:
                    # ShellExecuteW gibt bei Fehler einen Wert <= 32 zurück.
                    # (z.B. wenn der Benutzer bei UAC auf "Nein" klickt)
                    raise Exception("UAC_CANCELLED_OR_FAILED")
            else:
                # Fallback für Nicht-Windows-Systeme
                # (Hier würde ein .exe-Installer sowieso fehlschlagen)
                subprocess.Popen(
                    [installer_path, "/S"],
                    start_new_session=True
                )

            # Signal zum Beenden der App an die GUI senden
            progress_queue.put("EXIT_APP")

        except Exception as e:
            if "UAC_CANCELLED_OR_FAILED" in str(e):
                print("Update-Fehler: Benutzer hat UAC abgelehnt oder Admin-Rechte fehlen.")
                progress_queue.put("Fehler: Administratorrechte wurden verweigert.")
            else:
                # Anderer Fehler beim Starten des Prozesses
                raise e  # Wird von der äußeren try/except-Box abgefangen
        # --- ENDE KORREKTUR ---

    except Exception as e:
        # <<< ÄNDERUNG: Robuste Fehlerbehandlung und Cleanup >>>
        if "CancelledByUser" in str(e):
            progress_queue.put("CANCELLED")
            print("Update vom Benutzer abgebrochen.")
        elif isinstance(e, requests.Timeout):
            progress_queue.put(f"Fehler: Download-Timeout (Stream hing > 60s)")
            print("Update-Fehler: Timeout")
        else:
            # Anderer Fehler (z.B. Netzwerk, 404)
            progress_queue.put(f"Fehler: {e}")
            print(f"Update-Fehler: {e}")

        # Cleanup: Lösche unvollständige Datei bei Fehler oder Abbruch
        try:
            if os.path.exists(installer_path):
                os.remove(installer_path)
                print(f"Teildownload {installer_path} gelöscht.")
        except Exception as cleanup_e:
            print(f"Fehler beim Löschen des Teildownloads: {cleanup_e}")
        # <<< ENDE ÄNDERUNG >>>


# --- GUI-Klassen ---

# <<< NEU: Hilfsfunktion zum Zentrieren von Dialogen >>>
def _center_dialog(dialog_window):
    """Hilfsfunktion, um einen Toplevel-Dialog in der Mitte des Elternfensters zu zentrieren."""
    try:
        dialog_window.update_idletasks()  # Wichtig, damit winfo_width/height korrekte Werte liefert

        # Hole Geometrie des Elternfensters (Haupt-App)
        parent = dialog_window.master
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        # Hole Größe des Dialogs
        dialog_width = dialog_window.winfo_width()
        dialog_height = dialog_window.winfo_height()

        # Berechne die Position
        x_pos = parent_x + (parent_width // 2) - (dialog_width // 2)
        y_pos = parent_y + (parent_height // 2) - (dialog_height // 2)

        dialog_window.geometry(f"+{x_pos}+{y_pos}")
    except Exception as e:
        # Fallback, falls das Zentrieren fehlschlägt (z.B. Fenster minimiert)
        print(f"Konnte Dialog nicht zentrieren: {e}")
        # Das Fenster wird trotzdem angezeigt, nur nicht zentriert.


class AskUpdateDialog(tk.Toplevel):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Ein benutzerdefinierter Dialog, der den Nutzer fragt, ob er updaten möchte,
    inklusive einer "Ignorieren"-Checkbox.
    """

    def __init__(self, parent, app_version, version, release_notes):
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Update verfügbar!")

        self.result = None  # Speichert die Nutzerentscheidung
        self.version_to_ignore = version

        # --- Widgets ---
        text = (
            f"Eine neue Version ({version}) ist verfügbar.\n"
            f"Ihre Version: {app_version}\n\n"
            f"Änderungen:\n{release_notes}"
        )

        # <<< KORREKTUR 1/2 >>>
        # 'pad_x' und 'pad_y' wurden zu 'padx' und 'pady'
        # und in die .pack()-Methode verschoben.
        tk.Label(self, text=text, justify=tk.LEFT, anchor="w").pack(padx=10, pady=10)
        # <<< ENDE KORREKTUR 1/2 >>>

        self.ignore_var = tk.BooleanVar()
        tk.Checkbutton(
            self,
            text="Diese Version nicht mehr anzeigen",
            variable=self.ignore_var
        ).pack(pady=5)

        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Jetzt aktualisieren", command=self.on_yes).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Später", command=self.on_no).pack(side=tk.LEFT, padx=10)

        self.protocol("WM_DELETE_WINDOW", self.on_no)  # Schließen = "Nein"

        # <<< NEU: Dialog zentrieren >>>
        _center_dialog(self)

        self.wait_window()  # Dialog modal machen und warten

    def on_yes(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        self.result = "yes"
        self.check_and_save_settings()
        self.destroy()

    def on_no(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        self.result = "no"
        self.check_and_save_settings()
        self.destroy()

    def check_and_save_settings(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        if self.ignore_var.get():
            save_settings({"ignore_version": self.version_to_ignore})


class UpdateProgressDialog(tk.Toplevel):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Ein Dialog, der den Download-Fortschritt anzeigt
    und die Kommunikation mit dem Download-Thread verwaltet.
    """

    def __init__(self, parent, installer_url):
        # ... (keine Änderungen in diesem Abschnitt) ...
        super().__init__(parent)
        self.transient(parent)
        self.grab_set()
        self.title("Update wird heruntergeladen...")

        self.installer_url = installer_url
        self.progress_queue = queue.Queue()  # Thread-sichere Queue

        # <<< NEU: Event für Abbruch-Signal >>>
        self.cancel_event = threading.Event()

        # <<< ÄNDERUNG: Schließen-Button ruft on_cancel auf >>>
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # --- Widgets ---

        # <<< KORREKTUR 2/2 >>>
        # 'pad_x' und 'pad_y' wurden zu 'padx' und 'pady'
        # und in die .pack()-Methode verschoben.
        self.status_label = tk.Label(self, text="Lade Update herunter...")
        self.status_label.pack(padx=20, pady=10)
        # <<< ENDE KORREKTUR 2/2 >>>

        # <<< NEU 2/2: Starte im "Pendel-Modus" (indeterminate) >>>
        self.progress_bar = ttk.Progressbar(self, orient=tk.HORIZONTAL, length=300, mode='indeterminate')
        self.progress_bar.pack(padx=20, pady=(0, 20))
        self.progress_bar.start()  # Starte die Pendel-Animation
        # <<< ENDE NEU 2/2 >>>

        # <<< NEU: "Abbrechen"-Button >>>
        self.cancel_button = tk.Button(self, text="Abbrechen", command=self.on_cancel)
        self.cancel_button.pack(pady=(0, 10))

        # --- Start ---

        # <<< NEU: Dialog zentrieren >>>
        _center_dialog(self)

        self.start_download()
        self.check_queue()  # Polling der Queue starten

    def on_cancel(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        """Wird vom Button oder Schließen-X aufgerufen."""
        if messagebox.askyesno("Abbrechen?", "Möchten Sie das Update wirklich abbrechen?"):
            self.cancel_event.set()  # Signal an Thread senden
            self.status_label.config(text="Breche ab...")
            self.cancel_button.config(state="disabled")  # Button deaktivieren

    def start_download(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        """Startet den Download in einem neuen Thread."""
        self.download_thread = threading.Thread(
            target=download_and_install_thread,
            # <<< ÄNDERUNG: Übergibt das cancel_event an den Thread >>>
            args=(self.installer_url, self.progress_queue, self.cancel_event),
            daemon=True
        )
        self.download_thread.start()

    def check_queue(self):
        # ... (keine Änderungen in diesem Abschnitt) ...
        """
        Überprüft die Queue auf Nachrichten vom Download-Thread
        und aktualisiert die GUI entsprechend.
        """

        # <<< KORREKTUR: GUI-Drosselung (Throttling) >>>
        # Wir leeren die Queue bei jedem Durchlauf (alle 100ms)
        # und verarbeiten nur die *letzte* Nachricht, um die
        # GUI nicht zu überfluten.
        msg = None
        try:
            while True:
                # Hole alle Nachrichten aus der Queue, bis sie leer ist
                msg = self.progress_queue.get_nowait()
        except queue.Empty:
            # Queue ist jetzt leer, 'msg' enthält die letzte Nachricht
            pass

        # <<< ENDE KORREKTUR >>>

        # Nur wenn wir eine Nachricht verarbeitet haben
        if msg:
            if isinstance(msg, tuple):
                # ... (keine Änderungen in diesem Abschnitt) ...
                downloaded, total = msg

                if total > 0:
                    # ... (keine Änderungen in diesem Abschnitt) ...
                    # Fall A: Wir haben eine Gesamtgröße, nutze Prozent-Modus
                    if self.progress_bar['mode'] == 'indeterminate':
                        # ... (keine Änderungen in diesem Abschnitt) ...
                        # Beim ersten Mal umschalten
                        self.progress_bar.stop()
                        self.progress_bar['mode'] = 'determinate'

                    progress_percent = int((downloaded / total) * 100)
                    # ... (keine Änderungen in diesem Abschnitt) ...
                    self.progress_bar['value'] = progress_percent
                    # Zeige MB und Prozent
                    downloaded_mb = downloaded / (1024 * 1024)
                    total_mb = total / (1024 * 1024)
                    self.status_label.config(
                        text=f"Lade herunter... {progress_percent}% ({downloaded_mb:.1f} / {total_mb:.1f} MB)")

                else:
                    # ... (keine Änderungen in diesem Abschnitt) ...
                    # Fall B: Keine Gesamtgröße, bleibe im Pendel-Modus
                    # aber zeige zumindest die heruntergeladenen MB an
                    downloaded_mb = downloaded / (1024 * 1024)
                    self.status_label.config(text=f"Lade herunter... ({downloaded_mb:.1f} MB)")
            # <<< ENDE ÄNDERUNG 3/3 >>>

            elif msg == "DOWNLOAD_COMPLETE":
                # ... (keine Änderungen in diesem Abschnitt) ...
                self.status_label.config(text="Download abgeschlossen. Starte Installation...")
                self.cancel_button.pack_forget()  # Verstecke Abbrechen-Button
                self.progress_bar.stop()
                self.progress_bar['mode'] = 'indeterminate'  # "Warte"-Animation
                self.progress_bar.start()

            elif msg == "EXIT_APP":
                # ... (keine Änderungen in diesem Abschnitt) ...
                # App 500ms nach dem Start des Installers beenden
                self.status_label.config(text="Update wird ausgeführt. App wird neu gestartet.")
                # 'self.master' bezieht sich auf das 'parent'-Widget (die Haupt-App)
                self.master.after(500, self.master.destroy)  # Schließt die Haupt-App
                # WICHTIG: Nach EXIT_APP nicht mehr pollen
                return  # <--- Schleife hier beenden

            elif msg == "CANCELLED":
                # ... (keine Änderungen in diesem Abschnitt) ...
                self.status_label.config(text="Update abgebrochen.")
                self.progress_bar.stop()
                self.after(1000, self.destroy)  # Dialog nach 1s schließen
                return  # <--- Schleife hier beenden

            elif isinstance(msg, str) and msg.startswith("Fehler:"):
                # ... (keine Änderungen in diesem Abschnitt) ...
                # Fehler anzeigen und Dialog schließen
                self.progress_bar.stop()
                self.cancel_button.pack_forget()  # Button verstecken
                messagebox.showerror("Update-Fehler", msg)
                # <<< NEU: Dialog bei Fehler schließen >>>
                self.destroy()
                return  # <--- Schleife hier beenden

        # <<< KORREKTUR: 'self.after' bleibt am Ende >>>
        # Plane den nächsten Check in 100ms
        self.after(100, self.check_queue)


# --- Öffentliche Einstiegsfunktion ---
def initialize_updater(root_gui, app_version):
    # ... (keine Änderungen in diesem Abschnitt) ...
    """
    Startet die Update-Prüfung im Hintergrund.
    Diese Funktion wird von Ihrer Haupt-App (VideoGeneratorApp) aufgerufen.

    :param root_gui: Die tk.Tk() Instanz Ihrer Haupt-App.
    :param app_version: Die aktuelle Versionsnummer Ihrer App (z.B. "1.0.0").
    """
    update_thread = threading.Thread(
        target=check_for_updates_thread,
        args=(root_gui, app_version),
        daemon=True
    )
    update_thread.start()

