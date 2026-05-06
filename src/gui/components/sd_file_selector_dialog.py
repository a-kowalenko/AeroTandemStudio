"""
Dialog zur Auswahl von Dateien von der SD-Karte mit Thumbnail- und Detail-Ansicht
"""
import tkinter as tk
from tkinter import ttk
import os
from PIL import Image, ImageTk
import subprocess
import threading
import queue
import math
from collections import deque

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class SDFileSelectorDialog:
    """Dialog zur Auswahl von Dateien von der SD-Karte"""

    def __init__(self, parent, files_info, total_size_mb):
        """
        Args:
            parent: Parent-Fenster
            files_info: Liste von Dicts mit {path, size_bytes, filename, is_video}
            total_size_mb: Gesamtgröße aller Dateien in MB
        """
        self.parent = parent
        self.files_info = files_info
        self.total_size_mb = total_size_mb
        self.selected_files = []  # Liste der ausgewählten Pfade
        self.dialog = None
        self.view_mode = "thumbnail"  # "thumbnail" oder "details"
        self.current_preview = None  # Aktuell angezeigtes Preview-Fenster

        # NEU: Zwei-Stufen-Auswahl
        self.markierte_paths = set()  # Set der markierten Pfade (temporär)
        self.selected_paths = set()  # Set der FINAL selektierten Pfade (für Import)

        # NEU: Filter-Variablen
        self.filter_type_var = tk.StringVar(value="Alle")
        self.filter_sort_var = tk.StringVar(value="Datum")  # Standard: Datum
        self.filter_sort_order_var = tk.StringVar(value="↓ Ab")  # Standard: Absteigend (neueste zuerst)
        self.thumbnail_page_size_var = tk.StringVar(value="100")

        # Standardmäßig KEINE Dateien ausgewählt (User muss explizit auswählen)
        # self.selected_paths bleibt leer

        # Thumbnail-Cache
        self.thumbnail_cache = {}  # path -> PhotoImage
        self.thumbnail_pil_cache = {}  # path -> PIL.Image
        self._prepare_file_metadata()

        # NEU: Drag-Selection Variablen
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.drag_rect = None
        self.is_drag_selecting = False
        self.drag_canvas = None
        self.canvas_container = None  # Container für Canvas-Referenz
        self.current_canvas = None  # Für Scroll-Handler
        self.current_tree = None  # TreeView-Referenz für optimierte Updates
        self.thumbnail_widgets = {}  # path -> (frame_widget, bbox)

        # NEU: Async Thumbnail-Loading
        self.thumbnail_queue = deque()  # Queue von (file_info, thumb_label) Paaren
        self.is_loading_thumbnails = False
        self.loading_cancelled = False
        self._thumbnail_workers_active = 0
        self._max_thumbnail_workers = 2
        self.thumbnail_result_queue = queue.Queue()
        self.thumbnail_ui_poll_active = False
        self.max_ui_updates_per_tick = 2

        # Progressive Rendering
        self.thumbnail_batch_size = 6
        self.details_batch_size = 250
        self._filtered_files_cache = []
        self._thumbnail_render_index = 0
        self._details_render_index = 0
        self._thumb_render_generation = 0
        self._details_render_generation = 0
        self._thumbnail_all_filtered = []
        self.thumbnail_render_tasks = {}  # path -> queued render task tuple
        self.queued_thumbnail_paths = set()
        self.inflight_thumbnail_paths = set()
        self.failed_thumbnail_paths = set()
        self._visible_enqueue_after_id = None
        self.thumbnail_row_height = 220
        self.thumbnail_cols = 4
        self.thumbnail_load_threshold = 0.85
        self.details_load_threshold = 0.90
        self.thumbnail_parent = None
        self.thumbnail_saved_render_index = 0
        self.thumbnail_saved_scroll = 0.0
        self.thumbnail_current_page = 1
        self.thumbnail_total_pages = 1
        self.thumbnail_page_jump_var = tk.StringVar(value="1")
        self.thumbnail_prefetch_queue = deque()
        self.thumbnail_prefetch_inflight = set()
        self.thumbnail_prefetch_workers_active = 0
        self.max_thumbnail_prefetch_workers = 4
        self.thumbnail_prefetch_result_queue = queue.Queue()
        self.thumbnail_prefetch_ui_poll_active = False
        self.max_prefetch_ui_updates_per_tick = 2

        # Mousewheel-Scrolling Callback (wird von switch_to_thumbnails gesetzt)
        self.mousewheel_callback = None

        # NEU: SD-Karten Überwachung für Entfernung
        self.sd_card_path = None
        self.sd_check_running = False
        self._extract_sd_card_path()

    def _prepare_file_metadata(self):
        """Berechnet Dateisystem-Metadaten einmalig für schnellere Filter/Sortierung."""
        for file_info in self.files_info:
            path = file_info.get('path')
            if not path:
                file_info['mtime'] = 0
                continue
            try:
                file_info['mtime'] = os.path.getmtime(path)
            except Exception:
                file_info['mtime'] = 0

    def show(self):
        """Zeigt den Dialog an"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Dateien auswählen")
        self.dialog.geometry("1200x800")  # Erhöht von 700 auf 800
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

        self.create_widgets()
        self.center_dialog()
        self.update_selection_info()

        # X-Button soll wie Abbrechen funktionieren
        self.dialog.protocol("WM_DELETE_WINDOW", self.on_cancel)

        # Starte SD-Karten-Überwachung
        self._start_sd_card_monitoring()

        # Initial Thumbnail-Ansicht laden
        self.switch_to_thumbnails(reset_page=True)

    def center_dialog(self):
        """Zentriert den Dialog über dem Parent-Fenster"""
        self.dialog.update_idletasks()

        # Parent-Position und -Größe
        try:
            parent_x = self.parent.winfo_x()
            parent_y = self.parent.winfo_y()
            parent_w = self.parent.winfo_width()
            parent_h = self.parent.winfo_height()
        except:
            # Fallback wenn Parent nicht verfügbar
            parent_x = 0
            parent_y = 0
            parent_w = self.dialog.winfo_screenwidth()
            parent_h = self.dialog.winfo_screenheight()

        # Dialog-Größe
        w = self.dialog.winfo_width()
        h = self.dialog.winfo_height()

        # Berechne zentrierte Position
        x = parent_x + (parent_w - w) // 2
        y = parent_y + (parent_h - h) // 2

        # Verhindere negative Koordinaten
        x = max(0, x)
        y = max(0, y)

        self.dialog.geometry(f"{w}x{h}+{x}+{y}")

    def create_widgets(self):
        """Erstellt die Widgets"""
        main_frame = tk.Frame(self.dialog, padx=15, pady=15)
        main_frame.pack(fill='both', expand=True)

        # Header
        header_frame = tk.Frame(main_frame)
        header_frame.pack(fill='x', pady=(0, 10))

        tk.Label(header_frame,
                text=f"⚠️ Zu viele Dateien auf SD-Karte ({self.total_size_mb:.0f} MB)",
                font=("Arial", 12, "bold"),
                fg="#f44336").pack(side='left')

        # Auswahl-Info und Hinweis
        info_frame = tk.Frame(main_frame)
        info_frame.pack(fill='x', pady=(0, 10))

        self.selection_label = tk.Label(info_frame,
                                       text="",
                                       font=("Arial", 10))
        self.selection_label.pack(side='left')

        # Hinweis für Auswahl
        hint_label = tk.Label(info_frame,
                             text="💡 Tipp: Klick/Drag = Markieren | Button = Zur Auswahl hinzufügen",
                             font=("Arial", 8), fg="#666")
        hint_label.pack(side='left', padx=15)

        # NEU: Tabs + Filter + Buttons in einer Row
        tab_and_filter_frame = tk.Frame(main_frame)
        tab_and_filter_frame.pack(fill='x', pady=(0, 5))

        # Links: Tabs (ttk.Notebook wie in drag_drop.py) mit Style
        style = ttk.Style()
        style.configure('Large.TNotebook.Tab',
                       font=('Arial', 8, 'bold'),
                       padding=[20, 5])  # [horizontal, vertical] padding

        self.notebook = ttk.Notebook(tab_and_filter_frame, style='Large.TNotebook')
        self.notebook.pack(side='left')

        # Dummy-Frames für Tabs (Content wird dynamisch geladen)
        self.thumbnail_tab_frame = ttk.Frame(self.notebook)
        self.details_tab_frame = ttk.Frame(self.notebook)

        self.notebook.add(self.thumbnail_tab_frame, text="Kacheln")
        self.notebook.add(self.details_tab_frame, text="Details")

        # Tab-Change-Event
        self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        # Rechts: Filter + Buttons
        right_controls = tk.Frame(tab_and_filter_frame)
        right_controls.pack(side='right', fill='x')

        # Buttons (ganz rechts)
        button_group = tk.Frame(right_controls)
        button_group.pack(side='right', padx=(10, 0))

        # NEU: Button "X Dateien auswählen" (nur sichtbar wenn markiert)
        # Dunkleres Grün für "Zur Auswahl hinzufügen"
        self.add_to_selection_button = tk.Button(button_group,
                                                 text="✓ 0 Dateien auswählen",
                                                 command=self.add_marked_to_selection,
                                                 font=("Arial", 9, "bold"),
                                                 bg="#2E7D32", fg="white",
                                                 padx=10, pady=4,
                                                 relief='raised', bd=2,
                                                 cursor='hand2')
        # Initial versteckt
        # self.add_to_selection_button.pack(side='left', padx=2)

        # "Alle markieren" - Blau mit Icon
        tk.Button(button_group, text="☑ Alle markieren",
                 command=self.mark_all,
                 font=("Arial", 9),
                 bg="#2196F3", fg="white",
                 padx=8, pady=3,
                 relief='raised', bd=1,
                 cursor='hand2').pack(side='left', padx=2)

        # "Markierung aufheben" - Orange mit Icon
        tk.Button(button_group, text="☐ Markierung aufheben",
                 command=self.unmark_all,
                 font=("Arial", 9),
                 bg="#FF9800", fg="white",
                 padx=8, pady=3,
                 relief='raised', bd=1,
                 cursor='hand2').pack(side='left', padx=2)

        # Filter (rechts, vor Buttons)
        filter_group = tk.Frame(right_controls)
        filter_group.pack(side='right', padx=(0, 10))

        # Typ-Filter
        tk.Label(filter_group, text="Typ:", font=("Arial", 9)).pack(side='left', padx=(0, 3))
        type_combo = ttk.Combobox(filter_group, textvariable=self.filter_type_var,
                                  values=["Alle", "Videos", "Fotos"],
                                  state='readonly', width=8)
        type_combo.pack(side='left', padx=(0, 8))
        type_combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())

        # Sortierung
        tk.Label(filter_group, text="Sort:", font=("Arial", 9)).pack(side='left', padx=(0, 3))
        sort_combo = ttk.Combobox(filter_group, textvariable=self.filter_sort_var,
                                 values=["Name", "Größe", "Typ", "Datum"],
                                 state='readonly', width=8)
        sort_combo.pack(side='left', padx=(0, 8))
        sort_combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())

        # Sortierrichtung
        order_combo = ttk.Combobox(filter_group, textvariable=self.filter_sort_order_var,
                                   values=["↑ Auf", "↓ Ab"],
                                   state='readonly', width=7)
        order_combo.pack(side='left')
        order_combo.bind('<<ComboboxSelected>>', lambda e: self.apply_filters())

        # Pagination (nur Kacheln)
        tk.Label(filter_group, text="Pro Seite:", font=("Arial", 9)).pack(side='left', padx=(10, 3))
        page_size_combo = ttk.Combobox(
            filter_group,
            textvariable=self.thumbnail_page_size_var,
            values=["50", "100", "200", "500"],
            state='readonly',
            width=5
        )
        page_size_combo.pack(side='left', padx=(0, 6))
        page_size_combo.bind('<<ComboboxSelected>>', lambda e: self._on_thumbnail_page_size_changed())

        self.thumb_first_button = tk.Button(
            filter_group, text="|◀", command=self._go_to_thumbnail_first,
            font=("Arial", 9), width=2
        )
        self.thumb_first_button.pack(side='left', padx=(0, 3))
        self.thumb_prev_button = tk.Button(
            filter_group, text="◀", command=lambda: self._change_thumbnail_page(-1),
            font=("Arial", 9), width=2
        )
        self.thumb_prev_button.pack(side='left', padx=(0, 6))
        self.thumb_page_label = tk.Label(filter_group, text="1/1", font=("Arial", 9), width=7)
        self.thumb_page_label.pack(side='left')
        self.thumb_jump_entry = tk.Entry(
            filter_group, textvariable=self.thumbnail_page_jump_var, width=5, justify='center'
        )
        self.thumb_jump_entry.pack(side='left', padx=(3, 3))
        self.thumb_jump_entry.bind('<Return>', lambda e: self._on_thumbnail_page_jump())
        self.thumb_jump_button = tk.Button(
            filter_group, text="Go", command=self._on_thumbnail_page_jump, font=("Arial", 9), width=3
        )
        self.thumb_jump_button.pack(side='left', padx=(0, 3))
        self.thumb_next_button = tk.Button(
            filter_group, text="▶", command=lambda: self._change_thumbnail_page(1),
            font=("Arial", 9), width=2
        )
        self.thumb_next_button.pack(side='left', padx=(8, 3))
        self.thumb_last_button = tk.Button(
            filter_group, text="▶|", command=self._go_to_thumbnail_last,
            font=("Arial", 9), width=2
        )
        self.thumb_last_button.pack(side='left', padx=(0, 0))

        # Aktualisiere Sortierrichtungs-Variable für neue Labels
        if self.filter_sort_order_var.get() == "Aufsteigend":
            self.filter_sort_order_var.set("↑ Auf")
        else:
            self.filter_sort_order_var.set("↓ Ab")

        # Container für die Ansichten - NEU: Split in Links (Tab-Content) und Rechts (Selektierte Files)
        main_content_frame = tk.Frame(main_frame)
        main_content_frame.pack(fill='both', expand=True, pady=(0, 10))

        # Links: Tab-Content (Kacheln/Details)
        self.view_container = tk.Frame(main_content_frame)
        self.view_container.pack(side='left', fill='both', expand=True)

        # Rechts: Selektierte Files Liste
        self.selection_list_frame = tk.Frame(main_content_frame, bg='#f5f5f5', width=250)
        self.selection_list_frame.pack(side='right', fill='y', padx=(10, 0))
        self.selection_list_frame.pack_propagate(False)

        # Header für Selektions-Liste
        selection_header = tk.Frame(self.selection_list_frame, bg='#e0e0e0')
        selection_header.pack(fill='x', pady=(0, 5))

        tk.Label(selection_header, text="📋 Ausgewählte Dateien",
                font=("Arial", 10, "bold"), bg='#e0e0e0').pack(side='left', padx=5, pady=5)

        # Scrollbare Liste für selektierte Files
        selection_canvas = tk.Canvas(self.selection_list_frame, bg='white', highlightthickness=0)
        selection_scrollbar = ttk.Scrollbar(self.selection_list_frame, orient='vertical',
                                           command=selection_canvas.yview)

        self.selection_list_container = tk.Frame(selection_canvas, bg='white')
        self.selection_list_container.bind(
            "<Configure>",
            lambda e: selection_canvas.configure(scrollregion=selection_canvas.bbox("all"))
        )

        selection_canvas.create_window((0, 0), window=self.selection_list_container, anchor="nw")
        selection_canvas.configure(yscrollcommand=selection_scrollbar.set)

        selection_canvas.pack(side='left', fill='both', expand=True)
        selection_scrollbar.pack(side='right', fill='y')

        # Speichere Canvas-Referenz
        self.selection_canvas = selection_canvas

        # Mousewheel-Scrolling für Auswahlliste
        def on_selection_mousewheel(event):
            selection_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            return "break"

        selection_canvas.bind('<MouseWheel>', on_selection_mousewheel)
        self.selection_list_container.bind('<MouseWheel>', on_selection_mousewheel)

        # Buttons
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill='x')

        # "Abbrechen" Button - Grau
        tk.Button(button_frame, text="✕ Abbrechen",
                 command=self.on_cancel,
                 bg="#9E9E9E", fg="white",
                 font=("Arial", 10),
                 width=18,
                 padx=10, pady=6,
                 relief='raised', bd=2,
                 cursor='hand2').pack(side='right', padx=2)

        # "Ausgewählte importieren" Button - Helles Grün (unterscheidet sich von "auswählen")
        tk.Button(button_frame, text="⏬ Ausgewählte importieren",
                 command=self.on_import_selected,
                 bg="#4CAF50", fg="white",
                 font=("Arial", 10, "bold"),
                 width=25,
                 padx=10, pady=6,
                 relief='raised', bd=2,
                 cursor='hand2').pack(side='right', padx=2)

    def switch_to_thumbnails(self, reset_page=False):
        """Wechselt zur Thumbnail-Ansicht"""
        # Restore-Infos sichern, falls wir aus der Thumbnail-Ansicht kommen
        restore_scroll = self.thumbnail_saved_scroll
        restore_render_index = self.thumbnail_saved_render_index
        if self.view_mode == "thumbnail" and self.current_canvas:
            try:
                restore_scroll = self.current_canvas.yview()[0]
            except Exception:
                pass
            restore_render_index = max(restore_render_index, self._thumbnail_render_index)

        self.view_mode = "thumbnail"

        # Lösche alte Ansicht
        for widget in self.view_container.winfo_children():
            widget.destroy()

        # Erstelle Container-Frame
        container = tk.Frame(self.view_container)
        container.pack(fill='both', expand=True)

        # Erstelle Thumbnail-Ansicht
        canvas = tk.Canvas(container, bg='white')
        scrollbar = ttk.Scrollbar(container, orient='vertical', command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg='white')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")

        def on_canvas_yview(*args):
            scrollbar.set(*args)
            self._schedule_visible_thumbnail_enqueue(canvas)
            self._maybe_render_more_thumbnails()

        canvas.configure(yscrollcommand=on_canvas_yview)

        # Speichere Canvas-Referenz (kein separates Overlay mehr)
        # Rectangle wird direkt auf Haupt-Canvas gezeichnet
        # Canvas-Items haben höhere Z-Order als create_window Widgets
        self.overlay_canvas = canvas  # Verwende Haupt-Canvas für Rectangle

        # Speichere Canvas-Referenz für Drag-Selection
        self.drag_canvas = canvas
        self.thumbnail_widgets = {}
        self.thumbnail_render_tasks = {}
        self.queued_thumbnail_paths.clear()
        self.inflight_thumbnail_paths.clear()
        self.failed_thumbnail_paths.clear()

        # Reset Thumbnail-Queue
        self.thumbnail_queue = deque()
        self.loading_cancelled = False
        self._thumb_render_generation += 1
        generation = self._thumb_render_generation

        # Canvas-Referenz für Scroll-Handler speichern
        self.current_canvas = canvas
        self.thumbnail_parent = scrollable_frame

        # Filtere/sortiere und paginiere Dateien
        self._prepare_thumbnail_page(reset_page=reset_page)
        self._thumbnail_render_index = 0
        self.thumbnail_saved_scroll = max(0.0, min(1.0, restore_scroll))
        self.thumbnail_saved_render_index = min(
            len(self._filtered_files_cache),
            max(self.thumbnail_batch_size, restore_render_index)
        )

        canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

        # Speichere Canvas-Referenz für Drag-Selection
        # Rectangle wird auf dem Haupt-Canvas gezeichnet
        self.drag_canvas = canvas
        self.canvas_container = container

        # Initialisiere Drag-State
        self.drag_start_x = None
        self.drag_start_y = None
        self.is_drag_selecting = False
        self.drag_rect = None

        # Drag-Selection: Events werden vom Haupt-Canvas empfangen, aber Rectangle wird auf Overlay gezeichnet

        def on_canvas_press(event):
            # Speichere Start für Drag in Canvas-Koordinaten (mit Scroll)
            self.drag_start_canvas_x = canvas.canvasx(event.x)
            self.drag_start_canvas_y = canvas.canvasy(event.y)
            self.is_drag_selecting = False
            self.drag_rect = None

        def on_canvas_drag(event):
            if not hasattr(self, 'drag_start_canvas_x') or self.drag_start_canvas_x is None:
                return

            # Aktuelle Position in Canvas-Koordinaten
            current_canvas_x = canvas.canvasx(event.x)
            current_canvas_y = canvas.canvasy(event.y)

            # Prüfe Mindestbewegung
            if not self.is_drag_selecting:
                dx = abs(current_canvas_x - self.drag_start_canvas_x)
                dy = abs(current_canvas_y - self.drag_start_canvas_y)

                if dx > 10 or dy > 10:
                    self.is_drag_selecting = True

                    # Erstelle Rectangle direkt auf dem Haupt-Canvas
                    # Verwende sehr dicken Rahmen und halbtransparente Füllung für Sichtbarkeit
                    self.drag_rect = canvas.create_rectangle(
                        self.drag_start_canvas_x, self.drag_start_canvas_y,
                        current_canvas_x, current_canvas_y,
                        outline='#2196F3', width=5,  # Dickerer Rahmen für bessere Sichtbarkeit
                        fill='#BBDEFB',
                        stipple='gray50',
                        tags='drag_selection_rect'
                    )
                    # Bringe Rectangle nach oben (über andere Canvas-Items, aber unter Widgets)
                    canvas.tag_raise('drag_selection_rect')

            # Update Rectangle
            if self.is_drag_selecting and self.drag_rect:
                canvas.coords(self.drag_rect,
                             self.drag_start_canvas_x, self.drag_start_canvas_y,
                             current_canvas_x, current_canvas_y)
                # Bringe Rectangle immer nach oben
                canvas.tag_raise('drag_selection_rect')

        def on_canvas_release(event):
            if not self.is_drag_selecting:
                if hasattr(self, 'drag_start_canvas_x'):
                    self.drag_start_canvas_x = None
                    self.drag_start_canvas_y = None
                return

            # Berechne Auswahlbereich in Canvas-Koordinaten
            current_canvas_x = canvas.canvasx(event.x)
            current_canvas_y = canvas.canvasy(event.y)

            canvas_x1 = min(self.drag_start_canvas_x, current_canvas_x)
            canvas_y1 = min(self.drag_start_canvas_y, current_canvas_y)
            canvas_x2 = max(self.drag_start_canvas_x, current_canvas_x)
            canvas_y2 = max(self.drag_start_canvas_y, current_canvas_y)
            # Prüfe Überschneidungen und MARKIERE (nicht selektieren!)
            for path, (widget, bbox) in self.thumbnail_widgets.items():
                # Überspringe bereits ausgewählte Files
                if path in self.selected_paths:
                    continue

                try:
                    widget_x1 = widget.winfo_x()
                    widget_y1 = widget.winfo_y()
                    widget_x2 = widget_x1 + widget.winfo_width()
                    widget_y2 = widget_y1 + widget.winfo_height()
                except Exception:
                    continue

                if not (canvas_x2 < widget_x1 or canvas_x1 > widget_x2 or
                       canvas_y2 < widget_y1 or canvas_y1 > widget_y2):
                    # Widget ist im Auswahlbereich - MARKIERE es
                    if path not in self.markierte_paths:
                        self.markierte_paths.add(path)
                        if widget.winfo_children():
                            inner_frame = widget.winfo_children()[0]
                            inner_frame.config(bg='#000000')  # Schwarz (markiert)

            # Cleanup
            if self.drag_rect:
                canvas.delete(self.drag_rect)
                self.drag_rect = None


            self.is_drag_selecting = False
            self.drag_start_canvas_x = None
            self.drag_start_canvas_y = None
            self.update_mark_button()

        # Binde auf Haupt-Canvas
        canvas.bind('<Button-1>', on_canvas_press)
        canvas.bind('<B1-Motion>', on_canvas_drag)
        canvas.bind('<ButtonRelease-1>', on_canvas_release)

        # Binde auch Scroll-Events auf Canvas
        def on_canvas_scroll(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            self._schedule_visible_thumbnail_enqueue(canvas)
            self._maybe_render_more_thumbnails()
            return "break"
        canvas.bind('<MouseWheel>', on_canvas_scroll)

        # Mausrad-Scrolling - nur für Canvas, nicht global!
        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                    self._schedule_visible_thumbnail_enqueue(canvas)
                    self._maybe_render_more_thumbnails()
                    return "break"  # Verhindere weitere Event-Propagierung
            except:
                pass  # Canvas existiert nicht mehr

        # Speichere Callback für Verwendung in create_thumbnail_widget
        self.mousewheel_callback = _on_mousewheel

        # Binde auf Canvas und scrollable_frame
        canvas.bind("<MouseWheel>", _on_mousewheel, add=True)
        scrollable_frame.bind("<MouseWheel>", _on_mousewheel, add=True)

        # WICHTIG: Binde auch auf view_container für globales Scrolling
        self.view_container.bind("<MouseWheel>", _on_mousewheel, add=True)
        canvas.bind("<Configure>", lambda e: self._schedule_visible_thumbnail_enqueue(canvas), add=True)

        # Rendere Kacheln in Batches für flüssigere UI
        self._render_thumbnail_batch(scrollable_frame, generation)
        self.dialog.after(0, self._fill_thumbnail_viewport)

    def _render_thumbnail_batch(self, parent, generation):
        """Rendert Kacheln schrittweise, um die UI responsiv zu halten."""
        if generation != self._thumb_render_generation or self.loading_cancelled:
            return
        if not parent.winfo_exists():
            return

        start = self._thumbnail_render_index
        end = min(start + self.thumbnail_batch_size, len(self._filtered_files_cache))
        cols = 4

        for idx in range(start, end):
            file_info = self._filtered_files_cache[idx]
            row = idx // self.thumbnail_cols
            col = idx % self.thumbnail_cols
            frame_widget = self.create_thumbnail_widget(parent, file_info, row, col, queue_thumbnail=False)
            if frame_widget:
                self.thumbnail_widgets[file_info['path']] = (frame_widget, (0, 0, 0, 0))

        self._thumbnail_render_index = end
        # Sicheres Initial- und Folge-Queueing für sichtbare/preload Kacheln
        self._enqueue_visible_thumbnail_tasks(self.current_canvas)
        self._schedule_visible_thumbnail_enqueue(self.current_canvas)
        return end < len(self._filtered_files_cache)

    def _maybe_render_more_thumbnails(self):
        """Rendert weitere Kachel-Widgets nur bei Bedarf (nahe Listenende)."""
        if self.view_mode != "thumbnail":
            return
        if not self.current_canvas or not self.thumbnail_parent:
            return
        if self._thumbnail_render_index >= len(self._filtered_files_cache):
            return
        try:
            _, y2 = self.current_canvas.yview()
        except Exception:
            return
        if y2 >= self.thumbnail_load_threshold:
            self._render_thumbnail_batch(self.thumbnail_parent, self._thumb_render_generation)

    def _fill_thumbnail_viewport(self):
        """Füllt initial den sichtbaren Bereich ohne Voll-Render."""
        if self.view_mode != "thumbnail" or not self.current_canvas:
            return
        # 1) Vorherigen Render-Stand nachladen (damit Tab-Wechsel nicht "vergisst")
        while self._thumbnail_render_index < self.thumbnail_saved_render_index:
            if self._thumbnail_render_index >= len(self._filtered_files_cache):
                break
            self._render_thumbnail_batch(self.thumbnail_parent, self._thumb_render_generation)

        # 2) Scrollposition wiederherstellen
        try:
            self.current_canvas.yview_moveto(self.thumbnail_saved_scroll)
        except Exception:
            pass

        # 3) Sichtbaren Bereich sicher füllen
        for _ in range(4):
            try:
                _, y2 = self.current_canvas.yview()
            except Exception:
                break
            if y2 < 1.0:
                break
            if self._thumbnail_render_index >= len(self._filtered_files_cache):
                break
            self._render_thumbnail_batch(self.thumbnail_parent, self._thumb_render_generation)

    def _schedule_visible_thumbnail_enqueue(self, canvas):
        """Debounced Trigger für viewport-basiertes Thumbnail-Prefetching."""
        if not canvas or not canvas.winfo_exists():
            return
        if self._visible_enqueue_after_id and self.dialog:
            try:
                self.dialog.after_cancel(self._visible_enqueue_after_id)
            except Exception:
                pass
        self._visible_enqueue_after_id = self.dialog.after(
            60, lambda: self._enqueue_visible_thumbnail_tasks(canvas)
        )

    def _enqueue_visible_thumbnail_tasks(self, canvas):
        """Queue nur für sichtbare Kacheln + eine Viewport-Höhe prefetch oben/unten."""
        if self.loading_cancelled or not canvas or not canvas.winfo_exists():
            return
        if not self._filtered_files_cache:
            return

        top = canvas.canvasy(0)
        viewport_height = max(1, canvas.winfo_height())
        bottom = top + viewport_height
        prefetch_top = max(0, top - viewport_height)
        prefetch_bottom = bottom + viewport_height

        start_row = max(0, int(prefetch_top // self.thumbnail_row_height))
        end_row = int(prefetch_bottom // self.thumbnail_row_height) + 1
        start_idx = start_row * self.thumbnail_cols
        end_idx = min(len(self._filtered_files_cache), (end_row + 1) * self.thumbnail_cols)

        for idx in range(start_idx, end_idx):
            path = self._filtered_files_cache[idx]['path']
            if path in self.thumbnail_cache:
                continue
            if path in self.failed_thumbnail_paths:
                continue
            if path in self.queued_thumbnail_paths or path in self.inflight_thumbnail_paths:
                continue

            task = self.thumbnail_render_tasks.get(path)
            if task:
                self.thumbnail_queue.append(task)
                self.queued_thumbnail_paths.add(path)

        # Falls bei schnellem Scrollen nichts gequeued werden konnte, lade minimal
        # den ersten noch ungeladenen gerenderten Task als Fallback.
        if not self.thumbnail_queue and not self.inflight_thumbnail_paths:
            for path, task in self.thumbnail_render_tasks.items():
                if path in self.thumbnail_cache or path in self.failed_thumbnail_paths:
                    continue
                if path in self.queued_thumbnail_paths:
                    continue
                self.thumbnail_queue.append(task)
                self.queued_thumbnail_paths.add(path)
                break

        self.start_thumbnail_loading()

    def _prefetch_adjacent_thumbnail_pages(self, page_size):
        """Lädt Thumbnails der vorherigen/nächsten Seite vor (ohne UI-Block)."""
        pages = []
        # stale inflight bereinigen, falls bereits im Cache
        self.thumbnail_prefetch_inflight = {
            p for p in self.thumbnail_prefetch_inflight
            if p not in self.thumbnail_cache and p not in self.thumbnail_pil_cache
        }
        if self.thumbnail_current_page > 1:
            pages.append(self.thumbnail_current_page - 1)
        if self.thumbnail_current_page < self.thumbnail_total_pages:
            pages.append(self.thumbnail_current_page + 1)

        for page in pages:
            start_idx = (page - 1) * page_size
            end_idx = min(len(self._thumbnail_all_filtered), start_idx + page_size)
            page_items = self._thumbnail_all_filtered[start_idx:end_idx]
            # nächste Seite priorisieren
            if page == self.thumbnail_current_page + 1:
                iterator = reversed(page_items)
                use_left = True
            else:
                iterator = page_items
                use_left = False

            for file_info in iterator:
                path = file_info['path']
                if path in self.thumbnail_cache or path in self.thumbnail_pil_cache:
                    continue
                if path in self.thumbnail_prefetch_inflight:
                    continue
                if use_left:
                    self.thumbnail_prefetch_queue.appendleft(file_info)
                else:
                    self.thumbnail_prefetch_queue.append(file_info)
                self.thumbnail_prefetch_inflight.add(path)

        self._start_thumbnail_prefetch_worker()

    def _start_thumbnail_prefetch_worker(self):
        if not self.thumbnail_prefetch_queue:
            return
        if not self.thumbnail_prefetch_ui_poll_active:
            self.thumbnail_prefetch_ui_poll_active = True
            self.dialog.after(30, self._process_prefetch_results)

        while self.thumbnail_prefetch_workers_active < self.max_thumbnail_prefetch_workers and self.thumbnail_prefetch_queue:
            self.thumbnail_prefetch_workers_active += 1
            thread = threading.Thread(target=self._thumbnail_prefetch_worker, daemon=True)
            thread.start()

    def _thumbnail_prefetch_worker(self):
        while not self.loading_cancelled:
            try:
                file_info = self.thumbnail_prefetch_queue.popleft()
            except IndexError:
                break
            path = file_info['path']
            if path in self.thumbnail_cache or path in self.thumbnail_pil_cache:
                self.thumbnail_prefetch_inflight.discard(path)
                continue
            image = self.generate_thumbnail(file_info)
            if image:
                self.thumbnail_pil_cache[path] = image
                self.thumbnail_prefetch_result_queue.put(path)
            self.thumbnail_prefetch_inflight.discard(path)
        self.thumbnail_prefetch_workers_active = max(0, self.thumbnail_prefetch_workers_active - 1)

    def _process_prefetch_results(self):
        """Konvertiert prefetched PIL-Bilder in Tk-Cache für sofortige Anzeige."""
        if self.loading_cancelled:
            self.thumbnail_prefetch_ui_poll_active = False
            return

        processed = 0
        while processed < self.max_prefetch_ui_updates_per_tick:
            try:
                path = self.thumbnail_prefetch_result_queue.get_nowait()
            except queue.Empty:
                break

            if path in self.thumbnail_cache:
                processed += 1
                continue
            pil_image = self.thumbnail_pil_cache.get(path)
            if pil_image is not None:
                try:
                    self.thumbnail_cache[path] = ImageTk.PhotoImage(pil_image)
                except Exception:
                    pass
            processed += 1

        if self.thumbnail_prefetch_workers_active > 0 or self.thumbnail_prefetch_queue or not self.thumbnail_prefetch_result_queue.empty():
            self.dialog.after(30, self._process_prefetch_results)
        else:
            self.thumbnail_prefetch_ui_poll_active = False

    def _on_tab_changed(self, event):
        """Handler für Tab-Wechsel"""
        selected_tab = self.notebook.index(self.notebook.select())
        if selected_tab == 0:
            self.switch_to_thumbnails(reset_page=False)
        else:
            self.switch_to_details()

    def _prepare_thumbnail_page(self, reset_page=False):
        """Berechnet gefilterte Kachel-Daten inkl. Pagination."""
        self._thumbnail_all_filtered = self.get_filtered_files()
        try:
            page_size = int(self.thumbnail_page_size_var.get())
        except Exception:
            page_size = 100
        page_size = max(1, page_size)

        total_items = len(self._thumbnail_all_filtered)
        self.thumbnail_total_pages = max(1, math.ceil(total_items / page_size))

        if reset_page:
            self.thumbnail_current_page = 1
        self.thumbnail_current_page = max(1, min(self.thumbnail_current_page, self.thumbnail_total_pages))

        start_idx = (self.thumbnail_current_page - 1) * page_size
        end_idx = start_idx + page_size
        self._filtered_files_cache = self._thumbnail_all_filtered[start_idx:end_idx]
        self._update_thumbnail_pagination_ui()
        self._prefetch_adjacent_thumbnail_pages(page_size)

    def _update_thumbnail_pagination_ui(self):
        """Aktualisiert Seitenanzeige/Buttons für Kacheln."""
        if hasattr(self, 'thumb_page_label'):
            self.thumb_page_label.config(text=f"{self.thumbnail_current_page}/{self.thumbnail_total_pages}")
        if hasattr(self, 'thumbnail_page_jump_var'):
            self.thumbnail_page_jump_var.set(str(self.thumbnail_current_page))
        if hasattr(self, 'thumb_first_button'):
            self.thumb_first_button.config(state=('normal' if self.thumbnail_current_page > 1 else 'disabled'))
        if hasattr(self, 'thumb_prev_button'):
            self.thumb_prev_button.config(state=('normal' if self.thumbnail_current_page > 1 else 'disabled'))
        if hasattr(self, 'thumb_next_button'):
            self.thumb_next_button.config(state=('normal' if self.thumbnail_current_page < self.thumbnail_total_pages else 'disabled'))
        if hasattr(self, 'thumb_last_button'):
            self.thumb_last_button.config(state=('normal' if self.thumbnail_current_page < self.thumbnail_total_pages else 'disabled'))

    def _on_thumbnail_page_size_changed(self):
        """Handler für geänderte Kachel-Seitengröße."""
        if self.view_mode == "thumbnail":
            self.switch_to_thumbnails(reset_page=True)

    def _change_thumbnail_page(self, delta):
        """Blättert in der Kachel-Pagination vor/zurück."""
        new_page = self.thumbnail_current_page + delta
        if new_page < 1 or new_page > self.thumbnail_total_pages:
            return
        self.thumbnail_current_page = new_page
        if self.view_mode == "thumbnail":
            self.switch_to_thumbnails(reset_page=False)

    def _go_to_thumbnail_page(self, page):
        """Springt zu einer spezifischen Kachel-Seite."""
        target = int(page)
        target = max(1, min(target, self.thumbnail_total_pages))
        if target == self.thumbnail_current_page:
            return
        self.thumbnail_current_page = target
        if self.view_mode == "thumbnail":
            self.switch_to_thumbnails(reset_page=False)

    def _go_to_thumbnail_first(self):
        """Springt auf die erste Seite."""
        self._go_to_thumbnail_page(1)

    def _go_to_thumbnail_last(self):
        """Springt auf die letzte Seite."""
        self._go_to_thumbnail_page(self.thumbnail_total_pages)

    def _on_thumbnail_page_jump(self):
        """Handler für direkte Seiteneingabe."""
        try:
            target = int(self.thumbnail_page_jump_var.get().strip())
        except Exception:
            self.thumbnail_page_jump_var.set(str(self.thumbnail_current_page))
            return
        self._go_to_thumbnail_page(target)

    def get_filtered_files(self):
        """Gibt gefilterte und sortierte Dateiliste zurück"""
        files = self.files_info.copy()

        # Typ-Filter
        filter_type = self.filter_type_var.get()
        if filter_type == "Videos":
            files = [f for f in files if f['is_video']]
        elif filter_type == "Fotos":
            files = [f for f in files if not f['is_video']]

        # Sortierung
        sort_by = self.filter_sort_var.get()
        sort_order = self.filter_sort_order_var.get()
        # Unterstütze beide Formate: "Absteigend" und "↓ Ab"
        reverse = (sort_order in ["Absteigend", "↓ Ab"])

        if sort_by == "Name":
            files.sort(key=lambda f: f['filename'].lower(), reverse=reverse)
        elif sort_by == "Größe":
            files.sort(key=lambda f: f['size_bytes'], reverse=reverse)
        elif sort_by == "Typ":
            files.sort(key=lambda f: (not f['is_video'], f['filename'].lower()), reverse=reverse)
        elif sort_by == "Datum":
            # Sortiere nach gecachtem Datei-Änderungsdatum
            files.sort(key=lambda f: f.get('mtime', 0), reverse=reverse)

        return files

    def apply_filters(self):
        """Wendet Filter an und lädt Ansicht neu"""
        if self.view_mode == "thumbnail":
            self.switch_to_thumbnails(reset_page=True)
        else:
            self.switch_to_details()

    def create_thumbnail_widget(self, parent, file_info, row, col, queue_thumbnail=True):
        """Erstellt ein Thumbnail-Widget mit Rand-Markierung"""
        path = file_info['path']
        is_marked = path in self.markierte_paths
        is_selected = path in self.selected_paths

        # Outer-Frame: Feste Größe mit festem Abstand, verhindert Verschiebung
        outer_frame = tk.Frame(parent, bg=parent.cget('bg'), width=200, height=220)
        outer_frame.grid(row=row, column=col, padx=10, pady=10, sticky='n')
        outer_frame.grid_propagate(False)  # WICHTIG: Verhindert automatische Größenanpassung

        # Inner-Frame: Immer mit Border-Space, aber Farbe ändert sich
        # Border ist IMMER 2px
        # Ausgewählt (grün) > Markiert (schwarz) > Normal (hellgrau)
        if is_selected:
            border_color = '#4CAF50'  # Grün für ausgewählt
        elif is_marked:
            border_color = '#000000'  # Schwarz für markiert
        else:
            border_color = '#e0e0e0'  # Hellgrau für normal

        frame = tk.Frame(outer_frame,
                        relief='flat',
                        borderwidth=2,
                        bg=border_color,
                        highlightthickness=0)
        frame.pack(fill='both', expand=True)

        # Content-Frame (weiß, innen)
        inner_frame = tk.Frame(frame, bg='white', padx=5, pady=5)
        inner_frame.pack(fill='both', expand=True, padx=2, pady=2)

        # Thumbnail (echtes Bild oder Icon)
        thumb_frame = tk.Frame(inner_frame, width=180, height=135, bg='#f0f0f0')
        thumb_frame.pack()
        thumb_frame.pack_propagate(False)

        # Dateiname (gekürzt)
        filename = file_info['filename']
        if len(filename) > 22:
            filename = filename[:19] + "..."

        filename_label = tk.Label(inner_frame, text=filename, font=("Arial", 9), bg='white')
        filename_label.pack(pady=(5, 0))

        # NEU: Filedatum
        import os
        import time
        try:
            mtime = os.path.getmtime(file_info['path'])
            date_str = time.strftime("%d.%m.%Y %H:%M", time.localtime(mtime))
        except:
            date_str = "Unbekannt"

        date_label = tk.Label(inner_frame, text=date_str, font=("Arial", 8), fg='#666', bg='white')
        date_label.pack()

        # Größe
        size_mb = file_info['size_bytes'] / (1024 * 1024)
        size_label = tk.Label(inner_frame, text=f"{size_mb:.1f} MB", font=("Arial", 8), fg='gray', bg='white')
        size_label.pack()

        # Events: Klick=Markieren (Toggle), Doppelklick=Vorschau - DEFINIERE ZUERST!
        def on_click(event):
            # Ausgewählte Kacheln können nicht markiert werden!
            if path in self.selected_paths:
                return  # Nichts tun

            # Toggle Markierung (nur für nicht-ausgewählte!)
            if path in self.markierte_paths:
                self.markierte_paths.remove(path)
            else:
                self.markierte_paths.add(path)

            # Update Border-Color
            is_marked = path in self.markierte_paths

            if is_marked:
                border_color = '#000000'  # Schwarz für markiert
            else:
                border_color = '#e0e0e0'  # Hellgrau für normal

            frame.config(bg=border_color)
            self.update_mark_button()

        def on_double_click(event):
            self.show_preview(file_info)

        # JETZT anzeigen: Loading-Spinner oder Icon (wird später ersetzt)
        # Prüfe ob bereits im Cache
        if path in self.thumbnail_cache:
            # Aus Cache laden
            thumbnail_img = self.thumbnail_cache[path]
            thumb_label = tk.Label(thumb_frame, image=thumbnail_img, bg='#f0f0f0')
            thumb_label.image = thumbnail_img
            thumb_label._file_path = path
            thumb_label.place(relx=0.5, rely=0.5, anchor='center')
        elif path in self.thumbnail_pil_cache:
            thumbnail_img = ImageTk.PhotoImage(self.thumbnail_pil_cache[path])
            self.thumbnail_cache[path] = thumbnail_img
            thumb_label = tk.Label(thumb_frame, image=thumbnail_img, bg='#f0f0f0')
            thumb_label.image = thumbnail_img
            thumb_label._file_path = path
            thumb_label.place(relx=0.5, rely=0.5, anchor='center')
        else:
            # Zeige Platzhalter
            if file_info['is_video']:
                # Video: Zeige Loading-Animation
                loading_text = "⏳\nLädt..."
            else:
                # Foto: Sollte schnell laden, zeige Icon
                loading_text = "🖼️"

            thumb_label = tk.Label(thumb_frame, text=loading_text, font=("Arial", 20),
                                  bg='#f0f0f0', fg='#666')
            thumb_label._file_path = path
            thumb_label.place(relx=0.5, rely=0.5, anchor='center')

            # Speichere Task für viewport-basiertes Queueing
            task = (file_info, thumb_label, thumb_frame, frame, on_click, on_double_click)
            self.thumbnail_render_tasks[path] = task
            if queue_thumbnail:
                self.thumbnail_queue.append(task)
                self.queued_thumbnail_paths.add(path)

        # NEU: Video/Foto-Icon in oberer LINKER Ecke (NACH thumb_label, damit es darüber liegt!)
        icon_text = "🎬" if file_info['is_video'] else "🖼"
        icon_bg_frame = tk.Frame(thumb_frame, bg='#333333')
        icon_bg_frame.place(relx=0.0, rely=0.0, anchor='nw', x=5, y=5)
        icon_bg_frame.lift()  # Bringe Icon ÜBER Thumbnail

        icon_label = tk.Label(icon_bg_frame, text=icon_text, font=("Arial", 14),
                             bg='#333333', fg='white', padx=2, pady=2)
        icon_label.pack()

        # NEU: X-Button für ausgewählte Kacheln (oben rechts, NACH thumb_label!)
        x_button_frame = None
        x_button_label = None
        if is_selected:
            x_button_frame = tk.Frame(thumb_frame, bg='#f44336')
            x_button_frame.place(relx=1.0, rely=0.0, anchor='ne', x=-5, y=5)
            x_button_frame.lift()  # Bringe X-Button ÜBER Thumbnail

            def on_remove_click(event):
                # Entferne aus Auswahl
                self.selected_paths.discard(path)
                self.update_selection_info()
                # Optimiert: Update nur dieses Thumbnail ohne Flackern
                self.update_single_thumbnail(path)
                return "break"  # Verhindere weitere Event-Propagierung

            x_button_label = tk.Label(x_button_frame, text="✕", font=("Arial", 12, "bold"),
                                     bg='#f44336', fg='white', padx=3, pady=1, cursor='hand2')
            x_button_label.pack()
            # Binde X-Button separat mit seinem eigenen Handler
            x_button_label.bind('<Button-1>', on_remove_click)
            x_button_frame.bind('<Button-1>', on_remove_click)

        # Binde Events an ALLE Widgets im Frame (inkl. Labels!)
        # WICHTIG: Für Drag-Selection müssen wir auch B1-Motion und ButtonRelease binden
        # WICHTIG: X-Button wird NICHT hinzugefügt, damit on_click nicht überschrieben wird
        widgets_list = [outer_frame, frame, inner_frame, thumb_frame, thumb_label, icon_bg_frame, icon_label, filename_label, date_label, size_label]

        # NICHT: X-Button wird separat behandelt (siehe oben)

        for widget in widgets_list:
            widget.bind('<Button-1>', on_click)
            widget.bind('<Double-Button-1>', on_double_click)

            # NEU: Binde Drag-Events auf Widgets für Auswahlrahmen
            # Verwende self.current_canvas da canvas hier nicht im Scope ist
            widget.bind('<B1-Motion>', self._on_widget_drag, add='+')
            widget.bind('<ButtonRelease-1>', self._on_widget_release, add='+')

            # WICHTIG: Binde Mousewheel auch auf alle Widgets für Scrolling über Thumbnails
            def make_scroll_handler(w):
                def scroll_handler(event):
                    if hasattr(self, 'current_canvas') and self.current_canvas:
                        self.current_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                    return "break"
                return scroll_handler

            widget.bind('<MouseWheel>', make_scroll_handler(widget))

        # Gebe Outer-Frame zurück für Drag-Selection
        return outer_frame

    def _on_widget_drag(self, event):
        """Helper für Drag-Events auf Widgets (für Auswahlrahmen)"""
        if not self.current_canvas:
            return

        canvas = self.current_canvas

        if not hasattr(self, 'drag_start_canvas_x') or self.drag_start_canvas_x is None:
            # Starte Drag von Widget aus
            # Konvertiere Widget-Screen-Koordinaten zu Canvas-Koordinaten
            canvas_x = event.x_root - canvas.winfo_rootx()
            canvas_y = event.y_root - canvas.winfo_rooty()

            self.drag_start_canvas_x = canvas.canvasx(canvas_x)
            self.drag_start_canvas_y = canvas.canvasy(canvas_y)
            self.is_drag_selecting = False
            self.drag_rect = None
            return

        # Aktuelle Position (Canvas-Koordinaten)
        canvas_x = event.x_root - canvas.winfo_rootx()
        canvas_y = event.y_root - canvas.winfo_rooty()
        current_canvas_x = canvas.canvasx(canvas_x)
        current_canvas_y = canvas.canvasy(canvas_y)

        # Prüfe Mindestbewegung
        if not self.is_drag_selecting:
            dx = abs(current_canvas_x - self.drag_start_canvas_x)
            dy = abs(current_canvas_y - self.drag_start_canvas_y)

            if dx > 10 or dy > 10:
                self.is_drag_selecting = True

                # Erstelle Rectangle direkt auf dem Haupt-Canvas
                self.drag_rect = canvas.create_rectangle(
                    self.drag_start_canvas_x, self.drag_start_canvas_y,
                    current_canvas_x, current_canvas_y,
                    outline='#2196F3', width=5,  # Dickerer Rahmen
                    fill='#BBDEFB',
                    stipple='gray50',
                    tags='drag_selection_rect'
                )
                canvas.tag_raise('drag_selection_rect')

        # Update Rectangle
        if self.is_drag_selecting and self.drag_rect:
            canvas.coords(self.drag_rect,
                         self.drag_start_canvas_x, self.drag_start_canvas_y,
                         current_canvas_x, current_canvas_y)
            canvas.tag_raise('drag_selection_rect')

    def _on_widget_release(self, event):
        """Helper für Release-Events auf Widgets (für Auswahlrahmen)"""
        if not self.current_canvas:
            return

        canvas = self.current_canvas

        if not self.is_drag_selecting:
            if hasattr(self, 'drag_start_canvas_x'):
                self.drag_start_canvas_x = None
                self.drag_start_canvas_y = None
            return

        # Aktuelle Position (Canvas-Koordinaten)
        canvas_x = event.x_root - canvas.winfo_rootx()
        canvas_y = event.y_root - canvas.winfo_rooty()
        current_canvas_x = canvas.canvasx(canvas_x)
        current_canvas_y = canvas.canvasy(canvas_y)

        # Berechne Auswahlbereich
        canvas_x1 = min(self.drag_start_canvas_x, current_canvas_x)
        canvas_y1 = min(self.drag_start_canvas_y, current_canvas_y)
        canvas_x2 = max(self.drag_start_canvas_x, current_canvas_x)
        canvas_y2 = max(self.drag_start_canvas_y, current_canvas_y)

        # Prüfe Überschneidungen und MARKIERE (nicht selektieren!)
        for path, (widget, bbox) in self.thumbnail_widgets.items():
            # Überspringe bereits ausgewählte Files
            if path in self.selected_paths:
                continue

            try:
                widget_x1 = widget.winfo_x()
                widget_y1 = widget.winfo_y()
                widget_x2 = widget_x1 + widget.winfo_width()
                widget_y2 = widget_y1 + widget.winfo_height()
            except Exception:
                continue

            if not (canvas_x2 < widget_x1 or canvas_x1 > widget_x2 or
                   canvas_y2 < widget_y1 or canvas_y1 > widget_y2):
                # Widget ist im Auswahlbereich - MARKIERE es
                if path not in self.markierte_paths:
                    self.markierte_paths.add(path)
                    if widget.winfo_children():
                        inner_frame = widget.winfo_children()[0]
                        inner_frame.config(bg='#000000')  # Schwarz (markiert)

        # Cleanup
        if self.drag_rect:
            canvas.delete(self.drag_rect)
            self.drag_rect = None


        self.is_drag_selecting = False
        self.drag_start_canvas_x = None
        self.drag_start_canvas_y = None
        self.update_mark_button()

    def generate_thumbnail(self, file_info):
        """Generiert PIL-Thumbnail für Datei (ohne Tk-Aufrufe im Worker-Thread)."""
        path = file_info['path']
        if path in self.thumbnail_pil_cache:
            try:
                return self.thumbnail_pil_cache[path].copy()
            except Exception:
                pass

        try:
            if file_info['is_video']:
                # Video-Thumbnail: Extrahiere ersten Frame mit FFmpeg
                import tempfile
                import subprocess

                # Erstelle temporäres Bild
                with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
                    tmp_path = tmp.name

                try:
                    # FFmpeg-Kommando: Extrahiere Frame bei 1 Sekunde
                    cmd = [
                        'ffmpeg',
                        '-ss', '1',  # Springe zu 1 Sekunde
                        '-i', path,  # Input-Video
                        '-vframes', '1',  # Nur 1 Frame
                        '-vf', 'scale=180:135:force_original_aspect_ratio=decrease',  # Skaliere
                        '-y',  # Überschreibe
                        tmp_path
                    ]

                    # Führe FFmpeg aus (leise)
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                    # Lade generiertes Bild als PIL-Objekt
                    img = Image.open(tmp_path)
                    img_copy = img.copy()
                    img.close()
                    self.thumbnail_pil_cache[path] = img_copy.copy()

                    # Lösche temporäre Datei
                    import os
                    os.unlink(tmp_path)

                    return img_copy
                except Exception as e:
                    print(f"FFmpeg-Fehler für {file_info['filename']}: {e}")
                    # Cleanup
                    try:
                        import os
                        os.unlink(tmp_path)
                    except:
                        pass
                    return None
            else:
                # Foto-Thumbnail
                img = Image.open(path)
                img.thumbnail((180, 135), Image.Resampling.LANCZOS)
                img_copy = img.copy()
                self.thumbnail_pil_cache[path] = img_copy.copy()
                return img_copy
        except Exception as e:
            print(f"Fehler beim Thumbnail-Generieren für {file_info['filename']}: {e}")
            return None

    def toggle_selection(self, path):
        """Togglet Auswahl einer Datei"""
        if path in self.selected_paths:
            self.selected_paths.remove(path)
        else:
            self.selected_paths.add(path)

    def switch_to_details(self):
        """Wechselt zur Detail-Ansicht"""
        # Zustand der Thumbnail-Ansicht merken, bevor sie neu aufgebaut wird
        if self.current_canvas:
            try:
                self.thumbnail_saved_scroll = self.current_canvas.yview()[0]
            except Exception:
                pass
        self.thumbnail_saved_render_index = max(self.thumbnail_saved_render_index, self._thumbnail_render_index)

        self.view_mode = "details"

        # Lösche alte Ansicht
        for widget in self.view_container.winfo_children():
            widget.destroy()

        # Erstelle Detail-Ansicht
        tree_frame = tk.Frame(self.view_container)
        tree_frame.pack(fill='both', expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical')
        scrollbar.pack(side='right', fill='y')

        def on_tree_yview(*args):
            scrollbar.set(*args)
            self._maybe_render_more_details()

        tree = ttk.Treeview(tree_frame,
                           columns=('select', 'filename', 'type', 'size', 'date', 'path'),
                           show='headings',
                           yscrollcommand=on_tree_yview)
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.config(command=tree.yview)

        # Speichere TreeView-Referenz für optimierte Updates
        self.current_tree = tree

        # NEU: Aktiviere Multi-Selection im Treeview
        tree.config(selectmode='extended')  # Erlaubt Shift+Ctrl Multi-Selection

        # Spalten
        tree.heading('select', text='✓')
        tree.heading('filename', text='Dateiname')
        tree.heading('type', text='Typ')
        tree.heading('size', text='Größe')
        tree.heading('date', text='Datum')
        tree.heading('path', text='Pfad')

        tree.column('select', width=40, anchor='center')
        tree.column('filename', width=220)
        tree.column('type', width=70, anchor='center')
        tree.column('size', width=90, anchor='e')
        tree.column('date', width=130, anchor='center')
        tree.column('path', width=250)

        # Filtere und sortiere Dateien
        self._filtered_files_cache = self.get_filtered_files()
        self._details_render_index = 0
        self._details_render_generation += 1
        generation = self._details_render_generation
        self._render_details_batch(tree, generation)
        self.dialog.after(0, self._fill_details_viewport)

        # Events
        def on_tree_select(event):
            # Lösche alle Markierungen und setze neu basierend auf TreeView-Selection
            selected_items = tree.selection()
            new_markierte_paths = set()
            for item in selected_items:
                path = tree.item(item)['tags'][0]
                if path not in self.selected_paths:
                    new_markierte_paths.add(path)
            self.markierte_paths = new_markierte_paths

            for item in tree.get_children():
                path = tree.item(item)['tags'][0]
                values = list(tree.item(item)['values'])
                if path in self.selected_paths:
                    values[0] = '✅'
                elif path in self.markierte_paths:
                    values[0] = '⬛'
                else:
                    values[0] = ''
                tree.item(item, values=values)

            self.update_mark_button()

        tree.bind('<<TreeviewSelect>>', on_tree_select)

        def on_double_click(event):
            item = tree.identify_row(event.y)
            if item:
                path = tree.item(item)['tags'][0]
                file_info = next(f for f in self.files_info if f['path'] == path)
                self.show_preview(file_info)

        tree.bind('<Double-Button-1>', on_double_click)

    def _render_details_batch(self, tree, generation):
        """Fügt Detail-Zeilen in Batches ein, um Hänger zu vermeiden."""
        if generation != self._details_render_generation:
            return
        if not tree.winfo_exists():
            return

        start = self._details_render_index
        end = min(start + self.details_batch_size, len(self._filtered_files_cache))
        for idx in range(start, end):
            file_info = self._filtered_files_cache[idx]
            is_marked = file_info['path'] in self.markierte_paths
            is_selected = file_info['path'] in self.selected_paths

            # Markierungs-Symbol
            if is_selected:
                mark_symbol = '✅'  # Grün: Ausgewählt
            elif is_marked:
                mark_symbol = '⬛'  # Schwarz: Markiert
            else:
                mark_symbol = ''

            size_mb = file_info['size_bytes'] / (1024 * 1024)

            # Filedatum
            import time
            try:
                mtime = file_info.get('mtime', 0)
                date_str = time.strftime("%d.%m.%Y %H:%M", time.localtime(mtime))
            except:
                date_str = "Unbekannt"

            tree.insert('', 'end', values=(
                mark_symbol,
                file_info['filename'],
                'Video' if file_info['is_video'] else 'Foto',
                f"{size_mb:.1f} MB",
                date_str,
                file_info['path']
            ), tags=(file_info['path'],))
        self._details_render_index = end
        return end < len(self._filtered_files_cache)

    def _maybe_render_more_details(self):
        """Rendert weitere Detail-Zeilen nur bei Bedarf."""
        if self.view_mode != "details":
            return
        if not self.current_tree or not self.current_tree.winfo_exists():
            return
        if self._details_render_index >= len(self._filtered_files_cache):
            return
        try:
            _, y2 = self.current_tree.yview()
        except Exception:
            return
        if y2 >= self.details_load_threshold:
            self._render_details_batch(self.current_tree, self._details_render_generation)

    def _fill_details_viewport(self):
        """Füllt initial den sichtbaren Bereich in der Detailansicht."""
        if self.view_mode != "details" or not self.current_tree:
            return
        for _ in range(3):
            try:
                _, y2 = self.current_tree.yview()
            except Exception:
                break
            if y2 < 1.0:
                break
            if self._details_render_index >= len(self._filtered_files_cache):
                break
            self._render_details_batch(self.current_tree, self._details_render_generation)

    def show_preview(self, file_info):
        """Zeigt Vorschau für eine Datei"""
        if file_info['is_video']:
            # Video mit Standard-Player öffnen
            try:
                if os.name == 'nt':  # Windows
                    os.startfile(file_info['path'])
                else:  # Linux/Mac
                    subprocess.Popen(['xdg-open', file_info['path']])
            except Exception as e:
                print(f"Fehler beim Öffnen der Vorschau: {e}")
        else:
            # Foto in neuem Fenster anzeigen
            self.show_image_preview(file_info)

    def show_image_preview(self, file_info):
        """Zeigt Bild-Vorschau in neuem Fenster"""
        preview_window = tk.Toplevel(self.dialog)
        preview_window.title(f"Vorschau: {file_info['filename']}")
        preview_window.geometry("800x600")

        try:
            img = Image.open(file_info['path'])
            # Skaliere auf maximal 780x580
            img.thumbnail((780, 580), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)

            label = tk.Label(preview_window, image=photo)
            label.image = photo  # Referenz behalten
            label.pack(expand=True)
        except Exception as e:
            tk.Label(preview_window, text=f"Fehler beim Laden: {e}").pack(expand=True)

    def update_selection_info(self):
        """Aktualisiert die Auswahl-Info"""
        selected_count = len(self.selected_paths)
        selected_size = sum(
            f['size_bytes'] for f in self.files_info
            if f['path'] in self.selected_paths
        ) / (1024 * 1024)

        self.selection_label.config(
            text=f"Ausgewählt: {selected_count} von {len(self.files_info)} Dateien ({selected_size:.0f} MB)"
        )

        # Update Selektions-Liste rechts
        self.update_selection_list()

    def update_single_thumbnail(self, path):
        """
        Aktualisiert nur ein einzelnes Thumbnail/TreeView-Item ohne die gesamte Ansicht neu zu laden.
        Verhindert Flackern beim Hinzufügen/Entfernen aus der Auswahl.
        """
        if self.view_mode == "details":
            # Details-Ansicht: Update nur das betroffene TreeView-Item
            self._update_tree_item(path)
            return

        # Thumbnail-Ansicht: (bestehende Logik)
        # Finde das Widget für diesen Pfad
        if path not in self.thumbnail_widgets:
            # Widget existiert nicht (z.B. gefiltert), lade komplett neu
            self.apply_filters()
            return

        outer_frame, bbox = self.thumbnail_widgets[path]

        # Prüfe ob Widget noch existiert
        if not outer_frame.winfo_exists():
            self.apply_filters()
            return

        # Hole file_info
        file_info = next((f for f in self.files_info if f['path'] == path), None)
        if not file_info:
            return

        try:
            # Finde relevante Child-Widgets
            frame = outer_frame.winfo_children()[0]  # Der Border-Frame
            inner_frame = frame.winfo_children()[0]  # Der Content-Frame
            thumb_frame = inner_frame.winfo_children()[0]  # Der Thumbnail-Frame

            # Bestimme neuen Status
            is_marked = path in self.markierte_paths
            is_selected = path in self.selected_paths

            # Update Border-Farbe
            if is_selected:
                border_color = '#4CAF50'  # Grün für ausgewählt
            elif is_marked:
                border_color = '#000000'  # Schwarz für markiert
            else:
                border_color = '#e0e0e0'  # Hellgrau für normal

            frame.config(bg=border_color)

            # X-Button Management
            # Suche nach existierendem X-Button (erkennbar an bg='#f44336')
            x_button_frame = None
            for widget in thumb_frame.winfo_children():
                if isinstance(widget, tk.Frame) and widget.cget('bg') == '#f44336':
                    x_button_frame = widget
                    break

            if is_selected and not x_button_frame:
                # X-Button hinzufügen
                x_button_frame = tk.Frame(thumb_frame, bg='#f44336')
                x_button_frame.place(relx=1.0, rely=0.0, anchor='ne', x=-5, y=5)
                x_button_frame.lift()

                def on_remove_click(event):
                    self.selected_paths.discard(path)
                    self.update_selection_info()
                    self.update_single_thumbnail(path)
                    return "break"

                x_button_label = tk.Label(x_button_frame, text="✕", font=("Arial", 12, "bold"),
                                         bg='#f44336', fg='white', padx=3, pady=1, cursor='hand2')
                x_button_label.pack()
                x_button_label.bind('<Button-1>', on_remove_click)
                x_button_frame.bind('<Button-1>', on_remove_click)

            elif not is_selected and x_button_frame:
                # X-Button entfernen
                x_button_frame.destroy()

        except Exception as e:
            # Fallback: Komplette Ansicht neu laden
            print(f"Fehler beim Update von Thumbnail {path}: {e}")
            self.apply_filters()

    def _update_tree_item(self, path):
        """Aktualisiert nur ein TreeView-Item ohne Flackern"""
        if not self.current_tree or not self.current_tree.winfo_exists():
            return

        tree = self.current_tree

        # Finde das TreeView-Item für diesen Pfad
        for item in tree.get_children():
            if tree.item(item)['tags'][0] == path:
                # Update nur das Symbol in der ersten Spalte
                values = list(tree.item(item)['values'])

                is_marked = path in self.markierte_paths
                is_selected = path in self.selected_paths

                if is_selected:
                    values[0] = '✅'  # Grün: Ausgewählt
                elif is_marked:
                    values[0] = '⬛'  # Schwarz: Markiert
                else:
                    values[0] = ''

                tree.item(item, values=values)
                break

    def update_multiple_thumbnails(self, paths):
        """
        Aktualisiert mehrere Thumbnails/TreeView-Items ohne die gesamte Ansicht neu zu laden.
        Optimiert für Batch-Updates (mark_all, add_marked_to_selection, etc.)
        """
        if self.view_mode == "details":
            # Details-Ansicht: Update alle betroffenen TreeView-Items
            self._update_tree_items(paths)
            return

        # Thumbnail-Ansicht: Update jedes Thumbnail einzeln
        for path in paths:
            if path in self.thumbnail_widgets:
                outer_frame, bbox = self.thumbnail_widgets[path]

                try:
                    if outer_frame.winfo_exists():
                        # Finde relevante Child-Widgets
                        frame = outer_frame.winfo_children()[0]  # Der Border-Frame
                        inner_frame = frame.winfo_children()[0]  # Der Content-Frame
                        thumb_frame = inner_frame.winfo_children()[0]  # Der Thumbnail-Frame

                        # Bestimme neuen Status
                        is_marked = path in self.markierte_paths
                        is_selected = path in self.selected_paths

                        # Update Border-Farbe
                        if is_selected:
                            border_color = '#4CAF50'
                        elif is_marked:
                            border_color = '#000000'
                        else:
                            border_color = '#e0e0e0'

                        frame.config(bg=border_color)

                        # X-Button Management
                        x_button_frame = None
                        for widget in thumb_frame.winfo_children():
                            if isinstance(widget, tk.Frame) and widget.cget('bg') == '#f44336':
                                x_button_frame = widget
                                break

                        if is_selected and not x_button_frame:
                            # X-Button hinzufügen
                            x_button_frame = tk.Frame(thumb_frame, bg='#f44336')
                            x_button_frame.place(relx=1.0, rely=0.0, anchor='ne', x=-5, y=5)
                            x_button_frame.lift()

                            def make_remove_handler(p):
                                def on_remove_click(event):
                                    self.selected_paths.discard(p)
                                    self.update_selection_info()
                                    self.update_single_thumbnail(p)
                                    return "break"
                                return on_remove_click

                            x_button_label = tk.Label(x_button_frame, text="✕", font=("Arial", 12, "bold"),
                                                     bg='#f44336', fg='white', padx=3, pady=1, cursor='hand2')
                            x_button_label.pack()
                            handler = make_remove_handler(path)
                            x_button_label.bind('<Button-1>', handler)
                            x_button_frame.bind('<Button-1>', handler)

                        elif not is_selected and x_button_frame:
                            # X-Button entfernen
                            x_button_frame.destroy()

                except Exception as e:
                    print(f"Fehler beim Update von Thumbnail {path}: {e}")
                    pass  # Ignoriere Fehler bei einzelnen Widgets

    def _update_tree_items(self, paths):
        """Aktualisiert mehrere TreeView-Items ohne Flackern"""
        if not self.current_tree or not self.current_tree.winfo_exists():
            return

        tree = self.current_tree
        paths_set = set(paths)

        # Update alle betroffenen Items
        for item in tree.get_children():
            item_path = tree.item(item)['tags'][0]
            if item_path in paths_set:
                # Update nur das Symbol in der ersten Spalte
                values = list(tree.item(item)['values'])

                is_marked = item_path in self.markierte_paths
                is_selected = item_path in self.selected_paths

                if is_selected:
                    values[0] = '✅'  # Grün: Ausgewählt
                elif is_marked:
                    values[0] = '⬛'  # Schwarz: Markiert
                else:
                    values[0] = ''

                tree.item(item, values=values)

    def update_mark_button(self):
        """Aktualisiert den 'X Dateien auswählen' Button"""
        marked_count = len(self.markierte_paths)

        if marked_count > 0:
            # Button anzeigen und Text aktualisieren (mit Icon)
            self.add_to_selection_button.config(
                text=f"✓ {marked_count} {'Datei' if marked_count == 1 else 'Dateien'} auswählen"
            )
            if not self.add_to_selection_button.winfo_ismapped():
                # Pack Button einfach (erscheint an erster Stelle wenn vorher pack_forget)
                self.add_to_selection_button.pack(side='left', padx=2)
        else:
            # Button verstecken
            self.add_to_selection_button.pack_forget()

    def add_marked_to_selection(self):
        """Fügt markierte Dateien zur Selektion hinzu"""
        # Merke betroffene Pfade für Update
        affected_paths = set(self.markierte_paths)

        # Füge alle markierten zur Selektion hinzu
        self.selected_paths.update(self.markierte_paths)

        # Lösche Markierung
        self.markierte_paths.clear()

        # Update Button
        self.update_mark_button()

        # Update Info
        self.update_selection_info()

        # Optimiert: Update nur betroffene Thumbnails ohne Flackern
        self.update_multiple_thumbnails(affected_paths)

    def mark_all(self):
        """Markiert alle sichtbaren (gefilterten) Dateien"""
        filtered_files = self.get_filtered_files()
        affected_paths = set()
        for file_info in filtered_files:
            if file_info['path'] not in self.selected_paths:  # Nur nicht-ausgewählte
                self.markierte_paths.add(file_info['path'])
                affected_paths.add(file_info['path'])

        self.update_mark_button()
        # Optimiert: Update nur betroffene Thumbnails ohne Flackern
        self.update_multiple_thumbnails(affected_paths)

    def unmark_all(self):
        """Hebt alle Markierungen auf"""
        # Merke betroffene Pfade für Update
        affected_paths = set(self.markierte_paths)

        self.markierte_paths.clear()
        self.update_mark_button()

        # Optimiert: Update nur betroffene Thumbnails ohne Flackern
        self.update_multiple_thumbnails(affected_paths)

    def update_selection_list(self):
        """Aktualisiert die Liste der selektierten Dateien rechts (optimiert ohne Flackern)"""
        # Hole aktuelle Widgets (als Dict: path -> widget)
        current_widgets = {}
        for widget in self.selection_list_container.winfo_children():
            # Pfad ist im Widget als Attribut gespeichert (falls vorhanden)
            if hasattr(widget, '_file_path'):
                current_widgets[widget._file_path] = widget

        # Sortierte Liste der gewünschten Pfade
        desired_paths = sorted(self.selected_paths)
        current_paths = list(current_widgets.keys())

        # Prüfe ob sich die Liste geändert hat
        if desired_paths == current_paths:
            # Keine Änderung, nichts zu tun
            return

        # Diff berechnen
        paths_to_add = set(desired_paths) - set(current_paths)
        paths_to_remove = set(current_paths) - set(desired_paths)

        # Entferne nicht mehr benötigte Widgets
        for path in paths_to_remove:
            if path in current_widgets:
                current_widgets[path].destroy()
                del current_widgets[path]

        # Wenn nur hinzugefügt oder nur entfernt wurde, können wir optimieren
        if len(paths_to_add) > 0 or len(paths_to_remove) > 0:
            # Prüfe ob Reihenfolge noch stimmt
            remaining_paths = [p for p in current_paths if p in desired_paths]
            needs_reorder = remaining_paths != [p for p in desired_paths if p in remaining_paths]

            if needs_reorder or len(paths_to_add) > 3:
                # Bei großen Änderungen oder Neuordnung: Kompletter Rebuild (aber nur dann)
                for widget in self.selection_list_container.winfo_children():
                    widget.destroy()
                current_widgets = {}
                paths_to_add = set(desired_paths)

            # Füge neue Items hinzu
            for path in desired_paths:
                if path not in current_widgets:
                    # Finde file_info
                    file_info = next((f for f in self.files_info if f['path'] == path), None)
                    if not file_info:
                        continue

                    # Item-Frame
                    item_frame = tk.Frame(self.selection_list_container, bg='white', relief='flat', borderwidth=0)
                    item_frame._file_path = path  # Speichere Pfad für spätere Identifikation
                    item_frame.pack(fill='x', padx=5, pady=2)

                    # Icon + Filename
                    info_frame = tk.Frame(item_frame, bg='white')
                    info_frame.pack(side='left', fill='both', expand=True, padx=5, pady=3)

                    icon = "🎬" if file_info['is_video'] else "🖼️"
                    tk.Label(info_frame, text=icon, font=("Arial", 12), bg='white').pack(side='left', padx=(0, 5))

                    # Dateiname (gekürzt)
                    filename = file_info['filename']
                    if len(filename) > 20:
                        filename = filename[:17] + "..."
                    tk.Label(info_frame, text=filename, font=("Arial", 8), bg='white', anchor='w').pack(side='left', fill='x', expand=True)

                    # Entfernen-Button
                    def make_remove_handler(p):
                        def remove():
                            self.selected_paths.remove(p)
                            self.update_selection_info()
                            # Optimiert: Update nur dieses Thumbnail ohne Flackern
                            self.update_single_thumbnail(p)
                        return remove

                    tk.Button(item_frame, text="✕", command=make_remove_handler(path),
                             bg='#f44336', fg='white', font=("Arial", 8, "bold"),
                             width=2, relief='flat').pack(side='right', padx=2)

    def select_all(self):
        """Wählt alle Dateien aus"""
        for file_info in self.files_info:
            self.selected_paths.add(file_info['path'])
        self.update_selection_info()
        # Aktualisiere aktuelle Ansicht
        self.apply_filters()

    def deselect_all(self):
        """Wählt alle Dateien ab"""
        self.selected_paths.clear()
        self.update_selection_info()
        # Aktualisiere aktuelle Ansicht
        self.apply_filters()

    def on_import_selected(self):
        """Bestätigt Auswahl und schließt Dialog"""
        self.selected_files = list(self.selected_paths)

        if not self.selected_files:
            tk.messagebox.showwarning("Keine Auswahl",
                                     "Bitte wählen Sie mindestens eine Datei aus.",
                                     parent=self.dialog)
            return

        # Stoppe Thumbnail-Loading und SD-Monitoring
        self.loading_cancelled = True
        self.sd_check_running = False
        self.dialog.destroy()

    def on_cancel(self):
        """Bricht ab ohne Auswahl"""
        self.selected_files = None
        # Stoppe Thumbnail-Loading und SD-Monitoring
        self.loading_cancelled = True
        self.sd_check_running = False
        self.dialog.destroy()

    def get_selected_files(self):
        """Gibt ausgewählte Dateien zurück (nach Dialog-Schließung)"""
        return self.selected_files

    def start_thumbnail_loading(self):
        """Startet asynchrones Laden der Thumbnails in einem Background-Thread"""
        if not self.thumbnail_queue:
            return

        if not self.thumbnail_ui_poll_active:
            self.thumbnail_ui_poll_active = True
            self.dialog.after(20, self._process_thumbnail_results)

        while self._thumbnail_workers_active < self._max_thumbnail_workers and self.thumbnail_queue:
            self._thumbnail_workers_active += 1
            self.is_loading_thumbnails = True
            thread = threading.Thread(target=self._load_thumbnails_worker, daemon=True)
            thread.start()

    def _load_thumbnails_worker(self):
        """Worker-Thread: Lädt Thumbnails nacheinander und aktualisiert UI"""
        while not self.loading_cancelled:
            try:
                file_info, thumb_label, thumb_frame, container_frame, on_click, on_double_click = self.thumbnail_queue.popleft()
            except IndexError:
                break

            path = file_info['path']
            self.queued_thumbnail_paths.discard(path)
            self.inflight_thumbnail_paths.add(path)

            # Bereits gerendertes Tk-Thumbnail wiederverwenden
            if path in self.thumbnail_cache:
                self.thumbnail_result_queue.put((thumb_label, thumb_frame, self.thumbnail_cache[path], None, on_click, on_double_click))
                continue
            if path in self.thumbnail_pil_cache:
                self.thumbnail_result_queue.put((thumb_label, thumb_frame, None, self.thumbnail_pil_cache[path].copy(), on_click, on_double_click))
                continue

            # Generiere PIL-Thumbnail im Worker
            thumbnail_image = self.generate_thumbnail(file_info)
            if thumbnail_image and not self.loading_cancelled:
                self.thumbnail_result_queue.put((thumb_label, thumb_frame, None, thumbnail_image, on_click, on_double_click))
            elif not self.loading_cancelled:
                icon = "🎬" if file_info['is_video'] else "🖼️"
                self.thumbnail_result_queue.put((thumb_label, thumb_frame, None, icon, on_click, on_double_click))

        self._thumbnail_workers_active = max(0, self._thumbnail_workers_active - 1)
        self.is_loading_thumbnails = self._thumbnail_workers_active > 0
        if not self.is_loading_thumbnails and not self.thumbnail_queue and not self.loading_cancelled:
            # Nach Worker-Ende ggf. neue sichtbare Tasks nachziehen
            self._schedule_visible_thumbnail_enqueue(self.current_canvas)

    def _process_thumbnail_results(self):
        """Verarbeitet Thumbnail-Ergebnisse im UI-Thread in kleinen Batches."""
        if self.loading_cancelled:
            self.thumbnail_ui_poll_active = False
            return

        processed = 0
        while processed < self.max_ui_updates_per_tick:
            try:
                thumb_label, thumb_frame, cached_photo, payload, on_click, on_double_click = self.thumbnail_result_queue.get_nowait()
            except queue.Empty:
                break

            if cached_photo is not None:
                self._update_thumbnail_ui(thumb_label, thumb_frame, cached_photo, on_click, on_double_click)
            elif isinstance(payload, Image.Image):
                photo = ImageTk.PhotoImage(payload)
                self._update_thumbnail_ui(thumb_label, thumb_frame, photo, on_click, on_double_click)
            else:
                self._update_thumbnail_fallback(thumb_label, payload)
                path = getattr(thumb_label, "_file_path", None)
                if path:
                    self.failed_thumbnail_paths.add(path)
            path = getattr(thumb_label, "_file_path", None)
            if path:
                self.inflight_thumbnail_paths.discard(path)
            processed += 1

        if (self._thumbnail_workers_active > 0) or (not self.thumbnail_result_queue.empty()):
            self.dialog.after(20, self._process_thumbnail_results)
        else:
            self.thumbnail_ui_poll_active = False

    def _update_thumbnail_ui(self, thumb_label, thumb_frame, thumbnail_img, on_click, on_double_click):
        """Aktualisiert Thumbnail im UI (läuft im Haupt-Thread)"""
        try:
            # Cache für spätere Wiederverwendung
            file_path = getattr(thumb_label, "_file_path", None)
            if file_path and file_path not in self.thumbnail_cache:
                self.thumbnail_cache[file_path] = thumbnail_img

            # Lösche alten Platzhalter
            thumb_label.destroy()

            # Erstelle neues Label mit Thumbnail
            new_label = tk.Label(thumb_frame, image=thumbnail_img, bg='#f0f0f0')
            new_label.image = thumbnail_img  # Referenz behalten
            if file_path:
                new_label._file_path = file_path
            new_label.place(relx=0.5, rely=0.5, anchor='center')

            # WICHTIG: Binde Click-Events auf das neue Label
            new_label.bind('<Button-1>', on_click)
            new_label.bind('<Double-Button-1>', on_double_click)

            # Binde Drag-Events für Auswahlrahmen
            new_label.bind('<B1-Motion>', self._on_widget_drag, add='+')
            new_label.bind('<ButtonRelease-1>', self._on_widget_release, add='+')

            # Binde Mousewheel für Scrolling
            def scroll_handler(event):
                if hasattr(self, 'current_canvas') and self.current_canvas:
                    self.current_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
                return "break"
            new_label.bind('<MouseWheel>', scroll_handler)

            # WICHTIG: Bringe ALLE Overlay-Frames (Icon + X-Button) über das Thumbnail
            for child in thumb_frame.winfo_children():
                if isinstance(child, tk.Frame):  # Icon-Frame oder X-Button-Frame
                    child.lift()  # Bringe nach vorne, über das Thumbnail
        except:
            pass  # Widget existiert nicht mehr

    def _update_thumbnail_fallback(self, thumb_label, icon):
        """Zeigt Fallback-Icon wenn Thumbnail-Generierung fehlschlägt"""
        try:
            thumb_label.config(text=icon, font=("Arial", 40), fg='#999')
        except:
            pass  # Widget existiert nicht mehr

    def _extract_sd_card_path(self):
        """Extrahiert den SD-Karten-Pfad aus den Dateiinfos"""
        if not self.files_info:
            return

        # Nimm den ersten Dateipfad und extrahiere das Laufwerk
        first_path = self.files_info[0]['path']

        # Extrahiere Laufwerk (z.B. "D:" aus "D:\DCIM\...")
        if len(first_path) >= 2 and first_path[1] == ':':
            self.sd_card_path = first_path[:2]  # z.B. "D:"
            print(f"SD-Karte erkannt: {self.sd_card_path}")

    def _check_sd_card_available(self):
        """Prüft ob die SD-Karte noch verfügbar ist"""
        if not self.sd_card_path:
            return True  # Kein Pfad bekannt, nehmen an es ist ok

        try:
            # Versuche auf das Laufwerk zuzugreifen
            drive_path = self.sd_card_path + "\\"
            os.listdir(drive_path)
            return True
        except (OSError, PermissionError, FileNotFoundError):
            # Laufwerk nicht verfügbar
            return False
        except Exception as e:
            print(f"Fehler beim SD-Karten-Check: {e}")
            return True  # Bei unbekanntem Fehler nicht warnen

    def _start_sd_card_monitoring(self):
        """Startet die periodische Überwachung der SD-Karte"""
        if not self.sd_card_path:
            return  # Kein Laufwerk zu überwachen

        self.sd_check_running = True
        self._schedule_sd_check()

    def _schedule_sd_check(self):
        """Plant den nächsten SD-Karten-Check"""
        if not self.sd_check_running:
            return

        # Prüfe alle 1 Sekunde
        try:
            self.dialog.after(1000, self._perform_sd_check)
        except:
            # Dialog wurde geschlossen
            self.sd_check_running = False

    def _perform_sd_check(self):
        """Führt die SD-Karten-Prüfung durch"""
        if not self.sd_check_running:
            return

        # Prüfe ob SD-Karte noch verfügbar ist
        if not self._check_sd_card_available():
            # SD-Karte wurde entfernt!
            print("⚠️ SD-Karte wurde entfernt!")
            self.sd_check_running = False
            self._handle_sd_card_removed()
            return

        # Nächster Check
        self._schedule_sd_check()

    def _handle_sd_card_removed(self):
        """Behandelt die Entfernung der SD-Karte"""
        # Stoppe Thumbnail-Loading
        self.loading_cancelled = True

        # Zeige Error-Dialog
        from src.gui.components.error_dialog import show_error_dialog

        try:
            show_error_dialog(
                self.parent,
                title="SD-Karte entfernt",
                message="Die SD-Karte wurde während der Auswahl entfernt.\n\nDer Dialog wird geschlossen.",
                details=["Bitte stecken Sie die SD-Karte wieder ein und versuchen Sie es erneut."]
            )
        except Exception as e:
            print(f"Fehler beim Anzeigen des Error-Dialogs: {e}")

        # Schließe den Dialog
        self.selected_files = None
        try:
            self.dialog.destroy()
        except:
            pass

