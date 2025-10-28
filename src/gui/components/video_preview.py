import tkinter as tk
import os
import tempfile
import subprocess
import threading
import json
import re
import sys
from .progress_indicator import ProgressHandler
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class VideoPreview:
    def __init__(self, parent, app_instance=None):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent)
        self.combined_video_path = None
        self.progress_handler = None
        self.last_video_paths = None

        # --- State and Threading Control Attributes ---
        self.processing_thread = None
        self.ffmpeg_process = None
        self.cancellation_event = threading.Event()
        self.pending_restart_callback = None
        # ---

        self.create_widgets()

    def _get_clip_durations_seconds(self, video_paths):
        """Ermittelt die Dauer jedes einzelnen Clips in Sekunden."""
        durations = []
        for video_path in video_paths:
            try:
                # Ruft die Dauer für jeden Clip einzeln ab (wird von _calculate_total_duration_seconds benötigt)
                duration_str = self._get_single_video_duration_str(video_path)
                durations.append(float(duration_str))
            except Exception:
                durations.append(0.0)
        return durations

    def create_widgets(self):
        # --- Gemeinsamer Container für Info (links) und Steuerung (rechts) ---
        top_frame = tk.Frame(self.frame)
        top_frame.pack(fill="x", pady=5)

        # Linke Seite: Video-Info
        info_frame = tk.Frame(top_frame)
        info_frame.pack(side="left", anchor="n", padx=10, pady=5)

        self.duration_label = tk.Label(info_frame, text="Gesamtdauer: --:--", font=("Arial", 10))
        self.duration_label.pack(anchor="w")

        self.size_label = tk.Label(info_frame, text="Dateigröße: --", font=("Arial", 10))
        self.size_label.pack(anchor="w")

        self.clips_label = tk.Label(info_frame, text="Anzahl Clips: --", font=("Arial", 10))
        self.clips_label.pack(anchor="w")

        self.encoding_label = tk.Label(info_frame, text="Encoding: --", font=("Arial", 9), fg="gray")
        self.encoding_label.pack(anchor="w")

        # Rechte Seite: Steuerungs-Buttons
        control_frame = tk.Frame(top_frame)
        control_frame.pack(side="right", anchor="n", padx=10, pady=5)

        self.play_button = tk.Button(control_frame, text="▶ Vorschau abspielen",
                                     command=self.play_preview, state="disabled",
                                     font=("Arial", 11), width=20, height=1)
        self.play_button.pack(pady=2)

        self.action_button = tk.Button(control_frame, text="⏹ Erstellung abbrechen",
                                       command=self.cancel_creation, state="disabled",
                                       font=("Arial", 11), width=20, height=1)
        self.action_button.pack(pady=2)

        # Status-Label unter beiden Bereichen
        self.status_label = tk.Label(self.frame, text="Ziehen Sie Videos in das Feld links",
                                     font=("Arial", 10), fg="gray", wraplength=300)
        self.status_label.pack(pady=5)

        # Progress bar container
        self.progress_frame = tk.Frame(self.frame)
        self.progress_frame.pack(pady=5, fill='x')

    def update_preview(self, video_paths):
        """
        Public entry point to update the preview.
        Handles cancellation of an ongoing process before starting a new one.
        """
        if self.processing_thread and self.processing_thread.is_alive():
            # A process is running. Request a restart after it's cancelled.
            self.pending_restart_callback = lambda: self._start_preview_creation_thread(video_paths)
            self.cancel_creation()
            print("Preview creation in progress. Queuing a restart.")
        else:
            # No process is running, start directly.
            self._start_preview_creation_thread(video_paths)



    def _start_preview_creation_thread(self, video_paths):
        """Starts the background thread to create the preview."""
        if not video_paths:
            self.clear_preview()
            return

        # Store the current paths for a potential retry
        self.last_video_paths = video_paths

        if not self.progress_handler:
            self.progress_handler = ProgressHandler(self.progress_frame)

        self.status_label.config(text="Erstelle Vorschau...", fg="blue")
        self.play_button.config(state="disabled")

        self.action_button.config(text="⏹ Erstellung abbrechen",
                                  command=self.cancel_creation,
                                  state="normal")
        self.encoding_label.config(text="Encoding: Prüfe Formate...")
        self.clips_label.config(text=f"Anzahl Videos: {len(video_paths)}")

        self.cancellation_event.clear()

        self.processing_thread = threading.Thread(target=self._create_combined_preview, args=(video_paths,))
        self.processing_thread.start()

    def _create_combined_preview(self, video_paths):
        """Erstellt ein kombiniertes Vorschau-Video aus allen Clips"""
        try:
            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            format_info = self._check_video_formats(video_paths)
            needs_reencoding = not format_info["compatible"]

            self.parent.after(0, self._update_encoding_info, format_info)

            if needs_reencoding:
                self.parent.after(0, lambda: self.status_label.config(
                    text="Kodiere Videos auf 1080p @ 30fps...", fg="orange"))
                self.parent.after(0, self.progress_handler.pack_progress_bar)
                self.combined_video_path = self._create_reencoded_combined_video(video_paths)
            else:
                self.parent.after(0, lambda: self.status_label.config(
                    text="Kombiniere Videos (schnell)...", fg="blue"))
                self.combined_video_path = self._create_fast_combined_video(video_paths)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            if self.combined_video_path and os.path.exists(self.combined_video_path):
                self.parent.after(0, self._update_ui_success, video_paths, needs_reencoding)
            else:
                # Avoid showing an error if it was a user cancellation
                if not self.cancellation_event.is_set():
                    self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            if not self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")
        finally:
            # Schedule finalization on the main GUI thread for thread-safety.
            if self.parent.winfo_exists():
                self.parent.after(0, self._finalize_processing)

    def _finalize_processing(self):
        """
        Cleans up after a thread finishes and triggers a pending restart if requested.
        This method MUST run on the main GUI thread.
        """
        self.processing_thread = None
        self.ffmpeg_process = None

        if self.pending_restart_callback:
            # A restart was requested.
            callback = self.pending_restart_callback
            self.pending_restart_callback = None
            callback()  # This will call _start_preview_creation_thread with the new paths

    def _create_fast_combined_video(self, video_paths):
        """Kombiniert Videos schnell ohne Re-Encoding"""
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_fast.mp4")

        with open(concat_list_path, "w", encoding="utf-8") as f:
            for video_path in video_paths:
                f.write(f"file '{os.path.abspath(video_path)}'\n")

        if self.cancellation_event.is_set(): return None

        result = subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
            "-c", "copy", "-movflags", "+faststart", output_path
        ], capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        try:
            os.remove(concat_list_path)
        except OSError as e:
            print(f"Error removing temp file: {e}")

        if result.returncode == 0:
            return output_path
        else:
            if not self.cancellation_event.is_set():
                print(f"Fast combine failed: {result.stderr}")
            return None

    def _monitor_ffmpeg_progress(self, cmd, total_duration_secs):
        """Runs an ffmpeg command and updates the progress bar by reading its output."""
        if total_duration_secs <= 0 or self.cancellation_event.is_set():
            return False

        self.ffmpeg_process = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                               universal_newlines=True, encoding='utf-8', errors='replace',
                                               creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        for line in iter(self.ffmpeg_process.stderr.readline, ''):
            if self.cancellation_event.is_set():
                print("Cancellation detected, terminating FFmpeg.")
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
                return False

            match = re.search(r"time=(\d{2}):(\d{2}):(\d{2})\.(\d{2})", line)
            if match:
                h, m, s, ms = map(int, match.groups())
                current_secs = h * 3600 + m * 60 + s + ms / 100
                self.parent.after(0, self.progress_handler.update_progress, current_secs, total_duration_secs)

        self.ffmpeg_process.wait()

        if self.ffmpeg_process.returncode == 0 and not self.cancellation_event.is_set():
            self.parent.after(0, self.progress_handler.update_progress, total_duration_secs, total_duration_secs)

        return self.ffmpeg_process.returncode == 0 and not self.cancellation_event.is_set()

    def _create_reencoded_combined_video(self, video_paths):
        if not video_paths: return None
        total_duration_secs = self._calculate_total_duration_seconds(video_paths)
        target_params = {
            'width': 1920, 'height': 1080, 'fps': 30, 'pix_fmt': 'yuv420p',
            'video_codec': 'libx264', 'audio_codec': 'aac', 'audio_sample_rate': 48000, 'audio_channels': 2
        }
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_reencoded.mp4")
        try:
            cmd = ["ffmpeg", "-y"]
            for video_path in video_paths: cmd.extend(["-i", video_path])
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
            success = self._monitor_ffmpeg_progress(cmd, total_duration_secs)
            if success:
                return output_path
            elif not self.cancellation_event.is_set():
                print("Re-encoding with filter_complex failed. Trying fallback.")
                return self._create_simple_reencoded_video(video_paths, target_params, total_duration_secs)
            return None
        except Exception as e:
            if not self.cancellation_event.is_set():
                print(f"An unexpected error occurred during encoding: {e}")
            return None

    def _create_simple_reencoded_video(self, video_paths, params, total_duration_secs):
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_reencode.txt")
        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_simple_reencoded.mp4")
        with open(concat_list_path, "w", encoding="utf-8") as f:
            for video_path in video_paths: f.write(f"file '{os.path.abspath(video_path)}'\n")
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
            success = self._monitor_ffmpeg_progress(cmd, total_duration_secs)
            if success:
                return output_path
            elif not self.cancellation_event.is_set():
                print("Simple re-encoding fallback also failed.")
                return None
            return None
        finally:
            try:
                os.remove(concat_list_path)
            except OSError:
                pass

    def _check_video_formats(self, video_paths):
        if len(video_paths) <= 1:
            return {"compatible": True, "details": "Nur ein Video - kompatibel"}
        formats = []
        for video_path in video_paths:
            try:
                result = subprocess.run(['ffprobe', '-v', 'quiet', '-print_format', 'json',
                                         '-show_format', '-show_streams', video_path],
                                        capture_output=True, text=True, timeout=10,
                                        creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                if result.returncode == 0:
                    info = json.loads(result.stdout)
                    video_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
                    if video_stream:
                        formats.append({'codec_name': video_stream.get('codec_name', 'unknown'),
                                        'width': video_stream.get('width', 0), 'height': video_stream.get('height', 0),
                                        'r_frame_rate': video_stream.get('r_frame_rate', '0/0'),
                                        'pix_fmt': video_stream.get('pix_fmt', 'unknown')})
                    else:
                        formats.append({'error': 'No video stream'})
                else:
                    formats.append({'error': 'FFprobe failed'})
            except Exception as e:
                formats.append({'error': str(e)})
        first_format = next((f for f in formats if 'error' not in f), None)
        if not first_format: return {"compatible": False, "details": "No valid video streams found."}
        is_compatible = True;
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
        self.action_button.config(state="disabled")

        # NEU: Video an den VideoPlayer übergeben
        clip_durations = self._get_clip_durations_seconds(video_paths)
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.load_video(self.combined_video_path, clip_durations)

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text=error_msg, fg="red")
        self.clear_preview_info()
        self.play_button.config(state="disabled")
        # --- MODIFIED: Change to a retry button on error ---
        self.action_button.config(text="🔄 Erneut versuchen",
                                  command=self.retry_creation,
                                  state="normal")
        self.combined_video_path = None

    def _update_ui_cancelled(self):
        """Updates UI after creation was cancelled."""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text="Vorschau-Erstellung abgebrochen", fg="orange")
        self.clear_preview_info()
        self.play_button.config(state="disabled")
        # --- MODIFIED: Change to a retry button on cancel ---
        self.action_button.config(text="🔄 Erneut versuchen",
                                  command=self.retry_creation,
                                  state="normal")
        self.combined_video_path = None

    def _get_single_video_duration_str(self, video_path):
        """Hilfsmethode: Holt die Dauer EINES Videos als String in Sekunden (z.B. '12.34')."""

        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output = True, text = True, timeout = 5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return "0.0"

    def _calculate_total_duration_seconds(self, video_paths):
        total_seconds = 0
        for video_path in video_paths:
            total_seconds += float(self._get_single_video_duration_str(video_path))
        return total_seconds

    def _calculate_total_duration(self, video_paths):
        total_seconds = self._calculate_total_duration_seconds(video_paths)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{int(minutes):02d}:{int(seconds):02d}"

    def _calculate_total_size(self, video_paths):
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

        self.status_label.config(text="Starte externen Videoplayer...", fg="blue")
        try:
            if sys.platform == "win32":
                os.startfile(self.combined_video_path)
            elif sys.platform == "darwin":
                subprocess.run(['open', self.combined_video_path],
                               check=True,
                               creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            else:
                subprocess.run(['xdg-open', self.combined_video_path],
                               check=True,
                               creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except Exception as e:
            self.status_label.config(text=f"Player konnte nicht gestartet werden: {e}", fg="red")

        self.parent.after(2000, self._reset_play_state)

    def _reset_play_state(self):
        """Setzt den Wiedergabe-Status zurück."""
        if not self.parent.winfo_exists(): return
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            self.status_label.config(text="Vorschau bereit", fg="green")

    def cancel_creation(self):
        """Signals the processing thread to cancel the video creation."""
        if self.processing_thread and self.processing_thread.is_alive():
            self.status_label.config(text="Abbruch wird eingeleitet...", fg="orange")
            self.action_button.config(state="disabled")
            self.cancellation_event.set()

    # --- NEW: Retry creation method ---
    def retry_creation(self):
        """Retries the preview creation with the last used video paths."""
        if not self.last_video_paths:
            print("No previous video paths available to retry.")
            return
        self.update_preview(self.last_video_paths)

    def clear_preview(self):
        """Setzt die Vorschau zurück und löscht die temporäre Datei"""
        self.pending_restart_callback = None  # Clear any pending restart
        self.cancel_creation()
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            try:
                os.remove(self.combined_video_path)
            except OSError as e:
                print(f"Could not delete temp preview file: {e}")

        self.combined_video_path = None
        self.last_video_paths = None
        self.clear_preview_info()
        self.status_label.config(text="Keine Vorschau verfügbar", fg="gray")
        self.play_button.config(state="disabled")
        self.action_button.config(text="⏹ Erstellung abbrechen",
                                  command=self.cancel_creation,
                                  state="disabled")

        # NEU: Player ebenfalls zurücksetzen
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.unload_video()

    def clear_preview_info(self):
        """Helper to clear all text labels."""
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text=f"Anzahl Clips: {len(self.last_video_paths) if self.last_video_paths else '--'}")
        self.encoding_label.config(text="Encoding: --", fg="gray")

    def get_combined_video_path(self):
        """Gibt den Pfad des kombinierten Videos zurück"""
        return self.combined_video_path

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

