import platform
import re
import tkinter as tk
from tkinter import ttk, messagebox
from tkinterdnd2 import DND_FILES
import os
import subprocess
import time

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class DragDropFrame:
    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance  # Wichtig: Referenz zur Haupt-App
        self.frame = tk.Frame(parent, relief="sunken", borderwidth=2, padx=10, pady=10)
        self.video_paths = []
        self.photo_paths = []
        self.last_first_video = None  # NEU: Speichert den ersten Clip für Vergleich

        # Lade QR-Check-Status aus Config (Standard: False)
        qr_check_initial = self.app.config.get_settings().get("qr_check_enabled", False)
        self.qr_check_enabled = tk.BooleanVar(value=qr_check_initial)  # NEU: Checkbox-Variable für QR-Prüfung

        self.watermark_clip_index = None  # NEU: Index des Clips für Wasserzeichen
        self.show_watermark_column = False  # NEU: Steuert Sichtbarkeit der Wasserzeichen-Spalte
        self.create_widgets()

    def create_widgets(self):
        # Oberer Frame für Label und Checkbox in einer Reihe
        top_frame = tk.Frame(self.frame)
        top_frame.pack(pady=10, fill="x")

        # Checkbox für QR-Code-Prüfung (rechts)
        self.qr_check_checkbox = tk.Checkbutton(
            top_frame,
            text="Auf QR-Code im ersten Clip prüfen",
            variable=self.qr_check_enabled,
            command=self._on_qr_checkbox_toggled,  # Führe QR-Prüfung aus beim Anklicken
            font=("Arial", 10)
        )
        self.qr_check_checkbox.pack(side=tk.RIGHT)

        # Haupt-Label (links)
        self.drop_label = tk.Label(top_frame,
                                   text="Videos (.mp4) und Fotos (.jpg, .png) hierher ziehen",
                                   font=("Arial", 12))
        self.drop_label.pack(side=tk.LEFT)

        # Notebook (Tabs) erstellen mit größerem Style
        style = ttk.Style()
        style.configure('Large.TNotebook.Tab',
                       font=('Arial', 8, 'bold'),
                       padding=[20, 5])  # [horizontal, vertical] padding

        self.notebook = ttk.Notebook(self.frame, style='Large.TNotebook')
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
            columns=("Nr", "Dateiname", "Format", "Dauer", "Größe", "Datum", "Uhrzeit", "WM"),
            show="headings",
            height=6,
            yscrollcommand=video_scrollbar.set
        )

        # Spalten konfigurieren für Videos
        self.video_tree.heading("Nr", text="#")
        self.video_tree.heading("Dateiname", text="Dateiname")
        self.video_tree.heading("Format", text="Format")
        self.video_tree.heading("Dauer", text="Dauer")
        self.video_tree.heading("Größe", text="Größe")
        self.video_tree.heading("Datum", text="Datum")
        self.video_tree.heading("Uhrzeit", text="Uhrzeit")
        self.video_tree.heading("WM", text="💧")

        self.video_tree.column("Nr", width=10, anchor="center")
        self.video_tree.column("Dateiname", width=180)
        self.video_tree.column("Format", width=70, anchor="center")
        self.video_tree.column("Dauer", width=50, anchor="center")
        self.video_tree.column("Größe", width=70, anchor="center")
        self.video_tree.column("Datum", width=80, anchor="center")
        self.video_tree.column("Uhrzeit", width=70, anchor="center")
        self.video_tree.column("WM", width=0, minwidth=0, stretch=False, anchor="center")  # Startet versteckt

        self.video_tree.pack(side=tk.LEFT, fill="both", expand=True)
        video_scrollbar.config(command=self.video_tree.yview)

        # Doppelklick-Event für Videos
        self.video_tree.bind("<Double-1>", self._on_video_double_click)

        # NEU: Event für Checkbox-Klicks in der Wasserzeichen-Spalte (auf Release um Doppelklicks zu vermeiden)
        self.video_tree.bind("<ButtonRelease-1>", self._on_watermark_checkbox_click)

        # Drag & Drop für Video-Tabelle
        self.video_tree.drop_target_register(DND_FILES)
        self.video_tree.dnd_bind('<<Drop>>', self._handle_video_table_drop)

        # Steuerungs-Buttons für Videos
        video_button_frame = tk.Frame(self.video_tab)
        video_button_frame.pack(pady=5)

        tk.Button(video_button_frame, text="▲ Nach oben", command=self.move_video_up).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="▼ Nach unten", command=self.move_video_down).pack(side=tk.LEFT, padx=2)

        # NEU: Button zum Schneiden
        self.cut_button = tk.Button(video_button_frame, text="✂ Schneiden", command=self.open_cut_dialog)
        self.cut_button.pack(side=tk.LEFT, padx=5)

        tk.Button(video_button_frame, text="✕ Entfernen", command=self.remove_selected_video).pack(side=tk.LEFT, padx=2)
        tk.Button(video_button_frame, text="🗑 Alle Videos löschen", command=self.clear_videos).pack(side=tk.LEFT, padx=2)

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

        # Drag & Drop für Foto-Tabelle
        self.photo_tree.drop_target_register(DND_FILES)
        self.photo_tree.dnd_bind('<<Drop>>', self._handle_photo_table_drop)

        # Steuerungs-Buttons für Fotos
        photo_button_frame = tk.Frame(self.photo_tab)
        photo_button_frame.pack(pady=5)

        tk.Button(photo_button_frame, text="✕ Entfernen", command=self.remove_selected_photo).pack(side=tk.LEFT, padx=2)
        tk.Button(photo_button_frame, text="🗑 Alle Fotos löschen", command=self.clear_photos).pack(side=tk.LEFT, padx=2)

    def setup_drag_drop(self):
        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind('<<Drop>>', self.handle_drop)
        self.frame.drop_target_register(DND_FILES)
        self.frame.dnd_bind('<<Drop>>', self.handle_drop)

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
            # Prüfe Video-Formate wenn mehrere Videos hinzugefügt werden
            needs_reencoding_info = None
            if len(valid_videos) > 0 and len(self.video_paths) + len(valid_videos) > 1:
                needs_reencoding_info = self._check_if_reencoding_needed(valid_videos)

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

            # Info: Re-Encoding-Info wird in der Konsole ausgegeben
            if needs_reencoding_info and not needs_reencoding_info["compatible"]:
                print(f"Videos mit unterschiedlichen Formaten erkannt: {needs_reencoding_info['details']}")
                print("Die Vorschau-Erstellung kann länger dauern, da die Videos neu kodiert werden müssen.")
        else:
            self.drop_label.config(text="Keine gültigen Video- oder Foto-Dateien gefunden", fg="red")

    def _check_if_reencoding_needed(self, new_videos):
        """Prüft ob Re-Encoding für die neuen Videos nötig ist"""
        try:
            # Kombiniere vorhandene und neue Videos für die Prüfung
            all_videos = self.video_paths + new_videos

            if len(all_videos) <= 1:
                return {"compatible": True, "details": "Nur ein Video"}

            # Verwende ffprobe um Video-Informationen zu sammeln
            formats = []
            for video_path in all_videos:
                try:
                    result = subprocess.run([
                        'ffprobe', '-v', 'quiet',
                        '-print_format', 'json',
                        '-show_streams',
                        video_path
                    ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                    if result.returncode == 0:
                        import json
                        info = json.loads(result.stdout)

                        # Finde Video-Stream
                        video_stream = None
                        for stream in info.get('streams', []):
                            if stream.get('codec_type') == 'video':
                                video_stream = stream
                                break

                        if video_stream:
                            format_info = {
                                'filename': os.path.basename(video_path),
                                'codec_name': video_stream.get('codec_name', 'unknown'),
                                'width': video_stream.get('width', 0),
                                'height': video_stream.get('height', 0),
                                'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                            }
                            formats.append(format_info)
                        else:
                            formats.append({'filename': os.path.basename(video_path), 'error': 'No video stream'})
                    else:
                        formats.append({'filename': os.path.basename(video_path), 'error': 'FFprobe failed'})

                except Exception as e:
                    formats.append({'filename': os.path.basename(video_path), 'error': str(e)})

            # Vergleiche alle Formate
            first_format = formats[0]
            compatible = True
            differences = []

            for i, fmt in enumerate(formats[1:], 1):
                if 'error' in fmt:
                    compatible = False
                    differences.append(f"{fmt['filename']}: {fmt['error']}")
                    continue

                # Prüfe Codec
                if fmt.get('codec_name') != first_format.get('codec_name'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: Codec {fmt['codec_name']}")

                # Prüfe Auflösung
                if fmt.get('width') != first_format.get('width') or fmt.get('height') != first_format.get('height'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: {fmt['width']}x{fmt['height']}")

                # Prüfe Framerate (vereinfacht)
                if fmt.get('r_frame_rate') != first_format.get('r_frame_rate'):
                    compatible = False
                    differences.append(f"{fmt['filename']}: FPS {fmt['r_frame_rate']}")

            if compatible:
                details = f"Alle {len(all_videos)} Videos kompatibel"
            else:
                # Zeige nur die ersten 3 Unterschiede um die Meldung übersichtlich zu halten
                diff_display = "\n".join(differences[:3])
                if len(differences) > 3:
                    diff_display += f"\n... und {len(differences) - 3} weitere"
                details = f"Format-Unterschiede:\n{diff_display}"

            return {
                "compatible": compatible,
                "details": details,
                "formats": formats
            }

        except Exception as e:
            # Im Fehlerfall gehen wir davon aus dass Re-Encoding nötig ist
            return {
                "compatible": False,
                "details": f"Fehler bei Format-Prüfung: {str(e)}"
            }

    def _parse_dropped_files(self, data_string):
        """Verarbeitet die Zeichenkette eines Drop-Events in eine Liste von Dateipfaden."""
        # Diese Methode ist für den Aufruf durch einen Drag-and-Drop-Handler vorgesehen.
        # Tkinter unter Windows liefert eine Tcl-formatierte Liste, bei der Pfade
        # mit Leerzeichen in {} eingeschlossen sind.
        # Beispiel: '{C:/Benutzer/Test User/vid 1.mp4}' C:/normaler/pfad/vid2.mp4

        # Verwendung von Regex, um entweder in geschweiften Klammern stehende Inhalte oder Zeichenketten ohne Leerzeichen zu finden
        path_candidates = re.findall(r'\{[^{}]*\}|[^ ]+', data_string)

        cleaned_paths = []
        for path in path_candidates:
            # Entfernt die geschweiften Klammern, falls vorhanden
            if path.startswith('{') and path.endswith('}'):
                cleaned_paths.append(path[1:-1])
            else:
                cleaned_paths.append(path)

        return cleaned_paths

    def add_files(self, new_videos, new_photos):
        """Fügt neue Videos und Fotos hinzu und aktualisiert die Tabellen"""
        new_videos_added = False
        new_photos_added = False

        # Videos hinzufügen (ohne Duplikate)
        for video_path in new_videos:
            if video_path not in self.video_paths:
                self.video_paths.append(video_path)
                new_videos_added = True

        # Fotos hinzufügen (ohne Duplikate)
        for photo_path in new_photos:
            if photo_path not in self.photo_paths:
                self.photo_paths.append(photo_path)
                new_photos_added = True

        self._update_video_table()
        self._update_photo_table()

        # Vorschau nur mit Videos aktualisieren
        if new_videos_added:
            self._update_app_preview()

        # App über *alle* neuen Dateien benachrichtigen
        if new_videos_added or new_photos_added:
            if hasattr(self.app, 'on_files_added'):
                self.app.on_files_added(new_videos_added, new_photos_added)

    def _update_app_preview(self, video_paths=None):
        """
        Fordert eine Aktualisierung der Vorschau über die Hauptanwendung an.
        NEU: QR-Prüfung wird nur ausgelöst, wenn sich der erste Clip ändert UND die Checkbox aktiviert ist.
        """
        paths = self.video_paths.copy() if video_paths is None else video_paths.copy()

        # NEU: Prüfe, ob sich der erste Clip geändert hat
        current_first_video = paths[0] if paths else None
        first_video_changed = (current_first_video != self.last_first_video)

        # Aktualisiere die gespeicherte Referenz
        self.last_first_video = current_first_video

        # NEU: QR-Prüfung nur wenn Checkbox aktiviert ist UND sich der erste Clip geändert hat
        run_qr_check = self.qr_check_enabled.get() and first_video_changed

        if hasattr(self.app, 'update_video_preview'):
            # NEU: Übergebe Information, ob QR-Prüfung nötig ist
            self.app.update_video_preview(paths, run_qr_check=run_qr_check)

    def _on_qr_checkbox_toggled(self):
        """
        Wird aufgerufen, wenn die QR-Code-Checkbox angeklickt wird.
        Führt die QR-Prüfung sofort aus, wenn die Checkbox aktiviert wird.
        Speichert den Status in der Config.
        """
        # Speichere den neuen Status in der Config
        qr_check_status = self.qr_check_enabled.get()
        settings = self.app.config.get_settings()
        settings["qr_check_enabled"] = qr_check_status
        self.app.config.save_settings(settings)

        # Nur wenn Checkbox jetzt aktiviert ist UND Videos vorhanden sind
        if qr_check_status and self.video_paths:
            print("QR-Code-Prüfung wurde aktiviert - führe Prüfung durch...")
            # Trigger Vorschau-Update mit erzwungener QR-Prüfung
            if hasattr(self.app, 'run_qr_analysis'):
                self.app.run_qr_analysis(self.video_paths.copy())
        elif not qr_check_status:
            print("QR-Code-Prüfung wurde deaktiviert")

    def _update_video_table(self):
        """
        Aktualisiert die Video-Tabelle.
        NEU: Liest Metadaten aus dem Cache von video_preview, wenn dieser aktiv ist.
        """
        for item in self.video_tree.get_children():
            self.video_tree.delete(item)

        for i, original_path in enumerate(self.video_paths, 1):
            filename = os.path.basename(original_path)

            # Standard-Werte
            duration, size, date, timestamp, format_str = "--:--", "-- MB", "--.--.----", "--:--:--", "---"

            if self.app and hasattr(self.app, 'video_preview'):
                # Prüfen, ob die Vorschau-Sitzung (temp_dir) überhaupt schon läuft
                preview_session_active = self.app.video_preview.temp_dir is not None
                # Versuchen, Metadaten aus dem Cache zu holen
                metadata = self.app.video_preview.get_cached_metadata(original_path)

                if metadata:
                    # Fall 1: Wir haben Metadaten im Cache. Benutze sie.
                    duration = metadata.get("duration", "--:--")
                    size = metadata.get("size", "-- MB")
                    date = metadata.get("date", "--.--.----")
                    timestamp = metadata.get("timestamp", "--:--:--")
                    format_str = metadata.get("format", "---")

                elif preview_session_active:
                    # Fall 2: Vorschau ist aktiv, aber *keine* Metadaten für diesen Clip.
                    # Das bedeutet, der Clip wird gerade kopiert/erstellt.
                    filename = f"[LÄDT...] {filename}"

                else:
                    # Fall 3: Vorschau ist NICHT aktiv (z.B. beim ersten Hinzufügen).
                    # Hier ist es OK, die langsamen Fallback-Methoden zu nutzen,
                    # die ffprobe synchron aufrufen.
                    duration = self._get_video_duration_fallback(original_path)
                    size = self._get_file_size_fallback(original_path)
                    date = self._get_file_date_fallback(original_path)
                    timestamp = self._get_file_time_fallback(original_path)
                    format_str = self._get_video_format_fallback(original_path)

            else:
                # Fallback, falls self.app nicht existiert (sollte nicht passieren)
                duration = self._get_video_duration_fallback(original_path)
                size = self._get_file_size_fallback(original_path)
                date = self._get_file_date_fallback(original_path)
                timestamp = self._get_file_time_fallback(original_path)
                format_str = self._get_video_format_fallback(original_path)

            # NEU: Wasserzeichen-Spalte
            watermark_value = "☑" if i - 1 == self.watermark_clip_index else "☐"

            self.video_tree.insert("", "end", values=(i, filename, format_str, duration, size, date, timestamp, watermark_value))

    def _update_photo_table(self):
        """Aktualisiert die Foto-Tabelle"""
        for item in self.photo_tree.get_children():
            self.photo_tree.delete(item)

        for i, photo_path in enumerate(self.photo_paths, 1):
            filename = os.path.basename(photo_path)
            size = self._get_file_size_fallback(photo_path)  # Fotos verwenden immer Fallback
            date = self._get_file_date_fallback(photo_path)
            timestamp = self._get_file_time_fallback(photo_path)

            self.photo_tree.insert("", "end", values=(i, filename, size, date, timestamp))

    # --- NEU: Fallback-Methoden für Metadaten (sync ffprobe) ---
    # (Dies sind die alten Methoden, umbenannt)

    def _get_video_duration_fallback(self, video_path):
        """Ermittelt die Dauer des Videos (Blockierend)"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode == 0:
                seconds = float(result.stdout.strip())
                minutes = int(seconds // 60)
                secs = int(seconds % 60)
                return f"{minutes}:{secs:02d}"
        except:
            pass
        return "?:??"

    def _get_file_size_fallback(self, file_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(file_path)
            if size_bytes > 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / 1024:.1f} KB"
        except:
            return "Unbekannt"

    def _get_file_date_fallback(self, video_path):
        """Ermittelt das Erstellungsdatum der Datei"""
        try:
            modification_time = os.path.getmtime(video_path)
            return time.strftime("%d.%m.%Y", time.localtime(modification_time))
        except:
            return "Unbekannt"

    def _get_file_time_fallback(self, video_path):
        """Ermittelt die Erstellungsuhrzeit der Datei"""
        try:
            modification_time = os.path.getmtime(video_path)
            return time.strftime("%H:%M:%S", time.localtime(modification_time))
        except:
            return "Unbekannt"

    def _get_video_format_fallback(self, video_path):
        """Ermittelt das Video-Format (Auflösung und FPS) mit ffprobe"""
        try:
            import json
            result = subprocess.run([
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_streams', '-select_streams', 'v:0',
                video_path
            ], capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode == 0:
                data = json.loads(result.stdout)
                if 'streams' in data and len(data['streams']) > 0:
                    stream = data['streams'][0]
                    width = stream.get('width', 0)
                    height = stream.get('height', 0)

                    # FPS berechnen
                    fps_str = stream.get('r_frame_rate', '0/0')
                    try:
                        num, denom = map(int, fps_str.split('/'))
                        fps = round(num / denom) if denom != 0 else 0
                    except:
                        fps = 0

                    # Format-String erstellen (z.B. "1080p@30")
                    if height > 0:
                        format_label = f"{height}p"
                        if fps > 0:
                            format_label += f"@{fps}"
                        return format_label

            return "---"
        except:
            return "---"

    # --- ENDE Fallback-Methoden ---

    # --- NEUE METHODEN (von app.py aufgerufen) ---
    def refresh_table(self):
        """Erzwingt ein Neuzeichnen der Video-Tabelle mit aktuellen Metadaten."""
        print("DragDrop: Aktualisiere Tabelle nach Schnitt...")
        self._update_video_table()

    def insert_video_path_at_index(self, original_path: str, index: int):
        """Fügt einen neuen (Platzhalter-)Pfad an einem bestimmten Index ein (z.B. nach Split)."""
        if 0 <= index <= len(self.video_paths):
            self.video_paths.insert(index, original_path)
            print(f"DragDrop: Füge geteilten Clip an Index {index} ein.")
        else:
            self.video_paths.append(original_path)
            print(f"DragDrop: Füge geteilten Clip am Ende an (Index {index} ungültig).")

        # Tabelle neu zeichnen (noch ohne Metadaten, die kommen asynchron)
        self._update_video_table()

    # --- ENDE NEUE METHODEN ---

    def move_video_up(self):
        """Bewegt ausgewähltes Video nach oben"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if index > 0:
                self.video_paths[index], self.video_paths[index - 1] = self.video_paths[index - 1], self.video_paths[
                    index]

                # NEU: Aktualisiere Wasserzeichen-Index
                if self.watermark_clip_index == index:
                    self.watermark_clip_index = index - 1
                elif self.watermark_clip_index == index - 1:
                    self.watermark_clip_index = index

                self._update_video_table()
                self.video_tree.selection_set(self.video_tree.get_children()[index - 1])
                # Vorschau aktualisieren
                self._update_app_preview()

    def move_video_down(self):
        """Bewegt ausgewähltes Video nach unten"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if index < len(self.video_paths) - 1:
                self.video_paths[index], self.video_paths[index + 1] = self.video_paths[index + 1], self.video_paths[
                    index]

                # NEU: Aktualisiere Wasserzeichen-Index
                if self.watermark_clip_index == index:
                    self.watermark_clip_index = index + 1
                elif self.watermark_clip_index == index + 1:
                    self.watermark_clip_index = index

                self._update_video_table()
                self.video_tree.selection_set(self.video_tree.get_children()[index + 1])
                # Vorschau aktualisieren
                self._update_app_preview()

    def remove_selected_video(self):
        """Entfernt ausgewähltes Video"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])

            # NEU: Entferne auch aus dem Cache
            original_path = self.video_paths.pop(index)
            if self.app and hasattr(self.app, 'video_preview'):
                self.app.video_preview.remove_path_from_cache(original_path)

            # NEU: Aktualisiere Wasserzeichen-Index
            if self.watermark_clip_index == index:
                self.watermark_clip_index = None
            elif self.watermark_clip_index is not None and self.watermark_clip_index > index:
                self.watermark_clip_index -= 1

            self._update_video_table()
            # Vorschau aktualisieren
            self._update_app_preview()

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

        # NEU: Löschen Sie auch die Wasserzeichen-Auswahl
        self.watermark_clip_index = None

        # NEU: Cache leeren
        if self.app and hasattr(self.app, 'video_preview'):
            self.app.video_preview.clear_metadata_cache()

        self._update_video_table()
        # Vorschau zurücksetzen
        self._update_app_preview([])

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

    def open_cut_dialog(self):
        """Ruft den Schneide-Dialog in der Haupt-App auf."""
        selection = self.video_tree.selection()
        if not selection:
            messagebox.showwarning("Keine Auswahl",
                                   "Bitte wählen Sie zuerst ein Video aus der Tabelle aus, das Sie schneiden möchten.")
            return

        if not self.app or not hasattr(self.app, 'request_cut_dialog'):
            messagebox.showerror("Fehler", "Die Hauptanwendung ist nicht korrekt für das Schneiden konfiguriert.")
            return

        index = self.video_tree.index(selection[0])
        original_path = self.video_paths[index]

        # Rufe die Methode in app.py auf
        self.app.request_cut_dialog(original_path)

    def set_cut_button_enabled(self, enabled: bool):
        """Sperrt/Entsperrt den Schneiden-Button basierend auf Vorschau-Status."""
        if hasattr(self, 'cut_button'):
            self.cut_button.config(state="normal" if enabled else "disabled")
            if enabled:
                self.cut_button.config(text="✂ Schneiden", fg="black")
            else:
                self.cut_button.config(text="✂ Schneiden (Vorschau wird erstellt...)", fg="gray")

    def _on_video_double_click(self, event):
        """Öffnet das ausgewählte Video beim Doppelklick"""
        selection = self.video_tree.selection()
        if selection:
            index = self.video_tree.index(selection[0])
            if 0 <= index < len(self.video_paths):
                # NEU: Versuche, die Kopie zu öffnen, falle zurück auf Original
                video_path = self.video_paths[index]
                if self.app and hasattr(self.app, 'video_preview'):
                    copy_path = self.app.video_preview.get_copy_path(video_path)
                    if copy_path and os.path.exists(copy_path):
                        video_path = copy_path

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
                    subprocess.run(['open', file_path], check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:  # Linux
                    subprocess.run(['xdg-open', file_path], check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except Exception as e:
            messagebox.showerror("Fehler", f"Datei konnte nicht geöffnet werden:\n{str(e)}")

    def _handle_video_table_drop(self, event):
        """Verarbeitet das Ablegen von Dateien in die Video-Tabelle"""
        self.handle_drop(event)
        # Wechsle zum Video-Tab nach dem Drop
        self.notebook.select(0)

    def _handle_photo_table_drop(self, event):
        """Verarbeitet das Ablegen von Dateien in die Foto-Tabelle"""
        self.handle_drop(event)
        # Wechsle zum Foto-Tab nach dem Drop
        self.notebook.select(1)

    # NEU: Methoden für Wasserzeichen-Spalte
    def set_watermark_column_visible(self, visible: bool):
        """Zeigt oder verbirgt die Wasserzeichen-Spalte"""
        self.show_watermark_column = visible
        if visible:
            self.video_tree.column("WM", width=20, minwidth=30, stretch=False)
        else:
            self.video_tree.column("WM", width=0, minwidth=0, stretch=False)

        # Aktualisiere die Tabelle, um die Änderungen sofort zu reflektieren
        self.video_tree.update_idletasks()

    def get_watermark_clip_index(self):
        """Gibt den Index des für Wasserzeichen ausgewählten Clips zurück (oder None)"""
        return self.watermark_clip_index

    def set_watermark_clip_index(self, index):
        """Setzt den Index des für Wasserzeichen ausgewählten Clips"""
        self.watermark_clip_index = index
        self._update_video_table()

    def clear_watermark_selection(self):
        """Löscht die Wasserzeichen-Auswahl"""
        self.watermark_clip_index = None
        self._update_video_table()

    def _on_watermark_checkbox_click(self, event):
        """Verarbeitet Klicks auf die Wasserzeichen-Spalte"""
        if not self.show_watermark_column or not self.video_paths:
            return

        # Finde die angeklickte Spalte
        region = self.video_tree.identify_region(event.x, event.y)
        if region != "cell":
            return

        column = self.video_tree.identify_column(event.x)
        # Spalte 8 ist die Wasserzeichen-Spalte (0-indiziert: 7, aber +1 für tree_id)
        # Spalten: tree_id (#0), Nr, Dateiname, Format, Dauer, Größe, Datum, Uhrzeit, Wasserzeichen
        # Index:    0        1     2           3       4      5      6      7        8

        if column != "#8":
            return

        # Finde die Reihe
        item = self.video_tree.identify_row(event.y)
        if not item:
            return

        index = self.video_tree.index(item)

        # Toggle: Wenn bereits ausgewählt, deselektiere; sonst selektiere diese Reihe
        if self.watermark_clip_index == index:
            self.watermark_clip_index = None
        else:
            self.watermark_clip_index = index

        self._update_video_table()

        # Verhindere, dass die Reihe ausgewählt wird
        self.video_tree.selection_remove(self.video_tree.selection())

