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

        # Widgets
        self.large_preview_canvas = None
        self.thumbnail_canvas = None
        self.thumbnail_scrollbar = None
        self.thumbnail_inner_frame = None
        self.thumbnail_canvas_window = None
        self.info_labels = {}
        self.delete_button = None

        # Drag-Scrolling-Variablen
        self.drag_start_x = 0
        self.drag_start_scroll = 0
        self.is_dragging = False
        self.drag_start_scroll = 0

        # Navigation Pfeile
        self.left_arrow_id = None
        self.right_arrow_id = None
        self.show_arrows = False

        # Größen
        self.large_preview_width = 568
        self.large_preview_height = 320
        self.thumbnail_size = 60

        self.create_widgets()

    def create_widgets(self):
        """Erstellt alle Widgets für die Foto-Vorschau"""

        # --- Große Vorschau ---
        preview_frame = tk.Frame(self.frame)
        preview_frame.pack(fill="x", pady=(0, 10))

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

        # Event-Bindings für Navigation-Pfeile
        self.large_preview_canvas.bind("<Enter>", self._on_preview_enter)
        self.large_preview_canvas.bind("<Leave>", self._on_preview_leave)
        self.large_preview_canvas.bind("<Button-1>", self._on_preview_click)

        # --- Thumbnail-Galerie ---
        thumbnail_frame = tk.Frame(self.frame)
        thumbnail_frame.pack(fill="x", pady=(0, 5))

        # Scrollbarer Canvas für Thumbnails
        self.thumbnail_canvas = tk.Canvas(
            thumbnail_frame,
            height=self.thumbnail_size,
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
        self.thumbnail_scrollbar.pack(fill="x", pady=(2, 0))
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
        self.drag_start_x = 0
        self.drag_start_scroll = 0
        self.is_dragging = False

        # --- Foto-Informationen ---
        info_frame = tk.Frame(self.frame, relief="groove", borderwidth=1, padx=5, pady=5)
        info_frame.pack(fill="x", pady=(0, 10))

        # Zwei Spalten: Links = Aktuelles Foto, Rechts = Gesamt-Statistik
        left_info_frame = tk.Frame(info_frame)
        left_info_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right_info_frame = tk.Frame(info_frame)
        right_info_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

        # Grid-Gewichte für gleichmäßige Verteilung
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

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

            value_label = tk.Label(left_info_frame, text="-", font=("Arial", 8), anchor="w")
            value_label.grid(row=idx, column=1, sticky="w")

            self.info_labels[key] = value_label

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

        # Löschen-Button unter Gesamt-Statistik
        self.delete_button = tk.Button(
            right_info_frame,
            text="Ausgewähltes Foto löschen",
            command=self._delete_current_photo,
            bg="#f44336",
            fg="white",
            font=("Arial", 9, "bold"),
            state="disabled"
        )
        self.delete_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def set_photos(self, photo_paths):
        """Setzt die anzuzeigenden Fotos"""
        self.photo_paths = photo_paths
        self.current_photo_index = 0 if photo_paths else -1

        # Cache leeren
        self.photo_images.clear()
        self.thumbnail_images.clear()

        # UI aktualisieren
        self._update_thumbnails()
        self._update_large_preview()
        self._update_info()
        self._update_delete_button()

    def _update_thumbnails(self):
        """Aktualisiert die Thumbnail-Galerie"""
        # Alte Thumbnails entfernen
        for widget in self.thumbnail_inner_frame.winfo_children():
            widget.destroy()

        if not self.photo_paths:
            self.thumbnail_canvas.configure(scrollregion=(0, 0, 0, 0))
            return

        # Neue Thumbnails erstellen
        for idx, photo_path in enumerate(self.photo_paths):
            thumbnail = self._create_thumbnail(photo_path, idx)
            if thumbnail:
                # Frame für Thumbnail mit Border
                # Ausgewähltes Thumbnail hat dickeren grünen Rand
                is_selected = idx == self.current_photo_index

                if is_selected:
                    thumb_frame = tk.Frame(
                        self.thumbnail_inner_frame,
                        relief="solid",
                        borderwidth=4,
                        bg="#4CAF50",
                        highlightthickness=2,
                        highlightbackground="#4CAF50"
                    )
                else:
                    thumb_frame = tk.Frame(
                        self.thumbnail_inner_frame,
                        relief="solid",
                        borderwidth=2,
                        bg="#cccccc"
                    )

                thumb_frame.pack(side="left", padx=5, pady=5)

                # Label mit Thumbnail
                thumb_label = tk.Label(thumb_frame, image=thumbnail, bg="white")
                thumb_label.image = thumbnail  # Referenz behalten
                thumb_label.pack()

                # Click-Event - verwende ButtonRelease statt Button-1 um Drag-Scrolling zu ermöglichen
                thumb_label.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click_release(e, i))
                thumb_frame.bind("<ButtonRelease-1>", lambda e, i=idx: self._on_thumbnail_click_release(e, i))

        # Canvas-Scroll-Region aktualisieren
        self.thumbnail_inner_frame.update_idletasks()
        bbox = self.thumbnail_canvas.bbox("all")
        if bbox:
            self.thumbnail_canvas.configure(scrollregion=bbox)

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

    def _create_thumbnail(self, photo_path, idx):
        """Erstellt ein Thumbnail für ein Foto"""
        if idx in self.thumbnail_images:
            return self.thumbnail_images[idx]

        try:
            img = Image.open(photo_path)
            img.thumbnail((self.thumbnail_size, self.thumbnail_size), Image.LANCZOS)
            thumbnail = ImageTk.PhotoImage(img)
            self.thumbnail_images[idx] = thumbnail
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

        arrow_size = 30
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

    def _on_preview_enter(self, event):
        """Zeigt Pfeile an wenn Maus über Preview schwebt"""
        if len(self.photo_paths) > 1:
            self.large_preview_canvas.itemconfig("arrow", state="normal")
            self.show_arrows = True

    def _on_preview_leave(self, event):
        """Versteckt Pfeile wenn Maus Preview verlässt"""
        self.large_preview_canvas.itemconfig("arrow", state="hidden")
        self.show_arrows = False

    def _on_preview_click(self, event):
        """Behandelt Klicks auf die Preview (Navigation)"""
        if len(self.photo_paths) <= 1:
            return

        # Prüfe ob auf linken oder rechten Bereich geklickt wurde
        if event.x < self.large_preview_width // 3 and self.current_photo_index > 0:
            # Links geklickt - vorheriges Foto
            self._show_previous_photo()
        elif event.x > 2 * self.large_preview_width // 3 and self.current_photo_index < len(self.photo_paths) - 1:
            # Rechts geklickt - nächstes Foto
            self._show_next_photo()

    def _on_thumbnail_click(self, index):
        """Behandelt Klick auf ein Thumbnail"""
        self.current_photo_index = index
        self._update_large_preview()
        self._update_thumbnails()
        self._update_info()

    def _on_thumbnail_click_release(self, event, index):
        """Behandelt ButtonRelease auf ein Thumbnail - nur wenn es kein Drag war"""
        # Nur als Klick behandeln wenn nicht gedragged wurde
        if not self.is_dragging:
            self._on_thumbnail_click(index)

    def _show_previous_photo(self):
        """Zeigt das vorherige Foto"""
        if self.current_photo_index > 0:
            self.current_photo_index -= 1
            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()

    def _show_next_photo(self):
        """Zeigt das nächste Foto"""
        if self.current_photo_index < len(self.photo_paths) - 1:
            self.current_photo_index += 1
            self._update_large_preview()
            self._update_thumbnails()
            self._update_info()

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
            # Dateiname
            filename = os.path.basename(photo_path)
            self.info_labels["filename"].config(text=filename)

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
            except:
                pass

        total_size_mb = total_size / (1024 * 1024)
        self.info_labels["total_size"].config(text=f"{total_size_mb:.2f} MB")

    def _update_delete_button(self):
        """Aktualisiert den Status des Löschen-Buttons"""
        if self.photo_paths and self.current_photo_index >= 0:
            self.delete_button.config(state="normal")
        else:
            self.delete_button.config(state="disabled")

    def _delete_current_photo(self):
        """Löscht das aktuell ausgewählte Foto"""
        if not self.photo_paths or self.current_photo_index < 0:
            return

        # Foto-Pfad merken
        deleted_path = self.photo_paths[self.current_photo_index]
        deleted_index = self.current_photo_index

        # WICHTIG: Zuerst aus Drag-Drop-Liste entfernen, dann UI aktualisieren
        # Dies stellt sicher, dass beide Listen synchron bleiben
        if self.app and hasattr(self.app, 'drag_drop'):
            # Entferne aus Drag-Drop (dies aktualisiert auch photo_paths dort)
            self.app.drag_drop.remove_photo(deleted_path, update_preview=False)

            # Hole die aktualisierte Liste von Drag-Drop
            self.photo_paths = self.app.drag_drop.get_photo_paths()

            # Index anpassen
            if self.current_photo_index >= len(self.photo_paths):
                self.current_photo_index = len(self.photo_paths) - 1

            # INSTANT: Gelöschtes Thumbnail sofort entfernen (visuelles Feedback)
            self._remove_thumbnail_widget_instantly(deleted_index)

            # PERFORMANCE-OPTIMIERUNG: Cache intelligent aufräumen
            self._cleanup_cache_after_delete(deleted_index)

            # Sofort große Vorschau und Info aktualisieren (schnell)
            self._update_large_preview()
            self._update_info()
            self._update_delete_button()

            # Thumbnails komplett neu rendern (nach kurzer Verzögerung für sauberes Layout)
            self.frame.after(10, self._update_thumbnails)
        else:
            # Fallback: Entferne nur aus lokaler Liste
            self.photo_paths.pop(self.current_photo_index)
            self._remove_thumbnail_widget_instantly(deleted_index)
            self._cleanup_cache_after_delete(deleted_index)
            if self.current_photo_index >= len(self.photo_paths):
                self.current_photo_index = len(self.photo_paths) - 1
            self._update_large_preview()
            self._update_info()
            self._update_delete_button()
            self.frame.after(10, self._update_thumbnails)

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

    def pack(self, **kwargs):
        """Packt den Frame"""
        self.frame.pack(**kwargs)

    def get_photo_paths(self):
        """Gibt die aktuellen Foto-Pfade zurück"""
        return self.photo_paths

