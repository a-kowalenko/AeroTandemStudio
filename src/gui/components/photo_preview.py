import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk
import os
from datetime import datetime


class PhotoPreview:
    """Komponente für die Foto-Vorschau mit großer Ansicht, Thumbnail-Galerie und Informationen"""

    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent)

        # Foto-Daten
        self.photo_paths = []
        self.current_photo_index = 0
        self.photo_images = {}  # Cache für geladene Bilder
        self.thumbnail_images = {}  # Cache für Thumbnails

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
            text="Foto löschen",
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
            text="🔍",  # QR-Code ähnliches Symbol (Box mit Kreuz)
            command=self._scan_current_photo_qr,
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

    def set_photos(self, photo_paths):
        """Setzt die anzuzeigenden Fotos"""
        self.photo_paths = photo_paths
        self.current_photo_index = 0 if photo_paths else -1

        # NEU: Mehrfachauswahl zurücksetzen
        self.selected_photos.clear()
        self.explicitly_selected = False  # Keine explizite Markierung
        self.last_clicked_index = 0 if photo_paths else None

        # Cache leeren
        self.photo_images.clear()
        self.thumbnail_images.clear()

        # UI aktualisieren
        self._update_thumbnails()
        self._update_large_preview()
        self._update_info()
        self._update_delete_button()

    def _update_thumbnails(self):
        """Aktualisiert die Thumbnail-Galerie mit Mehrfachauswahl-Unterstützung"""
        # Alte Thumbnails entfernen
        for widget in self.thumbnail_inner_frame.winfo_children():
            widget.destroy()

        if not self.photo_paths:
            self.thumbnail_canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        # Neue Thumbnails erstellen
        for idx, photo_path in enumerate(self.photo_paths):
            is_current = idx == self.current_photo_index

            # Implizite vs. explizite Markierung
            if self.explicitly_selected:
                # Explizite Markierung vorhanden - nur explizit markierte zeigen
                is_selected = idx in self.selected_photos
            else:
                # Keine explizite Markierung - aktuelles Foto gilt als markiert
                is_selected = is_current

            # Prüfe ob mehrere Fotos markiert sind
            if self.explicitly_selected:
                multiple_selected = len(self.selected_photos) > 1
            else:
                multiple_selected = False

            thumbnail = self._create_thumbnail(photo_path, idx, is_current=is_current)
            if thumbnail:
                # Frame für Thumbnail mit Border
                # Bestimme Rahmenfarbe basierend auf Markierung
                # Oranger Rand nur wenn markiert UND (mehrere markiert ODER nicht aktiv)
                if is_selected and (multiple_selected or not is_current):
                    # Markiert mit orangem Rand: wenn mehrere markiert ODER nicht das aktive Foto
                    thumb_frame = tk.Frame(
                        self.thumbnail_inner_frame,
                        bg="white",
                        highlightthickness=3,
                        highlightbackground="#FF9800"  # Orange für markiert
                    )
                else:
                    # Nicht markiert oder nur das aktive allein markiert: Grauer Rand
                    thumb_frame = tk.Frame(
                        self.thumbnail_inner_frame,
                        bg="white",
                        highlightthickness=2,
                        highlightbackground="#999999"  # Grau
                    )

                thumb_frame.pack(side="left", padx=5, pady=5)

                # Label mit Thumbnail
                thumb_label = tk.Label(thumb_frame, image=thumbnail, bg="white")
                thumb_label.image = thumbnail  # Referenz behalten
                thumb_label.pack()

                # Click-Event - NEU: Mit Modifier-Keys für Mehrfachauswahl
                thumb_label.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click_release(e, i))
                thumb_frame.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click_release(e, i))

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

        # Hole alle Thumbnail-Widgets (Frames)
        children = self.thumbnail_inner_frame.winfo_children()
        if self.current_photo_index >= len(children):
            return

        # Hole das aktive Thumbnail-Frame
        active_frame = children[self.current_photo_index]

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

    def _create_thumbnail(self, photo_path, idx, is_current=False):
        """Erstellt ein Thumbnail für ein Foto - aktive 1.3x größer"""
        # Cache-Key berücksichtigt ob aktiv oder nicht
        cache_key = (idx, is_current)
        if cache_key in self.thumbnail_images:
            return self.thumbnail_images[cache_key]

        try:
            img = Image.open(photo_path)

            # Aktive Thumbnails sind 1.3x größer
            size = int(self.thumbnail_size * 1.3) if is_current else self.thumbnail_size

            # Verwende thumbnail() - skaliert in Bounding Box mit Aspect Ratio (wie Video Preview)
            img.thumbnail((size, size), Image.LANCZOS)

            thumbnail = ImageTk.PhotoImage(img)
            self.thumbnail_images[cache_key] = thumbnail
            return thumbnail
        except Exception as e:
            print(f"Fehler beim Erstellen des Thumbnails für {photo_path}: {e}")
            return None

    def _update_large_preview(self):
        """Aktualisiert die große Foto-Vorschau"""
        # Canvas leeren
        self.large_preview_canvas.delete("all")

        if not self.photo_paths or self.current_photo_index < 0:
            # Platzhalter anzeigen
            self.large_preview_canvas.create_text(
                self.large_preview_width // 2,
                self.large_preview_height // 2,
                text="Keine Fotos",
                fill="white",
                font=("Arial", 12)
            )
            return

        # Foto laden und anzeigen
        photo_path = self.photo_paths[self.current_photo_index]
        try:
            img = Image.open(photo_path)
            # Größe anpassen (aspect ratio beibehalten)
            img.thumbnail((self.large_preview_width, self.large_preview_height), Image.LANCZOS)
            photo_image = ImageTk.PhotoImage(img)
            self.photo_images[self.current_photo_index] = photo_image

            # Zentriert anzeigen
            x = self.large_preview_width // 2
            y = self.large_preview_height // 2
            self.large_preview_canvas.create_image(x, y, image=photo_image, anchor="center")

            # Pfeile zeichnen (initial versteckt)
            self._draw_navigation_arrows()

        except Exception as e:
            print(f"Fehler beim Laden des Fotos {photo_path}: {e}")
            self.large_preview_canvas.create_text(
                self.large_preview_width // 2,
                self.large_preview_height // 2,
                text="Fehler beim Laden",
                fill="red",
                font=("Arial", 12)
            )

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
                # Normaler Klick: Macht nur das Foto aktiv, deselektiert NICHT
                self.current_photo_index = index  # Macht das Foto aktiv
                self.last_clicked_index = index
        else:
            # Kein Event (z.B. programmatischer Aufruf)
            self.current_photo_index = index
            self.last_clicked_index = index

        # Update UI - nur bei normalem Klick wird große Preview aktualisiert
        if not event or (not ctrl_pressed and not shift_pressed):
            self._update_large_preview()
        self._update_thumbnails()
        self._update_info()
        self._update_delete_button()
        # NEU: WM-Button Status aktualisieren
        self.update_wm_button_state()

    def _on_thumbnail_click_release(self, event, index):
        """Behandelt ButtonRelease auf ein Thumbnail - nur wenn es kein Drag war"""
        # Nur als Klick behandeln wenn nicht gedragged wurde
        if not self.is_dragging:
            self._on_thumbnail_click(index, event)

    def _show_previous_photo(self):
        """Zeigt das vorherige Foto"""
        if self.current_photo_index > 0:
            # Nur aktuellen Index ändern, NICHT die Auswahl
            self.current_photo_index -= 1

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            # NEU: WM-Button Status aktualisieren
            self.update_wm_button_state()

    def _show_next_photo(self):
        """Zeigt das nächste Foto"""
        if self.current_photo_index < len(self.photo_paths) - 1:
            # Nur aktuellen Index ändern, NICHT die Auswahl
            self.current_photo_index += 1

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            # NEU: WM-Button Status aktualisieren
            self.update_wm_button_state()

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
            self.explicitly_selected = True  # Aktiviere explizite Markierung

            # Markiere Start-Foto und bewege Index nach links
            self.selected_photos.clear()
            self.selected_photos.add(self.current_photo_index)  # Startpunkt
            self.current_photo_index -= 1  # Bewege nach links
            self.selected_photos.add(self.current_photo_index)  # Neues Foto
            self.last_clicked_index = self.current_photo_index

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            self._update_delete_button()
            return

        # Fall 2: Wir waren nach rechts, jetzt nach links (Zusammenziehen)
        if self.shift_direction == 'right':
            # Entferne das aktuelle (rechts äußerste) Foto
            self.selected_photos.discard(self.current_photo_index)
            self.current_photo_index -= 1  # Gehe einen Schritt zurück
            # Richtung bleibt 'right' - wir ziehen nur zusammen

            # Prüfe ob nur noch das aktive Foto übrig ist
            if len(self.selected_photos) == 1 and self.current_photo_index in self.selected_photos:
                # Zurück zu impliziter Auswahl
                self.selected_photos.clear()
                self.explicitly_selected = False
                self.shift_selection_start = None
                self.shift_direction = None

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            self._update_delete_button()
            return

        # Fall 3: Weitergehen nach links (gleiche Richtung - Erweitern)
        self.current_photo_index -= 1
        self.selected_photos.add(self.current_photo_index)
        self.last_clicked_index = self.current_photo_index

        self._update_large_preview()
        self._update_thumbnails()
        self._update_info()
        self._update_delete_button()

    def _on_key_shift_right(self, event):
        """Behandelt Shift+Rechts - Akkordeon-Markierung nach rechts"""
        if not self.photo_paths or self.current_photo_index >= len(self.photo_paths) - 1:
            return

        # Fall 1: Erste Shift-Taste - Starte Session
        if self.shift_selection_start is None:
            self.shift_selection_start = self.current_photo_index
            self.shift_direction = 'right'
            self.explicitly_selected = True  # Aktiviere explizite Markierung

            # Markiere Start-Foto und bewege Index nach rechts
            self.selected_photos.clear()
            self.selected_photos.add(self.current_photo_index)  # Startpunkt
            self.current_photo_index += 1  # Bewege nach rechts
            self.selected_photos.add(self.current_photo_index)  # Neues Foto
            self.last_clicked_index = self.current_photo_index

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            self._update_delete_button()
            return

        # Fall 2: Wir waren nach links, jetzt nach rechts (Zusammenziehen)
        if self.shift_direction == 'left':
            # Entferne das aktuelle (links äußerste) Foto
            self.selected_photos.discard(self.current_photo_index)
            self.current_photo_index += 1  # Gehe einen Schritt zurück
            # Richtung bleibt 'left' - wir ziehen nur zusammen

            # Prüfe ob nur noch das aktive Foto übrig ist
            if len(self.selected_photos) == 1 and self.current_photo_index in self.selected_photos:
                # Zurück zu impliziter Auswahl
                self.selected_photos.clear()
                self.explicitly_selected = False
                self.shift_selection_start = None
                self.shift_direction = None

            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()
            self._update_delete_button()
            return

        # Fall 3: Weitergehen nach rechts (gleiche Richtung - Erweitern)
        self.current_photo_index += 1
        self.selected_photos.add(self.current_photo_index)
        self.last_clicked_index = self.current_photo_index

        self._update_large_preview()
        self._update_thumbnails()
        self._update_info()
        self._update_delete_button()

    def _on_key_select_all(self, event):
        """Behandelt Strg+A - Alle Fotos auswählen"""
        if not self.photo_paths:
            return

        # Wähle alle Fotos aus
        self.selected_photos = set(range(len(self.photo_paths)))
        self.explicitly_selected = True  # Explizite Markierung
        self.last_clicked_index = self.current_photo_index

        self._update_thumbnails()
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

        # Canvas für Vollbild-Foto
        fullscreen_canvas = tk.Canvas(
            self.fullscreen_window,
            bg='black',
            highlightthickness=0
        )
        fullscreen_canvas.pack(fill="both", expand=True)

        # Lade aktuelles Foto in voller Auflösung
        photo_path = self.photo_paths[self.current_photo_index]
        try:
            img = Image.open(photo_path)

            # Bildschirmgröße
            screen_width = self.fullscreen_window.winfo_screenwidth()
            screen_height = self.fullscreen_window.winfo_screenheight()

            # Skaliere Bild auf Bildschirmgröße (Aspect Ratio beibehalten)
            img.thumbnail((screen_width, screen_height), Image.LANCZOS)
            photo_image = ImageTk.PhotoImage(img)

            # Zentriert anzeigen
            x = screen_width // 2
            y = screen_height // 2
            fullscreen_canvas.create_image(x, y, image=photo_image, anchor="center")

            # Referenz behalten
            fullscreen_canvas.image = photo_image

            # Info-Text (unten links)
            filename = os.path.basename(photo_path)
            info_text = f"{self.current_photo_index + 1}/{len(self.photo_paths)} - {filename}"
            fullscreen_canvas.create_text(
                20, screen_height - 20,
                text=info_text,
                fill="white",
                font=("Arial", 12),
                anchor="sw"
            )

            # Hinweis-Text (unten rechts)
            help_text = "ESC: Beenden | ← →: Navigation"
            fullscreen_canvas.create_text(
                screen_width - 20, screen_height - 20,
                text=help_text,
                fill="white",
                font=("Arial", 11),
                anchor="se"
            )

        except Exception as e:
            print(f"Fehler beim Laden des Vollbild-Fotos: {e}")

        # Event-Bindings für Vollbild
        self.fullscreen_window.bind("<Escape>", lambda e: self.fullscreen_window.destroy())
        self.fullscreen_window.bind("<Button-1>", lambda e: self.fullscreen_window.destroy())
        self.fullscreen_window.bind("<Left>", self._on_fullscreen_key_left)
        self.fullscreen_window.bind("<Right>", self._on_fullscreen_key_right)

        # Focus setzen
        self.fullscreen_window.focus_set()

    def _on_fullscreen_key_left(self, event):
        """Behandelt linke Pfeiltaste im Vollbild-Modus"""
        if self.current_photo_index > 0:
            self.fullscreen_window.destroy()
            self._show_previous_photo()
            # Kurz warten, dann Vollbild wieder öffnen
            self.frame.after(50, self._open_fullscreen)

    def _on_fullscreen_key_right(self, event):
        """Behandelt rechte Pfeiltaste im Vollbild-Modus"""
        if self.current_photo_index < len(self.photo_paths) - 1:
            self.fullscreen_window.destroy()
            self._show_next_photo()
            # Kurz warten, dann Vollbild wieder öffnen
            self.frame.after(50, self._open_fullscreen)

    def _update_info(self):
        """Aktualisiert die Foto-Informationen"""
        if not self.photo_paths or self.current_photo_index < 0:
            # Alle Infos zurücksetzen
            for key in ["filename", "resolution", "size", "date"]:
                self.info_labels[key].config(text="-")
            self.info_labels["total_count"].config(text="0")
            self.info_labels["total_size"].config(text="0 MB")
            return

        # Aktuelles Foto Info
        photo_path = self.photo_paths[self.current_photo_index]

        try:
            # Dateiname (mit Kürzung)
            filename = os.path.basename(photo_path)
            truncated_filename = self._truncate_filename(filename, max_chars=30)
            self.info_labels["filename"].config(text=truncated_filename)

            # Auflösung
            img = Image.open(photo_path)
            width, height = img.size
            self.info_labels["resolution"].config(text=f"{width} × {height} px")

            # Dateigröße
            size_bytes = os.path.getsize(photo_path)
            size_mb = size_bytes / (1024 * 1024)
            self.info_labels["size"].config(text=f"{size_mb:.2f} MB")

            # Datum und Uhrzeit
            timestamp = os.path.getmtime(photo_path)
            dt = datetime.fromtimestamp(timestamp)
            self.info_labels["date"].config(text=dt.strftime("%d.%m.%Y - %H:%M:%S"))

        except Exception as e:
            print(f"Fehler beim Abrufen der Foto-Informationen: {e}")

        # Gesamt-Statistiken
        total_count = len(self.photo_paths)
        self.info_labels["total_count"].config(text=str(total_count))

        total_size = 0
        for path in self.photo_paths:
            try:
                total_size += os.path.getsize(path)
            except Exception:
                pass

        total_size_mb = total_size / (1024 * 1024)
        self.info_labels["total_size"].config(text=f"{total_size_mb:.2f} MB")

        # NEU: WM-Button Status aktualisieren
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
                self.delete_button.config(text="Foto löschen", state="normal")
            else:
                self.delete_button.config(text=f"{count} Fotos löschen", state="normal")
        else:
            self.delete_button.config(text="Foto löschen", state="disabled")

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

        self._update_thumbnails()
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

        # Cache komplett leeren (einfacher bei Mehrfachauswahl)
        self.photo_images.clear()
        self.thumbnail_images.clear()

        # Auswahl zurücksetzen
        self.selected_photos.clear()
        self.explicitly_selected = False

        # Neuen aktuellen Index bestimmen
        if self.photo_paths:
            # Wähle das erste verbleibende Foto
            self.current_photo_index = 0
            self.last_clicked_index = 0
        else:
            self.current_photo_index = -1
            self.last_clicked_index = None

        # UI komplett aktualisieren
        self._update_thumbnails()
        self._update_large_preview()
        self._update_info()
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
        if self.app and hasattr(self.app, 'toggle_photo_watermark') and self.current_photo_index is not None:
            if 0 <= self.current_photo_index < len(self.photo_paths):
                self.app.toggle_photo_watermark(self.current_photo_index)

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
            self.wm_button.config(text="💧", state="disabled", bg="#f0f0f0")
            return

        # Lese den Status direkt von drag_drop (via app)
        is_marked = self.app.drag_drop.is_photo_watermarked(self.current_photo_index)

        if is_marked:
            self.wm_button.config(text="💧", state="normal", bg="#D32F2F", fg="white")
        else:
            self.wm_button.config(text="💧", state="normal", bg="#FF9800", fg="black")

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

