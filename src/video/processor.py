import shutil
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

    def create_video_with_intro_only(self, form_data, combined_video_path, photo_paths=None):
        """Erstellt nur noch das Intro und hängt es vor das kombinierte Video"""
        thread = threading.Thread(
            target=self._video_creation_with_intro_only_task,
            args=(form_data, combined_video_path, photo_paths)
        )
        thread.start()
        return thread

    def _video_creation_with_intro_only_task(self, form_data, combined_video_path, photo_paths=None):
        """Hauptlogik für das Hinzufügen des Intros zum kombinierten Video"""
        try:
            self._execute_video_creation_with_intro_only(form_data, combined_video_path, photo_paths)
        except CancellationError:
            self._handle_cancellation()
        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _execute_video_creation_with_intro_only(self, form_data, combined_video_path, photo_paths=None):
        """Fügt nur das Intro zum bereits kombinierten Video hinzu"""
        load = form_data["load"]
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = form_data["dauer"]
        ort = form_data["ort"]
        speicherort = form_data["speicherort"]
        outside_video = form_data["outside_video"]
        upload_to_server = form_data["upload_to_server"]

        full_output_path = ""
        temp_files = []

        try:
            # Schritt 1: Videoinformationen des kombinierten Videos lesen
            self._update_progress(1)
            self._update_status("Ermittle Videoinformationen...")
            video_info = self._get_video_info(combined_video_path)
            clip_width, clip_height, clip_fps = video_info

            # Schritt 2: Textinhalte vorbereiten
            self._update_progress(2)
            self._update_status("Bereite Text-Overlays vor...")
            drawtext_filter = self._prepare_text_overlay(
                gast, tandemmaster, videospringer, datum, ort,
                clip_height, outside_video
            )

            temp_titel_clip_path = os.path.join(tempfile.gettempdir(), "titel_intro.mp4")
            temp_files.append(temp_titel_clip_path)

            if not os.path.exists("assets/hintergrund.png"):
                raise FileNotFoundError("hintergrund.png fehlt im assets/ Ordner")

            # Schritt 3: Titelclip OHNE Audio erstellen
            self._update_progress(3)
            self._update_status("Erstelle Titelclip...")
            self._create_title_clip_no_audio(
                temp_titel_clip_path, dauer, clip_fps, drawtext_filter
            )

            # Schritt 4: Concat-Liste für Intro + kombiniertes Video erstellen
            self._update_progress(4)
            self._update_status("Erstelle Concat-Liste...")
            concat_list_path = os.path.join(tempfile.gettempdir(), "final_concat_list.txt")
            temp_files.append(concat_list_path)

            with open(concat_list_path, "w", encoding="utf-8") as f:
                f.write(f"file '{os.path.abspath(temp_titel_clip_path)}'\n")
                f.write(f"file '{os.path.abspath(combined_video_path)}'\n")

            # Schritt 5: Temporäres Video ohne Audio erstellen (nur Konkatenierung)
            self._update_progress(5)
            self._update_status("Kombiniere Videos ohne Audio...")
            temp_video_no_audio = os.path.join(tempfile.gettempdir(), "temp_no_audio.mp4")
            temp_files.append(temp_video_no_audio)

            # Videos ohne Audio konkatenieren
            subprocess.run([
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c", "copy",
                "-an",  # KEINE Audio-Spur im temporären Video
                temp_video_no_audio
            ], check=True, capture_output=True, text=True)

            # Schritt 6: Output-Pfad generieren
            self._update_progress(6)
            self._update_status("Generiere Ausgabe-Pfad...")
            full_output_path = self._generate_output_path(
                load, gast, tandemmaster, videospringer,
                datum, speicherort, outside_video
            )

            # Schritt 7: Finales Video mit ursprünglicher Audio erstellen
            self._update_progress(7)
            self._update_status("Erstelle finales Video mit Audio...")
            self._create_final_video_with_original_audio(
                temp_video_no_audio, combined_video_path, full_output_path, dauer
            )

            # Schritt 8: Fotos in Output-Verzeichnis kopieren
            self._update_progress(8)
            if photo_paths:
                self._update_status("Kopiere Fotos in Ausgabe-Verzeichnis...")
                self._copy_photos_to_output_directory(photo_paths, full_output_path)

            # Schritt 9: Auf Server uploaden falls gewünscht
            self._update_progress(9)
            server_message = ""
            if upload_to_server:
                self._update_status("Lade Video auf Server hoch...")
                success, message, server_path = self._upload_to_server(full_output_path)
                server_message = f"\nServer: {message}" if message else ""
            else:
                success = True
                message = ""

            # Fertig
            self._update_progress(10)
            self._show_success_message(full_output_path, server_message)

        except Exception as e:
            if full_output_path and os.path.exists(full_output_path):
                os.remove(full_output_path)
            raise e
        finally:
            self._cleanup_temp_files(temp_files)

    def _copy_photos_to_output_directory(self, photo_paths, output_video_path):
        """Kopiert alle Fotos in ein Foto-Unterverzeichnis"""
        if not photo_paths:
            return

        # Verzeichnis des Output-Videos ermitteln
        output_dir = os.path.dirname(output_video_path)
        photos_dir = os.path.join(output_dir, "Fotos")

        try:
            # Foto-Verzeichnis erstellen
            os.makedirs(photos_dir, exist_ok=True)

            # Fotos kopieren
            copied_count = 0
            for photo_path in photo_paths:
                if os.path.exists(photo_path):
                    filename = os.path.basename(photo_path)
                    destination_path = os.path.join(photos_dir, filename)

                    # Datei kopieren (überschreiben falls existiert)
                    shutil.copy2(photo_path, destination_path)
                    copied_count += 1
                    print(f"Foto kopiert: {filename}")

            print(f"{copied_count} Foto(s) nach '{photos_dir}' kopiert")

        except Exception as e:
            print(f"Fehler beim Kopieren der Fotos: {e}")

    def _create_title_clip_no_audio(self, output_path, dauer, fps, drawtext_filter):
        """Erstellt den Titel-Clip mit Text-Overlay OHNE Audio"""
        print("Erstelle Titelclip ohne Audio...")
        result = subprocess.run([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", "assets/hintergrund.png",
            "-vf", drawtext_filter,
            "-t", str(dauer),
            "-r", str(fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "fast",
            "-an",  # KEINE Audio-Spur
            output_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Fehler beim Titelclip-Erstellen: {result.stderr}")
            raise Exception(f"Titelclip-Erstellung fehlgeschlagen: {result.stderr}")

    def _create_final_video_with_original_audio(self, video_with_intro_path, original_video_path, output_path,
                                                intro_duration):
        """Erstellt finales Video mit der originalen Audio (verschoben um Intro-Dauer)"""
        print("Erstelle finales Video mit verschobener Audio...")

        # Extrahiere Audio aus dem originalen kombinierten Video
        temp_audio_path = os.path.join(tempfile.gettempdir(), "original_audio.aac")

        # Audio extrahieren
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", original_video_path,
            "-vn",
            "-acodec", "copy",
            temp_audio_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Fehler beim Audio-Extrahieren: {result.stderr}")
            raise Exception(f"Audio-Extraktion fehlgeschlagen: {result.stderr}")

        # Audio um Intro-Dauer verschieben
        temp_delayed_audio_path = os.path.join(tempfile.gettempdir(), "delayed_audio.aac")
        intro_ms = int(intro_duration * 1000)

        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", temp_audio_path,
            "-af", f"adelay={intro_ms}|{intro_ms}",
            temp_delayed_audio_path
        ], capture_output=True, text=True)

        if result.returncode != 0:
            print(f"Fehler beim Audio-Verschieben: {result.stderr}")
            raise Exception(f"Audio-Verschieben fehlgeschlagen: {result.stderr}")

        # Kombiniere Video (mit Intro) mit verschobener Audio
        result = subprocess.run([
            "ffmpeg", "-y",
            "-i", video_with_intro_path,  # Video mit Intro aber ohne Audio
            "-i", temp_delayed_audio_path,  # Verschobene Audio
            "-c:v", "copy",
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path
        ], capture_output=True, text=True)

        # Temporäre Audio-Dateien löschen
        try:
            os.remove(temp_audio_path)
            os.remove(temp_delayed_audio_path)
        except:
            pass

        if result.returncode != 0:
            print(f"Fehler beim Final-Video-Erstellen: {result.stderr}")
            raise Exception(f"Final-Video-Erstellung fehlgeschlagen: {result.stderr}")

    def _get_video_info(self, video_path):
        """Ermittelt Video-Informationen"""
        try:
            user_clip = VideoFileClip(video_path)
            clip_width, clip_height = user_clip.size
            clip_fps = user_clip.fps or 30
            user_clip.close()
            return clip_width, clip_height, clip_fps
        except:
            # Fallback-Werte
            return 1920, 1080, 30

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

    def _generate_output_path(self, load, gast, tandemmaster, videospringer, datum, speicherort, outside_video):
        """Generiert den finalen Output-Pfad in einem gleichnamigen Verzeichnis"""
        try:
            datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
            datum_formatiert = datum_obj.strftime("%Y%m%d")
        except:
            # Fallback: aktuelles Datum verwenden
            from datetime import datetime
            datum_formatiert = datetime.now().strftime("%Y%m%d")

        # Basis-Dateiname ohne Endung
        base_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video:
            base_filename += f"_V_{videospringer}"

        # Verzeichnis erstellen
        output_dir = os.path.join(speicherort, sanitize_filename(base_filename))
        os.makedirs(output_dir, exist_ok=True)

        # Vollständiger Pfad mit Dateiname
        output_filename = f"{base_filename}.mp4"
        full_output_path = os.path.join(output_dir, sanitize_filename(output_filename))

        return full_output_path

    def _upload_to_server(self, local_video_path):
        """Lädt das erstellte Verzeichnis auf den Server hoch"""
        try:
            from ..utils.file_utils import upload_to_server_simple

            # Verzeichnis des Videos ermitteln
            video_dir = os.path.dirname(local_video_path)

            # Upload durchführen
            success, message, server_path = upload_to_server_simple(video_dir)

            if success:
                print(f"Server Upload erfolgreich: {server_path}")
            else:
                print(f"Server Upload fehlgeschlagen: {message}")

            return success, message, server_path

        except Exception as e:
            error_msg = f"Upload Fehler: {str(e)}"
            print(error_msg)
            return False, error_msg, ""

    def _update_progress(self, step, total_steps=10):
        """Aktualisiert den Fortschritt"""
        if self.progress_callback:
            self.progress_callback(step, total_steps)

    def _show_success_message(self, output_path, server_message=""):
        """Zeigt Erfolgsmeldung an"""
        if self.status_callback:
            self.status_callback("success", f"Das finale Video mit Intro wurde unter '{output_path}' gespeichert." + (f"\n{server_message}" if server_message != "" else server_message))

    def _handle_cancellation(self):
        """Behandelt Abbruch durch Benutzer"""
        if self.status_callback:
            self.status_callback("cancelled", "Erstellung abgebrochen.")

    def _handle_error(self, error):
        """Behandelt Fehler während der Verarbeitung"""
        if self.status_callback:
            self.status_callback("error", f"Fehler bei der Videoerstellung:\n{error}")

    def _update_status(self, message):
        """Aktualisiert den Status"""
        if self.status_callback:
            self.status_callback("update", message)

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

    def cancel_process(self):
        """Bricht die Videoerstellung ab"""
        self.cancel_event.set()

    def reset_cancel_event(self):
        """Setzt das Cancel-Event zurück"""
        self.cancel_event.clear()