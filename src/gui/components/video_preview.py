import tkinter as tk
from tkinter import ttk
import os
import tempfile
import subprocess
import threading
import json


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

        # Encoding-Info
        self.encoding_label = tk.Label(info_frame, text="Encoding: --", font=("Arial", 9), fg="gray")
        self.encoding_label.pack(anchor="w")

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
        self.encoding_label.config(text="Encoding: Prüfe Formate...")
        self.clips_label.config(text=f"Anzahl Videos: {len(video_paths)}")

        # Im Thread verarbeiten um UI nicht zu blockieren
        thread = threading.Thread(target=self._create_combined_preview, args=(video_paths,))
        thread.start()

        return thread

    def _create_combined_preview(self, video_paths):
        """Erstellt ein kombiniertes Vorschau-Video aus allen Clips"""
        try:
            # Video-Formate prüfen
            format_info = self._check_video_formats(video_paths)
            needs_reencoding = not format_info["compatible"]

            self.parent.after(0, self._update_encoding_info, format_info)

            # Concat-Liste erstellen
            concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")

            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video_path in video_paths:
                    f.write(f"file '{os.path.abspath(video_path)}'\n")

            # Temporäre Ausgabedatei
            self.combined_video_path = os.path.join(tempfile.gettempdir(), "preview_combined.mp4")

            if needs_reencoding:
                # Mit Re-Encoding kombinieren (langsamer, aber kompatibel)
                self.parent.after(0, lambda: self.status_label.config(
                    text="Verschiedene Formate - kodiere neu...", fg="orange"))

                result = subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", concat_list_path,
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k",
                    "-movflags", "+faststart",
                    self.combined_video_path
                ], capture_output=True, text=True)
            else:
                # Ohne Re-Encoding kombinieren (schnell)
                self.parent.after(0, lambda: self.status_label.config(
                    text="Kombiniere Videos (schnell)...", fg="blue"))

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
                self.parent.after(0, self._update_ui_success, video_paths, needs_reencoding)
            else:
                self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")

    def _check_video_formats(self, video_paths):
        """Prüft ob alle Videos das gleiche Format, Auflösung und FPS haben"""
        if len(video_paths) <= 1:
            return {"compatible": True, "details": "Nur ein Video - kompatibel"}

        formats = []
        for video_path in video_paths:
            try:
                result = subprocess.run([
                    'ffprobe', '-v', 'quiet',
                    '-print_format', 'json',
                    '-show_format', '-show_streams',
                    video_path
                ], capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    info = json.loads(result.stdout)

                    # Finde Video-Stream
                    video_stream = None
                    for stream in info.get('streams', []):
                        if stream.get('codec_type') == 'video':
                            video_stream = stream
                            break

                    if video_stream:
                        format_info = {
                            'codec_name': video_stream.get('codec_name', 'unknown'),
                            'width': video_stream.get('width', 0),
                            'height': video_stream.get('height', 0),
                            'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                            'pix_fmt': video_stream.get('pix_fmt', 'unknown')
                        }
                        formats.append(format_info)
                    else:
                        formats.append({'error': 'No video stream'})
                else:
                    formats.append({'error': 'FFprobe failed'})

            except Exception as e:
                formats.append({'error': str(e)})

        # Vergleiche alle Formate
        if len(formats) <= 1:
            return {"compatible": True, "details": "Nur ein Video"}

        first_format = formats[0]
        compatible = True
        differences = []

        for i, fmt in enumerate(formats[1:], 1):
            if 'error' in fmt:
                compatible = False
                differences.append(f"Video {i + 1}: {fmt['error']}")
                continue

            # Prüfe Codec
            if fmt.get('codec_name') != first_format.get('codec_name'):
                compatible = False
                differences.append(f"Video {i + 1}: Codec {fmt['codec_name']} != {first_format['codec_name']}")

            # Prüfe Auflösung
            if fmt.get('width') != first_format.get('width') or fmt.get('height') != first_format.get('height'):
                compatible = False
                differences.append(
                    f"Video {i + 1}: {fmt['width']}x{fmt['height']} != {first_format['width']}x{first_format['height']}")

            # Prüfe Framerate (vereinfacht)
            if fmt.get('r_frame_rate') != first_format.get('r_frame_rate'):
                compatible = False
                differences.append(f"Video {i + 1}: FPS {fmt['r_frame_rate']} != {first_format['r_frame_rate']}")

            # Prüfe Pixel-Format
            if fmt.get('pix_fmt') != first_format.get('pix_fmt'):
                compatible = False
                differences.append(f"Video {i + 1}: Pixel-Format {fmt['pix_fmt']} != {first_format['pix_fmt']}")

        if compatible:
            details = f"Alle {len(video_paths)} Videos kompatibel: {first_format['width']}x{first_format['height']}, {first_format['codec_name']}"
        else:
            details = f"Format-Unterschiede: {', '.join(differences[:3])}"  # Zeige nur erste 3 Unterschiede

        return {
            "compatible": compatible,
            "details": details,
            "formats": formats
        }

    def _update_encoding_info(self, format_info):
        """Aktualisiert die Encoding-Information in der UI"""
        if format_info["compatible"]:
            self.encoding_label.config(text=f"Encoding: Kompatibel (schnell)", fg="green")
        else:
            self.encoding_label.config(text=f"Encoding: Neu kodieren nötig", fg="orange")

    def _update_ui_success(self, video_paths, was_reencoded):
        """Aktualisiert UI nach erfolgreicher Vorschau-Erstellung"""
        # Gesamtdauer berechnen
        total_duration = self._calculate_total_duration(video_paths)
        total_size = self._calculate_total_size(video_paths)

        self.duration_label.config(text=f"Gesamtdauer: {total_duration}")
        self.size_label.config(text=f"Dateigröße: {total_size}")
        self.clips_label.config(text=f"Anzahl Clips: {len(video_paths)}")

        if was_reencoded:
            self.status_label.config(text="Vorschau bereit (neu kodiert)", fg="green")
            self.encoding_label.config(text="Encoding: Neu kodiert", fg="orange")
        else:
            self.status_label.config(text="Vorschau bereit (schnell)", fg="green")
            self.encoding_label.config(text="Encoding: Direkt kombiniert", fg="green")

        self.play_button.config(state="normal")

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        self.status_label.config(text=error_msg, fg="red")
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text="Anzahl Clips: 0")
        self.encoding_label.config(text="Encoding: Fehler", fg="red")
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
        self.encoding_label.config(text="Encoding: --", fg="gray")
        self.status_label.config(text="Keine Vorschau verfügbar", fg="gray")
        self.play_button.config(state="disabled")
        self.stop_button.config(state="disabled")

    def get_combined_video_path(self):
        """Gibt den Pfad des kombinierten Videos zurück"""
        return self.combined_video_path

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)