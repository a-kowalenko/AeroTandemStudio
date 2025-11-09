import tkinter as tk
from tkinter import messagebox, ttk
import threading
import os
import queue
from typing import List
from tkinterdnd2 import TkinterDnD
from datetime import datetime

from .components.form_fields import FormFields
from .components.drag_drop import DragDropFrame
from .components.video_preview import VideoPreview
from .components.photo_preview import PhotoPreview
from .components.progress_indicator import ProgressHandler
from .components.circular_spinner import CircularSpinner
from .components.settings_dialog import SettingsDialog
from .components.video_player import VideoPlayer
from .components.video_cutter import VideoCutterDialog  # Importiert
from .components.loading_window import LoadingWindow
from .components.sd_status_indicator import SDStatusIndicator
from ..model.kunde import Kunde

from ..video.processor import VideoProcessor
from ..utils.config import ConfigManager
from ..utils.validation import validate_form_data
from ..utils.sd_card_monitor import SDCardMonitor
from ..utils.media_history import MediaHistoryStore
from ..installer.ffmpeg_installer import ensure_ffmpeg_installed
from ..utils.file_utils import test_server_connection
from ..installer.updater import initialize_updater
from ..utils.constants import APP_VERSION


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

        # SD-Karten Monitor
        self.sd_card_monitor = None
        self.sd_status_indicator = None

        # Speichern der Button-Originalzustände
        self.old_button_text = ""
        self.old_button_bg = ""
        self.old_button_cursor = ""

        # Flag für Initialisierungsstatus
        self.initialization_complete = False

        # Starte asynchrone Initialisierung
        self._init_step_1()

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
        window_width = 1400
        window_height = 800
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")

        self.root.config(padx=20, pady=0)

        # Nächster Chunk
        self.root.after(1, self._setup_gui_step_2)

    def _setup_gui_step_2(self):
        """GUI Setup Teil 2: Header und Container"""
        if self.splash_callback:
            self.splash_callback("Erstelle Layout...")

        # Header
        self.create_header()

        # Container
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        self.left_frame = tk.Frame(self.main_container, width=600)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 20))

        self.right_frame = tk.Frame(self.main_container, width=350)
        self.right_frame.pack(side="right", fill="y", padx=(20, 0))

        # Nächster Chunk
        self.root.after(1, self._setup_gui_step_3)

    def _setup_gui_step_3(self):
        """GUI Setup Teil 3: Komponenten erstellen"""
        if self.splash_callback:
            self.splash_callback("Lade Formulare...")

        # Formular und Drag&Drop
        self.form_fields = FormFields(self.left_frame, self.config, self)

        self.drag_drop = DragDropFrame(self.left_frame, self)

        # Nächster Chunk
        self.root.after(1, self._setup_gui_step_4)

    def _setup_gui_step_4(self):
        """GUI Setup Teil 4: Tabs und Preview"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Video Player...")

        # Tabs erstellen
        style = ttk.Style()
        style.configure('Preview.TNotebook.Tab', font=('Arial', 8, 'bold'), padding=[20, 5])

        self.preview_notebook = ttk.Notebook(self.right_frame, style='Preview.TNotebook')
        self.video_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.video_tab, text="Video Vorschau")
        self.foto_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.foto_tab, text="Foto Vorschau")

        # Video Player und Preview
        self.video_player = VideoPlayer(self.video_tab, self)

        self.video_preview = VideoPreview(self.video_tab, self)

        # Nächster Chunk
        self.root.after(1, self._setup_gui_step_5)

    def _setup_gui_step_5(self):
        """GUI Setup Teil 5: Foto-Preview und Button"""
        if self.splash_callback:
            self.splash_callback("Initialisiere Foto Vorschau...")

        self.photo_preview = PhotoPreview(self.foto_tab, self)


        # Rufe den Rest von setup_gui auf
        self._finish_setup_gui()

        # Weiter mit nächstem Init-Schritt
        self.root.after(10, self._init_step_2)

    def _finish_setup_gui(self):
        """Finalisiert setup_gui - erstellt Upload-Frame etc."""
        # Event-Binding
        self.preview_notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Upload Frame erstellen (aus original setup_gui kopiert)
        self.upload_frame = tk.Frame(self.right_frame)
        progress_row = tk.Frame(self.upload_frame)
        progress_row.pack(fill="x", side="top")

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

        self.pack_components()
        self.load_settings()
        self.test_server_connection_async()

    def _init_step_2(self):
        """Schritt 2: Dependencies prüfen"""
        if self.splash_callback:
            self.splash_callback("Prüfe FFmpeg Installation...")

        self.ensure_dependencies()
        self.root.after(10, self._init_step_3)

    def _init_step_3(self):
        """Schritt 3: Finalisierung"""
        if self.splash_callback:
            self.splash_callback("Finalisiere...")

        # SD-Monitor wird NACH Splash-Schließung gestartet (verzögert)
        # Hier nur vorbereiten
        self.root.after(10, self._init_complete)

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

        # SD-Monitor verzögert starten (800ms nach Splash-Schließung)
        self.root.after(800, self._delayed_sd_monitor_start)

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
        self.root.title("Aero Tandem Studio")

        # Zentriere Fenster auf dem Bildschirm
        window_width = 1400
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
        progress_row.pack(fill="x", side="top")

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


        self.pack_components()
        self.load_settings()

        # Server-Verbindung testen (im Hintergrund)
        self.test_server_connection_async()

    def create_header(self):
        """Erstellt den Header mit Titel, Logo und Settings-Button"""
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
        SettingsDialog(
            self.root,
            self.config,
            on_settings_saved=self.on_settings_saved
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

    def update_video_preview(self, video_paths: List[str], run_qr_check: bool = True):
        """
        Aktualisiert die Video-Vorschau. Startet die QR-Analyse in einem
        separaten Thread oder setzt das Formular zurück, wenn keine Videos vorhanden sind.
        NEU: run_qr_check steuert, ob die QR-Analyse durchgeführt werden soll.
        """
        if not video_paths:
            # --- NEU: Anforderung des Users umsetzen ---
            # Wenn alle Videos gelöscht wurden, setze das Formular
            # auf den manuellen Modus zurück.
            print("Keine Videos gefunden, setze Formular auf manuell zurück.")
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

        # NEU: QR-Prüfung nur starten, wenn run_qr_check True ist
        if run_qr_check:
            # Starte QR-Analyse UND Preview-Erstellung PARALLEL!
            print("Starte QR-Analyse und Preview-Erstellung parallel...")

            # 1. Preview-Erstellung starten (läuft in eigenem Thread)
            if self.video_preview:
                self.video_preview.update_preview(video_paths)

            # 2. QR-Analyse starten (läuft ebenfalls in eigenem Thread)
            self.run_qr_analysis(video_paths)
        else:
            # Keine QR-Prüfung, nur Vorschau aktualisieren
            print("QR-Prüfung übersprungen - erster Clip hat sich nicht geändert.")
            if self.video_preview:
                self.video_preview.update_preview(video_paths)

    def run_qr_analysis(self, video_paths: list[str]):
        """
        Startet QR-Code-Analyse in separatem Thread.
        NEU: Ändert Button-Status NICHT mehr, da Preview parallel läuft!
        """
        # Ladefenster anzeigen
        self.loading_window = LoadingWindow(self.root, text="Analysiere QR-Code im Video...")

        # Queue erstellen für Ergebnis-Kommunikation
        self.analysis_queue = queue.Queue()

        # video_paths enthält nach dem ersten update_preview bereits Working-Folder-Pfade!
        first_video_path = video_paths[0]
        print(f"QR-Analyse: {os.path.basename(first_video_path)}")

        # Analyse-Thread starten
        analysis_thread = threading.Thread(
            target=self._run_analysis_thread,
            args=(first_video_path, self.analysis_queue),
            daemon=True
        )
        analysis_thread.start()

        # Polling-Funktion starten
        self.root.after(100, self._check_analysis_result, video_paths)

    def run_photo_qr_analysis(self, photo_path: str):
        """
        Startet QR-Code-Analyse für ein Foto in separatem Thread.
        Verwendet das gleiche Loading Window wie bei Videos.
        """
        # Ladefenster anzeigen
        self.loading_window = LoadingWindow(self.root, text="Analysiere QR-Code im Foto...")

        # Queue erstellen für Ergebnis-Kommunikation
        self.analysis_queue = queue.Queue()

        print(f"QR-Analyse Foto: {os.path.basename(photo_path)}")

        # Analyse-Thread starten
        analysis_thread = threading.Thread(
            target=self._run_photo_analysis_thread,
            args=(photo_path, self.analysis_queue),
            daemon=True
        )
        analysis_thread.start()

        # Polling-Funktion starten
        self.root.after(100, self._check_photo_analysis_result, photo_path)

    def _run_analysis_thread(self, video_path: str, result_queue: queue.Queue):
        """
        Diese Funktion läuft im separaten Thread.
        Sie führt die blockierende Analyse aus und legt das Ergebnis in die Queue.
        """
        try:
            from src.video.qr_analyser import analysiere_ersten_clip

            kunde, qr_scan_success = analysiere_ersten_clip(video_path)
            result_queue.put(("success", (kunde, qr_scan_success)))

        except Exception as e:
            print(f"Fehler im Analyse-Thread: {e}")
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

    def _check_analysis_result(self, video_paths: List[str]):
        """
        Überprüft alle 100ms, ob ein Ergebnis in der Queue liegt.
        Diese Funktion läuft im Haupt-Thread und kann die GUI sicher aktualisieren.
        """
        try:
            # Versuchen, ein Ergebnis zu holen, ohne zu blockieren
            status, result = self.analysis_queue.get_nowait()

            # --- Ergebnis ist da ---

            # 1. Ladefenster schließen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None

            # 2. Ergebnis verarbeiten
            if status == "success":
                kunde, qr_scan_success = result
                self._process_analysis_result(kunde, qr_scan_success, video_paths)
            elif status == "error":
                messagebox.showerror("Analyse-Fehler",
                                     f"Ein unerwarteter Fehler bei der Videoanalyse ist aufgetreten:\n{result}")
                # Kein _restore_button_state - Preview läuft parallel!
                self.form_fields.update_form_layout(False, None)


        except queue.Empty:
            # Wenn die Queue leer ist, erneut in 100ms prüfen
            self.root.after(100, self._check_analysis_result, video_paths)

        except Exception as e:
            # Allgemeiner Fehler beim Abrufen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None
            messagebox.showerror("Fehler", f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}")
            # Kein _restore_button_state - Preview läuft parallel!
            self.form_fields.update_form_layout(False, None)

    def _check_photo_analysis_result(self, photo_path: str):
        """
        Überprüft alle 100ms, ob ein Ergebnis der Foto-QR-Analyse in der Queue liegt.
        Diese Funktion läuft im Haupt-Thread und kann die GUI sicher aktualisieren.
        """
        try:
            # Versuchen, ein Ergebnis zu holen, ohne zu blockieren
            status, result = self.analysis_queue.get_nowait()

            # --- Ergebnis ist da ---

            # 1. Ladefenster schließen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None

            # 2. Ergebnis verarbeiten
            if status == "success":
                kunde, qr_scan_success, source_path = result
                self._process_photo_analysis_result(kunde, qr_scan_success, source_path)
            elif status == "error":
                messagebox.showerror("Analyse-Fehler",
                                     f"Ein unerwarteter Fehler bei der Foto-Analyse ist aufgetreten:\n{result}")
                self.form_fields.update_form_layout(False, None)

        except queue.Empty:
            # Wenn die Queue leer ist, erneut in 100ms prüfen
            self.root.after(100, self._check_photo_analysis_result, photo_path)

        except Exception as e:
            # Allgemeiner Fehler beim Abrufen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None
            messagebox.showerror("Fehler", f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}")
            self.form_fields.update_form_layout(False, None)

    def _process_analysis_result(self, kunde, qr_scan_success, video_paths):
        """
        Verarbeitet das erfolgreiche Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code gescannt: Kunde ID {kunde.kunde_id}, Email: {kunde.email}, Telefon: {kunde.telefon}, "
                      f"Handcam Foto: {kunde.handcam_foto}, Handcam Video: {kunde.handcam_video}, "
                      f"Outside Foto: {kunde.outside_foto}, Outside Video: {kunde.outside_video}")

                info_text = (
                    f"Kunde erkannt:\n\n"
                    f"ID: {kunde.kunde_id}\n"
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
                print("Kein QR-Code im ersten Video gefunden. Wechsle zu manueller Eingabe.")

            # Formular-Layout aktualisieren
            self.form_fields.update_form_layout(qr_scan_success, kunde)

            # NEU: Preview läuft bereits parallel! Kein wait_for_preview_thread nötig.
            # Button-Status wird von video_preview._finalize_processing wiederhergestellt
            print("QR-Analyse abgeschlossen. Preview läuft parallel weiter.")

        except Exception as e:
            print(f"Fehler in _process_analysis_result: {e}")
            # Nur wenn Preview NICHT läuft, Button wiederherstellen
            if not (self.video_preview and self.video_preview.processing_thread):
                self._restore_button_state()
            self.form_fields.update_form_layout(False, None)

    def _process_photo_analysis_result(self, kunde, qr_scan_success, photo_path):
        """
        Verarbeitet das erfolgreiche Foto-QR-Code-Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code im Foto gescannt: Kunde ID {kunde.kunde_id}, Email: {kunde.email}, "
                      f"Name: {kunde.vorname} {kunde.nachname}")

                # Formular automatisch füllen
                self.form_fields.update_form_layout(qr_scan_success, kunde)

            elif qr_scan_success and not kunde:
                messagebox.showwarning("Ungültiger QR-Code",
                                      f"Ein QR-Code wurde im Foto erkannt, aber die Daten sind ungültig.")
                self.form_fields.update_form_layout(False, None)

            else:
                messagebox.showwarning(
                    "Kein QR-Code gefunden",
                    f"Kein gültiger QR-Code im Foto gefunden:\n{os.path.basename(photo_path)}"
                )
                self.form_fields.update_form_layout(False, None)

        except Exception as e:
            print(f"Fehler in _process_photo_analysis_result: {e}")
            self.form_fields.update_form_layout(False, None)

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
        kunde_id_val = form_data.get("kunde_id")
        kunde = Kunde(
            kunde_id=int(kunde_id_val) if kunde_id_val and kunde_id_val.isdigit() else 0,
            vorname=str(form_data["vorname"]),
            nachname=str(form_data["nachname"]),
            email=str(form_data["email"]),
            telefon=str(form_data["telefon"]),
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
        errors = validate_form_data(form_data, (video_produkt_gewaehlt or foto_produkt_gewaehlt))
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
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
        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update,
            encoding_progress_callback=self._update_encoding_progress,  # NEU: Encoding-Fortschritt
            config_manager=self.config  # Config Manager übergeben
        )

        payload = {
            "form_data": form_data,
            "combined_video_path": combined_video_path if has_video else None,
            "video_clip_paths": self.drag_drop.get_video_paths() if has_video else [],  # NEU: Einzelne Clips
            "kunde": kunde,
            "photo_paths": photo_paths,
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
                                  current_time=0.0, total_time=None, task_id=None):
        """Callback für Live-Encoding-Fortschritt"""
        # Update ProgressHandler
        self.root.after(0, self.progress_handler.update_encoding_progress,
                       task_name, progress, fps, eta, current_time, total_time, task_id)

        # Update Drag&Drop Tabelle wenn task_id vorhanden (= Video-Index)
        if task_id is not None and progress is not None:
            # Aktiviere Progress-Modus beim ersten Update
            if not self.drag_drop.is_encoding:
                self.root.after(0, self.drag_drop.show_progress_mode)

            # Update Progress für das Video
            self.root.after(0, self.drag_drop.update_video_progress, task_id, progress, fps, eta)

        # Update Video-Preview
        if hasattr(self, 'video_preview') and self.video_preview and progress is not None:
            self.root.after(0, self.video_preview.update_encoding_progress, progress, fps, eta)

    def _handle_status_update(self, status_type, message):
        """Callback für Statusupdates"""
        if status_type == "success":
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
        """Löscht alle importierten Videos und Fotos nach erfolgreichem Erstellen"""
        try:
            print("🗑️ Auto-Clear: Lösche alle importierten Dateien...")

            # Lösche alle Videos
            if self.drag_drop.video_paths:
                video_count = len(self.drag_drop.video_paths)
                self.drag_drop.clear_videos()
                print(f"   ✓ {video_count} Video(s) gelöscht")

            # Lösche alle Fotos
            if self.drag_drop.photo_paths:
                photo_count = len(self.drag_drop.photo_paths)
                self.drag_drop.clear_photos()
                print(f"   ✓ {photo_count} Foto(s) gelöscht")

            # Setze drop_label zurück
            if hasattr(self, 'drag_drop') and self.drag_drop:
                self.drag_drop.drop_label.config(
                    text="Videos (.mp4) und Fotos (.jpg, .png) hierher ziehen",
                    fg="black"
                )
                print(f"   ✓ Drop-Label zurückgesetzt")

            # Aktualisiere Video Preview
            if hasattr(self, 'video_preview') and self.video_preview:
                self.video_preview.clear_preview()

            # Aktualisiere Photo Preview
            if hasattr(self, 'photo_preview') and self.photo_preview:
                self.photo_preview.set_photos([])

            print("✅ Auto-Clear abgeschlossen")

        except Exception as e:
            print(f"⚠️ Fehler beim Auto-Clear: {e}")

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

        # Zeige Spalte wenn Video ausgewählt aber nicht bezahlt ist
        self.drag_drop.set_watermark_column_visible(video_wm_sichtbar)

        # Wenn spalte nicht mehr sichtbar, lösche Auswahl
        if not video_wm_sichtbar:
            self.drag_drop.clear_watermark_selection()

        # NEU: Button in VideoPreview steuern
        if hasattr(self, 'video_preview'):
            self.video_preview.set_wm_button_visibility(video_wm_sichtbar)
            self.video_preview.update_wm_button_state()  # Status aktualisieren

        # --- NEU: Foto-Logik ---
        foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
        foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
        foto_wm_sichtbar = foto_gewaehlt and not foto_bezahlt

        print(f"🔍 Foto-Wasserzeichen-Spalte Update:")
        print(f"   Foto gewählt: {foto_gewaehlt}, Foto bezahlt: {foto_bezahlt}")
        print(f"   → Spalte sichtbar: {foto_wm_sichtbar}")

        # Rufe die neue Methode in drag_drop auf
        self.drag_drop.set_photo_watermark_column_visible(foto_wm_sichtbar)

        # Wenn spalte nicht mehr sichtbar, lösche Auswahl
        if not foto_wm_sichtbar:
            self.drag_drop.clear_photo_watermark_selection()

        # NEU: Button in PhotoPreview steuern
        if hasattr(self, 'photo_preview'):
            self.photo_preview.set_wm_button_visibility(foto_wm_sichtbar)
            self.photo_preview.update_wm_button_state()  # Status aktualisieren


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
            self.erstellen_button.config(
                text="Abbrechen",
                command=self.abbrechen_prozess,
                bg="#D32F2F",
                state="normal"
            )

        # Aktiviere den Abbrechen-Button nach 500ms
        self.root.after(500, enable_cancel_button)

        # Zeige Progress-Elemente rechts oben
        self.progress_handler.pack_progress_bar_right()
        self.progress_handler.progress_bar['value'] = 0

    def _switch_to_create_mode(self):
        """Wechselt den Button zurück zum Erstellen-Modus"""
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
        Callback vom VideoCutterDialog.
        NEU: Stößt asynchrone Metadaten-Aktualisierung an.
        """
        action = result.get("action")
        paths_to_refresh = []

        if action == "cut":
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geschnitten (getrimmt).")

            # Registriere das getrimmte Video als seine eigene Kopie
            # (Das Video wurde in-place ersetzt, hat aber neuen Inhalt)
            if self.video_preview:
                self.video_preview.register_new_copy(original_path, original_path)
                print(f"Getrimmtes Video registriert: {os.path.basename(original_path)}")

            paths_to_refresh.append(original_path)

        elif action == "split":
            # NEU: VideoCutter gibt jetzt part1_path und part2_path zurück
            part1_path = result.get("part1_path")
            part2_path = result.get("part2_path")
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geteilt.")
            print(f"     Teil 1: {os.path.basename(part1_path) if part1_path else 'N/A'}")
            print(f"     Teil 2: {os.path.basename(part2_path) if part2_path else 'N/A'}")

            if not part1_path or not part2_path:
                print("⚠️ Fehler: Split-Pfade nicht verfügbar")
                return

            # WICHTIG: Verwende die ECHTEN Dateipfade, nicht Placeholders!
            # Nach dem Split existieren:
            #   - part1_path (z.B. 000_1_1.MP4)
            #   - part2_path (z.B. 000_1_2.MP4)
            # Das Original (000_1.MP4) existiert NICHT mehr!

            if self.drag_drop:
                # 1. Ersetze das Original (an index) durch part1_path
                self.drag_drop.video_paths[index] = part1_path
                print(f"DragDrop: Ersetze Original an Index {index} durch Teil 1: {os.path.basename(part1_path)}")

                # 2. Füge part2_path direkt danach ein
                self.drag_drop.insert_video_path_at_index(part2_path, index + 1)

            # 3. Registriere die gesplitteten Videos als Kopien im Vorschau-System
            # Da die Dateien ihre finalen Namen haben, registrieren wir sie als ihre eigenen Kopien
            if self.video_preview:
                self.video_preview.register_new_copy(part1_path, part1_path)
                self.video_preview.register_new_copy(part2_path, part2_path)

            # 4. Für Metadaten-Refresh: Verwende die echten Pfade
            paths_to_refresh.append(part1_path)
            paths_to_refresh.append(part2_path)

        elif action == "cancel":
            print(f"App: Schneiden von '{os.path.basename(original_path)}' abgebrochen.")
            # Nichts tun
            return

        # Starte die asynchrone Aktualisierung der Metadaten für die geänderten Clips
        if paths_to_refresh and self.video_preview:
            self.video_preview.refresh_metadata_async(
                paths_to_refresh,
                on_complete_callback=self._on_metadata_refreshed
            )

    def _on_metadata_refreshed(self):
        """
        [MAIN-THREAD] Callback, der aufgerufen wird, nachdem die Metadaten
        im Cache aktualisiert wurden. JETZT ist es sicher, die GUI zu aktualisieren.
        """
        print("App: Metadaten-Aktualisierung abgeschlossen. Aktualisiere GUI.")

        # 1. DragDrop-Tabelle aktualisieren (liest jetzt aus dem aktualisierten Cache)
        if self.drag_drop:
            self.drag_drop.refresh_table()

        # 2. Video-Vorschau regenerieren (verwendet die *neue* Liste der Originale)
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

        # 3. Temporäre Vorschau-Kopien löschen
        if self.video_preview:
            self.video_preview._cleanup_temp_copies()  # Zugriff auf private Methode für Cleanup

        # 4. Root-Fenster zerstören
        self.root.destroy()

    def initialize_sd_card_monitor(self):
        """Initialisiert und startet den SD-Karten Monitor"""
        try:
            self.sd_card_monitor = SDCardMonitor(
                self.config,
                on_backup_complete=self.on_sd_backup_complete,
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
                self.progress_handler.set_status("Status: SD-Überwachung aktiv")

            elif status_type == 'sd_detected':
                self.sd_status_indicator.set_sd_detected(True)
                self.progress_handler.set_status(f"Status: SD-Karte erkannt ({data})")

            elif status_type == 'backup_started':
                self.sd_status_indicator.set_backup_active(True)
                self.sd_status_indicator.set_sd_detected(False)
                self.progress_handler.set_status("Status: SD-Karten Backup läuft...")

            elif status_type == 'backup_finished':
                self.sd_status_indicator.set_backup_active(False)
                self.sd_status_indicator.set_sd_detected(False)
                if data:  # Erfolg
                    self.progress_handler.set_status("Status: Backup abgeschlossen")
                else:  # Fehler
                    self.progress_handler.set_status("Status: Backup fehlgeschlagen")

            elif status_type == 'clearing_started':
                self.sd_status_indicator.set_clearing_active(True)
                self.sd_status_indicator.show_clearing_progress()
                self.progress_handler.set_status("Status: SD-Karte wird geleert...")

            elif status_type == 'clearing_finished':
                self.sd_status_indicator.set_clearing_active(False)
                self.progress_handler.set_status("Status: SD-Karte geleert")

            elif status_type == 'size_limit_exceeded':
                # NEU: Größen-Limit überschritten - zeige Dialog
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
        tk.Label(main_frame, text=info_text, font=("Arial", 10), justify='left').pack(pady=(0, 20))

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill='x')

        def on_proceed_all():
            self.sd_card_monitor.set_size_limit_decision("proceed_all")
            dialog.destroy()

        def on_select_files():
            dialog.destroy()
            # Zeige Dateiauswahl-Dialog
            self._show_file_selector_dialog(files_info, total_size_mb)

        def on_cancel():
            self.sd_card_monitor.set_size_limit_decision("cancel")
            dialog.destroy()

        tk.Button(button_frame, text="Trotzdem alle importieren",
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

    def on_sd_backup_complete(self, backup_path, success, error_message=None):
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

        settings = self.config.get_settings()

        # Prüfe ob automatischer Import aktiviert ist
        if settings.get("sd_auto_import", False):
            # Starte automatischen Import
            self.import_from_backup(backup_path)
        else:
            # Zeige nur Erfolgs-Benachrichtigung
            messagebox.showinfo(
                "Backup erfolgreich",
                f"SD-Karten Backup wurde erfolgreich erstellt:\n{backup_path}",
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
        # QR-Check Status merken und temporär deaktivieren
        qr_check_was_enabled = False
        if self.drag_drop and hasattr(self.drag_drop, 'qr_check_enabled'):
            qr_check_was_enabled = self.drag_drop.qr_check_enabled.get()
            if qr_check_was_enabled:
                print("QR-Code-Prüfung temporär deaktiviert für Auto-Import")
                self.drag_drop.qr_check_enabled.set(False)

        # Flag für finally-Block
        videos_imported = False

        try:
            # Sammle alle Dateien aus dem Backup-Ordner
            video_files = []
            photo_files = []

            # Dateien liegen direkt im Backup-Ordner (flache Struktur)
            if os.path.isdir(backup_path):
                for file in os.listdir(backup_path):
                    file_lower = file.lower()
                    file_path = os.path.join(backup_path, file)

                    # Nur Dateien, keine Ordner
                    if not os.path.isfile(file_path):
                        continue

                    # Video-Formate
                    if file_lower.endswith(('.mp4', '.mov', '.avi', '.mkv', '.m4v',
                                          '.mpg', '.mpeg', '.wmv', '.flv', '.webm')):
                        video_files.append(file_path)
                    # Foto-Formate
                    elif file_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tif',
                                            '.tiff', '.gif', '.webp', '.heic', '.raw',
                                            '.cr2', '.nef', '.arw', '.dng')):
                        photo_files.append(file_path)

            # Prüfe Einstellung für Duplikate-Filter
            settings = self.config.get_settings()
            skip_processed = settings.get("sd_skip_processed", False)

            if skip_processed and (video_files or photo_files):
                # Filtere bereits importierte Dateien
                history_store = MediaHistoryStore.instance()

                filtered_videos = []
                filtered_photos = []
                skipped_count = 0

                print("Prüfe auf bereits importierte Dateien...")

                # Videos filtern - nur importierte überspringen, nicht gesicherte
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

                # Fotos filtern - nur importierte überspringen, nicht gesicherte
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

            # Importiere gefilterte Dateien
            if video_files or photo_files:
                # Füge Dateien zum Drag&Drop hinzu
                if self.drag_drop:
                    self.drag_drop.add_files(video_files, photo_files)

                if video_files:
                    videos_imported = True

                # Füge zur Historie hinzu wenn Option aktiviert
                if skip_processed:
                    history_store = MediaHistoryStore.instance()
                    now = datetime.now().isoformat()

                    # Videos zur Historie hinzufügen
                    for file_path in video_files:
                        identity = history_store.compute_identity(file_path)
                        if identity:
                            identity_hash, size_bytes = identity
                            filename = os.path.basename(file_path)
                            history_store.upsert(
                                identity_hash=identity_hash,
                                filename=filename,
                                size_bytes=size_bytes,
                                media_type='video',
                                imported_at=now
                            )

                    # Fotos zur Historie hinzufügen
                    for file_path in photo_files:
                        identity = history_store.compute_identity(file_path)
                        if identity:
                            identity_hash, size_bytes = identity
                            filename = os.path.basename(file_path)
                            history_store.upsert(
                                identity_hash=identity_hash,
                                filename=filename,
                                size_bytes=size_bytes,
                                media_type='photo',
                                imported_at=now
                            )

                print(f"Auto-Import: {len(video_files)} Videos und {len(photo_files)} Fotos importiert")

                # Öffne passenden Tab (Video oder Foto) basierend auf Mehrheit
                self._switch_to_predominant_tab(len(video_files), len(photo_files))

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
            messagebox.showerror(
                "Import Fehler",
                f"Fehler beim Importieren der Dateien:\n{str(e)}",
                parent=self.root
            )

        finally:
            # QR-Check Status wiederherstellen
            if qr_check_was_enabled and self.drag_drop and hasattr(self.drag_drop, 'qr_check_enabled'):
                print("QR-Code-Prüfung wieder aktiviert nach Auto-Import")
                self.drag_drop.qr_check_enabled.set(True)

                # Trigger QR-Analyse für erstes importiertes Video
                if videos_imported:
                    print("Starte QR-Analyse für erstes importiertes Video")
                    video_paths = self.drag_drop.get_video_paths()
                    if video_paths:
                        self.run_qr_analysis(video_paths)

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

