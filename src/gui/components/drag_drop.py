import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import os
import subprocess


class DragDropFrame:
    def __init__(self, parent, app_instance):  # App-Instanz als Parameter
        self.parent = parent
        self.app = app_instance  # App-Instanz speichern
        self.frame = tk.Frame(parent, relief="sunken", borderwidth=2, padx=10, pady=10)
        self.video_paths = []
        self.create_widgets()

    def create_widgets(self):
        # Haupt-Label
        self.drop_label = tk.Label(self.frame,
                                   text="Mehrere .mp4 Dateien hierher ziehen (Reihenfolge wird beibehalten)",
                                   font=("Arial", 12))
        self.drop_label.pack(pady=10)

        # Tabelle für Vorschau der Videos
        self.create_preview_table()

        self.setup_drag_drop()

    def create_preview_table(self):
        # Frame für die Tabelle
        table_frame = tk.Frame(self.frame)
        table_frame.pack(fill="both", expand=True, padx=5, pady=5)

        # Scrollbar für die Tabelle
        scrollbar = ttk.Scrollbar(table_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Treeview als Tabelle
        self.tree = ttk.Treeview(
            table_frame,
            columns=("Nr", "Dateiname", "Dauer", "Größe"),
            show="headings",
            height=6,
            yscrollcommand=scrollbar.set
        )

        # Spalten konfigurieren
        self.tree.heading("Nr", text="#")
        self.tree.heading("Dateiname", text="Dateiname")
        self.tree.heading("Dauer", text="Dauer")
        self.tree.heading("Größe", text="Größe")

        self.tree.column("Nr", width=40, anchor="center")
        self.tree.column("Dateiname", width=200)
        self.tree.column("Dauer", width=80, anchor="center")
        self.tree.column("Größe", width=80, anchor="center")

        self.tree.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)

        # Buttons für Bearbeitung der Reihenfolge
        button_frame = tk.Frame(self.frame)
        button_frame.pack(pady=5)

        tk.Button(button_frame, text="Nach oben", command=self.move_up).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="Nach unten", command=self.move_down).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="Entfernen", command=self.remove_selected).pack(side=tk.LEFT, padx=2)
        tk.Button(button_frame, text="Alle löschen", command=self.clear_all).pack(side=tk.LEFT, padx=2)

    def setup_drag_drop(self):
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)

    def handle_drop(self, event):
        """Verarbeitet das Ablegen von Dateien"""
        filepaths = self._parse_dropped_files(event.data)
        valid_videos = []

        for filepath in filepaths:
            if os.path.isfile(filepath) and filepath.lower().endswith('.mp4'):
                valid_videos.append(filepath)
            else:
                messagebox.showwarning("Ungültige Datei",
                                       f"'{os.path.basename(filepath)}' ist keine gültige .mp4 Datei")

        if valid_videos:
            self.add_videos(valid_videos)
            self.drop_label.config(text=f"{len(valid_videos)} Video(s) hinzugefügt", fg="green")
        else:
            self.drop_label.config(text="Keine gültigen .mp4 Dateien gefunden", fg="red")

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

    def add_videos(self, new_videos):
        """Fügt neue Videos zur Liste hinzu und aktualisiert die Tabelle"""
        for video_path in new_videos:
            if video_path not in self.video_paths:
                self.video_paths.append(video_path)

        self._update_table()
        # Vorschau über App-Instanz aktualisieren
        if hasattr(self.app, 'update_video_preview'):
            self.app.update_video_preview(self.video_paths)

    def _update_table(self):
        """Aktualisiert die Vorschautabelle"""
        for item in self.tree.get_children():
            self.tree.delete(item)

        for i, video_path in enumerate(self.video_paths, 1):
            filename = os.path.basename(video_path)
            duration = self._get_video_duration(video_path)
            size = self._get_file_size(video_path)

            self.tree.insert("", "end", values=(i, filename, duration, size))

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

    def _get_file_size(self, video_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(video_path)
            if size_bytes > 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / 1024:.1f} KB"
        except:
            return "Unbekannt"

    def move_up(self):
        """Bewegt ausgewähltes Video nach oben"""
        selection = self.tree.selection()
        if selection:
            index = self.tree.index(selection[0])
            if index > 0:
                self.video_paths[index], self.video_paths[index - 1] = self.video_paths[index - 1], self.video_paths[
                    index]
                self._update_table()
                self.tree.selection_set(self.tree.get_children()[index - 1])
                # Vorschau aktualisieren
                if hasattr(self.app, 'update_video_preview'):
                    self.app.update_video_preview(self.video_paths)

    def move_down(self):
        """Bewegt ausgewähltes Video nach unten"""
        selection = self.tree.selection()
        if selection:
            index = self.tree.index(selection[0])
            if index < len(self.video_paths) - 1:
                self.video_paths[index], self.video_paths[index + 1] = self.video_paths[index + 1], self.video_paths[
                    index]
                self._update_table()
                self.tree.selection_set(self.tree.get_children()[index + 1])
                # Vorschau aktualisieren
                if hasattr(self.app, 'update_video_preview'):
                    self.app.update_video_preview(self.video_paths)

    def remove_selected(self):
        """Entfernt ausgewähltes Video"""
        selection = self.tree.selection()
        if selection:
            index = self.tree.index(selection[0])
            self.video_paths.pop(index)
            self._update_table()
            # Vorschau aktualisieren
            if hasattr(self.app, 'update_video_preview'):
                self.app.update_video_preview(self.video_paths)

    def clear_all(self):
        """Entfernt alle Videos"""
        self.video_paths.clear()
        self._update_table()
        self.drop_label.config(text="Mehrere .mp4 Dateien hierher ziehen (Reihenfolge wird beibehalten)", fg="black")
        # Vorschau zurücksetzen
        if hasattr(self.app, 'update_video_preview'):
            self.app.update_video_preview([])

    def get_video_paths(self):
        """Gibt die Liste der Video-Pfade zurück"""
        return self.video_paths.copy()

    def has_videos(self):
        """Prüft ob Videos vorhanden sind"""
        return len(self.video_paths) > 0

    def reset(self):
        """Setzt die Komponente zurück"""
        self.clear_all()

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)