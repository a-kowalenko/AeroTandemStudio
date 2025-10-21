import threading
import os
import tempfile
import subprocess
from datetime import date
from moviepy import VideoFileClip

from .logger import CancellableProgressBarLogger, CancellationError
from ..utils.file_utils import sanitize_filename


class VideoProcessor:
    def __init__(self, progress_callback=None, status_callback=None):
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.cancel_event = threading.Event()
        self.logger = CancellableProgressBarLogger(self.cancel_event)

    def create_video(self, form_data, video_paths):
        """Startet die Videoerstellung in einem separaten Thread"""
        thread = threading.Thread(
            target=self._video_creation_task,
            args=(form_data, video_paths)
        )
        thread.start()
        return thread

    def cancel_process(self):
        """Bricht die Videoerstellung ab"""
        self.cancel_event.set()

    def reset_cancel_event(self):
        """Setzt das Cancel-Event zurück"""
        self.cancel_event.clear()

    def _video_creation_task(self, form_data, video_paths):
        """Hauptlogik für die Videoerstellung mit mehreren Videos"""
        try:
            self._execute_video_creation(form_data, video_paths)
        except CancellationError:
            self._handle_cancellation()
        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _execute_video_creation(self, form_data, video_paths):
        load = form_data["load"]
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = form_data["dauer"]
        ort = form_data["ort"]
        speicherort = form_data["speicherort"]
        outside_video = form_data["outside_video"]

        if not video_paths:
            raise ValueError("Keine Video-Dateien ausgewählt")

        full_output_path = ""
        temp_files = []

        try:
            # Schritt 1: Videoinformationen des ersten Videos lesen (für Konsistenz)
            self._update_progress(1)
            first_video_info = self._get_video_info(video_paths[0])
            clip_width, clip_height, clip_fps = first_video_info

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

            # Schritt 4: Concat-Liste für alle Videos erstellen
            self._update_progress(4)
            concat_list_path = os.path.join(tempfile.gettempdir(), "concat_list.txt")
            temp_files.append(concat_list_path)

            # Erstelle Concat-Liste mit Titelclip und allen Videos
            with open(concat_list_path, "w", encoding="utf-8") as f:
                f.write(f"file '{os.path.abspath(temp_titel_clip_path)}'\n")
                for video_path in video_paths:
                    f.write(f"file '{os.path.abspath(video_path)}'\n")

            # Schritt 5: Videos ohne Rekodierung zusammenfügen
            self._update_progress(5)
            temp_video_noaudio = os.path.join(tempfile.gettempdir(), "temp_video_noaudio.mp4")
            temp_files.append(temp_video_noaudio)

            subprocess.run([
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                temp_video_noaudio
            ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            # Schritt 6: Audio aus allen Videos extrahieren und kombinieren
            self._update_progress(6)
            combined_audio = self._combine_audio_tracks(video_paths, dauer, temp_files)

            # Schritt 7: Output-Pfad generieren
            full_output_path = self._generate_output_path(
                load, gast, tandemmaster, videospringer,
                datum, speicherort, outside_video
            )

            # Schritt 8: Finales Video mit kombinierter Audio erstellen
            self._update_progress(7)
            self._create_final_video(
                temp_video_noaudio, combined_audio, full_output_path
            )

            # Fertig
            self._update_progress(8)
            self._show_success_message(full_output_path)

        except Exception as e:
            if full_output_path and os.path.exists(full_output_path):
                os.remove(full_output_path)
            raise e
        finally:
            self._cleanup_temp_files(temp_files)

    def _get_video_info(self, video_path):
        """Ermittelt Video-Informationen"""
        user_clip = VideoFileClip(video_path)
        clip_width, clip_height = user_clip.size
        clip_fps = user_clip.fps or 30
        user_clip.close()
        return clip_width, clip_height, clip_fps

    def _combine_audio_tracks(self, video_paths, intro_duration, temp_files):
        """Kombiniert Audio-Spuren aus allen Videos, nur das erste Audio erhält das Intro-Delay"""
        import shutil

        temp_audio_files = []
        delayed_audio_files = []

        try:
            # Audio aus jedem Video extrahieren
            for i, video_path in enumerate(video_paths):
                extracted_audio = os.path.join(tempfile.gettempdir(), f"audio_{i}.aac")
                temp_audio_files.append(extracted_audio)

                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", video_path,
                    "-vn",
                    "-acodec", "copy",
                    extracted_audio
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            # Nur das erste Audio mit Delay versehen
            for i, audio_file in enumerate(temp_audio_files):
                if i == 0:
                    delayed_audio = os.path.join(tempfile.gettempdir(), f"delayed_audio_{i}.aac")
                    delayed_audio_files.append(delayed_audio)
                    subprocess.run([
                        "ffmpeg", "-y",
                        "-i", audio_file,
                        "-af", f"adelay={int(intro_duration * 1000)}|{int(intro_duration * 1000)}",
                        delayed_audio
                    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                else:
                    # Die restlichen Audiospuren ohne Delay
                    delayed_audio_files.append(audio_file)

            # Alle Audios nacheinander zusammenfügen
            combined_audio = os.path.join(tempfile.gettempdir(), "combined_audio.aac")
            temp_files.append(combined_audio)

            if len(delayed_audio_files) == 1:
                shutil.copy2(delayed_audio_files[0], combined_audio)
            else:
                # Erstelle eine temporäre Liste für ffmpeg concat
                concat_list_path = os.path.join(tempfile.gettempdir(), "audio_concat_list.txt")
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for audio_file in delayed_audio_files:
                        f.write(f"file '{audio_file}'\n")
                temp_files.append(concat_list_path)

                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", concat_list_path,
                    "-c", "copy",
                    combined_audio
                ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

            return combined_audio

        finally:
            # Temporäre Audio-Dateien bereinigen
            for audio_file in temp_audio_files:
                try:
                    if os.path.exists(audio_file):
                        os.remove(audio_file)
                except:
                    pass
            for i, audio_file in enumerate(delayed_audio_files):
                # Nur die delayed Audios löschen, die wirklich delayed wurden (also i==0)
                if i == 0:
                    try:
                        if os.path.exists(audio_file):
                            os.remove(audio_file)
                    except:
                        pass

    def _get_video_duration_ffprobe(self, video_path):
        """Ermittelt die Dauer eines Videos mit ffprobe"""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error', '-show_entries',
                'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ], capture_output=True, text=True)

            if result.returncode == 0:
                return float(result.stdout.strip())
        except:
            pass

        # Fallback: Schätze 10 Sekunden
        return 10.0

    # Die restlichen Methoden (_prepare_text_overlay, _create_title_clip, etc.)
    # bleiben wie in der vorherigen Version, aber mit angepassten Progress-Schritten

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

    def _generate_output_path(self, load, gast, tandemmaster, videospringer, datum, speicherort, outside_video):
        """Generiert den finalen Output-Pfad"""
        datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
        datum_formatiert = datum_obj.strftime("%Y%m%d")

        output_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video:
            output_filename += f"_V_{videospringer}"
        output_filename += "_combined.mp4"  # Kennzeichnung für kombinierte Videos

        return os.path.join(speicherort, sanitize_filename(output_filename))

    def _create_final_video(self, video_path, audio_path, output_path):
        """Kombiniert Video und Audio zum finalen Ergebnis"""
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",  # Verwende AAC für bessere Kompatibilität
            "-shortest",  # Stoppt wenn das kürzeste Stream-Ende erreicht ist
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    def _update_progress(self, step, total_steps=8):
        """Aktualisiert den Fortschritt"""
        if self.progress_callback:
            self.progress_callback(step, total_steps)

    def _show_success_message(self, output_path):
        """Zeigt Erfolgsmeldung an"""
        if self.status_callback:
            self.status_callback("success", f"Das kombinierte Video wurde unter '{output_path}' gespeichert.")

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