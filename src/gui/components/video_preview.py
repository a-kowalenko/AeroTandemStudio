import tkinter as tk
import os
import tempfile
import subprocess
import threading
import json
import re
import sys
import shutil
import time
from .progress_indicator import ProgressHandler
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from typing import List, Dict, Callable  # NEU


class VideoPreview:
    def __init__(self, parent, app_instance=None):
        self.parent = parent
        self.app = app_instance
        self.frame = tk.Frame(parent)
        self.combined_video_path = None
        self.progress_handler = None
        self.last_video_paths = None  # Speichert die *originalen* Pfade für "Erneut versuchen"

        # --- State and Threading Control Attributes ---
        self.processing_thread = None
        self.ffmpeg_process = None
        self.cancellation_event = threading.Event()
        self.pending_restart_callback = None

        # --- NEU: Verwaltung der temporären Kopien UND Metadaten-Cache ---
        self.temp_dir = None
        self.video_copies_map: Dict[str, str] = {}  # Map: original_path -> copy_path
        self.metadata_cache: Dict[str, Dict] = {}  # Map: original_path -> {duration, size, ...}
        # ---

        self.create_widgets()

    def _check_for_cancellation(self):
        """Prüft, ob ein Abbruch angefordert wurde und wirft ggf. eine Exception."""
        if self.cancellation_event.is_set():
            raise Exception("Vorschau-Erstellung vom Benutzer abgebrochen.")

    def _get_clip_durations_seconds(self, video_paths):
        """Ermittelt die Dauer jedes einzelnen Clips in Sekunden (aus dem Cache, wenn möglich)."""
        durations = []
        for video_path in video_paths:  # HINWEIS: video_paths ist hier eine Liste von KOPIEN
            try:
                # Versuche, den Originalpfad aus der Kopie abzuleiten (für Cache-Lookup)
                original_path = next((key for key, value in self.video_copies_map.items() if value == video_path), None)

                if original_path and original_path in self.metadata_cache:
                    duration_str = self.metadata_cache[original_path].get("duration_sec_str", "0.0")
                    durations.append(float(duration_str))
                else:
                    # Fallback: ffprobe direkt auf die Kopie anwenden
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
        NEU: Cleanup nur noch wenn wirklich nötig (komplett neue Videos).
        """
        # NEU: Cleanup NICHT mehr hier aufrufen - wird intelligent in _start_preview_creation_thread gehandhabt
        # self._cleanup_temp_copies()  # ENTFERNT!

        if self.processing_thread and self.processing_thread.is_alive():
            self.pending_restart_callback = lambda: self._start_preview_creation_thread(video_paths)
            self.cancel_creation()
            print("Preview creation in progress. Queuing a restart.")
        else:
            self._start_preview_creation_thread(video_paths)

    def _start_preview_creation_thread(self, video_paths):
        """Starts the background thread to create the preview."""
        if not video_paths:
            self.clear_preview()
            return

        self.last_video_paths = video_paths

        # NEU: Erstelle temp_dir nur wenn noch nicht vorhanden
        # (verhindert unnötiges Löschen bereits kodierter Videos)
        if not self.temp_dir or not os.path.exists(self.temp_dir):
            self._create_temp_directory()  # Erstellt auch leere Caches/Maps

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

        # NEU: Schneiden-Button wird nur gesperrt wenn tatsächlich neu kodiert wird
        # Das wird in _create_combined_preview entschieden
        # if self.app and hasattr(self.app, 'drag_drop'):
        #     self.app.drag_drop.set_cut_button_enabled(False)

        self.processing_thread = threading.Thread(target=self._create_combined_preview, args=(video_paths,))
        self.processing_thread.start()

    def _create_temp_directory(self):
        """Erstellt ein sauberes temporäres Verzeichnis für Video-Kopien."""
        self._cleanup_temp_copies()
        try:
            self.temp_dir = tempfile.mkdtemp(prefix="aero_studio_preview_")
            self.video_copies_map = {}
            self.metadata_cache = {}  # NEU
            print(f"Temporäres Verzeichnis erstellt: {self.temp_dir}")
        except Exception as e:
            print(f"Fehler beim Erstellen des temporären Verzeichnisses: {e}")
            self.temp_dir = None

    def _cleanup_temp_copies(self):
        """Löscht das temporäre Verzeichnis und seinen Inhalt."""
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
                print(f"Temporäres Verzeichnis gelöscht: {self.temp_dir}")
            except Exception as e:
                print(f"Fehler beim Löschen des temporären Verzeichnisses {self.temp_dir}: {e}")
        self.temp_dir = None
        self.video_copies_map.clear()
        self.metadata_cache.clear()  # NEU

    def _prepare_video_copies(self, original_paths, needs_reencoding):
        """
        Erstellt temporäre Kopien der Videos (A/B-Logik) UND
        füllt den Metadaten-Cache im selben Thread.
        """
        if not self.temp_dir:
            raise Exception("Temporäres Verzeichnis nicht initialisiert.")

        # NEU: Sperre Schneiden-Button nur wenn tatsächlich neu kodiert wird
        if needs_reencoding and self.app and hasattr(self.app, 'drag_drop'):
            self.parent.after(0, lambda: self.app.drag_drop.set_cut_button_enabled(False))

        self.video_copies_map.clear()
        self.metadata_cache.clear()  # Cache bei voller Ne-Erstellung leeren
        temp_copy_paths = []
        total_clips = len(original_paths)

        self.parent.after(0, self.progress_handler.pack_progress_bar)
        self.parent.after(0, self.progress_handler.update_progress, 0, total_clips)

        for i, original_path in enumerate(original_paths):
            self._check_for_cancellation()

            filename = os.path.basename(original_path)
            # Ersetze ungültige Zeichen im Dateinamen für den Fall der Fälle
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            copy_path = os.path.join(self.temp_dir, f"{i:03d}_{safe_filename}")

            if needs_reencoding:
                # --- Fall B: Neukodierung ---
                status_msg = f"Kodiere Clip {i + 1}/{total_clips} (1080p@30)..."
                self.parent.after(0, lambda msg=status_msg: self.status_label.config(text=msg, fg="orange"))

                try:
                    self._reencode_single_clip(original_path, copy_path)
                except Exception as e:
                    if self.cancellation_event.is_set():
                        print("Neukodierung abgebrochen.")
                        raise
                    else:
                        print(f"Fehler bei Neukodierung von {filename}: {e}")
                        raise Exception(f"Fehler bei Neukodierung von {filename}")

            else:
                # --- Fall A: Kopieren ---
                status_msg = f"Kopiere Clip {i + 1}/{total_clips}..."
                self.parent.after(0, lambda msg=status_msg: self.status_label.config(text=msg, fg="blue"))

                try:
                    shutil.copy2(original_path, copy_path)
                except Exception as e:
                    print(f"Fehler beim Kopieren von {filename}: {e}")
                    raise Exception(f"Fehler beim Kopieren von {filename}")

            temp_copy_paths.append(copy_path)
            self.video_copies_map[original_path] = copy_path

            # NEU: Metadaten direkt nach Erstellung der Kopie cachen
            self._cache_metadata_for_copy(original_path, copy_path)

            self.parent.after(0, self.progress_handler.update_progress, i + 1, total_clips)

        # NEU: Entsperre Schneiden-Button nach Kopieren/Kodieren
        if self.app and hasattr(self.app, 'drag_drop'):
            self.parent.after(0, lambda: self.app.drag_drop.set_cut_button_enabled(True))

        self.parent.after(0, self.progress_handler.reset)
        return temp_copy_paths

    def _reencode_single_clip(self, input_path, output_path):
        """
        Neukodiert eine einzelne Videodatei auf 1080p@30fps. (Blockierend)
        """
        target_params = {
            'width': 1920, 'height': 1080, 'fps': 30, 'pix_fmt': 'yuv420p',
            'video_codec': 'libx264', 'audio_codec': 'aac', 'audio_sample_rate': 48000, 'audio_channels': 2
        }
        tp = target_params

        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf",
            f"scale={tp['width']}:{tp['height']}:force_original_aspect_ratio=decrease,pad={tp['width']}:{tp['height']}:(ow-iw)/2:(oh-ih)/2:color=black,fps={tp['fps']},format={tp['pix_fmt']}",
            "-c:v", tp['video_codec'], "-preset", "fast", "-crf", "23",
            "-c:a", tp['audio_codec'], "-b:a", "128k", "-ar", str(tp['audio_sample_rate']), "-ac", str(tp['audio_channels']),
            "-movflags", "+faststart",
            "-map", "0:v:0", "-map", "0:a:0?",  # WICHTIG: Video ist pflicht, Audio optional
            output_path
        ]

        # WICHTIG: Capture stderr für Fehlerdiagnose
        self.ffmpeg_process = subprocess.Popen(
            cmd,
            stderr=subprocess.PIPE,  # Geändert von DEVNULL
            stdout=subprocess.DEVNULL,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace',
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        # Sammle stderr für Fehlerdiagnose
        stderr_output = []

        while self.ffmpeg_process.poll() is None:
            if self.cancellation_event.is_set():
                print(f"Abbruch-Signal empfangen. Terminiere FFmpeg für: {input_path}")
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
                self.ffmpeg_process = None
                raise Exception("Neukodierung vom Benutzer abgebrochen.")

            # Lese stderr in kleinen Chunks (non-blocking)
            try:
                import select
                if hasattr(select, 'select'):  # Unix
                    ready = select.select([self.ffmpeg_process.stderr], [], [], 0.1)[0]
                    if ready:
                        line = self.ffmpeg_process.stderr.readline()
                        if line:
                            stderr_output.append(line)
            except:
                pass  # Windows hat kein select für pipes

            time.sleep(0.1)

        # Warte auf Prozess-Ende und hole restlichen stderr
        stdout, stderr = self.ffmpeg_process.communicate()
        if stderr:
            stderr_output.append(stderr)

        returncode = self.ffmpeg_process.returncode
        self.ffmpeg_process = None

        if returncode != 0:
            # Zeige die letzten Zeilen des stderr-Outputs für Debugging
            stderr_text = ''.join(stderr_output)
            last_lines = '\n'.join(stderr_text.split('\n')[-20:])  # Letzte 20 Zeilen
            print(f"\n=== FFmpeg Fehler bei {os.path.basename(input_path)} ===")
            print(f"Returncode: {returncode}")
            print(f"Letzter FFmpeg Output:\n{last_lines}")
            print("=" * 50)

            # Gebe detaillierte Fehlermeldung
            error_msg = f"FFmpeg-Fehler (Code {returncode}) bei der Neukodierung von {input_path}"
            if "Invalid" in stderr_text or "does not contain" in stderr_text:
                error_msg += "\nMögliches Problem: Video-/Audio-Stream fehlt oder ist ungültig"
            elif "Conversion failed" in stderr_text:
                error_msg += "\nMögliches Problem: Filter-Chain oder Codec-Fehler"

            raise Exception(error_msg)

    def _create_combined_preview(self, video_paths):
        """
        Erstellt ein kombiniertes Vorschau-Video.
        NEU: Verwendet bereits existierende Kopien wieder, wenn die gleichen Videos nur umsortiert wurden.
        """
        try:
            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            # Initialisiere Variablen
            needs_reencoding = False
            temp_copy_paths = []

            # NEU: Prüfe, ob wir bereits Kopien für alle Videos haben
            all_videos_cached = all(original_path in self.video_copies_map for original_path in video_paths)

            if all_videos_cached and self.temp_dir and os.path.exists(self.temp_dir):
                # Alle Videos sind bereits kopiert/kodiert, verwende existierende Kopien
                print("Verwende bereits existierende Video-Kopien (keine Neu-Kodierung nötig).")
                temp_copy_paths = [self.video_copies_map[original_path] for original_path in video_paths]
                needs_reencoding = False  # Bereits kodiert

                # Prüfe, ob alle Kopien noch existieren
                if all(os.path.exists(copy_path) for copy_path in temp_copy_paths):
                    self.parent.after(0, lambda: self.encoding_label.config(
                        text="Encoding: Verwende existierende Kopien"))
                    print(f"Alle {len(temp_copy_paths)} Kopien existieren noch.")
                else:
                    # Mindestens eine Kopie fehlt, muss neu erstellt werden
                    print("Einige Kopien fehlen, erstelle Videos neu...")
                    all_videos_cached = False
                    temp_copy_paths = []  # Zurücksetzen

            if not all_videos_cached:
                # Neue oder geänderte Video-Liste, Format prüfen und ggf. neu kodieren
                print(f"Prüfe Format von {len(video_paths)} Videos...")
                format_info = self._check_video_formats(video_paths)
                needs_reencoding = not format_info["compatible"]
                self.parent.after(0, self._update_encoding_info, format_info)

                # Diese Methode füllt jetzt auch self.metadata_cache
                print(f"Erstelle Video-Kopien (Re-Encoding: {needs_reencoding})...")
                temp_copy_paths = self._prepare_video_copies(video_paths, needs_reencoding)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            print(f"Starte Kombinierung von {len(temp_copy_paths)} Videos...")
            self.parent.after(0, lambda: self.status_label.config(
                text="Kombiniere Videos (schnell)...", fg="blue"))

            self.combined_video_path = self._create_fast_combined_video(temp_copy_paths)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            if self.combined_video_path and os.path.exists(self.combined_video_path):
                print(f"✅ Vorschau erfolgreich erstellt: {self.combined_video_path}")
                self.parent.after(0, self._update_ui_success, temp_copy_paths, needs_reencoding)
            else:
                if not self.cancellation_event.is_set():
                    print("❌ Vorschau konnte nicht erstellt werden")
                    self.parent.after(0, self._update_ui_error, "Vorschau konnte nicht erstellt werden")

        except Exception as e:
            # Fange die Abbruch-Exception von _check_for_cancellation ab
            if "abgebrochen" in str(e) or self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
            else:
                print(f"❌ Fehler in _create_combined_preview: {e}")
                import traceback
                traceback.print_exc()
                self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")
        finally:
            if self.parent.winfo_exists():
                self.parent.after(0, self._finalize_processing)

    def _finalize_processing(self):
        """
        Cleans up after a thread finishes and triggers a pending restart if requested.
        """
        self.processing_thread = None
        self.ffmpeg_process = None

        # NEU: Stelle den Button wieder her, wenn kein Neustart ansteht
        if not self.pending_restart_callback:
            if self.app:  # Stellt den "Erstellen" Button wieder her
                self.app._restore_button_state()

        if self.pending_restart_callback:
            callback = self.pending_restart_callback
            self.pending_restart_callback = None
            callback()

    def _create_fast_combined_video(self, video_paths):
        """Kombiniert Videos schnell ohne Re-Encoding (jetzt für die Kopien verwendet)"""
        concat_list_path = os.path.join(tempfile.gettempdir(), "preview_concat_list.txt")

        os.makedirs(os.path.dirname(concat_list_path), exist_ok=True)

        output_path = os.path.join(tempfile.gettempdir(), "preview_combined_fast.mp4")

        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video_path in video_paths:
                    # Escape Pfad für FFmpeg concat (besonders wichtig für Windows-Pfade)
                    escaped_path = os.path.abspath(video_path).replace('\\', '/')
                    f.write(f"file '{escaped_path}'\n")
        except Exception as e:
            print(f"Fehler beim Schreiben der concat-Liste: {e}")
            return None

        if self.cancellation_event.is_set():
            return None

        print(f"Kombiniere {len(video_paths)} Videos mit FFmpeg concat...")

        self.ffmpeg_process = subprocess.Popen([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list_path,
            "-c", "copy", "-movflags", "+faststart", output_path
        ], stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
            universal_newlines=True, encoding='utf-8', errors='replace',
            creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        # WICHTIG: Lese stderr um Pipe-Buffer-Overflow zu verhindern (verhindert Hängen!)
        stderr_lines = []

        while self.ffmpeg_process.poll() is None:
            if self.cancellation_event.is_set():
                print("Abbruch-Signal empfangen. Terminiere FFmpeg (concat)...")
                self.ffmpeg_process.terminate()
                self.ffmpeg_process.wait()
                self.ffmpeg_process = None
                try:
                    os.remove(concat_list_path)
                except OSError:
                    pass
                return None

            # Lese stderr um Buffer nicht volllaufen zu lassen
            try:
                line = self.ffmpeg_process.stderr.readline()
                if line:
                    stderr_lines.append(line)
                    # Zeige Fortschritt (optional)
                    if 'time=' in line.lower():
                        # Extrahiere Zeit für Fortschrittsanzeige
                        pass
            except:
                pass

            time.sleep(0.05)  # Kürzeres Intervall für bessere Responsiveness

        # Hole restlichen stderr-Output
        try:
            remaining_stderr = self.ffmpeg_process.stderr.read()
            if remaining_stderr:
                stderr_lines.append(remaining_stderr)
        except:
            pass

        returncode = self.ffmpeg_process.returncode
        self.ffmpeg_process = None

        try:
            os.remove(concat_list_path)
        except OSError as e:
            print(f"Fehler beim Löschen der temp. Datei: {e}")

        if returncode == 0:
            print(f"✅ Kombiniertes Video erstellt: {output_path}")
            return output_path
        else:
            if not self.cancellation_event.is_set():
                # Zeige FFmpeg-Fehler
                stderr_text = ''.join(stderr_lines)
                last_lines = '\n'.join(stderr_text.split('\n')[-15:])
                print(f"❌ Fast combine fehlgeschlagen (Code {returncode}).")
                print(f"FFmpeg Output:\n{last_lines}")
            return None

    def _check_video_formats(self, video_paths):
        if len(video_paths) <= 1:
            return {"compatible": True, "details": "Nur ein Video - kompatibel"}
        formats = []
        for video_path in video_paths:
            try:
                self._check_for_cancellation()  # Prüfe vor jedem blockierenden Aufruf
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
                if "abgebrochen" in str(e): raise  # Abbruch weiterleiten
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
            self.encoding_label.config(text=f"Encoding: Kompatibel (Fall A)", fg="green")
        else:
            self.encoding_label.config(text=f"Encoding: Standardisiert (Fall B)", fg="orange")

    def _update_ui_success(self, copy_paths, was_reencoded):
        """
        Aktualisiert UI nach erfolgreicher Vorschau-Erstellung.
        """
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)

        # Metadaten von den *Kopien* berechnen (jetzt aus dem Cache)
        total_duration_s = 0
        total_bytes = 0

        # Gehe über die *Originalpfade*, um den Cache zu lesen
        for original_path in self.last_video_paths:
            metadata = self.metadata_cache.get(original_path)
            if metadata:
                try:
                    total_duration_s += float(metadata.get("duration_sec_str", "0.0"))
                    total_bytes += metadata.get("size_bytes", 0)
                except:
                    pass  # Ignoriere fehlerhafte Cache-Einträge

        minutes, seconds = divmod(total_duration_s, 60)
        total_duration = f"{int(minutes):02d}:{int(seconds):02d}"
        total_size = self._format_size_bytes(total_bytes)

        self.duration_label.config(text=f"Gesamtdauer: {total_duration}")
        self.size_label.config(text=f"Dateigröße: {total_size}")
        self.clips_label.config(text=f"Anzahl Clips: {len(copy_paths)}")

        if was_reencoded:
            self.status_label.config(text="Vorschau bereit (standardisiert)", fg="green")
            self.encoding_label.config(text="Encoding: Standardisiert (Fall B)", fg="orange")
        else:
            self.status_label.config(text="Vorschau bereit (schnell)", fg="green")
            self.encoding_label.config(text="Encoding: Direkt kombiniert (Fall A)", fg="green")

        self.play_button.config(state="normal")
        self.action_button.config(state="disabled")

        clip_durations = self._get_clip_durations_seconds(copy_paths)
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.load_video(self.combined_video_path, clip_durations)

        # NEU: Entsperren Sie den Schneiden-Button, wenn Vorschau bereit ist
        if self.app and hasattr(self.app, 'drag_drop'):
            self.app.drag_drop.set_cut_button_enabled(True)

    def _update_ui_error(self, error_msg):
        """Aktualisiert UI bei Fehler"""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text=error_msg, fg="red")
        self.clear_preview_info()
        self.play_button.config(state="disabled")
        self.action_button.config(text="🔄 Erneut versuchen",
                                  command=self.retry_creation,
                                  state="normal")
        self.combined_video_path = None
        self._cleanup_temp_copies()

    def register_new_copy(self, original_placeholder: str, new_copy_path: str):
        """
        Fügt ein neues Mapping für eine geteilte Datei hinzu.
        """
        if original_placeholder in self.video_copies_map:
            print(f"Warnung: Platzhalter {original_placeholder} existierte bereits. Wird überschrieben.")

        self.video_copies_map[original_placeholder] = new_copy_path
        print(f"Neue Kopie registriert: {original_placeholder} -> {new_copy_path}")

    def regenerate_preview_after_cut(self, new_original_paths_list):
        """
        Startet eine Aktualisierung der kombinierten Vorschau, nachdem eine
        Kopie extern (z.B. durch den Cutter) geändert wurde.
        """
        print(
            f"Regeneriere Vorschau. Alte Originale: {len(self.last_video_paths) if self.last_video_paths else 0}, Neue Originale: {len(new_original_paths_list)}")

        if self.processing_thread and self.processing_thread.is_alive():
            print("Regenerierung zurückgestellt, da ein anderer Prozess läuft.")
            self.pending_restart_callback = lambda: self.regenerate_preview_after_cut(new_original_paths_list)
            self.cancel_creation()
            return

        self.last_video_paths = new_original_paths_list

        copy_paths = self.get_all_copy_paths()

        if not copy_paths:
            print("Keine Kopien zum Regenerieren gefunden.")
            self.clear_preview()
            return

        self.cancellation_event.clear()
        self.processing_thread = threading.Thread(target=self._regenerate_task, args=(copy_paths,))
        self.processing_thread.start()

    def _regenerate_task(self, copy_paths):
        """Thread-Funktion, die nur das Kombinieren der (bereits vorhandenen) Kopien durchführt."""

        self.parent.after(0, lambda: self.status_label.config(text="Aktualisiere Vorschau nach Schnitt...", fg="blue"))
        self.parent.after(0,
                          lambda: self.action_button.config(text="⏹ Erstellung abbrechen", command=self.cancel_creation,
                                                            state="normal"))

        try:
            new_combined_path = self._create_fast_combined_video(copy_paths)

            if self.cancellation_event.is_set():
                self.parent.after(0, self._update_ui_cancelled)
                return

            if new_combined_path and os.path.exists(new_combined_path):
                self.combined_video_path = new_combined_path
                self.parent.after(0, self._update_ui_success_after_cut, copy_paths)
            else:
                if not self.cancellation_event.is_set():
                    self.parent.after(0, self._update_ui_error, "Vorschau-Aktualisierung fehlgeschlagen")

        except Exception as e:
            if not self.cancellation_event.is_set():
                print(f"Fehler in _regenerate_task: {e}")
                self.parent.after(0, self._update_ui_error, f"Fehler: {str(e)}")
            else:
                self.parent.after(0, self._update_ui_cancelled)
        finally:
            if self.parent.winfo_exists():
                self.parent.after(0, self._finalize_processing)

    def _update_ui_success_after_cut(self, copy_paths):
        """Aktualisiert die UI nach einer erfolgreichen *Regenerierung* (Schnitt)."""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)

        # Metadaten von den (möglicherweise geschnittenen) Kopien berechnen (aus Cache)
        total_duration_s = 0
        total_bytes = 0

        for original_path in self.last_video_paths: # self.last_video_paths wurde aktualisiert
            metadata = self.metadata_cache.get(original_path)
            if metadata:
                try:
                    total_duration_s += float(metadata.get("duration_sec_str", "0.0"))
                    total_bytes += metadata.get("size_bytes", 0)
                except:
                    pass

        minutes, seconds = divmod(total_duration_s, 60)
        total_duration = f"{int(minutes):02d}:{int(seconds):02d}"
        total_size = self._format_size_bytes(total_bytes)

        self.duration_label.config(text=f"Gesamtdauer: {total_duration}")
        self.size_label.config(text=f"Dateigröße: {total_size}")
        self.clips_label.config(text=f"Anzahl Clips: {len(self.last_video_paths)}")

        self.status_label.config(text="Vorschau nach Schnitt aktualisiert", fg="green")
        self.play_button.config(state="normal")
        self.action_button.config(state="disabled")

        # NEU: Video-Player aktualisieren
        clip_durations = self._get_clip_durations_seconds(copy_paths)
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.load_video(self.combined_video_path, clip_durations)

    def _get_single_video_duration_str(self, video_path):
        """Hilfsmethode: Holt die Dauer EINES Videos als String in Sekunden (z.B. '12.34'). (Blockierend)"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
                capture_output=True, text=True, timeout=5, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            if result.returncode == 0 and result.stdout:
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, ValueError):
            pass
        return "0.0"

    def _calculate_total_duration(self, video_paths):
        """Veraltet - wird nicht mehr verwendet, da _update_ui_success jetzt Cache nutzt"""
        # Diese Methode wird nicht mehr verwendet
        # Der Cache wird in _update_ui_success verwendet
        pass

    def _calculate_total_size(self, video_paths):
        """Veraltet (wird nicht mehr verwendet, da _update_ui_success jetzt Cache nutzt), aber als Fallback behalten"""
        total_bytes = sum(os.path.getsize(p) for p in video_paths if os.path.exists(p))
        return self._format_size_bytes(total_bytes)

    def _format_size_bytes(self, total_bytes):
        """Formatiert Bytes in einen lesbaren String."""
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

    def _update_ui_cancelled(self, event=None):
        """Updates UI after creation was cancelled."""
        if self.progress_handler: self.parent.after(0, self.progress_handler.reset)
        self.status_label.config(text="Vorschau-Erstellung abgebrochen", fg="orange")
        self.clear_preview_info()
        self.play_button.config(state="disabled")
        self.action_button.config(text="🔄 Erneut versuchen",
                                  command=self.retry_creation,
                                  state="normal")
        self.combined_video_path = None
        self._cleanup_temp_copies()

    def cancel_creation(self):
        """Signals the processing thread to cancel the video creation."""
        if self.processing_thread and self.processing_thread.is_alive():
            self.status_label.config(text="Abbruch wird eingeleitet...", fg="orange")
            self.action_button.config(state="disabled")
            self.cancellation_event.set()

    def retry_creation(self):
        """Retries the preview creation with the last used *original* video paths."""
        if not self.last_video_paths:
            print("No previous video paths available to retry.")
            return
        self.update_preview(self.last_video_paths)

    def clear_preview(self):
        """Setzt die Vorschau zurück und löscht die temporäre Datei"""
        self.pending_restart_callback = None
        self.cancel_creation()

        # KORREKTUR: Zuerst Player entladen, um WinError 32 zu vermeiden
        if self.app and hasattr(self.app, 'video_player') and self.app.video_player:
            self.app.video_player.unload_video()

        # Erst DANACH die kombinierten Dateien löschen
        if self.combined_video_path and os.path.exists(self.combined_video_path):
            try:
                os.remove(self.combined_video_path)
            except OSError as e:
                print(f"Could not delete temp preview file: {e}")

        # Und die restlichen Kopien
        self._cleanup_temp_copies()  # Löscht temp_dir, video_copies_map und metadata_cache

        self.combined_video_path = None
        self.last_video_paths = None
        self.clear_preview_info()
        self.status_label.config(text="Keine Vorschau verfügbar", fg="gray")
        self.play_button.config(state="disabled")
        self.action_button.config(text="⏹ Erstellung abbrechen",
                                  command=self.cancel_creation,
                                  state="disabled")

    def clear_preview_info(self):
        """Helper to clear all text labels."""
        self.duration_label.config(text="Gesamtdauer: --:--")
        self.size_label.config(text="Dateigröße: --")
        self.clips_label.config(text=f"Anzahl Clips: {len(self.last_video_paths) if self.last_video_paths else '--'}")
        self.encoding_label.config(text="Encoding: --", fg="gray")

    def get_combined_video_path(self):
        """Gibt den Pfad des kombinierten Videos zurück"""
        return self.combined_video_path

    # --- NEUE METHODEN (Cache-Verwaltung) ---

    def _cache_metadata_for_copy(self, original_path: str, copy_path: str):
        """
        [THREAD-SAFE] Liest Metadaten von der Kopie und speichert sie im Cache.
        """
        if not os.path.exists(copy_path):
            print(f"Kann Metadaten nicht cachen: Kopie {copy_path} existiert nicht.")
            return

        try:
            # Hole Dauer als String 'MM:SS'
            duration_str = self._get_video_duration(copy_path)
            # Hole Dauer als String 'Sekunden.ms'
            duration_sec_str = self._get_single_video_duration_str(copy_path)
            # Hole Größe
            size_bytes = os.path.getsize(copy_path)
            size_str = self._format_size_bytes(size_bytes)
            # Hole Datum/Zeit
            date_str = self._get_file_date(copy_path)
            time_str = self._get_file_time(copy_path)

            self.metadata_cache[original_path] = {
                "duration": duration_str,
                "duration_sec_str": duration_sec_str,
                "size": size_str,
                "size_bytes": size_bytes,
                "date": date_str,
                "timestamp": time_str
            }

            # NEU: Aktualisiere die Tabelle im Haupt-Thread, wenn Metadaten hinzugefügt werden
            if self.app and hasattr(self.app, 'drag_drop'):
                self.parent.after(0, self.app.drag_drop._update_video_table)

        except Exception as e:
            print(f"Fehler beim Cachen der Metadaten für {original_path}: {e}")
            self.metadata_cache[original_path] = {
                "duration": "FEHLER", "size": "FEHLER", "date": "FEHLER", "timestamp": "FEHLER"
            }

    def refresh_metadata_async(self, original_paths_list: List[str], on_complete_callback: Callable):
        """
        Startet einen Thread, um die Metadaten für bestimmte Clips
        (z.B. nach einem Schnitt) neu zu berechnen und zu cachen.
        """
        print(f"App: Starte asynchrone Metadaten-Aktualisierung für {len(original_paths_list)} Clip(s)...")
        threading.Thread(
            target=self._run_refresh_metadata_task,
            args=(original_paths_list, on_complete_callback),
            daemon=True
        ).start()

    def _run_refresh_metadata_task(self, original_paths_list: List[str], on_complete_callback: Callable):
        """
        [THREAD] Berechnet Metadaten neu und ruft den Callback auf.
        """
        for original_path in original_paths_list:
            copy_path = self.get_copy_path(original_path)
            if copy_path:
                print(f"Task: Aktualisiere Metadaten für {os.path.basename(original_path)}...")
                self._cache_metadata_for_copy(original_path, copy_path)
            else:
                print(f"Task: Überspringe Metadaten-Aktualisierung, keine Kopie für {original_path} gefunden.")

        # Rufe den Callback im Haupt-Thread auf
        self.parent.after(0, on_complete_callback)

    def get_copy_path(self, original_path):
        """Gibt den Pfad der temporären Kopie für einen Originalpfad zurück."""
        return self.video_copies_map.get(original_path)

    def get_cached_metadata(self, original_path: str) -> Dict:
        """Gibt das gecachte Metadaten-Wörterbuch für einen Originalpfad zurück."""
        return self.metadata_cache.get(original_path)

    def clear_metadata_cache(self):
        """Leert den Metadaten-Cache (z.B. wenn alle Videos entfernt werden)."""
        self.metadata_cache.clear()

    def remove_path_from_cache(self, original_path: str):
        """Entfernt einen bestimmten Pfad aus Cache und Map."""
        if original_path in self.video_copies_map:
            del self.video_copies_map[original_path]
        if original_path in self.metadata_cache:
            del self.metadata_cache[original_path]

    def get_all_copy_paths(self):
        """
        Gibt eine Liste aller temporären Kopie-Pfade zurück,
        basierend auf der *aktuellen* self.last_video_paths-Liste.
        """
        if not self.last_video_paths:
            return []

        paths = [self.video_copies_map.get(orig_path) for orig_path in self.last_video_paths]
        return [p for p in paths if p and os.path.exists(p)]

    # --- Interne Metadaten-Helfer (laufen im Thread oder als Fallback) ---

    def _get_video_duration(self, video_path):
        """Ermittelt die Dauer des Videos (Blockierend)"""
        try:
            duration_str = self._get_single_video_duration_str(video_path)
            seconds = float(duration_str)
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}:{secs:02d}"
        except:
            return "?:??"

    def _get_file_size(self, file_path):
        """Ermittelt die Dateigröße"""
        try:
            size_bytes = os.path.getsize(file_path)
            return self._format_size_bytes(size_bytes)
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

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)
