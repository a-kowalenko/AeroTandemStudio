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
        # Hinweis: Der Logger wird hier instanziiert, aber seine Callback-Funktion wird
        # in diesem Setup nicht direkt von FFmpeg aufgerufen. Der Abbruch
        # wird durch manuelle Checks im Code gesteuert.
        self.logger = CancellableProgressBarLogger(self.cancel_event)

    def create_video_with_intro_only(self, form_data, combined_video_path, photo_paths=None, kunde=None):
        """Erstellt nur noch das Intro und hängt es vor das kombinierte Video"""
        thread = threading.Thread(
            target=self._video_creation_with_intro_only_task,
            args=(form_data, combined_video_path, photo_paths, kunde)
        )
        thread.start()
        return thread

    def _video_creation_with_intro_only_task(self, form_data, combined_video_path, photo_paths=None, kunde=None):
        """Hauptlogik für das Hinzufügen des Intros zum kombinierten Video"""
        try:
            self._execute_video_creation_with_intro_only(form_data, combined_video_path, photo_paths, kunde)
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

    def _execute_video_creation_with_intro_only(self, form_data, combined_video_path, photo_paths=None, kunde=None):
        """Fügt nur das Intro zum bereits kombinierten Video hinzu, ohne Neukodierung des Hauptvideos."""
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = form_data["dauer"]
        ort = form_data["ort"]
        speicherort = form_data["speicherort"]
        outside_video = form_data["video_mode"] == "outside"
        upload_to_server = form_data["upload_to_server"]

        full_output_path = ""
        temp_files = []

        try:
            # Schritt 1: Detaillierte Videoinformationen des kombinierten Videos lesen
            self._check_for_cancellation()
            self._update_progress(1)
            self._update_status("Ermittle detaillierte Videoinformationen...")
            video_params = self._get_video_info(combined_video_path)

            # Schritt 2: Textinhalte vorbereiten
            self._check_for_cancellation()
            self._update_progress(2)
            self._update_status("Bereite Text-Overlays vor...")
            drawtext_filter = self._prepare_text_overlay(
                gast, tandemmaster, videospringer, datum, ort,
                video_params['height'], outside_video
            )


            hintergrund_path = self.hintergrund_path
            if not os.path.exists(hintergrund_path):
                raise FileNotFoundError("hintergrund.png fehlt im assets/ Ordner")

            # Schritt 3: Kompatiblen Intro-Clip mit stiller Audiospur in einem Schritt erstellen
            self._check_for_cancellation()
            self._update_progress(3)
            self._update_status("Erstelle exakt kompatiblen Intro-Clip...")
            temp_intro_with_audio_path = os.path.join(tempfile.gettempdir(), "intro_with_silent_audio.mp4")
            temp_files.append(temp_intro_with_audio_path)
            self._create_intro_with_silent_audio(
                temp_intro_with_audio_path, dauer, video_params, drawtext_filter
            )

            # NEUER ANSATZ: Robuste Verkettung über MPEG-TS Zwischenformat
            # Schritt 4: Videos in .ts-Format umwandeln für stabilere Verkettung
            self._check_for_cancellation()
            self._update_progress(4)
            self._update_status("Normalisiere Videos für robustes Zusammenfügen...")

            # Bitstream-Filter basierend auf dem Codec auswählen
            bsf = "hevc_mp4toannexb" if video_params['vcodec'] == 'hevc' else "h264_mp4toannexb"

            # Schritt 5: Intro nach .ts konvertieren
            self._check_for_cancellation()
            self._update_progress(5)
            self._update_status("Konvertiere Intro in Zwischenformat...")
            temp_intro_ts_path = os.path.join(tempfile.gettempdir(), "intro.ts")
            temp_files.append(temp_intro_ts_path)
            subprocess.run([
                "ffmpeg", "-y", "-i", temp_intro_with_audio_path,
                "-c", "copy", "-bsf:v", bsf, "-f", "mpegts",
                temp_intro_ts_path
            ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Schritt 6: Hauptvideo nach .ts konvertieren
            self._check_for_cancellation()
            self._update_progress(6)
            self._update_status("Konvertiere Hauptvideo in Zwischenformat...")
            temp_combined_ts_path = os.path.join(tempfile.gettempdir(), "combined.ts")
            temp_files.append(temp_combined_ts_path)
            subprocess.run([
                "ffmpeg", "-y", "-i", combined_video_path,
                "-c", "copy", "-bsf:v", bsf, "-f", "mpegts",
                temp_combined_ts_path
            ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Schritt 7: Output-Pfad generieren
            self._check_for_cancellation()
            self._update_progress(7)
            self._update_status("Generiere Ausgabe-Pfad...")
            full_output_path = self._generate_output_path(
                form_data['load'], gast, tandemmaster, videospringer,
                datum, speicherort, outside_video
            )

            # Schritt 8: .ts-Dateien zusammenfügen
            self._check_for_cancellation()
            self._update_progress(8)
            self._update_status("Füge Videos final zusammen...")
            concat_input = f"concat:{temp_intro_ts_path}|{temp_combined_ts_path}"
            subprocess.run([
                "ffmpeg", "-y",
                "-i", concat_input,
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",  # Wichtig für korrekte Audio-Header in MP4
                "-movflags", "+faststart",
                full_output_path
            ], capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Schritt 9: Fotos in Output-Verzeichnis kopieren
            self._check_for_cancellation()
            self._update_progress(9)
            if photo_paths:
                self._update_status("Kopiere Fotos...")
                self._copy_photos_to_output_directory(photo_paths, full_output_path)

            # Schritt 10: Auf Server uploaden falls gewünscht
            self._check_for_cancellation()
            self._update_progress(10)
            server_message = ""
            if upload_to_server:
                self._update_status("Lade Video auf Server hoch...")
                success, message, server_path = self._upload_to_server(full_output_path)
                server_message = f"\nServer: {message}" if message else ""

            # Fertig
            self._update_progress(11)
            self._show_success_message(full_output_path, server_message)

            # Speichere MARKER Datei im Ausgabeordner
            marker_path = os.path.join(os.path.dirname(full_output_path), "_fertig.txt")
            with open(marker_path, 'w') as marker_file:
                try:
                    # Überprüfen, ob 'kunde' eine gültige Dataclass-Instanz ist
                    if kunde is not None and is_dataclass(kunde):
                        # 'asdict' hier sicher aufrufen
                        marker_file.write(json.dumps(asdict(kunde), ensure_ascii=False))
                    else:
                        marker_file.write(json.dumps({}, ensure_ascii=False))
                        print(f"Warnung: 'kunde'-Objekt ist 'None' oder keine Dataclass.")
                except TypeError as json_err:
                    print(f"Fehler beim Serialisieren der 'kunde'-Daten: {json_err}")

        except subprocess.CalledProcessError as e:
            # Prüfen, ob der Fehler durch einen Abbruch verursacht wurde
            if self.cancel_event.is_set():
                raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
            error_details = f"FFmpeg Error:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
            print(error_details)
            raise Exception(f"Fehler bei der Videoverarbeitung. Details siehe Konsole.")
        except Exception as e:
            if not isinstance(e, CancellationError):
                if full_output_path and os.path.exists(full_output_path):
                    os.remove(full_output_path)
            raise e
        finally:
            self._cleanup_temp_files(temp_files)

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
            # NEU: explizite Qualitätseinstellungen und Farbparameter für bessere Kompatibilität
            "-preset", "fast",
            "-crf", "18",  # Visuell verlustfrei, um Artefakte zu vermeiden
        ]

        # Füge die ausgelesenen Farb-Parameter hinzu, falls vorhanden
        if v_params.get('color_range'):
            command.extend(["-color_range", v_params['color_range']])
        if v_params.get('colorspace'):
            command.extend(["-colorspace", v_params['colorspace']])
        if v_params.get('color_primaries'):
            command.extend(["-color_primaries", v_params['color_primaries']])
        if v_params.get('color_trc'):
            command.extend(["-color_trc", v_params['color_trc']])

        # NEU: Füge Profil und Level hinzu, falls vorhanden.
        # Dies ist oft der entscheidende Punkt für 4K-Kompatibilität.
        if v_params.get('profile') and v_params['vcodec'] in ['h264', 'hevc']:
            # FIX: Der Profil-Name muss für den ffmpeg-Befehl kleingeschrieben werden.
            profile_str = str(v_params['profile']).lower()
            command.extend(["-profile:v", profile_str])
        if v_params.get('level') and v_params['vcodec'] in ['h264', 'hevc']:
            # Level wird von ffprobe oft als Zahl (z.B. 41 für 4.1) geliefert.
            # Wir rechnen es für den ffmpeg-Befehl um.
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

    def _copy_photos_to_output_directory(self, photo_paths, output_video_path):
        """Kopiert alle Fotos in ein Foto-Unterverzeichnis"""
        if not photo_paths:
            return

        output_dir = os.path.dirname(output_video_path)
        photos_dir = os.path.join(output_dir, "Fotos")

        try:
            os.makedirs(photos_dir, exist_ok=True)
            copied_count = 0
            for photo_path in photo_paths:
                self._check_for_cancellation()  # Check before copying each file
                if os.path.exists(photo_path):
                    filename = os.path.basename(photo_path)
                    destination_path = os.path.join(photos_dir, filename)
                    shutil.copy2(photo_path, destination_path)
                    copied_count += 1
            print(f"{copied_count} Foto(s) nach '{photos_dir}' kopiert")
        except Exception as e:
            if not isinstance(e, CancellationError):
                print(f"Fehler beim Kopieren der Fotos: {e}")
            raise e

    def _get_video_info(self, video_path):
        """
        Ermittelt detaillierte Video- und Audio-Stream-Informationen mit ffprobe.
        NEU: Liest zusätzliche Farb-Metadaten, Profil und Level aus, die für 4K/HDR-Material entscheidend sind.
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
            # Farb-Parameter auslesen
            "color_range": video_stream.get("color_range"),
            "colorspace": video_stream.get("color_space"),
            "color_primaries": video_stream.get("color_primaries"),
            "color_trc": video_stream.get("color_transfer"),  # 'color_trc' in ffmpeg
            # NEU: Codec Profile und Level für maximale Kompatibilität
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

        font_size = int(clip_height / 22)  # Etwas kleiner für bessere Lesbarkeit bei 4K
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
            from datetime import datetime
            datum_formatiert = datetime.now().strftime("%Y%m%d")

        base_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video:
            base_filename += f"_V_{videospringer}"

        output_dir = os.path.join(speicherort, sanitize_filename(base_filename))
        os.makedirs(output_dir, exist_ok=True)

        output_filename = f"{base_filename}.mp4"
        full_output_path = os.path.join(output_dir, sanitize_filename(output_filename))

        return full_output_path

    def _upload_to_server(self, local_video_path):
        """Lädt das erstellte Verzeichnis auf den Server hoch"""
        try:
            from ..utils.file_utils import upload_to_server_simple
            video_dir = os.path.dirname(local_video_path)
            # Hinzufügen einer Prüfung vor dem langen Upload-Prozess
            self._check_for_cancellation()
            success, message, server_path = upload_to_server_simple(video_dir)
            if success:
                print(f"Server Upload erfolgreich: {server_path}")
            else:
                print(f"Server Upload fehlgeschlagen: {message}")
            return success, message, server_path
        except Exception as e:
            if isinstance(e, CancellationError):
                raise e  # Erneut auslösen, um vom Haupt-Handler gefangen zu werden
            error_msg = f"Upload Fehler: {str(e)}"
            print(error_msg)
            return False, error_msg, ""

    def _update_progress(self, step, total_steps=11):
        if self.progress_callback:
            self.progress_callback(step, total_steps)

    def _show_success_message(self, output_path, server_message=""):
        if self.status_callback:
            msg = f"Das finale Video mit Intro wurde unter '{output_path}' gespeichert."
            if server_message:
                msg += f"\n{server_message}"
            self.status_callback("success", msg)

    def _handle_cancellation(self):
        print("Cancellation signal received and handled in VideoProcessor.")
        if self.status_callback:
            self.status_callback("cancelled", "Erstellung abgebrochen.")

    def _handle_error(self, error):
        if self.status_callback:
            self.status_callback("error", f"Fehler bei der Videoerstellung:\n{error}")

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
