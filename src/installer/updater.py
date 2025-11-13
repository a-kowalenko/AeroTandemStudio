import json
import sys
import os
import subprocess
import tempfile
import threading
import queue
import re
from packaging import version
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import webbrowser
from datetime import datetime

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW, MIN_SWITCHABLE_VERSION

# Windows-API für UAC-Adminrechte
if sys.platform == "win32":
    import ctypes

# Konfiguration
GITHUB_API_URL = "https://api.github.com/repos/a-kowalenko/AeroTandemStudio/releases/latest"
GITHUB_ALL_RELEASES_URL = "https://api.github.com/repos/a-kowalenko/AeroTandemStudio/releases"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SETTINGS_FILE = os.path.join(PROJECT_ROOT, "updater_settings.json")
DOWNLOAD_NAME = "setup_update.exe"


def render_markdown_to_text_widget(text_widget, markdown_text):
    """Rendert Markdown-Text in ein Tkinter Text Widget mit Formatierung

    Unterstützt:
    - **Bold**
    - *Italic*
    - # Überschriften (H1-H4)
    - ## Unterüberschriften
    - - Aufzählungen
    - 1. Nummerierte Listen
    - `Code`
    - [Link Text](URL) - Anklickbare Links
    - @username - Anklickbare @-Tags (GitHub Profile, unterstützt Bindestriche)
    """
    # Konfiguriere Text-Tags für Formatierung
    text_widget.tag_configure("h1", font=("Arial", 14, "bold"), spacing3=10)
    text_widget.tag_configure("h2", font=("Arial", 12, "bold"), spacing3=8)
    text_widget.tag_configure("h3", font=("Arial", 10, "bold"), spacing3=6)
    text_widget.tag_configure("h4", font=("Arial", 9, "bold"), spacing3=4)
    text_widget.tag_configure("bold", font=("Arial", 9, "bold"))
    text_widget.tag_configure("italic", font=("Arial", 9, "italic"))
    text_widget.tag_configure("code", font=("Courier", 9), background="#f0f0f0")
    text_widget.tag_configure("bullet", lmargin1=20, lmargin2=35)
    text_widget.tag_configure("link", foreground="#0066CC", underline=True)
    text_widget.tag_configure("link_hover", foreground="#0099FF", underline=True)
    text_widget.tag_configure("mention", foreground="#6A4C93", font=("Arial", 9, "bold"))
    text_widget.tag_configure("mention_hover", foreground="#9370DB", font=("Arial", 9, "bold"))

    # Setze Cursor für Links
    text_widget.tag_bind("link", "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("link", "<Leave>", lambda e: text_widget.config(cursor=""))
    text_widget.tag_bind("mention", "<Enter>", lambda e: text_widget.config(cursor="hand2"))
    text_widget.tag_bind("mention", "<Leave>", lambda e: text_widget.config(cursor=""))

    lines = markdown_text.split('\n')

    for line in lines:
        # H1 Überschrift (# )
        if line.startswith('# ') and not line.startswith('## '):
            text_widget.insert(tk.END, line[2:] + '\n', "h1")
        # H2 Überschrift (## )
        elif line.startswith('## ') and not line.startswith('### '):
            text_widget.insert(tk.END, line[3:] + '\n', "h2")
        # H3 Überschrift (### )
        elif line.startswith('### ') and not line.startswith('#### '):
            text_widget.insert(tk.END, line[4:] + '\n', "h3")
        # H4 Überschrift (#### )
        elif line.startswith('#### '):
            text_widget.insert(tk.END, line[5:] + '\n', "h4")
        # Bullet Point (- oder *)
        elif line.strip().startswith('- ') or line.strip().startswith('* '):
            # Entferne führende Leerzeichen, füge Bullet hinzu
            content = line.strip()[2:]
            text_widget.insert(tk.END, "  • ", "bullet")
            _insert_formatted_text(text_widget, content)
            text_widget.insert(tk.END, '\n', "bullet")
        # Nummerierte Liste (1. 2. etc.)
        elif re.match(r'^\d+\.\s', line.strip()):
            # Extrahiere Nummer und Inhalt
            match = re.match(r'^(\d+)\.\s(.+)', line.strip())
            if match:
                number, content = match.groups()
                text_widget.insert(tk.END, f"  {number}. ", "bullet")
                _insert_formatted_text(text_widget, content)
                text_widget.insert(tk.END, '\n', "bullet")
        else:
            # Normale Zeile mit Inline-Formatierung
            _insert_formatted_text(text_widget, line)
            text_widget.insert(tk.END, '\n')


def _insert_formatted_text(text_widget, text):
    """Fügt Text mit Inline-Formatierung ein (**bold**, *italic*, `code`, [link](url), @mention)"""

    remaining = text

    while remaining:
        # Suche nach nächstem Format-Marker
        bold_match = re.search(r'\*\*(.+?)\*\*', remaining)
        italic_match = re.search(r'\*(.+?)\*', remaining)
        code_match = re.search(r'`(.+?)`', remaining)
        link_match = re.search(r'\[(.+?)\]\((.+?)\)', remaining)  # [text](url)
        mention_match = re.search(r'@([\w\-\.]+)', remaining)  # @username (mit Bindestrich und Punkt)

        # ...existing code...

        # Finde welcher Match zuerst kommt
        matches = []
        if bold_match:
            matches.append(('bold', bold_match.start(), bold_match))
        if italic_match:
            matches.append(('italic', italic_match.start(), italic_match))
        if code_match:
            matches.append(('code', code_match.start(), code_match))
        if link_match:
            matches.append(('link', link_match.start(), link_match))
        if mention_match:
            matches.append(('mention', mention_match.start(), mention_match))

        if not matches:
            # Kein Formatting mehr, füge Rest ein
            text_widget.insert(tk.END, remaining)
            break

        # Sortiere nach Position
        matches.sort(key=lambda x: x[1])
        format_type, pos, match = matches[0]

        # Füge Text vor dem Match ein
        text_widget.insert(tk.END, remaining[:match.start()])

        # Füge formatierten Text ein
        if format_type == 'link':
            # Link: [text](url)
            link_text = match.group(1)
            link_url = match.group(2)

            # Erstelle eindeutigen Tag für diesen Link
            tag_name = f"link_{id(match)}"
            text_widget.tag_configure(tag_name, foreground="#0066CC", underline=True)

            # Füge Link-Text mit Tag ein
            start_index = text_widget.index(tk.INSERT)
            text_widget.insert(tk.END, link_text, (tag_name, "link"))

            # Binde Click-Event an diesen spezifischen Link
            text_widget.tag_bind(tag_name, "<Button-1>",
                                lambda e, url=link_url: webbrowser.open(url))
            text_widget.tag_bind(tag_name, "<Enter>",
                                lambda e: text_widget.config(cursor="hand2"))
            text_widget.tag_bind(tag_name, "<Leave>",
                                lambda e: text_widget.config(cursor=""))

        elif format_type == 'mention':
            # @username -> GitHub Profile Link
            username = match.group(1)
            github_url = f"https://github.com/{username}"

            # Erstelle eindeutigen Tag für diesen Mention
            tag_name = f"mention_{id(match)}"
            text_widget.tag_configure(tag_name, foreground="#6A4C93", font=("Arial", 9, "bold"))

            # Füge @username mit Tag ein
            text_widget.insert(tk.END, f"@{username}", (tag_name, "mention"))

            # Binde Click-Event an diesen spezifischen Mention
            text_widget.tag_bind(tag_name, "<Button-1>",
                                lambda e, url=github_url: webbrowser.open(url))
            text_widget.tag_bind(tag_name, "<Enter>",
                                lambda e: text_widget.config(cursor="hand2"))
            text_widget.tag_bind(tag_name, "<Leave>",
                                lambda e: text_widget.config(cursor=""))
        else:
            # Bold, Italic, Code - wie vorher
            text_widget.insert(tk.END, match.group(1), format_type)

        # Setze remaining auf Text nach dem Match
        remaining = remaining[match.end():]


def render_markdown_to_frame(parent_frame, markdown_text):
    """Rendert Markdown-Text direkt in ein Frame mit Labels

    Diese Funktion erstellt Labels für jeden Markdown-Block und fügt sie
    direkt in das parent_frame ein. Dies ermöglicht natürliches Scrolling
    ohne ein Text-Widget mit eigener Scrollfähigkeit.

    Unterstützt:
    - # Überschriften (H1-H4)
    - **Bold** und *Italic* (eingeschränkt)
    - - Aufzählungen
    - 1. Nummerierte Listen
    - Normale Textzeilen
    """
    lines = markdown_text.split('\n')

    for line in lines:
        # Leere Zeilen überspringen
        if not line.strip():
            continue

        # H1 Überschrift (# )
        if line.startswith('# ') and not line.startswith('## '):
            label = tk.Label(
                parent_frame,
                text=line[2:],
                font=("Arial", 14, "bold"),
                bg="white",
                anchor="w",
                justify="left"
            )
            label.pack(fill="x", padx=10, pady=(10, 5))

        # H2 Überschrift (## )
        elif line.startswith('## ') and not line.startswith('### '):
            label = tk.Label(
                parent_frame,
                text=line[3:],
                font=("Arial", 12, "bold"),
                bg="white",
                anchor="w",
                justify="left"
            )
            label.pack(fill="x", padx=10, pady=(8, 4))

        # H3 Überschrift (### )
        elif line.startswith('### ') and not line.startswith('#### '):
            label = tk.Label(
                parent_frame,
                text=line[4:],
                font=("Arial", 10, "bold"),
                bg="white",
                anchor="w",
                justify="left"
            )
            label.pack(fill="x", padx=10, pady=(6, 3))

        # H4 Überschrift (#### )
        elif line.startswith('#### '):
            label = tk.Label(
                parent_frame,
                text=line[5:],
                font=("Arial", 9, "bold"),
                bg="white",
                anchor="w",
                justify="left"
            )
            label.pack(fill="x", padx=10, pady=(4, 2))

        # Bullet Point (- oder *)
        elif line.strip().startswith('- ') or line.strip().startswith('* '):
            content = line.strip()[2:]
            # Entferne einfache Markdown-Formatierung für Label
            content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)  # **bold** -> text
            content = re.sub(r'\*(.+?)\*', r'\1', content)      # *italic* -> text
            content = re.sub(r'`(.+?)`', r'\1', content)        # `code` -> text

            label = tk.Label(
                parent_frame,
                text=f"  • {content}",
                font=("Arial", 9),
                bg="white",
                anchor="w",
                justify="left",
                wraplength=550  # Zeilenumbruch bei langen Texten
            )
            label.pack(fill="x", padx=20, pady=1)

        # Nummerierte Liste (1. 2. etc.)
        elif re.match(r'^\d+\.\s', line.strip()):
            match = re.match(r'^(\d+)\.\s(.+)', line.strip())
            if match:
                number, content = match.groups()
                # Entferne einfache Markdown-Formatierung für Label
                content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
                content = re.sub(r'\*(.+?)\*', r'\1', content)
                content = re.sub(r'`(.+?)`', r'\1', content)

                label = tk.Label(
                    parent_frame,
                    text=f"  {number}. {content}",
                    font=("Arial", 9),
                    bg="white",
                    anchor="w",
                    justify="left",
                    wraplength=550
                )
                label.pack(fill="x", padx=20, pady=1)

        else:
            # Normale Zeile
            content = line
            # Entferne einfache Markdown-Formatierung für Label
            content = re.sub(r'\*\*(.+?)\*\*', r'\1', content)
            content = re.sub(r'\*(.+?)\*', r'\1', content)
            content = re.sub(r'`(.+?)`', r'\1', content)

            if content.strip():  # Nur nicht-leere Zeilen
                label = tk.Label(
                    parent_frame,
                    text=content,
                    font=("Arial", 9),
                    bg="white",
                    anchor="w",
                    justify="left",
                    wraplength=550
                )
                label.pack(fill="x", padx=10, pady=1)


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


def get_all_releases(min_version=None):
    """Holt alle verfügbaren Releases von GitHub

    Args:
        min_version: Minimale Version (String), die berücksichtigt werden soll

    Returns:
        List of dicts mit: {
            'tag_name': str,      # z.B. "0.5.1.2"
            'published_at': str,  # z.B. "2024-01-15T10:30:00Z"
            'body': str,          # Release Notes (Markdown)
            'installer_url': str  # Download-URL für .exe
        }
        Oder None bei Fehler
    """
    try:
        response = requests.get(GITHUB_ALL_RELEASES_URL, timeout=10)
        response.raise_for_status()
        releases_data = response.json()

        releases = []
        min_ver = version.parse(min_version) if min_version else None

        for release in releases_data:
            # Parse version (entferne 'v' prefix)
            tag = release.get("tag_name", "").lstrip('v')
            if not tag:
                continue

            # Filter nach min_version
            if min_ver:
                try:
                    rel_ver = version.parse(tag)
                    if rel_ver < min_ver:
                        continue
                except:
                    continue

            # Suche .exe Installer
            assets = release.get("assets", [])
            installer_url = ""
            for asset in assets:
                if asset.get("name", "").endswith(".exe"):
                    installer_url = asset.get("browser_download_url")
                    break

            # Nur Releases mit Installer aufnehmen
            if installer_url:
                releases.append({
                    'tag_name': tag,
                    'published_at': release.get("published_at", ""),
                    'body': release.get("body", "Keine Details verfügbar."),
                    'installer_url': installer_url
                })

        # Sortiere absteigend nach Version
        releases.sort(key=lambda r: version.parse(r['tag_name']), reverse=True)

        return releases

    except requests.RequestException as e:
        print(f"Netzwerkfehler beim Abrufen der Releases: {e}")
        return None
    except Exception as e:
        print(f"Fehler beim Abrufen der Releases: {e}")
        return None


def check_for_updates_thread(root_gui, app_version, show_no_update_message=False, force_check=False):
    """Hintergrund-Thread für Update-Prüfung über GitHub API

    Args:
        root_gui: Tkinter Root-Widget
        app_version: Aktuelle App-Version
        show_no_update_message: Zeige Nachricht wenn keine Updates
        force_check: Bei True werden ignorierte Versionen trotzdem angezeigt (für manuelle Suche)
    """
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

        # Prüfe ob Update verfügbar (bei force_check ignoriere die Ignorierung)
        is_ignored = latest_version_str == ignored_version and not force_check
        if latest_version > current_version and not is_ignored:
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


def install_specific_version(root_gui, installer_url):
    """Startet Installation einer spezifischen Version

    Args:
        root_gui: Tkinter Root-Widget
        installer_url: Download-URL des Installers
    """
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

        # Setze Mindestgröße für Dialog
        self.minsize(500, 400)

        # Versions-Info Text (oben)
        info_text = (
            f"Eine neue Version ({version}) ist verfügbar.\n"
            f"Ihre installierte Version: {app_version}"
        )
        info_label = tk.Label(self, text=info_text, justify=tk.LEFT, anchor="w", font=("Arial", 10))
        info_label.pack(padx=15, pady=(15, 10), anchor="w")

        # Änderungen Label
        changes_label = tk.Label(self, text="Änderungen:", justify=tk.LEFT, anchor="w", font=("Arial", 10, "bold"))
        changes_label.pack(padx=15, pady=(10, 5), anchor="w")

        # Scrollbares Textfeld für Release Notes
        text_frame = tk.Frame(self)
        text_frame.pack(padx=15, pady=(0, 10), fill=tk.BOTH, expand=True)

        # Scrollbar
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Text Widget (scrollbar)
        self.release_notes_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            yscrollcommand=scrollbar.set,
            height=10,
            width=60,
            relief=tk.SUNKEN,
            borderwidth=2,
            font=("Arial", 9),
            state=tk.NORMAL
        )
        self.release_notes_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.release_notes_text.yview)

        # Release Notes mit Markdown-Rendering einfügen
        if release_notes:
            render_markdown_to_text_widget(self.release_notes_text, release_notes)
        else:
            self.release_notes_text.insert(tk.END, "Keine Details verfügbar.")

        self.release_notes_text.config(state=tk.DISABLED)  # Read-only

        # Ignorieren-Checkbox
        self.ignore_var = tk.BooleanVar()
        checkbox = tk.Checkbutton(
            self,
            text="Diese Version nicht mehr anzeigen",
            variable=self.ignore_var,
            font=("Arial", 9)
        )
        checkbox.pack(padx=15, pady=(5, 10), anchor="w")

        # Buttons (unten)
        btn_frame = tk.Frame(self)
        btn_frame.pack(pady=(0, 15), padx=15, fill=tk.X)

        # Später Button (links)
        later_btn = tk.Button(
            btn_frame,
            text="Später",
            command=self.on_no,
            width=15,
            font=("Arial", 9)
        )
        later_btn.pack(side=tk.LEFT)

        # Jetzt aktualisieren Button (rechts)
        update_btn = tk.Button(
            btn_frame,
            text="Jetzt aktualisieren",
            command=self.on_yes,
            width=20,
            font=("Arial", 9, "bold"),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049"
        )
        update_btn.pack(side=tk.RIGHT)

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


def initialize_updater(root_gui, app_version, show_no_update_message=False, force_check=False):
    """Startet Update-Prüfung im Hintergrund - Haupt-Einstiegspunkt

    Args:
        root_gui: Tkinter Root-Widget
        app_version: Aktuelle App-Version (z.B. "0.1.0.7")
        show_no_update_message: Zeige Nachricht wenn keine Updates verfügbar
        force_check: Bei True werden ignorierte Versionen trotzdem angezeigt (für manuelle Suche)
    """
    update_thread = threading.Thread(
        target=check_for_updates_thread,
        args=(root_gui, app_version, show_no_update_message, force_check),
        daemon=True
    )
    update_thread.start()