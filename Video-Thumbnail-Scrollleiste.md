Detaillierter Implementation Prompt für Video-Thumbnail-Scrollleiste
Kontext
Implementiere eine Thumbnail-Scrollleiste für Video-Clips in video_preview.py, die nahezu identisch zu photo_preview.py funktioniert, aber speziell für Videos mit Playback-Synchronisation optimiert ist.
Architektur-Entscheidung: Synchronisation
Option C - Vermittlung über app.py (empfohlen):

VideoPlayer._update_progress_ui() berechnet aktuellen Clip-Index basierend auf current_time_ms und clip_durations
VideoPlayer ruft app.video_preview.set_active_clip_by_time(current_time_ms) auf
VideoPreview berechnet intern den aktiven Clip-Index und aktualisiert die Thumbnail-Anzeige
Vermeidet zirkuläre Dependencies und ermöglicht flüssige Updates (alle 250ms während Playback)

Aufgaben
1. Thumbnail-Scrollleiste in video_preview.py erstellen
Neue Instanzvariablen hinzufügen:
python# In __init__() ergänzen:
self.thumbnail_canvas = None
self.thumbnail_scrollbar = None
self.thumbnail_inner_frame = None
self.thumbnail_canvas_window = None
self.thumbnail_images = {}  # Cache: {clip_index: ImageTk.PhotoImage}
self.current_active_clip = 0  # Aktuell aktiver Clip während Playback

# Drag-Scrolling
self.drag_start_x = 0
self.drag_start_scroll = 0
self.is_dragging = False

# Größen
self.thumbnail_size = 60  # px
Widget-Struktur in create_widgets() ergänzen:
python# Nach dem bestehenden Code, vor Info-Frame:

# --- Thumbnail-Galerie ---
thumbnail_frame = tk.Frame(self.frame)
thumbnail_frame.pack(fill="x", pady=(10, 5))

# Scrollbarer Canvas
self.thumbnail_canvas = tk.Canvas(
    thumbnail_frame,
    height=self.thumbnail_size,
    bg="#f0f0f0",
    highlightthickness=0
)
self.thumbnail_canvas.pack(fill="x", expand=True)

# Horizontale Scrollbar
self.thumbnail_scrollbar = ttk.Scrollbar(
    thumbnail_frame,
    orient="horizontal",
    command=self.thumbnail_canvas.xview
)
self.thumbnail_scrollbar.pack(fill="x", pady=(2, 0))
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
2. Info-Bereich erstellen (wie PhotoPreview)
Unterhalb der Thumbnail-Galerie:
python# --- Clip-Informationen ---
info_frame = tk.Frame(self.frame, relief="groove", borderwidth=1, padx=5, pady=5)
info_frame.pack(fill="x", pady=(0, 10))

# Zwei Spalten
left_info_frame = tk.Frame(info_frame)
left_info_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

right_info_frame = tk.Frame(info_frame)
right_info_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))

info_frame.grid_columnconfigure(0, weight=1)
info_frame.grid_columnconfigure(1, weight=1)

# === LINKE SPALTE: Aktueller Clip ===
single_info_title = tk.Label(left_info_frame, text="Aktueller Clip:", font=("Arial", 9, "bold"))
single_info_title.grid(row=0, column=0, columnspan=2, sticky="w")

info_fields = [
    ("Dateiname:", "filename"),
    ("Auflösung:", "resolution"),
    ("Dauer:", "duration"),  # NEU: Dauer statt Größe
    ("Größe:", "size")
]

self.info_labels = {}
for idx, (label_text, key) in enumerate(info_fields, start=1):
    label = tk.Label(left_info_frame, text=label_text, font=("Arial", 8), anchor="w")
    label.grid(row=idx, column=0, sticky="w", padx=(0, 5))
    
    value_label = tk.Label(left_info_frame, text="-", font=("Arial", 8), anchor="w")
    value_label.grid(row=idx, column=1, sticky="w")
    
    self.info_labels[key] = value_label

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

# Buttons
button_frame = tk.Frame(right_info_frame)
button_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
button_frame.columnconfigure(0, weight=1)
button_frame.columnconfigure(1, weight=1)
button_frame.columnconfigure(2, weight=0)

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
3. Thumbnail-Generierung mit FFmpeg
Neue Methode hinzufügen:
pythondef _create_video_thumbnail(self, video_path, clip_index, is_active=False):
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
        import subprocess
        import tempfile
        from PIL import Image, ImageTk
        
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
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        )
        
        # Lade Bild und erstelle Thumbnail
        img = Image.open(tmp_path)
        size = int(self.thumbnail_size * 1.3) if is_active else self.thumbnail_size
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
4. Thumbnail-Anzeige aktualisieren
Neue Methode:
pythondef _update_thumbnails(self):
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
5. Drag-Scrolling implementieren (von PhotoPreview kopieren)
Methoden hinzufügen:
pythondef _on_thumbnail_drag_start(self, event):
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
6. Click-Handler für Thumbnail-Navigation
pythondef _on_thumbnail_click(self, event, clip_index):
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
7. Synchronisation mit VideoPlayer
In video_preview.py hinzufügen:
pythondef set_active_clip_by_time(self, current_time_ms):
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
In video_player.py modifizieren:
In der Methode _update_progress_ui() nach dem Aktualisieren der Progress-Bar hinzufügen:
pythondef _update_progress_ui(self):
    """Aktualisiert die Fortschrittsanzeige und die Zeit-Labels"""
    # ... bestehender Code ...
    
    # NEU: Informiere VideoPreview über aktuelle Zeit für Clip-Synchronisation
    if self.app and hasattr(self.app, 'video_preview'):
        self.app.video_preview.set_active_clip_by_time(current_time_ms)
    
    if self.media_player.is_playing():
        self._start_updater()
8. Info-Aktualisierung implementieren
pythondef _update_info(self):
    """Aktualisiert die Clip-Informationen"""
    if not self.video_paths or self.current_active_clip < 0:
        for key in ["filename", "resolution", "duration", "size"]:
            self.info_labels[key].config(text="-")
        self.info_labels["total_count"].config(text="0")
        self.info_labels["total_duration"].config(text="00:00")
        return
    
    # Aktueller Clip
    video_path = self.video_paths[self.current_active_clip]
    
    try:
        # Dateiname
        filename = os.path.basename(video_path)
        self.info_labels["filename"].config(text=filename)
        
        # Hole Metadaten aus Cache (bereits von update_preview geladen)
        metadata = self.metadata_cache.get(video_path, {})
        
        # Auflösung
        width = metadata.get('width', 0)
        height = metadata.get('height', 0)
        self.info_labels["resolution"].config(text=f"{width} × {height} px" if width else "-")
        
        # Dauer
        if self.current_active_clip < len(self.clip_durations):
            duration_sec = self.clip_durations[self.current_active_clip]
            minutes = int(duration_sec // 60)
            seconds = int(duration_sec % 60)
            self.info_labels["duration"].config(text=f"{minutes:02d}:{seconds:02d}")
        else:
            self.info_labels["duration"].config(text="-")
        
        # Dateigröße
        size_bytes = os.path.getsize(video_path)
        size_mb = size_bytes / (1024 * 1024)
        self.info_labels["size"].config(text=f"{size_mb:.2f} MB")
        
    except Exception as e:
        print(f"Fehler beim Abrufen der Clip-Informationen: {e}")
    
    # Gesamt-Statistiken
    total_count = len(self.video_paths)
    self.info_labels["total_count"].config(text=str(total_count))
    
    total_duration_sec = sum(self.clip_durations) if self.clip_durations else 0
    total_minutes = int(total_duration_sec // 60)
    total_seconds = int(total_duration_sec % 60)
    self.info_labels["total_duration"].config(text=f"{total_minutes:02d}:{total_seconds:02d}")
9. Button-Funktionalität implementieren
pythondef _delete_selected_clip(self):
    """Löscht den aktuell ausgewählten Clip"""
    if self.current_active_clip < 0 or self.current_active_clip >= len(self.video_paths):
        return
    
    # Bestätigung
    from tkinter import messagebox
    clip_name = os.path.basename(self.video_paths[self.current_active_clip])
    if not messagebox.askyesno("Clip löschen", f"Clip '{clip_name}' wirklich löschen?"):
        return
    
    # Entferne aus drag_drop
    if self.app and hasattr(self.app, 'drag_drop'):
        deleted_path = self.video_paths[self.current_active_clip]
        self.app.drag_drop.remove_video(deleted_path, update_preview=True)

def _clear_selection(self):
    """Hebt Auswahl auf (für Mehrfachauswahl-Kompatibilität)"""
    # Aktuell keine Mehrfachauswahl - könnte später erweitert werden
    pass

def _scan_current_clip_qr(self):
    """Scannt den aktuellen Clip nach QR-Code"""
    if self.current_active_clip < 0 or self.current_active_clip >= len(self.video_paths):
        return
    
    video_path = self.video_paths[self.current_active_clip]
    
    if self.app and hasattr(self.app, 'run_qr_analysis'):
        self.app.run_qr_analysis([video_path])
10. Button-Status aktualisieren
pythondef _update_button_states(self):
    """Aktualisiert den Status aller Buttons"""
    has_clips = bool(self.video_paths)
    
    if has_clips:
        self.delete_button.config(state="normal")
        self.qr_scan_button.config(state="normal")
    else:
        self.delete_button.config(state="disabled")
        self.qr_scan_button.config(state="disabled")
    
    # Clear-Selection immer disabled (keine Mehrfachauswahl aktuell)
    self.clear_selection_button.config(state="disabled")
11. Integration in update_preview
In der bestehenden update_preview() Methode nach dem Laden der Metadaten:
pythondef update_preview(self, video_paths):
    """Aktualisiert die Vorschau mit neuen Videos"""
    # ... bestehender Code ...
    
    # NEU: Nach erfolgreicher Verarbeitung Thumbnails und Info aktualisieren
    self._update_thumbnails()
    self._update_info()
    self._update_button_states()
12. Cleanup erweitern
In _cleanup_temp_copies() ergänzen:
pythondef _cleanup_temp_copies(self):
    """Löscht temporäre Vorschau-Kopien"""
    # ... bestehender Code ...
    
    # NEU: Thumbnail-Cache leeren
    self.thumbnail_images.clear()
13. clear_preview erweitern
In clear_preview() ergänzen:
pythondef clear_preview(self):
    """Löscht die Vorschau komplett"""
    # ... bestehender Code ...
    
    # NEU: Thumbnails und Info zurücksetzen
    self.current_active_clip = 0
    self._update_thumbnails()
    self._update_info()
    self._update_button_states()
Testing-Checkliste

 Thumbnails werden korrekt generiert (erstes Frame)
 Klick auf Thumbnail springt zur richtigen Position im VideoPlayer
 Während Playback wird der aktive Clip hervorgehoben
 Drag-Scrolling funktioniert flüssig
 Mausrad-Scrolling funktioniert
 Auto-Scroll zum aktiven Clip während Playback
 Info-Anzeige zeigt korrekte Werte (Dateiname, Auflösung, Dauer, Größe)
 Gesamt-Statistik zeigt korrekte Werte
 Delete-Button entfernt Clip korrekt
 QR-Scan-Button startet Analyse
 Aktiver Clip hat größeres Thumbnail und blauen Rahmen
 Cache wird korrekt verwaltet (keine Memory-Leaks)

Wichtige Hinweise

Performance: Thumbnail-Generierung kann langsam sein - erwäge Threading für große Clip-Listen
FFmpeg-Path: Stelle sicher dass FFmpeg im PATH ist oder verwende den konfigurierten Pfad aus ConfigManager
Error-Handling: Robuste Fehlerbehandlung bei FFmpeg-Fehlern (korrupte Videos etc.)
Memory: Begrenze Thumbnail-Cache-Größe bei sehr vielen Clips (z.B. max 50 Thumbnails)