import platform
import re
import traceback
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import os
import subprocess
import time
import threading
import shutil
from typing import List, Optional

from src.gui.components.error_dialog import ErrorDialog
from src.utils.constants import LOG_FILE, SUBPROCESS_CREATE_NO_WINDOW
from src.utils.media_history import MediaHistoryStore
from src.utils.natural_sort import natural_sort_key, sort_paths_by_basename
from src.utils.dji_media_paths import (
    collect_media_paths_from_tree,
    dcim_has_timelapse_photo_tree,
    filter_collected_media_for_timelapse,
    resolve_dcim_root,
    should_skip_file_for_timelapse_session,
)
from src.utils.file_times import (
    format_creation_date,
    format_creation_time,
    get_creation_timestamp,
)
from src.utils.media_datetime import (
    format_epoch_date,
    format_epoch_time,
    format_photo_table_datetime,
    get_photo_display_epoch,
    resolve_video_display_epoch,
)
from src.utils.photo_thumbnail import (
    THUMB_MAX_SIZE,
    build_pil_thumbnail,
    build_pil_thumbnails_parallel,
)

# Mit handle_drop / Pipeline abgestimmt (v. a. .mp4 für Videos)
_DND_VIDEO_EXT = ".mp4"
_DND_PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp")

_DROP_ZONE_HELP_TEXT = (
    "Videos (.mp4) und Fotos (.jpg, .png) oder Ordner (eine Ebene) hierher ziehen"
)
_TEMP_DIR_WAIT_TIMEOUT_SEC = 10.0
_TEMP_DIR_POLL_INTERVAL_SEC = 0.1

def _norm_import_path(path: str) -> str:
    """Einheitliche Normalisierung für Import-Quell-Pfade (Deduplizierung)."""
    return os.path.normcase(os.path.normpath(path))


def _dnd_classify_file(path: str):
    """Liefert 'video', 'photo' oder None für einen Dateipfad."""
    pl = path.lower()
    if pl.endswith(_DND_VIDEO_EXT):
        return "video"
    if pl.endswith(_DND_PHOTO_EXTS):
        return "photo"
    return None


def _collect_media_from_directory(dir_path: str, exclude_timelapse_videos: bool = True):
    """
    Sammelt unterstützte Medien im Ordner.
    Bei DJI/DCIM-Struktur rekursiv mit Timelapse-Filter (nur Fotos aus TIMELAPSE).
    """
    dcim_root = resolve_dcim_root(dir_path)
    if dcim_root:
        all_media = collect_media_paths_from_tree(dir_path)
        return filter_collected_media_for_timelapse(
            all_media,
            dir_path,
            exclude_timelapse_videos=exclude_timelapse_videos,
        )

    videos, photos = [], []
    try:
        with os.scandir(dir_path) as it:
            entries = sorted(it, key=lambda e: natural_sort_key(e.name))
    except OSError:
        return videos, photos, 0
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            continue
        kind = _dnd_classify_file(entry.path)
        if kind == "video":
            videos.append(entry.path)
        elif kind == "photo":
            photos.append(entry.path)
    return videos, photos, 0


class ImportProgressDialog(tk.Toplevel):
    def __init__(self, parent, title="Dateien werden importiert..."):
        super().__init__(parent)
        self.title(title)
        width, height = 450, 200
        
        # Zentriere das Fenster über dem Parent
        if parent.winfo_viewable():
            x = parent.winfo_rootx() + (parent.winfo_width() // 2) - (width // 2)
            y = parent.winfo_rooty() + (parent.winfo_height() // 2) - (height // 2)
            self.geometry(f"{width}x{height}+{x}+{y}")
        else:
            self.geometry(f"{width}x{height}")
            
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.cancel_requested = threading.Event()

        # UI Elements
        self.status_var = tk.StringVar(value="Vorbereitung...")
        tk.Label(self, textvariable=self.status_var, font=("Arial", 10, "bold")).pack(pady=(10, 5))

        self.file_progress_var = tk.DoubleVar(value=0)
        self.file_progress = ttk.Progressbar(self, variable=self.file_progress_var, maximum=100)
        self.file_progress.pack(fill="x", padx=20, pady=5)

        self.global_status_var = tk.StringVar(value="Gesamtfortschritt: 0%")
        tk.Label(self, textvariable=self.global_status_var, font=("Arial", 9)).pack(pady=(10, 0))

        self.global_progress_var = tk.DoubleVar(value=0)
        self.global_progress = ttk.Progressbar(self, variable=self.global_progress_var, maximum=100)
        self.global_progress.pack(fill="x", padx=20, pady=5)

        self.speed_var = tk.StringVar(value="")
        tk.Label(self, textvariable=self.speed_var, font=("Arial", 9)).pack(pady=5)

        self.cancel_button = ttk.Button(self, text="Abbrechen", command=self._on_cancel)
        self.cancel_button.pack(pady=5)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _on_cancel(self):
        self.status_var.set("Abbruch wird ausgeführt... Bitte warten.")
        self.cancel_button.config(state="disabled")
        self.cancel_requested.set()


class DragDropFrame:
    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance  # Wichtig: Referenz zur Haupt-App
        self.frame = tk.Frame(parent, relief="sunken", borderwidth=2, padx=10, pady=10)
        self.video_paths = []
        self.photo_paths = []
        self._auto_qr_scanned_video_paths: set[str] = set()

        # Lade QR-Check-Status aus Config (Standard: False)
        settings = self.app.config.get_settings()
        qr_check_initial = settings.get("qr_check_enabled", False)
        photo_qr_check_initial = settings.get("photo_qr_check_enabled", False)
        self.qr_check_enabled = tk.BooleanVar(value=qr_check_initial)
        self.photo_qr_check_enabled = tk.BooleanVar(value=photo_qr_check_initial)

        self.watermark_clip_index = None  # NEU: Index des Clips für Wasserzeichen
        self.watermark_photo_indices = []  # NEU: Liste für Foto-Mehrfachauswahl
        self.show_watermark_column = False  # NEU: Steuert Sichtbarkeit der Wasserzeichen-Spalte
        self._wm_auto_select_running = False
        self.is_encoding = False  # NEU: Steuert Sichtbarkeit der Progress-Spalte vs. Datum/Uhrzeit
        # Unix-Zeit der Quelldatei beim Import-Kopieren (Key: normpath der Kopie im temp_dir)
        self._import_source_ts_by_dest: dict[str, float] = {}
        # Fotos: bekannte Quellpfade (Kopie im Arbeitsordner) — verhindert doppelten Import derselben Quelle
        self._photo_source_by_dest: dict[str, str] = {}
        self._active_imported_photo_sources: set[str] = set()
        # Tabellen-Sortierung (Standard: Dateiname aufsteigend)
        self._video_sort_column = "Dateiname"
        self._video_sort_desc = False
        self._photo_sort_column = "Dateiname"
        self._photo_sort_desc = False
        self._video_reorder_drag_item = None
        self._video_reorder_start_index = None
        self._video_reorder_insert_index = None
        self._video_reorder_drag_active = False
        self._video_row_highlight_after_id = None
        self._video_drop_indicator = None
        self.create_widgets()

    def create_widgets(self):
        # Oberer Frame für Label und Checkbox in einer Reihe
        top_frame = tk.Frame(self.frame)
        top_frame.pack(pady=0, fill="x")

        # QR-Optionen (rechts, untereinander)
        qr_options_frame = tk.Frame(top_frame)
        qr_options_frame.pack(side=tk.RIGHT)

        self.qr_check_checkbox = tk.Checkbutton(
            qr_options_frame,
            text="Auf QR-Code in Clips prüfen",
            variable=self.qr_check_enabled,
            command=self._on_qr_checkbox_toggled,
            font=("Arial", 10),
            anchor="w",
        )
        self.qr_check_checkbox.pack(anchor="w")

        self.photo_qr_check_checkbox = tk.Checkbutton(
            qr_options_frame,
            text="Auf QR-Code in Fotos prüfen",
            variable=self.photo_qr_check_enabled,
            command=self._on_photo_qr_checkbox_toggled,
            font=("Arial", 10),
            anchor="w",
        )
        self.photo_qr_check_checkbox.pack(anchor="w")

        # Haupt-Label (links)
        self.drop_label = tk.Label(top_frame,
                                   text=_DROP_ZONE_HELP_TEXT,
                                   font=("Arial", 10))
        self.drop_label.pack(side=tk.LEFT)

        # Notebook (Tabs) erstellen mit größerem Style
        style = ttk.Style()
        style.configure('Large.TNotebook.Tab',
                       font=('Arial', 8, 'bold'),
                       padding=[20, 5])  # [horizontal, vertical] padding

        self.notebook = ttk.Notebook(self.frame, style='Large.TNotebook')
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        # Tab für Videos
        self.video_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.video_tab, text="Videos")

        # Tab für Fotos
        self.photo_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.photo_tab, text="Fotos")

        # Tab-Inhalte erstellen
        self.create_video_tab()
        self.create_photo_tab()

        # Standardmäßig Videos-Tab auswählen
        self.notebook.select(0)

        self.setup_drag_drop()

    def create_video_tab(self):
        """Erstellt den Video-Tab mit Tabelle und Steuerung"""
        # Video-Tabelle
        video_table_frame = tk.Frame(self.video_tab)
        video_table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollbar für Video-Tabelle
        video_scrollbar = ttk.Scrollbar(video_table_frame)
        video_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview für Videos
        self.video_tree = ttk.Treeview(
            video_table_frame,
            columns=("Nr", "Dateiname", "Format", "Dauer", "Größe", "Datum", "Uhrzeit", "Progress", "WM"),
            show="headings",
            height=6,
            yscrollcommand=video_scrollbar.set
        )

        # Spalten konfigurieren für Videos
        self._video_heading_base = {
            "Nr": "#", "Dateiname": "Dateiname", "Format": "Format", "Dauer": "Dauer",
            "Größe": "Größe", "Datum": "Datum", "Uhrzeit": "Uhrzeit", "Progress": "Fortschritt", "WM": "💧",
        }
        for col in ("Nr", "Dateiname", "Format", "Dauer", "Größe", "Datum", "Uhrzeit", "Progress"):
            self.video_tree.heading(
                col,
                text=self._video_heading_base[col],
                command=lambda c=col: self._on_video_heading_click(c),
            )
        self.video_tree.heading("WM", text=self._video_heading_base["WM"])

        self.video_tree.column("Nr", width=10, anchor="center")
        self.video_tree.column("Dateiname", width=180)
        self.video_tree.column("Format", width=70, anchor="center")
        self.video_tree.column("Dauer", width=50, anchor="center")
        self.video_tree.column("Größe", width=70, anchor="center")
        self.video_tree.column("Datum", width=80, anchor="center")
        self.video_tree.column("Uhrzeit", width=70, anchor="center")
        self.video_tree.column("Progress", width=0, minwidth=0, stretch=False, anchor="w")  # Initial versteckt
        self.video_tree.column("WM", width=0, minwidth=0, stretch=False, anchor="center")  # Startet versteckt

        self.video_tree.pack(side=tk.LEFT, fill="both", expand=True)
        video_scrollbar.config(command=self.video_tree.yview)

        # Doppelklick-Event für Videos
        self.video_tree.bind("<Double-1>", self._on_video_double_click)

        # NEU: Event für Checkbox-Klicks in der Wasserzeichen-Spalte (auf Release um Doppelklicks zu vermeiden)
        self.video_tree.bind("<ButtonRelease-1>", self._on_watermark_checkbox_click)

        # Rechtsklick-Event für Kontextmenü
        self.video_tree.bind("<Button-3>", self._show_video_context_menu)
        self.video_tree.bind("<ButtonPress-1>", self._on_video_reorder_press, add="+")
        self.video_tree.bind("<B1-Motion>", self._on_video_reorder_motion, add="+")
        self.video_tree.bind("<ButtonRelease-1>", self._on_video_reorder_release, add="+")

        # Drag & Drop für Video-Tabelle
        self.video_tree.drop_target_register(DND_FILES)
        self.video_tree.dnd_bind('<<Drop>>', self._handle_video_table_drop)
        self.video_tree.tag_configure("recently_moved", background="#dff4df")
        self._video_drop_indicator = tk.Frame(self.video_tree, height=2, bg="#2d89ef")
        self._video_drop_indicator.place_forget()

        # Steuerungs-Buttons für Videos
        video_button_frame = tk.Frame(self.video_tab)
        video_button_frame.pack(pady=5)

        tk.Button(video_button_frame, text="▲ Nach oben", command=self.move_video_up).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="▼ Nach unten", command=self.move_video_down).pack(side=tk.LEFT, padx=2)

        # NEU: Button zum Schneiden
        self.cut_button = tk.Button(video_button_frame, text="✂ Schneiden", command=self.open_cut_dialog)
        self.cut_button.pack(side=tk.LEFT, padx=5)

        self.apply_pending_cuts_button = tk.Button(
            video_button_frame,
            text="Warteschlange",
            command=self.open_apply_pending_cuts_dialog,
            state="normal",
            bg="#d35400",
            fg="white",
            activebackground="#a04000",
            activeforeground="white",
            relief="raised",
            bd=2,
        )
        self._apply_pending_cuts_button_pack = {"side": tk.LEFT, "padx": 5}

        tk.Button(video_button_frame, text="✕ Entfernen", command=self.remove_selected_video).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="🗑 Alle Videos löschen", command=self.clear_videos).pack(side=tk.LEFT, padx=2)

        self._refresh_video_heading_arrows()

    def create_photo_tab(self):
        """Erstellt den Foto-Tab mit Tabelle"""
        # Foto-Tabelle
        photo_table_frame = tk.Frame(self.photo_tab)
        photo_table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollbar für Foto-Tabelle
        photo_scrollbar = ttk.Scrollbar(photo_table_frame)
        photo_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview für Fotos
        self.photo_tree = ttk.Treeview(
            photo_table_frame,
            columns=("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit", "WM"),
            show="headings",
            height=6,
            yscrollcommand=photo_scrollbar.set
        )

        # Spalten konfigurieren für Fotos
        self._photo_heading_base = {
            "Nr": "#", "Dateiname": "Dateiname", "Größe": "Größe", "Datum": "Datum",
            "Uhrzeit": "Uhrzeit", "WM": "💧",
        }
        for col in ("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit"):
            self.photo_tree.heading(
                col,
                text=self._photo_heading_base[col],
                command=lambda c=col: self._on_photo_heading_click(c),
            )
        self.photo_tree.heading("WM", text=self._photo_heading_base["WM"])

        self.photo_tree.column("Nr", width=10, anchor="center")
        self.photo_tree.column("Dateiname", width=250)
        self.photo_tree.column("Größe", width=100, anchor="center")
        self.photo_tree.column("Datum", width=100, anchor="center")
        self.photo_tree.column("Uhrzeit", width=100, anchor="center")
        self.photo_tree.column("WM", width=0, minwidth=0, stretch=False, anchor="center")  # Initial versteckt

        self.photo_tree.pack(side=tk.LEFT, fill="both", expand=True)
        photo_scrollbar.config(command=self.photo_tree.yview)

        # Doppelklick-Event für Fotos
        self.photo_tree.bind("<Double-1>", self._on_photo_double_click)

        # NEU: Event für Checkbox-Klicks in der Foto-Wasserzeichen-Spalte
        self.photo_tree.bind("<ButtonRelease-1>", self._on_photo_watermark_checkbox_click)

        # Rechtsklick-Event für Kontextmenü
        self.photo_tree.bind("<Button-3>", self._show_photo_context_menu)

        # Drag & Drop für Foto-Tabelle
        self.photo_tree.drop_target_register(DND_FILES)
        self.photo_tree.dnd_bind('<<Drop>>', self._handle_photo_table_drop)

        # Steuerungs-Buttons für Fotos
        photo_button_frame = tk.Frame(self.photo_tab)
        photo_button_frame.pack(pady=5)

        tk.Button(photo_button_frame, text="✕ Entfernen", command=self.remove_selected_photo).pack(side=tk.LEFT, padx=2)
        tk.Button(photo_button_frame, text="🗑 Alle Fotos löschen", command=self.clear_photos).pack(side=tk.LEFT, padx=2)

        self._refresh_photo_heading_arrows()

    def setup_drag_drop(self):
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)
        self.frame.drop_target_register(DND_FILES)
        self.frame.dnd_bind('<<Drop>>', self.handle_drop)

    def _should_skip_dji_timelapse_video(self, path: str) -> bool:
        if not self.app or not hasattr(self.app, "config"):
            return False
        settings = self.app.config.get_settings()
        if not settings.get("sd_exclude_timelapse_videos", True):
            return False
        dcim_root = resolve_dcim_root(path)
        if not dcim_root:
            return False
        session_active = dcim_has_timelapse_photo_tree(dcim_root)
        return should_skip_file_for_timelapse_session(
            path,
            dcim_root,
            is_video=True,
            timelapse_session_active=session_active,
        )

    def handle_drop(self, event):
        """Verarbeitet das Ablegen von Dateien (Videos und Fotos)"""
        filepaths = self._parse_dropped_files(event.data)
        valid_videos = []
        valid_photos = []

        for filepath in filepaths:
            if os.path.isfile(filepath):
                kind = _dnd_classify_file(filepath)
                if kind == "video":
                    if self._should_skip_dji_timelapse_video(filepath):
                        print(
                            f"DJI Timelapse-Filter: überspringe "
                            f"{os.path.basename(filepath)}"
                        )
                        continue
                    valid_videos.append(filepath)
                elif kind == "photo":
                    valid_photos.append(filepath)
                else:
                    messagebox.showwarning("Ungültige Datei",
                                           f"'{os.path.basename(filepath)}' ist keine unterstützte Video- oder Foto-Datei")
            elif os.path.isdir(filepath):
                exclude_timelapse = True
                if self.app and hasattr(self.app, "config"):
                    exclude_timelapse = bool(
                        self.app.config.get_settings().get("sd_exclude_timelapse_videos", True)
                    )
                v, p, skipped = _collect_media_from_directory(
                    filepath, exclude_timelapse_videos=exclude_timelapse,
                )
                if skipped:
                    print(
                        f"DJI Timelapse-Filter: {skipped} Video(s) übersprungen "
                        f"(Ordner: {os.path.basename(filepath)})"
                    )
                valid_videos.extend(v)
                valid_photos.extend(p)

        if valid_videos or valid_photos:
            valid_videos = sort_paths_by_basename(valid_videos)
            valid_photos = sort_paths_by_basename(valid_photos)
            # Prüfe Video-Formate wenn mehrere Videos hinzugefügt werden
            needs_reencoding_info = None
            if len(valid_videos) > 0 and len(self.video_paths) + len(valid_videos) > 1:
                needs_reencoding_info = self._check_if_reencoding_needed(valid_videos)

            self.add_files(valid_videos, valid_photos)
            self.drop_label.config(text="Importiere Dateien...", fg="#b8860b")

            # Info: Re-Encoding-Info wird in der Konsole ausgegeben
            if needs_reencoding_info and not needs_reencoding_info["compatible"]:
                print(f"Videos mit unterschiedlichen Formaten erkannt: {needs_reencoding_info['details']}")
                print("Die Vorschau-Erstellung kann länger dauern, da die Videos neu kodiert werden müssen.")
        else:
            self.drop_label.config(text="Keine gültigen Video- oder Foto-Dateien gefunden", fg="red")

    def _check_if_reencoding_needed(self, new_videos):
        """Prüft ob Re-Encoding für die neuen Videos nötig ist"""
        try:
            # Kombiniere vorhandene und neue Videos für die Prüfung
            all_videos = self.video_paths + new_videos

            if len(all_videos) <= 1:
                return {"compatible": True, "details": "Nur ein Video"}

            # Verwende ffprobe um Video-Informationen zu sammeln
            formats = []
            for video_path in all_videos:
                try:
                    result = subprocess.run([
                        'ffprobe', '-v', 'quiet',
                        '-print_format', 'json',
                        '-show_streams',
                        video_path
                    ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                    if result.returncode == 0:
                        import json
                        info = json.loads(result.stdout)

                        # Finde Video-Stream
                        video_stream = None
                        for stream in info.get('streams', []):
                            if stream.get('codec_type') == 'video':
                                video_stream = stream
                                break

                        if video_stream:
                            format_info = {
                                'filename': os.path.basename(video_path),
                                'codec_name': video_stream.get('codec_name', 'unknown'),
                                'width': video_stream.get('width', 0),
                                'height': video_stream.get('height', 0),
                                'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                            }
                            formats.append(format_info)
                        else:
                            formats.append({'filename': os.path.basename(video_path), 'error': 'No video stream'})
                    else:
                        formats.append({'filename': os.path.basename(video_path), 'error': 'FFprobe failed'})

                except Exception as e:
                    formats.append({'filename': os.path.basename(video_path), 'error': str(e)})

            # Vergleiche alle Formate
            first_format = formats[0]
            compatible = True
            differences = []

            for i, fmt in enumerate(formats[1:], 1):
                if 'error' in fmt:
                    compatible = False
                    differences.append(f"{fmt['filename']}: {fmt['error']}")
                    continue

                # Prüfe Codec
                if fmt.get('codec_name') != first_format.get('codec_name'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: Codec {fmt['codec_name']}")

                # Prüfe Auflösung
                if fmt.get('width') != first_format.get('width') or fmt.get('height') != first_format.get('height'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: {fmt['width']}x{fmt['height']}")

                # Prüfe Framerate (vereinfacht)
                if fmt.get('r_frame_rate') != first_format.get('r_frame_rate'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: FPS {fmt['r_frame_rate']}")

            if compatible:
                details = f"Alle {len(all_videos)} Videos kompatibel"
            else:
                # Zeige nur die ersten 3 Unterschiede um die Meldung übersichtlich zu halten
                diff_display = "\n".join(differences[:3])
                if len(differences) > 3:
                    diff_display += f"\n... und {len(differences) - 3} weitere"
                details = f"Format-Unterschiede:\n{diff_display}"

            return {
                "compatible": compatible,
                "details": details,
                "formats": formats
            }

        except Exception as e:
            # Im Fehlerfall gehen wir davon aus dass Re-Encoding nötig ist
            return {
                "compatible": False,
                "details": f"Fehler bei Format-Prüfung: {str(e)}"
            }

    def _parse_dropped_files(self, data_string):
        """Verarbeitet die Zeichenkette eines Drop-Events in eine Liste von Dateipfaden."""
        # Diese Methode ist für den Aufruf durch einen Drag-and-Drop-Handler vorgesehen.
        # Tkinter unter Windows liefert eine Tcl-formatierte Liste, bei der Pfade
        # mit Leerzeichen in {} eingeschlossen sind.
        # Beispiel: '{C:/Benutzer/Test User/vid 1.mp4}' C:/normaler/pfad/vid2.mp4

        # Verwendung von Regex, um entweder in geschweiften Klammern stehende Inhalte oder Zeichenketten ohne Leerzeichen zu finden
        path_candidates = re.findall(r'\{[^{}]*\}|[^ ]+', data_string)

        cleaned_paths = []
        for path in path_candidates:
            # Entfernt die geschweiften Klammern, falls vorhanden
            if path.startswith('{') and path.endswith('}'):
                cleaned_paths.append(path[1:-1])
            else:
                cleaned_paths.append(path)

        return cleaned_paths

    @staticmethod
    def _log_import_message(message: str, exc: Optional[BaseException] = None) -> None:
        """Schreibt Import-Fehler in die App-Logdatei und auf die Konsole."""
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        if exc is not None:
            line += f"\n{traceback.format_exc()}"
        print(line)
        try:
            os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
            with open(LOG_FILE, "a", encoding="utf-8") as log_file:
                log_file.write(line + "\n")
        except OSError:
            pass

    def _ensure_working_temp_dir(self, timeout_sec: float = _TEMP_DIR_WAIT_TIMEOUT_SEC) -> Optional[str]:
        """
        Stellt sicher, dass video_preview.temp_dir existiert (UI-Thread erstellt, Worker wartet).
        """
        if not self.app or not hasattr(self.app, "video_preview"):
            return None
        video_preview = self.app.video_preview
        temp_dir = video_preview.temp_dir
        if temp_dir and os.path.isdir(temp_dir):
            return temp_dir
        self.parent.after(0, video_preview._create_temp_directory)
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            temp_dir = video_preview.temp_dir
            if temp_dir and os.path.isdir(temp_dir):
                return temp_dir
            time.sleep(_TEMP_DIR_POLL_INTERVAL_SEC)
        return video_preview.temp_dir if video_preview.temp_dir and os.path.isdir(video_preview.temp_dir) else None

    def _generate_import_photo_thumbnails(
        self,
        photo_paths: List[str],
        dialog: "ImportProgressDialog",
        pil_photo_cache: dict,
    ) -> None:
        """Erzeugt PIL-Thumbnails für importierte Fotos (parallel oder sequentiell)."""
        settings = self.app.config.get_settings()
        parallel_enabled = bool(settings.get("import_photo_parallel_enabled", True))
        try:
            workers = int(settings.get("qr_video_parallel_workers", 2))
        except (TypeError, ValueError):
            workers = 2
        workers = max(1, min(4, workers))

        n_thumb = len(photo_paths)
        self.parent.after(0, dialog.speed_var.set, "")

        def _update_thumb_ui(completed: int, total: int, basename: str) -> None:
            gp = int((completed / total) * 100) if total else 100

            def ui():
                dialog.status_var.set(f"Importiere Fotos ({completed}/{total}): {basename}")
                dialog.file_progress_var.set(gp)
                dialog.global_progress_var.set(gp)
                dialog.global_status_var.set(f"Gesamtfortschritt: {gp}%")

            self.parent.after(0, ui)

        if parallel_enabled and n_thumb > 1:
            batch = build_pil_thumbnails_parallel(
                photo_paths,
                THUMB_MAX_SIZE,
                workers,
                cancel_check=dialog.cancel_requested.is_set,
                on_progress=_update_thumb_ui,
            )
            pil_photo_cache.update(batch)
            return

        for i_thumb, photo_path in enumerate(photo_paths, start=1):
            if dialog.cancel_requested.is_set():
                break
            fn = os.path.basename(photo_path)
            _update_thumb_ui(i_thumb, n_thumb, fn)
            thumb = build_pil_thumbnail(photo_path, THUMB_MAX_SIZE)
            if thumb is not None:
                pil_photo_cache[photo_path] = thumb

    def _schedule_import_finished(
        self,
        dialog,
        *,
        new_videos_added: bool,
        new_photos_added: bool,
        cancelled: bool,
        pil_photo_cache=None,
        imported_video_paths: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        unreadable_paths: Optional[List[str]] = None,
        videos_imported: int = 0,
        photos_imported: int = 0,
        on_complete=None,
        record_history_after_import: bool = False,
        history_source_paths: Optional[List[str]] = None,
    ) -> None:
        self.parent.after(
            0,
            lambda: self._on_import_finished(
                new_videos_added,
                new_photos_added,
                dialog,
                cancelled,
                pil_photo_cache,
                imported_video_paths=imported_video_paths or [],
                error_message=error_message,
                unreadable_paths=unreadable_paths or [],
                videos_imported=videos_imported,
                photos_imported=photos_imported,
                on_complete=on_complete,
                record_history_after_import=record_history_after_import,
                history_source_paths=history_source_paths or [],
            ),
        )

    def add_files(
        self,
        new_videos,
        new_photos,
        *,
        on_complete=None,
        record_history_after_import: bool = False,
    ):
        """
        Importiert neue Videos und Fotos.

        Args:
            on_complete: Optional callback(success, videos_imported, photos_imported, error, cancelled)
            record_history_after_import: imported_at erst nach erfolgreichem Kopieren setzen
        """
        if not new_videos and not new_photos:
            if on_complete:
                self.parent.after(0, lambda: on_complete(True, 0, 0, None, False))
            return

        dialog = ImportProgressDialog(self.parent)
        history_sources = list(new_videos) + list(new_photos)
        t = threading.Thread(
            target=self._async_add_files,
            args=(new_videos, new_photos, dialog),
            kwargs={
                "on_complete": on_complete,
                "record_history_after_import": record_history_after_import,
                "history_source_paths": history_sources,
            },
        )
        t.daemon = True
        t.start()

    def _async_add_files(
        self,
        new_videos,
        new_photos,
        dialog,
        *,
        on_complete=None,
        record_history_after_import: bool = False,
        history_source_paths=None,
    ):
        new_videos_added = False
        new_photos_added = False
        imported_paths = []
        imported_history_hashes = []
        photo_batch_paths = []
        pil_photo_cache = {}
        unreadable_paths: List[str] = []

        try:
            new_videos = sort_paths_by_basename(list(new_videos)) if new_videos else []
            new_photos = sort_paths_by_basename(list(new_photos)) if new_photos else []

            settings = self.app.config.get_settings()
            skip_processed = settings.get("sd_skip_processed", False)
            skip_processed_manual = settings.get("sd_skip_processed_manual", False)

            total_bytes = 0
            files_to_process = []

            if new_videos or new_photos:
                temp_dir = self._ensure_working_temp_dir()
                if not temp_dir:
                    raise RuntimeError(
                        "Der Arbeitsordner für den Import konnte nicht erstellt werden. "
                        "Bitte Schreibrechte für den Windows-Temp-Ordner prüfen "
                        f"({os.environ.get('TEMP', '%TEMP%')})."
                    )

            # Prepare videos
            if new_videos:
                for path in new_videos:
                    if skip_processed and skip_processed_manual:
                        history_store = MediaHistoryStore.instance()
                        identity = history_store.compute_identity(path)
                        if identity and history_store.was_imported(identity[0]):
                            continue
                    try:
                        total_bytes += os.path.getsize(path)
                        files_to_process.append(('video', path))
                    except OSError as e:
                        unreadable_paths.append(path)
                        self._log_import_message(f"Import: Datei nicht lesbar: {path}", e)

            # Prepare photos
            if new_photos:
                for path in new_photos:
                    if skip_processed and skip_processed_manual:
                        history_store = MediaHistoryStore.instance()
                        identity = history_store.compute_identity(path)
                        if identity and history_store.was_imported(identity[0]):
                            continue
                    try:
                        total_bytes += os.path.getsize(path)
                        files_to_process.append(('photo', path))
                    except OSError as e:
                        unreadable_paths.append(path)
                        self._log_import_message(f"Import: Datei nicht lesbar: {path}", e)

            if not files_to_process and (new_videos or new_photos):
                if unreadable_paths:
                    names = ", ".join(os.path.basename(p) for p in unreadable_paths[:5])
                    extra = f" (+{len(unreadable_paths) - 5} weitere)" if len(unreadable_paths) > 5 else ""
                    raise RuntimeError(
                        f"Keine der Dateien konnte gelesen werden: {names}{extra}"
                    )
                if skip_processed and skip_processed_manual:
                    raise RuntimeError(
                        "Alle ausgewählten Dateien wurden bereits importiert "
                        "(Einstellung „Bereits verarbeitete überspringen“)."
                    )

            copied_bytes = 0

            for ftype, source_path in files_to_process:
                if dialog.cancel_requested.is_set():
                    break

                filename = os.path.basename(source_path)
                self.parent.after(0, dialog.status_var.set, f"Kopiere {filename}...")
                self.parent.after(0, dialog.file_progress_var.set, 0)

                file_size = os.path.getsize(source_path)
                
                if ftype == 'video':
                    temp_dir = self._ensure_working_temp_dir()
                    if not temp_dir:
                        raise RuntimeError(
                            "Arbeitsordner für Video-Import nicht verfügbar. "
                            "Bitte Temp-Ordner und Schreibrechte prüfen."
                        )
                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    dest_path = os.path.join(temp_dir, safe_filename)
                    if os.path.exists(dest_path):
                        base_name, ext = os.path.splitext(safe_filename)
                        counter = 1
                        while os.path.exists(dest_path):
                            dest_path = os.path.join(temp_dir, f"{base_name}_{counter}{ext}")
                            counter += 1
                    
                    # Kopieren in Blöcken
                    chunk_size = 1024 * 1024 * 5 # 5 MB
                    file_copied_bytes = 0
                    start_time = time.time()
                    
                    with open(source_path, 'rb') as src, open(dest_path, 'wb') as dst:
                        while True:
                            if dialog.cancel_requested.is_set():
                                break
                            chunk = src.read(chunk_size)
                            if not chunk:
                                break
                            dst.write(chunk)
                            
                            file_copied_bytes += len(chunk)
                            copied_bytes += len(chunk)
                            
                            elapsed = time.time() - start_time
                            speed = (file_copied_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0
                            
                            file_prog = (file_copied_bytes / file_size) * 100 if file_size > 0 else 100
                            global_prog = (copied_bytes / total_bytes) * 100 if total_bytes > 0 else 100
                            
                            def update_ui(fp=file_prog, gp=global_prog, spd=speed):
                                dialog.file_progress_var.set(fp)
                                dialog.global_progress_var.set(gp)
                                dialog.global_status_var.set(f"Gesamtfortschritt: {int(gp)}%")
                                dialog.speed_var.set(f"{spd:.1f} MB/s")
                                
                            self.parent.after(0, update_ui)

                    if dialog.cancel_requested.is_set():
                        # Rollback current file
                        try:
                            os.remove(dest_path)
                        except:
                            pass
                        break
                    
                    imported_path = dest_path
                    
                    is_duplicate = False
                    for existing_path in self.video_paths + imported_paths:
                        try:
                            if os.path.getsize(existing_path) == file_size and os.path.basename(existing_path) == os.path.basename(imported_path):
                                is_duplicate = True
                                break
                        except:
                            pass
                            
                    if not is_duplicate:
                        imported_paths.append(imported_path)
                        ts_src = get_creation_timestamp(source_path)
                        if ts_src is not None:
                            self._import_source_ts_by_dest[os.path.normpath(imported_path)] = float(ts_src)
                        new_videos_added = True
                        if skip_processed and skip_processed_manual:
                            from datetime import datetime
                            history_store = MediaHistoryStore.instance()
                            identity = history_store.compute_identity(source_path)
                            if identity:
                                identity_hash, size_bytes = identity
                                history_store.upsert(
                                    identity_hash=identity_hash,
                                    filename=filename,
                                    size_bytes=size_bytes,
                                    media_type='video',
                                    imported_at=datetime.now().isoformat()
                                )
                                imported_history_hashes.append(identity_hash)
                    else:
                        try:
                            os.remove(imported_path)
                        except:
                            pass

                elif ftype == 'photo':
                    if not self.app or not hasattr(self.app, 'video_preview'):
                        continue
                    temp_dir = self._ensure_working_temp_dir()
                    if not temp_dir:
                        raise RuntimeError(
                            "Arbeitsordner für Foto-Import nicht verfügbar. "
                            "Bitte Temp-Ordner und Schreibrechte prüfen."
                        )

                    src_key = _norm_import_path(source_path)
                    if src_key in self._active_imported_photo_sources:
                        continue

                    photos_dir = os.path.join(temp_dir, "photos")
                    try:
                        os.makedirs(photos_dir, exist_ok=True)
                    except OSError as e:
                        print(f"  ⚠️ Konnte Foto-Arbeitsordner nicht anlegen: {e}")
                        continue

                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    dest_path = os.path.join(photos_dir, safe_filename)
                    if os.path.exists(dest_path):
                        base_name, ext = os.path.splitext(safe_filename)
                        counter = 1
                        while os.path.exists(dest_path):
                            dest_path = os.path.join(photos_dir, f"{base_name}_{counter}{ext}")
                            counter += 1

                    chunk_size = 1024 * 1024 * 5  # 5 MB — gleiche Logik wie Videos
                    file_copied_bytes = 0
                    start_time = time.time()

                    with open(source_path, 'rb') as src, open(dest_path, 'wb') as dst:
                        while True:
                            if dialog.cancel_requested.is_set():
                                break
                            chunk = src.read(chunk_size)
                            if not chunk:
                                break
                            dst.write(chunk)

                            file_copied_bytes += len(chunk)
                            copied_bytes += len(chunk)

                            elapsed = time.time() - start_time
                            speed = (file_copied_bytes / (1024 * 1024)) / elapsed if elapsed > 0 else 0

                            file_prog = (file_copied_bytes / file_size) * 100 if file_size > 0 else 100
                            global_prog = (copied_bytes / total_bytes) * 100 if total_bytes > 0 else 100

                            def update_ui(fp=file_prog, gp=global_prog, spd=speed):
                                dialog.file_progress_var.set(fp)
                                dialog.global_progress_var.set(gp)
                                dialog.global_status_var.set(f"Gesamtfortschritt: {int(gp)}%")
                                dialog.speed_var.set(f"{spd:.1f} MB/s")

                            self.parent.after(0, update_ui)

                    if dialog.cancel_requested.is_set():
                        try:
                            os.remove(dest_path)
                        except OSError:
                            pass
                        break

                    imported_p = dest_path
                    is_duplicate = False
                    for existing_path in self.photo_paths + photo_batch_paths:
                        try:
                            if (os.path.getsize(existing_path) == file_size
                                    and os.path.basename(existing_path) == os.path.basename(imported_p)):
                                is_duplicate = True
                                break
                        except OSError:
                            pass

                    if not is_duplicate:
                        photo_batch_paths.append(imported_p)
                        self._register_imported_photo(imported_p, source_path)
                        new_photos_added = True
                        ts_src = get_creation_timestamp(source_path)
                        if ts_src is not None:
                            self._import_source_ts_by_dest[os.path.normpath(imported_p)] = float(ts_src)
                        if skip_processed and skip_processed_manual:
                            from datetime import datetime
                            history_store = MediaHistoryStore.instance()
                            identity = history_store.compute_identity(source_path)
                            if identity:
                                identity_hash, size_bytes = identity
                                history_store.upsert(
                                    identity_hash=identity_hash,
                                    filename=filename,
                                    size_bytes=size_bytes,
                                    media_type='photo',
                                    imported_at=datetime.now().isoformat()
                                )
                                imported_history_hashes.append(identity_hash)
                    else:
                        try:
                            os.remove(imported_p)
                        except OSError:
                            pass

            added_photo_paths_this_batch = []
            if dialog.cancel_requested.is_set():
                print("Import abgebrochen, führe Rollback durch...")
                self.parent.after(0, dialog.status_var.set, "Rollback...")
                for p in imported_paths:
                    try:
                        os.remove(p)
                    except OSError:
                        pass
                    self._import_source_ts_by_dest.pop(os.path.normpath(p), None)

                for p in photo_batch_paths:
                    try:
                        if os.path.isfile(p):
                            os.remove(p)
                    except OSError:
                        pass
                    self._unregister_imported_photo(p)
                    self._import_source_ts_by_dest.pop(os.path.normpath(p), None)

                if imported_history_hashes:
                    MediaHistoryStore.instance().delete_by_hashes(imported_history_hashes)
            else:
                imported_paths = sort_paths_by_basename(imported_paths)
                photo_batch_paths = sort_paths_by_basename(photo_batch_paths)
                self.video_paths.extend(imported_paths)
                self.photo_paths.extend(photo_batch_paths)
                added_photo_paths_this_batch = photo_batch_paths

            # Schwere PIL-Arbeit im Worker, damit der Dialog sichtbar bleibt und der Mainthread nicht einfriert
            if not dialog.cancel_requested.is_set() and added_photo_paths_this_batch:
                self._generate_import_photo_thumbnails(
                    added_photo_paths_this_batch,
                    dialog,
                    pil_photo_cache,
                )

            if dialog.cancel_requested.is_set() and added_photo_paths_this_batch:
                self._rollback_imported_photo_batch(added_photo_paths_this_batch)
                added_photo_paths_this_batch = []
                new_photos_added = False

            cancelled = dialog.cancel_requested.is_set()
            cache_snapshot = pil_photo_cache if not cancelled else {}

            self._schedule_import_finished(
                dialog,
                new_videos_added=new_videos_added,
                new_photos_added=new_photos_added,
                cancelled=cancelled,
                pil_photo_cache=cache_snapshot,
                imported_video_paths=imported_paths if not cancelled else [],
                unreadable_paths=unreadable_paths,
                videos_imported=len(imported_paths) if not cancelled else 0,
                photos_imported=len(photo_batch_paths) if not cancelled else 0,
                on_complete=on_complete,
                record_history_after_import=record_history_after_import,
                history_source_paths=history_source_paths,
            )

        except Exception as e:
            self._log_import_message("Error during async import", e)
            self._schedule_import_finished(
                dialog,
                new_videos_added=False,
                new_photos_added=False,
                cancelled=False,
                imported_video_paths=[],
                error_message=str(e),
                unreadable_paths=unreadable_paths,
                on_complete=on_complete,
                record_history_after_import=record_history_after_import,
                history_source_paths=history_source_paths,
            )

    def _update_drop_label_after_import(
        self,
        *,
        new_videos_added: bool,
        new_photos_added: bool,
        cancelled: bool,
        error_message: Optional[str],
        videos_imported: int,
        photos_imported: int,
    ) -> None:
        if error_message:
            self.drop_label.config(text="Import fehlgeschlagen", fg="red")
            return
        if cancelled:
            self.drop_label.config(text=_DROP_ZONE_HELP_TEXT, fg="black")
            return
        if videos_imported or photos_imported:
            parts = []
            if videos_imported:
                parts.append(f"{videos_imported} Video(s)")
            if photos_imported:
                parts.append(f"{photos_imported} Foto(s)")
            self.drop_label.config(text=" und ".join(parts) + " hinzugefügt", fg="green")
            return
        self.drop_label.config(text="Keine Dateien importiert", fg="red")

    def _on_import_finished(
        self,
        new_videos_added,
        new_photos_added,
        dialog,
        cancelled,
        pil_photo_cache=None,
        *,
        imported_video_paths: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        unreadable_paths: Optional[List[str]] = None,
        videos_imported: int = 0,
        photos_imported: int = 0,
        on_complete=None,
        record_history_after_import: bool = False,
        history_source_paths: Optional[List[str]] = None,
    ):
        dialog.destroy()
        unreadable_paths = unreadable_paths or []
        imported_video_paths = imported_video_paths or []
        history_source_paths = history_source_paths or []

        def _invoke_on_complete(success: bool):
            if on_complete:
                try:
                    on_complete(
                        success,
                        videos_imported,
                        photos_imported,
                        error_message,
                        cancelled,
                    )
                except Exception as cb_err:
                    self._log_import_message("Import on_complete callback failed", cb_err)

        self._update_drop_label_after_import(
            new_videos_added=new_videos_added,
            new_photos_added=new_photos_added,
            cancelled=cancelled,
            error_message=error_message,
            videos_imported=videos_imported,
            photos_imported=photos_imported,
        )

        if error_message:
            details = []
            if unreadable_paths:
                details.append("Nicht lesbare Dateien:")
                details.extend(os.path.basename(p) for p in unreadable_paths[:10])
                if len(unreadable_paths) > 10:
                    details.append(f"... und {len(unreadable_paths) - 10} weitere")
            try:
                ErrorDialog(
                    self.parent,
                    "Import fehlgeschlagen",
                    error_message,
                    details=details or None,
                )
            except Exception as dialog_err:
                self._log_import_message("Import-Fehlerdialog konnte nicht geöffnet werden", dialog_err)
                messagebox.showerror("Import fehlgeschlagen", error_message, parent=self.parent)
            _invoke_on_complete(False)
            return

        if cancelled:
            _invoke_on_complete(False)
            return

        if not new_videos_added and not new_photos_added:
            if unreadable_paths:
                names = ", ".join(os.path.basename(p) for p in unreadable_paths[:5])
                messagebox.showwarning(
                    "Import",
                    f"Es konnten keine Dateien importiert werden.\nNicht lesbar: {names}",
                    parent=self.parent,
                )
            _invoke_on_complete(False)
            return

        if record_history_after_import and history_source_paths:
            try:
                MediaHistoryStore.instance().mark_imported_batch(history_source_paths)
            except Exception as hist_err:
                self._log_import_message("Historie nach Import konnte nicht gesetzt werden", hist_err)

        self._update_video_table()
        self._update_photo_table()

        if new_videos_added and self.show_watermark_column and self.watermark_clip_index is None:
            self._auto_select_longest_video()

        if new_videos_added:
            auto_qr_video_paths: List[str] = []
            if self.qr_check_enabled.get():
                for path in imported_video_paths:
                    norm_path = os.path.normpath(path)
                    if norm_path not in self._auto_qr_scanned_video_paths:
                        auto_qr_video_paths.append(path)
                        self._auto_qr_scanned_video_paths.add(norm_path)

            self.parent.after(
                0,
                lambda: self._update_app_preview(qr_video_paths=auto_qr_video_paths),
            )

        if new_photos_added:
            self._update_photo_preview(pil_photo_cache)
            # Foto-QR nur direkt starten, wenn kein Video-QR parallel läuft
            if not (new_videos_added and self.qr_check_enabled.get()):
                self._maybe_run_photo_qr_search()

        if (new_videos_added or new_photos_added) and self.app and hasattr(self.app, 'form_fields'):
            self.app.form_fields.auto_check_products(new_videos_added, new_photos_added)
            if hasattr(self.app, 'update_watermark_column_visibility'):
                self.app.update_watermark_column_visibility()

        # Wenn ausschließlich Fotos hinzugefügt wurden, automatisch
        # auf Foto-Tab (links) und Foto Vorschau (rechts) wechseln.
        if new_photos_added and not new_videos_added:
            try:
                self.notebook.select(self.photo_tab)
            except Exception as e:
                print(f"⚠️ Fehler beim Wechsel auf Foto-Tab: {e}")

            try:
                if self.app and hasattr(self.app, 'preview_notebook') and hasattr(self.app, 'foto_tab'):
                    self.app.preview_notebook.select(self.app.foto_tab)
            except Exception as e:
                print(f"⚠️ Fehler beim Wechsel auf Foto Vorschau-Tab: {e}")

        # Wenn ausschließlich Videos hinzugefügt wurden, automatisch
        # auf Video-Tab (links) und Video Vorschau (rechts) wechseln.
        if new_videos_added and not new_photos_added:
            try:
                self.notebook.select(self.video_tab)
            except Exception as e:
                print(f"⚠️ Fehler beim Wechsel auf Video-Tab: {e}")

            try:
                if self.app and hasattr(self.app, 'preview_notebook') and hasattr(self.app, 'video_tab'):
                    self.app.preview_notebook.select(self.app.video_tab)
            except Exception as e:
                print(f"⚠️ Fehler beim Wechsel auf Video Vorschau-Tab: {e}")

        if on_complete:
            _invoke_on_complete(True)
            return

    def _import_video(self, source_path):
        """
        Importiert ein Video in den Working-Folder mit Original-Dateinamen.
        Bei Namenskollision wird ein Suffix (_1, _2, etc.) hinzugefügt.

        Returns:
            Working-Folder-Pfad oder None bei Fehler
        """
        try:
            import shutil

            temp_dir = self.app.video_preview.temp_dir
            if not temp_dir:
                print(f"  ⚠️ Working-Folder nicht verfügbar")
                return None

            filename = os.path.basename(source_path)
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            dest_path = os.path.join(temp_dir, safe_filename)

            # Bei Namenskollision: Füge Suffix hinzu
            if os.path.exists(dest_path):
                base_name, ext = os.path.splitext(safe_filename)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(temp_dir, f"{base_name}_{counter}{ext}")
                    counter += 1
                print(f"  📋 {filename} → {os.path.basename(dest_path)} (Namenskollision)")
            else:
                print(f"  📋 {filename} → Working-Folder")

            # Kopiere Datei
            shutil.copy2(source_path, dest_path)

            ts_src = get_creation_timestamp(source_path)
            if ts_src is not None:
                self._import_source_ts_by_dest[os.path.normpath(dest_path)] = float(ts_src)

            return dest_path

        except Exception as e:
            print(f"  ❌ Fehler beim Importieren von {os.path.basename(source_path)}: {e}")
            return None

    def _update_app_preview(self, video_paths=None, qr_video_paths=None, run_qr_check=None):
        """
        Fordert eine Aktualisierung der Vorschau über die Hauptanwendung an.
        Auto-QR läuft nur für explizit übergebene Clips (typisch: neu importierte Videos).
        """
        paths = self.video_paths.copy() if video_paths is None else video_paths.copy()
        qr_paths = [] if qr_video_paths is None else qr_video_paths.copy()
        if run_qr_check is None:
            run_qr_check = self.qr_check_enabled.get() and bool(qr_paths)

        if hasattr(self.app, 'update_video_preview'):
            self.app.update_video_preview(
                paths,
                run_qr_check=run_qr_check,
                qr_video_paths=qr_paths,
            )

    def _on_qr_checkbox_toggled(self):
        """
        Wird aufgerufen, wenn die QR-Code-Checkbox angeklickt wird.
        Führt die QR-Prüfung sofort aus, wenn die Checkbox aktiviert wird.
        Speichert den Status in der Config.
        """
        # Speichere den neuen Status in der Config
        qr_check_status = self.qr_check_enabled.get()
        settings = self.app.config.get_settings()
        settings["qr_check_enabled"] = qr_check_status
        self.app.config.save_settings(settings)

        # Nur wenn Checkbox jetzt aktiviert ist UND Videos vorhanden sind
        if qr_check_status and self.video_paths:
            print("QR-Code-Prüfung wurde aktiviert - führe Prüfung durch...")
            self._auto_qr_scanned_video_paths.clear()
            for path in self.video_paths:
                self._auto_qr_scanned_video_paths.add(os.path.normpath(path))
            self._update_app_preview(
                self.video_paths.copy(),
                qr_video_paths=self.video_paths.copy(),
                run_qr_check=True,
            )
        elif not qr_check_status:
            print("QR-Code-Prüfung wurde deaktiviert")

    def _on_photo_qr_checkbox_toggled(self):
        """Speichert Foto-QR-Status und startet Suche bei Aktivierung."""
        photo_qr_status = self.photo_qr_check_enabled.get()
        settings = self.app.config.get_settings()
        settings["photo_qr_check_enabled"] = photo_qr_status
        self.app.config.save_settings(settings)

        if photo_qr_status and self.photo_paths:
            print("Foto-QR-Prüfung wurde aktiviert - führe Suche durch...")
            self._maybe_run_photo_qr_search()
        elif not photo_qr_status:
            print("Foto-QR-Prüfung wurde deaktiviert")

    def _maybe_run_photo_qr_search(self):
        """Startet Batch-QR-Suche in allen geladenen Fotos, wenn Option aktiv ist."""
        if not self.photo_qr_check_enabled.get():
            return
        if not self.photo_paths:
            return
        if self.app and hasattr(self.app, "run_photo_batch_qr_analysis"):
            self.app.run_photo_batch_qr_analysis(self.photo_paths.copy())

    def get_source_import_epoch(self, copy_path: str) -> Optional[float]:
        """Unix-Zeit der Quelldatei beim Kopieren ins Working-Verzeichnis (falls erfasst)."""
        return self._import_source_ts_by_dest.get(os.path.normpath(copy_path))

    def _video_row_sort_epoch(self, copy_path: str) -> float:
        """Gleiche Zeitbasis wie Spalten Datum/Uhrzeit (Cache > Import-Map > ffprobe > Dateisystem)."""
        if self.app and hasattr(self.app, "video_preview"):
            md = self.app.video_preview.get_cached_metadata(copy_path)
            if md:
                ep = md.get("display_timestamp_epoch")
                if ep is not None:
                    return float(ep)
        snap = self.get_source_import_epoch(copy_path)
        return resolve_video_display_epoch(copy_path, snap, None)

    def _update_video_table(self):
        """
        Aktualisiert die Video-Tabelle.
        NEU: Liest Metadaten aus dem Cache von video_preview, wenn dieser aktiv ist.
        """
        for item in self.video_tree.get_children():
            self.video_tree.delete(item)

        for i, original_path in enumerate(self.video_paths, 1):
            filename = os.path.basename(original_path)

            # Standard-Werte
            duration, size, date, timestamp, format_str = "--:--", "-- MB", "--.--.----", "--:--:--", "---"

            if self.app and hasattr(self.app, 'video_preview'):
                # Prüfen, ob die Vorschau-Sitzung (temp_dir) überhaupt schon läuft
                preview_session_active = self.app.video_preview.temp_dir is not None
                # Versuchen, Metadaten aus dem Cache zu holen
                metadata = self.app.video_preview.get_cached_metadata(original_path)

                if metadata:
                    # Fall 1: Wir haben Metadaten im Cache. Benutze sie.
                    duration = metadata.get("duration", "--:--")
                    size = metadata.get("size", "-- MB")
                    date = metadata.get("date", "--.--.----")
                    timestamp = metadata.get("timestamp", "--:--:--")
                    format_str = metadata.get("format", "---")

                elif preview_session_active:
                    # Fall 2: Vorschau ist aktiv, aber *keine* Metadaten für diesen Clip.
                    # Das bedeutet, der Clip wird gerade kopiert/erstellt.
                    filename = f"[LÄDT...] {filename}"

                else:
                    # Fall 3: Vorschau ist NICHT aktiv — Import-Map / ffprobe / Kopie
                    duration = self._get_video_duration_fallback(original_path)
                    size = self._get_file_size_fallback(original_path)
                    te = self._video_row_sort_epoch(original_path)
                    date = format_epoch_date(te)
                    timestamp = format_epoch_time(te)
                    format_str = self._get_video_format_fallback(original_path)

            else:
                # Fallback, falls self.app nicht existiert (sollte nicht passieren)
                duration = self._get_video_duration_fallback(original_path)
                size = self._get_file_size_fallback(original_path)
                te = resolve_video_display_epoch(
                    original_path,
                    self.get_source_import_epoch(original_path),
                    None,
                )
                date = format_epoch_date(te)
                timestamp = format_epoch_time(te)
                format_str = self._get_video_format_fallback(original_path)

            # NEU: Wasserzeichen-Spalte
            watermark_value = "☑" if i - 1 == self.watermark_clip_index else "☐"

            # Einfügen: Nr, Dateiname, Format, Dauer, Größe, Datum, Uhrzeit, Progress, WM
            self.video_tree.insert("", "end", values=(i, filename, format_str, duration, size, date, timestamp, "", watermark_value))

    def _update_photo_table(self):
        """Aktualisiert die Foto-Tabelle"""
        for item in self.photo_tree.get_children():
            self.photo_tree.delete(item)

        for i, photo_path in enumerate(self.photo_paths, 1):
            filename = os.path.basename(photo_path)
            size = self._get_file_size_fallback(photo_path)  # Fotos verwenden immer Fallback
            imp_ep = self.get_source_import_epoch(photo_path)
            date, timestamp = format_photo_table_datetime(photo_path, imp_ep)

            # NEU: Wasserzeichen-Status bestimmen
            watermark_value = "☑" if (i - 1) in self.watermark_photo_indices else "☐"

            self.photo_tree.insert("", "end", values=(i, filename, size, date, timestamp, watermark_value))

    # --- NEU: Fallback-Methoden für Metadaten (sync ffprobe) ---
    # (Dies sind die alten Methoden, umbenannt)

    def _get_video_duration_fallback(self, video_path):
        """Ermittelt die Dauer des Videos (Blockierend)"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode == 0:
                seconds = float(result.stdout.strip())
                minutes = int(seconds // 60)
                secs = int(seconds % 60)
                return f"{minutes}:{secs:02d}"
        except:
            pass
        return "?:??"

    def _get_file_size_fallback(self, file_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(file_path)
            if size_bytes > 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / 1024:.1f} KB"
        except:
            return "Unbekannt"

    def _get_file_date_fallback(self, video_path):
        """Erstellungsdatum (Dateisystem; siehe file_times)."""
        return format_creation_date(video_path)

    def _get_file_time_fallback(self, video_path):
        """Erstellungsuhrzeit (Dateisystem; siehe file_times)."""
        return format_creation_time(video_path)

    def _get_video_format_fallback(self, video_path):
        """Ermittelt das Video-Format (Auflösung und FPS) mit ffprobe"""
        try:
            import json
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', '-select_streams', 'v:0',
                video_path
            ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode == 0:
                data = json.loads(result.stdout)
                if 'streams' in data and len(data['streams']) > 0:
                    stream = data['streams'][0]
                    width = stream.get('width', 0)
                    height = stream.get('height', 0)

                    # FPS berechnen
                    fps_str = stream.get('r_frame_rate', '0/0')
                    try:
                        num, denom = map(int, fps_str.split('/'))
                        fps = round(num / denom) if denom != 0 else 0
                    except:
                        fps = 0

                    # Format-String erstellen (z.B. "1080p@30")
                    if height > 0:
                        format_label = f"{height}p"
                        if fps > 0:
                            format_label += f"@{fps}"
                        return format_label

            return "---"
        except:
            return "---"

    # --- ENDE Fallback-Methoden ---

    # --- Tabellen-Sortierung (Spaltenköpfe) ---
    def _parse_duration_sort_value(self, s):
        if not s or str(s).strip() in ("--:--", "?:??"):
            return float("inf")
        s = str(s).strip()
        if ":" in s:
            parts = s.split(":")
            try:
                if len(parts) == 2:
                    return int(parts[0]) * 60 + int(parts[1])
            except ValueError:
                pass
        return float("inf")

    def _parse_size_sort_value(self, s):
        if not s or str(s).strip() in ("Unbekannt", "--"):
            return float("inf")
        s = str(s).strip().upper().replace(",", ".")
        try:
            if "MB" in s:
                num = float(s.split("MB")[0].strip())
                return num * 1024 * 1024
            if "KB" in s:
                num = float(s.split("KB")[0].strip())
                return num * 1024
        except ValueError:
            pass
        return float("inf")

    def _photo_row_sort_epoch(self, path: str) -> float:
        return get_photo_display_epoch(path, self.get_source_import_epoch(path))

    def _video_sort_key(self, path, col, values):
        bn = os.path.basename(path)
        v = values if values else ()
        if col == "Dateiname":
            return (0, natural_sort_key(bn))
        if col == "Format":
            fmt = v[2] if len(v) > 2 else ""
            return (0, natural_sort_key(str(fmt)))
        if col == "Dauer":
            ds = v[3] if len(v) > 3 else ""
            return (0, self._parse_duration_sort_value(ds))
        if col == "Größe":
            return (0, self._parse_size_sort_value(v[4] if len(v) > 4 else ""))
        if col in ("Datum", "Uhrzeit"):
            return (0, self._video_row_sort_epoch(path))
        if col == "Progress":
            pr = v[7] if len(v) > 7 else ""
            return (0, natural_sort_key(str(pr)))
        return (1, natural_sort_key(bn))

    def _photo_sort_key(self, path, col, values):
        bn = os.path.basename(path)
        v = values if values else ()
        if col == "Dateiname":
            return (0, natural_sort_key(bn))
        if col == "Größe":
            return (0, self._parse_size_sort_value(v[2] if len(v) > 2 else ""))
        if col in ("Datum", "Uhrzeit"):
            return (0, self._photo_row_sort_epoch(path))
        return (1, natural_sort_key(bn))

    def _refresh_video_heading_arrows(self):
        arrow_u = " \u25b2"
        arrow_d = " \u25bc"
        sort_cols = ("Nr", "Dateiname", "Format", "Dauer", "Größe", "Datum", "Uhrzeit", "Progress")
        for col in sort_cols:
            base = self._video_heading_base[col]
            text = base + (arrow_d if self._video_sort_desc else arrow_u) if col == self._video_sort_column else base
            self.video_tree.heading(
                col,
                text=text,
                command=lambda c=col: self._on_video_heading_click(c),
            )
        self.video_tree.heading("WM", text=self._video_heading_base["WM"])

    def _refresh_photo_heading_arrows(self):
        arrow_u = " \u25b2"
        arrow_d = " \u25bc"
        sort_cols = ("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit")
        for col in sort_cols:
            base = self._photo_heading_base[col]
            text = base + (arrow_d if self._photo_sort_desc else arrow_u) if col == self._photo_sort_column else base
            self.photo_tree.heading(
                col,
                text=text,
                command=lambda c=col: self._on_photo_heading_click(c),
            )
        self.photo_tree.heading("WM", text=self._photo_heading_base["WM"])

    def _on_video_heading_click(self, col):
        if col not in ("Nr", "Dateiname", "Format", "Dauer", "Größe", "Datum", "Uhrzeit", "Progress"):
            return
        if self._video_sort_column == col:
            self._video_sort_desc = not self._video_sort_desc
        else:
            self._video_sort_column = col
            self._video_sort_desc = False
        self._apply_video_sort()
        self._refresh_video_heading_arrows()

    def _on_photo_heading_click(self, col):
        if col not in ("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit"):
            return
        if self._photo_sort_column == col:
            self._photo_sort_desc = not self._photo_sort_desc
        else:
            self._photo_sort_column = col
            self._photo_sort_desc = False
        self._apply_photo_sort()
        self._refresh_photo_heading_arrows()

    def _apply_video_sort(self):
        col = self._video_sort_column
        desc = self._video_sort_desc
        if not self.video_paths:
            return
        wm_path = None
        if self.watermark_clip_index is not None and 0 <= self.watermark_clip_index < len(self.video_paths):
            wm_path = self.video_paths[self.watermark_clip_index]

        if col == "Nr":
            if desc:
                self.video_paths.reverse()
        else:
            children = self.video_tree.get_children()
            if len(children) == len(self.video_paths):
                vals_list = [self.video_tree.item(ch, "values") for ch in children]
            else:
                vals_list = [() for _ in self.video_paths]
            rows = list(zip(self.video_paths, vals_list))
            rows.sort(
                key=lambda r: self._video_sort_key(r[0], col, r[1]),
                reverse=desc,
            )
            self.video_paths = [r[0] for r in rows]

        if wm_path is not None:
            try:
                self.watermark_clip_index = self.video_paths.index(wm_path)
            except ValueError:
                self.watermark_clip_index = None

        self._update_video_table()
        self._update_app_preview()

    def _apply_photo_sort(self):
        col = self._photo_sort_column
        desc = self._photo_sort_desc
        if not self.photo_paths:
            return
        marked = {self.photo_paths[i] for i in self.watermark_photo_indices}

        if col == "Nr":
            if desc:
                self.photo_paths.reverse()
        else:
            children = self.photo_tree.get_children()
            if len(children) == len(self.photo_paths):
                vals_list = [self.photo_tree.item(ch, "values") for ch in children]
            else:
                vals_list = [() for _ in self.photo_paths]
            rows = list(zip(self.photo_paths, vals_list))
            rows.sort(
                key=lambda r: self._photo_sort_key(r[0], col, r[1]),
                reverse=desc,
            )
            self.photo_paths = [r[0] for r in rows]

        self.watermark_photo_indices = [
            i for i, p in enumerate(self.photo_paths) if p in marked
        ]

        self._update_photo_table()
        self._update_photo_preview()

    # --- NEUE METHODEN (von app.py aufgerufen) ---
    def refresh_table(self):
        """Erzwingt ein Neuzeichnen der Video-Tabelle mit aktuellen Metadaten."""
        print("DragDrop: Aktualisiere Tabelle nach Schnitt...")
        self._update_video_table()

    def insert_video_path_at_index(self, original_path: str, index: int):
        """Fügt einen neuen (Platzhalter-)Pfad an einem bestimmten Index ein (z.B. nach Split)."""
        if 0 <= index <= len(self.video_paths):
            self.video_paths.insert(index, original_path)
            print(f"DragDrop: Füge geteilten Clip an Index {index} ein.")
        else:
            self.video_paths.append(original_path)
            print(f"DragDrop: Füge geteilten Clip am Ende an (Index {index} ungültig).")

        # Tabelle neu zeichnen (noch ohne Metadaten, die kommen asynchron)
        self._update_video_table()

    # --- ENDE NEUE METHODEN ---

    def move_video_up(self):
        """Bewegt ausgewähltes Video nach oben"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            self._move_video_by_index(index, index - 1, highlight=True)

    def move_video_down(self):
        """Bewegt ausgewähltes Video nach unten"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            self._move_video_by_index(index, index + 1, highlight=True)

    def _move_video_by_index(self, from_index: int, to_index: int, highlight: bool = False) -> bool:
        """Verschiebt ein Video von einem Index zu einem anderen."""
        if from_index == to_index:
            return False
        if not (0 <= from_index < len(self.video_paths)):
            return False
        if not (0 <= to_index < len(self.video_paths)):
            return False

        moved_path = self.video_paths.pop(from_index)
        self.video_paths.insert(to_index, moved_path)

        if self.watermark_clip_index == from_index:
            self.watermark_clip_index = to_index
        elif self.watermark_clip_index is not None:
            if from_index < to_index and from_index < self.watermark_clip_index <= to_index:
                self.watermark_clip_index -= 1
            elif to_index < from_index and to_index <= self.watermark_clip_index < from_index:
                self.watermark_clip_index += 1

        self._update_video_table()
        children = self.video_tree.get_children()
        if 0 <= to_index < len(children):
            moved_item = children[to_index]
            self.video_tree.selection_set(moved_item)
            self.video_tree.focus(moved_item)
            self.video_tree.see(moved_item)
            if highlight:
                self._highlight_video_row_temporarily(moved_item)
        self._update_app_preview()
        return True

    def _hide_video_drop_indicator(self):
        """Blendet die visuelle Einfüge-Linie für Reorder aus."""
        if self._video_drop_indicator is not None:
            self._video_drop_indicator.place_forget()
        self._video_reorder_insert_index = None

    def _show_video_drop_indicator_at(self, y_pos: int, insert_index: int):
        """Zeigt die Einfüge-Linie zwischen Rows an der berechneten Position."""
        if self._video_drop_indicator is None:
            return
        y_pos = max(0, y_pos)
        self._video_drop_indicator.place(x=0, y=max(0, y_pos - 1), relwidth=1.0, height=2)
        self._video_reorder_insert_index = insert_index

    def _highlight_video_row_temporarily(self, item_id: str, duration_ms: int = 350):
        """Zeigt kurzes visuelles Feedback nach erfolgreichem Verschieben."""
        if self._video_row_highlight_after_id is not None:
            try:
                self.parent.after_cancel(self._video_row_highlight_after_id)
            except Exception:
                pass
            self._video_row_highlight_after_id = None

        tags = tuple(self.video_tree.item(item_id, "tags"))
        if "recently_moved" not in tags:
            self.video_tree.item(item_id, tags=tags + ("recently_moved",))

        def _clear():
            if not self.video_tree.winfo_exists():
                return
            current_tags = tuple(t for t in self.video_tree.item(item_id, "tags") if t != "recently_moved")
            self.video_tree.item(item_id, tags=current_tags)
            self._video_row_highlight_after_id = None

        self._video_row_highlight_after_id = self.parent.after(duration_ms, _clear)

    def _reset_video_reorder_drag_state(self):
        """Setzt internen Drag&Drop-Reorder-Zustand zurück."""
        self._video_reorder_drag_item = None
        self._video_reorder_start_index = None
        self._video_reorder_drag_active = False
        self._hide_video_drop_indicator()

    def _on_video_reorder_press(self, event):
        """Erfasst potenziellen Drag-Start für internes Zeilen-Reordering."""
        if not self.video_paths:
            self._reset_video_reorder_drag_state()
            return
        region = self.video_tree.identify_region(event.x, event.y)
        if region != "cell":
            self._reset_video_reorder_drag_state()
            return
        if self.video_tree.identify_column(event.x) == "#9":
            self._reset_video_reorder_drag_state()
            return
        item = self.video_tree.identify_row(event.y)
        if not item:
            self._reset_video_reorder_drag_state()
            return
        self._video_reorder_drag_item = item
        self._video_reorder_start_index = self.video_tree.index(item)
        self._video_reorder_drag_active = False

    def _on_video_reorder_motion(self, event):
        """Aktiviert internes Reorder-Dragging und markiert Zielzeilen."""
        if not self._video_reorder_drag_item:
            return
        children = self.video_tree.get_children()
        if not children:
            self._hide_video_drop_indicator()
            return

        self._video_reorder_drag_active = True
        item = self.video_tree.identify_row(event.y)
        if item:
            row_bbox = self.video_tree.bbox(item)
            if row_bbox:
                _, row_y, _, row_h = row_bbox
                row_mid = row_y + (row_h // 2)
                row_index = self.video_tree.index(item)
                if event.y < row_mid:
                    self._show_video_drop_indicator_at(row_y, row_index)
                else:
                    self._show_video_drop_indicator_at(row_y + row_h, row_index + 1)
                return

        first_bbox = self.video_tree.bbox(children[0])
        if first_bbox and event.y < first_bbox[1]:
            self._show_video_drop_indicator_at(first_bbox[1], 0)
            return

        last_bbox = self.video_tree.bbox(children[-1])
        if last_bbox:
            _, last_y, _, last_h = last_bbox
            self._show_video_drop_indicator_at(last_y + last_h, len(children))
        else:
            self._hide_video_drop_indicator()

    def _on_video_reorder_release(self, event):
        """Verschiebt Video-Zeile auf das markierte Ziel und räumt Feedback auf."""
        if not self._video_reorder_drag_item:
            return
        source_index = self._video_reorder_start_index
        insert_index = self._video_reorder_insert_index
        was_dragging = self._video_reorder_drag_active
        self._hide_video_drop_indicator()
        self._video_reorder_drag_item = None
        self._video_reorder_start_index = None
        self._video_reorder_drag_active = False

        if not was_dragging or source_index is None or insert_index is None:
            return
        adjusted_target = insert_index
        if insert_index > source_index:
            adjusted_target -= 1
        self._move_video_by_index(source_index, adjusted_target, highlight=True)

    def remove_selected_video(self):
        """Entfernt ausgewähltes Video"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])

            # NEU: Entferne auch aus dem Cache
            original_path = self.video_paths.pop(index)
            if self.app and hasattr(self.app, 'video_preview'):
                self.app.video_preview.remove_path_from_cache(original_path)

            if self.app and hasattr(self.app, "discard_pending_cuts_for_path"):
                self.app.discard_pending_cuts_for_path(original_path)

            # NEU: Aktualisiere Wasserzeichen-Index
            if self.watermark_clip_index == index:
                self.watermark_clip_index = None
            elif self.watermark_clip_index is not None and self.watermark_clip_index > index:
                self.watermark_clip_index -= 1

            self._update_video_table()
            # Vorschau aktualisieren
            self._update_app_preview()

    def remove_selected_photo(self):
        """Entfernt ausgewähltes Foto"""
        selection = self.photo_tree.selection()
        if selection:
            index = self.photo_tree.index(selection[0])
            removed = self.photo_paths.pop(index)
            self._delete_photo_working_copy_if_owned(removed)
            self._unregister_imported_photo(removed)
            self._import_source_ts_by_dest.pop(os.path.normpath(removed), None)

            # NEU: Wasserzeichen-Indizes aktualisieren
            # Wenn der gelöschte Index markiert war, entferne ihn
            if index in self.watermark_photo_indices:
                self.watermark_photo_indices.remove(index)

            # Indizes verschieben, die größer als der entfernte Index sind
            updated_indices = []
            for i in self.watermark_photo_indices:
                if i > index:
                    updated_indices.append(i - 1)
                else:
                    updated_indices.append(i)
            self.watermark_photo_indices = updated_indices

            self._update_photo_table()
            self._update_photo_preview()

    def remove_video(self, video_path, update_preview=True):
        """Entfernt ein bestimmtes Video aus der Liste"""
        if video_path in self.video_paths:
            index = self.video_paths.index(video_path)
            self.video_paths.pop(index)
            self._auto_qr_scanned_video_paths.discard(os.path.normpath(video_path))
            self._import_source_ts_by_dest.pop(os.path.normpath(video_path), None)

            # Cache leeren
            if self.app and hasattr(self.app, 'video_preview'):
                self.app.video_preview.remove_path_from_cache(video_path)

            # Wasserzeichen-Index aktualisieren
            if getattr(self, 'watermark_clip_index', None) == index:
                self.watermark_clip_index = None
            elif getattr(self, 'watermark_clip_index', None) is not None and self.watermark_clip_index > index:
                self.watermark_clip_index -= 1

            self._update_video_table()

            if update_preview:
                self._update_app_preview()

    def clear_videos(self):
        """Entfernt alle Videos"""
        self.video_paths.clear()
        self._auto_qr_scanned_video_paths.clear()
        self._import_source_ts_by_dest.clear()

        if self.app and hasattr(self.app, "clear_pending_video_cuts"):
            self.app.clear_pending_video_cuts()

        # NEU: Löschen Sie auch die Wasserzeichen-Auswahl
        self.watermark_clip_index = None

        # NEU: Cache leeren
        if self.app and hasattr(self.app, 'video_preview'):
            self.app.video_preview.clear_metadata_cache()

        self._update_video_table()
        # Vorschau zurücksetzen
        self._update_app_preview([])

    def clear_photos(self):
        """Entfernt alle Fotos"""
        for p in list(self.photo_paths):
            self._delete_photo_working_copy_if_owned(p)
            self._unregister_imported_photo(p)
            self._import_source_ts_by_dest.pop(os.path.normpath(p), None)
        self.photo_paths.clear()
        self.clear_photo_watermark_selection()  # NEU
        self._update_photo_table()
        self._update_photo_preview()

    def remove_photo(self, photo_path, update_preview=True):
        """Entfernt ein bestimmtes Foto aus der Liste"""
        if photo_path in self.photo_paths:
            self.photo_paths.remove(photo_path)
            self._delete_photo_working_copy_if_owned(photo_path)
            self._unregister_imported_photo(photo_path)
            self._import_source_ts_by_dest.pop(os.path.normpath(photo_path), None)
            self._update_photo_table()
            # Nur Preview aktualisieren wenn nicht von Preview selbst aufgerufen
            if update_preview:
                self._update_photo_preview()

    def _update_photo_preview(self, pil_photo_cache=None):
        """Aktualisiert die Foto-Vorschau in der App"""
        if self.app and hasattr(self.app, 'photo_preview'):
            self.app.photo_preview.set_photos(self.photo_paths, pil_photo_cache)

    def clear_all(self):
        """Entfernt alle Videos und Fotos.

        Fotos zuerst, damit beim anschließenden Leeren der Videos das Formular
        (auto_check_products) nicht kurzzeitig noch „Fotos vorhanden“ sieht.
        """
        self.clear_photos()
        self.clear_videos()
        self.drop_label.config(text=_DROP_ZONE_HELP_TEXT, fg="black")

    def get_video_paths(self):
        """Gibt die Liste der Video-Pfade zurück"""
        return self.video_paths.copy()

    def get_photo_paths(self):
        """Gibt die Liste der Foto-Pfade zurück"""
        return self.photo_paths.copy()

    def has_videos(self):
        """Prüft ob Videos vorhanden sind"""
        return len(self.video_paths) > 0

    def has_photos(self):
        """Prüft ob Fotos vorhanden sind"""
        return len(self.photo_paths) > 0

    def _delete_photo_working_copy_if_owned(self, photo_path: str) -> None:
        """Löscht die Foto-Kopie im Arbeitsordner (temp_dir), falls der Pfad dorthin gehört."""
        if not photo_path or not self.app or not hasattr(self.app, "video_preview"):
            return
        td = self.app.video_preview.temp_dir
        if not td:
            return
        try:
            rp = os.path.realpath(photo_path)
            rt = os.path.realpath(td)
            if os.path.commonpath([rp, rt]) != rt:
                return
        except (ValueError, OSError):
            return
        try:
            if os.path.isfile(rp):
                os.remove(rp)
        except OSError as e:
            print(f"⚠️ Konnte Foto-Arbeitskopie nicht löschen ({photo_path}): {e}")

    def _register_imported_photo(self, dest_path: str, source_path: str) -> None:
        """Merkt Quellpfad zur Kopie (Deduplizierung)."""
        dn = os.path.normpath(dest_path)
        sn = _norm_import_path(source_path)
        self._photo_source_by_dest[dn] = sn
        self._active_imported_photo_sources.add(sn)

    def _unregister_imported_photo(self, dest_path: str) -> None:
        """Entfernt Mapping wenn Foto aus der Liste genommen wird."""
        dn = os.path.normpath(dest_path)
        sn = self._photo_source_by_dest.pop(dn, None)
        if sn is not None:
            self._active_imported_photo_sources.discard(sn)

    def _rollback_imported_photo_batch(self, batch_paths: list) -> None:
        """Macht einen Foto-Import-Stapel rückgängig (Abbruch während Thumbnails o. ä.)."""
        if not batch_paths:
            return
        to_remove = {os.path.normpath(p) for p in batch_paths}
        idxs = sorted(
            (i for i, p in enumerate(self.photo_paths) if os.path.normpath(p) in to_remove),
            reverse=True,
        )
        for index in idxs:
            self.photo_paths.pop(index)
            if index in self.watermark_photo_indices:
                self.watermark_photo_indices.remove(index)
            updated_wm = []
            for i in self.watermark_photo_indices:
                if i > index:
                    updated_wm.append(i - 1)
                else:
                    updated_wm.append(i)
            self.watermark_photo_indices = updated_wm

        hs = MediaHistoryStore.instance()
        hashes_to_delete = []
        for p in batch_paths:
            ident = hs.compute_identity(p)
            if ident:
                hashes_to_delete.append(ident[0])
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass
            self._unregister_imported_photo(p)
            self._import_source_ts_by_dest.pop(os.path.normpath(p), None)
        if hashes_to_delete:
            hs.delete_by_hashes(hashes_to_delete)

    def reset(self):
        """Setzt die Komponente zurück"""
        self.clear_all()

    # NEU: Methoden für Video-Encoding-Fortschritt
    def update_video_progress(self, video_identifier, progress_percent, fps=None, eta=None):
        """
        Aktualisiert den Fortschritt für ein bestimmtes Video in der Tabelle.

        Args:
            video_identifier: Dateipfad oder Index des Videos (0-basiert)
            progress_percent: Fortschritt in Prozent (0-100)
            fps: Optional FPS-Wert
            eta: Optional ETA-String (z.B. "1:23")
        """
        # Bestimme den Index basierend auf dem Identifier
        if isinstance(video_identifier, str):
            # Identifier ist ein Dateipfad - finde den Index
            try:
                video_index = self.video_paths.index(video_identifier)
            except ValueError:
                # Pfad nicht in Liste - versuche Basis-Dateinamen zu vergleichen
                basename = os.path.basename(video_identifier)
                video_index = -1
                for i, path in enumerate(self.video_paths):
                    if os.path.basename(path) == basename:
                        video_index = i
                        break
                if video_index == -1:
                    return  # Video nicht gefunden
        else:
            # Identifier ist bereits ein Index
            video_index = video_identifier

        if video_index < 0 or video_index >= len(self.video_paths):
            return

        # Erstelle Text-basierten Fortschrittsbalken
        bar_length = 20
        filled = int((progress_percent / 100) * bar_length)
        bar = "█" * filled + "░" * (bar_length - filled)

        # Baue Fortschritts-Text
        progress_text = f"{bar} {int(progress_percent)}%"

        if fps and fps > 0:
            progress_text += f" {fps:.1f}fps"

        if eta:
            progress_text += f" {eta}"

        # Hole das Item in der Treeview
        items = self.video_tree.get_children()
        if video_index < len(items):
            item = items[video_index]
            # Update nur die Progress-Spalte
            values = list(self.video_tree.item(item)['values'])
            values[7] = progress_text  # Progress ist Spalte 7 (0-basiert)
            self.video_tree.item(item, values=values)

    def clear_video_progress(self, video_identifier):
        """Löscht den Fortschritt für ein bestimmtes Video"""
        # Bestimme den Index basierend auf dem Identifier
        if isinstance(video_identifier, str):
            # Identifier ist ein Dateipfad - finde den Index
            try:
                video_index = self.video_paths.index(video_identifier)
            except ValueError:
                # Pfad nicht in Liste - versuche Basis-Dateinamen zu vergleichen
                basename = os.path.basename(video_identifier)
                video_index = -1
                for i, path in enumerate(self.video_paths):
                    if os.path.basename(path) == basename:
                        video_index = i
                        break
                if video_index == -1:
                    return  # Video nicht gefunden
        else:
            # Identifier ist bereits ein Index
            video_index = video_identifier

        if video_index < 0 or video_index >= len(self.video_paths):
            return

        items = self.video_tree.get_children()
        if video_index < len(items):
            item = items[video_index]
            values = list(self.video_tree.item(item)['values'])
            values[7] = ""  # Leere Progress-Spalte
            self.video_tree.item(item, values=values)

    def set_video_status(self, video_identifier, status_text):
        """
        Setzt einen Status-Text für ein Video (z.B. "Fertig", "Fehler", "Warte...")

        Args:
            video_identifier: Dateipfad oder Index des Videos
            status_text: Status-Text anzuzeigen
        """
        # Bestimme den Index basierend auf dem Identifier
        if isinstance(video_identifier, str):
            # Identifier ist ein Dateipfad - finde den Index
            try:
                video_index = self.video_paths.index(video_identifier)
            except ValueError:
                # Pfad nicht in Liste - versuche Basis-Dateinamen zu vergleichen
                basename = os.path.basename(video_identifier)
                video_index = -1
                for i, path in enumerate(self.video_paths):
                    if os.path.basename(path) == basename:
                        video_index = i
                        break
                if video_index == -1:
                    return  # Video nicht gefunden
        else:
            # Identifier ist bereits ein Index
            video_index = video_identifier

        if video_index < 0 or video_index >= len(self.video_paths):
            return

        items = self.video_tree.get_children()
        if video_index < len(items):
            item = items[video_index]
            values = list(self.video_tree.item(item)['values'])
            values[7] = status_text
            self.video_tree.item(item, values=values)

    def clear_all_video_progress(self):
        """Löscht den Fortschritt für alle Videos"""
        for i in range(len(self.video_paths)):
            self.clear_video_progress(i)

    def show_progress_mode(self):
        """
        Aktiviert Progress-Modus: Zeigt Progress-Spalte, versteckt Datum/Uhrzeit
        """
        if self.is_encoding:
            return  # Bereits im Progress-Modus

        self.is_encoding = True

        # Verstecke Datum und Uhrzeit Spalten
        self.video_tree.column("Datum", width=0, minwidth=0, stretch=False)
        self.video_tree.column("Uhrzeit", width=0, minwidth=0, stretch=False)

        # Zeige Progress-Spalte (breiter, da mehr Platz verfügbar)
        self.video_tree.column("Progress", width=200, minwidth=200, stretch=False)

        self.video_tree.update_idletasks()

    def show_normal_mode(self):
        """
        Aktiviert Normal-Modus: Versteckt Progress-Spalte, zeigt Datum/Uhrzeit
        """
        if not self.is_encoding:
            return  # Bereits im Normal-Modus

        self.is_encoding = False

        # Zeige Datum und Uhrzeit Spalten wieder
        self.video_tree.column("Datum", width=80, minwidth=80, stretch=False)
        self.video_tree.column("Uhrzeit", width=70, minwidth=70, stretch=False)

        # Verstecke Progress-Spalte
        self.video_tree.column("Progress", width=0, minwidth=0, stretch=False)

        # Lösche alle Progress-Inhalte
        self.clear_all_video_progress()

        self.video_tree.update_idletasks()

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def open_cut_dialog(self):
        """Ruft den Schneide-Dialog in der Haupt-App auf."""
        selection = self.video_tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl",
                                   "Bitte wählen Sie zuerst ein Video aus der Tabelle aus, das Sie schneiden möchten.")
            return

        if not self.app or not hasattr(self.app, 'request_cut_dialog'):
            messagebox.showerror("Fehler", "Die Hauptanwendung ist nicht korrekt für das Schneiden konfiguriert.")
            return

        index = self.video_tree.index(selection[0])
        # video_paths enthält nach update_preview Working-Folder-Pfade!
        video_path = self.video_paths[index]

        # Rufe die Methode in app.py auf
        self.app.request_cut_dialog(video_path, index)

    def open_apply_pending_cuts_dialog(self):
        if not self.app or not hasattr(self.app, "request_apply_pending_cuts"):
            messagebox.showerror("Fehler", "Warteschlange ist in dieser Ansicht nicht verfügbar.")
            return
        self.app.request_apply_pending_cuts()

    def set_pending_cuts_count(self, count: int):
        """Zeigt den Warteschlange-Button nur bei ausstehenden Schnitten."""
        if not hasattr(self, "apply_pending_cuts_button"):
            return
        if count > 0:
            if not self.apply_pending_cuts_button.winfo_ismapped():
                self.apply_pending_cuts_button.pack(**self._apply_pending_cuts_button_pack)
            self.apply_pending_cuts_button.config(state="normal", text="Warteschlange")
        else:
            if self.apply_pending_cuts_button.winfo_ismapped():
                self.apply_pending_cuts_button.pack_forget()

    def set_cut_button_enabled(self, enabled: bool):
        """Sperrt/Entsperrt den Schneiden-Button basierend auf Vorschau-Status."""
        if hasattr(self, 'cut_button'):
            self.cut_button.config(state="normal" if enabled else "disabled")
            if enabled:
                self.cut_button.config(text="✂ Schneiden", fg="black")
            else:
                self.cut_button.config(text="✂ Schneiden (Vorschau wird erstellt...)", fg="gray")

    def _on_video_double_click(self, event):
        """Öffnet das ausgewählte Video beim Doppelklick - video_paths enthält Working-Folder-Pfade"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if 0 <= index < len(self.video_paths):
                # video_paths enthält nach dem ersten update_preview Working-Folder-Pfade!
                video_path = self.video_paths[index]
                self._open_file_with_default_app(video_path)

    def _on_photo_double_click(self, event):
        """Öffnet das ausgewählte Foto beim Doppelklick"""
        selection = self.photo_tree.selection()
        if selection:
            index = self.photo_tree.index(selection[0])
            if 0 <= index < len(self.photo_paths):
                photo_path = self.photo_paths[index]
                self._open_file_with_default_app(photo_path)

    def _open_file_with_default_app(self, file_path):
        """Öffnet eine Datei mit der Standard-Anwendung des Systems"""
        try:
            if os.name == 'nt':  # Windows
                os.startfile(file_path)
            elif os.name == 'posix':  # macOS und Linux
                if platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', file_path], check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:  # Linux
                    subprocess.run(['xdg-open', file_path], check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("Fehler", f"Datei konnte nicht geöffnet werden:\n{str(e)}")

    def _show_video_context_menu(self, event):
        """Zeigt Kontextmenü für Video-Zeile bei Rechtsklick"""
        # Identifiziere die angeklickte Zeile
        item = self.video_tree.identify_row(event.y)
        if item:
            # Wähle die Zeile aus
            self.video_tree.selection_set(item)
            index = self.video_tree.index(item)

            if 0 <= index < len(self.video_paths):
                # video_paths enthält nach update_preview Working-Folder-Pfade!
                video_path = self.video_paths[index]

                # Erstelle Kontextmenü
                context_menu = tk.Menu(self.video_tree, tearoff=0)
                context_menu.add_command(label="▶ Öffnen", command=lambda: self._open_file_with_default_app(video_path))
                context_menu.add_command(label="📁 Im Verzeichnis öffnen", command=lambda: self._open_in_directory(video_path))
                context_menu.add_separator()
                context_menu.add_command(label="🔍 Auf QR-Code prüfen", command=lambda: self._check_qr_from_context(index))
                context_menu.add_command(label="✂ Schneiden", command=lambda: self._cut_video_from_context(index))
                context_menu.add_separator()
                context_menu.add_command(label="✕ Löschen", command=lambda: self._delete_video_from_context(index))

                # Zeige Menü an Mausposition
                try:
                    context_menu.tk_popup(event.x_root, event.y_root)
                finally:
                    context_menu.grab_release()

    def _show_photo_context_menu(self, event):
        """Zeigt Kontextmenü für Foto-Zeile bei Rechtsklick"""
        # Identifiziere die angeklickte Zeile
        item = self.photo_tree.identify_row(event.y)
        if item:
            # Wähle die Zeile aus
            self.photo_tree.selection_set(item)
            index = self.photo_tree.index(item)

            if 0 <= index < len(self.photo_paths):
                photo_path = self.photo_paths[index]

                # Erstelle Kontextmenü
                context_menu = tk.Menu(self.photo_tree, tearoff=0)
                context_menu.add_command(label="▶ Öffnen", command=lambda: self._open_file_with_default_app(photo_path))
                context_menu.add_command(label="📁 Im Verzeichnis öffnen", command=lambda: self._open_in_directory(photo_path))
                context_menu.add_separator()
                context_menu.add_command(label="🔍 Auf QR-Code prüfen",
                                         command=lambda: self._scan_photo_qr_code(photo_path))
                context_menu.add_separator()
                context_menu.add_command(label="✕ Löschen", command=lambda: self._delete_photo_from_context(index))

                # Zeige Menü an Mausposition
                try:
                    context_menu.tk_popup(event.x_root, event.y_root)
                finally:
                    context_menu.grab_release()


    def _open_in_directory(self, file_path):
        """Öffnet den Datei-Explorer und markiert die Datei"""
        try:
            if os.name == 'nt':  # Windows
                subprocess.run(['explorer', '/select,', os.path.normpath(file_path)],
                             creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            elif os.name == 'posix':  # macOS und Linux
                directory = os.path.dirname(file_path)
                if platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', '-R', file_path], creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:  # Linux
                    subprocess.run(['xdg-open', directory], creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("Fehler", f"Verzeichnis konnte nicht geöffnet werden:\n{str(e)}")

    def _check_qr_from_context(self, index):
        """Führt QR-Code-Prüfung für spezifisches Video aus - video_paths enthält Working-Folder-Pfade"""
        if 0 <= index < len(self.video_paths):
            # video_paths enthält nach update_preview Working-Folder-Pfade!
            video_path = self.video_paths[index]

            if self.app:
                # Führe QR-Analyse aus
                self.app.run_qr_analysis([video_path])

    def _cut_video_from_context(self, index):
        """Öffnet Schnitt-Dialog für spezifisches Video"""
        if 0 <= index < len(self.video_paths):
            # Wähle das Video in der Tabelle aus
            items = self.video_tree.get_children()
            if index < len(items):
                self.video_tree.selection_set(items[index])
            # Öffne Schnitt-Dialog
            self.open_cut_dialog()

    def _delete_video_from_context(self, index):
        """Löscht Video aus Kontextmenü"""
        if 0 <= index < len(self.video_paths):
            # Wähle das Video in der Tabelle aus
            items = self.video_tree.get_children()
            if index < len(items):
                self.video_tree.selection_set(items[index])
            # Rufe normale Lösch-Funktion auf
            self.remove_selected_video()

    def _delete_photo_from_context(self, index):
        """Löscht Foto aus Kontextmenü"""
        if 0 <= index < len(self.photo_paths):
            # Wähle das Foto in der Tabelle aus
            items = self.photo_tree.get_children()
            if index < len(items):
                self.photo_tree.selection_set(items[index])
            # Rufe normale Lösch-Funktion auf
            self.remove_selected_photo()

    def _scan_photo_qr_code(self, photo_path):
        """Scannt ein Foto nach QR-Code und füllt das Formular"""
        # Nutze die App-Methode mit Loading Window und Thread
        if self.app and hasattr(self.app, 'run_photo_qr_analysis'):
            self.app.run_photo_qr_analysis(photo_path)
        else:
            from tkinter import messagebox
            messagebox.showerror("Fehler", "QR-Code-Scanner nicht verfügbar")

    def _handle_video_table_drop(self, event):
        """Verarbeitet das Ablegen von Dateien in die Video-Tabelle"""
        self.handle_drop(event)
        # Wechsle zum Video-Tab nach dem Drop
        self.notebook.select(0)

    def _handle_photo_table_drop(self, event):
        """Verarbeitet das Ablegen von Dateien in die Foto-Tabelle"""
        self.handle_drop(event)
        # Wechsle zum Foto-Tab nach dem Drop
        self.notebook.select(1)

    # NEU: Methoden für Wasserzeichen-Spalte
    def set_watermark_column_visible(self, visible: bool):
        """Zeigt oder verbirgt die Wasserzeichen-Spalte"""
        was_visible = self.show_watermark_column
        self.show_watermark_column = visible

        # Keine Arbeit, wenn Sichtbarkeit unverändert ist.
        if was_visible == visible:
            return

        if visible:
            self.video_tree.column("WM", width=20, minwidth=30, stretch=False)

            # NEU: Automatisch längstes Video auswählen, wenn Spalte neu sichtbar wird
            # und noch kein Video markiert ist
            if not was_visible and self.watermark_clip_index is None and self.video_paths:
                self._auto_select_longest_video_async()
        else:
            self.video_tree.column("WM", width=0, minwidth=0, stretch=False)

        # Aktualisiere die Tabelle, um die Änderungen sofort zu reflektieren
        self.video_tree.update_idletasks()

    def _auto_select_longest_video_async(self):
        """Startet die Auswahl des längsten Videos asynchron, um UI-Ruckler zu vermeiden."""
        if self._wm_auto_select_running:
            return
        self._wm_auto_select_running = True

        worker = threading.Thread(target=self._auto_select_longest_video, daemon=True)
        worker.start()

    def _auto_select_longest_video(self):
        """
        Wählt automatisch das längste Video als Wasserzeichen aus.
        Wird aufgerufen, wenn die Wasserzeichen-Spalte sichtbar wird.
        """
        try:
            if not self.video_paths:
                return

            longest_index = None
            longest_duration = 0.0

            for i, video_path in enumerate(self.video_paths):
                # Versuche Dauer aus Metadaten-Cache zu holen
                duration_seconds = 0.0

                if self.app and hasattr(self.app, 'video_preview'):
                    metadata = self.app.video_preview.get_cached_metadata(video_path)
                    if metadata:
                        duration_str = metadata.get("duration", "0:00")
                        # Konvertiere "MM:SS" zu Sekunden
                        try:
                            parts = duration_str.split(':')
                            if len(parts) == 2:
                                duration_seconds = int(parts[0]) * 60 + int(parts[1])
                        except:
                            pass

                # Fallback: ffprobe verwenden
                if duration_seconds == 0.0:
                    try:
                        result = subprocess.run([
                            'ffprobe', '-v', 'error', '-show_entries',
                            'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                            video_path
                        ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                        if result.returncode == 0:
                            duration_seconds = float(result.stdout.strip())
                    except:
                        pass

                # Vergleiche mit bisherigem Maximum
                if duration_seconds > longest_duration:
                    longest_duration = duration_seconds
                    longest_index = i

            # Wähle das längste Video aus
            if longest_index is not None:
                def apply_selection():
                    self.watermark_clip_index = longest_index
                    print(f"✅ Automatisch längstes Video als Wasserzeichen ausgewählt: Index {longest_index}, Dauer {longest_duration:.1f}s")
                    self._update_video_table()

                    # Synchronisiere mit video_preview
                    if self.app and hasattr(self.app, 'video_preview'):
                        self.app.video_preview.update_wm_button_state()

                self.frame.after(0, apply_selection)
        finally:
            self._wm_auto_select_running = False

    def get_watermark_clip_index(self):
        """Gibt den Index des für Wasserzeichen ausgewählten Clips zurück (oder None)"""
        return self.watermark_clip_index

    def set_watermark_clip_index(self, index):
        """Setzt den Index des für Wasserzeichen ausgewählten Clips"""
        self.watermark_clip_index = index
        self._update_video_table()

    def clear_watermark_selection(self):
        """Löscht die Wasserzeichen-Auswahl"""
        self.watermark_clip_index = None
        self._update_video_table()

    # NEU: Methoden für Foto-Wasserzeichen
    def set_photo_watermark_column_visible(self, visible: bool):
        """Zeigt oder verbirgt die Wasserzeichen-Spalte für Fotos"""
        if visible:
            self.photo_tree.column("WM", width=20, minwidth=30, stretch=False)
        else:
            self.photo_tree.column("WM", width=0, minwidth=0, stretch=False)
        self.photo_tree.update_idletasks()

    def get_watermark_photo_indices(self):
        """Gibt die Liste der für Wasserzeichen ausgewählten Foto-Indizes zurück"""
        return self.watermark_photo_indices

    def clear_photo_watermark_selection(self):
        """Löscht die Foto-Wasserzeichen-Auswahl"""
        self.watermark_photo_indices = []
        self._update_photo_table()

    # --- NEUE ÖFFENTLICHE METHODEN FÜR WASSERZEICHEN-STEUERUNG ---

    def toggle_video_watermark_at_index(self, index):
        """
        Schaltet die Wasserzeichen-Markierung für einen bestimmten Video-Index um.
        Wird von app.py aufgerufen.
        """
        if self.watermark_clip_index == index:
            # Bereits ausgewählt -> abwählen
            self.watermark_clip_index = None
        else:
            # Anderes oder keins ausgewählt -> dieses auswählen
            self.watermark_clip_index = index

        self._update_video_table()

        # NEU: Synchronisiere mit video_preview
        if self.app and hasattr(self.app, 'video_preview'):
            self.app.video_preview.update_wm_button_state()

    def is_video_watermarked(self, index):
        """Prüft, ob ein bestimmter Video-Index als Wasserzeichen markiert ist."""
        return self.watermark_clip_index == index

    def toggle_photo_watermark_at_index(self, index):
        """
        Schaltet die Wasserzeichen-Markierung für einen bestimmten Foto-Index um.
        Wird von app.py aufgerufen.
        """
        if index in self.watermark_photo_indices:
            # Bereits in der Liste -> entfernen
            self.watermark_photo_indices.remove(index)
        else:
            # Nicht in der Liste -> hinzufügen
            self.watermark_photo_indices.append(index)

        self._update_photo_table()

        # NEU: Synchronisiere mit photo_preview
        if self.app and hasattr(self.app, 'photo_preview'):
            self.app.photo_preview.update_wm_button_state()

    def set_photo_watermark_for_indices(self, indices, marked: bool):
        """
        Setzt die Wasserzeichen-Markierung für mehrere Foto-Indizes auf einen
        einheitlichen Zielzustand.
        """
        if not indices:
            return

        valid_indices = sorted({
            int(i) for i in indices
            if isinstance(i, int) and 0 <= i < len(self.photo_paths)
        })
        if not valid_indices:
            return

        current_marked = set(self.watermark_photo_indices)
        if marked:
            current_marked.update(valid_indices)
        else:
            current_marked.difference_update(valid_indices)

        self.watermark_photo_indices = sorted(current_marked)
        self._update_photo_table()

        # Synchronisiere den Button-Status in der Foto-Vorschau.
        if self.app and hasattr(self.app, 'photo_preview'):
            self.app.photo_preview.update_wm_button_state()

    def is_photo_watermarked(self, index):
        """Prüft, ob ein bestimmter Foto-Index als Wasserzeichen markiert ist."""
        return index in self.watermark_photo_indices

    def _on_photo_watermark_checkbox_click(self, event):
        """Verarbeitet Klicks auf die Foto-Wasserzeichen-Spalte (Mehrfachauswahl)"""
        # Prüfen, ob Spalte überhaupt sichtbar ist
        if self.photo_tree.column("WM", "width") == 0:
            return

        region = self.photo_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        column = self.photo_tree.identify_column(event.x)
        # Spalten: #0 (tree), #1 (Nr), #2 (Datei), #3 (Größe), #4 (Datum), #5 (Uhrzeit), #6 (WM)
        if column != "#6":
            return

        item = self.photo_tree.identify_row(event.y)
        if not item:
            return

        index = self.photo_tree.index(item)

        # Multi-Auswahl-Logik (Toggle):
        if index in self.watermark_photo_indices:
            self.watermark_photo_indices.remove(index)
        else:
            self.watermark_photo_indices.append(index)

        self._update_photo_table()

        # NEU: Synchronisiere mit photo_preview
        if self.app and hasattr(self.app, 'photo_preview'):
            self.app.photo_preview.update_wm_button_state()

        # Verhindere, dass die Reihe ausgewählt wird (optional, aber gut für Checkbox-Feeling)
        self.photo_tree.selection_remove(self.photo_tree.selection())

    def _on_watermark_checkbox_click(self, event):
        """Verarbeitet Klicks auf die Wasserzeichen-Spalte"""
        if self._video_reorder_drag_active:
            return
        if not self.show_watermark_column or not self.video_paths:
            return

        # Finde die angeklickte Spalte
        region = self.video_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        column = self.video_tree.identify_column(event.x)
        # Spalte 9 ist die Wasserzeichen-Spalte (0-indiziert: 8, aber +1 für tree_id)
        # Spalten: tree_id (#0), Nr, Dateiname, Format, Dauer, Größe, Datum, Uhrzeit, Progress, WM
        # Index:    0           1    2          3       4      5      6      7        8         9

        if column != "#9":
            return

        # Finde die Reihe
        item = self.video_tree.identify_row(event.y)
        if not item:
            return

        index = self.video_tree.index(item)

        # Toggle: Wenn bereits ausgewählt, deselektiere; sonst selektiere diese Reihe
        if self.watermark_clip_index == index:
            self.watermark_clip_index = None
        else:
            self.watermark_clip_index = index

        self._update_video_table()

        # NEU: Synchronisiere mit video_preview
        if self.app and hasattr(self.app, 'video_preview'):
            self.app.video_preview.update_wm_button_state()

        # Verhindere, dass die Reihe ausgewählt wird
        self.video_tree.selection_remove(self.video_tree.selection())
