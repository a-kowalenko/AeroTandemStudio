import tkinter as tk
from tkinter import ttk
import os
import tempfile
import subprocess
import threading


class VideoPreview:
    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent)
        self.combined_video_path = None
        self.is_playing = False
        self.create_widgets()

    def create_widgets(self):
        # Titel
        title_label = tk.Label(self.frame, text="Video Vorschau", font=("Arial", 14, "bold"))
        title_label.pack(pady=5)

        # Separator
        ttk.Separator(self.frame, orient='horizontal').pack(fill='x', pady=5)

        # Video-Info Frame
        info_frame = tk.Frame(self.frame)
        info_frame.pack(fill="x", pady=5)

        self.duration_label = tk.Label(info_frame, text="Gesamtdauer: --:--", font=("Arial", 10))
        self.duration_label.pack(anchor="w")

        self.size_label = tk.Label(info_frame, text="Dateigröße: --", font=("Arial", 10))
        self.size_label.pack(anchor="w")

        # Anzahl der Clips
        self.clips_label = tk.Label(info_frame, text="Anzahl Clips: 0", font=("Arial", 10))
        self.clips_label.pack(anchor="w")

        # Steuerungs-Buttons
        control_frame = tk.Frame(self.frame)
        control_frame.pack(pady=10)

        self.play_button = tk.Button(control_frame, text="▶ Vorschau abspielen",
                                     command=self.play_preview, state="disabled",
                                     font=("Arial", 11), width=15, height=1)
        self.play_button.pack(pady=2)

        self.stop_button = tk.Button(control_frame, text="⏹ Abbrechen",
                                     command=self.stop_preview, state="disabled",
                                     font=("Arial", 11), width=15, height=1)
        self.stop_button.pack(pady=2)

        # Status-Label
        self.status_label = tk.Label(self.frame, text="Ziehen Sie Videos in das Feld links",
                                     font=("Arial", 10), fg="gray", wraplength=300)
        self.status_label.pack(pady=5)

    def update_preview(self, video_paths):
        """Erstellt eine Vorschau aus allen Videos und aktualisiert die UI"""
        if not video_paths:
            self.clear_preview()
            return

        self.status_label.config(text="Erstelle Vorschau...", fg="blue")
        self.play_button.config(state="disabled")
        self.clips_label.config(text=f"Anzahl Clips: {len(video_paths)}")

        # Im Thread verarbeiten um UI nicht zu blockieren
        thread = threading.Thread(target=self._create_combined_preview, args=(video_paths,))
        thread.start()

    def _create_combined_preview(self, video_paths):
        """Erstellt ein kombiniertes Vorschau-Video aus allen Clips"""
        try:
            # Concat-Liste erstellen
            concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")

            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video_path in video_paths:
                    f.write(f"file '{os.path.abspath(video_path)}'\n")

            # Temporäre Ausgabedatei
            self.combined_video_path = os.path.join(tempfile.gettempdir(), "preview_combined.mp4")

            # Videos ohne Rekodierung kombinieren
            result = subprocess.run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                "-movflags", "+faststart",
                self.combined_video_path
            ], capture_output=True, text=True)

            # Aufräumen
            try:
                os.remove(concat_list_path)
            except:
                pass

            if result.returncode == 0:
                # UI aktualisieren
                self.parent.after(0, self._update_ui_success, video_paths)
            else:
                self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")

    def _update_ui_success(self, video_paths):
        """Aktualisiert UI nach erfolgreicher Vorschau-Erstellung"""
        # Gesamtdauer berechnen
        total_duration = self._calculate_total_duration(video_paths)
        total_size = self._calculate_total_size(video_paths)

        self.duration_label.config(text=f"Gesamtdauer: {total_duration}")
        self.size_label.config(text=f"Dateigröße: {total_size}")
        self.clips_label.config(text=f"Anzahl Clips: {len(video_paths)}")
        self.status_label.config(text="Vorschau bereit", fg="green")
        self.play_button.config(state="normal")

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        self.status_label.config(text=error_msg, fg="red")
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text="Anzahl Clips: 0")
        self.play_button.config(state="disabled")
        self.combined_video_path = None

    def _calculate_total_duration(self, video_paths):
        """Berechnet die Gesamtdauer aller Videos"""
        total_seconds = 0
        for video_path in video_paths:
            try:
                result = subprocess.run([
                    'ffprobe', '-v', 'error', '-show_entries',
                    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                    video_path
                ], capture_output=True, text=True, timeout=5)

                if result.returncode == 0:
                    total_seconds += float(result.stdout.strip())
            except:
                continue

        minutes = int(total_seconds // 60)
        seconds = int(total_seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def _calculate_total_size(self, video_paths):
        """Berechnet die Gesamtgröße aller Videos"""
        total_bytes = 0
        for video_path in video_paths:
            try:
                total_bytes += os.path.getsize(video_path)
            except:
                continue

        if total_bytes > 1024 * 1024 * 1024:
            return f"{total_bytes / (1024 * 1024 * 1024):.1f} GB"
        elif total_bytes > 1024 * 1024:
            return f"{total_bytes / (1024 * 1024):.1f} MB"
        else:
            return f"{total_bytes / 1024:.1f} KB"

    def play_preview(self):
        """Startet die Vorschau-Wiedergabe"""
        if not self.combined_video_path or not os.path.exists(self.combined_video_path):
            return

        self.is_playing = True
        self.play_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_label.config(text="Wiedergabe läuft...", fg="blue")

        # Video mit Standard-Player öffnen
        try:
            if os.name == 'nt':  # Windows
                os.startfile(self.combined_video_path)
            elif os.name == 'posix':  # macOS/Linux
                subprocess.run(['open', self.combined_video_path])  # macOS
                # Für Linux: subprocess.run(['xdg-open', self.combined_video_path])
        except Exception as e:
            self.status_label.config(text=f"Player konnte nicht gestartet werden: {e}", fg="red")

        # Zurücksetzen nach kurzer Zeit (Player öffnet eigenständig)
        self.parent.after(2000, self._reset_play_state)

    def _reset_play_state(self):
        """Setzt den Play-Button zurück"""
        self.is_playing = False
        self.play_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Vorschau bereit", fg="green")

    def stop_preview(self):
        """Stoppt die Vorschau-Wiedergabe"""
        self.is_playing = False
        self.play_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Vorschau bereit", fg="green")

    def clear_preview(self):
        """Setzt die Vorschau zurück"""
        self.combined_video_path = None
        self.is_playing = False
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text="Anzahl Clips: 0")
        self.status_label.config(text="Keine Vorschau verfügbar", fg="gray")
        self.play_button.config(state="disabled")
        self.stop_button.config(state="disabled")

    def get_combined_video_path(self):
        """Gibt den Pfad des kombinierten Videos zurück"""
        return self.combined_video_path

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)