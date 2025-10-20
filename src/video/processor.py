import threading
import os
import tempfile
import subprocess
from datetime import date
from tkinter import messagebox
from moviepy import VideoFileClip

from .logger import CancellableProgressBarLogger, CancellationError
from ..utils.file_utils import sanitize_filename


class VideoProcessor:
    def __init__(self, progress_callback=None, status_callback=None):
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.cancel_event = threading.Event()
        self.logger = CancellableProgressBarLogger(self.cancel_event)

    def create_video(self, form_data, video_path):
        """Startet die Videoerstellung in einem separaten Thread"""
        thread = threading.Thread(
            target=self._video_creation_task,
            args=(form_data, video_path)
        )
        thread.start()
        return thread

    def cancel_process(self):
        """Bricht die Videoerstellung ab"""
        self.cancel_event.set()

    def reset_cancel_event(self):
        """Setzt das Cancel-Event zurück"""
        self.cancel_event.clear()

    def _video_creation_task(self, form_data, dropped_video_path):
        """Hauptlogik für die Videoerstellung"""
        try:
            self._execute_video_creation(form_data, dropped_video_path)
        except CancellationError:
            self._handle_cancellation()
        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _execute_video_creation(self, form_data, dropped_video_path):
        load = form_data["load"]
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = form_data["dauer"]
        ort = form_data["ort"]
        speicherort = form_data["speicherort"]
        outside_video = form_data["outside_video"]

        full_output_path = ""
        temp_files = []

        try:
            # Schritt 1: Videoinformationen lesen
            self._update_progress(1)
            user_clip = VideoFileClip(dropped_video_path)
            clip_width, clip_height = user_clip.size
            clip_fps = user_clip.fps or 30
            user_clip.close()

            # Schritt 2: Textinhalte vorbereiten
            self._update_progress(2)
            drawtext_filter = self._prepare_text_overlay(
                gast, tandemmaster, videospringer, datum, ort,
                clip_height, outside_video
            )

            temp_titel_clip_path = os.path.join(tempfile.gettempdir(), "titel_intro.mp4")
            temp_files.append(temp_titel_clip_path)

            if not os.path.exists("assets/hintergrund.png"):
                raise FileNotFoundError("hintergrund.png fehlt im assets/ Ordner")

            # Schritt 3: Titelclip ohne Audio erzeugen
            self._update_progress(3)
            self._create_title_clip(
                temp_titel_clip_path, dauer, clip_fps, drawtext_filter
            )

            # Schritt 4: Audio verarbeiten
            self._update_progress(4)
            extracted_audio, delayed_audio = self._process_audio(
                dropped_video_path, dauer, temp_files
            )

            # Schritt 5: Output-Pfad generieren
            full_output_path = self._generate_output_path(
                load, gast, tandemmaster, videospringer,
                datum, speicherort, outside_video
            )

            # Schritt 6: Videos zusammenfügen
            self._update_progress(5)
            temp_video_noaudio = self._concat_videos(
                temp_titel_clip_path, dropped_video_path, temp_files
            )

            # Schritt 7: Finales Video mit Audio erstellen
            self._update_progress(6)
            self._create_final_video(
                temp_video_noaudio, delayed_audio, full_output_path
            )

            # Fertig
            self._update_progress(7)
            self._show_success_message(full_output_path)

        except Exception as e:
            if full_output_path and os.path.exists(full_output_path):
                os.remove(full_output_path)
            raise e
        finally:
            self._cleanup_temp_files(temp_files)

    def _prepare_text_overlay(self, gast, tandemmaster, videospringer, datum, ort, clip_height, outside_video):
        """Bereitet die Text-Overlays für das Video vor"""

        def ffmpeg_escape(text: str) -> str:
            return text.replace(":", r"\:").replace("'", r"\''").replace(",", r"\,")

        text_inhalte = [f"Gast: {gast}", f"Tandemmaster: {tandemmaster}"]
        if outside_video:
            text_inhalte.append(f"Videospringer: {videospringer}")
        text_inhalte.extend([f"Datum: {datum}", f"Ort: {ort}"])
        text_inhalte = [ffmpeg_escape(t) for t in text_inhalte]

        font_size = int(clip_height / 18)
        y = clip_height * 0.15
        y_step = clip_height * 0.15
        drawtext_cmds = []

        for t in text_inhalte:
            drawtext_cmds.append(
                f"drawtext=text='{t}':x=(w-text_w)/2:y={int(y)}:fontsize={font_size}:fontcolor=black:font='Arial'"
            )
            y += y_step

        return ",".join(drawtext_cmds)

    def _create_title_clip(self, output_path, dauer, fps, drawtext_filter):
        """Erstellt den Titel-Clip mit Text-Overlay"""
        subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", "assets/hintergrund.png",
            "-vf", drawtext_filter,
            "-t", str(dauer),
            "-r", str(fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _process_audio(self, video_path, dauer, temp_files):
        """Extrahiert und verschiebt die Audio-Spur"""
        extracted_audio = os.path.join(tempfile.gettempdir(), "original_audio.aac")
        delayed_audio = os.path.join(tempfile.gettempdir(), "delayed_audio.aac")

        temp_files.extend([extracted_audio, delayed_audio])

        # Audio extrahieren
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "copy",
            extracted_audio
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        # Audio verschieben
        intro_ms = int(dauer * 1000)
        subprocess.run([
            "ffmpeg", "-y",
            "-i", extracted_audio,
            "-af", f"adelay={intro_ms}|{intro_ms}",
            delayed_audio
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        return extracted_audio, delayed_audio

    def _generate_output_path(self, load, gast, tandemmaster, videospringer, datum, speicherort, outside_video):
        """Generiert den finalen Output-Pfad"""
        datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
        datum_formatiert = datum_obj.strftime("%Y%m%d")

        output_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video:
            output_filename += f"_V_{videospringer}"
        output_filename += ".mp4"

        return os.path.join(speicherort, sanitize_filename(output_filename))

    def _concat_videos(self, title_clip_path, video_path, temp_files):
        """Fügt Titel und Hauptvideo zusammen"""
        concat_list_path = os.path.join(tempfile.gettempdir(), "concat_list.txt")
        temp_video_noaudio = os.path.join(tempfile.gettempdir(), "temp_video_noaudio.mp4")

        temp_files.extend([concat_list_path, temp_video_noaudio])

        with open(concat_list_path, "w", encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(title_clip_path)}'\n")
            f.write(f"file '{os.path.abspath(video_path)}'\n")

        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            temp_video_noaudio
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        return temp_video_noaudio

    def _create_final_video(self, video_path, audio_path, output_path):
        """Kombiniert Video und Audio zum finalen Ergebnis"""
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "copy",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _update_progress(self, step, total_steps=7):
        """Aktualisiert den Fortschritt"""
        if self.progress_callback:
            self.progress_callback(step, total_steps)

    def _show_success_message(self, output_path):
        """Zeigt Erfolgsmeldung an"""
        if self.status_callback:
            self.status_callback("success", f"Das Video wurde unter '{output_path}' gespeichert.")

    def _handle_cancellation(self):
        """Behandelt Abbruch durch Benutzer"""
        if self.status_callback:
            self.status_callback("cancelled", "Erstellung abgebrochen.")

    def _handle_error(self, error):
        """Behandelt Fehler während der Verarbeitung"""
        if self.status_callback:
            self.status_callback("error", f"Fehler bei der Videoerstellung:\n{error}")

    def _cleanup_temp_files(self, temp_files):
        """Räumt temporäre Dateien auf"""
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    def _cleanup(self):
        """Führt allgemeine Cleanup-Aufgaben durch"""
        self.reset_cancel_event()