import tkinter as tk
from tkinter import ttk
import os
import tempfile
import subprocess
import threading
import json
import re
import sys
from .progress_indicator import ProgressHandler


class VideoPreview:
    def __init__(self, parent):
        self.parent = parent
        self.frame = tk.Frame(parent)
        self.combined_video_path = None
        self.is_playing = False
        self.progress_handler = None
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

        # Progress bar container
        self.progress_frame = tk.Frame(self.frame)
        self.progress_frame.pack(pady=5, fill='x')

    def update_preview(self, video_paths):
        """Erstellt eine Vorschau aus allen Videos und aktualisiert die UI"""
        if not video_paths:
            self.clear_preview()
            return None

        # Instantiate progress handler if it doesn't exist
        if not self.progress_handler:
            self.progress_handler = ProgressHandler(self.progress_frame)

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

            if needs_reencoding:
                # Mit Re-Encoding kombinieren - alle Videos auf 1080p@30fps standardisieren
                self.parent.after(0, lambda: self.status_label.config(
                    text="Kodiere Videos auf 1080p @ 30fps...", fg="orange"))
                self.parent.after(0, self.progress_handler.pack_progress_bar)

                self.combined_video_path = self._create_reencoded_combined_video(video_paths)
            else:
                # Ohne Re-Encoding kombinieren (schnell)
                self.parent.after(0, lambda: self.status_label.config(
                    text="Kombiniere Videos (schnell)...", fg="blue"))

                self.combined_video_path = self._create_fast_combined_video(video_paths)

            if self.combined_video_path and os.path.exists(self.combined_video_path):
                # UI aktualisieren
                self.parent.after(0, self._update_ui_success, video_paths, needs_reencoding)
            else:
                self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")

    def _create_fast_combined_video(self, video_paths):
        """Kombiniert Videos schnell ohne Re-Encoding"""
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_fast.mp4")

        # Use ' with open(...) ' to ensure the file is closed automatically
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for video_path in video_paths:
                # Use os.path.abspath to create safe file paths for ffmpeg
                f.write(f"file '{os.path.abspath(video_path)}'\n")

        result = subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path
        ], capture_output=True, text=True)

        # Clean up the temporary list file
        try:
            os.remove(concat_list_path)
        except OSError as e:
            print(f"Error removing temp file: {e}")

        if result.returncode == 0:
            return output_path
        else:
            print(f"Fast combine failed: {result.stderr}")
            return None

    def _monitor_ffmpeg_progress(self, cmd, total_duration_secs):
        """Runs an ffmpeg command and updates the progress bar by reading its output."""
        if total_duration_secs <= 0:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            return result.returncode == 0

        process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                   universal_newlines=True, encoding='utf-8', errors='replace')

        for line in iter(process.stderr.readline, ''):
            match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line)
            if match:
                h, m, s, ms = map(int, match.groups())
                current_secs = h * 3600 + m * 60 + s + ms / 100
                self.parent.after(0, self.progress_handler.update_progress, current_secs, total_duration_secs)

        process.wait()
        # Ensure progress bar reaches 100%
        self.parent.after(0, self.progress_handler.update_progress, total_duration_secs, total_duration_secs)
        return process.returncode == 0

    def _create_reencoded_combined_video(self, video_paths):
        """Kombiniert Videos, indem alle auf 1080p@30fps standardisiert werden, ohne das Seitenverhältnis zu verzerren."""
        if not video_paths:
            return None

        total_duration_secs = self._calculate_total_duration_seconds(video_paths)

        target_params = {
            'width': 1920, 'height': 1080, 'fps': 30, 'pix_fmt': 'yuv420p',
            'video_codec': 'libx264', 'audio_codec': 'aac', 'audio_sample_rate': 48000, 'audio_channels': 2
        }
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_reencoded.mp4")

        try:
            cmd = ["ffmpeg", "-y"]
            for video_path in video_paths:
                cmd.extend(["-i", video_path])

            filter_complex_parts = []
            for i, _ in enumerate(video_paths):
                video_filter = (
                    f"[{i}:v]scale={target_params['width']}:{target_params['height']}:force_original_aspect_ratio=decrease,"
                    f"pad={target_params['width']}:{target_params['height']}:-1:-1:color=black,"
                    f"fps={target_params['fps']},format={target_params['pix_fmt']}[v{i}]"
                )
                audio_filter = f"[{i}:a]aresample={target_params['audio_sample_rate']},asetpts=N/SR/TB[a{i}]"
                filter_complex_parts.extend([video_filter, audio_filter])

            video_outputs = "".join([f"[v{i}]" for i in range(len(video_paths))])
            audio_outputs = "".join([f"[a{i}]" for i in range(len(video_paths))])
            filter_complex_parts.append(f"{video_outputs}concat=n={len(video_paths)}:v=1:a=0[outv]")
            filter_complex_parts.append(f"{audio_outputs}concat=n={len(video_paths)}:v=0:a=1[outa]")
            filter_complex = ";".join(filter_complex_parts)

            cmd.extend([
                "-filter_complex", filter_complex, "-map", "[outv]", "-map", "[outa]",
                "-c:v", target_params['video_codec'], "-preset", "fast", "-crf", "23",
                "-c:a", target_params['audio_codec'], "-b:a", "128k",
                "-movflags", "+faststart", output_path
            ])

            print(f"FFmpeg command: {' '.join(cmd)}")
            success = self._monitor_ffmpeg_progress(cmd, total_duration_secs)

            if success:
                return output_path
            else:
                print("Re-encoding with filter_complex failed. Trying fallback.")
                return self._create_simple_reencoded_video(video_paths, target_params, total_duration_secs)

        except Exception as e:
            print(f"An unexpected error occurred during encoding: {e}")
            return None

    def _create_simple_reencoded_video(self, video_paths, params, total_duration_secs):
        """Einfachere Fallback-Methode, die den Concat-Demuxer verwendet und das Ergebnis neu kodiert."""
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_reencode.txt")
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_simple_reencoded.mp4")

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for video_path in video_paths:
                f.write(f"file '{os.path.abspath(video_path)}'\n")

        try:
            cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
                "-vf", f"scale={params['width']}:{params['height']}:force_original_aspect_ratio=decrease,"
                       f"pad={params['width']}:{params['height']}:-1:-1:color=black,"
                       f"fps={params['fps']},format={params['pix_fmt']}",
                "-c:v", params['video_codec'], "-preset", "fast", "-crf", "23",
                "-c:a", params['audio_codec'], "-b:a", "128k",
                "-ar", str(params['audio_sample_rate']), "-ac", str(params['audio_channels']),
                "-movflags", "+faststart", output_path
            ]

            print(f"FFmpeg fallback command: {' '.join(cmd)}")
            success = self._monitor_ffmpeg_progress(cmd, total_duration_secs)

            if success:
                return output_path
            else:
                print("Simple re-encoding fallback also failed.")
                return None
        finally:
            try:
                os.remove(concat_list_path)
            except OSError:
                pass

    def _check_video_formats(self, video_paths):
        """Prüft ob alle Videos das gleiche Format haben"""
        if len(video_paths) <= 1:
            return {"compatible": True, "details": "Nur ein Video - kompatibel"}

        formats = []
        for video_path in video_paths:
            try:
                result = subprocess.run([
                    'ffprobe', '-v', 'quiet', '-print_format', 'json',
                    '-show_format', '-show_streams', video_path
                ], capture_output=True, text=True, timeout=10)

                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    video_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
                    if video_stream:
                        formats.append({
                            'codec_name': video_stream.get('codec_name', 'unknown'),
                            'width': video_stream.get('width', 0), 'height': video_stream.get('height', 0),
                            'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                            'pix_fmt': video_stream.get('pix_fmt', 'unknown'),
                        })
                    else:
                        formats.append({'error': 'No video stream'})
                else:
                    formats.append({'error': 'FFprobe failed'})
            except Exception as e:
                formats.append({'error': str(e)})

        first_format = next((f for f in formats if 'error' not in f), None)
        if not first_format: return {"compatible": False, "details": "No valid video streams found."}

        is_compatible = True
        diffs = []
        for i, fmt in enumerate(formats):
            if 'error' in fmt:
                is_compatible = False
                diffs.append(f"Video {i + 1}: {fmt['error']}")
                continue
            for key in ['codec_name', 'width', 'height', 'r_frame_rate', 'pix_fmt']:
                if fmt.get(key) != first_format.get(key):
                    is_compatible = False
                    diffs.append(f"V{i + 1} {key}")

        details = f"Alle {len(video_paths)} Videos kompatibel." if is_compatible else f"Format-Unterschiede: {', '.join(diffs[:3])}"
        return {"compatible": is_compatible, "details": details}

    def _update_encoding_info(self, format_info):
        """Aktualisiert die Encoding-Information in der UI"""
        if format_info["compatible"]:
            self.encoding_label.config(text=f"Encoding: Kompatibel (schnell)", fg="green")
        else:
            self.encoding_label.config(text=f"Encoding: Standardisiert (1080p)", fg="orange")

    def _update_ui_success(self, video_paths, was_reencoded):
        """Aktualisiert UI nach erfolgreicher Vorschau-Erstellung"""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)

        total_duration = self._calculate_total_duration(video_paths)
        total_size = self._calculate_total_size(video_paths)

        self.duration_label.config(text=f"Gesamtdauer: {total_duration}")
        self.size_label.config(text=f"Dateigröße: {total_size}")
        self.clips_label.config(text=f"Anzahl Clips: {len(video_paths)}")

        if was_reencoded:
            self.status_label.config(text="Vorschau bereit (standardisiert)", fg="green")
            self.encoding_label.config(text="Encoding: Standardisiert (1080p)", fg="orange")
        else:
            self.status_label.config(text="Vorschau bereit (schnell)", fg="green")
            self.encoding_label.config(text="Encoding: Direkt kombiniert", fg="green")

        self.play_button.config(state="normal")

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text=error_msg, fg="red")
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text="Anzahl Clips: 0")
        self.encoding_label.config(text="Encoding: Fehler", fg="red")
        self.play_button.config(state="disabled")
        self.combined_video_path = None

    def _calculate_total_duration_seconds(self, video_paths):
        """Berechnet die Gesamtdauer aller Videos in Sekunden."""
        total_seconds = 0
        for video_path in video_paths:
            try:
                result = subprocess.run([
                    'ffprobe', '-v', 'error', '-show_entries',
                    'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path
                ], capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout:
                    total_seconds += float(result.stdout.strip())
            except (subprocess.TimeoutExpired, ValueError):
                continue
        return total_seconds

    def _calculate_total_duration(self, video_paths):
        """Berechnet die Gesamtdauer aller Videos und formatiert sie als MM:SS."""
        total_seconds = self._calculate_total_duration_seconds(video_paths)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{int(minutes):02d}:{int(seconds):02d}"

    def _calculate_total_size(self, video_paths):
        """Berechnet die Gesamtgröße aller Videos"""
        total_bytes = sum(os.path.getsize(p) for p in video_paths if os.path.exists(p))
        if total_bytes == 0: return "0 KB"
        if total_bytes > 1024 ** 3: return f"{total_bytes / (1024 ** 3):.1f} GB"
        if total_bytes > 1024 ** 2: return f"{total_bytes / (1024 ** 2):.1f} MB"
        return f"{total_bytes / 1024:.1f} KB"

    def play_preview(self):
        """Startet die Vorschau-Wiedergabe"""
        if not self.combined_video_path or not os.path.exists(self.combined_video_path):
            self.status_label.config(text="Vorschau-Datei nicht gefunden", fg="red")
            return

        self.is_playing = True
        self.play_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.status_label.config(text="Wiedergabe läuft...", fg="blue")

        try:
            if sys.platform == "win32":
                os.startfile(self.combined_video_path)
            elif sys.platform == "darwin":
                subprocess.run(['open', self.combined_video_path], check=True)
            else:
                subprocess.run(['xdg-open', self.combined_video_path], check=True)
        except Exception as e:
            self.status_label.config(text=f"Player konnte nicht gestartet werden: {e}", fg="red")
            self._reset_play_state()
            return

        self.parent.after(3000, self._reset_play_state)

    def _reset_play_state(self):
        """Setzt den Play-Button zurück"""
        if not self.parent.winfo_exists(): return
        self.is_playing = False
        self.play_button.config(state="normal")
        self.stop_button.config(state="disabled")
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            self.status_label.config(text="Vorschau bereit", fg="green")

    def stop_preview(self):
        """Stoppt die Vorschau-Wiedergabe (symbolisch, da externer Player)"""
        if not self.parent.winfo_exists(): return
        self.is_playing = False
        self.play_button.config(state="normal")
        self.stop_button.config(state="disabled")
        self.status_label.config(text="Vorschau gestoppt", fg="orange")
        self.parent.after(2000, self._reset_play_state)

    def clear_preview(self):
        """Setzt die Vorschau zurück und löscht die temporäre Datei"""
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            try:
                os.remove(self.combined_video_path)
            except OSError as e:
                print(f"Could not delete temp preview file: {e}")

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

