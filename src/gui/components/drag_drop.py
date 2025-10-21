import platform
import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import os
import subprocess
import shutil
import time


class DragDropFrame:
    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent, relief="sunken", borderwidth=2, padx=10, pady=10)
        self.video_paths = []
        self.photo_paths = []
        self.create_widgets()

    def create_widgets(self):
        # Haupt-Label
        self.drop_label = tk.Label(self.frame,
                                   text="Videos (.mp4) und Fotos (.jpg, .png) hierher ziehen",
                                   font=("Arial", 12))
        self.drop_label.pack(pady=10)

        # Notebook (Tabs) erstellen
        self.notebook = ttk.Notebook(self.frame)
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
            columns=("Nr", "Dateiname", "Dauer", "Größe", "Datum", "Uhrzeit"),
            show="headings",
            height=6,
            yscrollcommand=video_scrollbar.set
        )

        # Spalten konfigurieren für Videos
        self.video_tree.heading("Nr", text="#")
        self.video_tree.heading("Dateiname", text="Dateiname")
        self.video_tree.heading("Dauer", text="Dauer")
        self.video_tree.heading("Größe", text="Größe")
        self.video_tree.heading("Datum", text="Datum")
        self.video_tree.heading("Uhrzeit", text="Uhrzeit")

        self.video_tree.column("Nr", width=10, anchor="center")
        self.video_tree.column("Dateiname", width=200)
        self.video_tree.column("Dauer", width=80, anchor="center")
        self.video_tree.column("Größe", width=80, anchor="center")
        self.video_tree.column("Datum", width=80, anchor="center")
        self.video_tree.column("Uhrzeit", width=80, anchor="center")

        self.video_tree.pack(side=tk.LEFT, fill="both", expand=True)
        video_scrollbar.config(command=self.video_tree.yview)

        # Doppelklick-Event für Videos
        self.video_tree.bind("<Double-1>", self._on_video_double_click)

        # Steuerungs-Buttons für Videos
        video_button_frame = tk.Frame(self.video_tab)
        video_button_frame.pack(pady=5)

        tk.Button(video_button_frame, text="Nach oben", command=self.move_video_up).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="Nach unten", command=self.move_video_down).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="Entfernen", command=self.remove_selected_video).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="Alle Videos löschen", command=self.clear_videos).pack(side=tk.LEFT, padx=2)

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
            columns=("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit"),
            show="headings",
            height=6,
            yscrollcommand=photo_scrollbar.set
        )

        # Spalten konfigurieren für Fotos
        self.photo_tree.heading("Nr", text="#")
        self.photo_tree.heading("Dateiname", text="Dateiname")
        self.photo_tree.heading("Größe", text="Größe")
        self.photo_tree.heading("Datum", text="Datum")
        self.photo_tree.heading("Uhrzeit", text="Uhrzeit")

        self.photo_tree.column("Nr", width=10, anchor="center")
        self.photo_tree.column("Dateiname", width=250)
        self.photo_tree.column("Größe", width=100, anchor="center")
        self.photo_tree.column("Datum", width=100, anchor="center")
        self.photo_tree.column("Uhrzeit", width=100, anchor="center")

        self.photo_tree.pack(side=tk.LEFT, fill="both", expand=True)
        photo_scrollbar.config(command=self.photo_tree.yview)

        # Doppelklick-Event für Fotos
        self.photo_tree.bind("<Double-1>", self._on_photo_double_click)

        # Steuerungs-Buttons für Fotos
        photo_button_frame = tk.Frame(self.photo_tab)
        photo_button_frame.pack(pady=5)

        tk.Button(photo_button_frame, text="Entfernen", command=self.remove_selected_photo).pack(side=tk.LEFT, padx=2)
        tk.Button(photo_button_frame, text="Alle Fotos löschen", command=self.clear_photos).pack(side=tk.LEFT, padx=2)

    def setup_drag_drop(self):
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        """Verarbeitet das Ablegen von Dateien (Videos und Fotos)"""
        filepaths = self._parse_dropped_files(event.data)
        valid_videos = []
        valid_photos = []

        for filepath in filepaths:
            if os.path.isfile(filepath):
                filename_lower = filepath.lower()
                if filename_lower.endswith('.mp4'):
                    valid_videos.append(filepath)
                elif filename_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp')):
                    valid_photos.append(filepath)
                else:
                    messagebox.showwarning("Ungültige Datei",
                                           f"'{os.path.basename(filepath)}' ist keine unterstützte Video- oder Foto-Datei")

        if valid_videos or valid_photos:
            self.add_files(valid_videos, valid_photos)
            video_count = len(valid_videos)
            photo_count = len(valid_photos)

            status_text = ""
            if video_count > 0:
                status_text += f"{video_count} Video(s)"
            if photo_count > 0:
                if status_text:
                    status_text += " und "
                status_text += f"{photo_count} Foto(s)"
            status_text += " hinzugefügt"

            self.drop_label.config(text=status_text, fg="green")
        else:
            self.drop_label.config(text="Keine gültigen Video- oder Foto-Dateien gefunden", fg="red")

    def _parse_dropped_files(self, data):
        """Parst die abgelegten Dateien"""
        filepaths = []
        clean_data = data.strip('{}')

        if ' ' in clean_data:
            potential_files = clean_data.split(' ')
            for filepath in potential_files:
                filepath = filepath.strip()
                if filepath and os.path.exists(filepath):
                    filepaths.append(filepath)
        else:
            if os.path.exists(clean_data):
                filepaths.append(clean_data)

        return filepaths

    def add_files(self, new_videos, new_photos):
        """Fügt neue Videos und Fotos hinzu und aktualisiert die Tabellen"""
        # Videos hinzufügen (ohne Duplikate)
        for video_path in new_videos:
            if video_path not in self.video_paths:
                self.video_paths.append(video_path)

        # Fotos hinzufügen (ohne Duplikate)
        for photo_path in new_photos:
            if photo_path not in self.photo_paths:
                self.photo_paths.append(photo_path)

        self._update_video_table()
        self._update_photo_table()

        # Vorschau nur mit Videos aktualisieren
        if hasattr(self.app, 'update_video_preview'):
            self.app.update_video_preview(self.video_paths)

    def _update_video_table(self):
        """Aktualisiert die Video-Tabelle"""
        for item in self.video_tree.get_children():
            self.video_tree.delete(item)

        for i, video_path in enumerate(self.video_paths, 1):
            filename = os.path.basename(video_path)
            duration = self._get_video_duration(video_path)
            size = self._get_file_size(video_path)
            date = self._get_file_date(video_path)
            timestamp = self._get_file_time(video_path)

            self.video_tree.insert("", "end", values=(i, filename, duration, size, date, timestamp))

    def _update_photo_table(self):
        """Aktualisiert die Foto-Tabelle"""
        for item in self.photo_tree.get_children():
            self.photo_tree.delete(item)

        for i, photo_path in enumerate(self.photo_paths, 1):
            filename = os.path.basename(photo_path)
            size = self._get_file_size(photo_path)
            date = self._get_file_date(photo_path)
            timestamp = self._get_file_time(photo_path)

            self.photo_tree.insert("", "end", values=(i, filename, size, date, timestamp))

    def _get_video_duration(self, video_path):
        """Ermittelt die Dauer des Videos"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ], capture_output=True, text=True, timeout=5)

            if result.returncode == 0:
                seconds = float(result.stdout.strip())
                minutes = int(seconds // 60)
                secs = int(seconds % 60)
                return f"{minutes}:{secs:02d}"
        except:
            pass

        return "?:??"

    def _get_file_size(self, file_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(file_path)
            if size_bytes > 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / 1024:.1f} KB"
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

    def move_video_up(self):
        """Bewegt ausgewähltes Video nach oben"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if index > 0:
                self.video_paths[index], self.video_paths[index - 1] = self.video_paths[index - 1], self.video_paths[
                    index]
                self._update_video_table()
                self.video_tree.selection_set(self.video_tree.get_children()[index - 1])
                # Vorschau aktualisieren
                if hasattr(self.app, 'update_video_preview'):
                    self.app.update_video_preview(self.video_paths)

    def move_video_down(self):
        """Bewegt ausgewähltes Video nach unten"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if index < len(self.video_paths) - 1:
                self.video_paths[index], self.video_paths[index + 1] = self.video_paths[index + 1], self.video_paths[
                    index]
                self._update_video_table()
                self.video_tree.selection_set(self.video_tree.get_children()[index + 1])
                # Vorschau aktualisieren
                if hasattr(self.app, 'update_video_preview'):
                    self.app.update_video_preview(self.video_paths)

    def remove_selected_video(self):
        """Entfernt ausgewähltes Video"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            self.video_paths.pop(index)
            self._update_video_table()
            # Vorschau aktualisieren
            if hasattr(self.app, 'update_video_preview'):
                self.app.update_video_preview(self.video_paths)

    def remove_selected_photo(self):
        """Entfernt ausgewähltes Foto"""
        selection = self.photo_tree.selection()
        if selection:
            index = self.photo_tree.index(selection[0])
            self.photo_paths.pop(index)
            self._update_photo_table()

    def clear_videos(self):
        """Entfernt alle Videos"""
        self.video_paths.clear()
        self._update_video_table()
        # Vorschau zurücksetzen
        if hasattr(self.app, 'update_video_preview'):
            self.app.update_video_preview([])

    def clear_photos(self):
        """Entfernt alle Fotos"""
        self.photo_paths.clear()
        self._update_photo_table()

    def clear_all(self):
        """Entfernt alle Videos und Fotos"""
        self.clear_videos()
        self.clear_photos()
        self.drop_label.config(text="Videos (.mp4) und Fotos (.jpg, .png) hierher ziehen", fg="black")

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

    def reset(self):
        """Setzt die Komponente zurück"""
        self.clear_all()

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    def _on_video_double_click(self, event):
        """Öffnet das ausgewählte Video beim Doppelklick"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if 0 <= index < len(self.video_paths):
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
                    subprocess.run(['open', file_path], check=True)
                else:  # Linux
                    subprocess.run(['xdg-open', file_path], check=True)
        except Exception as e:
            messagebox.showerror("Fehler", f"Datei konnte nicht geöffnet werden:\n{str(e)}")