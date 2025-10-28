import json
import shutil
import threading
import os
import tempfile
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import date

from .logger import CancellableProgressBarLogger, CancellationError
from ..utils.file_utils import sanitize_filename
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.constants import HINTERGRUND_PATH


class VideoProcessor:
    def __init__(self, progress_callback=None, status_callback=None):
        self.hintergrund_path = HINTERGRUND_PATH
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.cancel_event = threading.Event()
        self.logger = CancellableProgressBarLogger(self.cancel_event)

    def create_video_with_intro_only(self, payload):
        """Erstellt ein Verzeichnis, verarbeitet optional Videos und kopiert Fotos."""
        thread = threading.Thread(
            target=self._video_creation_with_intro_only_task,
            args=(payload,)
        )
        thread.start()
        return thread

    def _video_creation_with_intro_only_task(self, payload):
        """Hauptlogik für die Verzeichniserstellung, Videoverarbeitung und Fotokopieren."""
        try:
            self._execute_video_creation_with_intro_only(payload)
        except CancellationError:
            self._handle_cancellation()
        except Exception as e:
            self._handle_error(e)
        finally:
            self._cleanup()

    def _check_for_cancellation(self):
        """Prüft, ob ein Abbruch angefordert wurde und wirft ggf. eine Exception."""
        if self.cancel_event.is_set():
            raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")

    def _execute_video_creation_with_intro_only(self, payload):
        """
        Erstellt ein Verzeichnis.
        Wenn ein Video vorhanden ist, wird es verarbeitet (Intro hinzugefügt) und im Unterordner (Handcam_Video/Outside_Video) gespeichert.
        ZUSÄTZLICH: Wenn create_watermark_version True ist, wird eine zweite Version mit Wasserzeichen erstellt.
        """

        form_data = payload["form_data"]
        combined_video_path = payload["combined_video_path"]  # Kann None sein
        photo_paths = payload.get("photo_paths", [])
        kunde = payload.get("kunde")
        settings = payload.get("settings")
        # NEU: Flag für Wasserzeichen-Version
        create_watermark_version = payload.get("create_watermark_version", False)

        print("kunde Objekt:", kunde)
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = settings.get("dauer", "8")
        ort = form_data["ort"]
        speicherort = settings.get("speicherort", "")
        outside_video_mode = form_data["video_mode"] == "outside"
        upload_to_server = form_data["upload_to_server"]

        base_output_dir = ""
        full_video_output_path = None  # Pfad zum *finalen Video*, falls eines erstellt wird
        watermark_video_output_path = None  # NEU: Pfad zur Wasserzeichen-Version
        temp_files = []

        # Gesamt-Fortschrittsschritte anpassen für mögliche zweite Video-Erstellung
        TOTAL_STEPS = 12 if create_watermark_version else 11

        try:
            # Schritt 1: Output-Basisverzeichnis generieren
            self._check_for_cancellation()
            self._update_progress(1, TOTAL_STEPS)
            self._update_status("Generiere Ausgabe-Verzeichnis...")
            base_output_dir, base_filename = self._generate_base_output_dir(
                form_data['load'], gast, tandemmaster, videospringer,
                datum, speicherort, outside_video_mode
            )

            # --- VIDEO VERARBEITUNG (Schritte 2-8) ---
            if combined_video_path and os.path.exists(combined_video_path):
                # Schritt 2: Detaillierte Videoinformationen des kombinierten Videos lesen
                self._check_for_cancellation()
                self._update_progress(2, TOTAL_STEPS)
                self._update_status("Ermittle detaillierte Videoinformationen...")
                video_params = self._get_video_info(combined_video_path)

                # Schritt 3: Textinhalte vorbereiten
                self._check_for_cancellation()
                self._update_progress(3, TOTAL_STEPS)
                self._update_status("Bereite Text-Overlays vor...")
                drawtext_filter = self._prepare_text_overlay(
                    gast, tandemmaster, videospringer, datum, ort,
                    video_params['height'], outside_video_mode
                )

                hintergrund_path = self.hintergrund_path
                if not os.path.exists(hintergrund_path):
                    raise FileNotFoundError("hintergrund.png fehlt im assets/ Ordner")

                # Schritt 4: Kompatiblen Intro-Clip erstellen
                self._check_for_cancellation()
                self._update_progress(4, TOTAL_STEPS)
                self._update_status("Erstelle exakt kompatiblen Intro-Clip...")
                temp_intro_with_audio_path = os.path.join(tempfile.gettempdir(), "intro_with_silent_audio.mp4")
                temp_files.append(temp_intro_with_audio_path)
                self._create_intro_with_silent_audio(
                    temp_intro_with_audio_path, dauer, video_params, drawtext_filter
                )

                # Schritt 5: Videos in .ts-Format umwandeln (Intro)
                self._check_for_cancellation()
                self._update_progress(5, TOTAL_STEPS)
                self._update_status("Normalisiere Intro für robustes Zusammenfügen...")
                bsf = "hevc_mp4toannexb" if video_params['vcodec'] == 'hevc' else "h264_mp4toannexb"
                temp_intro_ts_path = os.path.join(tempfile.gettempdir(), "intro.ts")
                temp_files.append(temp_intro_ts_path)
                subprocess.run([
                    "ffmpeg", "-y", "-i", temp_intro_with_audio_path,
                    "-c", "copy", "-bsf:v", bsf, "-f", "mpegts",
                    temp_intro_ts_path
                ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                # Schritt 6: Hauptvideo nach .ts konvertieren
                self._check_for_cancellation()
                self._update_progress(6, TOTAL_STEPS)
                self._update_status("Normalisiere Hauptvideo für robustes Zusammenfügen...")
                temp_combined_ts_path = os.path.join(tempfile.gettempdir(), "combined.ts")
                temp_files.append(temp_combined_ts_path)
                subprocess.run([
                    "ffmpeg", "-y", "-i", combined_video_path,
                    "-c", "copy", "-bsf:v", bsf, "-f", "mpegts",
                    temp_combined_ts_path
                ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

                # Schritt 6a: Hauptvideo mit Wasserzeichen erstellen (falls gewünscht)
                temp_combined_with_watermark_path = None
                if create_watermark_version:
                    self._check_for_cancellation()
                    self._update_progress(7, TOTAL_STEPS)
                    self._update_status("Füge Wasserzeichen zum Hauptvideo hinzu...")

                    # Temporäre Datei für Hauptvideo mit Wasserzeichen
                    temp_combined_with_watermark_path = os.path.join(tempfile.gettempdir(),
                                                                     "combined_with_watermark.mp4")
                    temp_files.append(temp_combined_with_watermark_path)

                    # Wasserzeichen nur auf das Hauptvideo anwenden
                    self._create_video_with_watermark(
                        combined_video_path,  # Originales Hauptvideo
                        temp_combined_with_watermark_path,  # Ausgabe mit Wasserzeichen
                        video_params
                    )

                    # Jetzt das Wasserzeichen-Video in .ts konvertieren
                    temp_combined_with_watermark_ts_path = os.path.join(tempfile.gettempdir(),
                                                                        "combined_with_watermark.ts")
                    temp_files.append(temp_combined_with_watermark_ts_path)
                    subprocess.run([
                        "ffmpeg", "-y", "-i", temp_combined_with_watermark_path,
                        "-c", "copy", "-bsf:v", bsf, "-f", "mpegts",
                        temp_combined_with_watermark_ts_path
                    ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:
                    self._update_progress(7, TOTAL_STEPS)

                # Schritt 7: Finalen Video-Output-Pfad generieren (inkl. Unterordner)
                self._check_for_cancellation()
                self._update_progress(8, TOTAL_STEPS)
                self._update_status("Generiere Video-Ausgabe-Pfad...")

                # NEU: Prüfen ob normale Video-Version erstellt werden soll
                if kunde and (kunde.handcam_video or kunde.outside_video):
                    full_video_output_path = self._generate_video_output_path(
                        base_output_dir, base_filename, kunde
                    )
                else:
                    full_video_output_path = None
                    self._update_status("Überspringe normale Video-Erstellung (kein Produkt gewählt)...")

                # Schritt 8: .ts-Dateien zusammenfügen (nur wenn normale Version gewünscht)
                if full_video_output_path:
                    self._check_for_cancellation()
                    self._update_progress(9, TOTAL_STEPS)
                    self._update_status("Füge Videos final zusammen...")
                    concat_input = f"concat:{temp_intro_ts_path}|{temp_combined_ts_path}"
                    subprocess.run([
                        "ffmpeg", "-y",
                        "-i", concat_input,
                        "-c", "copy",
                        "-bsf:a", "aac_adtstoasc",
                        "-movflags", "+faststart",
                        full_video_output_path
                    ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:
                    self._update_progress(9, TOTAL_STEPS)
                    self._update_status("Überspringe normale Video-Erstellung...")

                # Schritt 8a: Wasserzeichen-Version erstellen (falls gewünscht)
                if create_watermark_version:
                    self._check_for_cancellation()
                    self._update_progress(10, TOTAL_STEPS)
                    self._update_status("Erstelle Video mit Wasserzeichen...")

                    watermark_video_output_path = self._generate_watermark_video_path(
                        base_output_dir, base_filename
                    )

                    # Intro (ohne Wasserzeichen) mit Hauptvideo (mit Wasserzeichen) kombinieren
                    concat_input_watermark = f"concat:{temp_intro_ts_path}|{temp_combined_with_watermark_ts_path}"
                    subprocess.run([
                        "ffmpeg", "-y",
                        "-i", concat_input_watermark,
                        "-c", "copy",
                        "-bsf:a", "aac_adtstoasc",
                        "-movflags", "+faststart",
                        watermark_video_output_path
                    ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                else:
                    self._update_progress(10, TOTAL_STEPS)

            else:
                # Schritte 2-8 überspringen, wenn kein Video vorhanden ist
                self._update_status("Kein Video zur Verarbeitung ausgewählt. Überspringe...")
                for i in range(2, 11 if create_watermark_version else 10):  # Schritte 2 bis 10/9
                    self._update_progress(i, TOTAL_STEPS)
                full_video_output_path = None  # Sicherstellen, dass es None ist

            # --- FOTO VERARBEITUNG (Schritt 11) ---
            self._check_for_cancellation()
            step_photo = 11 if create_watermark_version else 10
            self._update_progress(step_photo, TOTAL_STEPS)
            photo_copy_message = ""
            if photo_paths:
                self._update_status("Kopiere Fotos...")
                copied_count = self._copy_photos_to_output_directory(photo_paths, base_output_dir, kunde)
                photo_copy_message = f"{copied_count} Foto(s) wurden in die entsprechenden Ordner kopiert."
            else:
                self._update_status("Keine Fotos zum Kopieren ausgewählt.")

            # --- SERVER UPLOAD (Schritt 12) ---
            self._check_for_cancellation()
            step_server = 12 if create_watermark_version else 11
            self._update_progress(step_server, TOTAL_STEPS)
            server_message = ""
            if upload_to_server:
                self._update_status("Lade Verzeichnis auf Server hoch...")
                # Wir laden das gesamte Basis-Verzeichnis hoch
                success, message, server_path = self._upload_to_server(base_output_dir)
                server_message = f"\nServer: {message}" if message else ""

            # --- ABSCHLUSS (letzter Schritt) ---
            final_step = 13 if create_watermark_version else 12
            self._update_progress(final_step, TOTAL_STEPS)

            # Speichere MARKER Datei im Ausgabeordner
            marker_path = os.path.join(base_output_dir, "_fertig.txt")
            with open(marker_path, 'w') as marker_file:
                try:
                    if kunde is not None and is_dataclass(kunde):
                        marker_file.write(json.dumps(asdict(kunde), ensure_ascii=False))
                    else:
                        marker_file.write(json.dumps({}, ensure_ascii=False))
                except TypeError as json_err:
                    print(f"Fehler beim Serialisieren der 'kunde'-Daten: {json_err}")

            # Fertig-Meldung erstellen
            success_messages = []
            if full_video_output_path:
                success_messages.append(f"Das finale Video wurde unter '{full_video_output_path}' gespeichert.")
            if watermark_video_output_path:
                success_messages.append(
                    f"Die Wasserzeichen-Version wurde unter '{watermark_video_output_path}' gespeichert.")
            if photo_copy_message:
                success_messages.append(photo_copy_message)

            if not success_messages:
                # Fallback, wenn nur ein leeres Verzeichnis erstellt wurde (sollte durch app.py verhindert werden)
                success_messages.append(f"Ausgabe-Verzeichnis '{base_output_dir}' wurde erstellt.")

            if server_message:
                success_messages.append(server_message)

            self._show_success_message("\n".join(success_messages))

        except subprocess.CalledProcessError as e:
            if self.cancel_event.is_set():
                raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
            error_details = f"FFmpeg Error:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
            print(error_details)
            raise Exception(f"Fehler bei der Videoverarbeitung. Details siehe Konsole.")
        except Exception as e:
            # Bei Fehler die (möglicherweise unvollständigen) Videos löschen
            if not isinstance(e, CancellationError):
                if full_video_output_path and os.path.exists(full_video_output_path):
                    try:
                        os.remove(full_video_output_path)
                    except Exception as del_e:
                        print(f"Konnte unvollständiges Video nicht löschen: {del_e}")
                if watermark_video_output_path and os.path.exists(watermark_video_output_path):
                    try:
                        os.remove(watermark_video_output_path)
                    except Exception as del_e:
                        print(f"Konnte unvollständiges Wasserzeichen-Video nicht löschen: {del_e}")
            raise e
        finally:
            self._cleanup_temp_files(temp_files)

    def _generate_watermark_video_path(self, base_output_dir, base_filename):
        """Generiert den Pfad für die Wasserzeichen-Video-Version"""
        watermark_dir = os.path.join(base_output_dir, "Wasserzeichen_Video")
        os.makedirs(watermark_dir, exist_ok=True)

        output_filename = f"{base_filename}_wasserzeichen.mp4"
        full_output_path = os.path.join(watermark_dir, output_filename)

        return full_output_path

    def _create_video_with_watermark(self, input_video_path, output_path, video_params):
        """Erstellt eine Video-Version mit Wasserzeichen über dem gesamten Video"""

        # Pfad zum Wasserzeichen-Bild
        wasserzeichen_path = os.path.join(os.path.dirname(self.hintergrund_path), "skydivede_wasserzeichen.png")

        if not os.path.exists(wasserzeichen_path):
            raise FileNotFoundError("skydivede_wasserzeichen.png fehlt im assets/ Ordner")

        # Wasserzeichen-Filter: mittig positioniert, volle Breite des Videos
        watermark_filter = (
            f"[1]scale={video_params['width']}:{video_params['height']}:force_original_aspect_ratio=decrease:"
            f"eval=frame[wm_scaled];"
            f"[0][wm_scaled]overlay=(W-w)/2:(H-h)/2"
        )

        subprocess.run([
            "ffmpeg", "-y",
            "-i", input_video_path,
            "-i", wasserzeichen_path,
            "-filter_complex", watermark_filter,
            "-c:a", "copy",
            "-movflags", "+faststart",
            output_path
        ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

    def _create_intro_with_silent_audio(self, output_path, dauer, v_params, drawtext_filter):
        """
        Erstellt den Intro-Clip inklusive einer passenden stillen Audiospur in einem einzigen Befehl.
        NEU: Nutzt erweiterte Parameter für maximale Kompatibilität, speziell für 4K.
        """
        self._check_for_cancellation()
        print(f"Erstelle Intro mit erweiterten Parametern: {v_params}")
        video_filters = f"scale={v_params['width']}:{v_params['height']},{drawtext_filter}"

        command = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", self.hintergrund_path,
            "-f", "lavfi", "-i",
            f"anullsrc=channel_layout={v_params['channel_layout']}:sample_rate={v_params['sample_rate']}",
            "-vf", video_filters,
            "-c:v", v_params['vcodec'],
            "-tag:v", v_params['vtag'],
            "-pix_fmt", v_params['pix_fmt'],
            "-r", v_params['fps'],
            "-video_track_timescale", v_params['timescale'],
            "-c:a", v_params['acodec'],
            "-t", str(dauer),
            "-shortest",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-preset", "fast",
            "-crf", "18",
        ]

        if v_params.get('color_range'):
            command.extend(["-color_range", v_params['color_range']])
        if v_params.get('colorspace'):
            command.extend(["-colorspace", v_params['colorspace']])
        if v_params.get('color_primaries'):
            command.extend(["-color_primaries", v_params['color_primaries']])
        if v_params.get('color_trc'):
            command.extend(["-color_trc", v_params['color_trc']])

        if v_params.get('profile') and v_params['vcodec'] in ['h264', 'hevc']:
            profile_str = str(v_params['profile']).lower()
            command.extend(["-profile:v", profile_str])
        if v_params.get('level') and v_params['vcodec'] in ['h264', 'hevc']:
            try:
                level_str = str(float(v_params['level']) / 10.0)
                command.extend(["-level:v", level_str])
            except (ValueError, TypeError):
                command.extend(["-level:v", str(v_params['level'])])

        command.append(output_path)

        result = subprocess.run(command, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        if result.returncode != 0:
            if self.cancel_event.is_set():
                raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
            print(f"Fehler bei Intro-Erstellung: {result.stderr}")
            raise subprocess.CalledProcessError(result.returncode, command, result.stdout, result.stderr)

    def _copy_photos_to_output_directory(self, photo_paths, base_output_dir, kunde):
        """
        Kopiert alle Fotos in die entsprechenden Unterverzeichnisse (Handcam_Foto / Outside_Foto)
        basierend auf den im Kunde-Objekt ausgewählten Optionen.
        Gibt die Anzahl der kopierten *Quelldateien* zurück.
        """
        if not photo_paths or not kunde:
            return 0

        # Definiere Zielverzeichnisse
        handcam_dir = os.path.join(base_output_dir, "Handcam_Foto")
        outside_dir = os.path.join(base_output_dir, "Outside_Foto")

        # Erstelle Verzeichnisse nur, wenn sie im Formular ausgewählt wurden
        if kunde.handcam_foto:
            os.makedirs(handcam_dir, exist_ok=True)
        if kunde.outside_foto:
            os.makedirs(outside_dir, exist_ok=True)

        copied_files_count = 0
        for photo_path in photo_paths:
            self._check_for_cancellation()
            if not os.path.exists(photo_path):
                continue

            filename = os.path.basename(photo_path)
            copied_this_file = False

            if kunde.handcam_foto:
                destination_path = os.path.join(handcam_dir, filename)
                shutil.copy2(photo_path, destination_path)
                copied_this_file = True

            if kunde.outside_foto:
                destination_path = os.path.join(outside_dir, filename)
                shutil.copy2(photo_path, destination_path)
                copied_this_file = True

            if copied_this_file:
                copied_files_count += 1

        print(f"{copied_files_count} Foto(s) nach '{handcam_dir}' und/oder '{outside_dir}' kopiert")
        return copied_files_count

    def _get_video_info(self, video_path):
        """
        Ermittelt detaillierte Video- und Audio-Stream-Informationen mit ffprobe.
        """
        self._check_for_cancellation()
        command = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_streams", video_path
        ]
        result = subprocess.run(command, capture_output=True, text=True, check=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        streams = json.loads(result.stdout)["streams"]

        video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in streams if s['codec_type'] == 'audio'), None)

        if not video_stream:
            raise ValueError("Kein Video-Stream in der Eingabedatei gefunden.")
        if not audio_stream:
            raise ValueError("Kein Audio-Stream in der Eingabedatei gefunden.")

        time_base = video_stream.get("time_base", "1/25").split('/')
        timescale = time_base[1] if len(time_base) == 2 else "25"

        return {
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": video_stream.get("r_frame_rate"),
            "timescale": timescale,
            "pix_fmt": video_stream.get("pix_fmt"),
            "vcodec": video_stream.get("codec_name"),
            "vtag": video_stream.get("codec_tag_string", "avc1"),
            "acodec": audio_stream.get("codec_name"),
            "sample_rate": audio_stream.get("sample_rate"),
            "channel_layout": audio_stream.get("channel_layout", "stereo"),
            "color_range": video_stream.get("color_range"),
            "colorspace": video_stream.get("color_space"),
            "color_primaries": video_stream.get("color_primaries"),
            "color_trc": video_stream.get("color_transfer"),
            "profile": video_stream.get("profile"),
            "level": video_stream.get("level"),
        }

    def _prepare_text_overlay(self, gast, tandemmaster, videospringer, datum, ort, clip_height, outside_video):
        """Bereitet die Text-Overlays für das Video vor"""

        def ffmpeg_escape(text: str) -> str:
            return text.replace(":", r"\:").replace("'", r"\''").replace(",", r"\,")

        text_inhalte = [f"Gast: {gast}", f"Tandemmaster: {tandemmaster}"]
        if outside_video:
            text_inhalte.append(f"Videospringer: {videospringer}")
        text_inhalte.extend([f"Datum: {datum}", f"Ort: {ort}"])
        text_inhalte = [ffmpeg_escape(t) for t in text_inhalte]

        font_size = int(clip_height / 22)
        y = clip_height * 0.15
        y_step = clip_height * 0.15
        drawtext_cmds = []

        for t in text_inhalte:
            drawtext_cmds.append(
                f"drawtext=text='{t}':x=(w-text_w)/2:y={int(y)}:fontsize={font_size}:fontcolor=black:font='Arial'"
            )
            y += y_step

        return ",".join(drawtext_cmds)

    def _generate_base_output_dir(self, load, gast, tandemmaster, videospringer, datum, speicherort, outside_video):
        """Generiert den Basis-Output-Pfad (nur das Verzeichnis)"""
        try:
            datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
            datum_formatiert = datum_obj.strftime("%Y%m%d")
        except:
            from datetime import datetime
            datum_formatiert = datetime.now().strftime("%Y%m%d")

        base_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video:
            base_filename += f"_V_{videospringer}"

        base_filename_sanitized = sanitize_filename(base_filename)
        output_dir = os.path.join(speicherort, base_filename_sanitized)
        os.makedirs(output_dir, exist_ok=True)

        return output_dir, base_filename_sanitized  # Gebe auch den sauberen Basisnamen zurück

    def _generate_video_output_path(self, base_output_dir, base_filename, kunde):
        """Generiert den finalen Video-Output-Pfad (in Handcam_Video/Outside_Video)"""

        video_subdir_name = ""

        # Bestimme das Unterverzeichnis basierend auf den Kunde-Optionen
        # Wir priorisieren Outside_Video, wenn beides ausgewählt ist,
        # oder speichern es in Handcam, wenn nur das ausgewählt ist.
        if kunde.outside_video:
            video_subdir_name = "Outside_Video"
        elif kunde.handcam_video:
            video_subdir_name = "Handcam_Video"
        else:
            # Fallback, falls die Logik in app.py dies zulässt (sollte nicht, aber sicher ist sicher)
            video_subdir_name = "Handcam_Video"

        video_dir = os.path.join(base_output_dir, video_subdir_name)
        os.makedirs(video_dir, exist_ok=True)

        output_filename = f"{base_filename}.mp4"
        full_output_path = os.path.join(video_dir, output_filename)  # Name bleibt gleich, nur Pfad ändert sich

        return full_output_path

    def _upload_to_server(self, local_directory_path):
        """Lädt das erstellte Verzeichnis auf den Server hoch"""
        try:
            from ..utils.file_utils import upload_to_server_simple
            # Hinzufügen einer Prüfung vor dem langen Upload-Prozess
            self._check_for_cancellation()

            # Übergebe das Verzeichnis direkt an die Upload-Funktion
            success, message, server_path = upload_to_server_simple(local_directory_path)

            if success:
                print(f"Server Upload erfolgreich: {server_path}")
            else:
                print(f"Server Upload fehlgeschlagen: {message}")
            return success, message, server_path
        except Exception as e:
            if isinstance(e, CancellationError):
                raise e
            error_msg = f"Upload Fehler: {str(e)}"
            print(error_msg)
            return False, error_msg, ""

    def _update_progress(self, step, total_steps=11):
        if self.progress_callback:
            self.progress_callback(step, total_steps)

    def _show_success_message(self, message):
        """Zeigt die kombinierte Erfolgsmeldung an"""
        if self.status_callback:
            self.status_callback("success", message)

    def _handle_cancellation(self):
        print("Cancellation signal received and handled in VideoProcessor.")
        if self.status_callback:
            self.status_callback("cancelled", "Erstellung abgebrochen.")

    def _handle_error(self, error):
        if self.status_callback:
            self.status_callback("error", f"Fehler bei der Erstellung:\n{error}")

    def _update_status(self, message):
        if self.status_callback:
            self.status_callback("update", message)

    def _cleanup_temp_files(self, temp_files):
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass

    def _cleanup(self):
        self.reset_cancel_event()

    def cancel_process(self):
        print("Cancel event set!")
        self.cancel_event.set()

    def reset_cancel_event(self):
        self.cancel_event.clear()
