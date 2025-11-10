import tkinter as tk
from tkinter import messagebox
import os
import tempfile
import subprocess
import threading
import json
import re
import sys
import shutil
import time
import multiprocessing
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageTk
from .progress_indicator import ProgressHandler
from .circular_spinner import CircularSpinner
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.hardware_acceleration import HardwareAccelerationDetector
from src.video.parallel_processor import ParallelVideoProcessor
from typing import List, Dict, Callable  # NEU


class VideoPreview:
    def __init__(self, parent, app_instance=None):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent)
        self.combined_video_path = None
        self.encoding_progress_callback = None  # NEU: Callback für Live-Encoding-Fortschritt

        # Hardware-Beschleunigung initialisieren
        self.hw_detector = HardwareAccelerationDetector()
        self.parallel_processor = None  # Wird in _init_hardware_acceleration gesetzt
        self._init_hardware_acceleration()
        self.progress_handler = None
        self.last_video_paths = None  # Speichert die *originalen* Pfade für "Erneut versuchen"

        # --- State and Threading Control Attributes ---
        self.processing_thread = None
        self.ffmpeg_process = None
        self.cancellation_event = threading.Event()
        self.pending_restart_callback = None

        # --- NEU: Verwaltung der temporären Kopien UND Metadaten-Cache ---
        self.temp_dir = None
        # WICHTIG: Cache verwendet (filename, size) als Key, NICHT den Pfad!
        # Die gleiche Datei in verschiedenen Ordnern wird als identisch erkannt.
        self.video_copies_map: Dict[tuple, str] = {}  # Map: (filename, size) -> copy_path
        self.metadata_cache: Dict[tuple, Dict] = {}  # Map: (filename, size) -> {duration, ...}
        self.videos_were_reencoded = False  # Flag: Wurden Videos bereits auf Default-Format (1080p@30) kodiert?
        # ---

        # --- NEU: Thumbnail-Scrollleiste ---
        self.thumbnail_canvas = None
        self.thumbnail_scrollbar = None
        self.thumbnail_inner_frame = None
        self.thumbnail_canvas_window = None
        self.thumbnail_images = {}  # Cache: {(clip_index, is_active): ImageTk.PhotoImage}
        self.current_active_clip = 0  # Aktuell aktiver Clip während Playback
        self.video_paths = []  # Liste der Video-Pfade für Thumbnails
        self.clip_durations = []  # Liste der Clip-Dauern in Sekunden

        # Drag-Scrolling
        self.drag_start_x = 0
        self.drag_start_scroll = 0
        self.is_dragging = False

        # Größen
        self.thumbnail_size = 60  # px

        # Info-Labels (werden in create_widgets erstellt)
        self.info_labels = {}
        # ---

        self.create_widgets()

    def _init_hardware_acceleration(self):
        """Initialisiert Hardware-Beschleunigung basierend auf Einstellungen (asynchron)"""
        # Sofortiger Software-Fallback - Hardware wird asynchron nachgeladen
        self.hw_accel_enabled = False
        self.parallel_processing_enabled = True
        self.hw_detector = HardwareAccelerationDetector()
        self.parallel_processor = None

        if self.app and hasattr(self.app, 'config'):
            settings = self.app.config.get_settings()
            hw_accel_setting = settings.get("hardware_acceleration_enabled", True)
            self.parallel_processing_enabled = settings.get("parallel_processing_enabled", True)

            if hw_accel_setting:
                # Starte Hardware-Erkennung asynchron
                print("🔄 Starte Hardware-Erkennung asynchron...")
                self.hw_detector.detect_async(self._on_hardware_detected)
            else:
                print("ℹ VideoPreview: Hardware-Beschleunigung deaktiviert (Software-Encoding)")

            # Initialisiere ParallelProcessor mit Software-Encoding
            if self.parallel_processing_enabled:
                cpu_count = multiprocessing.cpu_count()
                workers = max(1, cpu_count // 2)
                print(f"🚀 VideoPreview: Paralleles Processing aktiviert: {workers} Worker (Software-Modus)")
                self.parallel_processor = ParallelVideoProcessor(hw_accel_enabled=False)
            else:
                print("ℹ VideoPreview: Paralleles Processing deaktiviert")
        else:
            print("ℹ VideoPreview: Keine Config verfügbar, verwende Software-Encoding")

    def _on_hardware_detected(self, hw_info):
        """
        Callback wenn Hardware-Erkennung abgeschlossen ist.
        Wird asynchron aus Hardware-Thread aufgerufen.
        """
        if hw_info.get('available'):
            self.hw_accel_enabled = True
            print(f"✓ VideoPreview: Hardware-Beschleunigung aktiviert: {self.hw_detector.get_hardware_info_string()}")

            # Update ParallelProcessor mit Hardware-Beschleunigung
            if self.parallel_processing_enabled and self.parallel_processor:
                cpu_count = multiprocessing.cpu_count()
                workers = min(cpu_count, 4)
                print(f"🔄 Update: Paralleles Processing mit Hardware: {workers} Worker")
                self.parallel_processor = ParallelVideoProcessor(hw_accel_enabled=True)
        else:
            print("ℹ VideoPreview: Keine Hardware-Beschleunigung verfügbar, bleibe bei Software-Encoding")

    def reload_hardware_acceleration_settings(self):
        """
        Lädt die Hardware-Beschleunigungseinstellungen neu.
        Wird aufgerufen wenn die Einstellungen geändert wurden.
        """
        print("🔄 VideoPreview: Lade Hardware-Beschleunigungseinstellungen neu...")
        self._init_hardware_acceleration()

    def _get_encoding_params(self, codec='h264'):
        """
        Gibt Encoding-Parameter basierend auf Hardware-Beschleunigung zurück.

        Args:
            codec: 'h264' oder 'hevc'

        Returns:
            Dict mit input_params, output_params und encoder
        """
        return self.hw_detector.get_encoding_params(codec, self.hw_accel_enabled)

    def _get_current_encoder_name(self):
        """
        Gibt einen lesbaren Namen des aktuell verwendeten Encoders zurück.

        Returns:
            String wie "Intel Quick Sync (h264_qsv)" oder "Software (libx264)"
        """
        if not self.hw_accel_enabled:
            return "Software (libx264)"

        hw_info = self.hw_detector.detect_hardware()
        if hw_info['available']:
            type_names = {
                'nvidia': 'NVIDIA NVENC',
                'amd': 'AMD AMF',
                'intel': 'Intel Quick Sync',
                'videotoolbox': 'Apple VideoToolbox',
                'vaapi': 'VAAPI'
            }
            hw_name = type_names.get(hw_info['type'], hw_info['type'])
            encoder = hw_info.get('encoder', 'unknown')
            return f"{hw_name} ({encoder})"
        else:
            return "Software (libx264)"

    def _get_video_codec(self, video_path):
        """
        Extrahiert den Video-Codec aus einer Videodatei.

        Args:
            video_path: Pfad zur Videodatei

        Returns:
            String mit Codec-Namen (z.B. "h264", "hevc") oder "unknown"
        """
        try:
            result = subprocess.run(
                ['ffprobe', '-v', 'quiet', '-print_format', 'json',
                 '-show_streams', '-select_streams', 'v:0', video_path],
                capture_output=True, text=True, timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                streams = info.get('streams', [])
                if streams:
                    codec_name = streams[0].get('codec_name', 'unknown')
                    return codec_name
        except Exception as e:
            print(f"Fehler beim Extrahieren des Codecs von {video_path}: {e}")
        return "unknown"

    def _check_for_cancellation(self):
        """Prüft, ob ein Abbruch angefordert wurde und wirft ggf. eine Exception."""
        if self.cancellation_event.is_set():
            raise Exception("Vorschau-Erstellung vom Benutzer abgebrochen.")

    def _get_file_identity(self, file_path):
        """
        Erstellt eine eindeutige Identität für eine Datei basierend auf Name und Größe.
        Das ist pfad-unabhängig - die gleiche Datei in verschiedenen Ordnern
        hat die gleiche Identität.

        WICHTIG: Der Original-Pfad ist irrelevant! Nur Dateiname + Größe zählen.

        Returns:
            Tuple (filename, size) oder None bei Fehler
        """
        try:
            filename = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            return (filename, file_size)
        except Exception as e:
            print(f"  ⚠️ Fehler beim Erstellen der File-Identity für {file_path}: {e}")
            return None

    def _find_cached_copy(self, original_path):
        """
        Sucht eine existierende Cache-Kopie für die gegebene Datei.

        WICHTIG: Verwendet Datei-Identität (Name + Größe), NICHT den Pfad!
        Die gleiche Datei in verschiedenen Backup-Ordnern wird als identisch erkannt.

        Returns:
            copy_path wenn gefunden, sonst None
        """
        file_identity = self._get_file_identity(original_path)
        if not file_identity:
            return None

        copy_path = self.video_copies_map.get(file_identity)

        # Prüfe ob Kopie noch existiert
        if copy_path and os.path.exists(copy_path):
            return copy_path
        elif copy_path:
            # Kopie existiert nicht mehr - entferne aus Cache
            print(f"  🗑️ Entferne ungültige Cache-Kopie: {os.path.basename(copy_path)}")
            del self.video_copies_map[file_identity]
            if file_identity in self.metadata_cache:
                del self.metadata_cache[file_identity]

        return None

    def _get_clip_durations_seconds(self, video_paths):
        """Ermittelt die Dauer jedes einzelnen Clips in Sekunden (aus dem Cache, wenn möglich)."""
        durations = []
        for video_path in video_paths:  # HINWEIS: video_paths ist hier eine Liste von KOPIEN
            try:
                # Suche die file-identity aus der Kopie (umgekehrter Lookup im Cache)
                file_identity = next((key for key, value in self.video_copies_map.items() if value == video_path), None)

                if file_identity and file_identity in self.metadata_cache:
                    duration_str = self.metadata_cache[file_identity].get("duration_sec_str", "0.0")
                    durations.append(float(duration_str))
                else:
                    # Fallback: ffprobe direkt auf die Kopie anwenden
                    duration_str = self._get_single_video_duration_str(video_path)
                    durations.append(float(duration_str))
            except Exception:
                durations.append(0.0)
        return durations

    def create_widgets(self):

        # --- NEU: Thumbnail-Galerie ---
        thumbnail_frame = tk.Frame(self.frame)
        thumbnail_frame.pack(fill="x", pady=(0, 5))

        # Scrollbarer Canvas
        self.thumbnail_canvas = tk.Canvas(
            thumbnail_frame,
            height=self.thumbnail_size,
            bg="#f0f0f0",
            highlightthickness=0
        )
        self.thumbnail_canvas.pack(fill="x", expand=True)

        # Horizontale Scrollbar
        self.thumbnail_scrollbar = tk.Scrollbar(
            thumbnail_frame,
            orient="horizontal",
            command=self.thumbnail_canvas.xview
        )
        self.thumbnail_scrollbar.pack(fill="x", pady=(0, 0))
        self.thumbnail_canvas.configure(xscrollcommand=self.thumbnail_scrollbar.set)

        # Inner Frame für Thumbnails
        self.thumbnail_inner_frame = tk.Frame(self.thumbnail_canvas, bg="#f0f0f0")
        self.thumbnail_canvas_window = self.thumbnail_canvas.create_window(
            (0, 0), window=self.thumbnail_inner_frame, anchor="nw"
        )

        # Event-Bindings
        self.thumbnail_canvas.bind("<ButtonPress-1>", self._on_thumbnail_drag_start)
        self.thumbnail_canvas.bind("<B1-Motion>", self._on_thumbnail_drag_motion)
        self.thumbnail_canvas.bind("<ButtonRelease-1>", self._on_thumbnail_drag_end)
        self.thumbnail_canvas.bind("<MouseWheel>", self._on_thumbnail_mousewheel)

        # --- NEU: Clip-Informationen ---
        info_detail_frame = tk.Frame(self.frame, relief="groove", borderwidth=1, padx=5, pady=5)
        info_detail_frame.pack(fill="x", pady=(0, 10))

        # Zwei Spalten - linke Spalte fest 35%
        left_info_frame = tk.Frame(info_detail_frame)
        left_info_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right_info_frame = tk.Frame(info_detail_frame)
        right_info_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # WICHTIG: Linke Spalte 35%, Rechte Spalte 65%
        info_detail_frame.grid_columnconfigure(0, weight=35, minsize=150)
        info_detail_frame.grid_columnconfigure(1, weight=65)

        # === LINKE SPALTE: Aktueller Clip ===
        single_info_title = tk.Label(left_info_frame, text="Aktueller Clip:", font=("Arial", 9, "bold"))
        single_info_title.grid(row=0, column=0, columnspan=2, sticky="w")

        info_fields = [
            ("Dateiname:", "filename"),
            ("Auflösung:", "resolution"),
            ("Dauer:", "duration"),
            ("Größe:", "size")
        ]

        self.info_labels = {}
        self.filename_tooltip = None  # Für Tooltip-Verwaltung

        for idx, (label_text, key) in enumerate(info_fields, start=1):
            label = tk.Label(left_info_frame, text=label_text, font=("Arial", 8), anchor="w")
            label.grid(row=idx, column=0, sticky="w", padx=(0, 5))

            if key == "filename":
                # Dateiname mit Textkürzung und Tooltip
                value_label = tk.Label(left_info_frame, text="-", font=("Arial", 8), anchor="w")
                value_label.grid(row=idx, column=1, sticky="ew")

                # Binde Tooltip-Events
                value_label.bind("<Enter>", self._on_filename_hover_enter)
                value_label.bind("<Leave>", self._on_filename_hover_leave)
            else:
                value_label = tk.Label(left_info_frame, text="-", font=("Arial", 8), anchor="w")
                value_label.grid(row=idx, column=1, sticky="w")

            self.info_labels[key] = value_label

        # Spalte 1 soll sich ausdehnen für Textkürzung
        left_info_frame.grid_columnconfigure(1, weight=1)

        # === RECHTE SPALTE: Gesamt-Statistik ===
        stats_title = tk.Label(right_info_frame, text="Gesamt-Statistik:", font=("Arial", 9, "bold"))
        stats_title.grid(row=0, column=0, columnspan=2, sticky="w")

        total_count_label = tk.Label(right_info_frame, text="Anzahl Clips:", font=("Arial", 8), anchor="w")
        total_count_label.grid(row=1, column=0, sticky="w", padx=(0, 5))
        self.info_labels["total_count"] = tk.Label(right_info_frame, text="0", font=("Arial", 8), anchor="w")
        self.info_labels["total_count"].grid(row=1, column=1, sticky="w")

        total_duration_label = tk.Label(right_info_frame, text="Gesamt-Dauer:", font=("Arial", 8), anchor="w")
        total_duration_label.grid(row=2, column=0, sticky="w", padx=(0, 5))
        self.info_labels["total_duration"] = tk.Label(right_info_frame, text="00:00", font=("Arial", 8), anchor="w")
        self.info_labels["total_duration"].grid(row=2, column=1, sticky="w")

        # NEU: Dateigröße und Encoding hinzufügen
        total_size_label_text = tk.Label(right_info_frame, text="Dateigröße:", font=("Arial", 8), anchor="w")
        total_size_label_text.grid(row=3, column=0, sticky="w", padx=(0, 5))
        self.size_label = tk.Label(right_info_frame, text="--", font=("Arial", 8), anchor="w")
        self.size_label.grid(row=3, column=1, sticky="w")

        encoding_label_text = tk.Label(right_info_frame, text="Encoding:", font=("Arial", 8), anchor="w")
        encoding_label_text.grid(row=4, column=0, sticky="w", padx=(0, 5))
        self.encoding_label = tk.Label(right_info_frame, text="--", font=("Arial", 8), anchor="w", fg="gray")
        self.encoding_label.grid(row=4, column=1, sticky="w")

        # Dummy-Label für clips_label (für Kompatibilität)
        self.clips_label = self.info_labels["total_count"]
        self.duration_label = self.info_labels["total_duration"]

        # Buttons
        button_frame = tk.Frame(right_info_frame)
        button_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=0)
        button_frame.columnconfigure(3, weight=0)  # NEUE Spalte

        self.delete_button = tk.Button(
            button_frame,
            text="Ausgewählten Clip löschen",
            command=self._delete_selected_clip,
            bg="#f44336",
            fg="white",
            font=("Arial", 9, "bold"),
            state="disabled"
        )
        self.delete_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.clear_selection_button = tk.Button(
            button_frame,
            text="Auswahl aufheben",
            command=self._clear_selection,
            bg="#999999",
            fg="white",
            font=("Arial", 9),
            state="disabled"
        )
        self.clear_selection_button.grid(row=0, column=1, sticky="ew", padx=(5, 5))

        self.qr_scan_button = tk.Button(
            button_frame,
            text="🔍",
            command=self._scan_current_clip_qr,
            bg="#2196F3",
            fg="white",
            font=("Arial", 9),
            width=3,
            state="disabled"
        )
        self.qr_scan_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        # --- NEU: Wasserzeichen-Button ---
        self.wm_button = tk.Button(
            button_frame,
            text="💧",
            command=self._on_wm_button_click,
            bg="#f0f0f0",
            fg="black",
            font=("Arial", 9),
            width=3,
            state="disabled"
        )
        # INITIAL VERSTECKT - wird von app.py gesteuert
        # self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        # --- ENDE NEU ---

        # Container für Status-Label und Progress bar in einer Zeile (zentriert)
        status_progress_container = tk.Frame(self.frame)
        status_progress_container.pack(pady=2, fill='x')

        # Innerer Container für Zentrierung
        center_container = tk.Frame(status_progress_container)
        center_container.pack(expand=True)

        # Status-Label links
        self.status_label = tk.Label(center_container, text="Ziehen Sie Videos in das Feld links",
                                     font=("Arial", 10), fg="gray", wraplength=400)
        self.status_label.pack(side='left', padx=(0, 10))

        # Progress bar container rechts
        self.progress_frame = tk.Frame(center_container)
        self.progress_frame.pack(side='left')


    def update_preview(self, video_paths):
        """
        Public entry point to update the preview.
        Handles cancellation of an ongoing process before starting a new one.
        NEU: Cleanup nur noch wenn wirklich nötig (komplett neue Videos).
        """
        # NEU: Cleanup NICHT mehr hier aufrufen - wird intelligent in _start_preview_creation_thread gehandhabt
        # self._cleanup_temp_copies()  # ENTFERNT!

        if self.processing_thread and self.processing_thread.is_alive():
            self.pending_restart_callback = lambda: self._start_preview_creation_thread(video_paths)
            self.cancel_creation()
            print("Preview creation in progress. Queuing a restart.")
        else:
            self._start_preview_creation_thread(video_paths)

    def _start_preview_creation_thread(self, video_paths):
        """Starts the background thread to create the preview."""
        if not video_paths:
            self.clear_preview()
            return

        self.last_video_paths = video_paths

        # NEU: Erstelle temp_dir nur wenn noch nicht vorhanden
        # WICHTIG: Wenn temp_dir existiert, NICHT neu erstellen - bereits kodierte Videos behalten!
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            self._create_temp_directory()  # Erstellt auch leere Caches/Maps
        else:
            # temp_dir existiert bereits - behalte bereits kodierte Videos
            # ABER: Bereinige ungültige Cache-Einträge (Dateien die nicht mehr existieren)
            invalid_entries = []
            for file_identity, copy_path in list(self.video_copies_map.items()):
                if not os.path.exists(copy_path):
                    invalid_entries.append(file_identity)

            if invalid_entries:
                print(f"🗑️ Bereinige {len(invalid_entries)} ungültige Cache-Einträge")
                for file_identity in invalid_entries:
                    del self.video_copies_map[file_identity]
                    if file_identity in self.metadata_cache:
                        del self.metadata_cache[file_identity]

            print(f"♻️ Verwende bestehendes temp_dir: {self.temp_dir}")
            print(f"   {len(self.video_copies_map)} Video(s) bereits im Cache")

        if not self.progress_handler:
            self.progress_handler = ProgressHandler(self.progress_frame)

        self.status_label.config(text="Erstelle Vorschau...", fg="blue")
        # self.play_button.config(state="disabled")  # ENTFERNT

        # self.action_button.config(text="⏹ Erstellung abbrechen",  # ENTFERNT
        #                           command=self.cancel_creation,
        #                           state="normal")
        self.encoding_label.config(text="Prüfe Formate...")
        self.clips_label.config(text=str(len(video_paths)))

        self.cancellation_event.clear()

        # NEU: Schneiden-Button wird nur gesperrt wenn tatsächlich neu kodiert wird
        # Das wird in _create_combined_preview entschieden
        # if self.app and hasattr(self.app, 'drag_drop'):
        #     self.app.drag_drop.set_cut_button_enabled(False)

        self.processing_thread = threading.Thread(target=self._create_combined_preview, args=(video_paths,))
        self.processing_thread.start()

    def _create_temp_directory(self):
        """Erstellt ein sauberes temporäres Verzeichnis für Video-Kopien."""
        # NEU: Wenn temp_dir bereits existiert, NICHT neu erstellen!
        if self.temp_dir and os.path.exists(self.temp_dir):
            print(f"⚠️ temp_dir existiert bereits, überspringe Erstellung: {self.temp_dir}")
            return

        self._cleanup_temp_copies()
        try:
            self.temp_dir = tempfile.mkdtemp(prefix="aero_studio_preview_")
            self.video_copies_map = {}
            self.metadata_cache = {}  # NEU
            print(f"Temporäres Verzeichnis erstellt: {self.temp_dir}")
        except Exception as e:
            print(f"Fehler beim Erstellen des temporären Verzeichnisses: {e}")
            self.temp_dir = None

    def _cleanup_temp_copies(self):
        """Löscht das temporäre Verzeichnis und seinen Inhalt."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                print(f"Temporäres Verzeichnis gelöscht: {self.temp_dir}")
            except Exception as e:
                print(f"Fehler beim Löschen des temporären Verzeichnisses {self.temp_dir}: {e}")
        self.temp_dir = None
        self.video_copies_map.clear()
        self.metadata_cache.clear()  # NEU
        self.videos_were_reencoded = False  # Flag zurücksetzen

        # NEU: Thumbnail-Cache leeren
        self.thumbnail_images.clear()

    def _prepare_video_copies(self, original_paths, needs_reencoding, preserve_cache=False):
        """
        Erstellt temporäre Kopien der Videos (A/B-Logik) UND
        füllt den Metadaten-Cache im selben Thread.

        Args:
            original_paths: Liste der zu verarbeitenden Video-Pfade
            needs_reencoding: True = Re-Encoding, False = Stream-Copy
            preserve_cache: True = Cache behalten (für inkrementelles Hinzufügen neuer Videos)
        """
        if not self.temp_dir:
            raise Exception("Temporäres Verzeichnis nicht initialisiert.")

        # NEU: Sperre Schneiden-Button nur wenn tatsächlich neu kodiert wird
        if needs_reencoding and self.app and hasattr(self.app, 'drag_drop'):
            self.parent.after(0, lambda: self.app.drag_drop.set_cut_button_enabled(False))

        # OPTIMIERUNG: Behalte existierende Kopien NUR wenn KEIN Re-Encoding nötig ODER preserve_cache=True
        if needs_reencoding and not preserve_cache:
            # Bei Re-Encoding müssen ALLE Videos neu kodiert werden
            # WICHTIG: Dateien NICHT löschen! Sie werden als Source benötigt und danach überschrieben.
            print("⚠️ Re-Encoding aktiviert → ALLE Videos werden neu kodiert (Format-Unterschiede)")

            # Leere nur die Caches, aber NICHT die Dateien!
            # Die Dateien werden während des Re-Encodings überschrieben
            self.video_copies_map.clear()
            self.metadata_cache.clear()
        elif needs_reencoding and preserve_cache:
            # Bei Re-Encoding MIT preserve_cache: Nur neue Videos verarbeiten, Cache behalten
            print(f"⚠️ Re-Encoding aktiviert → Kodiere nur neue Videos, Cache bleibt erhalten")
        else:
            # Bei Stream-Copy: Behalte existierende Kopien, entferne nur nicht mehr benötigte
            # WICHTIG: Verwende self.last_video_paths (die vollständige Liste), NICHT original_paths (nur neue Videos)!
            # Erstelle Set der aktuellen Dateinamen (nur Basename, nicht Pfad)
            current_filenames = set()
            # Nutze last_video_paths (vollständige aktuelle Video-Liste) statt original_paths (nur zu verarbeitende)
            video_list_to_check = self.last_video_paths if self.last_video_paths else original_paths
            for path in video_list_to_check:
                filename = os.path.basename(path)
                current_filenames.add(filename)

            # DEBUG: Zeige was in der Liste ist
            print(f"📋 DEBUG: current_filenames = {current_filenames}")
            print(f"📋 DEBUG: video_copies_map keys = {[identity[0] for identity in self.video_copies_map.keys()]}")

            # Finde Kopien, deren Dateinamen NICHT mehr in der aktuellen Liste sind
            identities_to_remove = []
            for identity, copy_path in list(self.video_copies_map.items()):
                # Identity ist (filename, size), also identity[0] ist der Dateiname
                filename_in_cache = identity[0]
                # Nur entfernen wenn Dateiname NICHT in current_filenames
                if filename_in_cache not in current_filenames:
                    print(f"🗑️ DEBUG: '{filename_in_cache}' NICHT in current_filenames - wird gelöscht")
                    identities_to_remove.append(identity)
                else:
                    print(f"✅ DEBUG: '{filename_in_cache}' in current_filenames - wird behalten")

            for identity in identities_to_remove:
                # Lösche Datei und Cache-Eintrag
                if identity in self.video_copies_map:
                    old_copy = self.video_copies_map[identity]
                    if os.path.exists(old_copy):
                        try:
                            os.remove(old_copy)
                            print(f"🗑️ Entferne alte Kopie: {os.path.basename(old_copy)}")
                        except:
                            pass
                    del self.video_copies_map[identity]
                if identity in self.metadata_cache:
                    del self.metadata_cache[identity]

        temp_copy_paths = []
        total_clips = len(original_paths)

        # Zähle wie viele Videos tatsächlich verarbeitet werden müssen
        if needs_reencoding and not preserve_cache:
            # Bei Re-Encoding OHNE preserve_cache: ALLE Videos verarbeiten
            clips_to_process = total_clips
            print(f"📦 ALLE {total_clips} Videos müssen neu kodiert werden (Format-Unterschiede)")
        elif needs_reencoding and preserve_cache:
            # Bei Re-Encoding MIT preserve_cache: Nur neue Videos (nicht im Cache)
            clips_to_process = 0
            for original_path in original_paths:
                if not self._find_cached_copy(original_path):
                    clips_to_process += 1
            print(f"📦 {clips_to_process} von {total_clips} Videos müssen neu kodiert werden ({total_clips - clips_to_process} bereits im Cache)")
        else:
            # Bei Stream-Copy: Nur neue Videos
            clips_to_process = 0
            for original_path in original_paths:
                if not self._find_cached_copy(original_path):
                    clips_to_process += 1

            if clips_to_process == 0:
                print(f"✅ Alle {total_clips} Videos bereits im Cache - nichts zu tun!")
            else:
                print(f"📦 {clips_to_process} von {total_clips} Videos müssen verarbeitet werden ({total_clips - clips_to_process} bereits im Cache)")

        self.parent.after(0, self.progress_handler.pack_progress_bar_right)
        self.parent.after(0, self.progress_handler.update_progress, 0, total_clips)

        # NEU: Sammle alle Videos, die verarbeitet werden müssen
        videos_to_process = []  # Liste von (index, original_path, source_path, copy_path, filename)

        for i, original_path in enumerate(original_paths):
            self._check_for_cancellation()

            # NEU: Prüfe ob die Datei bereits im Working-Folder liegt
            # (wurde von drag_drop.py importiert)
            is_in_working_folder = (self.temp_dir and
                                   os.path.normpath(os.path.dirname(original_path)) == os.path.normpath(self.temp_dir))

            if is_in_working_folder and not needs_reencoding:
                # Video ist bereits im Working-Folder UND kein Re-Encoding nötig!
                print(f"✅ Video bereits im Working-Folder: {os.path.basename(original_path)}")

                # Verwende die Datei direkt
                temp_copy_paths.append(original_path)

                # Füge zum Cache hinzu
                file_identity = self._get_file_identity(original_path)
                if file_identity and file_identity not in self.video_copies_map:
                    self.video_copies_map[file_identity] = original_path

                # Cache Metadaten wenn noch nicht vorhanden
                if file_identity and file_identity not in self.metadata_cache:
                    try:
                        # original_path IST bereits die Kopie im Working-Folder
                        self._cache_metadata_for_copy(original_path, original_path)
                    except Exception as e:
                        print(f"  ⚠️ Metadaten-Extraktion fehlgeschlagen: {e}")

                self.parent.after(0, self.progress_handler.update_progress, i + 1, total_clips)
                continue  # Überspringe weitere Verarbeitung für dieses Video

            # Wenn needs_reencoding=True: Datei muss neu kodiert werden, auch wenn im Working-Folder
            if is_in_working_folder and needs_reencoding:
                print(f"🔄 Video im Working-Folder wird neu kodiert (Format-Unterschiede): {os.path.basename(original_path)}")

            filename = os.path.basename(original_path)
            # Ersetze ungültige Zeichen im Dateinamen für den Fall der Fälle
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            copy_path = os.path.join(self.temp_dir, safe_filename)

            # Bei Namenskollision: Füge Suffix hinzu
            if os.path.exists(copy_path):
                base_name, ext = os.path.splitext(safe_filename)
                counter = 1
                while os.path.exists(copy_path):
                    copy_path = os.path.join(self.temp_dir, f"{base_name}_{counter}{ext}")
                    counter += 1


            # OPTIMIERUNG: Prüfe ob bereits eine gültige Kopie existiert
            # Bei Stream-Copy ODER bei Re-Encoding mit preserve_cache
            if not needs_reencoding or preserve_cache:
                existing_copy = self._find_cached_copy(original_path)

                if existing_copy:
                    # Kopie existiert bereits - überspringen!
                    print(f"♻️ Verwende bereits existierende Kopie: {os.path.basename(existing_copy)}")

                    # Prüfe ob Pfad umbenannt werden muss (Index hat sich geändert)
                    if existing_copy != copy_path:
                        try:
                            # Benenne um zu neuem Index-Pfad
                            file_identity = self._get_file_identity(original_path)
                            shutil.move(existing_copy, copy_path)
                            # Aktualisiere Cache mit neuem Pfad
                            if file_identity:
                                self.video_copies_map[file_identity] = copy_path
                            print(f"  → Umbenannt zu: {os.path.basename(copy_path)}")
                        except Exception as e:
                            # Falls Umbenennung fehlschlägt, behalte alten Pfad
                            print(f"  ⚠️ Umbenennung fehlgeschlagen: {e}")
                            copy_path = existing_copy

                    temp_copy_paths.append(copy_path)
                    self.parent.after(0, self.progress_handler.update_progress, i + 1, total_clips)
                    continue  # Überspringe Verarbeitung

            # WICHTIG: Prüfe ob die Original-Datei existiert
            # Nach einem Split existieren die Dateien nur noch im Working-Folder!
            source_path = original_path
            if not os.path.exists(original_path):
                # Datei existiert nicht am Original-Ort, suche im Working-Folder
                working_copy = self._find_cached_copy(original_path)
                if working_copy and os.path.exists(working_copy):
                    source_path = working_copy
                    print(f"→ Verwende Working-Folder-Kopie: {os.path.basename(working_copy)}")
                else:
                    raise Exception(f"Datei nicht gefunden: {filename} (weder in Upload-Ordner noch Working-Folder)")

            # Füge zur Liste der zu verarbeitenden Videos hinzu
            videos_to_process.append((i, original_path, source_path, copy_path, filename))
            temp_copy_paths.append(copy_path)  # Bereits hier hinzufügen für korrekte Reihenfolge

        # Verarbeite Videos (parallel oder sequenziell)
        if needs_reencoding and self.parallel_processor and len(videos_to_process) > 1:
            # --- PARALLEL: Re-Encoding mehrerer Videos gleichzeitig ---
            print(f"🚀 Starte paralleles Re-Encoding von {len(videos_to_process)} Videos...")
            self.parent.after(0, lambda: self.status_label.config(
                text=f"Kodiere {len(videos_to_process)} Videos parallel...", fg="orange"))

            # NEU: Aktiviere Progress-Modus in DragDrop-Tabelle
            if self.app and hasattr(self.app, 'drag_drop'):
                self.parent.after(0, self.app.drag_drop.show_progress_mode)

            # Setze initialen Gesamt-Fortschritt
            self.parent.after(0, self.progress_handler.update_progress, 0, len(videos_to_process))

            # Erstelle Tasks für parallele Verarbeitung
            tasks = []
            for i, original_path, source_path, copy_path, filename in videos_to_process:
                # Setze Status auf "Warte..." für alle Videos
                if self.app and hasattr(self.app, 'drag_drop'):
                    self.parent.after(0, self.app.drag_drop.set_video_status, i, "⏳ Warte...")

                def reencode_task(src=source_path, dst=copy_path, idx=i, task_id=None):
                    # Setze Status auf "Kodiert..." wenn Task startet
                    if self.app and hasattr(self.app, 'drag_drop'):
                        self.parent.after(0, self.app.drag_drop.set_video_status, idx, "🔄 Kodiert...")
                    self._reencode_single_clip(src, dst, task_id, idx)
                tasks.append((reencode_task, (), {}))

            # Führe parallele Verarbeitung aus
            start_time = time.time()

            # Zähler für fertige Videos (thread-safe)
            import threading
            completed_videos = {'count': 0}
            completed_lock = threading.Lock()

            def on_video_completed(task_index):
                """Callback wenn ein Video fertig enkodiert ist"""
                with completed_lock:
                    completed_videos['count'] += 1
                    # Update Gesamt-Fortschritt in VideoPreview
                    self.parent.after(0, self.progress_handler.update_progress,
                                    completed_videos['count'], len(videos_to_process))

            results = self.parallel_processor.process_videos_parallel(tasks, self.cancellation_event, on_video_completed)
            total_time = time.time() - start_time

            # Prüfe auf Fehler
            for task_index, result, error in results:
                if error:
                    if self.cancellation_event.is_set():
                        print("Paralleles Re-Encoding abgebrochen.")
                        raise Exception("Neukodierung abgebrochen.")
                    else:
                        i, original_path, source_path, copy_path, filename = videos_to_process[task_index]
                        print(f"Fehler bei Neukodierung von {filename}: {error}")
                        raise Exception(f"Fehler bei Neukodierung von {filename}")

            avg_time = total_time / len(videos_to_process)
            print(f"✅ Paralleles Re-Encoding abgeschlossen in {total_time:.1f}s ({avg_time:.1f}s pro Video)")

            # Cache Metadaten für alle verarbeiteten Videos
            for i, original_path, source_path, copy_path, filename in videos_to_process:
                file_identity = self._get_file_identity(original_path)
                if file_identity:
                    self.video_copies_map[file_identity] = copy_path
                self._cache_metadata_for_copy(original_path, copy_path)

        elif needs_reencoding and len(videos_to_process) > 0:
            # --- SEQUENZIELL: Re-Encoding (wie bisher) ---
            print(f"Starte sequenzielles Re-Encoding von {len(videos_to_process)} Videos...")

            # NEU: Aktiviere Progress-Modus in DragDrop-Tabelle
            if self.app and hasattr(self.app, 'drag_drop'):
                self.parent.after(0, self.app.drag_drop.show_progress_mode)

            encoding_times = []

            for idx, (i, original_path, source_path, copy_path, filename) in enumerate(videos_to_process):
                self._check_for_cancellation()

                start_time = time.time()

                # Berechne ETA basierend auf bisherigen Kodierzeiten
                eta_str = ""
                if encoding_times:
                    avg_time_per_video = sum(encoding_times) / len(encoding_times)
                    remaining_videos = len(videos_to_process) - idx
                    eta_seconds = avg_time_per_video * remaining_videos
                    eta_minutes = int(eta_seconds // 60)
                    eta_secs = int(eta_seconds % 60)
                    eta_str = f" (ETA: ~{eta_minutes}:{eta_secs:02d})"

                status_msg = f"Kodiere Clip {idx + 1}/{len(videos_to_process)}{eta_str}..."
                self.parent.after(0, lambda msg=status_msg: self.status_label.config(text=msg, fg="orange"))

                # Setze Status in DragDrop-Tabelle
                if self.app and hasattr(self.app, 'drag_drop'):
                    self.parent.after(0, self.app.drag_drop.set_video_status, i, "🔄 Kodiert...")

                try:
                    self._reencode_single_clip(source_path, copy_path, video_index=i)

                    # Speichere Kodierzeit für ETA-Berechnung
                    encoding_time = time.time() - start_time
                    encoding_times.append(encoding_time)

                except Exception as e:
                    if self.cancellation_event.is_set():
                        print("Neukodierung abgebrochen.")
                        raise
                    else:
                        print(f"Fehler bei Neukodierung von {filename}: {e}")
                        raise Exception(f"Fehler bei Neukodierung von {filename}")

                # Speichere im Cache mit file-identity als Key
                file_identity = self._get_file_identity(original_path)
                if file_identity:
                    self.video_copies_map[file_identity] = copy_path

                # NEU: Metadaten direkt nach Erstellung der Kopie cachen
                self._cache_metadata_for_copy(original_path, copy_path)

                self.parent.after(0, self.progress_handler.update_progress, idx + 1, len(videos_to_process))

        elif not needs_reencoding and len(videos_to_process) > 0:
            # --- Stream-Copy (ohne Thumbnails) ---
            for idx, (i, original_path, source_path, copy_path, filename) in enumerate(videos_to_process):
                self._check_for_cancellation()

                status_msg = f"Kopiere Clip {idx + 1}/{len(videos_to_process)}..."
                self.parent.after(0, lambda msg=status_msg: self.status_label.config(text=msg, fg="blue"))

                try:
                    # Verwende FFmpeg Stream-Copy um Thumbnails zu entfernen
                    self._copy_without_thumbnails(source_path, copy_path)
                except Exception as e:
                    print(f"Fehler beim Kopieren von {filename}: {e}")
                    raise Exception(f"Fehler beim Kopieren von {filename}")

                # Speichere im Cache mit file-identity als Key
                file_identity = self._get_file_identity(original_path)
                if file_identity:
                    self.video_copies_map[file_identity] = copy_path

                # NEU: Metadaten direkt nach Erstellung der Kopie cachen
                self._cache_metadata_for_copy(original_path, copy_path)

                self.parent.after(0, self.progress_handler.update_progress, idx + 1, len(videos_to_process))

        # NEU: Entsperre Schneiden-Button nach Kopieren/Kodieren
        if self.app and hasattr(self.app, 'drag_drop'):
            self.parent.after(0, lambda: self.app.drag_drop.set_cut_button_enabled(True))
            # Deaktiviere Progress-Modus und zeige wieder Datum/Uhrzeit
            if needs_reencoding and len(videos_to_process) > 0:
                self.parent.after(0, self.app.drag_drop.show_normal_mode)

        self.parent.after(0, self.progress_handler.reset)
        return temp_copy_paths

    def _copy_without_thumbnails(self, input_path, output_path):
        """
        Kopiert ein Video ohne Re-Encoding und entfernt dabei MJPEG-Thumbnails.

        MJPEG-Thumbnails (attached_pic) werden oft von Kameras (besonders DJI-Drohnen)
        hinzugefügt und können beim Concat Probleme verursachen.
        """
        # Prüfe ob Thumbnails vorhanden sind
        has_thumbnail = self._check_for_thumbnail(input_path)

        if has_thumbnail:
            print(f"  → Entferne MJPEG-Thumbnail aus {os.path.basename(input_path)}")

            # FFmpeg Stream-Copy OHNE attached_pic (Thumbnails)
            # -map 0 = Alle Streams
            # -map -0:v:? -map 0:V = Entferne alle Video-Streams, füge nur nicht-Thumbnail-Videos hinzu
            # Einfacher: -dn entfernt Data-Streams, aber wir brauchen präziser:
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-map", "0:v:0",      # Haupt-Video-Stream
                "-map", "0:a?",       # Audio (optional)
                "-map", "0:s?",       # Untertitel (optional)
                "-c", "copy",         # Stream-Copy (kein Re-Encoding)
                "-disposition:v:0", "default",  # Setze Haupt-Video als Default
                output_path
            ]
        else:
            # Kein Thumbnail, normale Stream-Copy
            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,
                "-c", "copy",
                "-map", "0",
                output_path
            ]

        # Führe FFmpeg aus
        result = subprocess.run(
            cmd,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace',
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        if result.returncode != 0:
            # Bei Fehler: Zeige Details und fallback zu shutil.copy2
            stderr_text = result.stderr if result.stderr else ""
            print(f"⚠️ FFmpeg Stream-Copy fehlgeschlagen, verwende Datei-Kopie als Fallback")
            print(f"   Fehler: {stderr_text[:200]}")

            # Fallback: Normale Datei-Kopie
            shutil.copy2(input_path, output_path)

    def _check_for_thumbnail(self, video_path):
        """
        Prüft ob ein Video MJPEG-Thumbnails (attached_pic) enthält.

        Returns:
            True wenn Thumbnails gefunden wurden, sonst False
        """
        try:
            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                video_path
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            if result.returncode == 0:
                data = json.loads(result.stdout)
                streams = data.get("streams", [])

                # Suche nach attached_pic (MJPEG-Thumbnails)
                for stream in streams:
                    if stream.get("codec_type") == "video":
                        disposition = stream.get("disposition", {})
                        codec_name = stream.get("codec_name", "")

                        # attached_pic = 1 bedeutet es ist ein Thumbnail
                        if disposition.get("attached_pic") == 1:
                            print(f"    Thumbnail gefunden: {codec_name}")
                            return True

                        # Manche Videos haben MJPEG als zweiten Video-Stream
                        if codec_name == "mjpeg" and stream.get("width", 0) < 500:
                            print(f"    MJPEG-Thumbnail gefunden ({stream.get('width')}x{stream.get('height')})")
                            return True

            return False

        except Exception as e:
            print(f"    Konnte Thumbnail-Check nicht durchführen: {e}")
            return False  # Im Zweifelsfall ohne Thumbnail-Entfernung kopieren

    def _run_ffmpeg_with_progress(self, command, total_duration=None, task_name="Encoding", task_id=None, video_index=None):
        """
        Führt FFmpeg-Befehl aus und liest den Fortschritt live aus.

        WICHTIG: Nutzt separaten Thread für stderr um Deadlocks zu vermeiden.

        Args:
            command: FFmpeg-Befehl als Liste
            total_duration: Gesamtdauer des Videos in Sekunden (für Fortschrittsberechnung)
            task_name: Name der Aufgabe für Status-Updates
            task_id: Optional ID für parallele Tasks
            video_index: Optional Index des Videos in der DragDrop-Tabelle

        Returns:
            True bei Erfolg, wirft Exception bei Fehler
        """
        # Füge Progress-Ausgabe zu FFmpeg-Befehl hinzu
        progress_command = command.copy()
        # Füge -progress pipe:1 vor dem Output-File ein (letztes Element)
        output_file = progress_command[-1]
        progress_command = progress_command[:-1] + ['-progress', 'pipe:1'] + [output_file]

        # Starte FFmpeg-Prozess
        process = subprocess.Popen(
            progress_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,  # Line buffered
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        start_time = time.time()
        last_update_time = start_time

        # Lese Fortschritt aus stdout
        current_time_sec = 0.0
        fps = 0.0

        # Sammle stderr in separatem Thread um Deadlock zu vermeiden
        stderr_lines = []
        def read_stderr():
            try:
                for line in process.stderr:
                    stderr_lines.append(line)
            except Exception as ex:
                # It's possible for the pipe to close unexpectedly if the process ends.
                # We ignore these errors to avoid crashing the background thread.
                # If needed, log unexpected exceptions for debugging.
                # import logging
                # logging.exception("Exception in read_stderr thread")
                pass
        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        try:
            while True:
                self._check_for_cancellation()

                # Non-blocking read mit Timeout
                line = process.stdout.readline()
                if not line:
                    # Prüfe ob Prozess beendet ist
                    if process.poll() is not None:
                        break
                    # Kurze Pause um CPU nicht zu belasten
                    time.sleep(0.01)
                    continue

                line = line.strip()

                # Parse FFmpeg Progress-Ausgabe
                if line.startswith('out_time_ms='):
                    try:
                        time_ms_str = line.split('=')[1].strip()
                        time_ms = int(time_ms_str)
                        current_time_sec = time_ms / 1000000.0
                    except (ValueError, IndexError):
                        # Ignore malformed FFmpeg progress lines; these are expected occasionally.
                        pass

                elif line.startswith('fps='):
                    fps_str = line.split('=')[1].strip()
                    try:
                        fps = float(fps_str)
                    except ValueError:
                        # Ignore malformed fps values; not critical for progress update
                        pass

                # Update nur alle 0.5 Sekunden um UI nicht zu überlasten
                current_update_time = time.time()
                if current_update_time - last_update_time >= 0.5:
                    last_update_time = current_update_time

                    # Stelle sicher, dass total_duration ein numerischer Wert ist
                    if total_duration is not None and isinstance(total_duration, (int, float)) and total_duration > 0:
                        progress_percent = min((current_time_sec / total_duration) * 100, 100)

                        # Berechne ETA
                        elapsed_time = current_update_time - start_time
                        if current_time_sec > 0 and elapsed_time > 0:
                            encoding_speed = current_time_sec / elapsed_time
                            remaining_time = (total_duration - current_time_sec) / encoding_speed if encoding_speed > 0 else 0

                            # Formatiere ETA
                            eta_minutes = int(remaining_time // 60)
                            eta_seconds = int(remaining_time % 60)
                            eta_str = f"{eta_minutes}:{eta_seconds:02d}"

                            # Sende Update NUR an DragDrop-Tabelle für individuellen Clip-Fortschritt
                            # VideoPreview zeigt Gesamt-Fortschritt über update_progress()
                            if video_index is not None and self.app and hasattr(self.app, 'drag_drop'):
                                self.parent.after(0, self.app.drag_drop.update_video_progress,
                                                video_index, progress_percent, fps, eta_str)

            # Warte auf Prozessende mit Timeout
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("⚠️ FFmpeg antwortet nicht - beende Prozess...")
                process.kill()
                process.wait()

            # Warte auf stderr-Thread
            stderr_thread.join(timeout=2)

            # Prüfe Return Code
            if process.returncode != 0:
                stderr_output = ''.join(stderr_lines)
                if self.cancellation_event.is_set():
                    raise Exception("Encoding vom Benutzer abgebrochen.")

                # Zeige nur relevante stderr-Zeilen (letzte 20)
                stderr_relevant = '\n'.join(stderr_lines[-20:]) if stderr_lines else "Kein stderr verfügbar"
                print(f"FFmpeg Fehler (Code {process.returncode}):")
                print(stderr_relevant)
                raise subprocess.CalledProcessError(process.returncode, command, stderr=stderr_output)

            # Finaler 100% Status nur für DragDrop-Tabelle (nicht für VideoPreview ProgressHandler)
            # VideoPreview zeigt Gesamt-Fortschritt über update_progress()
            if video_index is not None and self.app and hasattr(self.app, 'drag_drop'):
                if total_duration is not None and isinstance(total_duration, (int, float)):
                    self.parent.after(0, self.app.drag_drop.update_video_progress,
                                    video_index, 100, fps, "0:00")

            return True

        except Exception as e:
            # Beende FFmpeg-Prozess bei Fehler
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise

    def _get_video_duration_seconds(self, video_path):
        """
        Ermittelt die Dauer eines Videos in Sekunden mit ffprobe.

        Args:
            video_path: Pfad zur Videodatei

        Returns:
            Dauer in Sekunden als float, oder None bei Fehler
        """
        try:
            command = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path
            ]
            result = subprocess.run(command, capture_output=True, text=True,
                                  timeout=10, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode == 0 and result.stdout.strip():
                duration_str = result.stdout.strip()
                return float(duration_str)
            else:
                return None
        except (ValueError, subprocess.TimeoutExpired) as e:
            print(f"Warnung: Konnte Videodauer nicht ermitteln für {video_path}: {e}")
            return None

    def _reencode_single_clip(self, input_path, output_path, task_id=None, video_index=None):
        """
        Kodiert ein einzelnes Video neu auf das Ziel-Format.
        WICHTIG: Blockiert während des Re-Encodings.

        Args:
            input_path: Pfad zum Input-Video
            output_path: Pfad zum Output-Video
            task_id: Optional Task-ID für paralleles Encoding
            video_index: Optional Index des Videos in der DragDrop-Tabelle
        """
        target_params = {
            'width': 1920, 'height': 1080, 'fps': 30, 'pix_fmt': 'yuv420p',
            'audio_codec': 'aac', 'audio_sample_rate': 48000, 'audio_channels': 2
        }
        tp = target_params

        # NEU: Hole Codec-Auswahl aus Settings
        selected_codec = "auto"
        if self.app and hasattr(self.app, 'config'):
            settings = self.app.config.get_settings()
            selected_codec = settings.get("video_codec", "auto")

        # Wenn "auto", verwende h264 (Standard), sonst den ausgewählten Codec
        codec_to_use = "h264" if selected_codec == "auto" else selected_codec

        # Hole Encoding-Parameter für den gewählten Codec
        encoding_params = self._get_encoding_params(codec_to_use)

        cmd = ["ffmpeg", "-y"]

        # FEHLERTOLERANZ: Ignoriere Dekodier-Fehler
        cmd.extend(["-err_detect", "ignore_err", "-fflags", "+genpts+igndts"])

        # Hardware-spezifische Konfiguration
        hw_info = self.hw_detector.detect_hardware()
        hw_type = hw_info.get('type') if hw_info.get('available') else None
        # NEU: use_hw_filters = False, weil wir Software-Filter für Aspect-Ratio nutzen
        # Nur das Encoding läuft in Hardware, nicht die Filter
        use_hw_filters = False  # Deaktiviert wegen Aspect-Ratio-Problemen

        # Kein Hardware-Decoding, da wir Software-Filter verwenden
        # Dies verhindert Pixel-Format-Inkompatibilitäten

        # Input
        cmd.extend(["-i", input_path])

        # Filter-Chain basierend auf Hardware-Typ
        if use_hw_filters and hw_type == 'intel':
            # Intel Quick Sync: Verwende vpp_qsv (Video Processing Pipeline)
            # WICHTIG: vpp_qsv hat KEIN force_original_aspect_ratio!
            # Lösung: Erst mit Software-Scale auf richtige Größe MIT Aspect Ratio,
            # dann mit vpp_qsv nur FPS-Konvertierung und Format
            # Alternative: Nutze Software-Filter für Scaling, nur Hardware für Encoding
            filter_str = (
                f"scale={tp['width']}:{tp['height']}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                f"pad={tp['width']}:{tp['height']}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={tp['fps']},format=nv12,hwupload=extra_hw_frames=64,format=qsv"
            )
            cmd.extend(["-vf", filter_str])
        elif use_hw_filters and hw_type == 'nvidia':
            # NVIDIA CUDA: scale_cuda unterstützt force_original_aspect_ratio nicht direkt
            # Lösung: Berechne Scaling manuell oder nutze Software-Filter
            # Für Konsistenz: Software-Scale + Hardware-Upload
            filter_str = (
                f"scale={tp['width']}:{tp['height']}:force_original_aspect_ratio=decrease:flags=fast_bilinear,"
                f"pad={tp['width']}:{tp['height']}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={tp['fps']},format=nv12,hwupload"
            )
            cmd.extend(["-vf", filter_str])
        else:
            # Software-Filter (Standard)
            # WICHTIG: format=yuv420p konvertiert 10-bit Videos zu 8-bit (für Kompatibilität)
            cmd.extend([
                "-vf", f"scale={tp['width']}:{tp['height']}:force_original_aspect_ratio=decrease:flags=fast_bilinear,pad={tp['width']}:{tp['height']}:(ow-iw)/2:(oh-ih)/2:color=black,fps={tp['fps']},format=yuv420p"
            ])

        # WICHTIG: Pixel-Format explizit setzen für bessere Kompatibilität
        cmd.extend(["-pix_fmt", "yuv420p"])

        # Video-Encoder (Hardware oder Software)
        cmd.extend(encoding_params['output_params'])

        # Zusätzliche Parameter für Software-Encoding (wenn HW nicht aktiv)
        if not self.hw_accel_enabled:
            encoder = encoding_params.get('encoder', 'libx264')

            # Codec-spezifische Parameter
            if encoder == 'libx264':
                # H.264 spezifische Optimierungen
                cmd.extend([
                    "-preset", "veryfast",
                    "-crf", "26",
                    "-tune", "fastdecode",
                    "-x264-params", "ref=1:me=dia:subme=1:trellis=0"
                ])
            elif encoder == 'libx265':
                # H.265/HEVC spezifische Optimierungen
                cmd.extend([
                    "-preset", "veryfast",
                    "-crf", "28",
                    "-x265-params", "ref=1:me=dia"
                ])
            elif encoder == 'libvpx-vp9':
                # VP9 spezifische Optimierungen
                cmd.extend([
                    "-deadline", "realtime",  # Schnelles Encoding
                    "-cpu-used", "5",  # Geschwindigkeit (0=langsam, 5=schnell)
                    "-row-mt", "1",  # Multi-Threading
                    "-b:v", "0",  # CRF Mode
                    "-crf", "31"  # Qualität (höher = kleiner/schlechter)
                ])
            elif encoder in ['libaom-av1', 'libsvtav1']:
                # AV1 spezifische Optimierungen
                cmd.extend([
                    "-cpu-used", "8",  # Sehr schnell
                    "-crf", "35",
                    "-b:v", "0"
                ])
        else:
            # Bei Hardware-Encoding: Optimierte Qualitätseinstellungen
            # (preset und tune sind bereits in encoding_params enthalten)
            print(f"  → Nutze Hardware-Encoder: {encoding_params['encoder']}")
            if use_hw_filters:
                print(f"  → Nutze Hardware-Filter: {hw_type}")

        # Audio-Encoding
        cmd.extend([
            "-c:a", tp['audio_codec'],
            "-b:a", "96k",
            "-ar", str(tp['audio_sample_rate']),
            "-ac", str(tp['audio_channels'])
        ])

        # Container-Optionen
        cmd.extend([
            "-movflags", "+faststart",
            "-max_muxing_queue_size", "1024",
            "-map", "0:v:0", "-map", "0:a:0?",
            output_path
        ])

        # WICHTIG: Capture stderr für Fehlerdiagnose
        hw_status = "HW-Beschleunigung" if self.hw_accel_enabled else "Software"
        print(f"Starte Re-Encoding ({hw_status}): {os.path.basename(input_path)} → 1080p@30fps")

        # Hole Videodauer für Fortschrittsanzeige
        total_duration = self._get_video_duration_seconds(input_path)
        if total_duration is None:
            print(f"Warnung: Konnte Videodauer nicht ermitteln - kein ETA verfügbar")

        # Task Name basierend auf task_id
        task_name = f"Re-Encoding {os.path.basename(input_path)[:20]}"
        if task_id:
            task_name = f"[Task {task_id}] " + task_name

        # Verwende neue Methode mit Live-Fortschritt
        try:
            self._run_ffmpeg_with_progress(cmd, total_duration, task_name, task_id, video_index)
            print(f"✅ Re-Encoding erfolgreich: {os.path.basename(output_path)}")

            # Setze Status in DragDrop-Tabelle auf "Fertig"
            if video_index is not None and self.app and hasattr(self.app, 'drag_drop'):
                self.parent.after(0, self.app.drag_drop.set_video_status, video_index, "✓ Fertig")

            return  # Erfolg!
        except subprocess.CalledProcessError as e:
            # Hole stderr aus dem Fehler
            stderr_text = e.stderr if hasattr(e, 'stderr') else "Kein stderr verfügbar"

            # ZUSÄTZLICHE ÜBERPRÜFUNG: Wenn Output-Datei existiert und vernünftige Größe hat,
            # betrachte als Erfolg
            output_exists = os.path.exists(output_path)
            output_size = os.path.getsize(output_path) if output_exists else 0
            output_valid = output_exists and output_size > 10240

            if output_valid:
                print(f"⚠️ FFmpeg beendet mit Fehler, aber Output-Datei ist valid ({output_size} bytes)")
                print(f"→ Betrachte als Erfolg")
                print(f"✅ Re-Encoding erfolgreich: {os.path.basename(output_path)}")
                return  # Erfolg!

            # Echter Fehler - zeige Details
            print(f"\n{'='*60}")
            print(f"FFmpeg Fehler bei: {os.path.basename(input_path)}")
            print(f"{'='*60}")
            print(f"Fehler: {stderr_text[:500]}")  # Zeige ersten Teil
            print(f"{'='*60}\n")

            # WICHTIG: Prüfe auf Hardware-Encoder-Fehler und versuche Fallback
            if self.hw_accel_enabled and stderr_text:
                hw_error_indicators = [
                    "10 bit encode not supported",  # WICHTIG: 10-bit Videos nicht von HW-Encoder unterstützt
                    "Driver does not support",
                    "nvenc API version",
                    "minimum required Nvidia driver",
                    "Error while opening encoder",
                    "Could not open encoder",
                    "No NVENC capable devices found",
                    "No capable devices found",
                    "Cannot load nvcuda.dll",
                    "amf encoder error",
                    "qsv encoder error",
                    "Unable to parse option",
                    "Error setting option",
                    "Undefined constant",
                    "hwaccel initialisation returned error"
                ]

                if any(indicator in stderr_text for indicator in hw_error_indicators):
                    print(f"⚠️ Hardware-Encoder-Fehler erkannt!")

                    # Prüfe spezifisch auf 10-bit Problem
                    if "10 bit encode not supported" in stderr_text:
                        print(f"→ 10-bit Video erkannt - Hardware-Encoder unterstützt nur 8-bit")

                    print(f"→ Versuche Fallback auf Software-Encoding (libx264)...")

                    # Deaktiviere Hardware-Beschleunigung temporär
                    original_hw_state = self.hw_accel_enabled
                    self.hw_accel_enabled = False

                    try:
                        # Rekursiver Aufruf mit Software-Encoding
                        print(f"Starte Re-Encoding (Software): {os.path.basename(input_path)} → 1080p@30fps")
                        self._reencode_single_clip(input_path, output_path, task_id, video_index)
                        print(f"✅ Software-Encoding erfolgreich als Fallback")
                        return  # Erfolgreicher Fallback
                    finally:
                        # Stelle Hardware-Zustand wieder her
                        self.hw_accel_enabled = original_hw_state

            # Kein Fallback möglich - werfe Fehler
            raise Exception(f"Re-Encoding fehlgeschlagen: {os.path.basename(input_path)}")
        except Exception as e:
            if "abgebrochen" in str(e) or "abort" in str(e).lower():
                raise  # Nutzer-Abbruch weiterreichen
            print(f"Fehler beim Re-Encoding: {e}")
            raise

    def _create_combined_preview(self, video_paths):
        """
        Erstellt ein kombiniertes Vorschau-Video.
        NEU: Verwendet bereits existierende Kopien wieder, wenn die gleichen Videos nur umsortiert wurden.
        NEU: Berücksichtigt Codec-Auswahl aus den Einstellungen.
        """
        try:
            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            # Deaktiviere Erstellen-Button während Kombinierung
            self.parent.after(0, lambda: self.app._set_button_waiting())

            # Hole Codec-Auswahl aus Settings
            selected_codec = "auto"
            if self.app and hasattr(self.app, 'config'):
                settings = self.app.config.get_settings()
                selected_codec = settings.get("video_codec", "auto")
                print(f"Codec-Auswahl: {selected_codec}")

            # Initialisiere Variablen
            needs_reencoding = False
            force_codec = selected_codec != "auto"  # Wenn nicht "auto", dann erzwinge Re-Encoding
            temp_copy_paths = []

            # Prüfe ob bereits Kopien existieren (mit file-identity-basiertem Cache)
            all_videos_cached = True
            cached_copy_paths = []

            for original_path in video_paths:
                copy_path = self._find_cached_copy(original_path)
                if copy_path:
                    cached_copy_paths.append(copy_path)
                else:
                    all_videos_cached = False
                    break

            if all_videos_cached and self.temp_dir and os.path.exists(self.temp_dir):
                # FALL 1: Alle Videos bereits gecacht (z.B. beim Verschieben)
                # Prüfe ob alle Kopien noch existieren
                if all(os.path.exists(copy_path) for copy_path in cached_copy_paths):
                    print(f"✅ Alle {len(cached_copy_paths)} Videos bereits im Cache")
                    temp_copy_paths = cached_copy_paths
                    needs_reencoding = False
                    self.parent.after(0, lambda: self.encoding_label.config(
                        text="Verwende existierende Kopien"))
                else:
                    # Mindestens eine Kopie fehlt
                    print("⚠️ Einige Kopien fehlen, erstelle Videos neu...")
                    all_videos_cached = False
                    temp_copy_paths = []

            if not all_videos_cached:
                # FALL 2: Nicht alle Videos gecacht (neue Videos hinzugefügt)

                # Finde neue Videos (nicht im Cache) - mit file-identity-basiertem Cache
                new_videos = []
                cached_videos = []

                for p in video_paths:
                    copy_path = self._find_cached_copy(p)
                    if copy_path:
                        cached_videos.append(p)
                    else:
                        new_videos.append(p)

                print(f"📊 Neue Videos: {len(new_videos)}, Gecachte: {len(cached_videos)}")

                if len(new_videos) > 0 and len(cached_videos) > 0:
                    # FALL 2a: Mix aus neuen und gecachten Videos
                    if self.videos_were_reencoded:
                        # Gecachte Videos wurden bereits neu kodiert (sind 1080p@30)
                        # → Nur neue Videos müssen auf 1080p@30 kodiert werden
                        print("✅ Gecachte Videos bereits standardisiert (1080p@30)")
                        print(f"→ Kodiere nur die {len(new_videos)} neuen Video(s) auf 1080p@30")

                        # WICHTIG: needs_reencoding=True, ABER Cache NICHT leeren!
                        # Wir kodieren nur die neuen Videos, gecachte bleiben
                        needs_reencoding = True

                        # Kodiere nur neue Videos (mit speziellem Flag um Cache-Clear zu vermeiden)
                        new_encoded_paths = self._prepare_video_copies(new_videos, needs_reencoding=True, preserve_cache=True)

                        # Jetzt baue temp_copy_paths in der richtigen Reihenfolge
                        temp_copy_paths = []
                        for p in video_paths:
                            copy_path = self._find_cached_copy(p)
                            if copy_path:
                                temp_copy_paths.append(copy_path)
                            else:
                                # Sollte nicht passieren, aber zur Sicherheit
                                raise Exception(f"Video {p} nicht in Cache gefunden!")
                    else:
                        # Gecachte Videos wurden nur kopiert (Stream-Copy)
                        # → Prüfe ob neue Videos kompatibel sind
                        print(f"Prüfe ob neue(s) Video(s) kompatibel mit gecachten...")

                        # Prüfe Format: ein gecachtes + alle neuen
                        test_videos = [cached_videos[0]] + new_videos
                        format_info = self._check_video_formats(test_videos)

                        if format_info["compatible"]:
                            # Neue Videos sind kompatibel → Stream-Copy
                            print("✅ Neue Videos kompatibel → Stream-Copy")
                            needs_reencoding = False
                            new_copied_paths = self._prepare_video_copies(new_videos, needs_reencoding=False)

                            # Baue temp_copy_paths mit file-identity-basiertem Cache
                            temp_copy_paths = []
                            for p in video_paths:
                                copy_path = self._find_cached_copy(p)
                                if copy_path:
                                    temp_copy_paths.append(copy_path)
                                else:
                                    raise Exception(f"Video {p} nicht in Cache gefunden!")

                            self.parent.after(0, self._update_encoding_info, format_info)
                        else:
                            # Neue Videos nicht kompatibel → ALLE neu kodieren
                            print(f"⚠️ Format-Unterschiede: {format_info['details']}")
                            print("→ ALLE Videos werden auf 1080p@30 standardisiert")
                            needs_reencoding = True

                            # Cache leeren
                            if self.video_copies_map:
                                print("🗑️ Lösche alte Kopien...")
                                for path, copy_path in list(self.video_copies_map.items()):
                                    if os.path.exists(copy_path):
                                        try:
                                            os.remove(copy_path)
                                        except:
                                            pass
                                self.video_copies_map.clear()
                                self.metadata_cache.clear()

                            self.parent.after(0, self._update_encoding_info, format_info)
                            temp_copy_paths = self._prepare_video_copies(video_paths, needs_reencoding=True)
                            self.videos_were_reencoded = True  # Markiere als neu kodiert

                elif len(new_videos) == len(video_paths):
                    # FALL 2b: Alle Videos sind neu (erste Beladung)
                    print(f"Prüfe Format von {len(video_paths)} neuen Videos...")
                    format_info = self._check_video_formats(video_paths)

                    # NEU: Prüfe Codec-Auswahl
                    if force_codec:
                        # Spezifischer Codec wurde ausgewählt → ALLE neu kodieren
                        print(f"→ Codec '{selected_codec}' ausgewählt → ALLE Videos werden neu kodiert")
                        needs_reencoding = True
                        self.videos_were_reencoded = True
                    elif format_info["compatible"]:
                        # Alle gleich → Stream-Copy
                        print("✅ Alle Videos kompatibel → Stream-Copy")
                        needs_reencoding = False
                        self.videos_were_reencoded = False
                    else:
                        # Unterschiede → ALLE neu kodieren
                        print(f"⚠️ Format-Unterschiede: {format_info['details']}")
                        print("→ ALLE Videos werden auf 1080p@30 standardisiert")
                        needs_reencoding = True
                        self.videos_were_reencoded = True

                    self.parent.after(0, self._update_encoding_info, format_info)
                    temp_copy_paths = self._prepare_video_copies(video_paths, needs_reencoding=needs_reencoding)
                else:
                    # FALL 2c: Nur gecachte Videos (sollte nicht vorkommen, wäre FALL 1)
                    temp_copy_paths = []
                    for p in video_paths:
                        copy_path = self._find_cached_copy(p)
                        if copy_path:
                            temp_copy_paths.append(copy_path)
                        else:
                            raise Exception(f"Video {p} nicht in Cache gefunden!")
                    needs_reencoding = False

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            print(f"Starte Kombinierung von {len(temp_copy_paths)} Videos...")
            self.parent.after(0, lambda: self.status_label.config(
                text="Kombiniere Videos (schnell)...", fg="blue"))

            self.combined_video_path = self._create_fast_combined_video(temp_copy_paths)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            if self.combined_video_path and os.path.exists(self.combined_video_path):
                print(f"✅ Vorschau erfolgreich erstellt: {self.combined_video_path}")
                self.parent.after(0, self._update_ui_success, temp_copy_paths, needs_reencoding)
            else:
                if not self.cancellation_event.is_set():
                    print("❌ Vorschau konnte nicht erstellt werden")
                    self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            # Fange die Abbruch-Exception von _check_for_cancellation ab
            if "abgebrochen" in str(e) or self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
            else:
                print(f"❌ Fehler in _create_combined_preview: {e}")
                import traceback
                traceback.print_exc()
                self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")
        finally:
            if self.parent.winfo_exists():
                self.parent.after(0, self._finalize_processing)

    def _finalize_processing(self):
        """
        Cleans up after a thread finishes and triggers a pending restart if requested.
        """
        self.processing_thread = None
        self.ffmpeg_process = None

        # NEU: Stelle den Button wieder her, wenn kein Neustart ansteht
        if not self.pending_restart_callback:
            if self.app:  # Stellt den "Erstellen" Button wieder her
                self.app._restore_button_state()

        if self.pending_restart_callback:
            callback = self.pending_restart_callback
            self.pending_restart_callback = None
            callback()

    def _create_fast_combined_video(self, video_paths):
        """Kombiniert Videos schnell ohne Re-Encoding (jetzt für die Kopien verwendet)"""
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")

        os.makedirs(os.path.dirname(concat_list_path), exist_ok=True)

        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_fast.mp4")

        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video_path in video_paths:
                    # Escape Pfad für FFmpeg concat (besonders wichtig für Windows-Pfade)
                    escaped_path = os.path.abspath(video_path).replace('\\', '/')
                    f.write(f"file '{escaped_path}'\n")
        except Exception as e:
            print(f"Fehler beim Schreiben der concat-Liste: {e}")
            return None

        if self.cancellation_event.is_set():
            return None

        print(f"Kombiniere {len(video_paths)} Videos mit FFmpeg concat...")

        self.ffmpeg_process = subprocess.Popen([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
            "-c", "copy", "-movflags", "+faststart", output_path
        ], stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
            universal_newlines=True, encoding='utf-8', errors='replace',
            creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        # WICHTIG: Lese stderr um Pipe-Buffer-Overflow zu verhindern (verhindert Hängen!)
        stderr_lines = []

        while self.ffmpeg_process.poll() is None:
            if self.cancellation_event.is_set():
                print("Abbruch-Signal empfangen. Terminiere FFmpeg (concat)...")
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
                self.ffmpeg_process = None
                try:
                    os.remove(concat_list_path)
                except OSError:
                    pass
                return None

            # Lese stderr um Buffer nicht volllaufen zu lassen
            try:
                line = self.ffmpeg_process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    # Zeige Fortschritt (optional)
                    if 'time=' in line.lower():
                        # Extrahiere Zeit für Fortschrittsanzeige
                        pass
            except:
                pass

            time.sleep(0.05)  # Kürzeres Intervall für bessere Responsiveness

        # Hole restlichen stderr-Output
        try:
            remaining_stderr = self.ffmpeg_process.stderr.read()
            if remaining_stderr:
                stderr_lines.append(remaining_stderr)
        except:
            pass

        returncode = self.ffmpeg_process.returncode
        self.ffmpeg_process = None

        try:
            os.remove(concat_list_path)
        except OSError as e:
            print(f"Fehler beim Löschen der temp. Datei: {e}")

        if returncode == 0:
            print(f"✅ Kombiniertes Video erstellt: {output_path}")
            return output_path
        else:
            if not self.cancellation_event.is_set():
                # Zeige FFmpeg-Fehler
                stderr_text = ''.join(stderr_lines)
                last_lines = '\n'.join(stderr_text.split('\n')[-15:])
                print(f"❌ Fast combine fehlgeschlagen (Code {returncode}).")
                print(f"FFmpeg Output:\n{last_lines}")
            return None

    def _check_video_formats(self, video_paths):
        """Prüft ob Videos kompatible Formate haben - mit UI-Feedback und Spinner"""
        if len(video_paths) <= 1:
            return {"compatible": True, "details": "Nur ein Video - kompatibel"}

        total = len(video_paths)
        formats = []

        # NEU: Erstelle Spinner für Format-Check
        format_check_spinner = None

        def show_spinner():
            nonlocal format_check_spinner
            format_check_spinner = CircularSpinner(self.progress_frame, size=15, line_width=4, color="#007ACC")
            format_check_spinner.pack(pady=5)
            format_check_spinner.start()

        def hide_spinner():
            nonlocal format_check_spinner
            if format_check_spinner:
                format_check_spinner.stop()
                format_check_spinner.canvas.destroy()
                format_check_spinner = None

        # Zeige Spinner im Haupt-Thread
        self.parent.after(0, show_spinner)

        try:
            for i, video_path in enumerate(video_paths):
                # UI-Update: Zeige Fortschritt mit Spinner
                progress_text = f"Prüfe Format {i + 1}/{total}..."
                self.parent.after(0, lambda t=progress_text: self.status_label.config(text=t, fg="blue"))

                try:
                    self._check_for_cancellation()  # Prüfe vor jedem blockierenden Aufruf
                    result = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                             '-show_format', '-show_streams', video_path],
                                            capture_output=True, text=True, timeout=10,
                                            creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                    if result.returncode == 0:
                        info = json.loads(result.stdout)
                        video_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
                        if video_stream:
                            formats.append({'codec_name': video_stream.get('codec_name', 'unknown'),
                                            'width': video_stream.get('width', 0), 'height': video_stream.get('height', 0),
                                            'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                                            'pix_fmt': video_stream.get('pix_fmt', 'unknown')})
                        else:
                            formats.append({'error': 'No video stream'})
                    else:
                        formats.append({'error': 'FFprobe failed'})
                except Exception as e:
                    if "abgebrochen" in str(e): raise  # Abbruch weiterleiten
                    formats.append({'error': str(e)})

        finally:
            # Verstecke Spinner nach Format-Check
            self.parent.after(0, hide_spinner)

        first_format = next((f for f in formats if 'error' not in f), None)
        if not first_format: return {"compatible": False, "details": "No valid video streams found."}
        is_compatible = True
        diffs = []
        for i, fmt in enumerate(formats):
            if 'error' in fmt:
                is_compatible = False
                diffs.append(f"Video {i + 1}: {fmt['error']}")
                continue
            for key in ['codec_name', 'width', 'height', 'r_frame_rate', 'pix_fmt']:
                if fmt.get(key) != first_format.get(key):
                    is_compatible = False
                    diffs.append(f"V{i + 1} {key}")
        details = f"Alle {len(video_paths)} Videos kompatibel." if is_compatible else f"Format-Unterschiede: {', '.join(diffs[:3])}"
        return {"compatible": is_compatible, "details": details}

    def _update_encoding_info(self, format_info):
        """Aktualisiert die Encoding-Information in der UI"""
        encoder_name = self._get_current_encoder_name()

        # Hole den tatsächlichen Codec aus dem ersten Video
        codec = "unknown"
        if self.last_video_paths and len(self.last_video_paths) > 0:
            # Versuche den Codec aus der ersten gecachten Kopie zu holen
            file_identity = self._get_file_identity(self.last_video_paths[0])
            if file_identity and file_identity in self.video_copies_map:
                copy_path = self.video_copies_map[file_identity]
                codec = self._get_video_codec(copy_path)

        if format_info["compatible"]:
            self.encoding_label.config(text=f"Kompatibel | {encoder_name} | Codec: {codec.upper()}", fg="green")
        else:
            self.encoding_label.config(text=f"Standardisiert | {encoder_name} | Codec: {codec.upper()}", fg="orange")

    def _update_ui_success(self, copy_paths, was_reencoded):
        """
        Aktualisiert UI nach erfolgreicher Vorschau-Erstellung.
        """
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)

        # Metadaten von den *Kopien* berechnen (jetzt aus dem Cache)
        total_duration_s = 0
        total_bytes = 0

        # Gehe über die *Originalpfade*, um den Cache zu lesen
        for original_path in self.last_video_paths:
            # BUGFIX: Verwende file_identity als Cache-Key, nicht den Pfad direkt
            file_identity = self._get_file_identity(original_path)
            if file_identity:
                metadata = self.metadata_cache.get(file_identity)
                if metadata:
                    try:
                        total_duration_s += float(metadata.get("duration_sec_str", "0.0"))
                        total_bytes += metadata.get("size_bytes", 0)
                    except Exception:
                        pass  # Ignoriere fehlerhafte Cache-Einträge

        minutes, seconds = divmod(total_duration_s, 60)
        total_duration = f"{int(minutes):02d}:{int(seconds):02d}"
        total_size = self._format_size_bytes(total_bytes)

        self.duration_label.config(text=total_duration)
        self.size_label.config(text=total_size)
        self.clips_label.config(text=str(len(copy_paths)))

        # Hole Encoder-Namen
        encoder_name = self._get_current_encoder_name()

        # Hole den tatsächlichen Codec aus dem kombinierten Video oder der ersten Kopie
        codec = "unknown"
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            codec = self._get_video_codec(self.combined_video_path)
        elif copy_paths and len(copy_paths) > 0:
            codec = self._get_video_codec(copy_paths[0])

        if was_reencoded:
            self.status_label.config(text="Vorschau bereit (standardisiert)", fg="green")
            self.encoding_label.config(text=f"Standardisiert | {encoder_name} | Codec: {codec.upper()}", fg="orange")
        else:
            self.status_label.config(text="Vorschau bereit (schnell)", fg="green")
            self.encoding_label.config(text=f"Direkt kombiniert | {encoder_name} | Codec: {codec.upper()}", fg="green")

        # self.play_button.config(state="normal")  # ENTFERNT
        # self.action_button.config(state="disabled")  # ENTFERNT

        clip_durations = self._get_clip_durations_seconds(copy_paths)
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.load_video(self.combined_video_path, clip_durations)

        # NEU: Entsperren Sie den Schneiden-Button, wenn Vorschau bereit ist
        if self.app and hasattr(self.app, 'drag_drop'):
            self.app.drag_drop.set_cut_button_enabled(True)

        # NEU: Aktualisiere Thumbnails und Info
        self.video_paths = copy_paths
        self.clip_durations = clip_durations
        self.current_active_clip = 0
        self._update_thumbnails()
        self._update_info()
        self._update_button_states()

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text=error_msg, fg="red")
        self.clear_preview_info()
        # self.play_button.config(state="disabled")  # ENTFERNT
        # self.action_button.config(text="🔄 Erneut versuchen",  # ENTFERNT
        #                           command=self.retry_creation,
        #                           state="normal")
        self.combined_video_path = None

        # WICHTIG: Lösche temp_dir NUR wenn kein Neustart geplant ist!
        if not self.pending_restart_callback:
            self._cleanup_temp_copies()
        else:
            print("♻️ Behalte temp_dir trotz Fehler für Neustart")

    def register_new_copy(self, original_placeholder: str, new_copy_path: str):
        """
        Fügt ein neues Mapping für eine geteilte Datei hinzu.
        Verwendet file-identity (Name + Größe) als Cache-Key.
        """
        file_identity = self._get_file_identity(original_placeholder)
        if not file_identity:
            print(f"⚠️ Kann neue Kopie nicht registrieren: File-Identity konnte nicht erstellt werden für {original_placeholder}")
            return

        if file_identity in self.video_copies_map:
            print(f"Warnung: File-Identity {file_identity} existierte bereits. Wird überschrieben.")

        self.video_copies_map[file_identity] = new_copy_path
        print(f"Neue Kopie registriert: {original_placeholder} -> {new_copy_path}")

    def regenerate_preview_after_cut(self, new_original_paths_list):
        """
        Startet eine Aktualisierung der kombinierten Vorschau, nachdem eine
        Kopie extern (z.B. durch den Cutter) geändert wurde.
        """
        print(
            f"Regeneriere Vorschau. Alte Originale: {len(self.last_video_paths) if self.last_video_paths else 0}, Neue Originale: {len(new_original_paths_list)}")

        if self.processing_thread and self.processing_thread.is_alive():
            print("Regenerierung zurückgestellt, da ein anderer Prozess läuft.")
            self.pending_restart_callback = lambda: self.regenerate_preview_after_cut(new_original_paths_list)
            self.cancel_creation()
            return

        self.last_video_paths = new_original_paths_list

        copy_paths = self.get_all_copy_paths()

        if not copy_paths:
            print("Keine Kopien zum Regenerieren gefunden.")
            self.clear_preview()
            return

        self.cancellation_event.clear()
        self.processing_thread = threading.Thread(target=self._regenerate_task, args=(copy_paths,))
        self.processing_thread.start()

    def _regenerate_task(self, copy_paths):
        """Thread-Funktion, die nur das Kombinieren der (bereits vorhandenen) Kopien durchführt."""

        self.parent.after(0, lambda: self.status_label.config(text="Aktualisiere Vorschau nach Schnitt...", fg="blue"))
        # self.parent.after(0,  # ENTFERNT
        #                   lambda: self.action_button.config(text="⏹ Erstellung abbrechen", command=self.cancel_creation,
        #                                                     state="normal"))

        try:
            new_combined_path = self._create_fast_combined_video(copy_paths)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            if new_combined_path and os.path.exists(new_combined_path):
                self.combined_video_path = new_combined_path
                self.parent.after(0, self._update_ui_success_after_cut, copy_paths)
            else:
                if not self.cancellation_event.is_set():
                    self.parent.after(0, self._update_ui_error, "Vorschau-Aktualisierung fehlgeschlagen")

        except Exception as e:
            if not self.cancellation_event.is_set():
                print(f"Fehler in _regenerate_task: {e}")
                self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")
            else:
                self.parent.after(0, self._update_ui_cancelled)
        finally:
            if self.parent.winfo_exists():
                self.parent.after(0, self._finalize_processing)

    def _update_ui_success_after_cut(self, copy_paths):
        """Aktualisiert die UI nach einer erfolgreichen *Regenerierung* (Schnitt)."""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)

        # Metadaten von den (möglicherweise geschnittenen) Kopien berechnen (aus Cache)
        total_duration_s = 0
        total_bytes = 0

        for original_path in self.last_video_paths: # self.last_video_paths wurde aktualisiert
            # BUGFIX: Verwende file_identity als Cache-Key, nicht den Pfad direkt
            file_identity = self._get_file_identity(original_path)
            if file_identity:
                metadata = self.metadata_cache.get(file_identity)
                if metadata:
                    try:
                        total_duration_s += float(metadata.get("duration_sec_str", "0.0"))
                        total_bytes += metadata.get("size_bytes", 0)
                    except Exception:
                        pass

        minutes, seconds = divmod(total_duration_s, 60)
        total_duration = f"{int(minutes):02d}:{int(seconds):02d}"
        total_size = self._format_size_bytes(total_bytes)

        self.duration_label.config(text=total_duration)
        self.size_label.config(text=total_size)
        self.clips_label.config(text=str(len(self.last_video_paths)))

        self.status_label.config(text="Vorschau nach Schnitt aktualisiert", fg="green")
        # self.play_button.config(state="normal")  # ENTFERNT
        # self.action_button.config(state="disabled")  # ENTFERNT

        # NEU: Video-Player aktualisieren
        clip_durations = self._get_clip_durations_seconds(copy_paths)
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.load_video(self.combined_video_path, clip_durations)

        # NEU: Aktualisiere Thumbnails und Info
        self.video_paths = copy_paths
        self.clip_durations = clip_durations
        self.current_active_clip = 0
        self._update_thumbnails()
        self._update_info()
        self._update_button_states()

    def _get_single_video_duration_str(self, video_path):
        """Hilfsmethode: Holt die Dauer EINES Videos als String in Sekunden (z.B. '12.34'). (Blockierend)"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return "0.0"

    def _calculate_total_duration(self, video_paths):
        """Veraltet - wird nicht mehr verwendet, da _update_ui_success jetzt Cache nutzt"""
        # Diese Methode wird nicht mehr verwendet
        # Der Cache wird in _update_ui_success verwendet
        pass

    def _calculate_total_size(self, video_paths):
        """Veraltet (wird nicht mehr verwendet, da _update_ui_success jetzt Cache nutzt), aber als Fallback behalten"""
        total_bytes = sum(os.path.getsize(p) for p in video_paths if os.path.exists(p))
        return self._format_size_bytes(total_bytes)

    def _format_size_bytes(self, total_bytes):
        """Formatiert Bytes in einen lesbaren String."""
        if total_bytes == 0: return "0 KB"
        if total_bytes > 1024 ** 3: return f"{total_bytes / (1024 ** 3):.1f} GB"
        if total_bytes > 1024 ** 2: return f"{total_bytes / (1024 ** 2):.1f} MB"
        return f"{total_bytes / 1024:.1f} KB"

    def play_preview(self):
        """Startet die Vorschau-Wiedergabe"""
        if not self.combined_video_path or not os.path.exists(self.combined_video_path):
            self.status_label.config(text="Vorschau-Datei nicht gefunden", fg="red")
            return

        self.status_label.config(text="Starte externen Videoplayer...", fg="blue")
        try:
            if sys.platform == "win32":
                os.startfile(self.combined_video_path)
            elif sys.platform == "darwin":
                subprocess.run(['open', self.combined_video_path],
                               check=True,
                               creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            else:
                subprocess.run(['xdg-open', self.combined_video_path],
                               check=True,
                               creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except Exception as e:
            self.status_label.config(text=f"Player konnte nicht gestartet werden: {e}", fg="red")

        self.parent.after(2000, self._reset_play_state)

    def _reset_play_state(self):
        """Setzt den Wiedergabe-Status zurück."""
        if not self.parent.winfo_exists(): return
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            self.status_label.config(text="Vorschau bereit", fg="green")

    def _update_ui_cancelled(self, event=None):
        """Updates UI after creation was cancelled."""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text="Vorschau-Erstellung abgebrochen", fg="orange")
        self.clear_preview_info()
        # self.play_button.config(state="disabled")  # ENTFERNT
        # self.action_button.config(text="🔄 Erneut versuchen",  # ENTFERNT
        #                           command=self.retry_creation,
        #                           state="normal")
        self.combined_video_path = None

        # WICHTIG: Lösche temp_dir NUR wenn kein Neustart geplant ist!
        # Bei Neustart (neue Videos hinzufügen) wollen wir bereits kodierte Videos behalten
        if not self.pending_restart_callback:
            self._cleanup_temp_copies()
        else:
            print("♻️ Behalte temp_dir für Neustart (bereits kodierte Videos bleiben erhalten)")

    def cancel_creation(self):
        """Signals the processing thread to cancel the video creation."""
        if self.processing_thread and self.processing_thread.is_alive():
            self.status_label.config(text="Abbruch wird eingeleitet...", fg="orange")
            # self.action_button.config(state="disabled")  # ENTFERNT
            self.cancellation_event.set()

    def retry_creation(self):
        """Retries the preview creation with the last used *original* video paths."""
        if not self.last_video_paths:
            print("No previous video paths available to retry.")
            return
        self.update_preview(self.last_video_paths)

    def clear_preview(self):
        """Setzt die Vorschau zurück und löscht die temporäre Datei"""
        self.pending_restart_callback = None
        self.cancel_creation()

        # NEU: Stelle Normal-Modus in DragDrop-Tabelle wieder her
        if self.app and hasattr(self.app, 'drag_drop'):
            self.app.drag_drop.show_normal_mode()

        # KORREKTUR: Zuerst Player entladen, um WinError 32 zu vermeiden
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.unload_video()

        # Erst DANACH die kombinierten Dateien löschen
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            try:
                os.remove(self.combined_video_path)
            except OSError as e:
                print(f"Could not delete temp preview file: {e}")

        # Und die restlichen Kopien
        self._cleanup_temp_copies()  # Löscht temp_dir, video_copies_map und metadata_cache

        self.combined_video_path = None
        self.last_video_paths = None
        self.clear_preview_info()
        self.status_label.config(text="Keine Vorschau verfügbar", fg="gray")
        # self.play_button.config(state="disabled")  # ENTFERNT
        # self.action_button.config(text="⏹ Erstellung abbrechen",  # ENTFERNT
        #                           command=self.cancel_creation,
        #                           state="disabled")

        # NEU: Thumbnails und Info zurücksetzen
        self.video_paths = []
        self.clip_durations = []
        self.current_active_clip = 0
        self._update_thumbnails()
        self._update_info()
        self._update_button_states()

    def clear_preview_info(self):
        """Helper to clear all text labels."""
        self.duration_label.config(text="00:00")
        self.size_label.config(text="--")
        self.clips_label.config(text="0")
        self.encoding_label.config(text="--", fg="gray")

    def get_combined_video_path(self):
        """Gibt den Pfad des kombinierten Videos zurück"""
        return self.combined_video_path

    def update_encoding_progress(self, progress, fps=None, eta=None):
        """
        Aktualisiert die Encoding-Fortschrittsanzeige in der Video-Preview.

        Args:
            progress: Fortschritt in Prozent (0-100)
            fps: Optional FPS-Wert
            eta: Optional ETA-String
        """
        # Update Encoding-Label mit Fortschrittsanzeige
        if progress is not None:
            status_text = f"Encoding: {int(progress)}%"
            if fps and fps > 0:
                status_text += f" ({fps:.1f} fps)"
            if eta:
                status_text += f" - {eta}"

            self.encoding_label.config(text=status_text, fg="#2196F3")  # Blau während Encoding

        self.parent.update_idletasks()

    # --- NEUE METHODEN (Cache-Verwaltung) ---

    def _cache_metadata_for_copy(self, original_path: str, copy_path: str):
        """
        [THREAD-SAFE] Liest Metadaten von der Kopie und speichert sie im Cache.
        Verwendet file-identity (Name + Größe) als Cache-Key.
        """
        if not os.path.exists(copy_path):
            print(f"Kann Metadaten nicht cachen: Kopie {copy_path} existiert nicht.")
            return

        file_identity = self._get_file_identity(original_path)
        if not file_identity:
            print(f"Kann Metadaten nicht cachen: File-Identity konnte nicht erstellt werden für {original_path}")
            return

        try:
            # Hole Dauer als String 'MM:SS'
            duration_str = self._get_video_duration(copy_path)
            # Hole Dauer als String 'Sekunden.ms'
            duration_sec_str = self._get_single_video_duration_str(copy_path)
            # Hole Größe
            size_bytes = os.path.getsize(copy_path)
            size_str = self._format_size_bytes(size_bytes)
            # Hole Datum/Zeit
            date_str = self._get_file_date(copy_path)
            time_str = self._get_file_time(copy_path)
            # Hole Format (Auflösung und FPS)
            format_str = self._get_video_format(copy_path)
            # NEU: Hole auch width und height separat
            width, height = self._get_video_resolution(copy_path)

            self.metadata_cache[file_identity] = {
                "duration": duration_str,
                "duration_sec_str": duration_sec_str,
                "size": size_str,
                "size_bytes": size_bytes,
                "date": date_str,
                "timestamp": time_str,
                "format": format_str,
                "width": width,
                "height": height
            }

            # NEU: Aktualisiere die Tabelle im Haupt-Thread, wenn Metadaten hinzugefügt werden
            if self.app and hasattr(self.app, 'drag_drop'):
                self.parent.after(0, self.app.drag_drop._update_video_table)

        except Exception as e:
            print(f"Fehler beim Cachen der Metadaten für {original_path}: {e}")
            self.metadata_cache[file_identity] = {
                "duration": "FEHLER", "size": "FEHLER", "date": "FEHLER", "timestamp": "FEHLER", "format": "FEHLER",
                "width": 0, "height": 0
            }

    def refresh_metadata_async(self, original_paths_list: List[str], on_complete_callback: Callable):
        """
        Startet einen Thread, um die Metadaten für bestimmte Clips
        (z.B. nach einem Schnitt) neu zu berechnen und zu cachen.
        """
        print(f"App: Starte asynchrone Metadaten-Aktualisierung für {len(original_paths_list)} Clip(s)...")
        threading.Thread(
            target=self._run_refresh_metadata_task,
            args=(original_paths_list, on_complete_callback),
            daemon=True
        ).start()

    def _run_refresh_metadata_task(self, original_paths_list: List[str], on_complete_callback: Callable):
        """
        [THREAD] Berechnet Metadaten neu und ruft den Callback auf.
        """
        for original_path in original_paths_list:
            copy_path = self.get_copy_path(original_path)
            if copy_path:
                print(f"Task: Aktualisiere Metadaten für {os.path.basename(original_path)}...")
                self._cache_metadata_for_copy(original_path, copy_path)
            else:
                print(f"Task: Überspringe Metadaten-Aktualisierung, keine Kopie für {original_path} gefunden.")

        # Rufe den Callback im Haupt-Thread auf
        self.parent.after(0, on_complete_callback)

    def get_copy_path(self, original_path):
        """Gibt den Pfad der temporären Kopie für einen Originalpfad zurück (basierend auf file-identity)."""
        return self._find_cached_copy(original_path)

    def get_cached_metadata(self, original_path: str) -> Dict:
        """Gibt das gecachte Metadaten-Wörterbuch für einen Originalpfad zurück (basierend auf file-identity)."""
        file_identity = self._get_file_identity(original_path)
        if file_identity:
            return self.metadata_cache.get(file_identity)
        return None

    def clear_metadata_cache(self):
        """Leert den Metadaten-Cache (z.B. wenn alle Videos entfernt werden)."""
        self.metadata_cache.clear()

    def remove_path_from_cache(self, original_path: str):
        """Entfernt einen bestimmten Pfad aus Cache und Map (basierend auf file-identity)."""
        file_identity = self._get_file_identity(original_path)
        if file_identity:
            if file_identity in self.video_copies_map:
                del self.video_copies_map[file_identity]
            if file_identity in self.metadata_cache:
                del self.metadata_cache[file_identity]

    def get_all_copy_paths(self):
        """
        Gibt eine Liste aller temporären Kopie-Pfade zurück,
        basierend auf der *aktuellen* self.last_video_paths-Liste.
        """
        if not self.last_video_paths:
            return []

        paths = [self._find_cached_copy(orig_path) for orig_path in self.last_video_paths]
        return [p for p in paths if p and os.path.exists(p)]

    # --- Interne Metadaten-Helfer (laufen im Thread oder als Fallback) ---

    def _get_video_duration(self, video_path):
        """Ermittelt die Dauer des Videos (Blockierend)"""
        try:
            duration_str = self._get_single_video_duration_str(video_path)
            seconds = float(duration_str)
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}:{secs:02d}"
        except:
            return "?:??"

    def _get_file_size(self, file_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(file_path)
            return self._format_size_bytes(size_bytes)
        except:
            return "Unbekannt"

    def _get_file_date(self, video_path):
        """Ermittelt das Erstellungsdatum der Datei"""
        try:
            modification_time = os.path.getmtime(video_path)
            return time.strftime("%d.%m.%Y", time.localtime(modification_time))
        except:
            return "Unbekannt"

    def _get_file_time(self, video_path):
        """Ermittelt die Erstellungsuhrzeit der Datei"""
        try:
            modification_time = os.path.getmtime(video_path)
            return time.strftime("%H:%M:%S", time.localtime(modification_time))
        except:
            return "Unbekannt"

    def _get_video_format(self, video_path):
        """Ermittelt das Video-Format (Auflösung und FPS)"""
        try:
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

    def _get_video_resolution(self, video_path):
        """Ermittelt die Video-Auflösung (Breite, Höhe)"""
        try:
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
                    return width, height

            return 0, 0
        except:
            return 0, 0

    # --- THUMBNAIL-FUNKTIONALITÄT ---

    def _on_filename_hover_enter(self, event):
        """Zeigt Tooltip mit vollständigem Dateinamen beim Hover"""
        widget = event.widget
        full_text = widget.cget("text")

        # Zeige Tooltip nur wenn Text abgekürzt ist (enthält ...)
        if "..." in full_text or len(full_text) > 30:
            # Hole vollständigen Dateinamen aus video_paths
            if self.video_paths and self.current_active_clip < len(self.video_paths):
                full_filename = os.path.basename(self.video_paths[self.current_active_clip])

                # Erstelle Tooltip
                x = widget.winfo_rootx() + 10
                y = widget.winfo_rooty() + 25

                self.filename_tooltip = tk.Toplevel(widget)
                self.filename_tooltip.wm_overrideredirect(True)
                self.filename_tooltip.wm_geometry(f"+{x}+{y}")

                label = tk.Label(
                    self.filename_tooltip,
                    text=full_filename,
                    background="#ffffe0",
                    relief="solid",
                    borderwidth=1,
                    font=("Arial", 8),
                    padx=5,
                    pady=3
                )
                label.pack()

    def _on_filename_hover_leave(self, event):
        """Entfernt Tooltip beim Verlassen"""
        if self.filename_tooltip:
            self.filename_tooltip.destroy()
            self.filename_tooltip = None

    def _truncate_filename(self, filename, max_chars=30):
        """Kürzt Dateinamen wenn zu lang"""
        if len(filename) <= max_chars:
            return filename

        # Behalte Dateiendung
        name, ext = os.path.splitext(filename)
        if len(ext) > 10:  # Falls Endung sehr lang
            ext = ext[:10]

        # Berechne verfügbare Zeichen für Namen
        available = max_chars - len(ext) - 3  # 3 für "..."
        if available < 5:
            return filename[:max_chars-3] + "..."

        return name[:available] + "..." + ext

    # --- THUMBNAIL-FUNKTIONALITÄT ---

    def _create_video_thumbnail(self, video_path, clip_index, is_active=False):
        """
        Erstellt ein Thumbnail vom ersten Frame eines Video-Clips.

        Args:
            video_path: Pfad zum Video
            clip_index: Index des Clips
            is_active: Ob dieser Clip gerade aktiv ist (größeres Thumbnail)

        Returns:
            ImageTk.PhotoImage oder None
        """
        cache_key = (clip_index, is_active)
        if cache_key in self.thumbnail_images:
            return self.thumbnail_images[cache_key]

        try:
            # Temporäre Datei für Frame-Extraktion
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                tmp_path = tmp.name

            # FFmpeg-Befehl: Erstes Frame extrahieren
            cmd = [
                'ffmpeg',
                '-i', video_path,
                '-vframes', '1',  # Nur 1 Frame
                '-vf', f'scale={self.thumbnail_size * 2}:-1',  # Höhere Auflösung für bessere Qualität
                '-y',  # Überschreiben
                tmp_path
            ]

            # Führe FFmpeg aus (versteckt)
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW,
                timeout=5
            )

            # Lade Bild und erstelle Thumbnail
            img = Image.open(tmp_path)
            size = int(self.thumbnail_size * 1.3) if is_active else self.thumbnail_size
            # Versuche neuere PIL-Version, fallback auf ältere
            try:
                img.thumbnail((size, size), Image.Resampling.LANCZOS)
            except AttributeError:
                img.thumbnail((size, size), Image.LANCZOS)
            thumbnail = ImageTk.PhotoImage(img)

            # Cache speichern
            self.thumbnail_images[cache_key] = thumbnail

            # Temporäre Datei löschen
            try:
                os.remove(tmp_path)
            except:
                pass

            return thumbnail

        except Exception as e:
            print(f"Fehler beim Erstellen des Video-Thumbnails für {video_path}: {e}")
            return None

    def _update_thumbnails(self):
        """Aktualisiert die Thumbnail-Galerie"""
        # Alte Thumbnails entfernen
        for widget in self.thumbnail_inner_frame.winfo_children():
            widget.destroy()

        if not self.video_paths:
            self.thumbnail_canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        # Neue Thumbnails erstellen
        for idx, video_path in enumerate(self.video_paths):
            is_active = idx == self.current_active_clip

            thumbnail = self._create_video_thumbnail(video_path, idx, is_active=is_active)
            if thumbnail:
                # Frame mit Rahmen
                border_color = "#0078d4" if is_active else "#999999"
                border_width = 3 if is_active else 2

                thumb_frame = tk.Frame(
                    self.thumbnail_inner_frame,
                    bg="white",
                    highlightthickness=border_width,
                    highlightbackground=border_color
                )
                thumb_frame.pack(side="left", padx=5, pady=5)

                # Label mit Thumbnail
                thumb_label = tk.Label(thumb_frame, image=thumbnail, bg="white")
                thumb_label.image = thumbnail  # Referenz behalten
                thumb_label.pack()

                # Click-Event
                thumb_label.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click(e, i))
                thumb_frame.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click(e, i))

        # Canvas-Scroll-Region aktualisieren
        self.thumbnail_inner_frame.update_idletasks()
        bbox = self.thumbnail_canvas.bbox("all")
        if bbox:
            self.thumbnail_canvas.configure(scrollregion=bbox)

        # Scrolle zum aktiven Thumbnail
        self._scroll_to_active_thumbnail()

    def _on_thumbnail_drag_start(self, event):
        """Startet das Drag-Scrolling"""
        self.drag_start_x = event.x
        self.is_dragging = False
        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if scroll_region:
            current_view = self.thumbnail_canvas.xview()
            self.drag_start_scroll = current_view[0]

    def _on_thumbnail_drag_motion(self, event):
        """Führt das Drag-Scrolling durch"""
        if abs(event.x - self.drag_start_x) > 5:
            self.is_dragging = True

        if not self.is_dragging:
            return

        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if not scroll_region or scroll_region == "0 0 0 0":
            return

        delta_x = self.drag_start_x - event.x
        canvas_width = self.thumbnail_canvas.winfo_width()
        scroll_parts = scroll_region.split()
        total_width = float(scroll_parts[2]) if len(scroll_parts) > 2 else canvas_width

        if total_width > canvas_width:
            scroll_delta = delta_x / total_width
            new_scroll = self.drag_start_scroll + scroll_delta
            new_scroll = max(0.0, min(1.0, new_scroll))
            self.thumbnail_canvas.xview_moveto(new_scroll)

    def _on_thumbnail_drag_end(self, event):
        """Beendet das Drag-Scrolling"""
        self.frame.after(50, lambda: setattr(self, 'is_dragging', False))

    def _on_thumbnail_mousewheel(self, event):
        """Scrolling mit Mausrad"""
        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if scroll_region and scroll_region != "0 0 0 0":
            delta = -1 if event.delta > 0 else 1
            self.thumbnail_canvas.xview_scroll(delta, "units")

    def _scroll_to_active_thumbnail(self):
        """Scrollt die Thumbnail-Leiste so, dass das aktive Thumbnail sichtbar ist"""
        if not self.video_paths or self.current_active_clip < 0:
            return

        self.thumbnail_inner_frame.update_idletasks()
        children = self.thumbnail_inner_frame.winfo_children()

        if self.current_active_clip >= len(children):
            return

        active_frame = children[self.current_active_clip]
        thumb_x = active_frame.winfo_x()
        thumb_width = active_frame.winfo_width()
        thumb_right = thumb_x + thumb_width

        canvas_width = self.thumbnail_canvas.winfo_width()
        scroll_region = self.thumbnail_canvas.cget("scrollregion")

        if not scroll_region or scroll_region == "0 0 0 0":
            return

        parts = scroll_region.split()
        total_width = float(parts[2]) if len(parts) > 2 else canvas_width

        if total_width <= canvas_width:
            return

        current_view = self.thumbnail_canvas.xview()
        view_start = current_view[0]
        view_end = current_view[1]

        visible_start = view_start * total_width
        visible_end = view_end * total_width
        margin = 60

        if thumb_x < visible_start + margin:
            new_view_start = max(0.0, (thumb_x - margin) / total_width)
            self.thumbnail_canvas.xview_moveto(new_view_start)
        elif thumb_right > visible_end - margin:
            new_view_start = min(1.0, (thumb_right + margin - canvas_width) / total_width)
            self.thumbnail_canvas.xview_moveto(new_view_start)

    def _on_thumbnail_click(self, event, clip_index):
        """
        Behandelt Klick auf ein Thumbnail - nur wenn kein Drag

        Args:
            event: Click-Event
            clip_index: Index des geklickten Clips
        """
        if self.is_dragging:
            return

        # Berechne Startzeit des Clips
        clip_start_time_ms = self._calculate_clip_start_time(clip_index)

        # Springe im VideoPlayer zur Position
        if self.app and hasattr(self.app, 'video_player'):
            player = self.app.video_player
            if player and player.media_player:
                player.media_player.set_time(clip_start_time_ms)
                # Aktualisiere sofort die UI
                player._update_progress_ui()

        # Update aktiven Clip
        self.current_active_clip = clip_index
        self._update_thumbnails()
        self._update_info()

    def _calculate_clip_start_time(self, clip_index):
        """
        Berechnet die Startzeit eines Clips in Millisekunden

        Args:
            clip_index: Index des Clips

        Returns:
            Startzeit in Millisekunden
        """
        if clip_index < 0 or not self.clip_durations:
            return 0

        start_time_sec = sum(self.clip_durations[:clip_index])
        return int(start_time_sec * 1000)

    def set_active_clip_by_time(self, current_time_ms):
        """
        Setzt den aktiven Clip basierend auf der aktuellen Playback-Zeit.
        Wird von VideoPlayer aufgerufen.

        Args:
            current_time_ms: Aktuelle Wiedergabezeit in Millisekunden
        """
        if not self.clip_durations:
            return

        # Berechne welcher Clip gerade aktiv ist
        current_time_sec = current_time_ms / 1000.0
        accumulated_time = 0.0
        new_active_clip = 0

        for idx, duration in enumerate(self.clip_durations):
            if current_time_sec < accumulated_time + duration:
                new_active_clip = idx
                break
            accumulated_time += duration
        else:
            # Falls Zeit über alle Clips hinausgeht, letzter Clip ist aktiv
            new_active_clip = len(self.clip_durations) - 1

        # Nur aktualisieren wenn sich der aktive Clip geändert hat
        if new_active_clip != self.current_active_clip:
            self.current_active_clip = new_active_clip
            self._update_thumbnails()
            self._update_info()
            # NEU: WM-Button Status aktualisieren
            self.update_wm_button_state()

    def _update_info(self):
        """Aktualisiert die Clip-Informationen"""
        if not self.video_paths or self.current_active_clip < 0:
            for key in ["filename", "resolution", "duration", "size"]:
                if key in self.info_labels:
                    self.info_labels[key].config(text="-")
            self.info_labels["total_count"].config(text="0")
            self.info_labels["total_duration"].config(text="00:00")
            return

        # Aktueller Clip
        if self.current_active_clip >= len(self.video_paths):
            return

        video_path = self.video_paths[self.current_active_clip]

        try:
            # Dateiname (mit Kürzung)
            filename = os.path.basename(video_path)
            truncated_filename = self._truncate_filename(filename, max_chars=30)
            self.info_labels["filename"].config(text=truncated_filename)

            # Hole Metadaten aus Cache (bereits von update_preview geladen)
            # Suche die file-identity aus der Kopie (umgekehrter Lookup im Cache)
            file_identity = next((key for key, value in self.video_copies_map.items() if value == video_path), None)
            metadata = {}
            if file_identity:
                metadata = self.metadata_cache.get(file_identity, {})

            # Auflösung
            width = metadata.get('width', 0)
            height = metadata.get('height', 0)
            if width and height:
                self.info_labels["resolution"].config(text=f"{width} × {height} px")
            else:
                self.info_labels["resolution"].config(text="-")

            # Dauer
            if self.current_active_clip < len(self.clip_durations):
                duration_sec = self.clip_durations[self.current_active_clip]
                minutes = int(duration_sec // 60)
                seconds = int(duration_sec % 60)
                self.info_labels["duration"].config(text=f"{minutes:02d}:{seconds:02d}")
            else:
                self.info_labels["duration"].config(text="-")

            # Dateigröße
            if os.path.exists(video_path):
                size_bytes = os.path.getsize(video_path)
                size_mb = size_bytes / (1024 * 1024)
                self.info_labels["size"].config(text=f"{size_mb:.2f} MB")
            else:
                self.info_labels["size"].config(text="-")

        except Exception as e:
            print(f"Fehler beim Abrufen der Clip-Informationen: {e}")

        # Gesamt-Statistiken
        total_count = len(self.video_paths)
        self.info_labels["total_count"].config(text=str(total_count))

        total_duration_sec = sum(self.clip_durations) if self.clip_durations else 0
        total_minutes = int(total_duration_sec // 60)
        total_seconds = int(total_duration_sec % 60)
        self.info_labels["total_duration"].config(text=f"{total_minutes:02d}:{total_seconds:02d}")

        # NEU: WM-Button Status aktualisieren
        self.update_wm_button_state()

    def _delete_selected_clip(self):
        """Löscht den aktuell ausgewählten Clip"""
        if self.current_active_clip < 0 or self.current_active_clip >= len(self.video_paths):
            return

        # Bestätigung
        clip_name = os.path.basename(self.video_paths[self.current_active_clip])
        if not messagebox.askyesno("Clip löschen", f"Clip '{clip_name}' wirklich löschen?"):
            return

        # Entferne aus drag_drop
        if self.app and hasattr(self.app, 'drag_drop'):
            # Finde den Original-Pfad aus last_video_paths
            if self.last_video_paths and self.current_active_clip < len(self.last_video_paths):
                deleted_path = self.last_video_paths[self.current_active_clip]
                self.app.drag_drop.remove_video(deleted_path, update_preview=True)

    def _clear_selection(self):
        """Hebt Auswahl auf (für Mehrfachauswahl-Kompatibilität)"""
        # Aktuell keine Mehrfachauswahl - könnte später erweitert werden
        pass

    def _scan_current_clip_qr(self):
        """Scannt den aktuellen Clip nach QR-Code"""
        if self.current_active_clip < 0 or self.current_active_clip >= len(self.video_paths):
            return

        # Finde den Original-Pfad aus last_video_paths
        if self.last_video_paths and self.current_active_clip < len(self.last_video_paths):
            video_path = self.last_video_paths[self.current_active_clip]

            if self.app and hasattr(self.app, 'run_qr_analysis'):
                self.app.run_qr_analysis([video_path])

    def _update_button_states(self):
        """Aktualisiert den Status aller Buttons"""
        has_clips = bool(self.video_paths)

        if has_clips:
            self.delete_button.config(state="normal")
            self.qr_scan_button.config(state="normal")
            self.wm_button.config(state="normal")  # NEU
        else:
            self.delete_button.config(state="disabled")
            self.qr_scan_button.config(state="disabled")
            self.wm_button.config(state="disabled")  # NEU

        # Clear-Selection immer disabled (keine Mehrfachauswahl aktuell)
        self.clear_selection_button.config(state="disabled")

    # --- NEU: WASSERZEICHEN-METHODEN ---

    def _on_wm_button_click(self):
        """
        Wird aufgerufen, wenn der Wasserzeichen-Button geklickt wird.
        Leitet die Aktion an app.py weiter.
        """
        if self.app and hasattr(self.app, 'toggle_video_watermark') and self.current_active_clip is not None:
            if 0 <= self.current_active_clip < len(self.video_paths):
                self.app.toggle_video_watermark(self.current_active_clip)

    def set_wm_button_visibility(self, visible: bool):
        """Zeigt oder verbirgt den Wasserzeichen-Button (gesteuert von app.py)."""
        if visible:
            self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        else:
            self.wm_button.grid_remove()

    def update_wm_button_state(self):
        """
        Aktualisiert Text und Farbe des WM-Buttons basierend auf dem Status
        in drag_drop.py.
        """
        if not self.app or not hasattr(self.app, 'drag_drop') or self.current_active_clip < 0:
            self.wm_button.config(text="💧", state="disabled", bg="#f0f0f0")
            return

        # Lese den Status direkt von drag_drop (via app)
        is_marked = self.app.drag_drop.is_video_watermarked(self.current_active_clip)

        if is_marked:
            self.wm_button.config(text="💧", state="normal", bg="#D32F2F", fg="white")
        else:
            self.wm_button.config(text="💧", state="normal", bg="#FF9800", fg="black")

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

