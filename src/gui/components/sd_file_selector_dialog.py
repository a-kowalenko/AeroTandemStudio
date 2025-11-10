"""
Dialog zur Auswahl von Dateien von der SD-Karte mit Thumbnail- und Detail-Ansicht
"""
import tkinter as tk
from tkinter import ttk
import os
from pathlib import Path
from PIL import Image, ImageTk
import subprocess
import threading


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

        # Standardmäßig KEINE Dateien ausgewählt (User muss explizit auswählen)
        # self.selected_paths bleibt leer

        # Thumbnail-Cache
        self.thumbnail_cache = {}  # path -> PhotoImage

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
        self.thumbnail_queue = []  # Queue von (file_info, thumb_label) Paaren
        self.is_loading_thumbnails = False
        self.loading_cancelled = False

        # Mousewheel-Scrolling Callback (wird von switch_to_thumbnails gesetzt)
        self.mousewheel_callback = None

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

        # Initial Thumbnail-Ansicht laden
        self.switch_to_thumbnails()

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
        tk.Button(button_frame, text="⬇ Ausgewählte importieren",
                 command=self.on_import_selected,
                 bg="#4CAF50", fg="white",
                 font=("Arial", 10, "bold"),
                 width=25,
                 padx=10, pady=6,
                 relief='raised', bd=2,
                 cursor='hand2').pack(side='right', padx=2)

    def switch_to_thumbnails(self):
        """Wechselt zur Thumbnail-Ansicht"""
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
        canvas.configure(yscrollcommand=scrollbar.set)

        # Speichere Canvas-Referenz (kein separates Overlay mehr)
        # Rectangle wird direkt auf Haupt-Canvas gezeichnet
        # Canvas-Items haben höhere Z-Order als create_window Widgets
        self.overlay_canvas = canvas  # Verwende Haupt-Canvas für Rectangle

        # Speichere Canvas-Referenz für Drag-Selection
        self.drag_canvas = canvas
        self.thumbnail_widgets = {}

        # Reset Thumbnail-Queue
        self.thumbnail_queue = []
        self.loading_cancelled = False

        # Canvas-Referenz für Scroll-Handler speichern
        self.current_canvas = canvas

        # Filtere und sortiere Dateien
        filtered_files = self.get_filtered_files()

        # Thumbnails in Grid anzeigen - SOFORT ohne auf Loading zu warten
        cols = 4
        for idx, file_info in enumerate(filtered_files):
            row = idx // cols
            col = idx % cols

            frame_widget = self.create_thumbnail_widget(scrollable_frame, file_info, row, col)

            # Speichere Widget und Position für Drag-Selection
            if frame_widget:
                # Warte bis Widget platziert ist
                scrollable_frame.update_idletasks()
                x = frame_widget.winfo_x()
                y = frame_widget.winfo_y()
                w = frame_widget.winfo_width()
                h = frame_widget.winfo_height()
                self.thumbnail_widgets[file_info['path']] = (frame_widget, (x, y, x+w, y+h))

        # Starte asynchrones Thumbnail-Loading
        self.start_thumbnail_loading()

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

                widget_x1, widget_y1, widget_x2, widget_y2 = bbox

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
            return "break"
        canvas.bind('<MouseWheel>', on_canvas_scroll)

        # Mausrad-Scrolling - nur für Canvas, nicht global!
        def _on_mousewheel(event):
            try:
                if canvas.winfo_exists():
                    canvas.yview_scroll(int(-1*(event.delta/120)), "units")
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

    def _on_tab_changed(self, event):
        """Handler für Tab-Wechsel"""
        selected_tab = self.notebook.index(self.notebook.select())
        if selected_tab == 0:
            self.switch_to_thumbnails()
        else:
            self.switch_to_details()

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
            # Sortiere nach Datei-Änderungsdatum
            import os
            files.sort(key=lambda f: os.path.getmtime(f['path']), reverse=reverse)

        return files

    def apply_filters(self):
        """Wendet Filter an und lädt Ansicht neu"""
        if self.view_mode == "thumbnail":
            self.switch_to_thumbnails()
        else:
            self.switch_to_details()

    def create_thumbnail_widget(self, parent, file_info, row, col):
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
            thumb_label.place(relx=0.5, rely=0.5, anchor='center')

            # Füge zur Thumbnail-Queue hinzu für asynchrones Laden
            # Speichere auch Click-Handler und Widgets für späteren Zugriff
            self.thumbnail_queue.append((file_info, thumb_label, thumb_frame, frame, on_click, on_double_click))

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

            widget_x1, widget_y1, widget_x2, widget_y2 = bbox

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
        """Generiert echtes Thumbnail für Datei"""
        path = file_info['path']

        # Prüfe Cache
        if path in self.thumbnail_cache:
            return self.thumbnail_cache[path]

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
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)

                    # Lade generiertes Bild
                    img = Image.open(tmp_path)
                    photo = ImageTk.PhotoImage(img)
                    self.thumbnail_cache[path] = photo

                    # Lösche temporäre Datei
                    import os
                    os.unlink(tmp_path)

                    return photo
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
                photo = ImageTk.PhotoImage(img)
                self.thumbnail_cache[path] = photo
                return photo
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
        self.view_mode = "details"

        # Lösche alte Ansicht
        for widget in self.view_container.winfo_children():
            widget.destroy()

        # Erstelle Detail-Ansicht
        tree_frame = tk.Frame(self.view_container)
        tree_frame.pack(fill='both', expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient='vertical')
        scrollbar.pack(side='right', fill='y')

        tree = ttk.Treeview(tree_frame,
                           columns=('select', 'filename', 'type', 'size', 'date', 'path'),
                           show='headings',
                           yscrollcommand=scrollbar.set)
        tree.pack(side='left', fill='both', expand=True)

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
        filtered_files = self.get_filtered_files()

        # Daten einfügen
        for file_info in filtered_files:
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
            import os
            import time
            try:
                mtime = os.path.getmtime(file_info['path'])
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

        # NEU: TreeviewSelect Event - Synchronisiere markierte_paths mit TreeView-Selection
        def on_tree_select(event):
            # Lösche alle Markierungen und setze neu basierend auf TreeView-Selection
            # WICHTIG: Nur nicht-ausgewählte Dateien können markiert werden

            # Hole alle aktuell selektierten Items im TreeView (blau markiert)
            selected_items = tree.selection()

            # Baue neue Markierungs-Liste auf
            new_markierte_paths = set()

            for item in selected_items:
                path = tree.item(item)['tags'][0]

                # Überspringe bereits ausgewählte Files (grün)
                if path not in self.selected_paths:
                    new_markierte_paths.add(path)

            # Update markierte_paths
            self.markierte_paths = new_markierte_paths

            # Update Tree-Symbole für ALLE Dateien
            for item in tree.get_children():
                path = tree.item(item)['tags'][0]
                values = list(tree.item(item)['values'])

                if path in self.selected_paths:
                    values[0] = '✅'  # Grün: Ausgewählt
                elif path in self.markierte_paths:
                    values[0] = '⬛'  # Schwarz: Markiert (blau selektiert)
                else:
                    values[0] = ''

                tree.item(item, values=values)

            self.update_mark_button()

        # Binde TreeviewSelect Event (feuert bei Shift+Ctrl+Click und normalen Clicks)
        tree.bind('<<TreeviewSelect>>', on_tree_select)

        # Doppelklick für Preview
        def on_double_click(event):
            item = tree.identify_row(event.y)
            if item:
                path = tree.item(item)['tags'][0]
                file_info = next(f for f in self.files_info if f['path'] == path)
                self.show_preview(file_info)

        tree.bind('<Double-Button-1>', on_double_click)

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

        # Stoppe Thumbnail-Loading
        self.loading_cancelled = True
        self.dialog.destroy()

    def on_cancel(self):
        """Bricht ab ohne Auswahl"""
        self.selected_files = None
        # Stoppe Thumbnail-Loading
        self.loading_cancelled = True
        self.dialog.destroy()

    def get_selected_files(self):
        """Gibt ausgewählte Dateien zurück (nach Dialog-Schließung)"""
        return self.selected_files

    def start_thumbnail_loading(self):
        """Startet asynchrones Laden der Thumbnails in einem Background-Thread"""
        if self.is_loading_thumbnails or not self.thumbnail_queue:
            return

        self.is_loading_thumbnails = True

        # Starte Thread für Thumbnail-Generierung
        thread = threading.Thread(target=self._load_thumbnails_worker, daemon=True)
        thread.start()

    def _load_thumbnails_worker(self):
        """Worker-Thread: Lädt Thumbnails nacheinander und aktualisiert UI"""
        while self.thumbnail_queue and not self.loading_cancelled:
            # Hole nächstes Item aus Queue
            file_info, thumb_label, thumb_frame, container_frame, on_click, on_double_click = self.thumbnail_queue.pop(0)

            # Generiere Thumbnail
            thumbnail_img = self.generate_thumbnail(file_info)

            # Aktualisiere UI im Haupt-Thread
            if thumbnail_img and not self.loading_cancelled:
                try:
                    self.dialog.after(0, self._update_thumbnail_ui, thumb_label, thumb_frame,
                                    thumbnail_img, on_click, on_double_click)
                except:
                    # Dialog wurde geschlossen
                    break
            elif not self.loading_cancelled:
                # Fallback wenn Thumbnail-Generierung fehlschlägt
                icon = "🎬" if file_info['is_video'] else "🖼️"
                try:
                    self.dialog.after(0, self._update_thumbnail_fallback, thumb_label, icon)
                except:
                    break

        self.is_loading_thumbnails = False

    def _update_thumbnail_ui(self, thumb_label, thumb_frame, thumbnail_img, on_click, on_double_click):
        """Aktualisiert Thumbnail im UI (läuft im Haupt-Thread)"""
        try:
            # Lösche alten Platzhalter
            thumb_label.destroy()

            # Erstelle neues Label mit Thumbnail
            new_label = tk.Label(thumb_frame, image=thumbnail_img, bg='#f0f0f0')
            new_label.image = thumbnail_img  # Referenz behalten
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
