import tkinter as tk
from tkinter import messagebox, ttk
import math
import threading
import os
import queue
import time
from typing import List, Literal, Optional, Dict, Any
from tkinterdnd2 import TkinterDnD
from datetime import datetime

from .pending_video_cut import PendingVideoCut
from ..video.cutter_service import VideoCutterService
from ..model.kunde import Kunde

from ..utils.config import ConfigManager
from ..utils.validation import validate_form_data
from ..utils.natural_sort import sort_paths_by_basename
from ..utils.dji_media_paths import collect_media_from_backup_folder
from ..installer.ffmpeg_installer import ensure_ffmpeg_installed
from ..utils.file_utils import test_server_connection
from ..installer.updater import initialize_updater
from ..utils.constants import APP_VERSION


def _truthy_session_keep_flag(value) -> bool:
    """Konfigurationswert für „beim Zurücksetzen beibehalten“ zuverlässig als bool auswerten."""
    if value is True or value == 1:
        return True
    if value is False or value is None or value == 0:
        return False
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "ja")
    return False


class VideoGeneratorApp:

    def __init__(self, root=None, splash_callback=None):
        """
        Args:
            root: Optionales bestehendes TkinterDnD.Tk() Fenster.
                  Wenn None, wird ein neues erstellt.
            splash_callback: Optional - Callback für Splash-Screen Status-Updates
        """
        # Verwende übergebenes Root oder erstelle neues
        self.root = root if root is not None else TkinterDnD.Tk()
        self.splash_callback = splash_callback
        self.config = ConfigManager()
        self.video_processor = None
        self.erstellen_button = None
        self.combined_video_path = None
        self.server_status_label = None
        self.server_connected = False
        self.video_player = None
        self.video_cutter_dialog = None  # NEU: Referenz auf offenen Dialog
        self.pending_video_cuts: List[PendingVideoCut] = []
        self._pending_cuts_batch_running = False
        self._suppress_preview_regenerate_after_metadata = False
        self._cut_batch_button_snapshot: Optional[Dict[str, str]] = None
        self.APP_VERSION = APP_VERSION

        # Preview Tab-Elemente
        # self.title_label = None
        # self.preview_separator = None
        self.preview_notebook = None
        self.video_tab = None
        self.foto_tab = None

        # Für Threading und Ladefenster ---
        self.analysis_queue = None
        self.loading_window = None
        self._session_reset_in_progress = False
        self._last_video_wm_visible = None
        self._last_photo_wm_visible = None

        # SD-Karten Monitor
        self.sd_card_monitor = None
        self.sd_status_indicator = None

        # Speichern der Button-Originalzustände
        self.old_button_text = ""
        self.old_button_bg = ""
        self.old_button_cursor = ""

        # Flag für Initialisierungsstatus
        self.initialization_complete = False

        # VLC früh im Hintergrund laden (blockiert Splash-Spinner nicht)
        from .components.video_player import preload_shared_vlc_instance
        preload_shared_vlc_instance()

        # Starte asynchrone Initialisierung
        self._init_step_1()

    def _schedule_init_chunk(self, callback, delay=1):
        """Gibt dem Event-Loop Zeit für Splash-Spinner und UI-Updates."""
        self.root.after(delay, callback)

    def _init_step_1(self):
        """Schritt 1: GUI erstellen - aufgeteilt in Sub-Schritte"""
        if self.splash_callback:
            self.splash_callback("Erstelle Fenster...")

        # Starte GUI-Erstellung in Chunks
        self._setup_gui_step_1()

    def _setup_gui_step_1(self):
        """GUI Setup Teil 1: Grundkonfiguration"""
        # WICHTIG: Stelle sicher dass Fenster versteckt bleibt!
        if not self.root.wm_state() == 'withdrawn':
            self.root.withdraw()

        self.root.title("Aero Tandem Studio")

        # Zentriere Fenster auf dem Bildschirm
        window_width = 1500
        window_height = 800
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.root.config(padx=20, pady=0)

        self._schedule_init_chunk(self._setup_gui_step_2)

    def _setup_gui_step_2(self):
        """GUI Setup Teil 2: Header und Container"""
        if self.splash_callback:
            self.splash_callback("Erstelle Layout...")

        # Header
        self.create_header()

        # Container
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        self.left_frame = tk.Frame(self.main_container, width=350)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self.left_frame.pack_propagate(False)  # Erzwingt die width-Einstellung

        self.right_frame = tk.Frame(self.main_container, width=700)
        self.right_frame.pack(side="right", fill="y", padx=(10, 0))
        self.right_frame.pack_propagate(False)  # Erzwingt die width-Einstellung

        self._schedule_init_chunk(self._setup_gui_step_3)

    def _setup_gui_step_3(self):
        """GUI Setup Teil 3: Formular"""
        if self.splash_callback:
            self.splash_callback("Lade Formulare...")

        from .components.form_fields import FormFields
        self.form_fields = FormFields(self.left_frame, self.config, self)

        self._schedule_init_chunk(self._setup_gui_step_3b)

    def _setup_gui_step_3b(self):
        """GUI Setup Teil 3b: Drag & Drop"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Import...")

        from .components.drag_drop import DragDropFrame
        self.drag_drop = DragDropFrame(self.left_frame, self)

        self._schedule_init_chunk(self._setup_gui_step_4)

    def _setup_gui_step_4(self):
        """GUI Setup Teil 4: Preview-Tabs"""
        if self.splash_callback:
            self.splash_callback("Erstelle Vorschau...")

        style = ttk.Style()
        style.configure('Preview.TNotebook.Tab', font=('Arial', 8, 'bold'), padding=[20, 5])

        self.preview_notebook = ttk.Notebook(self.right_frame, style='Preview.TNotebook')
        self.video_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.video_tab, text="Video Vorschau")
        self.foto_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.foto_tab, text="Foto Vorschau")

        self._schedule_init_chunk(self._setup_gui_step_4b)

    def _setup_gui_step_4b(self):
        """GUI Setup Teil 4b: Video Player (VLC)"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Video Player...")

        from .components.video_player import (
            VideoPlayer,
            is_vlc_preload_finished,
            preload_shared_vlc_instance,
        )

        preload_shared_vlc_instance()
        if not is_vlc_preload_finished():
            self._schedule_init_chunk(self._setup_gui_step_4b, delay=50)
            return

        self.video_player = VideoPlayer(self.video_tab, self)

        self._schedule_init_chunk(self._setup_gui_step_4c)

    def _setup_gui_step_4c(self):
        """GUI Setup Teil 4c: Video-Vorschau"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Video Vorschau...")

        from .components.video_preview import VideoPreview
        self.video_preview = VideoPreview(self.video_tab, self)

        self._schedule_init_chunk(self._setup_gui_step_5)

    def _setup_gui_step_5(self):
        """GUI Setup Teil 5: Foto-Preview und Button"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Foto Vorschau...")

        from .components.photo_preview import PhotoPreview
        self.photo_preview = PhotoPreview(self.foto_tab, self)

        self._finish_setup_gui()

        self._schedule_init_chunk(self._init_step_2, delay=10)

    def _create_reset_session_icon(self):
        """Raster-Reload-Icon (weiß, transparent); None bei fehlendem PIL."""
        try:
            from PIL import Image, ImageDraw, ImageTk
        except ImportError:
            return None
        try:
            size = 24
            scale = 5
            s = size * scale
            img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            cx = cy = s / 2
            r = s * 0.36
            stroke = max(int(round(s * 0.09)), scale * 2)
            white = (255, 255, 255, 255)
            # Bogen (Lücke oben-rechts), Pfeil am Endpunkt
            draw.arc(
                [cx - r, cy - r, cx + r, cy + r],
                start=38,
                end=328,
                fill=white,
                width=stroke,
            )
            end_deg = 328
            theta = math.radians(end_deg)
            tx = cx + r * math.cos(theta)
            ty = cy + r * math.sin(theta)
            travel = math.radians(end_deg + 90)
            ah = r * 0.52
            spread = math.radians(36)
            p0 = (tx, ty)
            p1 = (tx - ah * math.cos(travel - spread), ty - ah * math.sin(travel - spread))
            p2 = (tx - ah * math.cos(travel + spread), ty - ah * math.sin(travel + spread))
            draw.polygon([p0, p1, p2], fill=white)
            try:
                resample = Image.Resampling.LANCZOS
            except AttributeError:
                resample = Image.LANCZOS
            img = img.resize((size, size), resample)
            return ImageTk.PhotoImage(img)
        except Exception:
            return None

    def _build_reset_session_button(self, controls_row, size_reference_button=None):
        """Zurücksetzen-Button mit Raster-Icon (Fallback: Unicode).

        Mit size_reference_button (Erstellen): gleiche Höhe und Breite wie früher
        width=4 / width=36 relativ zum Erstellen-Button.
        """
        self._reset_session_icon = self._create_reset_session_icon()
        base_kw = dict(
            command=self.reset_session,
            bg="#FF9800",
            fg="white",
            activebackground="#F57C00",
            activeforeground="white",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
        )

        parent = controls_row
        if size_reference_button is not None:
            self.root.update_idletasks()
            ref = size_reference_button
            ref_h = max(ref.winfo_reqheight(), 1)
            ref_w_full = max(ref.winfo_reqwidth(), 1)
            reset_w = max(int(round(ref_w_full * (4.0 / 36.0))), ref_h)
            shell = tk.Frame(
                controls_row,
                height=ref_h,
                width=reset_w,
                bg="#FF9800",
                highlightthickness=0,
                bd=0,
            )
            shell.pack_propagate(False)
            shell.pack(side="right")
            parent = shell

        if self._reset_session_icon is not None:
            self.reset_session_button = tk.Button(
                parent,
                image=self._reset_session_icon,
                compound=tk.CENTER,
                **base_kw,
            )
        else:
            fb_kw = dict(**base_kw)
            if parent is controls_row:
                fb_kw["width"] = 4
                fb_kw["height"] = 2
            self.reset_session_button = tk.Button(
                parent,
                text="\u21bb",
                font=("Arial", 12, "bold"),
                **fb_kw,
            )

        if parent is controls_row:
            self.reset_session_button.pack(side="right")
        else:
            self.reset_session_button.pack(expand=True, fill="both")

        self.create_tooltip(self.reset_session_button, "Formular und alle importierten Medien leeren")

    def _finish_setup_gui(self):
        """Finalisiert setup_gui - erstellt Upload-Frame etc."""
        from .components.progress_indicator import ProgressHandler

        # Event-Binding
        self.preview_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Upload Frame erstellen (aus original setup_gui kopiert)
        self.upload_frame = tk.Frame(self.right_frame)
        progress_row = tk.Frame(self.upload_frame)
        progress_row.pack(fill="x", side="top", pady=(2, 6))

        self.progress_handler = ProgressHandler(self.root, progress_row)

        controls_row = tk.Frame(self.upload_frame)
        controls_row.pack(fill="x", side="top", pady=(5, 0))

        checkboxes_frame = tk.Frame(controls_row)
        checkboxes_frame.pack(side="left", fill="both", expand=True)

        upload_row = tk.Frame(checkboxes_frame)
        upload_row.pack(fill="x", pady=(0, 3))

        self.upload_to_server_var = tk.BooleanVar()
        self.upload_checkbox = tk.Checkbutton(upload_row, text="Auf Server laden",
                                               variable=self.upload_to_server_var,
                                               font=("Arial", 11),
                                               command=self.on_upload_checkbox_toggle)
        self.upload_checkbox.pack(side="left")

        self.server_status_label = tk.Label(upload_row, text="Prüfe...",
                                            font=("Arial", 9, "bold"), fg="orange")
        self.server_status_label.pack(side="left", padx=(5, 0))

        autoclear_row = tk.Frame(checkboxes_frame)
        autoclear_row.pack(fill="x")

        self.auto_clear_files_var = tk.BooleanVar()
        self.auto_clear_checkbox = tk.Checkbutton(autoclear_row,
                                                   text="Nach Erstellen zurücksetzen",
                                                   variable=self.auto_clear_files_var,
                                                   font=("Arial", 11),
                                                   command=self._on_auto_clear_toggle)
        self.auto_clear_checkbox.pack(side="left")

        self.erstellen_button = tk.Button(controls_row, text="Erstellen",
                                          font=("Arial", 12, "bold"),
                                          command=self.erstelle_video,
                                          bg="#4CAF50", fg="white",
                                          width=36, height=2)
        self.erstellen_button.pack(side="right", padx=(10, 0))

        self._build_reset_session_button(controls_row, size_reference_button=self.erstellen_button)

        self.pack_components()
        self.load_settings()
        self.test_server_connection_async()

    def _init_step_2(self):
        """Schritt 2: Dependencies prüfen"""
        if self.splash_callback:
            self.splash_callback("Prüfe FFmpeg Installation...")

        self.ensure_dependencies()
        self._schedule_init_chunk(self._init_step_3, delay=10)

    def _init_step_3(self):
        """Schritt 3: Finalisierung"""
        if self.splash_callback:
            self.splash_callback("Finalisiere...")

        self._schedule_init_chunk(self._init_complete, delay=10)

    def _init_complete(self):
        """Initialisierung abgeschlossen"""
        if self.splash_callback:
            self.splash_callback("Bereit!")

        # NEU: Schließ-Ereignis abfangen
        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)

        # Markiere Initialisierung als abgeschlossen
        self.initialization_complete = True

        # NEU: Initial WM-Button-Sichtbarkeit setzen
        self.update_watermark_column_visibility()

        print("✅ App-Initialisierung abgeschlossen")

        # Update-Prüfung starten (automatisch im Hintergrund)
        try:
            initialize_updater(self.root, self.APP_VERSION)
        except Exception as e:
            print(f"⚠️ Fehler beim Initialisieren des Updaters: {e}")

        # SD-Monitor verzögert starten (800ms nach Splash-Schließung)
        self.root.after(800, self._delayed_sd_monitor_start)

        # Verwaiste Vorschau-Temp-Ordner im Hintergrund entfernen
        self.root.after(1200, self._startup_cache_sweep)

    def _delayed_sd_monitor_start(self):
        """Startet SD-Monitor verzögert nach UI-Initialisierung"""
        try:
            if self.splash_callback:
                # Splash könnte bereits geschlossen sein, ignoriere Fehler
                try:
                    self.splash_callback("Starte SD-Überwachung...")
                except:
                    pass

            self.initialize_sd_card_monitor()
            print("✅ SD-Karten Monitor gestartet")
        except Exception as e:
            print(f"⚠️ Fehler beim Starten des SD-Monitors: {e}")


    def setup_gui(self):
        from .components.form_fields import FormFields
        from .components.drag_drop import DragDropFrame
        from .components.video_player import VideoPlayer
        from .components.video_preview import VideoPreview
        from .components.photo_preview import PhotoPreview
        from .components.progress_indicator import ProgressHandler

        self.root.title("Aero Tandem Studio")

        # Zentriere Fenster auf dem Bildschirm
        window_width = 1500
        window_height = 800
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.root.config(padx=20, pady=0)

        # Header mit Titel und Settings-Button
        self.create_header()

        # Haupt-Container mit zwei Spalten
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        # Linke Spalte für Formular und Drag & Drop
        self.left_frame = tk.Frame(self.main_container, width=600)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 20))

        # Rechte Spalte für Vorschau und Button
        self.right_frame = tk.Frame(self.main_container, width=350)
        self.right_frame.pack(side="right", fill="y", padx=(20, 0))

        # Linke Spalte: Formular und Drag & Drop
        self.form_fields = FormFields(self.left_frame, self.config, self)
        self.drag_drop = DragDropFrame(self.left_frame, self)

        # Rechte Spalte: Tab-View für Vorschau-Inhalte
        # Tab-View erstellen mit gleichem Style wie Drag-and-Drop
        style = ttk.Style()
        style.configure('Preview.TNotebook.Tab',
                       font=('Arial', 8, 'bold'),
                       padding=[20, 5])  # [horizontal, vertical] padding

        self.preview_notebook = ttk.Notebook(self.right_frame, style='Preview.TNotebook')

        # Tab für Video Vorschau
        self.video_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.video_tab, text="Video Vorschau")

        # Tab für Foto Vorschau
        self.foto_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.foto_tab, text="Foto Vorschau")

        # Video-Tab Inhalt
        # Titel im Video-Tab
        # self.title_label = tk.Label(self.video_tab, text="Video Vorschau", font=("Arial", 14, "bold"))

        # Separator im Video-Tab
        # self.preview_separator = ttk.Separator(self.video_tab, orient='horizontal')

        # Video Player und Preview im Video-Tab
        self.video_player = VideoPlayer(self.video_tab, self)
        self.video_preview = VideoPreview(self.video_tab, self)

        # Foto-Tab Inhalt
        self.photo_preview = PhotoPreview(self.foto_tab, self)

        # Event-Binding für Tab-Wechsel: Focus auf Photo Preview setzen
        self.preview_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Server-Upload Frame mit Status-Anzeige
        # Neues Layout: Progress ganz rechts oben, darunter Checkboxen links und Button rechts
        self.upload_frame = tk.Frame(self.right_frame)

        # Obere Zeile: Progress Handler ganz rechts
        progress_row = tk.Frame(self.upload_frame)
        progress_row.pack(fill="x", side="top", pady=(2, 6))

        # Progress Handler (wird hier initialisiert, aber später gepackt)
        self.progress_handler = ProgressHandler(self.root, progress_row)

        # Untere Zeile: Checkboxen links, Button rechts
        controls_row = tk.Frame(self.upload_frame)
        controls_row.pack(fill="x", side="top", pady=(0, 0))

        # Linke Seite: Frame für Checkboxen (untereinander)
        checkboxes_frame = tk.Frame(controls_row)
        checkboxes_frame.pack(side="left", fill="both", expand=True)

        # Erste Zeile: Server-Upload Checkbox und Status
        upload_row = tk.Frame(checkboxes_frame)
        upload_row.pack(fill="x", pady=(0, 0))

        self.upload_to_server_var = tk.BooleanVar()
        self.upload_checkbox = tk.Checkbutton(
            upload_row,
            text="Auf Server laden",
            variable=self.upload_to_server_var,
            font=("Arial", 11),
            command=self.on_upload_checkbox_toggle
        )
        self.upload_checkbox.pack(side="left")

        # Server Status Label
        self.server_status_label = tk.Label(
            upload_row,
            text="Prüfe...",
            font=("Arial", 9, "bold"),
            fg="orange"
        )
        self.server_status_label.pack(side="left", padx=(5, 0))

        # Zweite Zeile: Auto-Clear Checkbox
        autoclear_row = tk.Frame(checkboxes_frame)
        autoclear_row.pack(fill="x")

        self.auto_clear_files_var = tk.BooleanVar()
        self.auto_clear_checkbox = tk.Checkbutton(
            autoclear_row,
            text="Nach Erstellen zurücksetzen",
            variable=self.auto_clear_files_var,
            font=("Arial", 11),
            command=self._on_auto_clear_toggle
        )
        self.auto_clear_checkbox.pack(side="left")

        # Rechte Seite: Erstellen-Button (kleiner, kompakter)
        self.erstellen_button = tk.Button(
            controls_row,
            text="Erstellen",
            font=("Arial", 12, "bold"),
            command=self.erstelle_video,
            bg="#4CAF50",
            fg="white",
            width=36,
            height=2
        )
        self.erstellen_button.pack(side="right", padx=(10, 0))

        self._build_reset_session_button(controls_row, size_reference_button=self.erstellen_button)

        self.pack_components()
        self.load_settings()

        # Server-Verbindung testen (im Hintergrund)
        self.test_server_connection_async()

    def create_header(self):
        """Erstellt den Header mit Titel, Logo und Settings-Button"""
        from .components.sd_status_indicator import SDStatusIndicator

        header_frame = tk.Frame(self.root)
        header_frame.pack(fill="x")

        # Logo links neben dem Titel (80x80)
        img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo.png"))
        self.logo_image = None
        if os.path.exists(img_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(img_path).convert("RGBA")
                img = img.resize((50, 50), Image.LANCZOS)
                self.logo_image = ImageTk.PhotoImage(img)
            except Exception:
                try:
                    self.logo_image = tk.PhotoImage(file=img_path)
                except Exception:
                    self.logo_image = None

        if self.logo_image:
            logo_label = tk.Label(header_frame, image=self.logo_image, bd=0)
            logo_label.pack(side="left", padx=(0, 10))

        # Titel
        title_label = tk.Label(
            header_frame,
            text="Aero Tandem Studio",
            font=("Arial", 16, "bold"),
            fg="#009d8b"
        )
        title_label.pack(side="left")

        # SD-Status Indikator (wird rechts vom Titel angezeigt, wenn aktiv)
        self.sd_status_indicator = SDStatusIndicator(header_frame)
        self.sd_status_indicator.create_widgets()
        # Wird später gepackt wenn Monitoring aktiv ist

        # Settings-Button (rechts)
        self.settings_button = tk.Button(
            header_frame,
            text="⚙",  # Gear Icon
            font=("Arial", 16),
            command=self.show_settings,
            bg="#f0f0f0",
            relief="flat",
            width=3,
        )
        self.settings_button.pack(side="right")

        # Tooltip für Settings-Button
        self.create_tooltip(self.settings_button, "Einstellungen öffnen")

    def create_tooltip(self, widget, text):
        """Erstellt einen Tooltip für ein Widget"""

        tooltip_window = None
        tooltip_timer = None

        def show_tooltip(event):
            nonlocal tooltip_window, tooltip_timer

            # Cleanup vorhandener Tooltip
            hide_tooltip()

            # Verzögerte Anzeige (verhindert Flackern)
            def create_window():
                nonlocal tooltip_window
                try:
                    tooltip_window = tk.Toplevel()
                    tooltip_window.wm_overrideredirect(True)
                    tooltip_window.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

                    label = tk.Label(
                        tooltip_window,
                        text=text,
                        background="#ffffcc",
                        relief="solid",
                        borderwidth=1,
                        padx=5,
                        pady=3
                    )
                    label.pack()

                    # Auto-Cleanup nach 5 Sekunden
                    tooltip_window.after(5000, hide_tooltip)
                except tk.TclError:
                    tooltip_window = None

            tooltip_timer = widget.after(500, create_window)

        def hide_tooltip(event=None):
            nonlocal tooltip_window, tooltip_timer

            # Stoppe Timer
            if tooltip_timer:
                try:
                    widget.after_cancel(tooltip_timer)
                except tk.TclError:
                    # Ignore if timer is already cancelled or invalid
                    pass
                tooltip_timer = None

            # Zerstöre Fenster
            if tooltip_window:
                try:
                    tooltip_window.destroy()
                except Exception:
                    pass
                tooltip_window = None

        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def show_settings(self):
        """
        Zeigt den Einstellungs-Dialog

        Öffnet ein modales Fenster mit allen Konfigurationsoptionen.
        Nach dem Speichern wird on_settings_saved() automatisch aufgerufen.
        """
        from .components.settings_dialog import SettingsDialog

        SettingsDialog(
            self.root,
            self.config,
            on_settings_saved=self.on_settings_saved,
            app=self,
        ).show()

    def on_settings_saved(self):
        """
        Wird aufgerufen nachdem Settings gespeichert wurden

        Lädt alle notwendigen Komponenten neu, damit Änderungen
        sofort wirksam werden ohne die App neu starten zu müssen.
        """
        # Config neu laden für aktuelle Einstellungen
        self.config.reload_settings()

        # Hardware-Beschleunigung in VideoPreview neu laden
        if hasattr(self, 'video_preview') and self.video_preview:
            self.video_preview.reload_hardware_acceleration_settings()

        # Wenn VideoProcessor existiert, auch dort neu laden
        if hasattr(self, 'video_processor') and self.video_processor:
            self.video_processor.reload_hardware_acceleration_settings()

        # Server-Verbindung asynchron testen
        self.test_server_connection_async()

        # SD-Monitor sofort neu starten (wenn Auto-Backup aktiviert/deaktiviert wurde)
        self._restart_sd_monitor_if_needed()

        if hasattr(self, 'form_fields') and self.form_fields:
            self.form_fields.reload_current_layout()

    def pack_components(self):
        # Linke Spalte
        self.form_fields.pack(pady=10, fill="x")
        self.drag_drop.pack(fill="both", expand=True, pady=10)

        # Rechte Spalte
        # Tab-View packen
        self.preview_notebook.pack(fill="both", expand=True, pady=(0, 0))

        # Video-Tab Inhalt packen
        # self.title_label.pack(pady=0)
        # self.preview_separator.pack(fill='x', pady=5)
        self.video_player.pack(fill="x", pady=(0, 0), side="top")
        self.video_preview.pack(fill="x", pady=(0, 0), side="top")

        # Foto-Tab Inhalt packen
        self.photo_preview.pack(fill="both", expand=True, padx=5, pady=0)

        # Upload-Frame (enthält jetzt Progress oben rechts, Checkboxen und Button)
        self.upload_frame.pack(pady=0, fill="x", side="top")

        # Progress Bar NICHT hier packen - wird nur während Erstellung angezeigt
        # self.progress_handler.pack_progress_bar_right()

        # Status-Label ganz unten
        self.progress_handler.pack_status_label()

        # Initialer Focus: Wenn Video-Tab aktiv ist, kein Focus setzen
        # Wenn Foto-Tab aktiv ist, Focus setzen
        # Warte kurz bis alles gerendert ist
        self.root.after(100, self._set_initial_focus)

    def _set_initial_focus(self):
        """Setzt den initialen Focus basierend auf dem aktiven Tab"""
        try:
            selected_tab = self.preview_notebook.select()
            tab_text = self.preview_notebook.tab(selected_tab, "text")

            if tab_text == "Foto Vorschau":
                self.photo_preview.frame.focus_set()
        except:
            pass  # Ignoriere Fehler beim initialen Focus-Setzen

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        try:
            settings = self.config.get_settings()
            self.upload_to_server_var.set(settings.get("upload_to_server", False))
            self.auto_clear_files_var.set(settings.get("auto_clear_files_after_creation", False))
        except:
            self.upload_to_server_var.set(False)
            self.auto_clear_files_var.set(False)

    def test_server_connection_async(self):
        """Testet die Server-Verbindung asynchron"""
        self.server_status_label.config(text="Prüfe...", fg="orange")

        def test_connection():
            success, message = test_server_connection(self.config)
            self.root.after(0, self.update_server_status, success, message)

        thread = threading.Thread(target=test_connection, daemon=True)
        thread.start()

    def update_server_status(self, connected, message):
        """Aktualisiert den Server-Status in der GUI"""
        self.server_connected = connected

        if connected:
            self.server_status_label.config(text="✓ Verbunden", fg="green")
            # Tooltip für erfolgreiche Verbindung
            self.create_tooltip(self.server_status_label, f"Server erreichbar\n{message}")
        else:
            self.server_status_label.config(text="✗ Getrennt", fg="red")
            # Tooltip für Fehler
            self.create_tooltip(self.server_status_label, f"Server nicht erreichbar\n{message}")

            # Deaktiviere Upload-Checkbox falls nicht verbunden
            if self.upload_to_server_var.get():
                self.upload_to_server_var.set(False)
                messagebox.showwarning(
                    "Server nicht erreichbar",
                    f"Server-Verbindung fehlgeschlagen:\n{message}\n\n"
                    "Upload wurde deaktiviert. Bitte überprüfen Sie die Einstellungen."
                )

    def _on_tab_changed(self, event):
        """Wird aufgerufen wenn der Tab gewechselt wird"""
        # Prüfe welcher Tab aktiv ist
        selected_tab = self.preview_notebook.select()
        tab_text = self.preview_notebook.tab(selected_tab, "text")

        # Wenn Foto-Tab aktiv ist, setze Focus auf Photo Preview
        if tab_text == "Foto Vorschau":
            # Focus auf den Frame setzen, damit Pfeiltasten funktionieren
            self.photo_preview.frame.focus_set()

    def on_upload_checkbox_toggle(self):
        """Wird aufgerufen wenn die Upload-Checkbox geändert wird"""
        if self.upload_to_server_var.get() and not self.server_connected:
            # Wenn Upload aktiviert aber nicht verbunden, zeige Warnung und deaktiviere
            self.upload_to_server_var.set(False)
            messagebox.showwarning(
                "Server nicht erreichbar",
                "Kann nicht auf Server uploaden - keine Verbindung verfügbar.\n\n"
                "Bitte überprüfen Sie:\n"
                "• Server-Einstellungen (⚙)\n"
                "• Netzwerkverbindung\n"
                "• Server-Erreichbarkeit"
            )
            # Starte erneuten Verbindungstest
            self.test_server_connection_async()

    def _on_auto_clear_toggle(self):
        """Wird aufgerufen wenn die Auto-Clear-Checkbox geändert wird"""
        # Speichere die Einstellung in der Config
        try:
            settings = self.config.get_settings()
            settings["auto_clear_files_after_creation"] = self.auto_clear_files_var.get()
            self.config.save_settings(settings)
            print(f"Auto-Clear Einstellung gespeichert: {self.auto_clear_files_var.get()}")
        except Exception as e:
            print(f"Fehler beim Speichern der Auto-Clear Einstellung: {e}")

    def ensure_dependencies(self):
        """Stellt sicher, dass FFmpeg installiert ist"""
        self._start_ffmpeg_installer_overlayed()

    def _create_install_overlay(self):
        """Erstellt Installations-Overlay"""
        from .components.circular_spinner import CircularSpinner

        overlay = tk.Frame(self.root, bg="#000000")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()

        def _block_event(e):
            return "break"

        for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>", "<Button>"):
            overlay.bind_all(seq, _block_event)

        container = tk.Frame(overlay, bg='white', bd=2, relief=tk.RIDGE)
        container_width = min(420, int(self.root.winfo_width() * 0.7 or 300))
        container.place(relx=0.5, rely=0.5, anchor='center', width=container_width)

        spinner = CircularSpinner(container, size=80, line_width=8, color="#2E86C1", speed=10)
        spinner.pack(padx=20, pady=(20, 6))

        status_var = tk.StringVar(value="Installing FFmpeg...")
        status_lbl = tk.Label(container, textvariable=status_var, font=("Arial", 10), bg='white',
                              wraplength=container_width - 40)
        status_lbl.pack(padx=20, pady=(0, 20))

        return overlay, spinner, status_var

    def _start_ffmpeg_installer_overlayed(self):
        """Startet FFmpeg-Installation mit Overlay"""
        overlay, spinner, status_var = self._create_install_overlay()
        spinner.start()

        def progress_callback(msg):
            self.root.after(0, status_var.set, msg)

        def finish(success_path=None, error=None):
            try:
                spinner.stop()
            except Exception:
                pass
            for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>",
                        "<Button>"):
                try:
                    overlay.unbind_all(seq)
                except Exception:
                    pass
            try:
                overlay.destroy()
            except Exception:
                pass
            if error:
                self.root.after(0, lambda: messagebox.showerror("FFmpeg installation failed", str(error)))

        def installer_thread():
            try:
                path = ensure_ffmpeg_installed(progress_callback=progress_callback)
                finish(success_path=path)
            except Exception as e:
                finish(error=e)

        t = threading.Thread(target=installer_thread, daemon=True)
        t.start()

    def _save_button_state(self):
        """Speichert den aktuellen Zustand des Buttons."""
        current_text = self.erstellen_button.cget("text")

        # Speichere nur gültige Button-Zustände (nicht "Bitte warten..." oder "Abbrechen")
        # Wenn der Button bereits in einem temporären Zustand ist, behalte den gespeicherten Wert
        if current_text not in ("Bitte warten...", "Abbrechen"):
            self.old_button_text = current_text
            self.old_button_bg = self.erstellen_button.cget("bg")
            try:
                self.old_button_cursor = self.erstellen_button.cget("cursor")
            except tk.TclError:
                self.old_button_cursor = ""  # Standard-Cursor
        # Sonst: Behalte die vorher gespeicherten Werte
        # Falls keine gespeichert wurden, setze Default-Werte
        elif not hasattr(self, 'old_button_text') or not self.old_button_text:
            self.old_button_text = "Erstellen"
            self.old_button_bg = "#4CAF50"
            self.old_button_cursor = ""

    def _set_button_waiting(self):
        """Setzt den Button in den Wartezustand."""
        self.erstellen_button.config(text="Bitte warten...", bg="#9E9E9E", state="disabled", cursor="watch")

    def _restore_button_state(self):
        """Stellt den ursprünglichen Zustand des Buttons wieder her."""
        # Nur wiederherstellen, wenn der Button nicht im "Abbrechen"-Modus ist
        current_text = self.erstellen_button.cget("text")
        if current_text == "Bitte warten..." or current_text == "Erstellen":
            if self.old_button_text and self.old_button_text != "Abbrechen":  # Nur wiederherstellen, wenn ein gültiger Zustand gespeichert wurde
                self.erstellen_button.config(text=self.old_button_text,
                                             bg=self.old_button_bg,
                                             state="normal",
                                             cursor=self.old_button_cursor)
            else:
                # Fallback, falls kein Zustand gespeichert wurde oder "Abbrechen" gespeichert war
                self.erstellen_button.config(text="Erstellen",
                                             bg="#4CAF50",
                                             state="normal",
                                             cursor="")
        # Wenn der Button "Abbrechen" anzeigt, ändere nichts

    def update_video_preview(
        self,
        video_paths: List[str],
        run_qr_check: bool = True,
        qr_video_paths: Optional[List[str]] = None,
    ):
        """
        Aktualisiert die Video-Vorschau. Startet die QR-Analyse in einem
        separaten Thread oder setzt das Formular zurück, wenn keine Videos vorhanden sind.
        run_qr_check steuert, ob die QR-Analyse durchgeführt werden soll.
        Optional kann mit qr_video_paths eine Teilmenge der Clips für QR vorgegeben werden.
        """
        if threading.current_thread() is not threading.main_thread():
            paths_copy = video_paths.copy()
            qr_paths_copy = None if qr_video_paths is None else qr_video_paths.copy()
            self.root.after(
                0,
                lambda: self.update_video_preview(
                    paths_copy,
                    run_qr_check=run_qr_check,
                    qr_video_paths=qr_paths_copy,
                ),
            )
            return

        if not video_paths:
            # --- NEU: Anforderung des Users umsetzen ---
            # Wenn alle Videos gelöscht wurden, setze das Formular
            # auf den manuellen Modus zurück.
            print("Keine Videos gefunden, setze Formular auf manuell zurück.")
            if not getattr(self, "_session_reset_in_progress", False):
                self.form_fields.update_form_layout(qr_success=False, kunde=None)

            # Auch Vorschau und Player leeren
            try:
                if self.video_preview:
                    self.video_preview.clear_preview()
            except AttributeError:
                print("Hinweis: video_preview hat keine 'clear_preview' Methode.")
            except Exception as e:
                print(f"Fehler beim Leeren der Vorschau: {e}")

            try:
                if self.video_player:
                    self.video_player.unload_video()
            except AttributeError:
                print("Hinweis: video_player hat keine 'unload_video' Methode.")
            except Exception as e:
                print(f"Fehler beim Entladen des Players: {e}")

            # Button-Status wiederherstellen - WICHTIG: Setze Button explizit auf "Erstellen"
            # um sicherzustellen dass er nicht im "Bitte warten"-Zustand hängen bleibt
            print("Stelle Button-Status nach Video-Löschung wieder her")
            self.erstellen_button.config(
                text="Erstellen",
                bg="#4CAF50",
                state="normal",
                cursor=""
            )
            # Speichere den korrekten Status für zukünftige Wiederherstellungen
            self.old_button_text = "Erstellen"
            self.old_button_bg = "#4CAF50"
            self.old_button_cursor = ""

            return
            # --- ENDE NEU ---

        qr_scan_paths = video_paths if qr_video_paths is None else qr_video_paths
        qr_scan_paths = qr_scan_paths.copy() if qr_scan_paths else []

        if run_qr_check and qr_scan_paths:
            # Starte QR-Analyse UND Preview-Erstellung PARALLEL!
            print("Starte QR-Analyse und Preview-Erstellung parallel...")

            # 1. Preview-Erstellung starten (läuft in eigenem Thread)
            if self.video_preview:
                self.video_preview.update_preview(video_paths)

            # 2. QR-Analyse starten (läuft ebenfalls in eigenem Thread)
            self.run_qr_analysis(qr_scan_paths)
        else:
            # Keine QR-Prüfung, nur Vorschau aktualisieren
            print("QR-Prüfung übersprungen - keine neuen Clips für Auto-Scan.")
            if self.video_preview:
                self.video_preview.update_preview(video_paths)

    def _reset_qr_cancel_event(self):
        self._qr_cancel_event = threading.Event()

    def _request_qr_cancel(self):
        if hasattr(self, "_qr_cancel_event"):
            self._qr_cancel_event.set()
        print("QR-Analyse: Abbruch angefordert...")

    def _qr_cancel_check(self) -> bool:
        return hasattr(self, "_qr_cancel_event") and self._qr_cancel_event.is_set()

    def _qr_parallel_worker_count(self) -> int:
        settings = self.config.get_settings() if self.config else {}
        try:
            parallel_workers = int(settings.get("qr_video_parallel_workers", 2))
        except (TypeError, ValueError):
            parallel_workers = 2
        return max(1, min(4, parallel_workers))

    def _qr_video_scan_kwargs(self) -> dict:
        settings = self.config.get_settings() if self.config else {}
        try:
            scan_seconds = float(settings.get("qr_video_scan_seconds", 5))
        except (TypeError, ValueError):
            scan_seconds = 5.0
        try:
            frame_step = int(settings.get("qr_video_frame_step", 10))
        except (TypeError, ValueError):
            frame_step = 10
        parallel_enabled = bool(settings.get("qr_video_parallel_enabled", False))
        scan_all_clips = bool(settings.get("qr_video_scan_all_clips", True))
        return {
            "scan_seconds": max(0.5, scan_seconds),
            "frame_step": max(1, frame_step),
            "scan_all_clips": scan_all_clips,
            "parallel_enabled": parallel_enabled and scan_all_clips,
            "parallel_workers": self._qr_parallel_worker_count(),
        }

    def _qr_photo_scan_kwargs(self) -> dict:
        settings = self.config.get_settings() if self.config else {}
        parallel_enabled = bool(settings.get("qr_photo_parallel_enabled", False))
        return {
            "parallel_enabled": parallel_enabled,
            "parallel_workers": self._qr_parallel_worker_count(),
        }

    def _qr_media_labels(self, media: Literal["video", "photo"]) -> tuple[str, str]:
        if media == "video":
            return "Video", "Videos"
        return "Foto", "Fotos"

    def _show_qr_loading_dialog(
        self,
        media: Literal["video", "photo"],
        total: int,
        first_basename: str,
        *,
        parallel: bool = False,
    ) -> None:
        _, plural = self._qr_media_labels(media)
        from .components.loading_window import LoadingWindow

        self.loading_window = LoadingWindow(
            self.root,
            text=f"Prüfe {plural} auf QR-Code",
            on_cancel=self._request_qr_cancel,
            detail_mode=True,
        )
        if parallel:
            phase = "parallel"
            completed_count = 0
        elif total > 1 and media == "video":
            phase = "hybrid_first"
            completed_count = 0
        else:
            phase = "scanning"
            completed_count = 0
        self._update_qr_scan_progress(
            media,
            1,
            total,
            first_basename,
            phase=phase,
            completed_count=completed_count,
        )
        try:
            self.loading_window.lift()
            self.loading_window.focus_force()
        except tk.TclError:
            pass

    def _set_qr_loading_status(self, text: str) -> None:
        """Aktualisiert den Text im QR-Ladefenster (falls geöffnet)."""
        if self.loading_window and hasattr(self.loading_window, "update_text"):
            try:
                self.loading_window.update_text(text)
            except tk.TclError:
                pass

    def _dismiss_qr_loading_window(self) -> None:
        """Schließt das QR-Ladefenster, falls vorhanden."""
        if self.loading_window:
            try:
                self.loading_window.destroy()
            except tk.TclError:
                pass
            self.loading_window = None

    def _update_form_layout_after_qr(self, qr_success, kunde=None) -> None:
        """Aktualisiert das Formular-Layout; QR-Lade-Dialog bleibt bis zum Aufrufer offen."""
        self._set_qr_loading_status("Formular wird aktualisiert…")
        self.form_fields.update_form_layout(qr_success, kunde)

    def _update_qr_scan_progress(
        self,
        media: Literal["video", "photo"],
        item_index: int,
        total: int,
        basename: str,
        *,
        phase: str = "scanning",
        active_basenames: Optional[List[str]] = None,
        completed_count: Optional[int] = None,
    ) -> None:
        if not self.loading_window:
            return

        singular, plural = self._qr_media_labels(media)
        active = list(active_basenames or [])

        if completed_count is None:
            completed_count = max(0, item_index - 1)

        if phase == "parallel":
            status = f"Parallele QR-Suche ({plural})"
            progress_text = f"{singular} {completed_count} von {total}"
            primary = active[0] if active else basename
        elif phase == "hybrid_first":
            status = f"Prüfe {plural} auf QR-Code"
            progress_text = f"{singular} {item_index} von {total} (zuerst)"
            primary = basename
            active = []
        else:
            status = f"Prüfe {plural} auf QR-Code"
            progress_text = f"{singular} {completed_count} von {total}"
            primary = basename
            active = []

        if hasattr(self.loading_window, "update_qr_progress"):
            self.loading_window.update_qr_progress(
                status,
                progress_text,
                primary,
                active if phase == "parallel" else None,
                completed_count=completed_count,
                total=total,
            )
        elif hasattr(self.loading_window, "update_text"):
            lines = [status, progress_text, primary]
            if active:
                lines.extend(active[1:])
            self.loading_window.update_text("\n".join(line for line in lines if line))

    def _video_paths_for_qr_scan(self, video_paths: list[str]) -> list[str]:
        """Gibt die zu scannenden Clip-Pfade gemäß Einstellung zurück."""
        if not video_paths:
            return []
        scan_opts = self._qr_video_scan_kwargs()
        if scan_opts.get("scan_all_clips", True):
            return video_paths
        return video_paths[:1]

    def run_qr_analysis(self, video_paths: list[str]):
        """
        Startet QR-Code-Analyse in separatem Thread.
        Durchsucht alle Clips (Abbruch beim ersten gültigen Treffer oder per Button).
        """
        if not video_paths:
            return

        if threading.current_thread() is not threading.main_thread():
            paths_copy = video_paths.copy()
            self.root.after(0, lambda: self.run_qr_analysis(paths_copy))
            return

        self._reset_qr_cancel_event()
        paths_to_scan = self._video_paths_for_qr_scan(video_paths)
        total = len(paths_to_scan)
        self._show_qr_loading_dialog(
            "video",
            total,
            os.path.basename(paths_to_scan[0]),
        )

        self.analysis_queue = queue.Queue()

        scope = "alle" if total == len(video_paths) else "nur erster"
        print(f"QR-Analyse: {total} Clip(s) ({scope})")

        analysis_thread = threading.Thread(
            target=self._run_analysis_thread,
            args=(paths_to_scan.copy(), self.analysis_queue),
            daemon=True,
        )
        analysis_thread.start()

        self.root.after(100, self._check_analysis_result, video_paths)

    def run_photo_qr_analysis(self, photo_path: str):
        """
        Startet QR-Code-Analyse für ein Foto in separatem Thread.
        Verwendet das gleiche Loading Window wie bei Videos.
        """
        self.run_photo_batch_qr_analysis([photo_path], single_photo=True)

    def run_photo_batch_qr_analysis(
        self,
        photo_paths: list[str],
        *,
        single_photo: bool = False,
    ):
        """
        Durchsucht Fotos nach einem QR-Code (Abbruch beim ersten gültigen Treffer).
        """
        if not photo_paths:
            return

        if threading.current_thread() is not threading.main_thread():
            paths_copy = photo_paths.copy()
            self.root.after(
                0,
                lambda: self.run_photo_batch_qr_analysis(
                    paths_copy,
                    single_photo=single_photo,
                ),
            )
            return

        if (
            not single_photo
            and self.form_fields
            and self.form_fields.has_qr_kunde_layout()
        ):
            print("Foto-QR-Suche übersprungen: Formular bereits durch QR-Scan befüllt.")
            return

        self._reset_qr_cancel_event()
        total = len(photo_paths)
        scan_opts = self._qr_photo_scan_kwargs()
        use_parallel = (
            scan_opts.get("parallel_enabled")
            and total >= 2
            and not single_photo
        )
        self._show_qr_loading_dialog(
            "photo",
            total,
            os.path.basename(photo_paths[0]),
            parallel=use_parallel,
        )
        self.analysis_queue = queue.Queue()
        self._photo_qr_batch_mode = not single_photo

        print(f"QR-Analyse Fotos: {len(photo_paths)} Datei(en)")

        analysis_thread = threading.Thread(
            target=self._run_photo_batch_analysis_thread,
            args=(photo_paths.copy(), self.analysis_queue),
            daemon=True,
        )
        analysis_thread.start()

        self.root.after(100, self._check_photo_batch_analysis_result)

    def _make_qr_progress_callback(self, media: Literal["video", "photo"]):
        def _progress(
            current: int,
            total: int,
            basename: str,
            *,
            phase: str = "scanning",
            active_basenames=None,
            completed_count=None,
        ):
            if self.loading_window:
                active = list(active_basenames or [])

                def _apply(
                    c=current,
                    t=total,
                    bn=basename,
                    ph=phase,
                    act=active,
                    cc=completed_count,
                ):
                    self._update_qr_scan_progress(
                        media,
                        c,
                        t,
                        bn,
                        phase=ph,
                        active_basenames=act,
                        completed_count=cc,
                    )

                self.root.after(0, _apply)

        return _progress

    def _run_analysis_thread(self, video_paths: list[str], result_queue: queue.Queue):
        """Durchsucht Clips nach QR-Code (Abbruch beim ersten Treffer oder per Button)."""
        try:
            from src.video.qr_analyser import (
                analysiere_ersten_clip,
                analysiere_videos_bis_erster_treffer,
                analysiere_videos_hybrid_bis_erster_treffer,
            )

            cancel_check = self._qr_cancel_check
            scan_opts = self._qr_video_scan_kwargs()
            scan_kwargs = {
                "scan_seconds": scan_opts["scan_seconds"],
                "frame_step": scan_opts["frame_step"],
            }
            use_hybrid = (
                scan_opts.get("parallel_enabled")
                and len(video_paths) >= 2
            )

            _progress = self._make_qr_progress_callback("video")

            if len(video_paths) == 1:
                kunde, qr_scan_success = analysiere_ersten_clip(
                    video_paths[0],
                    cancel_check=cancel_check,
                    clip_index=1,
                    total_clips=1,
                    progress_callback=_progress,
                    **scan_kwargs,
                )
                if cancel_check():
                    result_queue.put(("cancelled", None))
                    return
                source_path = video_paths[0] if qr_scan_success else None
                result_queue.put(("success", (kunde, qr_scan_success, source_path)))
                return

            if use_hybrid:
                kunde, qr_scan_success, source_path, cancelled = (
                    analysiere_videos_hybrid_bis_erster_treffer(
                        video_paths,
                        progress_callback=_progress,
                        cancel_check=cancel_check,
                        parallel_workers=scan_opts["parallel_workers"],
                        **scan_kwargs,
                    )
                )
            else:
                kunde, qr_scan_success, source_path, cancelled = (
                    analysiere_videos_bis_erster_treffer(
                        video_paths,
                        progress_callback=_progress,
                        cancel_check=cancel_check,
                        **scan_kwargs,
                    )
                )
            if cancelled:
                result_queue.put(("cancelled", None))
            else:
                result_queue.put(("success", (kunde, qr_scan_success, source_path)))

        except Exception as e:
            import traceback

            print(f"Fehler im Analyse-Thread: {e}")
            traceback.print_exc()
            result_queue.put(("error", e))

    def _run_photo_analysis_thread(self, photo_path: str, result_queue: queue.Queue):
        """
        Diese Funktion läuft im separaten Thread für Foto-QR-Code-Analyse.
        Sie führt die blockierende Analyse aus und legt das Ergebnis in die Queue.
        """
        try:
            from src.video.qr_analyser import analysiere_foto

            kunde, qr_scan_success = analysiere_foto(photo_path)
            result_queue.put(("success", (kunde, qr_scan_success, photo_path)))

        except Exception as e:
            print(f"Fehler im Foto-Analyse-Thread: {e}")
            result_queue.put(("error", e))

    def _run_photo_batch_analysis_thread(self, photo_paths: list[str], result_queue: queue.Queue):
        """Durchsucht mehrere Fotos nach QR-Code (Abbruch beim ersten Treffer)."""
        try:
            from src.video.qr_analyser import (
                analysiere_foto,
                analysiere_fotos_bis_erster_treffer,
                analysiere_fotos_hybrid_bis_erster_treffer,
            )

            cancel_check = self._qr_cancel_check
            scan_opts = self._qr_photo_scan_kwargs()
            _progress = self._make_qr_progress_callback("photo")

            if len(photo_paths) == 1:
                photo_path = photo_paths[0]
                if cancel_check():
                    result_queue.put(("cancelled", None))
                    return
                kunde, qr_scan_success = analysiere_foto(photo_path)
                if cancel_check():
                    result_queue.put(("cancelled", None))
                    return
                result_queue.put(("success", (kunde, qr_scan_success, photo_path)))
                return

            use_hybrid = (
                scan_opts.get("parallel_enabled")
                and len(photo_paths) >= 2
            )

            if use_hybrid:
                kunde, qr_scan_success, source_path, cancelled = (
                    analysiere_fotos_hybrid_bis_erster_treffer(
                        photo_paths,
                        progress_callback=_progress,
                        cancel_check=cancel_check,
                        parallel_workers=scan_opts["parallel_workers"],
                    )
                )
            else:
                kunde, qr_scan_success, source_path, cancelled = (
                    analysiere_fotos_bis_erster_treffer(
                        photo_paths,
                        progress_callback=_progress,
                        cancel_check=cancel_check,
                    )
                )

            if cancelled:
                result_queue.put(("cancelled", None))
            else:
                result_queue.put(("success", (kunde, qr_scan_success, source_path)))

        except Exception as e:
            print(f"Fehler im Foto-Batch-Analyse-Thread: {e}")
            result_queue.put(("error", e))

    def _signal_qr_search_stop(self):
        """Stoppt laufende QR-Worker (Treffer, Abbruch oder Fehler)."""
        if hasattr(self, "_qr_cancel_event"):
            self._qr_cancel_event.set()

    def _check_analysis_result(self, video_paths: List[str]):
        """
        Überprüft alle 100ms, ob ein Ergebnis in der Queue liegt.
        Diese Funktion läuft im Haupt-Thread und kann die GUI sicher aktualisieren.
        """
        try:
            # Versuchen, ein Ergebnis zu holen, ohne zu blockieren
            status, result = self.analysis_queue.get_nowait()
        except queue.Empty:
            # Wenn die Queue leer ist, erneut in 100ms prüfen
            self.root.after(100, self._check_analysis_result, video_paths)
            return

        try:
            # --- Ergebnis ist da ---
            self._signal_qr_search_stop()

            if status == "success":
                kunde, qr_scan_success, source_path = result
                self._process_analysis_result(kunde, qr_scan_success, video_paths, source_path)
            elif status == "cancelled":
                print("QR-Analyse in Clips vom Benutzer abgebrochen.")
            elif status == "error":
                messagebox.showerror("Analyse-Fehler",
                                     f"Ein unerwarteter Fehler bei der Videoanalyse ist aufgetreten:\n{result}")
                # Kein _restore_button_state - Preview läuft parallel!
                self._update_form_layout_after_qr(False, None)

        except Exception as e:
            # Allgemeiner Fehler beim Abrufen
            messagebox.showerror("Fehler", f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}")
            # Kein _restore_button_state - Preview läuft parallel!
            self._update_form_layout_after_qr(False, None)
        finally:
            self._dismiss_qr_loading_window()

    def _check_photo_analysis_result(self, photo_path: str):
        """Legacy-Polling für Einzelfoto-QR (wird nicht mehr direkt aufgerufen)."""
        self._check_photo_batch_analysis_result()

    def _check_photo_batch_analysis_result(self):
        """Überprüft alle 100ms, ob ein Ergebnis der Foto-QR-Analyse in der Queue liegt."""
        try:
            status, result = self.analysis_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._check_photo_batch_analysis_result)
            return

        try:
            self._signal_qr_search_stop()

            batch_mode = getattr(self, "_photo_qr_batch_mode", False)
            self._photo_qr_batch_mode = False

            if status == "success":
                kunde, qr_scan_success, source_path = result
                self._process_photo_analysis_result(
                    kunde,
                    qr_scan_success,
                    source_path,
                    batch_scan=batch_mode,
                )
            elif status == "cancelled":
                print("Foto-QR-Suche vom Benutzer abgebrochen.")
            elif status == "error":
                messagebox.showerror(
                    "Analyse-Fehler",
                    f"Ein unerwarteter Fehler bei der Foto-Analyse ist aufgetreten:\n{result}",
                )
                if not batch_mode:
                    self._update_form_layout_after_qr(False, None)

        except Exception as e:
            self._photo_qr_batch_mode = False
            messagebox.showerror(
                "Fehler",
                f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}",
            )
        finally:
            self._dismiss_qr_loading_window()

    def _get_media_duration_seconds(self, media_path: str):
        """Ermittelt die Medien-Dauer in Sekunden (ffprobe)."""
        if not media_path:
            return None
        if self.video_preview and hasattr(self.video_preview, "_get_video_duration_seconds"):
            try:
                return self.video_preview._get_video_duration_seconds(media_path)
            except Exception:
                pass
        try:
            import subprocess
            from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW

            command = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                media_path,
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW,
            )
            return float(result.stdout.strip())
        except Exception as e:
            print(f"Konnte Medien-Dauer nicht ermitteln ({media_path}): {e}")
            return None

    def _maybe_remove_qr_source_after_scan(self, media_type: str, source_path: Optional[str]):
        """Entfernt QR-Träger-Medien nach erfolgreicher Analyse, wenn in den Settings aktiviert."""
        if not source_path or not self.drag_drop:
            return

        settings = self.config.get_settings()

        if media_type == "photo":
            if not settings.get("qr_remove_photo_after_scan", False):
                return
            if source_path not in self.drag_drop.photo_paths:
                return
            print(f"Entferne QR-Foto nach Analyse: {os.path.basename(source_path)}")
            self.drag_drop.remove_photo(source_path, update_preview=True)
            return

        if media_type != "video":
            return

        if not settings.get("qr_remove_video_after_scan", False):
            return
        if source_path not in self.drag_drop.video_paths:
            return

        max_duration = float(settings.get("qr_remove_video_max_duration_sec", 10))
        duration = self._get_media_duration_seconds(source_path)
        if duration is None:
            print(f"QR-Video nicht entfernt (Dauer unbekannt): {os.path.basename(source_path)}")
            return
        if duration > max_duration:
            print(
                f"QR-Video nicht entfernt ({duration:.1f}s > {max_duration}s): "
                f"{os.path.basename(source_path)}"
            )
            return

        print(f"Entferne QR-Videoclip nach Analyse ({duration:.1f}s): {os.path.basename(source_path)}")
        self.discard_pending_cuts_for_path(source_path)
        self.drag_drop.remove_video(source_path, update_preview=True)

    def _process_analysis_result(self, kunde, qr_scan_success, video_paths, source_path=None):
        """
        Verarbeitet das erfolgreiche Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code gescannt: Kunden ID Hash {kunde.kunden_id_hash}, "
                      f"Booking ID Hash {kunde.booking_id_hash}, "
                      f"Email: {kunde.email}, Telefon: {kunde.telefon}, "
                      f"Handcam Foto: {kunde.handcam_foto}, Handcam Video: {kunde.handcam_video}, "
                      f"Outside Foto: {kunde.outside_foto}, Outside Video: {kunde.outside_video}")

                info_text = (
                    f"Kunde erkannt:\n\n"
                    f"Kunden ID Hash: {kunde.kunden_id_hash}\n"
                    f"Booking ID Hash: {kunde.booking_id_hash}\n"
                    f"Name: {kunde.vorname} {kunde.nachname}\n"
                    f"Email: {kunde.email}\n"
                    f"Telefon: {kunde.telefon}\n"
                    f"Handcam Foto: {'Ja' if kunde.handcam_foto else 'Nein'}\n"
                    f"Handcam Video: {'Ja' if kunde.handcam_video else 'Nein'}\n"
                    f"Outside Foto: {'Ja' if kunde.outside_foto else 'Nein'}\n"
                    f"Outside Video: {'Ja' if kunde.outside_video else 'Nein'}\n"
                    f"Möchten Sie fortfahren?"
                )
                # Dialog entfernt - QR-Code wurde gefunden und wird automatisch verarbeitet
                print(f"QR-Code erfolgreich gescannt: {kunde.vorname} {kunde.nachname}")

            elif qr_scan_success and not kunde:
                messagebox.showwarning("Ungültiger QR-Code", "Ein QR-Code wurde erkannt, aber die Daten sind ungültig.")

            else:
                # Dialog entfernt - Wechsel zu manueller Eingabe erfolgt automatisch
                print("Kein QR-Code in den Clips gefunden. Wechsle zu manueller Eingabe.")
                if (
                    self.drag_drop
                    and hasattr(self.drag_drop, "photo_qr_check_enabled")
                    and self.drag_drop.photo_qr_check_enabled.get()
                    and self.drag_drop.photo_paths
                ):
                    print("Starte Foto-QR-Suche nach fehlgeschlagener Video-QR-Analyse...")
                    self.run_photo_batch_qr_analysis(self.drag_drop.photo_paths.copy())

            # Formular-Layout aktualisieren
            self._update_form_layout_after_qr(qr_scan_success, kunde)

            if qr_scan_success and kunde:
                self._maybe_remove_qr_source_after_scan("video", source_path)

            # NEU: Preview läuft bereits parallel! Kein wait_for_preview_thread nötig.
            # Button-Status wird von video_preview._finalize_processing wiederhergestellt
            print("QR-Analyse abgeschlossen. Preview läuft parallel weiter.")

        except Exception as e:
            print(f"Fehler in _process_analysis_result: {e}")
            # Nur wenn Preview NICHT läuft, Button wiederherstellen
            if not (self.video_preview and self.video_preview.processing_thread):
                self._restore_button_state()
            self._update_form_layout_after_qr(False, None)

    def _process_photo_analysis_result(
        self,
        kunde,
        qr_scan_success,
        photo_path,
        *,
        batch_scan: bool = False,
    ):
        """
        Verarbeitet das erfolgreiche Foto-QR-Code-Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code im Foto gescannt: Kunden ID Hash {kunde.kunden_id_hash}, "
                      f"Booking ID Hash {kunde.booking_id_hash}, Email: {kunde.email}, "
                      f"Name: {kunde.vorname} {kunde.nachname}")

                self._update_form_layout_after_qr(qr_scan_success, kunde)
                self._maybe_remove_qr_source_after_scan("photo", photo_path)

            elif qr_scan_success and not kunde:
                messagebox.showwarning(
                    "Ungültiger QR-Code",
                    "Ein QR-Code wurde im Foto erkannt, aber die Daten sind ungültig.",
                )
                if not batch_scan:
                    self._update_form_layout_after_qr(False, None)

            else:
                if batch_scan:
                    print("Kein gültiger QR-Code in den importierten Fotos gefunden.")
                else:
                    basename = os.path.basename(photo_path) if photo_path else "?"
                    messagebox.showwarning(
                        "Kein QR-Code gefunden",
                        f"Kein gültiger QR-Code im Foto gefunden:\n{basename}",
                    )
                    self._update_form_layout_after_qr(False, None)

        except Exception as e:
            print(f"Fehler in _process_photo_analysis_result: {e}")
            if not batch_scan:
                self._update_form_layout_after_qr(False, None)

    def erstelle_video(self):
        """Bereitet die Videoerstellung mit Intro vor"""
        # Formulardaten sammeln
        form_data = self.form_fields.get_form_data()

        # Server-Upload Einstellung hinzufügen
        form_data["upload_to_server"] = self.upload_to_server_var.get()

        # Prüfe Server-Verbindung wenn Upload aktiviert
        if form_data["upload_to_server"] and not self.server_connected:
            messagebox.showwarning(
                "Server nicht erreichbar",
                "Server-Upload ist aktiviert, aber keine Verbindung zum Server verfügbar.\n\n"
                "Bitte überprüfen Sie die Server-Einstellungen oder deaktivieren Sie den Upload."
            )
            return

        # Verwende das kombinierte Video aus der Vorschau
        combined_video_path = self.video_preview.get_combined_video_path()
        # Foto-Pfade holen
        photo_paths = self.drag_drop.get_photo_paths()

        # Physische Anwesenheit von Dateien prüfen
        has_video = combined_video_path and os.path.exists(combined_video_path)
        has_photos = photo_paths and len(photo_paths) > 0

        # Ausgewählte Produkte aus form_data holen
        video_produkt_gewaehlt = form_data.get("handcam_video", False) or form_data.get("outside_video", False)
        foto_produkt_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)

        # Prüfen ob Video gewählt aber nicht bezahlt ist
        video_gewaehlt_aber_nicht_bezahlt = (
                (form_data.get("handcam_video", False) and not form_data.get("ist_bezahlt_handcam_video", False)) or
                (form_data.get("outside_video", False) and not form_data.get("ist_bezahlt_outside_video", False))
        )

        # 1. Prüfen, ob überhaupt ein Produkt ausgewählt ist.
        if not video_produkt_gewaehlt and not foto_produkt_gewaehlt:
            messagebox.showwarning("Fehler",
                                   "Bitte wählen Sie mindestens ein Produkt aus\n"
                                   "(Handcam Foto/Video oder Outside Foto/Video).")
            return

        # 2. Prüfen auf Diskrepanz: Produkt ausgewählt, aber keine Datei da
        error_messages = []
        if video_produkt_gewaehlt and not has_video:
            error_messages.append("Sie haben ein Video-Produkt ausgewählt, aber keine Videos hinzugefügt.")

        if foto_produkt_gewaehlt and not has_photos:
            error_messages.append("Sie haben ein Foto-Produkt ausgewählt, aber keine Fotos hinzugefügt.")

        # Zeige Fehler, wenn Produkt ausgewählt, aber Datei fehlt
        if error_messages:
            messagebox.showwarning("Fehlende Dateien", "\n\n".join(error_messages))
            return

        # NEU: Foto-Wasserzeichen-Validierung
        foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
        foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
        foto_wm_erforderlich = foto_gewaehlt and not foto_bezahlt

        watermark_photo_indices = self.drag_drop.get_watermark_photo_indices()

        if foto_wm_erforderlich and not watermark_photo_indices:
            messagebox.showwarning("Fehlende Auswahl",
                                   "Sie haben ein Foto-Produkt als 'nicht bezahlt' markiert, aber kein Foto für das Wasserzeichen ausgewählt.\n\n"
                                   "Bitte wählen Sie mindestens ein Foto in der '💧' Spalte aus.")
            return

        # Parse Kundendaten aus der Formular-Eingabe
        form_mode = form_data.get("form_mode")
        kunden_id_hash_val = form_data.get("kunden_id_hash", "").strip()
        booking_id_hash_val = form_data.get("booking_id_hash", "").strip()
        kunden_id_val = form_data.get("kunden_id", "").strip()
        booking_id_val = form_data.get("booking_id", "").strip()

        kunde = Kunde(
            kunden_id_hash=kunden_id_hash_val or None,
            booking_id_hash=booking_id_hash_val or None,
            kunden_id=(kunden_id_val or None) if form_mode == "manual" else None,
            booking_id=(booking_id_val or None) if form_mode == "manual" else None,
            vorname=str(form_data["vorname"]),
            nachname=str(form_data["nachname"]),
            email=(form_data.get("email", "").strip() or None),
            telefon=(form_data.get("telefon", "").strip() or None),
            handcam_foto=bool(form_data["handcam_foto"]),
            handcam_video=bool(form_data["handcam_video"]),
            outside_foto=bool(form_data["outside_foto"]),
            outside_video=bool(form_data["outside_video"]),
            ist_bezahlt_handcam_foto=bool(form_data["ist_bezahlt_handcam_foto"]),
            ist_bezahlt_handcam_video=bool(form_data["ist_bezahlt_handcam_video"]),
            ist_bezahlt_outside_foto=bool(form_data["ist_bezahlt_outside_foto"]),
            ist_bezahlt_outside_video=bool(form_data["ist_bezahlt_outside_video"])
        )

        # Validierung der Formulardaten (Textfelder)
        oldschool_mode = bool(self.config.get_settings().get("oldschool_mode", False))
        errors = validate_form_data(
            form_data,
            (video_produkt_gewaehlt or foto_produkt_gewaehlt),
            oldschool_mode=oldschool_mode,
        )
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
            return

        if getattr(self, "_pending_cuts_batch_running", False):
            messagebox.showwarning(
                "Warteschlange aktiv",
                "Die geplanten Videoschnitte werden gerade verarbeitet.\n\n"
                "Bitte warten Sie, bis die Warteschlange fertig ist, bevor Sie „Erstellen“ starten.",
                parent=self.root,
            )
            return

        if self.pending_video_cuts:
            n = len(self.pending_video_cuts)
            if n == 1:
                qtext = "Es liegt noch 1 geplanter Videoschnitt in der Warteschlange.\n\n"
            else:
                qtext = f"Es liegen noch {n} geplante Videoschnitte in der Warteschlange.\n\n"
            messagebox.showwarning(
                "Ausstehende Schnitte",
                qtext
                + "Bitte wenden Sie zuerst die Warteschlange an (Button „Warteschlange anwenden …“ in der "
                "Video-Liste), bevor die Kodierung startet.",
                parent=self.root,
            )
            return

        # Einstellungen speichern
        settings_data = self.form_fields.get_settings_data()
        settings_data["upload_to_server"] = form_data["upload_to_server"]
        self.config.save_settings(settings_data)

        # GUI für Verarbeitung vorbereiten
        video_count = len(self.drag_drop.get_video_paths()) if has_video else 0
        photo_count = len(photo_paths)

        status_parts = []
        if video_produkt_gewaehlt:
            if video_gewaehlt_aber_nicht_bezahlt:
                status_parts.append(f"Erstelle {video_count} Video(s) mit Wasserzeichen (nicht bezahlt)")
            else:
                status_parts.append(f"Verarbeite {video_count} Video(s)")

        if foto_produkt_gewaehlt:
            status_parts.append(f"Kopiere {photo_count} Foto(s)")

        status_text = "Status: " + " und ".join(status_parts)

        if form_data["upload_to_server"]:
            status_text += " - Lade auf Server hoch"

        status_text += "... Bitte warten."

        self.progress_handler.set_status(status_text)
        self._switch_to_cancel_mode()

        # VideoProcessor initialisieren
        from ..video.processor import VideoProcessor

        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update,
            encoding_progress_callback=self._update_encoding_progress,
            upload_progress_callback=self._update_upload_progress,
            config_manager=self.config
        )

        payload = {
            "form_data": form_data,
            "combined_video_path": combined_video_path if has_video else None,
            "video_clip_paths": self.drag_drop.get_video_paths() if has_video else [],  # NEU: Einzelne Clips
            "kunde": kunde,
            "photo_paths": photo_paths,
            "photo_import_epochs": {
                os.path.normpath(p): self.drag_drop.get_source_import_epoch(p)
                for p in photo_paths
            },
            "settings": self.config.get_settings(),
            "create_watermark_version": video_gewaehlt_aber_nicht_bezahlt,
            "watermark_clip_index": self.drag_drop.get_watermark_clip_index(),  # NEU: Index des ausgewählten Clips
            "watermark_photo_indices": watermark_photo_indices  # NEU: Foto-Indizes
        }

        print('kunde in erstelle_video:', kunde)

        video_thread = threading.Thread(
            target=self.video_processor.create_video_with_intro_only,
            args=(payload,)
        )
        video_thread.start()

    def _update_progress(self, step, total_steps=8):
        """Callback für Fortschrittsupdates"""
        self.root.after(0, self.progress_handler.update_progress, step, total_steps)

    def _update_encoding_progress(self, task_name="Encoding", progress=None, fps=0.0, eta=None,
                                  current_time=0.0, total_time=None, task_id=None, encoding_lane=0):
        """Callback für Live-Encoding-Fortschritt"""
        self.root.after(
            0,
            self.progress_handler.update_encoding_progress,
            task_name,
            progress,
            fps,
            eta,
            current_time,
            total_time,
            task_id,
            encoding_lane,
        )

        # Update Drag&Drop Tabelle wenn task_id vorhanden (= Video-Index)
        if task_id is not None and progress is not None:
            # Aktiviere Progress-Modus beim ersten Update
            if not self.drag_drop.is_encoding:
                self.root.after(0, self.drag_drop.show_progress_mode)

            # Update Progress für das Video
            self.root.after(0, self.drag_drop.update_video_progress, task_id, progress, fps, eta)

        # Video-Vorschau: nur Leiste 0 spiegeln (paralleler Wasserzeichen-Job nutzt Leiste 1)
        if (
            encoding_lane == 0
            and hasattr(self, "video_preview")
            and self.video_preview
            and progress is not None
        ):
            self.root.after(
                0,
                self.video_preview.update_encoding_progress,
                progress,
                fps,
                eta,
                task_name,
            )

    def _update_upload_progress(
        self,
        *,
        percent=0.0,
        current_file=0,
        total_files=0,
        current_bytes=0,
        total_bytes=0,
        filename="",
    ):
        """Callback für Live-Server-Upload-Fortschritt"""
        self.root.after(
            0,
            self.progress_handler.update_upload_progress,
            percent,
            current_file,
            total_files,
            current_bytes,
            total_bytes,
            filename,
        )

    def _handle_status_update(self, status_type, message):
        """Callback für Statusupdates"""
        if status_type == "success":
            # message ist jetzt ein Dict mit created_items
            if isinstance(message, dict):
                from .components.success_dialog import show_success_dialog
                self.root.after(0, lambda: show_success_dialog(self.root, message))
            else:
                # Fallback für alte Text-Nachrichten
                self.root.after(0, lambda: messagebox.showinfo("Fertig", message))

            self.root.after(0, self.progress_handler.set_status, "Status: Fertig.")

            # NEU: Auto-Clear nach erfolgreichem Erstellen
            if self.auto_clear_files_var.get():
                self.root.after(0, self._clear_all_files_after_success)

        elif status_type == "error":
            self.root.after(0, lambda: messagebox.showerror("Fehler", message))
            self.root.after(0, self.progress_handler.set_status, "Status: Fehler aufgetreten.")
        elif status_type == "cancelled":
            self.root.after(0, self.progress_handler.set_status, "Status: Erstellung abgebrochen.")
        elif status_type == "update":
            self.root.after(0, self.progress_handler.set_status, f"Status: {message}.")
            return

        # Zurück zu Normal-Modus in Drag&Drop
        if hasattr(self, 'drag_drop') and self.drag_drop and self.drag_drop.is_encoding:
            self.root.after(0, self.drag_drop.show_normal_mode)

        self.root.after(0, self._switch_to_create_mode)

    def _clear_all_files_after_success(self):
        """Setzt Session nach erfolgreichem Erstellen zurück (Formular + Medien)."""
        try:
            print("🗑️ Auto-Clear: Setze Formular und importierte Medien zurück...")
            self._apply_session_reset(update_progress_status=False)
            print("✅ Auto-Clear abgeschlossen")
        except Exception as e:
            print(f"⚠️ Fehler beim Auto-Clear: {e}")

    def _startup_cache_sweep(self):
        """Entfernt verwaiste Preview-Temp-Ordner nach App-Start (ohne aktive Session)."""
        exclude = None
        if getattr(self, "video_preview", None) and self.video_preview.temp_dir:
            exclude = self.video_preview.temp_dir

        def run():
            from ..utils.cache_cleanup import CacheCleanupService

            result = CacheCleanupService.cleanup_orphans_only(exclude_temp_dir=exclude)
            if result.deleted_dirs or result.deleted_files:
                print(
                    f"Startup-Cache-Sweep: {len(result.deleted_dirs)} Ordner, "
                    f"{len(result.deleted_files)} Dateien entfernt."
                )

        threading.Thread(target=run, daemon=True).start()

    def clear_application_cache(self, include_hw_cache: bool = False):
        """
        Leert zuerst Formular/Medien der aktuellen Session und löscht danach Cache-Dateien.
        """
        from ..utils.cache_cleanup import CacheCleanupService

        settings = self.config.get_settings()
        speicherort = settings.get("speicherort")
        import_paths = []
        if self.drag_drop:
            import_paths = list(self.drag_drop.get_video_paths()) + list(
                self.drag_drop.get_photo_paths()
            )
        base_paths = CacheCleanupService.collect_work_base_paths(
            speicherort=speicherort,
            import_paths=import_paths,
        )

        self._clear_session_state_for_cache_cleanup()
        return CacheCleanupService.cleanup_all(
            base_paths_for_work=base_paths,
            include_hw_cache=include_hw_cache,
        )

    def _clear_session_state_for_cache_cleanup(self):
        """Leert Session-Daten ohne Bestätigungsdialog (Formular + importierte Medien)."""
        if hasattr(self, "video_preview") and self.video_preview:
            self.video_preview.cancel_creation()
            self.video_preview.clear_preview()

        if self.drag_drop:
            self.drag_drop.clear_all()

        if self.form_fields:
            settings = self.config.get_settings()
            self.form_fields.tandemmaster_var.set("")
            settings["tandemmaster"] = ""
            self.form_fields.videospringer_var.set("")
            settings["videospringer"] = ""
            self.form_fields.gast_name_var.set("")
            settings["gast_name"] = ""
            self.config.save_settings(settings)

        if hasattr(self, "progress_handler") and self.progress_handler:
            self.progress_handler.set_status("Status: Bereit.")

        self.update_watermark_column_visibility()

    def _is_session_reset_blocked(self):
        """True wenn Zurücksetzen nicht angeboten werden soll (laufende Erstellung / Analyse)."""
        if getattr(self, "loading_window", None):
            return True, (
                "Bitte warten Sie, bis die QR-Analyse abgeschlossen ist,\n"
                "oder schließen Sie das Lade-Fenster."
            )
        btn = self.erstellen_button
        if btn:
            txt = btn.cget("text")
            if txt in ("Abbrechen", "Bitte warten...", "Kodierung läuft..."):
                return True, "Zurücksetzen ist während der Videoerstellung nicht möglich."
        return False, ""

    def _apply_session_reset(self, *, respect_keep_flags: bool = True, update_progress_status: bool = True):
        """
        Leert importierte Medien und setzt das Formular auf den manuellen Modus zurück.

        respect_keep_flags: Tandemmaster/Videospringer gemäß Einstellungen beibehalten.
        """
        keep_tm = False
        keep_vs = False
        tm_snapshot = ""
        vs_snapshot = ""
        if self.form_fields:
            snap_settings = self.config.get_settings()
            if respect_keep_flags:
                keep_tm = _truthy_session_keep_flag(
                    snap_settings.get("keep_tandemmaster_on_session_reset", False))
                keep_vs = _truthy_session_keep_flag(
                    snap_settings.get("keep_videospringer_on_session_reset", False))
            tm_snapshot = self.form_fields.tandemmaster_var.get()
            vs_snapshot = self.form_fields.videospringer_var.get()

        if hasattr(self, "video_preview") and self.video_preview:
            self.video_preview.cancel_creation()

        self._session_reset_in_progress = True
        try:
            if self.drag_drop:
                self.drag_drop.clear_all()

            if self.form_fields:
                settings = self.config.get_settings()
                settings["gast_name"] = ""
                settings["tandemmaster"] = tm_snapshot if keep_tm else ""
                settings["videospringer"] = vs_snapshot if keep_vs else ""
                self.config.save_settings(settings)

                self.form_fields._last_layout_signature = None
                self.form_fields._last_qr_success = False
                self.form_fields._last_kunde = None
                self.form_fields.update_form_layout(False, None)

                self.form_fields.gast_name_var.set("")
                self.form_fields.tandemmaster_var.set(tm_snapshot if keep_tm else "")
                self.form_fields.videospringer_var.set(vs_snapshot if keep_vs else "")

                settings = self.config.get_settings()
                settings["gast_name"] = ""
                settings["tandemmaster"] = self.form_fields.tandemmaster_var.get()
                settings["videospringer"] = self.form_fields.videospringer_var.get()
                self.config.save_settings(settings)
        finally:
            self._session_reset_in_progress = False

        if update_progress_status and hasattr(self, "progress_handler") and self.progress_handler:
            self.progress_handler.set_status("Status: Bereit.")

        self.update_watermark_column_visibility()

    def reset_session(self):
        """Leert Formular (manueller Modus) und alle importierten Medien nach Bestätigung."""
        blocked, reason = self._is_session_reset_blocked()
        if blocked:
            messagebox.showwarning("Zurücksetzen nicht möglich", reason, parent=self.root)
            return

        if not messagebox.askyesno(
            "Alles zurücksetzen?",
            "Alle Eingaben im Formular und alle importierten Videos und Fotos "
            "werden verworfen.\n\nFortfahren?",
            parent=self.root,
        ):
            return

        blocked, reason = self._is_session_reset_blocked()
        if blocked:
            messagebox.showwarning("Zurücksetzen nicht möglich", reason, parent=self.root)
            return

        try:
            self._apply_session_reset()
        except Exception as e:
            print(f"⚠️ Fehler beim Zurücksetzen: {e}")
            messagebox.showerror("Zurücksetzen", f"Fehler beim Zurücksetzen:\n{e}", parent=self.root)

    def on_files_added(self, has_videos, has_photos):
        """Wird von DragDropFrame aufgerufen, um FormFields zu aktualisieren."""
        if self.form_fields:
            self.form_fields.auto_check_products(has_videos, has_photos)

    def update_watermark_column_visibility(self):
        """Aktualisiert die Sichtbarkeit der Wasserzeichen-Spalte basierend auf Kunde-Status"""
        form_data = self.form_fields.get_form_data()

        # --- Video-Logik ---
        video_gewaehlt = form_data.get("handcam_video", False) or form_data.get("outside_video", False)
        video_bezahlt = form_data.get("ist_bezahlt_handcam_video", False) or form_data.get("ist_bezahlt_outside_video", False)
        video_wm_sichtbar = video_gewaehlt and not video_bezahlt

        # Debug-Ausgabe
        print(f"🔍 Video-Wasserzeichen-Spalte Update:")
        print(f"   Handcam Video: {form_data.get('handcam_video', False)}, Bezahlt: {form_data.get('ist_bezahlt_handcam_video', False)}")
        print(f"   Outside Video: {form_data.get('outside_video', False)}, Bezahlt: {form_data.get('ist_bezahlt_outside_video', False)}")
        print(f"   → Spalte sichtbar: {video_wm_sichtbar}")

        if self._last_video_wm_visible != video_wm_sichtbar:
            # Zeige Spalte wenn Video ausgewählt aber nicht bezahlt ist
            self.drag_drop.set_watermark_column_visible(video_wm_sichtbar)

            # Wenn spalte nicht mehr sichtbar, lösche Auswahl
            if not video_wm_sichtbar:
                self.drag_drop.clear_watermark_selection()

            # NEU: Button in VideoPreview steuern
            if hasattr(self, 'video_preview'):
                self.video_preview.set_wm_button_visibility(video_wm_sichtbar)
                self.video_preview.update_wm_button_state()  # Status aktualisieren

            self._last_video_wm_visible = video_wm_sichtbar

        # --- NEU: Foto-Logik ---
        foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
        foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
        foto_wm_sichtbar = foto_gewaehlt and not foto_bezahlt

        print(f"🔍 Foto-Wasserzeichen-Spalte Update:")
        print(f"   Foto gewählt: {foto_gewaehlt}, Foto bezahlt: {foto_bezahlt}")
        print(f"   → Spalte sichtbar: {foto_wm_sichtbar}")

        if self._last_photo_wm_visible != foto_wm_sichtbar:
            # Rufe die neue Methode in drag_drop auf
            self.drag_drop.set_photo_watermark_column_visible(foto_wm_sichtbar)

            # Wenn spalte nicht mehr sichtbar, lösche Auswahl
            if not foto_wm_sichtbar:
                self.drag_drop.clear_photo_watermark_selection()

            # NEU: Button in PhotoPreview steuern
            if hasattr(self, 'photo_preview'):
                self.photo_preview.set_wm_button_visibility(foto_wm_sichtbar)
                self.photo_preview.update_wm_button_state()  # Status aktualisieren

            self._last_photo_wm_visible = foto_wm_sichtbar


    def _switch_to_cancel_mode(self):
        """Wechselt den Button zum Abbrechen-Modus"""
        # Initial: Button deaktivieren während der Kodierung
        self.erstellen_button.config(
            text="Kodierung läuft...",
            bg="#808080",
            state="disabled"
        )

        # Nach kurzer Verzögerung: Button als "Abbrechen" aktivieren
        def enable_cancel_button():
            self._cancel_timer_id = None
            self.erstellen_button.config(
                text="Abbrechen",
                command=self.abbrechen_prozess,
                bg="#D32F2F",
                state="normal"
            )

        # Aktiviere den Abbrechen-Button nach 500ms
        self._cancel_timer_id = self.root.after(500, enable_cancel_button)

        # Zeige Progress-Elemente rechts oben
        self.progress_handler.pack_progress_bar_right()
        self.progress_handler.progress_bar['value'] = 0

    def _switch_to_create_mode(self):
        """Wechselt den Button zurück zum Erstellen-Modus"""
        if hasattr(self, '_cancel_timer_id') and self._cancel_timer_id:
            self.root.after_cancel(self._cancel_timer_id)
            self._cancel_timer_id = None

        self.erstellen_button.config(
            text="Erstellen",
            command=self.erstelle_video,
            bg="#4CAF50",
            state="normal"
        )
        self.progress_handler.reset()

    def abbrechen_prozess(self):
        """Bricht die laufende Videoerstellung ab"""
        self.progress_handler.set_status("Status: Abbruch wird eingeleitet...")
        self.erstellen_button.config(state="disabled")

        if self.video_processor:
            self.video_processor.cancel_process()

    # --- NEUE WASSERZEICHEN-PROXY-METHODEN ---

    def toggle_video_watermark(self, index):
        """Wird von VideoPreview aufgerufen, leitet an DragDrop weiter."""
        if not hasattr(self, 'drag_drop'):
            return

        # 1. Status in drag_drop ändern
        self.drag_drop.toggle_video_watermark_at_index(index)

        # 2. Button-Status in video_preview aktualisieren
        if hasattr(self, 'video_preview'):
            self.video_preview.update_wm_button_state()

    def toggle_photo_watermark(self, index):
        """Wird von PhotoPreview aufgerufen, leitet an DragDrop weiter."""
        if not hasattr(self, 'drag_drop'):
            return

        # 1. Status in drag_drop ändern
        self.drag_drop.toggle_photo_watermark_at_index(index)

        # 2. Button-Status in photo_preview aktualisieren
        if hasattr(self, 'photo_preview'):
            self.photo_preview.update_wm_button_state()

    def set_photo_watermark_for_indices(self, indices, marked: bool):
        """Setzt Preview-Status für mehrere Foto-Indizes in einem Schritt."""
        if not hasattr(self, "drag_drop"):
            return

        self.drag_drop.set_photo_watermark_for_indices(indices, marked)

        if hasattr(self, "photo_preview"):
            self.photo_preview.update_wm_button_state()

    # --- NEUE METHODEN FÜR DEN SCHNEIDE-DIALOG ---

    def request_cut_dialog(self, video_path: str, index: int):
        """
        Wird von drag_drop.py aufgerufen, um den Schneide-Dialog zu öffnen.

        video_path ist nach dem ersten update_preview bereits ein Working-Folder-Pfad!
        """
        if self.video_cutter_dialog is not None:
            print("Ein Schneide-Dialog ist bereits geöffnet.")
            self.video_cutter_dialog.lift()
            return

        if not os.path.exists(video_path):
            messagebox.showerror("Fehler",
                                 f"Video '{os.path.basename(video_path)}' konnte nicht gefunden werden.")
            return

        # Dialog erstellen - video_path ist bereits der Working-Folder-Pfad!
        from .components.video_cutter import VideoCutterDialog

        self.video_cutter_dialog = VideoCutterDialog(
            self.root,
            video_path=video_path,
            on_complete_callback=lambda result: self.on_cut_complete(video_path, index, result)
        )

        # 4. Callback binden, um Referenz zu löschen, wenn Dialog geschlossen wird
        self.video_cutter_dialog.bind("<Destroy>", self._on_cutter_dialog_close)

        self.video_cutter_dialog.show()

    def on_cut_complete(self, original_path: str, index: int, result: dict):
        """
        Callback vom VideoCutterDialog (Warteschlange oder direkte Ergebnisse).
        """
        action = result.get("action")

        if action == "cancel":
            print(f"App: Schneiden von '{os.path.basename(original_path)}' abgebrochen.")
            return

        if action == "queue_trim":
            self._enqueue_pending_trim(original_path, index, result)
            return

        if action == "queue_split":
            self._enqueue_pending_split(original_path, index, result)
            return

        paths_to_refresh = self._sync_apply_cut_or_split_result(original_path, index, result)
        if paths_to_refresh and self.video_preview:
            self.video_preview.refresh_metadata_async(
                paths_to_refresh,
                on_complete_callback=self._on_metadata_refreshed,
            )

    def _sync_apply_cut_or_split_result(self, original_path: str, index: int, result: dict) -> List[str]:
        """Aktualisiert Listen/Vorschau wie nach einem fertigen Schnitt, ohne Metadaten-Thread."""
        action = result.get("action")
        paths_to_refresh: List[str] = []

        if action == "cut":
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geschnitten (getrimmt).")
            if self.video_preview:
                self.video_preview.register_new_copy(original_path, original_path)
                print(f"Getrimmtes Video registriert: {os.path.basename(original_path)}")
            paths_to_refresh.append(original_path)

        elif action == "split":
            part1_path = result.get("part1_path")
            part2_path = result.get("part2_path")
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geteilt.")
            print(f"     Teil 1: {os.path.basename(part1_path) if part1_path else 'N/A'}")
            print(f"     Teil 2: {os.path.basename(part2_path) if part2_path else 'N/A'}")

            if not part1_path or not part2_path:
                print("⚠️ Fehler: Split-Pfade nicht verfügbar")
                return []

            if self.drag_drop:
                self.drag_drop.video_paths[index] = part1_path
                print(
                    f"DragDrop: Ersetze Original an Index {index} durch Teil 1: {os.path.basename(part1_path)}"
                )
                self.drag_drop.insert_video_path_at_index(part2_path, index + 1)

            if self.video_preview:
                self.video_preview.register_new_copy(part1_path, part1_path)
                self.video_preview.register_new_copy(part2_path, part2_path)

            paths_to_refresh.extend([part1_path, part2_path])

        return paths_to_refresh

    def _enqueue_pending_trim(self, original_path: str, index: int, result: dict):
        had_same = any(p.source_path == original_path for p in self.pending_video_cuts)
        self.pending_video_cuts = [p for p in self.pending_video_cuts if p.source_path != original_path]
        self.pending_video_cuts.append(
            PendingVideoCut(
                source_path=original_path,
                list_index=index,
                kind="trim",
                start_ms=result["start_ms"],
                end_ms=result["end_ms"],
            )
        )
        if had_same:
            print("Hinweis: Ausstehender Schnitt für dieselbe Datei wurde ersetzt.")
        self._update_pending_cuts_ui()

    def _enqueue_pending_split(self, original_path: str, index: int, result: dict):
        had_same = any(p.source_path == original_path for p in self.pending_video_cuts)
        self.pending_video_cuts = [p for p in self.pending_video_cuts if p.source_path != original_path]
        self.pending_video_cuts.append(
            PendingVideoCut(
                source_path=original_path,
                list_index=index,
                kind="split",
                split_ms=result["split_ms"],
            )
        )
        if had_same:
            print("Hinweis: Ausstehender Schnitt für dieselbe Datei wurde ersetzt.")
        self._update_pending_cuts_ui()

    def _update_pending_cuts_ui(self):
        n = len(self.pending_video_cuts)
        if self.drag_drop:
            self.drag_drop.set_pending_cuts_count(n)
        if self.progress_handler:
            if n:
                self.progress_handler.set_status(f"Status: {n} Schnitt(e) in der Warteschlange.")
            else:
                self.progress_handler.set_status("Status: Bereit.")

    def clear_pending_video_cuts(self):
        self.pending_video_cuts.clear()
        self._update_pending_cuts_ui()

    def discard_pending_cuts_for_path(self, path: str):
        self.pending_video_cuts = [p for p in self.pending_video_cuts if p.source_path != path]
        self._update_pending_cuts_ui()

    def request_apply_pending_cuts(self):
        if not self.pending_video_cuts:
            messagebox.showinfo(
                "Warteschlange",
                "Es sind keine ausstehenden Schnitte geplant.",
                parent=self.root,
            )
            return
        self._open_pending_cuts_review_dialog()

    def _open_pending_cuts_review_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Ausstehende Schnitte")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("+%d+%d" % (self.root.winfo_rootx() + 50, self.root.winfo_rooty() + 50))

        tk.Label(
            dlg,
            text="Geplante Operationen (von oben nach unten nacheinander):",
            font=("Arial", 10, "bold"),
        ).pack(anchor="w", padx=10, pady=(10, 4))

        lb_h = min(16, max(4, len(self.pending_video_cuts) + 2))
        lb = tk.Listbox(dlg, width=92, height=lb_h, font=("Consolas", 9))
        for p in self.pending_video_cuts:
            lb.insert(tk.END, p.summary_line())
        lb.pack(fill="both", expand=True, padx=10, pady=6)

        btn_fr = tk.Frame(dlg)
        btn_fr.pack(fill="x", padx=10, pady=8)

        def refresh_list():
            lb.delete(0, tk.END)
            for p in self.pending_video_cuts:
                lb.insert(tk.END, p.summary_line())
            self._update_pending_cuts_ui()

        def remove_sel():
            sel = lb.curselection()
            if not sel:
                return
            i = int(sel[0])
            if 0 <= i < len(self.pending_video_cuts):
                self.pending_video_cuts.pop(i)
                refresh_list()

        def apply_all():
            if not self.pending_video_cuts:
                dlg.destroy()
                return
            if not messagebox.askokcancel(
                "Schnitte anwenden",
                f"{len(self.pending_video_cuts)} geplante Schnitt(e) mit FFmpeg verarbeiten?\n"
                "Dies kann je nach Material und Anzahl einige Minuten dauern.",
                parent=dlg,
            ):
                return
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            dlg.destroy()
            self._start_pending_cuts_batch()

        ttk.Button(btn_fr, text="Ausgewähltes entfernen", command=remove_sel).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_fr, text="Alle anwenden …", command=apply_all).pack(side=tk.LEFT, padx=4)

        def close_dlg():
            try:
                dlg.grab_release()
            except tk.TclError:
                pass
            dlg.destroy()

        ttk.Button(btn_fr, text="Schließen", command=close_dlg).pack(side=tk.RIGHT, padx=4)

    def _find_video_index_for_path(self, path: str) -> Optional[int]:
        if not self.drag_drop:
            return None
        try:
            return self.drag_drop.get_video_paths().index(path)
        except ValueError:
            return None

    def _start_pending_cuts_batch(self):
        self._pending_cuts_batch_running = True
        self._suppress_preview_regenerate_after_metadata = True
        self._disable_create_button_for_cut_batch()
        if self.video_preview:
            self.video_preview.halt_preview_for_cut_batch()

        snapshot = list(self.pending_video_cuts)
        self.pending_video_cuts.clear()
        self._update_pending_cuts_ui()

        def runner():
            try:
                self._pending_cuts_batch_thread(snapshot)
            finally:
                self._pending_cuts_batch_running = False
                self._suppress_preview_regenerate_after_metadata = False
                self.root.after(0, self._restore_create_button_after_cut_batch)
                self.root.after(0, self._kick_preview_regenerate_after_batch)

        threading.Thread(target=runner, daemon=True).start()

    def _disable_create_button_for_cut_batch(self):
        """Deaktiviert den Erstellen-Button während der Schnitt-Warteschlange."""
        btn = getattr(self, "erstellen_button", None)
        if not btn:
            return
        if self._cut_batch_button_snapshot is None:
            self._cut_batch_button_snapshot = {
                "text": btn.cget("text"),
                "bg": btn.cget("bg"),
                "state": btn.cget("state"),
            }
        btn.config(text="Schnitt läuft...", bg="#808080", state="disabled")

    def _restore_create_button_after_cut_batch(self):
        """Stellt den vorherigen Zustand des Erstellen-Buttons nach der Warteschlange wieder her."""
        btn = getattr(self, "erstellen_button", None)
        if not btn:
            return
        snapshot = self._cut_batch_button_snapshot
        self._cut_batch_button_snapshot = None
        if snapshot:
            btn.config(
                text=snapshot.get("text", "Erstellen"),
                bg=snapshot.get("bg", "#4CAF50"),
                state=snapshot.get("state", "normal"),
            )

    def _kick_preview_regenerate_after_batch(self):
        """Einmalige Vorschau-Regeneration nach Ende der Schnitt-Warteschlange (Hauptthread)."""
        if not self.video_preview or not self.drag_drop:
            return
        paths = self.drag_drop.get_video_paths()
        if paths:
            self.video_preview.regenerate_preview_after_cut(paths)

    def _restore_pending_snapshot(self, items: List[PendingVideoCut]):
        self.pending_video_cuts = items + self.pending_video_cuts
        self._update_pending_cuts_ui()

    def _pending_cuts_batch_thread(self, snapshot: List[PendingVideoCut]):
        total_items = max(1, len(snapshot))

        def _set_cut_preview_state(progress: float, eta_text: str):
            self._update_encoding_progress(
                task_name="Cutting/Trimming",
                progress=max(0.0, min(100.0, float(progress))),
                eta=eta_text,
                encoding_lane=0,
            )

        _set_cut_preview_state(0, "Schnitt-Warteschlange gestartet")

        for i, item in enumerate(snapshot):
            path = item.source_path
            if not os.path.exists(path):

                def _missing(p=path, rest=snapshot[i:]):
                    messagebox.showerror(
                        "Warteschlange",
                        f"Datei nicht gefunden, Abbruch der Warteschlange:\n{p}",
                        parent=self.root,
                    )
                    self._restore_pending_snapshot(rest)
                    if self.progress_handler:
                        self.progress_handler.set_status("Status: Warteschlange mit Fehler abgebrochen.")
                    _set_cut_preview_state((((i) / total_items) * 100.0), "Abgebrochen (Datei fehlt)")

                self.root.after(0, _missing)
                return

            svc = VideoCutterService()

            def pcb(_pct, msg, step=i + 1, total=len(snapshot)):
                total_safe = max(1, total)
                bounded_pct = max(0.0, min(100.0, float(_pct or 0.0)))
                queue_pct = (((step - 1) + (bounded_pct / 100.0)) / total_safe) * 100.0
                cut_task_name = "Trimming" if item.kind == "trim" else "Cutting"
                eta_text = f"Schnitt {step}/{total_safe} — {msg}"
                self._update_encoding_progress(
                    task_name=cut_task_name,
                    progress=queue_pct,
                    eta=eta_text,
                    encoding_lane=0,
                )
                if self.progress_handler:
                    self.root.after(
                        0,
                        lambda m=msg, s=step, t=total_safe: self.progress_handler.set_status(
                            f"Status: Schnitt {s}/{t} — {m}"
                        ),
                    )

            try:
                if item.kind == "trim":
                    ok = svc.apply_trim_overwrite(
                        path, item.start_ms / 1000.0, item.end_ms / 1000.0, pcb
                    )
                    result: Dict[str, Any] = {"action": "cut"} if ok else {}
                else:
                    p1, p2 = svc.apply_split_overwrite(path, (item.split_ms or 0) / 1000.0, pcb)
                    ok = bool(p1 and p2)
                    result = (
                        {"action": "split", "part1_path": p1, "part2_path": p2} if ok else {}
                    )
            except Exception as e:
                err = str(e)

                def _err_ui(e=err, rest=snapshot[i:]):
                    messagebox.showerror("Warteschlange", f"FFmpeg-Fehler:\n{e}", parent=self.root)
                    self._restore_pending_snapshot(rest)
                    if self.progress_handler:
                        self.progress_handler.set_status("Status: Warteschlange mit Fehler abgebrochen.")
                    _set_cut_preview_state((((i) / total_items) * 100.0), "Abgebrochen (FFmpeg-Fehler)")

                self.root.after(0, _err_ui)
                return

            if not ok:

                def _fail_ui(it=item, rest=snapshot[i:]):
                    messagebox.showerror(
                        "Warteschlange",
                        f"Schnitt fehlgeschlagen (FFmpeg):\n{it.summary_line()}",
                        parent=self.root,
                    )
                    self._restore_pending_snapshot(rest)
                    if self.progress_handler:
                        self.progress_handler.set_status("Status: Warteschlange mit Fehler abgebrochen.")
                    _set_cut_preview_state((((i) / total_items) * 100.0), "Abgebrochen (Schnitt fehlgeschlagen)")

                self.root.after(0, _fail_ui)
                return

            holder: Dict[str, Any] = {"done": False, "error": None}

            def main_ui_step(it=item, res=result):
                try:
                    idx = self._find_video_index_for_path(it.source_path)
                    if idx is None:
                        raise RuntimeError("Video nicht mehr in der Liste.")
                    paths = self._sync_apply_cut_or_split_result(it.source_path, idx, res)

                    def finish_meta():
                        self._on_metadata_refreshed()
                        holder["done"] = True

                    if paths and self.video_preview:
                        self.video_preview.refresh_metadata_async(paths, on_complete_callback=finish_meta)
                    else:
                        self._on_metadata_refreshed()
                        holder["done"] = True
                except Exception as ex:
                    holder["error"] = str(ex)
                    holder["done"] = True

            self.root.after(0, main_ui_step)
            deadline = time.monotonic() + 7200
            while not holder["done"]:
                if time.monotonic() > deadline:

                    def _to(rest=snapshot[i:]):
                        messagebox.showerror(
                            "Warteschlange",
                            "Zeitüberschreitung bei der Metadaten-Aktualisierung.",
                            parent=self.root,
                        )
                        self._restore_pending_snapshot(rest)
                        _set_cut_preview_state((((i) / total_items) * 100.0), "Abgebrochen (Timeout)")

                    self.root.after(0, _to)
                    return
                time.sleep(0.05)

            if holder.get("error"):
                err = holder["error"]

                def _e2(e=err, rest=snapshot[i:]):
                    messagebox.showerror(
                        "Warteschlange",
                        f"GUI-Aktualisierung fehlgeschlagen:\n{e}",
                        parent=self.root,
                    )
                    self._restore_pending_snapshot(rest)
                    if self.progress_handler:
                        self.progress_handler.set_status("Status: Warteschlange mit Fehler abgebrochen.")
                    _set_cut_preview_state((((i) / total_items) * 100.0), "Abgebrochen (GUI-Fehler)")

                self.root.after(0, _e2)
                return

        def _done_all():
            if self.progress_handler:
                self.progress_handler.set_status("Status: Warteschlange fertig.")
            if self.video_preview:
                self.video_preview.update_encoding_progress(
                    100,
                    task_name="Cutting/Trimming",
                    eta="Fertig",
                )

        self.root.after(0, _done_all)

    def _on_metadata_refreshed(self):
        """
        [MAIN-THREAD] Callback, der aufgerufen wird, nachdem die Metadaten
        im Cache aktualisiert wurden. JETZT ist es sicher, die GUI zu aktualisieren.
        """
        print("App: Metadaten-Aktualisierung abgeschlossen. Aktualisiere GUI.")

        # 1. DragDrop-Tabelle aktualisieren (liest jetzt aus dem aktualisierten Cache)
        if self.drag_drop:
            self.drag_drop.refresh_table()

        # 2. Video-Vorschau regenerieren — während Schnitt-Warteschlange unterdrückt;
        #    danach einmalig in _kick_preview_regenerate_after_batch.
        if getattr(self, "_suppress_preview_regenerate_after_metadata", False):
            return

        if self.video_preview and self.drag_drop:
            original_paths = self.drag_drop.get_video_paths()
            self.video_preview.regenerate_preview_after_cut(original_paths)

    def _on_cutter_dialog_close(self, event=None):
        """Wird aufgerufen, wenn der Cutter-Dialog zerstört wird."""
        if self.video_cutter_dialog:
            print("Cutter-Dialog geschlossen, Referenz wird gelöscht.")
            self.video_cutter_dialog = None

    # --- ENDE NEUE METHODEN ---

    def on_app_close(self):
        """Aufräumen beim Schließen der App."""
        print("App wird geschlossen...")

        # 1. Aktiven Schneide-Dialog schließen (falls offen)
        if self.video_cutter_dialog:
            try:
                self.video_cutter_dialog.destroy()
            except tk.TclError:
                pass  # Fenster vielleicht schon weg

        # 2. SD-Karten Monitor stoppen
        if self.sd_card_monitor:
            self.sd_card_monitor.stop_monitoring()

        # 3. Vorschau und temporäre Kopien vollständig löschen (inkl. combined MP4)
        if self.video_preview:
            self.video_preview.clear_preview()

        # 4. Root-Fenster zerstören
        self.root.destroy()

    def initialize_sd_card_monitor(self):
        """Initialisiert und startet den SD-Karten Monitor"""
        from ..utils.sd_card_monitor import SDCardMonitor

        try:
            self.sd_card_monitor = SDCardMonitor(
                self.config,
                on_backup_complete=self._on_sd_backup_complete_threadsafe,
                on_progress_update=self.on_sd_progress_update,
                on_status_change=self.on_sd_status_change
            )
            self.sd_card_monitor.start_monitoring()
            print("SD-Karten Monitor initialisiert")
        except Exception as e:
            print(f"Fehler beim Initialisieren des SD-Karten Monitors: {e}")
            # Nicht kritisch, App kann weiter laufen
            self.sd_card_monitor = None

    def on_sd_status_change(self, status_type, data):
        """
        Callback wenn sich der SD-Karten Status ändert

        Args:
            status_type: Art des Status ('monitoring_started', 'sd_detected', 'backup_started',
                        'backup_finished', 'clearing_started', 'clearing_finished')
            data: Zusätzliche Daten je nach Status
        """
        def update_ui():
            if not self.sd_status_indicator:
                return

            if status_type == 'monitoring_started':
                self.sd_status_indicator.set_monitoring_active(True)
                self.sd_status_indicator.set_active_drive(None)
                self.sd_status_indicator.set_waiting_size_limit(False)
                self.sd_status_indicator.set_auto_import_active(False)
                self.progress_handler.set_status("Status: SD-Überwachung aktiv")

            elif status_type == 'sd_detected':
                self.sd_status_indicator.set_sd_detected(True)
                if data is not None:
                    self.sd_status_indicator.set_active_drive(data)
                self.progress_handler.set_status(f"Status: SD-Karte erkannt ({data})")

            elif status_type == 'backup_started':
                self.sd_status_indicator.set_backup_active(True)
                self.sd_status_indicator.set_sd_detected(False)
                if data is not None:
                    self.sd_status_indicator.set_active_drive(data)
                self.sd_status_indicator.set_waiting_size_limit(False)
                self.progress_handler.set_status("Status: SD-Karten Backup läuft...")

            elif status_type == 'backup_finished':
                self.sd_status_indicator.set_backup_active(False)
                self.sd_status_indicator.set_sd_detected(False)
                self.sd_status_indicator.set_waiting_size_limit(False)
                self.sd_status_indicator.set_active_drive(None)

                # Prüfe Backup-Typ aus data
                if data and isinstance(data, dict):
                    backup_type = data.get('type', 'full')
                    file_count = data.get('file_count')

                    if backup_type == 'selective' and file_count:
                        self.progress_handler.set_status(f"Status: {file_count} Dateien erfolgreich importiert")
                    elif backup_type == 'full':
                        self.progress_handler.set_status("Status: Backup abgeschlossen")
                    elif backup_type == 'cancelled':
                        self.progress_handler.set_status("Status: Import abgebrochen")
                    elif backup_type == 'failed':
                        self.progress_handler.set_status("Status: Backup fehlgeschlagen")
                    else:
                        self.progress_handler.set_status("Status: Backup abgeschlossen")
                else:
                    # Fallback für alte Logik (wenn data None oder nicht Dict)
                    if data:  # Erfolg
                        self.progress_handler.set_status("Status: Backup abgeschlossen")
                    else:  # Fehler
                        self.progress_handler.set_status("Status: Backup fehlgeschlagen")

            elif status_type == 'clearing_started':
                self.sd_status_indicator.set_clearing_active(True)
                if data is not None:
                    self.sd_status_indicator.set_active_drive(data)
                self.sd_status_indicator.show_clearing_progress()
                self.progress_handler.set_status("Status: SD-Karte wird geleert...")

            elif status_type == 'clearing_finished':
                self.sd_status_indicator.set_clearing_active(False)
                self.progress_handler.set_status("Status: SD-Karte geleert")

            elif status_type == 'clearing_skipped_selective':
                # SD-Karte wurde nicht geleert wegen selektivem Import
                self.progress_handler.set_status("Status: SD-Karte wurde nicht geleert (selektiver Import)")

            elif status_type == 'size_limit_exceeded':
                self.sd_status_indicator.set_waiting_size_limit(True)
                self._show_size_limit_dialog(data)

        # UI-Update im Haupt-Thread
        self.root.after(0, update_ui)

    def _show_size_limit_dialog(self, data):
        """
        Zeigt Dialog für Größen-Limit-Überschreitung (läuft im Haupt-Thread).

        Args:
            data: Dict mit files_info, total_size_mb, limit_mb
        """
        from tkinter import messagebox

        files_info = data['files_info']
        total_size_mb = data['total_size_mb']
        limit_mb = data['limit_mb']

        # Zeige custom Dialog mit 3 Optionen
        dialog = tk.Toplevel(self.root)
        dialog.title("Größen-Limit überschritten")
        dialog.geometry("550x400")
        dialog.transient(self.root)
        dialog.grab_set()

        # Zentriere Dialog
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")

        # Inhalt
        main_frame = tk.Frame(dialog, padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Warnung
        tk.Label(main_frame,
                text="⚠️ Zu viele Dateien auf SD-Karte!",
                font=("Arial", 14, "bold"),
                fg="#f44336").pack(pady=(0, 15))

        # Info
        info_text = (
            f"Gefundene Dateien: {len(files_info)}\n"
            f"Gesamtgröße: {total_size_mb:.0f} MB\n"
            f"Eingestelltes Limit: {limit_mb} MB\n\n"
            f"Was möchten Sie tun?"
        )
        tk.Label(main_frame, text=info_text, font=("Arial", 10), justify='left').pack(pady=(0, 10))

        trotzdem_button_text = "Trotzdem alle importieren"
        # NEU: Hinweis wenn Auto-Import deaktiviert ist
        settings = self.config.get_settings()
        if not settings.get("sd_auto_import", False):
            hint_text = "Hinweis: Automatischer Import ist deaktiviert.\nDateien werden nur gesichert, nicht importiert."
            tk.Label(main_frame, text=hint_text, font=("Arial", 9, "bold"), fg="#D84315",
                    justify='left', bg='#FFE0B2', padx=10, pady=8, relief='solid', borderwidth=1).pack(pady=(0, 15), fill='x')
            trotzdem_button_text = "Trotzdem alle sichern"

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill='x')

        def on_proceed_all():
            if self.sd_status_indicator:
                self.sd_status_indicator.set_waiting_size_limit(False)
            self.sd_card_monitor.set_size_limit_decision("proceed_all")
            dialog.destroy()

        def on_select_files():
            dialog.destroy()
            # Zeige Dateiauswahl-Dialog
            self._show_file_selector_dialog(files_info, total_size_mb)

        def on_cancel():
            if self.sd_status_indicator:
                self.sd_status_indicator.set_waiting_size_limit(False)
            self.sd_card_monitor.set_size_limit_decision("cancel")
            dialog.destroy()

        tk.Button(button_frame, text=trotzdem_button_text,
                 command=on_proceed_all, bg="#FF9800", fg="white",
                 font=("Arial", 10), width=25, height=2).pack(pady=5)

        tk.Button(button_frame, text="Dateien auswählen...",
                 command=on_select_files, bg="#2196F3", fg="white",
                 font=("Arial", 10), width=25, height=2).pack(pady=5)

        tk.Button(button_frame, text="Abbrechen",
                 command=on_cancel, bg="#9E9E9E", fg="white",
                 font=("Arial", 10), width=25, height=2).pack(pady=5)

        # X-Button soll wie Abbrechen funktionieren
        dialog.protocol("WM_DELETE_WINDOW", on_cancel)

    def _show_file_selector_dialog(self, files_info, total_size_mb):
        """
        Zeigt Dateiauswahl-Dialog.

        Args:
            files_info: Liste von Datei-Infos
            total_size_mb: Gesamtgröße in MB
        """
        try:
            from src.gui.components.sd_file_selector_dialog import SDFileSelectorDialog

            selector = SDFileSelectorDialog(self.root, files_info, total_size_mb)
            selector.show()

            # Warte bis Dialog geschlossen
            self.root.wait_window(selector.dialog)

            # Hole Auswahl
            selected_files = selector.get_selected_files()

            if selected_files is None:
                # User hat abgebrochen
                self.sd_card_monitor.set_size_limit_decision("cancel")
            else:
                # User hat Dateien ausgewählt
                self.sd_card_monitor.set_size_limit_decision(selected_files)

        except Exception as e:
            print(f"Fehler beim Dateiauswahl-Dialog: {e}")
            import traceback
            traceback.print_exc()
            # Bei Fehler: Alle importieren
            self.sd_card_monitor.set_size_limit_decision("proceed_all")
        finally:
            if self.sd_status_indicator:
                self.sd_status_indicator.set_waiting_size_limit(False)

    def on_sd_progress_update(self, current_mb, total_mb, speed_mbps):
        """
        Callback für SD-Backup Progress-Updates

        Args:
            current_mb: Bereits kopierte MB
            total_mb: Gesamt MB
            speed_mbps: Kopiergeschwindigkeit in MB/s
        """
        def update_ui():
            if self.sd_status_indicator:
                self.sd_status_indicator.update_backup_progress(current_mb, total_mb, speed_mbps)
            progress_percent = (current_mb / total_mb * 100) if total_mb > 0 else 0
            self.progress_handler.set_status(
                f"Status: SD-Backup {progress_percent:.0f}% ({current_mb:.0f}/{total_mb:.0f} MB, {speed_mbps:.1f} MB/s)"
            )
        self.root.after(0, update_ui)

    def _restart_sd_monitor_if_needed(self):
        """Startet den SD-Monitor neu wenn Einstellungen geändert wurden"""
        settings = self.config.get_settings()
        should_monitor = settings.get("sd_auto_backup", False)

        if self.sd_card_monitor:
            is_monitoring = self.sd_card_monitor.monitoring

            if should_monitor and not is_monitoring:
                self.sd_card_monitor.start_monitoring()
            elif not should_monitor and is_monitoring:
                self.sd_card_monitor.stop_monitoring()
                if self.sd_status_indicator:
                    self.sd_status_indicator.hide()
                self.progress_handler.set_status("Status: Bereit.")

    def _on_sd_backup_complete_threadsafe(self, backup_path, success, error_message=None, backup_info=None):
        """Marshalled Callback vom SD-Monitor-Thread auf den Tk-Hauptthread."""
        self.root.after(
            0,
            lambda: self.on_sd_backup_complete(backup_path, success, error_message, backup_info),
        )

    def on_sd_backup_complete(self, backup_path, success, error_message=None, backup_info=None):
        """
        Wird aufgerufen wenn SD-Karten Backup abgeschlossen ist

        Callback-Methode vom SD-Card-Monitor. Zeigt Benachrichtigung
        und startet optional automatischen Import wenn aktiviert.

        Args:
            backup_path: Pfad zum erstellten Backup-Ordner (oder None bei Fehler)
            success: True wenn Backup erfolgreich, False bei Fehler
            error_message: Fehlermeldung bei Fehler, None bei Erfolg
        """
        # Fehlerfall behandeln
        if not success:
            print(f"SD-Karten Backup fehlgeschlagen: {error_message}")

            # Zeige detaillierte Fehlermeldung
            error_text = "Das Backup von der SD-Karte ist fehlgeschlagen."
            if error_message:
                error_text += f"\n\nGrund:\n{error_message}"

            messagebox.showerror(
                "Backup Fehler",
                error_text,
                parent=self.root
            )
            return

        # Erfolgsfall
        print(f"SD-Karten Backup erfolgreich: {backup_path}")

        server_warning = None
        server_path = None
        if isinstance(backup_info, dict):
            server_warning = backup_info.get("server_warning_message")
            server_path = backup_info.get("server_backup_path")
        if server_warning:
            warning_text = server_warning
            if server_path:
                warning_text += f"\n\nServer-Ziel:\n{server_path}"
            messagebox.showwarning(
                "Backup lokal erfolgreich, Server mit Warnung",
                warning_text,
                parent=self.root,
            )

        settings = self.config.get_settings()

        # Prüfe ob automatischer Import aktiviert ist
        if settings.get("sd_auto_import", False):
            # Starte automatischen Import
            self.import_from_backup(backup_path)
        else:
            # Zeige nur Erfolgs-Benachrichtigung
            info_text = f"SD-Karten Backup wurde erfolgreich erstellt:\n{backup_path}"
            if server_path and not server_warning:
                info_text += f"\n\nServer-Kopie erstellt:\n{server_path}"
            messagebox.showinfo(
                "Backup erfolgreich",
                info_text,
                parent=self.root
            )

    def import_from_backup(self, backup_path):
        """
        Importiert Dateien aus dem Backup-Ordner in die Anwendung

        Simuliert Drag&Drop durch direktes Hinzufügen der Dateien.
        Wenn "Nur neue Dateien" aktiviert ist, werden bereits importierte
        Dateien automatisch übersprungen.

        Args:
            backup_path: Pfad zum Backup-Ordner mit Mediendateien
        """
        def _notify_import_active(active):
            ind = self.sd_status_indicator
            if ind:
                ind.set_auto_import_active(active)

        _notify_import_active(True)

        qr_check_was_enabled = False
        photo_qr_check_was_enabled = False
        if self.drag_drop and hasattr(self.drag_drop, 'qr_check_enabled'):
            qr_check_was_enabled = self.drag_drop.qr_check_enabled.get()
            if qr_check_was_enabled:
                print("QR-Code-Prüfung temporär deaktiviert für Auto-Import")
                self.drag_drop.qr_check_enabled.set(False)
        if self.drag_drop and hasattr(self.drag_drop, 'photo_qr_check_enabled'):
            photo_qr_check_was_enabled = self.drag_drop.photo_qr_check_enabled.get()
            if photo_qr_check_was_enabled:
                print("Foto-QR-Prüfung temporär deaktiviert für Auto-Import")
                self.drag_drop.photo_qr_check_enabled.set(False)

        pending_video_count = 0
        pending_photo_count = 0

        def _on_import_complete(success, videos_imported, photos_imported, error, cancelled):
            _notify_import_active(False)
            if self.drag_drop:
                if qr_check_was_enabled and hasattr(self.drag_drop, 'qr_check_enabled'):
                    self.drag_drop.qr_check_enabled.set(True)
                if photo_qr_check_was_enabled and hasattr(self.drag_drop, 'photo_qr_check_enabled'):
                    self.drag_drop.photo_qr_check_enabled.set(True)

            if not success or cancelled:
                if error and not cancelled:
                    messagebox.showerror(
                        "Import Fehler",
                        f"Fehler beim Importieren der Dateien:\n{error}",
                        parent=self.root,
                    )
                return

            if videos_imported > 0:
                self._switch_to_predominant_tab(videos_imported, photos_imported)
                if qr_check_was_enabled and self.drag_drop:
                    video_paths = self.drag_drop.get_video_paths()
                    if video_paths:
                        self.run_qr_analysis(video_paths.copy())
            elif photos_imported > 0:
                self._switch_to_predominant_tab(videos_imported, photos_imported)
                if photo_qr_check_was_enabled and self.drag_drop:
                    if not (videos_imported > 0 and qr_check_was_enabled):
                        self.drag_drop._maybe_run_photo_qr_search()

        try:
            settings = self.config.get_settings()
            skip_processed = settings.get("sd_skip_processed", False)
            exclude_timelapse = settings.get("sd_exclude_timelapse_videos", True)

            video_files, photo_files, timelapse_skipped = collect_media_from_backup_folder(
                backup_path,
                exclude_timelapse_videos=exclude_timelapse,
            )
            if timelapse_skipped:
                print(
                    f"DJI Timelapse-Filter beim Import: "
                    f"{timelapse_skipped} Video(s) übersprungen"
                )

            if skip_processed and (video_files or photo_files):
                # Filtere bereits importierte Dateien
                from ..utils.media_history import MediaHistoryStore

                history_store = MediaHistoryStore.instance()

                filtered_videos = []
                filtered_photos = []
                skipped_count = 0

                print("Prüfe auf bereits importierte Dateien...")

                # Videos filtern - nur importierte überspringen, nicht nur gesicherte
                for file_path in video_files:
                    identity = history_store.compute_identity(file_path)
                    if identity:
                        identity_hash, _ = identity
                        # Prüfe ob bereits IMPORTIERT (nicht nur gesichert)
                        if not history_store.was_imported(identity_hash):
                            filtered_videos.append(file_path)
                        else:
                            skipped_count += 1
                    else:
                        # Bei Hash-Fehler: Datei trotzdem importieren
                        filtered_videos.append(file_path)

                # Fotos filtern - nur importierte überspringen, nicht nur gesicherte
                for file_path in photo_files:
                    identity = history_store.compute_identity(file_path)
                    if identity:
                        identity_hash, _ = identity
                        # Prüfe ob bereits IMPORTIERT (nicht nur gesichert)
                        if not history_store.was_imported(identity_hash):
                            filtered_photos.append(file_path)
                        else:
                            skipped_count += 1
                    else:
                        # Bei Hash-Fehler: Datei trotzdem importieren
                        filtered_photos.append(file_path)

                print(f"Import-Filter: {len(video_files) + len(photo_files)} Dateien, "
                      f"{len(filtered_videos) + len(filtered_photos)} neu, {skipped_count} übersprungen")

                video_files = filtered_videos
                photo_files = filtered_photos

            if video_files or photo_files:
                video_files = sort_paths_by_basename(video_files)
                photo_files = sort_paths_by_basename(photo_files)
                pending_video_count = len(video_files)
                pending_photo_count = len(photo_files)
                if self.drag_drop:
                    self.drag_drop.add_files(
                        video_files,
                        photo_files,
                        on_complete=_on_import_complete,
                        record_history_after_import=skip_processed,
                    )
                print(
                    f"Auto-Import gestartet: {pending_video_count} Videos, "
                    f"{pending_photo_count} Fotos"
                )
            else:
                # Keine neuen Dateien gefunden
                print("Keine neuen Dateien zum Importieren gefunden")
                if skip_processed:
                    messagebox.showinfo(
                        "Keine neuen Dateien",
                        "Alle Dateien im Backup wurden bereits früher importiert.",
                        parent=self.root
                    )
                else:
                    messagebox.showwarning(
                        "Keine Dateien",
                        "Im Backup wurden keine Videos oder Fotos gefunden.",
                        parent=self.root
                    )

        except Exception as e:
            print(f"Fehler beim Importieren aus Backup: {e}")
            _notify_import_active(False)
            if self.drag_drop:
                if qr_check_was_enabled and hasattr(self.drag_drop, 'qr_check_enabled'):
                    self.drag_drop.qr_check_enabled.set(True)
                if photo_qr_check_was_enabled and hasattr(self.drag_drop, 'photo_qr_check_enabled'):
                    self.drag_drop.photo_qr_check_enabled.set(True)
            messagebox.showerror(
                "Import Fehler",
                f"Fehler beim Importieren der Dateien:\n{str(e)}",
                parent=self.root
            )

    def _switch_to_predominant_tab(self, video_count: int, photo_count: int):
        """
        Wechselt automatisch zum Video- oder Foto-Tab basierend darauf,
        welcher Medientyp häufiger importiert wurde.

        Wechselt beide Notebooks:
        - Preview-Notebook (Video-/Foto-Preview)
        - Drag&Drop-Notebook (Video-/Foto-Liste)

        Args:
            video_count: Anzahl importierter Videos
            photo_count: Anzahl importierter Fotos
        """
        if video_count == 0 and photo_count == 0:
            return  # Nichts zu tun

        # Bestimme welcher Tab geöffnet werden soll
        if video_count > photo_count:
            # Mehr Videos → Video-Tab
            target_tab = "video"
            target_index = 0
            print(f"→ Öffne Video-Tabs (Auto-Import: {video_count} Videos > {photo_count} Fotos)")
        elif photo_count > video_count:
            # Mehr Fotos → Foto-Tab
            target_tab = "photo"
            target_index = 1
            print(f"→ Öffne Foto-Tabs (Auto-Import: {photo_count} Fotos > {video_count} Videos)")
        else:
            # Gleich viele → Video-Tab als Standard
            target_tab = "video"
            target_index = 0
            print(f"→ Öffne Video-Tabs (Auto-Import: gleich viele - {video_count} Videos = {photo_count} Fotos)")

        # Wechsle zum passenden Tab im Preview-Notebook
        if self.preview_notebook and hasattr(self.preview_notebook, 'select'):
            try:
                if target_tab == "video" and self.video_tab:
                    self.preview_notebook.select(self.video_tab)
                    print("  ✅ Preview: Video-Tab aktiviert")
                elif target_tab == "photo" and self.foto_tab:
                    self.preview_notebook.select(self.foto_tab)
                    print("  ✅ Preview: Foto-Tab aktiviert")
            except Exception as e:
                print(f"  ⚠️ Fehler beim Preview-Tab-Wechsel: {e}")

        # Wechsle zum passenden Tab im Drag&Drop-Notebook
        if self.drag_drop and hasattr(self.drag_drop, 'notebook'):
            try:
                # Verwende Index für einfacheren Zugriff (0=Videos, 1=Fotos)
                self.drag_drop.notebook.select(target_index)
                print(f"  ✅ Drag&Drop: {'Video' if target_index == 0 else 'Foto'}-Tab aktiviert")
            except Exception as e:
                print(f"  ⚠️ Fehler beim Drag&Drop-Tab-Wechsel: {e}")

    def run(self):
        """Startet die Hauptloop der Anwendung"""
        try:
            initialize_updater(self.root, self.APP_VERSION)
        except Exception as e:
            print(f"Fehler beim Initialisieren des Updaters: {e}")
        self.root.mainloop()

