import os
import threading
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from src.utils.media_datetime import format_photo_table_datetime

_THUMB_BATCH_SIZE = 30


class PhotoPreview:
    """Komponente für die Foto-Vorschau mit großer Ansicht, Thumbnail-Galerie und Informationen"""

    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent)

        # Foto-Daten
        self.photo_paths = []
        self.current_photo_index = 0
        self.photo_images = {}  # Cache: index -> ImageTk für große Vorschau
        # Cache: (path, size_px) -> ImageTk.PhotoImage
        self.thumbnail_images = {}
        # Vom Import-Worker vorberechnete Thumbnails (Pfad -> PIL.Image)
        self._pil_thumbnail_cache = {}
        self._photo_metadata_cache = {}
        self._thumb_widgets = {}
        self._thumb_build_job = None
        self._metadata_build_job = None
        self._large_preview_generation = 0
        self._totals_dirty = True

        # NEU: Mehrfachauswahl
        self.selected_photos = set()  # Set von ausgewählten Indizes
        self.explicitly_selected = False  # Flag: Wurde explizit markiert (Shift/Ctrl)?
        self.last_clicked_index = None  # Für Shift+Klick Bereichsauswahl
        self.shift_selection_start = None  # Startpunkt der Shift+Pfeiltasten-Selection
        self.shift_direction = None  # Direction: 'left', 'right', or None

        # Widgets
        self.large_preview_canvas = None
        self.thumbnail_canvas = None
        self.thumbnail_scrollbar = None
        self.thumbnail_inner_frame = None
        self.thumbnail_canvas_window = None
        self.info_labels = {}
        self.delete_button = None
        self.clear_selection_button = None
        self.qr_scan_button = None

        # Drag-Scrolling-Variablen
        self.drag_start_x = 0
        self.drag_start_scroll = 0
        self.is_dragging = False

        # Navigation Pfeile
        self.left_arrow_id = None
        self.right_arrow_id = None
        self.show_arrows = False

        # Tooltip für Dateinamen
        self.filename_tooltip = None  # Für Tooltip-Verwaltung

        # Größen
        self.large_preview_width = 568
        self.large_preview_height = 320
        self.thumbnail_size = 60

        self.create_widgets()

    def create_widgets(self):
        """Erstellt alle Widgets für die Foto-Vorschau"""

        # --- Große Vorschau ---
        preview_frame = tk.Frame(self.frame)
        preview_frame.pack(fill="x", pady=(0, 0))

        # Canvas für große Vorschau
        self.large_preview_canvas = tk.Canvas(
            preview_frame,
            width=self.large_preview_width,
            height=self.large_preview_height,
            bg="#2c2c2c",
            highlightthickness=1,
            highlightbackground="#555555"
        )
        self.large_preview_canvas.pack()

        # Platzhalter-Text
        self.placeholder_text = self.large_preview_canvas.create_text(
            self.large_preview_width // 2,
            self.large_preview_height // 2,
            text="Keine Fotos",
            fill="white",
            font=("Arial", 12)
        )

        # Vollbild-Button (unten links)
        self.fullscreen_button_id = None
        self.fullscreen_button_bg = None
        self.fullscreen_button_text = None

        # Event-Bindings für Navigation-Pfeile und Vollbild
        self.large_preview_canvas.bind("<Enter>", self._on_preview_enter)
        self.large_preview_canvas.bind("<Leave>", self._on_preview_leave)
        self.large_preview_canvas.bind("<Button-1>", self._on_preview_click)

        # Tastatur-Navigation (Pfeiltasten)
        self.frame.bind("<Left>", self._on_key_left)
        self.frame.bind("<Right>", self._on_key_right)
        # NEU: Erweiterte Tastatur-Shortcuts für Mehrfachauswahl
        self.frame.bind("<Shift-Left>", self._on_key_shift_left)
        self.frame.bind("<Shift-Right>", self._on_key_shift_right)
        self.frame.bind("<Control-a>", self._on_key_select_all)
        self.frame.bind("<Delete>", self._on_key_delete)
        # Focus setzen damit Tastatur-Events funktionieren
        self.frame.bind("<FocusIn>", lambda e: None)
        self.large_preview_canvas.bind("<Button-1>", self._on_canvas_click_focus, add="+")

        # Vollbild-Fenster
        self.fullscreen_window = None
        self.fullscreen_canvas = None
        self.fullscreen_image_id = None
        self.fullscreen_info_text_id = None

        # --- Thumbnail-Galerie ---
        thumbnail_frame = tk.Frame(self.frame)
        thumbnail_frame.pack(fill="x", pady=(0, 5))

        # Scrollbarer Canvas für Thumbnails - Höhe exakt wie aktives Thumbnail (78px)
        canvas_height = int(self.thumbnail_size)
        self.thumbnail_canvas = tk.Canvas(
            thumbnail_frame,
            height=canvas_height,
            bg="#f0f0f0",
            highlightthickness=0
        )
        self.thumbnail_canvas.pack(fill="x", expand=True)

        # Sichtbare Scrollbar für Thumbnails
        self.thumbnail_scrollbar = ttk.Scrollbar(
            thumbnail_frame,
            orient="horizontal",
            command=self.thumbnail_canvas.xview
        )
        self.thumbnail_scrollbar.pack(fill="x", pady=(0, 0))
        self.thumbnail_canvas.configure(xscrollcommand=self.thumbnail_scrollbar.set)

        # Frame innerhalb des Canvas für die Thumbnails
        self.thumbnail_inner_frame = tk.Frame(self.thumbnail_canvas, bg="#f0f0f0")
        self.thumbnail_canvas_window = self.thumbnail_canvas.create_window((0, 0), window=self.thumbnail_inner_frame, anchor="nw")

        # Maus-Drag-Scrolling aktivieren (wie Smartphone Touch) - zusätzlich zur Scrollbar
        self.thumbnail_canvas.bind("<ButtonPress-1>", self._on_thumbnail_drag_start)
        self.thumbnail_canvas.bind("<B1-Motion>", self._on_thumbnail_drag_motion)
        self.thumbnail_canvas.bind("<ButtonRelease-1>", self._on_thumbnail_drag_end)

        # Mausrad-Scrolling
        self.thumbnail_canvas.bind("<MouseWheel>", self._on_thumbnail_mousewheel)

        # Drag-Variablen

        # --- Foto-Informationen ---
        info_frame = tk.Frame(self.frame, relief="groove", borderwidth=1, padx=5, pady=5)
        info_frame.pack(fill="x", pady=(0, 10))

        # Zwei Spalten: Links = Aktuelles Foto, Rechts = Gesamt-Statistik
        left_info_frame = tk.Frame(info_frame)
        left_info_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        right_info_frame = tk.Frame(info_frame)
        right_info_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        # WICHTIG: Beide Spalten exakt 50%, uniform für feste Breite (wie Video Preview)
        info_frame.grid_columnconfigure(0, weight=1, uniform="info_cols")
        info_frame.grid_columnconfigure(1, weight=1, uniform="info_cols")

        # === LINKE SPALTE: Aktuelles Foto ===
        single_info_title = tk.Label(left_info_frame, text="Aktuelles Foto:", font=("Arial", 9, "bold"))
        single_info_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 0))

        # Info-Labels erstellen
        info_fields = [
            ("Dateiname:", "filename"),
            ("Auflösung:", "resolution"),
            ("Größe:", "size"),
            ("Datum:", "date")
        ]

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
        stats_title.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 0))

        total_count_label = tk.Label(right_info_frame, text="Anzahl Fotos:", font=("Arial", 8), anchor="w")
        total_count_label.grid(row=1, column=0, sticky="w", padx=(0, 5))
        self.info_labels["total_count"] = tk.Label(right_info_frame, text="0", font=("Arial", 8), anchor="w")
        self.info_labels["total_count"].grid(row=1, column=1, sticky="w")

        total_size_label = tk.Label(right_info_frame, text="Gesamt-Größe:", font=("Arial", 8), anchor="w")
        total_size_label.grid(row=2, column=0, sticky="w", padx=(0, 5))
        self.info_labels["total_size"] = tk.Label(right_info_frame, text="0 MB", font=("Arial", 8), anchor="w")
        self.info_labels["total_size"].grid(row=2, column=1, sticky="w")

        # Löschen-Button, "Auswahl aufheben" und QR-Code-Scan Button
        button_frame = tk.Frame(right_info_frame)
        button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(2, weight=0)  # QR-Button hat feste Breite
        button_frame.columnconfigure(3, weight=0)  # NEUE Spalte: WM-Button

        self.delete_button = tk.Button(
            button_frame,
            text="Entfernen",
            command=self._delete_current_photo,
            bg="#f44336",
            fg="white",
            font=("Arial", 9, "bold"),
            state="disabled"
        )
        self.delete_button.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        # "Auswahl aufheben" Button
        self.clear_selection_button = tk.Button(
            button_frame,
            text="Auswahl aufheben",
            command=self._clear_all_selections,
            bg="#999999",
            fg="white",
            font=("Arial", 9),
            state="disabled"
        )
        self.clear_selection_button.grid(row=0, column=1, sticky="ew", padx=(5, 5))

        # QR-Code-Scan Button
        self.qr_scan_button = tk.Button(
            button_frame,
            text="🔍 QR",
            command=self._scan_current_photo_qr,
            bg="#2196F3",
            fg="white",
            font=("Arial", 9),
            width=6,
            state="disabled"
        )
        self.qr_scan_button.grid(row=0, column=2, sticky="ew", padx=(5, 0))

        # --- NEU: Wasserzeichen-Button ---
        self.wm_button_var = tk.BooleanVar(value=False)
        self.wm_button = tk.Button(
            button_frame,
            text="Preview ☐",
            command=self._on_wm_button_click,
            bg="#f0f0f0",
            fg="black",
            font=("Arial", 9),
            width=10,
            state="disabled"
        )
        # INITIAL VERSTECKT - wird von app.py gesteuert
        # self.wm_button.grid(row=0, column=3, sticky="ew", padx=(5, 0))
        # --- ENDE NEU ---

    def set_photos(self, photo_paths, pil_thumbnail_cache=None):
        """Setzt die anzuzeigenden Fotos. Optional: vorberechnete PIL-Thumbnails vom Import-Thread."""
        self._cancel_thumb_build_job()
        self.photo_paths = photo_paths
        self.current_photo_index = 0 if photo_paths else -1

        self.selected_photos.clear()
        self.explicitly_selected = False
        self.last_clicked_index = 0 if photo_paths else None

        self.photo_images.clear()
        self.thumbnail_images.clear()
        self._pil_thumbnail_cache = dict(pil_thumbnail_cache) if pil_thumbnail_cache else {}
        self._prune_metadata_cache()
        if photo_paths and self.current_photo_index >= 0:
            current_path = photo_paths[self.current_photo_index]
            if current_path not in self._photo_metadata_cache:
                self._photo_metadata_cache[current_path] = self._load_photo_metadata(current_path)
        self._schedule_metadata_prefetch(photo_paths)
        self._totals_dirty = True

        self._rebuild_thumbnails_full()
        self._schedule_large_preview_update()
        self._update_current_photo_info()
        self._update_totals_info()
        self._update_delete_button()

    def _cancel_thumb_build_job(self):
        if self._thumb_build_job is not None:
            try:
                self.frame.after_cancel(self._thumb_build_job)
            except tk.TclError:
                pass
            self._thumb_build_job = None

    def _cancel_metadata_build_job(self):
        if self._metadata_build_job is not None:
            try:
                self.frame.after_cancel(self._metadata_build_job)
            except tk.TclError:
                pass
            self._metadata_build_job = None

    def _active_thumb_size(self):
        return int(self.thumbnail_size * 1.3)

    def _thumbnail_cache_key(self, photo_path, is_active):
        size = self._active_thumb_size() if is_active else self.thumbnail_size
        return (photo_path, size)

    def _prune_metadata_cache(self):
        active = set(self.photo_paths)
        stale = [path for path in self._photo_metadata_cache if path not in active]
        for path in stale:
            del self._photo_metadata_cache[path]

    def _load_photo_metadata(self, photo_path):
        meta = {
            "filename": os.path.basename(photo_path),
            "resolution": "-",
            "size": "-",
            "date": "-",
            "time": "-",
        }
        try:
            with Image.open(photo_path) as img:
                width, height = img.size
            meta["resolution"] = f"{width} × {height} px"
            size_bytes = os.path.getsize(photo_path)
            meta["size"] = f"{size_bytes / (1024 * 1024):.2f} MB"
            imp_ep = None
            if self.app and hasattr(self.app, "drag_drop"):
                imp_ep = self.app.drag_drop.get_source_import_epoch(photo_path)
            date_str, time_str = format_photo_table_datetime(photo_path, imp_ep)
            meta["date"] = date_str
            meta["time"] = time_str
        except Exception as e:
            print(f"Fehler beim Laden der Foto-Metadaten für {photo_path}: {e}")
        return meta

    def _schedule_metadata_prefetch(self, paths):
        self._cancel_metadata_build_job()
        self._metadata_prefetch_paths = list(paths or [])
        self._metadata_prefetch_index = 0
        if self._metadata_prefetch_paths:
            self._build_metadata_batch()

    def _build_metadata_batch(self):
        paths = getattr(self, "_metadata_prefetch_paths", [])
        start = self._metadata_prefetch_index
        end = min(start + 15, len(paths))

        for path in paths[start:end]:
            if path not in self._photo_metadata_cache:
                self._photo_metadata_cache[path] = self._load_photo_metadata(path)

        if end < len(paths):
            self._metadata_prefetch_index = end
            self._metadata_build_job = self.frame.after(1, self._build_metadata_batch)
            return

        self._metadata_build_job = None
        self._totals_dirty = True

    def _selection_style_for_index(self, idx):
        is_current = idx == self.current_photo_index
        if self.explicitly_selected:
            is_selected = idx in self.selected_photos
            multiple_selected = len(self.selected_photos) > 1
        else:
            is_selected = is_current
            multiple_selected = False

        if is_selected and (multiple_selected or not is_current):
            return 3, "#FF9800"
        return 2, "#999999"

    def _apply_thumbnail_frame_style(self, frame, idx):
        thickness, color = self._selection_style_for_index(idx)
        frame.config(highlightthickness=thickness, highlightbackground=color)

    def _get_thumbnail_photoimage(self, photo_path, is_active):
        cache_key = self._thumbnail_cache_key(photo_path, is_active)
        cached = self.thumbnail_images.get(cache_key)
        if cached is not None:
            return cached

        try:
            size = self._active_thumb_size() if is_active else self.thumbnail_size
            pil_source = self._pil_thumbnail_cache.get(photo_path)
            if pil_source is not None:
                img = pil_source.copy()
                if img.width > size or img.height > size:
                    img.thumbnail((size, size), Image.LANCZOS)
            else:
                with Image.open(photo_path) as opened:
                    img = opened.copy()
                img.thumbnail((size, size), Image.LANCZOS)

            thumbnail = ImageTk.PhotoImage(img)
            self.thumbnail_images[cache_key] = thumbnail
            return thumbnail
        except Exception as e:
            print(f"Fehler beim Erstellen des Thumbnails für {photo_path}: {e}")
            return None

    def _create_thumbnail_widget(self, idx):
        if idx < 0 or idx >= len(self.photo_paths):
            return

        photo_path = self.photo_paths[idx]
        is_current = idx == self.current_photo_index
        thumbnail = self._get_thumbnail_photoimage(photo_path, is_active=is_current)
        if not thumbnail:
            return

        thickness, color = self._selection_style_for_index(idx)
        thumb_frame = tk.Frame(
            self.thumbnail_inner_frame,
            bg="white",
            highlightthickness=thickness,
            highlightbackground=color,
        )
        thumb_frame.pack(side="left", padx=5, pady=5)

        thumb_label = tk.Label(thumb_frame, image=thumbnail, bg="white")
        thumb_label.image = thumbnail
        thumb_label.pack()
        thumb_label.bind(
            "<ButtonRelease-1>",
            lambda e, i=idx: self._on_thumbnail_click_release(e, i),
        )
        thumb_frame.bind(
            "<ButtonRelease-1>",
            lambda e, i=idx: self._on_thumbnail_click_release(e, i),
        )
        self._thumb_widgets[idx] = {"frame": thumb_frame, "label": thumb_label}

    def _rebuild_thumbnails_full(self):
        """Baut die Thumbnail-Leiste komplett neu (Import, Löschen, Strg+A)."""
        self._cancel_thumb_build_job()
        for widget in self.thumbnail_inner_frame.winfo_children():
            widget.destroy()
        self._thumb_widgets.clear()

        if not self.photo_paths:
            self.thumbnail_canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        self._build_thumbnail_batch(0)

    def _build_thumbnail_batch(self, start_index):
        end_index = min(start_index + _THUMB_BATCH_SIZE, len(self.photo_paths))
        for idx in range(start_index, end_index):
            self._create_thumbnail_widget(idx)

        if end_index < len(self.photo_paths):
            self._thumb_build_job = self.frame.after(
                1, lambda n=end_index: self._build_thumbnail_batch(n)
            )
            return

        self._thumb_build_job = None
        self.thumbnail_inner_frame.update_idletasks()
        bbox = self.thumbnail_canvas.bbox("all")
        if bbox:
            self.thumbnail_canvas.configure(scrollregion=bbox)
        self._scroll_to_active_thumbnail()

    def _update_thumbnails(self):
        """Kompatibilitäts-Wrapper: vollständiger Neuaufbau."""
        self._rebuild_thumbnails_full()

    def _refresh_thumbnail_at_index(self, idx):
        widgets = self._thumb_widgets.get(idx)
        if not widgets or idx < 0 or idx >= len(self.photo_paths):
            return False

        photo_path = self.photo_paths[idx]
        is_active = idx == self.current_photo_index
        thumbnail = self._get_thumbnail_photoimage(photo_path, is_active=is_active)
        if not thumbnail:
            return False

        widgets["label"].config(image=thumbnail)
        widgets["label"].image = thumbnail
        self._apply_thumbnail_frame_style(widgets["frame"], idx)
        return True

    def _update_thumbnail_selection_styles(self):
        for idx in self._thumb_widgets:
            widgets = self._thumb_widgets.get(idx)
            if widgets:
                self._apply_thumbnail_frame_style(widgets["frame"], idx)

    def _can_incremental_navigate(self, old_index, new_index):
        return (
            old_index is not None
            and old_index >= 0
            and new_index >= 0
            and old_index in self._thumb_widgets
            and new_index in self._thumb_widgets
        )

    def _navigate_to_photo(self, new_index, *, update_large=True):
        if new_index < 0 or new_index >= len(self.photo_paths):
            return
        if new_index == self.current_photo_index:
            return

        old_index = self.current_photo_index
        self.current_photo_index = new_index

        if self._can_incremental_navigate(old_index, new_index):
            self._refresh_thumbnail_at_index(old_index)
            self._refresh_thumbnail_at_index(new_index)
            self._scroll_to_active_thumbnail()
        else:
            self._rebuild_thumbnails_full()

        if update_large:
            self._schedule_large_preview_update()
        self._update_current_photo_info()
        self.update_wm_button_state()

    def _after_selection_change(self, *, update_large=False):
        self._update_thumbnail_selection_styles()
        if update_large:
            self._schedule_large_preview_update()
            self._update_current_photo_info()
        self._update_delete_button()
        self.update_wm_button_state()

    def _on_thumbnail_drag_start(self, event):
        """Startet das Drag-Scrolling"""
        self.drag_start_x = event.x
        self.is_dragging = False
        # Hole aktuelle Scroll-Position
        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if scroll_region:
            current_view = self.thumbnail_canvas.xview()
            self.drag_start_scroll = current_view[0]

    def _on_thumbnail_drag_motion(self, event):
        """Führt das Drag-Scrolling durch"""
        # Wenn sich die Maus mehr als 5 Pixel bewegt hat, ist es ein Drag, kein Klick
        if abs(event.x - self.drag_start_x) > 5:
            self.is_dragging = True

        if not self.is_dragging:
            return

        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if not scroll_region or scroll_region == "0 0 0 0":
            return

        # Berechne Drag-Distanz
        delta_x = self.drag_start_x - event.x

        # Konvertiere zu Scroll-Units
        canvas_width = self.thumbnail_canvas.winfo_width()
        scroll_parts = scroll_region.split()
        total_width = float(scroll_parts[2]) if len(scroll_parts) > 2 else canvas_width

        if total_width > canvas_width:
            # Berechne neue Scroll-Position
            scroll_delta = delta_x / total_width
            new_scroll = self.drag_start_scroll + scroll_delta

            # Limitiere auf 0.0 - 1.0 Bereich
            new_scroll = max(0.0, min(1.0, new_scroll))

            # Setze Scroll-Position
            self.thumbnail_canvas.xview_moveto(new_scroll)

    def _on_thumbnail_drag_end(self, event):
        """Beendet das Drag-Scrolling"""
        # Reset drag flag nach kurzer Zeit, damit Klicks funktionieren
        self.frame.after(50, lambda: setattr(self, 'is_dragging', False))

    def _on_thumbnail_mousewheel(self, event):
        """Scrolling mit Mausrad"""
        scroll_region = self.thumbnail_canvas.cget("scrollregion")
        if scroll_region and scroll_region != "0 0 0 0":
            # Windows/Linux unterschiedliche Werte
            delta = -1 if event.delta > 0 else 1
            self.thumbnail_canvas.xview_scroll(delta, "units")

    def _scroll_to_active_thumbnail(self):
        """Scrollt die Thumbnail-Leiste so, dass das aktive Thumbnail sichtbar ist"""
        if not self.photo_paths or self.current_photo_index < 0:
            return

        # Warte bis die Widgets gerendert sind
        self.thumbnail_inner_frame.update_idletasks()

        widgets = self._thumb_widgets.get(self.current_photo_index)
        if not widgets:
            children = self.thumbnail_inner_frame.winfo_children()
            if self.current_photo_index >= len(children):
                return
            active_frame = children[self.current_photo_index]
        else:
            active_frame = widgets["frame"]

        # Hole die Position und Größe des aktiven Thumbnails relativ zum inner_frame
        thumb_x = active_frame.winfo_x()
        thumb_width = active_frame.winfo_width()
        thumb_right = thumb_x + thumb_width

        # Hole die Canvas-Größe und Scroll-Position
        canvas_width = self.thumbnail_canvas.winfo_width()
        scroll_region = self.thumbnail_canvas.cget("scrollregion")

        if not scroll_region or scroll_region == "0 0 0 0":
            return

        # Parse scroll region: "x1 y1 x2 y2"
        parts = scroll_region.split()
        total_width = float(parts[2]) if len(parts) > 2 else canvas_width

        if total_width <= canvas_width:
            # Alles passt in den Canvas, kein Scrollen nötig
            return

        # Aktuelle Scroll-Position (0.0 bis 1.0)
        current_view = self.thumbnail_canvas.xview()
        view_start = current_view[0]  # Linker Rand (0.0 bis 1.0)
        view_end = current_view[1]    # Rechter Rand (0.0 bis 1.0)

        # Berechne die absoluten Pixel-Positionen des sichtbaren Bereichs
        visible_start = view_start * total_width
        visible_end = view_end * total_width

        # Prüfe ob das aktive Thumbnail außerhalb des sichtbaren Bereichs ist
        margin = 60  # Sicherheitsabstand in Pixeln

        if thumb_x < visible_start + margin:
            # Thumbnail ist links außerhalb - scrolle nach links
            new_view_start = max(0.0, (thumb_x - margin) / total_width)
            self.thumbnail_canvas.xview_moveto(new_view_start)
        elif thumb_right > visible_end - margin:
            # Thumbnail ist rechts außerhalb - scrolle nach rechts
            # Berechne neue Position so, dass das Thumbnail am rechten Rand sichtbar ist
            new_view_start = min(1.0, (thumb_right + margin - canvas_width) / total_width)
            self.thumbnail_canvas.xview_moveto(new_view_start)

    def _schedule_large_preview_update(self):
        """Lädt die große Vorschau asynchron; zeigt zuerst ein schnelles Thumbnail."""
        self._large_preview_generation += 1
        generation = self._large_preview_generation

        self.large_preview_canvas.delete("all")
        if not self.photo_paths or self.current_photo_index < 0:
            self.large_preview_canvas.create_text(
                self.large_preview_width // 2,
                self.large_preview_height // 2,
                text="Keine Fotos",
                fill="white",
                font=("Arial", 12),
            )
            return

        photo_path = self.photo_paths[self.current_photo_index]
        self._show_large_preview_quick(photo_path)
        self._draw_navigation_arrows()

        def worker():
            try:
                with Image.open(photo_path) as opened:
                    img = opened.copy()
                img.thumbnail(
                    (self.large_preview_width, self.large_preview_height),
                    Image.LANCZOS,
                )
                payload = img.copy()
            except Exception as e:
                print(f"Fehler beim Laden des Fotos {photo_path}: {e}")
                payload = None

            self.frame.after(
                0,
                lambda g=generation, p=photo_path, data=payload: self._apply_large_preview_result(
                    g, p, data
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _show_large_preview_quick(self, photo_path):
        quick = self._get_thumbnail_photoimage(photo_path, is_active=True)
        if quick is None:
            return
        x = self.large_preview_width // 2
        y = self.large_preview_height // 2
        self.large_preview_canvas.create_image(x, y, image=quick, anchor="center", tags="preview_image")

    def _apply_large_preview_result(self, generation, photo_path, pil_image):
        if generation != self._large_preview_generation:
            return
        if (
            not self.photo_paths
            or self.current_photo_index < 0
            or self.photo_paths[self.current_photo_index] != photo_path
        ):
            return

        self.large_preview_canvas.delete("all")
        if pil_image is None:
            self.large_preview_canvas.create_text(
                self.large_preview_width // 2,
                self.large_preview_height // 2,
                text="Fehler beim Laden",
                fill="red",
                font=("Arial", 12),
            )
            return

        photo_image = ImageTk.PhotoImage(pil_image)
        self.photo_images[self.current_photo_index] = photo_image
        x = self.large_preview_width // 2
        y = self.large_preview_height // 2
        self.large_preview_canvas.create_image(x, y, image=photo_image, anchor="center")
        self._draw_navigation_arrows()

    def _update_large_preview(self):
        """Synchroner Wrapper für bestehende Aufrufer."""
        self._schedule_large_preview_update()

    def _draw_navigation_arrows(self):
        """Zeichnet die Navigation-Pfeile (initial versteckt)"""
        if len(self.photo_paths) <= 1:
            return

        arrow_color = "#ffffff"
        arrow_bg = "#000000"

        # Linker Pfeil (zeigt nach links)
        if self.current_photo_index > 0:
            left_x = 20
            left_y = self.large_preview_height // 2

            # Hintergrund
            self.left_arrow_bg = self.large_preview_canvas.create_rectangle(
                left_x - 15, left_y - 15, left_x + 15, left_y + 15,
                fill=arrow_bg, outline="", stipple="gray50", tags="arrow", state="hidden"
            )

            # Pfeil nach links: <
            self.left_arrow_id = self.large_preview_canvas.create_polygon(
                left_x - 5, left_y,
                left_x + 5, left_y - 10,
                left_x + 5, left_y + 10,
                fill=arrow_color, outline="", tags="arrow", state="hidden"
            )

        # Rechter Pfeil (zeigt nach rechts)
        if self.current_photo_index < len(self.photo_paths) - 1:
            right_x = self.large_preview_width - 20
            right_y = self.large_preview_height // 2

            # Hintergrund
            self.right_arrow_bg = self.large_preview_canvas.create_rectangle(
                right_x - 15, right_y - 15, right_x + 15, right_y + 15,
                fill=arrow_bg, outline="", stipple="gray50", tags="arrow", state="hidden"
            )

            # Pfeil nach rechts: >
            self.right_arrow_id = self.large_preview_canvas.create_polygon(
                right_x + 5, right_y,
                right_x - 5, right_y - 10,
                right_x - 5, right_y + 10,
                fill=arrow_color, outline="", tags="arrow", state="hidden"
            )

        # Vollbild-Button (unten rechts)
        if self.photo_paths:
            button_x = self.large_preview_width - 35
            button_y = self.large_preview_height - 15

            # Hintergrund-Rechteck
            self.fullscreen_button_bg = self.large_preview_canvas.create_rectangle(
                button_x - 35, button_y - 12, button_x + 35, button_y + 12,
                fill=arrow_bg, outline="", stipple="gray50", tags="fullscreen_btn", state="hidden"
            )

            # Text-Icon
            self.fullscreen_button_text = self.large_preview_canvas.create_text(
                button_x, button_y,
                text="Vollbild ⛶ ",
                fill=arrow_color,
                font=("Arial", 9, "bold"),
                tags="fullscreen_btn",
                state="hidden"
            )

    def _on_preview_enter(self, event):
        """Zeigt Pfeile und Vollbild-Button an wenn Maus über Preview schwebt"""
        if len(self.photo_paths) > 0:
            self.large_preview_canvas.itemconfig("arrow", state="normal")
            self.large_preview_canvas.itemconfig("fullscreen_btn", state="normal")
            self.show_arrows = True

    def _on_preview_leave(self, event):
        """Versteckt Pfeile und Vollbild-Button wenn Maus Preview verlässt"""
        self.large_preview_canvas.itemconfig("arrow", state="hidden")
        self.large_preview_canvas.itemconfig("fullscreen_btn", state="hidden")
        self.show_arrows = False

    def _on_preview_click(self, event):
        """Behandelt Klicks auf die Preview (Navigation oder Vollbild)"""
        # Prüfe ob auf Vollbild-Button geklickt wurde (unten rechts)
        if event.y > self.large_preview_height - 30 and event.x > self.large_preview_width - 70:
            self._open_fullscreen()
            return

        if len(self.photo_paths) <= 1:
            return

        # Prüfe ob auf linken oder rechten Bereich geklickt wurde
        if event.x < self.large_preview_width // 3 and self.current_photo_index > 0:
            # Links geklickt - vorheriges Foto
            self._show_previous_photo()
        elif event.x > 2 * self.large_preview_width // 3 and self.current_photo_index < len(self.photo_paths) - 1:
            # Rechts geklickt - nächstes Foto
            self._show_next_photo()

    def _on_thumbnail_click(self, index, event=None):
        """
        Behandelt Klick auf ein Thumbnail mit Mehrfachauswahl-Unterstützung.

        - Normaler Klick: Deselektiert alle, wählt nur dieses Foto aus UND macht es aktiv
        - Strg+Klick: Fügt Foto zur Auswahl hinzu/entfernt es (OHNE es aktiv zu machen)
        - Shift+Klick: Wählt Bereich von letztem Klick bis hierhin aus (OHNE aktiv zu ändern)
        """
        if event:
            # Prüfe Modifier-Keys
            ctrl_pressed = (event.state & 0x0004) != 0  # Control-Key
            shift_pressed = (event.state & 0x0001) != 0  # Shift-Key

            if shift_pressed and self.last_clicked_index is not None:
                # Shift+Klick: Bereichsauswahl
                start = min(self.last_clicked_index, index)
                end = max(self.last_clicked_index, index)

                # Füge alle Fotos im Bereich zur Auswahl hinzu
                for i in range(start, end + 1):
                    self.selected_photos.add(i)

                self.explicitly_selected = True  # Explizite Markierung
                # NICHT aktiv machen - aktuelles Foto bleibt unverändert

            elif ctrl_pressed:
                # Strg+Klick: Toggle-Auswahl
                if index in self.selected_photos:
                    self.selected_photos.remove(index)
                    # Wenn keine Auswahl mehr übrig ist, zurück zu impliziter Auswahl
                    if not self.selected_photos:
                        self.explicitly_selected = False
                else:
                    self.selected_photos.add(index)
                    self.explicitly_selected = True  # Explizite Markierung

                # NICHT aktiv machen - aktuelles Foto bleibt unverändert
                self.last_clicked_index = index
            else:
                self.last_clicked_index = index
                self._navigate_to_photo(index, update_large=True)
                self._update_delete_button()
                return
        else:
            self.last_clicked_index = index
            self._navigate_to_photo(index, update_large=True)
            self._update_delete_button()
            return

        if shift_pressed or ctrl_pressed:
            self._after_selection_change(update_large=False)
            return

    def _on_thumbnail_click_release(self, event, index):
        """Behandelt ButtonRelease auf ein Thumbnail - nur wenn es kein Drag war"""
        # Nur als Klick behandeln wenn nicht gedragged wurde
        if not self.is_dragging:
            self._on_thumbnail_click(index, event)

    def _show_previous_photo(self):
        """Zeigt das vorherige Foto"""
        if self.current_photo_index > 0:
            self._navigate_to_photo(self.current_photo_index - 1, update_large=True)

    def _show_next_photo(self):
        """Zeigt das nächste Foto"""
        if self.current_photo_index < len(self.photo_paths) - 1:
            self._navigate_to_photo(self.current_photo_index + 1, update_large=True)

    def _on_canvas_click_focus(self, event):
        """Setzt Focus auf Frame bei Klick auf Canvas für Tastatur-Events"""
        self.frame.focus_set()

    def _on_key_left(self, event):
        """Behandelt linke Pfeiltaste - vorheriges Foto"""
        # Reset Shift-Auswahl
        self.shift_selection_start = None
        self.shift_direction = None

        if self.photo_paths and self.current_photo_index > 0:
            self._show_previous_photo()

    def _on_key_right(self, event):
        """Behandelt rechte Pfeiltaste - nächstes Foto"""
        # Reset Shift-Auswahl
        self.shift_selection_start = None
        self.shift_direction = None

        if self.photo_paths and self.current_photo_index < len(self.photo_paths) - 1:
            self._show_next_photo()

    def _on_key_shift_left(self, event):
        """Behandelt Shift+Links - Akkordeon-Markierung nach links"""
        if not self.photo_paths or self.current_photo_index <= 0:
            return

        # Fall 1: Erste Shift-Taste - Starte Session
        if self.shift_selection_start is None:
            self.shift_selection_start = self.current_photo_index
            self.shift_direction = 'left'
            self.explicitly_selected = True

            self.selected_photos.clear()
            self.selected_photos.add(self.current_photo_index)
            self._navigate_to_photo(self.current_photo_index - 1, update_large=True)
            self.selected_photos.add(self.current_photo_index)
            self.last_clicked_index = self.current_photo_index
            self._update_thumbnail_selection_styles()
            self._update_delete_button()
            return

        # Fall 2: Wir waren nach rechts, jetzt nach links (Zusammenziehen)
        if self.shift_direction == 'right':
            self.selected_photos.discard(self.current_photo_index)
            self._navigate_to_photo(self.current_photo_index - 1, update_large=True)

            if len(self.selected_photos) == 1 and self.current_photo_index in self.selected_photos:
                self.selected_photos.clear()
                self.explicitly_selected = False
                self.shift_selection_start = None
                self.shift_direction = None

            self._update_thumbnail_selection_styles()
            self._update_delete_button()
            return

        # Fall 3: Weitergehen nach links (gleiche Richtung - Erweitern)
        self._navigate_to_photo(self.current_photo_index - 1, update_large=True)
        self.selected_photos.add(self.current_photo_index)
        self.last_clicked_index = self.current_photo_index
        self._update_thumbnail_selection_styles()
        self._update_delete_button()

    def _on_key_shift_right(self, event):
        """Behandelt Shift+Rechts - Akkordeon-Markierung nach rechts"""
        if not self.photo_paths or self.current_photo_index >= len(self.photo_paths) - 1:
            return

        # Fall 1: Erste Shift-Taste - Starte Session
        if self.shift_selection_start is None:
            self.shift_selection_start = self.current_photo_index
            self.shift_direction = 'right'
            self.explicitly_selected = True

            self.selected_photos.clear()
            self.selected_photos.add(self.current_photo_index)
            self._navigate_to_photo(self.current_photo_index + 1, update_large=True)
            self.selected_photos.add(self.current_photo_index)
            self.last_clicked_index = self.current_photo_index
            self._update_thumbnail_selection_styles()
            self._update_delete_button()
            return

        # Fall 2: Wir waren nach links, jetzt nach rechts (Zusammenziehen)
        if self.shift_direction == 'left':
            self.selected_photos.discard(self.current_photo_index)
            self._navigate_to_photo(self.current_photo_index + 1, update_large=True)

            if len(self.selected_photos) == 1 and self.current_photo_index in self.selected_photos:
                self.selected_photos.clear()
                self.explicitly_selected = False
                self.shift_selection_start = None
                self.shift_direction = None

            self._update_thumbnail_selection_styles()
            self._update_delete_button()
            return

        # Fall 3: Weitergehen nach rechts (gleiche Richtung - Erweitern)
        self._navigate_to_photo(self.current_photo_index + 1, update_large=True)
        self.selected_photos.add(self.current_photo_index)
        self.last_clicked_index = self.current_photo_index
        self._update_thumbnail_selection_styles()
        self._update_delete_button()

    def _on_key_select_all(self, event):
        """Behandelt Strg+A - Alle Fotos auswählen"""
        if not self.photo_paths:
            return

        # Wähle alle Fotos aus
        self.selected_photos = set(range(len(self.photo_paths)))
        self.explicitly_selected = True  # Explizite Markierung
        self.last_clicked_index = self.current_photo_index

        self._update_thumbnail_selection_styles()
        self._update_delete_button()

    def _on_key_delete(self, event):
        """Behandelt Delete-Taste - Ausgewählte Fotos löschen"""
        if self.photo_paths and self.selected_photos:
            self._delete_current_photo()

    def _open_fullscreen(self):
        """Öffnet das aktuelle Foto im Vollbild-Modus"""
        if not self.photo_paths or self.current_photo_index < 0:
            return

        # Erstelle Vollbild-Fenster
        self.fullscreen_window = tk.Toplevel(self.frame)
        self.fullscreen_window.title("Vollbild")
        self.fullscreen_window.attributes('-fullscreen', True)
        self.fullscreen_window.configure(bg='black')

        # Canvas für Vollbild-Foto (als Instanzvariable speichern)
        self.fullscreen_canvas = tk.Canvas(
            self.fullscreen_window,
            bg='black',
            highlightthickness=0
        )
        self.fullscreen_canvas.pack(fill="both", expand=True)

        # Bildschirmgröße ermitteln
        screen_width = self.fullscreen_window.winfo_screenwidth()
        screen_height = self.fullscreen_window.winfo_screenheight()

        # Erstelle Platzhalter für Bild und Texte (werden später aktualisiert)
        x = screen_width // 2
        y = screen_height // 2
        self.fullscreen_image_id = self.fullscreen_canvas.create_image(x, y, anchor="center")

        # Info-Text (unten links) - Platzhalter
        self.fullscreen_info_text_id = self.fullscreen_canvas.create_text(
            20, screen_height - 20,
            text="",
            fill="white",
            font=("Arial", 12),
            anchor="sw"
        )

        # Hinweis-Text (unten rechts) - bleibt statisch
        help_text = "ESC: Beenden | ← →: Navigation"
        self.fullscreen_canvas.create_text(
            screen_width - 20, screen_height - 20,
            text=help_text,
            fill="white",
            font=("Arial", 11),
            anchor="se"
        )

        # Lade das erste Foto
        self._update_fullscreen_photo()

        # Event-Bindings für Vollbild
        self.fullscreen_window.bind("<Escape>", lambda e: self._close_fullscreen())
        self.fullscreen_window.bind("<Button-1>", lambda e: self._close_fullscreen())
        self.fullscreen_window.bind("<Left>", self._on_fullscreen_key_left)
        self.fullscreen_window.bind("<Right>", self._on_fullscreen_key_right)

        # Focus setzen
        self.fullscreen_window.focus_set()

    def _update_fullscreen_photo(self):
        """Aktualisiert das Foto im Vollbild-Modus ohne das Fenster zu schließen"""
        if not self.fullscreen_window or not self.fullscreen_canvas:
            return

        if not self.photo_paths or self.current_photo_index < 0:
            return

        photo_path = self.photo_paths[self.current_photo_index]
        try:
            img = Image.open(photo_path)

            # Bildschirmgröße
            screen_width = self.fullscreen_window.winfo_screenwidth()
            screen_height = self.fullscreen_window.winfo_screenheight()

            # Skaliere Bild auf Bildschirmgröße (Aspect Ratio beibehalten)
            img.thumbnail((screen_width, screen_height), Image.LANCZOS)
            photo_image = ImageTk.PhotoImage(img)

            # Aktualisiere das Bild im Canvas
            self.fullscreen_canvas.itemconfig(self.fullscreen_image_id, image=photo_image)

            # Referenz behalten (wichtig, sonst wird das Bild vom GC gelöscht)
            self.fullscreen_canvas.image = photo_image

            # Info-Text aktualisieren (unten links)
            filename = os.path.basename(photo_path)
            info_text = f"{self.current_photo_index + 1}/{len(self.photo_paths)} - {filename}"
            self.fullscreen_canvas.itemconfig(self.fullscreen_info_text_id, text=info_text)

        except Exception as e:
            print(f"Fehler beim Laden des Vollbild-Fotos: {e}")

    def _close_fullscreen(self):
        """Schließt den Vollbild-Modus"""
        if self.fullscreen_window:
            self.fullscreen_window.destroy()
            self.fullscreen_window = None
            self.fullscreen_canvas = None
            self.fullscreen_image_id = None
            self.fullscreen_info_text_id = None

    def _on_fullscreen_key_left(self, event):
        """Behandelt linke Pfeiltaste im Vollbild-Modus"""
        if self.current_photo_index > 0:
            self._navigate_to_photo(self.current_photo_index - 1, update_large=False)
            self._update_fullscreen_photo()

    def _on_fullscreen_key_right(self, event):
        """Behandelt rechte Pfeiltaste im Vollbild-Modus"""
        if self.current_photo_index < len(self.photo_paths) - 1:
            self._navigate_to_photo(self.current_photo_index + 1, update_large=False)
            self._update_fullscreen_photo()

    def _update_info(self):
        """Aktualisiert alle Foto-Informationen (aktuell + Gesamt)."""
        self._update_current_photo_info()
        self._update_totals_info()

    def _update_current_photo_info(self):
        """Aktualisiert nur die Infos des aktuellen Fotos (ohne Dateizugriff bei Navigation)."""
        if not self.photo_paths or self.current_photo_index < 0:
            for key in ["filename", "resolution", "size", "date"]:
                self.info_labels[key].config(text="-")
            return

        photo_path = self.photo_paths[self.current_photo_index]
        if photo_path not in self._photo_metadata_cache:
            self._photo_metadata_cache[photo_path] = self._load_photo_metadata(photo_path)

        meta = self._photo_metadata_cache.get(photo_path, {})
        truncated_filename = self._truncate_filename(
            meta.get("filename", os.path.basename(photo_path)),
            max_chars=30,
        )
        self.info_labels["filename"].config(text=truncated_filename)
        self.info_labels["resolution"].config(text=meta.get("resolution", "-"))
        self.info_labels["size"].config(text=meta.get("size", "-"))
        date_str = meta.get("date", "-")
        time_str = meta.get("time", "-")
        self.info_labels["date"].config(text=f"{date_str} - {time_str}")

    def _update_totals_info(self):
        """Aktualisiert Gesamt-Statistiken nur wenn sich die Foto-Liste geändert hat."""
        if not self.photo_paths:
            self.info_labels["total_count"].config(text="0")
            self.info_labels["total_size"].config(text="0 MB")
            self._totals_dirty = False
            return

        self.info_labels["total_count"].config(text=str(len(self.photo_paths)))
        if not self._totals_dirty:
            self.update_wm_button_state()
            return

        total_size = 0
        for path in self.photo_paths:
            meta = self._photo_metadata_cache.get(path)
            if meta and meta.get("size") != "-":
                try:
                    total_size += os.path.getsize(path)
                    continue
                except OSError:
                    pass
            try:
                total_size += os.path.getsize(path)
            except OSError:
                pass

        total_size_mb = total_size / (1024 * 1024)
        self.info_labels["total_size"].config(text=f"{total_size_mb:.2f} MB")
        self._totals_dirty = False
        self.update_wm_button_state()

    def _update_delete_button(self):
        """Aktualisiert den Status und Text des Löschen-Buttons, Clear-Selection-Buttons und QR-Scan-Buttons"""
        # Bestimme welche Fotos als markiert gelten
        if self.explicitly_selected:
            effective_selection = self.selected_photos
        else:
            # Implizite Auswahl - nur aktuelles Foto
            effective_selection = {self.current_photo_index} if self.photo_paths else set()

        if self.photo_paths and effective_selection:
            count = len(effective_selection)
            if count == 1:
                self.delete_button.config(text="Entfernen", state="normal")
            else:
                self.delete_button.config(text=f"{count} Entfernen", state="normal")
        else:
            self.delete_button.config(text="Entfernen", state="disabled")

        # Clear-Selection-Button nur anzeigen wenn explizite Markierung vorhanden
        if self.explicitly_selected and self.selected_photos:
            self.clear_selection_button.config(state="normal")
        else:
            self.clear_selection_button.config(state="disabled")

        # QR-Scan-Button aktivieren wenn genau EIN Foto angezeigt wird
        # (auch wenn mehrere ausgewählt sind, wird nur das aktuelle gescannt)
        if self.photo_paths and 0 <= self.current_photo_index < len(self.photo_paths):
            self.qr_scan_button.config(state="normal")
            self.wm_button.config(state="normal")  # NEU
            self.update_wm_button_state()  # NEU: Status aktualisieren
        else:
            self.qr_scan_button.config(state="disabled")
            self.wm_button.config(state="disabled")  # NEU

    def _clear_all_selections(self):
        """Hebt alle expliziten Markierungen auf"""
        self.selected_photos.clear()
        self.explicitly_selected = False
        self.shift_selection_start = None
        self.shift_direction = None

        self._update_thumbnail_selection_styles()
        self._update_delete_button()

    def _scan_current_photo_qr(self):
        """Scannt das aktuelle Foto nach QR-Code"""
        if self.current_photo_index < 0 or self.current_photo_index >= len(self.photo_paths):
            return

        photo_path = self.photo_paths[self.current_photo_index]

        # Nutze die App-Methode mit Loading Window und Thread
        if self.app and hasattr(self.app, 'run_photo_qr_analysis'):
            self.app.run_photo_qr_analysis(photo_path)
        else:
            from tkinter import messagebox
            messagebox.showerror("Fehler", "QR-Code-Scanner nicht verfügbar")

    def _delete_current_photo(self):
        """Löscht die aktuell ausgewählten Fotos (Mehrfachauswahl-fähig)"""
        if not self.photo_paths:
            return

        # Bestimme welche Fotos zu löschen sind
        if self.explicitly_selected and self.selected_photos:
            indices_to_delete = sorted(self.selected_photos, reverse=True)
        else:
            # Implizite Auswahl - nur aktuelles Foto
            indices_to_delete = [self.current_photo_index]

        # WICHTIG: Zuerst aus Drag-Drop-Liste entfernen
        if self.app and hasattr(self.app, 'drag_drop'):
            for idx in indices_to_delete:
                if 0 <= idx < len(self.photo_paths):
                    deleted_path = self.photo_paths[idx]
                    # Entferne aus Drag-Drop (dies aktualisiert auch photo_paths dort)
                    self.app.drag_drop.remove_photo(deleted_path, update_preview=False)

            # Hole die aktualisierte Liste von Drag-Drop
            self.photo_paths = self.app.drag_drop.get_photo_paths()
        else:
            # Fallback: Entferne nur aus lokaler Liste
            for idx in indices_to_delete:
                if 0 <= idx < len(self.photo_paths):
                    self.photo_paths.pop(idx)

        self.photo_images.clear()
        self.thumbnail_images.clear()
        self._prune_metadata_cache()

        self.selected_photos.clear()
        self.explicitly_selected = False

        if self.photo_paths:
            self.current_photo_index = 0
            self.last_clicked_index = 0
        else:
            self.current_photo_index = -1
            self.last_clicked_index = None

        self._totals_dirty = True
        self._rebuild_thumbnails_full()
        self._schedule_large_preview_update()
        self._update_current_photo_info()
        self._update_totals_info()
        self._update_delete_button()

    def _cleanup_cache_after_delete(self, deleted_index):
        """Räumt Cache intelligent auf nach dem Löschen eines Fotos"""
        # Alte Cache-Einträge ab dem gelöschten Index entfernen
        # Die Einträge davor können bleiben
        keys_to_delete = [k for k in self.thumbnail_images.keys() if k >= deleted_index]
        for key in keys_to_delete:
            if key in self.thumbnail_images:
                del self.thumbnail_images[key]

        keys_to_delete = [k for k in self.photo_images.keys() if k >= deleted_index]
        for key in keys_to_delete:
            if key in self.photo_images:
                del self.photo_images[key]

    def _remove_thumbnail_widget_instantly(self, index):
        """Entfernt das Thumbnail-Widget am angegebenen Index sofort für instant Feedback"""
        try:
            children = self.thumbnail_inner_frame.winfo_children()
            if 0 <= index < len(children):
                # Entferne das Widget sofort
                children[index].destroy()
                # Update Canvas sofort
                self.thumbnail_inner_frame.update_idletasks()
        except Exception as e:
            # Fehler ignorieren, wird beim nächsten Update eh neu gerendert
            pass

    # --- NEU: WASSERZEICHEN-METHODEN ---

    def _on_wm_button_click(self):
        """
        Wird aufgerufen, wenn der Wasserzeichen-Button geklickt wird.
        Leitet die Aktion an app.py weiter.
        """
        if not self.app or not hasattr(self.app, 'drag_drop') or not self.photo_paths:
            return

        # Bei expliziter Mehrfachauswahl: auf alle markierten Fotos anwenden.
        if self.explicitly_selected and self.selected_photos:
            target_indices = sorted(
                i for i in self.selected_photos
                if 0 <= i < len(self.photo_paths)
            )
        elif self.current_photo_index is not None and 0 <= self.current_photo_index < len(self.photo_paths):
            target_indices = [self.current_photo_index]
        else:
            target_indices = []

        if not target_indices:
            return

        # Einheitliches Ziel für die komplette Auswahl:
        # Wenn mindestens ein Foto noch nicht markiert ist -> alle markieren,
        # sonst alle entmarkieren.
        should_mark_all = any(
            not self.app.drag_drop.is_photo_watermarked(i) for i in target_indices
        )

        if hasattr(self.app, "set_photo_watermark_for_indices"):
            self.app.set_photo_watermark_for_indices(target_indices, should_mark_all)
        elif len(target_indices) == 1 and hasattr(self.app, 'toggle_photo_watermark'):
            # Fallback für ältere App-Versionen
            self.app.toggle_photo_watermark(target_indices[0])

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
        if (not self.app or not hasattr(self.app, 'drag_drop') or
            self.current_photo_index < 0 or not self.photo_paths):
            self.wm_button.config(text="Preview ☐", state="disabled", bg="#f0f0f0")
            self.wm_button_var.set(False)
            return

        # Lese den Status direkt von drag_drop (via app)
        is_marked = self.app.drag_drop.is_photo_watermarked(self.current_photo_index)
        self.wm_button_var.set(is_marked)

        if is_marked:
            self.wm_button.config(text="Preview ☑", state="normal", bg="#4CAF50", fg="white")
        else:
            self.wm_button.config(text="Preview ☐", state="normal", bg="#f0f0f0", fg="black")

    def pack(self, **kwargs):
        """Packt den Frame"""
        self.frame.pack(**kwargs)

    def _on_filename_hover_enter(self, event):
        """Zeigt Tooltip mit vollständigem Dateinamen beim Hover"""
        widget = event.widget
        full_text = widget.cget("text")

        # Zeige Tooltip nur wenn Text abgekürzt ist (enthält ...)
        if "..." in full_text or len(full_text) > 30:
            # Hole vollständigen Dateinamen aus photo_paths
            if self.photo_paths and self.current_photo_index < len(self.photo_paths):
                full_filename = os.path.basename(self.photo_paths[self.current_photo_index])

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

    def get_photo_paths(self):
        """Gibt die aktuellen Foto-Pfade zurück"""
        return self.photo_paths

