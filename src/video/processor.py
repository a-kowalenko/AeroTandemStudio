import json
import shutil
import threading
import os
import tempfile
import subprocess
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import multiprocessing
import time

from .logger import CancellableProgressBarLogger, CancellationError
from ..utils.file_utils import sanitize_filename
from src.utils.media_datetime import get_photo_display_epoch
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.constants import HINTERGRUND_PATH
from src.utils.constants import (
    HINTERGRUND_ORIGINAL_WIDTH, HINTERGRUND_ORIGINAL_HEIGHT,
    CONTENT_AREA_X1, CONTENT_AREA_Y1, CONTENT_AREA_X2, CONTENT_AREA_Y2,
    CONTENT_AREA_PADDING_LEFT, CONTENT_AREA_PADDING_RIGHT,
    CONTENT_AREA_PADDING_TOP, CONTENT_AREA_PADDING_BOTTOM
)
from src.utils.hardware_acceleration import HardwareAccelerationDetector


class VideoProcessor:
    def __init__(self, progress_callback=None, status_callback=None, config_manager=None, encoding_progress_callback=None):
        self.hintergrund_path = HINTERGRUND_PATH
        self.progress_callback = progress_callback
        self.status_callback = status_callback
        self.encoding_progress_callback = encoding_progress_callback  # NEU: Callback für Live-Encoding-Fortschritt
        self.cancel_event = threading.Event()
        self.logger = CancellableProgressBarLogger(self.cancel_event)
        self.config_manager = config_manager  # Config Manager speichern
        self.parallel_processor = None  # Wird in _init_hardware_acceleration initialisiert (Optional[ParallelVideoProcessor])

        # Hardware-Beschleunigung initialisieren
        self.hw_detector = HardwareAccelerationDetector()
        self._init_hardware_acceleration()

    def _init_hardware_acceleration(self):
        """Initialisiert Hardware-Beschleunigung basierend auf Einstellungen"""
        self.hw_accel_enabled = False
        self.parallel_processing_enabled = True  # Standard: aktiviert

        if self.config_manager:
            settings = self.config_manager.get_settings()
            self.hw_accel_enabled = settings.get("hardware_acceleration_enabled", True)
            self.parallel_processing_enabled = settings.get("parallel_processing_enabled", True)

            if self.hw_accel_enabled:
                hw_info = self.hw_detector.detect_hardware()
                if hw_info['available']:
                    print(f"✓ Hardware-Beschleunigung aktiviert: {self.hw_detector.get_hardware_info_string()}")
                else:
                    print("⚠ Hardware-Beschleunigung aktiviert, aber keine kompatible Hardware gefunden")
                    print("  → Fallback auf Software-Encoding")
            else:
                print("ℹ Hardware-Beschleunigung deaktiviert (Software-Encoding)")

            # Info über Paralleles Processing
            if self.parallel_processing_enabled:
                cpu_count = multiprocessing.cpu_count()
                if self.hw_accel_enabled:
                    workers = min(cpu_count, 4)
                else:
                    workers = max(1, cpu_count // 2)
                print(f"🚀 Paralleles Processing aktiviert: {workers} Worker-Threads ({cpu_count} CPU-Kerne)")
                # ParallelVideoProcessor importieren und initialisieren
                from .parallel_processor import ParallelVideoProcessor
                self.parallel_processor = ParallelVideoProcessor(self.hw_accel_enabled)
            else:
                print("ℹ Paralleles Processing deaktiviert (sequenziell)")
                self.parallel_processor = None

    def reload_hardware_acceleration_settings(self):
        """
        Lädt die Hardware-Beschleunigungseinstellungen neu.
        Wird aufgerufen wenn die Einstellungen geändert wurden.
        """
        print("🔄 VideoProcessor: Lade Hardware-Beschleunigungseinstellungen neu...")
        self._init_hardware_acceleration()

    def _get_encoding_params(self, codec='h264'):
        """
        Gibt Encoding-Parameter basierend auf Hardware-Beschleunigung zurück.

        Args:
            codec: 'h264' oder 'hevc'

        Returns:
            Dict mit input_params, output_params und encoder
        """
        params = self.hw_detector.get_encoding_params(codec, self.hw_accel_enabled)

        # Füge Thread-Steuerung basierend auf Parallel Processing Einstellung hinzu
        if not self.hw_accel_enabled:  # Nur bei Software-Encoding relevant
            if hasattr(self, 'parallel_processing_enabled'):
                if self.parallel_processing_enabled:
                    # Nutze alle verfügbaren Threads
                    params['output_params'].extend(['-threads', '0'])
                else:
                    # Limitiere auf 1 Thread für echtes sequenzielles Processing
                    params['output_params'].extend(['-threads', '1'])

        return params

    @staticmethod
    def _parse_r_frame_rate(r_frame_rate):
        """Wandelt ffprobe r_frame_rate (z. B. 30000/1001 oder 25) in eine ganzzahlige FPS für GOP -g."""
        if r_frame_rate is None:
            return 30
        try:
            if isinstance(r_frame_rate, (int, float)):
                return max(1, int(round(float(r_frame_rate))))
            s = str(r_frame_rate).strip()
            if '/' in s:
                num, den = s.split('/', 1)
                return max(1, int(round(float(num) / float(den))))
            return max(1, int(round(float(s))))
        except (ValueError, ZeroDivisionError, TypeError):
            return 30

    @staticmethod
    def _get_work_temp_dir(*path_hints):
        """
        Temp-Verzeichnis auf dem Laufwerk des Quellvideos (nicht immer %TEMP% auf C:).
        """
        for path_hint in path_hints:
            if not path_hint:
                continue
            base = path_hint if os.path.isdir(path_hint) else os.path.dirname(os.path.abspath(path_hint))
            if not base or not os.path.isdir(base):
                continue
            work = os.path.join(base, ".aerotandem_work")
            try:
                os.makedirs(work, exist_ok=True)
                if os.access(work, os.W_OK):
                    return work
            except OSError:
                continue
        return tempfile.gettempdir()

    @staticmethod
    def _mp4_has_faststart(file_path, scan_bytes=4 * 1024 * 1024):
        """
        True wenn der moov-Atom vor mdat liegt (typisch nach -movflags +faststart).
        """
        try:
            with open(file_path, 'rb') as handle:
                header = handle.read(scan_bytes)
        except OSError:
            return False
        moov_pos = header.find(b'moov')
        if moov_pos < 0:
            return False
        mdat_pos = header.find(b'mdat')
        if mdat_pos < 0:
            return True
        return moov_pos < mdat_pos

    def _normalize_mp4_for_concat(self, input_path, output_path, video_params):
        """Remux nur Video+Audio mit sauberen Timestamps (Stream-Copy, kein Neuencode)."""
        cmd = ['ffmpeg', '-y', '-fflags', '+genpts', '-i', input_path, '-map', '0:v:0']
        if video_params.get('has_audio', True):
            cmd.extend(['-map', '0:a:0'])
        cmd.extend([
            '-c', 'copy',
            '-avoid_negative_ts', 'make_zero',
            '-movflags', '+faststart',
            output_path,
        ])
        subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )

    def _mp4_to_mpegts_stream_copy(self, input_path, output_ts, vcodec, video_params):
        """MP4 → MPEG-TS per Stream-Copy (Annex-B) für robustes HEVC/H.264-Concat."""
        vcodec = self._normalize_vcodec_name(vcodec)
        bsf_map = {'h264': 'h264_mp4toannexb', 'hevc': 'hevc_mp4toannexb'}
        bsf = bsf_map.get(vcodec)

        cmd = ['ffmpeg', '-y', '-fflags', '+genpts', '-i', input_path, '-map', '0:v:0']
        if video_params.get('has_audio', True):
            cmd.extend(['-map', '0:a:0'])
        cmd.extend(['-c', 'copy', '-avoid_negative_ts', 'make_zero'])
        if bsf:
            cmd.extend(['-bsf:v', bsf])
        cmd.extend(['-f', 'mpegts', output_ts])
        subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )

    def _build_final_intro_body_stream_copy_command(
        self,
        full_video_output_path,
        video_params,
        concat_list_path=None,
        intro_ts_path=None,
        body_ts_path=None,
    ):
        """
        Intro + Hauptvideo per Stream-Copy zusammenfügen (schnell, Hauptvideo unverändert).
        HEVC: MPEG-TS-Concat (verhindert eingefrorenes Intro-Bild im Browser).
        H.264: MP4 concat demuxer.
        """
        if intro_ts_path and body_ts_path:
            concat_input = f'concat:{intro_ts_path}|{body_ts_path}'
            cmd = ['ffmpeg', '-y', '-fflags', '+genpts', '-i', concat_input]
        else:
            cmd = [
                'ffmpeg', '-y', '-fflags', '+genpts',
                '-f', 'concat', '-safe', '0', '-i', concat_list_path,
            ]

        cmd.extend(['-map', '0:v:0'])
        if video_params.get('has_audio', True):
            cmd.extend(['-map', '0:a:0'])

        cmd.extend([
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-reset_timestamps', '1',
            '-max_interleave_delta', '0',
        ])

        vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))
        if vcodec == 'hevc':
            cmd.extend(['-bsf:v', 'hevc_metadata=aud=insert,extract_extradata', '-tag:v', 'hvc1'])
        elif vcodec == 'h264':
            if intro_ts_path and body_ts_path:
                cmd.extend(['-bsf:v', 'h264_metadata=aud=insert'])
            cmd.extend(['-tag:v', 'avc1'])

        cmd.append(full_video_output_path)
        return cmd

    @staticmethod
    def _normalize_vcodec_name(codec_name):
        if not codec_name:
            return 'h264'
        name = str(codec_name).lower()
        if name in ('hevc', 'h265'):
            return 'hevc'
        return name

    @staticmethod
    def _normalize_profile_name(profile):
        if not profile:
            return None
        p = str(profile).lower().replace(' ', '')
        if p == 'constrainedbaseline':
            return 'baseline'
        return p

    @staticmethod
    def _browser_safe_pix_fmts(vcodec):
        vcodec = VideoProcessor._normalize_vcodec_name(vcodec)
        if vcodec == 'hevc':
            return ('yuv420p', 'yuv420p10le')
        return ('yuv420p', 'yuvj420p')

    @classmethod
    def pix_fmt_needs_reencode_for_browser(cls, pix_fmt, vcodec):
        """True wenn pix_fmt für Stream-Copy-Final mux nicht browser-tauglich ist."""
        if not pix_fmt:
            return False
        return str(pix_fmt) not in cls._browser_safe_pix_fmts(vcodec)

    def _probe_video_stream_summary(self, video_path):
        """Liest zentrale Video-Stream-Eigenschaften für Concat-Kompatibilitätsprüfungen."""
        try:
            info = self._get_video_info(video_path)
            return {
                'width': info.get('width'),
                'height': info.get('height'),
                'fps': info.get('fps'),
                'pix_fmt': info.get('pix_fmt'),
                'vcodec': self._normalize_vcodec_name(info.get('vcodec')),
                'vtag': (info.get('vtag') or '').lower(),
                'profile': self._normalize_profile_name(info.get('profile')),
            }
        except Exception as exc:
            print(f"Stream-Summary fehlgeschlagen für {video_path}: {exc}")
            return None

    def _assert_stream_copy_compatible(self, intro_path, combined_path):
        """Stellt sicher, dass Intro und Hauptvideo per Stream-Copy zusammenpassen."""
        if not intro_path or not os.path.exists(intro_path):
            raise ValueError("Intro-Datei fehlt für Stream-Copy-Zusammenführung.")
        if not combined_path or not os.path.exists(combined_path):
            raise ValueError("Hauptvideo fehlt für Stream-Copy-Zusammenführung.")

        intro = self._probe_video_stream_summary(intro_path)
        body = self._probe_video_stream_summary(combined_path)
        if not intro or not body:
            raise ValueError("Stream-Parameter von Intro oder Hauptvideo konnten nicht gelesen werden.")

        if intro['vcodec'] != body['vcodec']:
            raise ValueError(
                f"Intro-Codec ({intro['vcodec']}) passt nicht zum Hauptvideo ({body['vcodec']})."
            )

        for key in ('width', 'height', 'pix_fmt', 'fps'):
            if intro.get(key) != body.get(key):
                raise ValueError(
                    f"Intro und Hauptvideo unterscheiden sich bei {key}: "
                    f"intro={intro.get(key)}, body={body.get(key)}"
                )

        if intro.get('profile') and body.get('profile') and intro['profile'] != body['profile']:
            raise ValueError(
                f"Intro-Profil ({intro['profile']}) passt nicht zum Hauptvideo ({body['profile']})."
            )

    def _validate_browser_mp4(self, output_path, video_params, expected_duration_sec=None):
        """Prüft Browser-taugliche MP4 nach Stream-Copy-Mux. Returns (ok, reason)."""
        if not output_path or not os.path.exists(output_path):
            reason = "Ausgabedatei fehlt"
            print(f"Browser-Validierung: {reason}")
            return False, reason

        try:
            stream = self._probe_video_stream_summary(output_path)
            if not stream:
                reason = "Video-Stream konnte nicht gelesen werden"
                print(f"Browser-Validierung: {reason}")
                return False, reason

            vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))
            safe_pix_fmts = self._browser_safe_pix_fmts(vcodec)
            if vcodec == 'h264':
                if stream['vcodec'] != 'h264':
                    reason = f"Codec ist {stream['vcodec']}, erwartet h264"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason
                if stream.get('pix_fmt') not in safe_pix_fmts:
                    reason = f"pix_fmt {stream.get('pix_fmt')} (erlaubt: {', '.join(safe_pix_fmts)})"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason
                vtag = stream.get('vtag') or ''
                if vtag and vtag not in ('avc1', 'avc3'):
                    reason = f"Video-Tag {vtag} (erlaubt: avc1, avc3)"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason
            elif vcodec == 'hevc':
                if stream['vcodec'] != 'hevc':
                    reason = f"Codec ist {stream['vcodec']}, erwartet hevc"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason
                if stream.get('pix_fmt') not in safe_pix_fmts:
                    reason = f"pix_fmt {stream.get('pix_fmt')} (erlaubt: {', '.join(safe_pix_fmts)})"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason
                vtag = stream.get('vtag') or ''
                if vtag and vtag not in ('hvc1', 'hev1'):
                    reason = f"Video-Tag {vtag} (erlaubt: hvc1, hev1)"
                    print(f"Browser-Validierung: {reason}")
                    return False, reason

            if expected_duration_sec and expected_duration_sec > 0:
                actual = self._get_video_duration(output_path)
                if abs(actual - expected_duration_sec) > 3.0:
                    reason = (
                        f"Dauer abweichend (erwartet ~{expected_duration_sec:.1f}s, ist {actual:.1f}s)"
                    )
                    print(f"Browser-Validierung: {reason}")
                    return False, reason

            return True, ""
        except Exception as exc:
            reason = str(exc)
            print(f"Browser-Validierung fehlgeschlagen: {reason}")
            return False, reason

    def _prepare_final_mux_segments(
        self,
        intro_path,
        combined_video_path,
        video_params,
        work_temp_dir,
        force_normalize=False,
        use_ts_concat=False,
    ):
        """
        Bereitet Intro + Hauptvideo für Stream-Copy-Zusammenführung vor.
        HEVC/H.264-TS → MPEG-TS-Concat (Browser-kompatibel), sonst H.264 → MP4-concat.
        Schnellpfad: ohne body_norm/intro_norm wenn moov vor mdat (Vorschau-Concat).
        Returns: dict mit mux-Parametern + Liste temporärer Dateien.
        """
        extra_temp_files = []
        vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))

        if not video_params.get("has_audio", True):
            self._update_status("Erzeuge stille Audiospur für Hauptvideo...")
            temp_combined_path = os.path.join(work_temp_dir, "combined_with_silent_audio.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-i", combined_video_path,
                "-f", "lavfi", "-i",
                f"anullsrc=channel_layout={video_params['channel_layout']}:sample_rate={video_params['sample_rate']}",
                "-c:v", "copy",
                "-c:a", video_params['acodec'],
                "-shortest",
                "-movflags", "+faststart",
                temp_combined_path,
            ]
            subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW,
            )
            body_path = temp_combined_path
            extra_temp_files.append(temp_combined_path)
        else:
            body_path = combined_video_path

        skip_norm = (
            not force_normalize
            and self._mp4_has_faststart(intro_path)
            and self._mp4_has_faststart(body_path)
        )

        if skip_norm:
            self._update_status("Bereite Stream-Copy-Zusammenführung vor (Schnellpfad)...")
            intro_mux = intro_path
            body_mux = body_path
        else:
            self._update_status("Normalisiere Intro- und Hauptvideo-Timestamps...")
            intro_norm = os.path.join(work_temp_dir, "intro_norm.mp4")
            body_norm = os.path.join(work_temp_dir, "body_norm.mp4")
            extra_temp_files.extend([intro_norm, body_norm])
            self._normalize_mp4_for_concat(intro_path, intro_norm, video_params)
            self._normalize_mp4_for_concat(body_path, body_norm, video_params)
            intro_mux = intro_norm
            body_mux = body_norm

        if vcodec == 'hevc' or use_ts_concat:
            if use_ts_concat and vcodec == 'h264':
                self._update_status("H.264: bereite MPEG-TS-Concat vor (stabile Wiedergabe)...")
            else:
                self._update_status("HEVC: bereite MPEG-TS-Concat vor (stabile Wiedergabe)...")
            intro_ts = os.path.join(work_temp_dir, "intro.ts")
            body_ts = os.path.join(work_temp_dir, "body.ts")
            extra_temp_files.extend([intro_ts, body_ts])
            self._mp4_to_mpegts_stream_copy(intro_mux, intro_ts, vcodec, video_params)
            if use_ts_concat and vcodec == 'h264':
                self._update_status("H.264: Hauptvideo nach MPEG-TS (Stream-Copy)...")
            else:
                self._update_status("HEVC: Hauptvideo nach MPEG-TS (Stream-Copy)...")
            self._mp4_to_mpegts_stream_copy(body_mux, body_ts, vcodec, video_params)
            return {
                'method': 'ts',
                'intro_ts_path': intro_ts,
                'body_ts_path': body_ts,
                'combined_body_path': body_mux,
                'temp_files': extra_temp_files,
                'used_fast_path': skip_norm,
                'intro_source': intro_path,
                'combined_video_path': combined_video_path,
                'work_temp_dir': work_temp_dir,
            }

        concat_list_path = os.path.join(work_temp_dir, "final_concat_list.txt")
        extra_temp_files.append(concat_list_path)
        self._update_status("Schreibe concat-Liste (Intro + Hauptvideo)...")
        with open(concat_list_path, 'w', encoding='utf-8') as f:
            intro_escaped = os.path.abspath(intro_mux).replace('\\', '/')
            combined_escaped = os.path.abspath(body_mux).replace('\\', '/')
            f.write(f"file '{intro_escaped}'\n")
            f.write(f"file '{combined_escaped}'\n")

        return {
            'method': 'mp4_concat',
            'concat_list_path': concat_list_path,
            'combined_body_path': body_mux,
            'temp_files': extra_temp_files,
            'used_fast_path': skip_norm,
            'intro_source': intro_path,
            'combined_video_path': combined_video_path,
            'work_temp_dir': work_temp_dir,
        }

    def _execute_final_mux_command(self, full_video_output_path, video_params, mux_segments):
        """Baut den FFmpeg-Befehl für den Stream-Copy-Mux (MP4-concat oder MPEG-TS-concat)."""
        if mux_segments.get('method') == 'ts':
            vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))
            if vcodec == 'h264':
                self._update_status("Füge Intro an (H.264 Stream-Copy via MPEG-TS)...")
            else:
                self._update_status("Füge Intro an (HEVC Stream-Copy via MPEG-TS)...")
            return self._build_final_intro_body_stream_copy_command(
                full_video_output_path,
                video_params,
                intro_ts_path=mux_segments['intro_ts_path'],
                body_ts_path=mux_segments['body_ts_path'],
            )
        self._update_status("Füge Intro an (Stream-Copy, ohne Neuencode)...")
        return self._build_final_intro_body_stream_copy_command(
            full_video_output_path,
            video_params,
            concat_list_path=mux_segments['concat_list_path'],
        )

    @staticmethod
    def _remove_output_file(output_path):
        if output_path and os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass

    def _run_stream_copy_mux_attempt(
        self,
        full_video_output_path,
        video_params,
        mux_segments,
        temp_intro_with_audio_path,
        intro_dauer,
        expected_duration,
        task_name,
        encoding_lane,
    ):
        """Führt einen Stream-Copy-Mux aus und validiert das Ergebnis. Returns (ok, reason)."""
        combined_body_path = mux_segments['combined_body_path']
        self._assert_stream_copy_compatible(temp_intro_with_audio_path, combined_body_path)
        command = self._execute_final_mux_command(full_video_output_path, video_params, mux_segments)
        mux_progress_duration = self._estimate_stream_copy_mux_duration_sec(
            intro_dauer, combined_body_path, mux_segments
        )
        self._run_ffmpeg_with_progress(
            command,
            mux_progress_duration,
            task_name,
            task_id=None,
            encoding_lane=encoding_lane,
        )
        return self._validate_browser_mp4(full_video_output_path, video_params, expected_duration)

    def _build_final_intro_body_reencode_command(
        self,
        output_path,
        intro_path,
        body_path,
        video_params,
    ):
        """Re-Encode-Fallback: Intro + Body per filter concat zu browser-tauglicher MP4."""
        vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))
        sw_codec = 'hevc' if vcodec == 'hevc' else 'h264'
        encoding_params = self.hw_detector._get_software_params(sw_codec)
        encoder_name = encoding_params.get('encoder') or 'libx264'

        if vcodec == 'hevc' and self._is_10bit_pix_fmt(video_params.get('pix_fmt')):
            target_pix_fmt = 'yuv420p10le'
        else:
            target_pix_fmt = 'yuv420p'

        cmd = ['ffmpeg', '-y', '-i', intro_path, '-i', body_path]
        cmd.extend([
            '-filter_complex', '[0:v:0][0:a:0][1:v:0][1:a:0]concat=n=2:v=1:a=1[outv][outa]',
            '-map', '[outv]', '-map', '[outa]',
        ])
        cmd.extend(encoding_params['output_params'])

        if encoder_name == 'libx264':
            cmd.extend(['-preset', 'veryfast', '-crf', '18'])
        elif encoder_name == 'libx265':
            cmd.extend(['-preset', 'veryfast', '-crf', '20'])

        cmd.extend(['-pix_fmt', target_pix_fmt])

        profile_str = self._normalize_profile_name(video_params.get('profile'))
        if profile_str and vcodec in ('h264', 'hevc'):
            if vcodec in ('hevc',) and profile_str not in ('main', 'main10'):
                profile_str = 'main'
            cmd.extend(['-profile:v', profile_str])

        if video_params.get('level') and vcodec in ('h264', 'hevc'):
            cmd.extend(['-level:v', self._ffmpeg_level_string(vcodec, video_params['level'])])

        vtag = video_params.get('vtag')
        if vtag and vcodec in ('h264', 'hevc'):
            cmd.extend(['-tag:v', vtag])
        elif vcodec == 'h264':
            cmd.extend(['-tag:v', 'avc1'])
        elif vcodec == 'hevc':
            cmd.extend(['-tag:v', 'hvc1'])

        cmd.extend(['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', output_path])
        return cmd

    def _run_final_intro_body_reencode_mux(
        self,
        full_video_output_path,
        video_params,
        intro_path,
        body_path,
        intro_dauer,
        task_name,
        encoding_lane=0,
    ):
        """Letzter Ausweg: Intro + Hauptvideo einmal neu encodieren."""
        self._update_status("Stream-Copy fehlgeschlagen – encodiere Intro + Video neu...")
        expected_duration = self._estimate_final_output_duration_sec(intro_dauer, body_path)
        command = self._build_final_intro_body_reencode_command(
            full_video_output_path, intro_path, body_path, video_params
        )
        self._run_ffmpeg_with_progress(
            command,
            expected_duration,
            f"{task_name} (Re-Encode)",
            task_id=None,
            encoding_lane=encoding_lane,
        )

    def _run_final_intro_body_mux(
        self,
        full_video_output_path,
        video_params,
        mux_segments,
        temp_intro_with_audio_path,
        intro_dauer,
        task_name="Finaler Schnitt (Intro + Video)",
        encoding_lane=0,
        extra_temp_files=None,
    ):
        """Fügt Intro + Hauptvideo per Stream-Copy zusammen; Fallbacks bei Validierungsfehlern."""
        combined_body_path = mux_segments['combined_body_path']
        expected_duration = self._estimate_final_output_duration_sec(intro_dauer, combined_body_path)
        vcodec = self._normalize_vcodec_name(video_params.get('vcodec', 'h264'))
        last_reason = "Unbekannter Validierungsfehler"

        self._check_for_cancellation()

        ok, reason = self._run_stream_copy_mux_attempt(
            full_video_output_path,
            video_params,
            mux_segments,
            temp_intro_with_audio_path,
            intro_dauer,
            expected_duration,
            task_name,
            encoding_lane,
        )
        if ok:
            print("✓ Finaler Schnitt per Stream-Copy (Browser-Validierung OK)")
            return
        last_reason = reason
        print(f"⚠ Browser-Validierung fehlgeschlagen (Stream-Copy): {reason}")
        self._remove_output_file(full_video_output_path)

        if mux_segments.get('used_fast_path'):
            print("⚠ Versuche Remux mit Timestamp-Normalisierung...")
            self._update_status("Normalisiere Timestamps und füge erneut zusammen...")
            norm_segments = self._prepare_final_mux_segments(
                mux_segments['intro_source'],
                mux_segments['combined_video_path'],
                video_params,
                mux_segments['work_temp_dir'],
                force_normalize=True,
            )
            if extra_temp_files is not None:
                extra_temp_files.extend(norm_segments.get('temp_files', []))

            ok, reason = self._run_stream_copy_mux_attempt(
                full_video_output_path,
                video_params,
                norm_segments,
                temp_intro_with_audio_path,
                intro_dauer,
                expected_duration,
                task_name,
                encoding_lane,
            )
            if ok:
                print("✓ Finaler Schnitt per Stream-Copy (Normalisierung OK)")
                return
            last_reason = reason
            print(f"⚠ Browser-Validierung fehlgeschlagen (Normalisierung): {reason}")
            self._remove_output_file(full_video_output_path)
            mux_segments = norm_segments

        if vcodec == 'h264' and mux_segments.get('method') != 'ts':
            print("⚠ Versuche H.264 MPEG-TS-Concat...")
            ts_segments = self._prepare_final_mux_segments(
                mux_segments['intro_source'],
                mux_segments['combined_video_path'],
                video_params,
                mux_segments['work_temp_dir'],
                force_normalize=True,
                use_ts_concat=True,
            )
            if extra_temp_files is not None:
                extra_temp_files.extend(ts_segments.get('temp_files', []))

            ok, reason = self._run_stream_copy_mux_attempt(
                full_video_output_path,
                video_params,
                ts_segments,
                temp_intro_with_audio_path,
                intro_dauer,
                expected_duration,
                task_name,
                encoding_lane,
            )
            if ok:
                print("✓ Finaler Schnitt per Stream-Copy (H.264 MPEG-TS OK)")
                return
            last_reason = reason
            print(f"⚠ Browser-Validierung fehlgeschlagen (H.264 MPEG-TS): {reason}")
            self._remove_output_file(full_video_output_path)
            combined_body_path = ts_segments['combined_body_path']

        self._run_final_intro_body_reencode_mux(
            full_video_output_path,
            video_params,
            temp_intro_with_audio_path,
            combined_body_path,
            intro_dauer,
            task_name,
            encoding_lane=encoding_lane,
        )
        ok, reason = self._validate_browser_mp4(
            full_video_output_path, video_params, expected_duration
        )
        if ok:
            print("✓ Finaler Schnitt per Re-Encode (Browser-Validierung OK)")
            return

        last_reason = reason or last_reason
        raise Exception(
            f"Finale MP4 ist nach allen Mux-Versuchen nicht browser-kompatibel: {last_reason}"
        )

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
        video_clip_paths = payload.get("video_clip_paths", [])  # NEU: Einzelne Clips
        photo_paths = payload.get("photo_paths", [])
        self._photo_import_epochs = payload.get("photo_import_epochs") or {}
        kunde = payload.get("kunde")
        settings = payload.get("settings")
        # NEU: Flag für Wasserzeichen-Version
        create_watermark_version = payload.get("create_watermark_version", False)
        # NEU: Index des für Wasserzeichen ausgewählten Clips
        watermark_clip_index = payload.get("watermark_clip_index", None)
        # NEU: Indizes der für Wasserzeichen ausgewählten Fotos
        watermark_photo_indices = payload.get("watermark_photo_indices", [])

        print("kunde Objekt:", kunde)
        gast = form_data["gast"]
        tandemmaster = form_data["tandemmaster"]
        videospringer = form_data["videospringer"]
        datum = form_data["datum"]
        dauer = settings.get("dauer", "5")
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
                gast, tandemmaster, videospringer,
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
                    video_params['width'], video_params['height'], outside_video_mode
                )

                hintergrund_path = self.hintergrund_path
                if not os.path.exists(hintergrund_path):
                    raise FileNotFoundError("hintergrund.png fehlt im assets/ Ordner")

                work_temp = self._get_work_temp_dir(combined_video_path, speicherort)

                # Schritt 4: Kompatiblen Intro-Clip erstellen
                self._check_for_cancellation()
                self._update_progress(4, TOTAL_STEPS)
                self._update_status("Erstelle exakt kompatiblen Intro-Clip...")
                temp_intro_with_audio_path = os.path.join(work_temp, "intro_with_silent_audio.mp4")
                temp_files.append(temp_intro_with_audio_path)
                self._create_intro_with_silent_audio(
                    temp_intro_with_audio_path, dauer, video_params, drawtext_filter
                )

                # Schritt 5 & 6: MP4 concat-Liste (kein MPEG-TS — spart viel Plattenplatz)
                self._check_for_cancellation()
                self._update_progress(5, TOTAL_STEPS)
                self._update_status("Bereite Stream-Copy-Zusammenführung vor...")

                mux_segments = self._prepare_final_mux_segments(
                    temp_intro_with_audio_path,
                    combined_video_path,
                    video_params,
                    work_temp,
                )
                temp_files.extend(mux_segments.get('temp_files', []))

                self._assert_stream_copy_compatible(
                    temp_intro_with_audio_path, mux_segments['combined_body_path']
                )

                self._update_progress(6, TOTAL_STEPS)

                # Schritt 6a: Längsten Clip finden (falls Wasserzeichen gewünscht)
                longest_clip_path = None
                if create_watermark_version:
                    self._check_for_cancellation()
                    self._update_progress(7, TOTAL_STEPS)
                    self._update_status("Suche Clip für Wasserzeichen...")

                    # NEU: Verwende ausgewählten Clip, wenn vorhanden; sonst finde längsten Clip
                    if watermark_clip_index is not None and 0 <= watermark_clip_index < len(video_clip_paths):
                        longest_clip_path = video_clip_paths[watermark_clip_index]
                        print(f"Verwende Clip an Index {watermark_clip_index} für Wasserzeichen: {longest_clip_path}")
                    else:
                        longest_clip_path = self._find_longest_clip(video_clip_paths)
                        print(f"Verwende längsten Clip für Wasserzeichen: {longest_clip_path}")
                    if longest_clip_path:
                        self._update_status(
                            f"Wasserzeichen-Quellclip: {os.path.basename(str(longest_clip_path))}"
                        )
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

                # Schritt 8-10: Video-Erstellung (sequenziell: Final-Mux zuerst, dann Wasserzeichen)
                if full_video_output_path or (create_watermark_version and longest_clip_path):
                    if full_video_output_path:
                        self._check_for_cancellation()
                        self._update_progress(9, TOTAL_STEPS)
                        self._run_final_intro_body_mux(
                            full_video_output_path,
                            video_params,
                            mux_segments,
                            temp_intro_with_audio_path,
                            dauer,
                            task_name="Finaler Schnitt (Intro + Video)",
                            encoding_lane=0,
                            extra_temp_files=temp_files,
                        )
                    else:
                        self._update_progress(9, TOTAL_STEPS)
                        self._update_status("Überspringe normale Video-Erstellung...")

                    if create_watermark_version and longest_clip_path:
                        self._check_for_cancellation()
                        self._update_progress(10, TOTAL_STEPS)
                        self._update_status("Erstelle Video mit Wasserzeichen (nur längster Clip)...")

                        watermark_video_output_path = self._generate_watermark_video_path(
                            base_output_dir, base_filename
                        )

                        self._create_video_with_watermark(
                            longest_clip_path,
                            watermark_video_output_path,
                            video_params
                        )
                    else:
                        self._update_progress(10, TOTAL_STEPS)
                else:
                    # Weder normale noch Wasserzeichen-Version
                    self._update_progress(9, TOTAL_STEPS)
                    self._update_progress(10, TOTAL_STEPS)

            else:
                # Schritte 2-8 überspringen, wenn kein Video vorhanden ist
                self._update_status("Kein Video zur Verarbeitung ausgewählt. Überspringe...")
                for i in range(2, 11 if create_watermark_version else 10):  # Schritte 2 bis 10/9
                    self._update_progress(i, TOTAL_STEPS)
                full_video_output_path = None  # Sicherstellen, dass es None ist

            photo_rename_map = self._build_photo_rename_map(photo_paths) if photo_paths else {}

            # --- NEU: FOTO WASSERZEICHEN VERARBEITUNG ---
            watermark_photo_count = 0
            if watermark_photo_indices and photo_paths:
                self._check_for_cancellation()
                self._update_status("Erstelle Wasserzeichen-Vorschau für Fotos...")

                # 1. Pfade der ausgewählten Fotos holen
                selected_photo_paths = []
                for i in watermark_photo_indices:
                    if i < len(photo_paths):
                        selected_photo_paths.append(photo_paths[i])

                if selected_photo_paths:
                    # 2. Preview-Verzeichnis erstellen (Ziel: base_output_dir/Preview_Foto)
                    try:
                        preview_dir = self._generate_watermark_photo_directory(base_output_dir)
                        total_wm_photos = len(selected_photo_paths)

                        # 3. Jedes ausgewählte Foto verarbeiten
                        for wm_i, photo_path in enumerate(selected_photo_paths):
                            self._check_for_cancellation()
                            if os.path.exists(photo_path):
                                self._update_status(
                                    f"Foto-Wasserzeichen {wm_i + 1}/{total_wm_photos}: "
                                    f"{os.path.basename(photo_path)}"
                                )
                                out_name = photo_rename_map.get(
                                    photo_path, os.path.basename(photo_path)
                                )
                                self._create_photo_with_watermark(
                                    photo_path, preview_dir, out_name
                                )
                                watermark_photo_count += 1

                        print(f"{watermark_photo_count} Foto(s) mit Wasserzeichen verarbeitet und in {preview_dir} gespeichert.")

                    except Exception as e:
                        print(f"Fehler bei der Erstellung der Foto-Wasserzeichen: {e}")
                        self._update_status(f"Fehler bei Foto-WM: {e}")

            # --- FOTO VERARBEITUNG (Schritt 11) ---
            self._check_for_cancellation()
            step_photo = 11 if create_watermark_version else 10
            self._update_progress(step_photo, TOTAL_STEPS)
            copied_count = 0
            if photo_paths:
                self._update_status("Kopiere Fotos (Start)...")
                copied_count = self._copy_photos_to_output_directory(
                    photo_paths, base_output_dir, kunde, photo_rename_map
                )
                if copied_count:
                    self._update_status(f"Fotos kopiert: {copied_count} Datei(en).")
            else:
                self._update_status("Keine Fotos zum Kopieren ausgewählt.")

            # --- SERVER UPLOAD (Schritt 12) ---
            self._check_for_cancellation()

            # Speichere MARKER Datei im Ausgabeordner (VOR dem Server-Upload!)
            self._update_status("Schreibe Abschluss-Datei (_fertig.txt)...")
            marker_path = os.path.join(base_output_dir, "_fertig.txt")
            with open(marker_path, 'w') as marker_file:
                try:
                    marker_type = "Outside" if outside_video_mode else "Handcam"
                    form_mode = form_data.get("form_mode")
                    oldschool_mode = bool(settings.get("oldschool_mode", False)) if settings else False
                    if kunde is not None and is_dataclass(kunde):
                        if oldschool_mode and form_mode != "kunde":
                            marker_data = {
                                "vorname": (form_data.get("vorname", "") or "").strip(),
                                "nachname": (form_data.get("nachname", "") or "").strip(),
                                "email": (form_data.get("email", "") or "").strip(),
                            }
                            telefon = (form_data.get("telefon", "") or "").strip()
                            if telefon:
                                marker_data["telefon"] = telefon
                            marker_file.write(json.dumps(marker_data, ensure_ascii=False))
                        else:
                            marker_data = asdict(kunde)
                            marker_data["type"] = marker_type

                            # ID-Felder strikt exklusiv halten (QR ODER manuell)
                            marker_data.pop("kunden_id", None)
                            marker_data.pop("booking_id", None)
                            marker_data.pop("kunden_id_hash", None)
                            marker_data.pop("booking_id_hash", None)

                            if form_mode == "kunde":
                                marker_data["kunden_id_hash"] = (form_data.get("kunden_id_hash", "") or "").strip() or None
                                marker_data["booking_id_hash"] = (form_data.get("booking_id_hash", "") or "").strip() or None
                            else:
                                marker_data["kunden_id"] = (form_data.get("kunden_id", "") or "").strip() or None
                                marker_data["booking_id"] = (form_data.get("booking_id", "") or "").strip() or None

                            # Nicht gewünschte Felder explizit aus _fertig.txt entfernen
                            excluded_fields = {
                                "vorname", "nachname", "email", "telefon",
                                "handcam_foto", "handcam_video", "outside_foto", "outside_video",
                                "ist_bezahlt_handcam_foto", "ist_bezahlt_handcam_video",
                                "ist_bezahlt_outside_foto", "ist_bezahlt_outside_video",
                            }
                            for field_name in excluded_fields:
                                marker_data.pop(field_name, None)

                            marker_file.write(json.dumps(marker_data, ensure_ascii=False))
                    else:
                        marker_file.write(json.dumps({"type": marker_type}, ensure_ascii=False))
                except TypeError as json_err:
                    print(f"Fehler beim Serialisieren der 'kunde'-Daten: {json_err}")

            # Jetzt Server-Upload durchführen (inkl. _fertig.txt)
            step_server = 12 if create_watermark_version else 11
            self._update_progress(step_server, TOTAL_STEPS)
            server_uploaded = False
            if upload_to_server:
                self._update_status("Lade Verzeichnis auf Server hoch...")
                # Wir laden das gesamte Basis-Verzeichnis hoch (inkl. _fertig.txt)
                success, message, server_path = self._upload_to_server(base_output_dir)
                server_uploaded = success
                if success:
                    self._update_status(f"Server-Upload abgeschlossen ({message})")
                else:
                    self._update_status(f"Server-Upload fehlgeschlagen ({message})")

            # --- ABSCHLUSS (letzter Schritt) ---
            final_step = 13 if create_watermark_version else 12
            self._update_progress(final_step, TOTAL_STEPS)

            # Erstelle strukturierte Informationen über erstellte Elemente
            created_items = {
                'video': bool(full_video_output_path),
                'watermark_video': bool(watermark_video_output_path),
                'photos': copied_count,
                'watermark_photos': watermark_photo_count,
                'server_uploaded': server_uploaded
            }

            self._show_success_message(created_items)

        except subprocess.CalledProcessError as e:
            if self.cancel_event.is_set():
                raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
            error_details = f"FFmpeg Error:\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
            print(error_details)
            raise Exception(f"Fehler bei der Videoverarbeitung. Details siehe Konsole.")
        except PermissionError as e:
            # Spezifische Behandlung von Zugriffsfehlern
            raise PermissionError(f"Fehler bei der Erstellung: {str(e)}")
        except OSError as e:
            # Spezifische Behandlung von OS-Fehlern
            raise OSError(f"Fehler bei der Erstellung: {str(e)}")
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
        watermark_dir = os.path.join(base_output_dir, "Preview_Video")

        try:
            os.makedirs(watermark_dir, exist_ok=True)
        except PermissionError as e:
            error_msg = f"Zugriff verweigert beim Erstellen des Vorschau-Ordners\n\n"
            error_msg += f"Basis-Verzeichnis: {base_output_dir}\n"
            error_msg += f"Unterordner: Preview_Video\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Fehler beim Erstellen des Vorschau-Ordners\n\n"
            error_msg += f"Voller Pfad: {watermark_dir}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise OSError(error_msg)

        output_filename = f"{base_filename}_preview.mp4"
        full_output_path = os.path.join(watermark_dir, output_filename)

        return full_output_path

    def _create_video_with_watermark(self, input_video_path, output_path, video_params, task_id=None,
                                     encoding_lane=0):
        """
        Erstellt eine Video-Version mit Wasserzeichen über dem gesamten Video.
        NEU: Nutzt Hardware-Encoding wenn verfügbar, aber Software-Decoding für Filter-Kompatibilität.

        WICHTIG:
        - overlay-Filter benötigt Software-Frames (yuv420p), daher KEIN Hardware-Decoding!
        - Wasserzeichen-Videos werden IMMER mit H.264 codiert für maximale Kompatibilität
        """

        # Pfad zum Wasserzeichen-Bild
        wasserzeichen_path = os.path.join(os.path.dirname(self.hintergrund_path), "preview_stempel.png")

        if not os.path.exists(wasserzeichen_path):
            raise FileNotFoundError("preview_stempel.png fehlt im assets/ Ordner")

        # Hole Videodauer für Fortschrittsanzeige
        total_duration = self._get_video_duration(input_video_path)

        # Wasserzeichen-Video in 240p erstellen
        target_width = 320
        target_height = 240

        # Wasserzeichen-Filter mit Downscaling + Overlay
        watermark_filter = (
            f"[0]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
            f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p[v];"
            f"[1]scale={target_width}:{target_height}:force_original_aspect_ratio=decrease:eval=init[wm_scaled];"
            f"[v][wm_scaled]overlay=(W-w)/2:(H-h)/2"
        )

        # Hole Encoding-Parameter für H.264 (Wasserzeichen-Videos werden IMMER mit H.264 codiert)
        encoding_params = self._get_encoding_params('h264')

        # Baue FFmpeg-Befehl
        command = ["ffmpeg", "-y"]

        # WICHTIG: KEIN Hardware-Decoding verwenden!
        # overlay-Filter benötigt Software-Frames (yuv420p), Hardware-Frames (qsv) sind inkompatibel
        # Nur die Input-Dateien, OHNE hwaccel-Parameter
        command.extend(["-i", input_video_path, "-i", wasserzeichen_path])

        # Filter
        command.extend(["-filter_complex", watermark_filter])

        # Output-Parameter: Hardware-Encoder wenn verfügbar, sonst Software
        command.extend(encoding_params['output_params'])

        # Für Wasserzeichen-Version: schnellere Einstellungen wenn Software-Encoding
        if not self.hw_accel_enabled:
            command.extend([
                "-preset", "ultrafast",     # Schnellstes Preset
                "-crf", "28",               # Höheres CRF = schneller + kleinere Datei
            ])
        else:
            # Bei Hardware-Encoding: Schnelle Qualitätseinstellungen
            print(f"  → Nutze Hardware-Encoder für Wasserzeichen: {encoding_params['encoder']}")

        command.extend([
            "-movflags", "+faststart",
            "-an",  # Kein Audio
            output_path
        ])

        # Task Name basierend auf task_id
        task_name = f"Wasserzeichen-Video (Task {task_id})" if task_id else "Wasserzeichen-Video"

        # task_id nicht an FFmpeg-Progress: kein Eintrag in drag_drop für diese Vorschau.
        # encoding_lane: 1 = zweite Zeile in der Haupt-UI bei parallelem Final-Job
        self._run_ffmpeg_with_progress(
            command, total_duration, task_name, task_id=None, encoding_lane=encoding_lane
        )

    @staticmethod
    def _ffmpeg_level_string(vcodec, level_value):
        """Wandelt ffprobe-level in FFmpeg -level:v (H.264: /10, HEVC: /30)."""
        try:
            level_num = float(level_value)
        except (ValueError, TypeError):
            return str(level_value)
        if VideoProcessor._normalize_vcodec_name(vcodec) == 'hevc':
            return str(level_num / 30.0)
        return str(level_num / 10.0)

    @staticmethod
    def _is_10bit_pix_fmt(pix_fmt):
        return '10' in str(pix_fmt or '')

    def _intro_requires_software_encoder(self, v_params, encoder_name):
        """
        Intro nutzt drawtext/PNG-Filter — Intel QSV HEVC 10-bit/Main10 scheitert oft.
        """
        profile = self._normalize_profile_name(v_params.get('profile'))
        pix_fmt = v_params.get('pix_fmt', 'yuv420p')
        vcodec = self._normalize_vcodec_name(v_params.get('vcodec', 'h264'))

        if self._is_10bit_pix_fmt(pix_fmt) or profile == 'main10':
            return True
        if encoder_name == 'hevc_qsv' and vcodec == 'hevc':
            return True
        return False

    def _get_intro_encoding_params(self, v_params):
        """Encoding-Parameter für Intro: SW bei 10-bit/HEVC-QSV, sonst HW wenn aktiv."""
        vcodec = v_params.get('vcodec', 'h264')
        if self.hw_accel_enabled:
            hw_params = self._get_encoding_params(vcodec)
            encoder_name = hw_params.get('encoder') or 'libx264'
            if self._intro_requires_software_encoder(v_params, encoder_name):
                print(
                    f"ℹ Intro: Software-Encoder für {vcodec} "
                    f"(pix_fmt={v_params.get('pix_fmt')}, profile={v_params.get('profile')})"
                )
                sw = self.hw_detector._get_software_params(
                    'hevc' if vcodec in ('hevc', 'h265') else vcodec
                )
                return sw, False
            return hw_params, True
        return self._get_encoding_params(vcodec), False

    def _build_intro_ffmpeg_command(self, output_path, dauer, v_params, drawtext_filter, force_software=False):
        """Baut den FFmpeg-Befehl für die Intro-Erstellung."""
        video_filters = (
            f"scale={v_params['width']}:{v_params['height']}:force_original_aspect_ratio=decrease,"
            f"pad={v_params['width']}:{v_params['height']}:(ow-iw)/2:(oh-ih)/2:black,"
            f"{drawtext_filter}"
        )

        vcodec = v_params.get('vcodec', 'h264')
        if force_software:
            sw_codec = 'hevc' if vcodec in ('hevc', 'h265') else vcodec
            encoding_params = self.hw_detector._get_software_params(sw_codec)
            use_hw_tuning = False
        else:
            encoding_params, use_hw_tuning = self._get_intro_encoding_params(v_params)

        encoder_name = encoding_params.get('encoder') or 'libx264'
        use_hw_tuning = use_hw_tuning and self.hw_accel_enabled and not force_software

        command = ["ffmpeg", "-y"]
        command.extend([
            "-loop", "1", "-i", self.hintergrund_path,
            "-f", "lavfi", "-i",
            f"anullsrc=channel_layout={v_params['channel_layout']}:sample_rate={v_params['sample_rate']}"
        ])
        command.extend(["-vf", video_filters])
        command.extend(encoding_params['output_params'])
        command.extend([
            "-pix_fmt", v_params['pix_fmt'],
            "-r", v_params['fps'],
            "-video_track_timescale", v_params['timescale'],
            "-c:a", v_params['acodec'],
            "-t", str(dauer),
            "-shortest",
            "-map", "0:v:0",
            "-map", "1:a:0"
        ])

        if not use_hw_tuning:
            if encoder_name == 'libx264':
                command.extend(["-preset", "veryfast", "-crf", "18"])
            elif encoder_name == 'libx265':
                command.extend(["-preset", "veryfast", "-crf", "20"])
            elif encoder_name == 'libvpx-vp9':
                command.extend(["-deadline", "good", "-cpu-used", "2", "-crf", "23", "-b:v", "0"])
            elif encoder_name in ('libaom-av1', 'libsvtav1'):
                command.extend(["-cpu-used", "6", "-crf", "28", "-b:v", "0"])
        else:
            if encoder_name.endswith('_nvenc'):
                command.extend(["-rc", "constqp", "-qp", "18", "-preset", "p2", "-no-scenecut", "1"])
            elif encoder_name.endswith('_qsv'):
                if vcodec in ('hevc', 'h265'):
                    command.extend(["-global_quality", "18"])
                else:
                    command.extend(["-global_quality", "18", "-look_ahead", "0", "-forced_idr", "1"])
            elif encoder_name.endswith('_amf'):
                command.extend(["-quality", "balanced", "-rc", "cqp", "-qp_i", "18", "-qp_p", "18"])
            elif encoder_name.endswith('_videotoolbox'):
                command.extend(["-q:v", "50"])
            elif encoder_name.endswith('_vaapi'):
                command.extend(["-qp", "18"])

        fps_int = self._parse_r_frame_rate(v_params.get('fps'))
        if vcodec in ('h264', 'hevc', 'h265'):
            command.extend(["-g", str(fps_int), "-keyint_min", str(fps_int), "-sc_threshold", "0", "-bf", "0"])
        command.extend(["-fps_mode", "cfr"])

        if v_params.get('color_range'):
            command.extend(["-color_range", v_params['color_range']])
        if v_params.get('colorspace'):
            command.extend(["-colorspace", v_params['colorspace']])
        if v_params.get('color_primaries'):
            command.extend(["-color_primaries", v_params['color_primaries']])
        if v_params.get('color_trc'):
            command.extend(["-color_trc", v_params['color_trc']])

        if v_params.get('profile') and vcodec in ('h264', 'hevc', 'h265'):
            profile_str = self._normalize_profile_name(v_params['profile'])
            if profile_str == 'constrainedbaseline':
                profile_str = 'baseline'
            if vcodec in ('hevc', 'h265') and profile_str not in ('main', 'main10'):
                profile_str = 'main'
            command.extend(["-profile:v", profile_str])

        if v_params.get('level') and vcodec in ('h264', 'hevc', 'h265'):
            command.extend(["-level:v", self._ffmpeg_level_string(vcodec, v_params['level'])])

        vtag = v_params.get('vtag')
        if vtag and vcodec in ('h264', 'hevc', 'h265', 'vp9', 'av1'):
            command.extend(["-tag:v", vtag])

        try:
            dauer_float = float(dauer)
            force_t = max(0.0, dauer_float - 0.05)
            # Erster Frame + letzter Frame als IDR → sauberer Übergang zum Hauptvideo
            command.extend(["-force_key_frames", f"expr:eq(n,0)+gte(t,{force_t})"])
        except (TypeError, ValueError):
            pass

        if encoder_name == 'libx264':
            command.extend(["-x264-params", "repeat-headers=1:nal-hrd=none:open-gop=0"])
        elif encoder_name == 'libx265':
            command.extend([
                "-x265-params",
                f"keyint={fps_int}:min-keyint={fps_int}:scenecut=0:open-gop=0:"
                f"repeat-headers=1:aud=1:bframes=0",
            ])

        command.extend(["-movflags", "+faststart"])
        command.append(output_path)
        return command

    def _create_intro_with_silent_audio(self, output_path, dauer, v_params, drawtext_filter):
        """
        Erstellt den Intro-Clip inklusive einer passenden stillen Audiospur.
        Bei HEVC Main 10 / 10-bit oder HW-Fehler: automatischer Software-Fallback.
        """
        self._check_for_cancellation()
        print(
            "Intro-Quellreferenz (combined preview): "
            f"profile={v_params.get('profile')} level={v_params.get('level')} "
            f"pix_fmt={v_params.get('pix_fmt')} has_b_frames={v_params.get('has_b_frames')} "
            f"fps={v_params.get('fps')} vcodec={v_params.get('vcodec')}"
        )
        print(f"Erstelle Intro mit erweiterten Parametern: {v_params}")

        try:
            duration_float = float(dauer)
        except (TypeError, ValueError):
            duration_float = None

        last_error = None
        for attempt, force_sw in enumerate((False, True)):
            if attempt == 1:
                print("⚠ Intro-Encoding fehlgeschlagen → Retry mit Software-Encoder")
                if os.path.exists(output_path):
                    try:
                        os.remove(output_path)
                    except OSError:
                        pass
            command = self._build_intro_ffmpeg_command(
                output_path, dauer, v_params, drawtext_filter, force_software=force_sw
            )
            try:
                self._run_ffmpeg_with_progress(
                    command, duration_float, "Intro-Erstellung", encoding_lane=0
                )
                return
            except subprocess.CalledProcessError as exc:
                if self.cancel_event.is_set():
                    raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
                last_error = exc
                if force_sw:
                    break

        print(f"Fehler bei Intro-Erstellung: {last_error.stderr if last_error and hasattr(last_error, 'stderr') else last_error}")
        raise last_error

    def _get_photo_capture_dt(self, photo_path):
        """Gleiche Zeitbasis wie Video/Foto-Tabelle (EXIF, ffprobe, Import-Snapshot, Dateisystem)."""
        snap = None
        if getattr(self, "_photo_import_epochs", None):
            snap = self._photo_import_epochs.get(os.path.normpath(photo_path))
        return datetime.fromtimestamp(get_photo_display_epoch(photo_path, snap))

    def _build_photo_rename_map(self, photo_paths):
        """
        Ordnet jedem Quellpfad einen eindeutigen Zielnamen zu:
        yyyyMMddHHmmss_<Originalname>; bei Kollision ' (1)', ' (2)', ... vor der Endung.
        """
        used = set()
        mapping = {}
        for src in photo_paths:
            if not os.path.exists(src):
                continue
            prefix = self._get_photo_capture_dt(src).strftime("%Y%m%d%H%M%S")
            candidate = f"{prefix}_{os.path.basename(src)}"
            if candidate in used:
                base, ext = os.path.splitext(candidate)
                n = 1
                while f"{base} ({n}){ext}" in used:
                    n += 1
                candidate = f"{base} ({n}){ext}"
            used.add(candidate)
            mapping[src] = candidate
        return mapping

    def _copy_photos_to_output_directory(self, photo_paths, base_output_dir, kunde, rename_map=None):
        """
        Kopiert alle Fotos in die entsprechenden Unterverzeichnisse (Handcam_Foto / Outside_Foto)
        basierend auf den im Kunde-Objekt ausgewählten Optionen.
        Gibt die Anzahl der kopierten *Quelldateien* zurück.
        """
        if not photo_paths or not kunde:
            return 0
        if rename_map is None:
            rename_map = {}

        # Definiere Zielverzeichnisse
        handcam_dir = os.path.join(base_output_dir, "Handcam_Foto")
        outside_dir = os.path.join(base_output_dir, "Outside_Foto")

        # Erstelle Verzeichnisse nur, wenn sie im Formular ausgewählt wurden
        if kunde.handcam_foto:
            os.makedirs(handcam_dir, exist_ok=True)
        if kunde.outside_foto:
            os.makedirs(outside_dir, exist_ok=True)

        copied_files_count = 0
        total = len(photo_paths)
        step = max(1, total // 12) if total > 12 else 1

        for idx, photo_path in enumerate(photo_paths):
            self._check_for_cancellation()
            if not os.path.exists(photo_path):
                continue

            if idx % step == 0 or idx == total - 1:
                self._update_status(
                    f"Kopiere Fotos ({idx + 1}/{total}): {os.path.basename(photo_path)}"
                )

            filename = rename_map.get(photo_path, os.path.basename(photo_path))
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

    def _generate_watermark_photo_directory(self, base_output_dir):
        """
        Erstellt den Ordner 'Preview_Foto' innerhalb des base_output_dir.
        """
        preview_dir_path = os.path.join(base_output_dir, "Preview_Foto")

        try:
            os.makedirs(preview_dir_path, exist_ok=True)
            return preview_dir_path
        except PermissionError as e:
            error_msg = f"Zugriff verweigert beim Erstellen des Foto-Vorschau-Ordners\n\n"
            error_msg += f"Pfad: {preview_dir_path}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Fehler beim Erstellen des Foto-Vorschau-Ordners\n\n"
            error_msg += f"Pfad: {preview_dir_path}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise OSError(error_msg)

    def _create_photo_with_watermark(self, input_photo_path, output_dir, output_filename):
        """
        Verwendet PIL/Pillow, um ein einzelnes Foto auf 720p (Höhe) zu skalieren
        und ein Wasserzeichen (80% Transparenz) darüber zu legen.
        Das Wasserzeichen wird so groß wie möglich gemacht, ohne das Seitenverhältnis zu ändern.
        """
        from PIL import Image

        wasserzeichen_path = os.path.join(os.path.dirname(self.hintergrund_path), "preview_stempel.png")

        if not os.path.exists(wasserzeichen_path):
            print(f"Warnung: Wasserzeichen-Datei nicht gefunden: {wasserzeichen_path}")
            return
        if not os.path.exists(input_photo_path):
            print(f"Warnung: Eingabe-Foto nicht gefunden: {input_photo_path}")
            return

        output_path = os.path.join(output_dir, output_filename)

        target_height = 720
        alpha_level = 1  # keine Transparenz

        try:
            # Lade Foto und Wasserzeichen
            foto = Image.open(input_photo_path).convert('RGBA')
            wasserzeichen = Image.open(wasserzeichen_path).convert('RGBA')

            # Skaliere Foto auf Zielhöhe, behalte Seitenverhältnis
            foto_aspect_ratio = foto.width / foto.height
            new_foto_width = int(target_height * foto_aspect_ratio)
            foto = foto.resize((new_foto_width, target_height), Image.Resampling.LANCZOS)

            # Berechne optimale Wasserzeichen-Größe:
            # Das Wasserzeichen soll so groß wie möglich sein, aber vollständig ins Foto passen
            wm_aspect_ratio = wasserzeichen.width / wasserzeichen.height
            foto_aspect = foto.width / foto.height

            if wm_aspect_ratio > foto_aspect:
                # Wasserzeichen ist breiter (im Verhältnis) -> Breite ist limitierend
                new_wm_width = foto.width
                new_wm_height = int(new_wm_width / wm_aspect_ratio)
            else:
                # Wasserzeichen ist höher (im Verhältnis) -> Höhe ist limitierend
                new_wm_height = foto.height
                new_wm_width = int(new_wm_height * wm_aspect_ratio)

            # Skaliere Wasserzeichen
            wasserzeichen = wasserzeichen.resize((new_wm_width, new_wm_height), Image.Resampling.LANCZOS)

            # Setze Transparenz des Wasserzeichens
            if wasserzeichen.mode == 'RGBA':
                r, g, b, a = wasserzeichen.split()
                # Multipliziere Alpha-Kanal mit Transparenz-Faktor
                a = a.point(lambda x: int(x * alpha_level))
                wasserzeichen = Image.merge('RGBA', (r, g, b, a))

            # Berechne Position (mittig)
            paste_x = (foto.width - wasserzeichen.width) // 2
            paste_y = (foto.height - wasserzeichen.height) // 2

            # Erstelle Composite-Bild
            foto.paste(wasserzeichen, (paste_x, paste_y), wasserzeichen)

            # Speichere als JPEG (konvertiere von RGBA zu RGB)
            foto_rgb = foto.convert('RGB')
            foto_rgb.save(output_path, 'JPEG', quality=90)

        except Exception as e:
            print(f"Fehler beim Erstellen des Wasserzeichen-Fotos für {output_filename}:")
            print(f"Fehler: {e}")
            # Fallback: Versuche es mit FFmpeg
            self._create_photo_with_watermark_ffmpeg(
                input_photo_path, output_dir, output_filename
            )

    def _create_photo_with_watermark_ffmpeg(self, input_photo_path, output_dir, output_filename):
        """
        Fallback: Verwendet FFmpeg für Wasserzeichen-Fotos.
        """
        wasserzeichen_path = os.path.join(os.path.dirname(self.hintergrund_path), "preview_stempel.png")
        output_path = os.path.join(output_dir, output_filename)
        target_height = 720
        alpha_level = 1

        # FFmpeg Filter:
        # Einfacher Ansatz: Skaliere Wasserzeichen mit scale, behalte Seitenverhältnis
        watermark_filter = (
            # Skaliere Hauptfoto auf Zielhöhe (Breite automatisch berechnet)
            f"[0:v]scale=w=-2:h={target_height}[v];"
            # Skaliere Wasserzeichen: Erst auf Foto-Breite, Höhe automatisch (Seitenverhältnis erhalten)
            # Dann prüfen ob es zu hoch ist und ggf. auf Foto-Höhe skalieren
            f"[1:v]scale=w=iw:h=-2[wm_original];"
            f"[wm_original][v]scale2ref=w='min(main_w,iw*main_h/ih)':h=-2:flags=bicubic[wm_scaled][v2];"
            # Setze Transparenz auf dem skalierten Wasserzeichen
            f"[wm_scaled]colorchannelmixer=aa={alpha_level}[wm_transparent];"
            # Überlagere mittig (horizontal und vertikal zentriert)
            f"[v2][wm_transparent]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2"
        )

        command = [
            "ffmpeg", "-y",
            "-i", input_photo_path,
            "-i", wasserzeichen_path,
            "-filter_complex", watermark_filter,
            "-frames:v", "1",  # Wichtig: Nur einen Frame (das Bild) ausgeben
            output_path
        ]

        try:
            subprocess.run(command, capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        except subprocess.CalledProcessError as e:
            print(f"Fehler bei FFmpeg-Foto-Wasserzeichen für {output_filename}:")
            print(f"STDERR: {e.stderr}")
            raise e

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
        
        has_audio = audio_stream is not None

        time_base = video_stream.get("time_base", "1/25").split('/')
        timescale = time_base[1] if len(time_base) == 2 else "25"

        # Codec-spezifisches vtag ermitteln
        vcodec = video_stream.get("codec_name", "h264")
        vtag = video_stream.get("codec_tag_string", "")

        # Wenn kein vtag vorhanden, verwende codec-spezifische Defaults
        if not vtag or vtag == "0x00000000":
            vtag_map = {
                'h264': 'avc1',
                'hevc': 'hvc1',
                'h265': 'hvc1',
                'vp9': 'vp09',
                'av1': 'av01'
            }
            vtag = vtag_map.get(vcodec, 'avc1')

        return {
            "width": video_stream.get("width"),
            "height": video_stream.get("height"),
            "fps": video_stream.get("r_frame_rate"),
            "timescale": timescale,
            "pix_fmt": video_stream.get("pix_fmt"),
            "vcodec": vcodec,
            "vtag": vtag,
            "has_audio": has_audio,
            "acodec": audio_stream.get("codec_name") if has_audio and audio_stream.get("codec_name") else "aac",
            "sample_rate": audio_stream.get("sample_rate") if has_audio and audio_stream.get("sample_rate") else "48000",
            "channel_layout": audio_stream.get("channel_layout", "stereo") if has_audio else "stereo",
            "color_range": video_stream.get("color_range"),
            "colorspace": video_stream.get("color_space"),
            "color_primaries": video_stream.get("color_primaries"),
            "color_trc": video_stream.get("color_transfer"),
            "profile": video_stream.get("profile"),
            "level": video_stream.get("level"),
            "has_b_frames": video_stream.get("has_b_frames"),
        }

    def _get_best_available_font(self):
        """
        Ermittelt den besten verfügbaren Font für die Text-Overlays.
        Prüft in dieser Reihenfolge:
        1. TheSans Bold (falls im assets-Ordner vorhanden)
        2. Segoe UI Semibold (moderne Windows-Schriftart)
        3. Arial Bold (Fallback)

        Returns:
            tuple: (font_name, fontfile_path_or_None)
        """
        # Prüfe ob TheSans im assets-Ordner liegt
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        thesans_path = os.path.join(base_dir, "assets", "fonts", "SansBlackCondRegular.ttf")

        if os.path.exists(thesans_path):
            return ("TheSans Bold", thesans_path)

        # Prüfe ob Segoe UI Semibold verfügbar ist (Windows 7+)
        # Segoe UI ist eine professionelle, moderne Sans-Serif
        segoe_paths = [
            "C:\\Windows\\Fonts\\segoeuib.ttf",  # Segoe UI Bold
            "C:\\Windows\\Fonts\\seguisb.ttf"     # Segoe UI Semibold
        ]

        for path in segoe_paths:
            if os.path.exists(path):
                return ("Segoe UI Semibold", path)

        # Fallback auf Arial Bold (immer verfügbar)
        return ("Arial Bold", None)  # None = FFmpeg nutzt Systemfont

    def _calculate_scaled_content_area(self, video_width, video_height):
        """
        Berechnet die skalierten Content-Area-Koordinaten basierend auf der Video-Auflösung.
        Berücksichtigt das Aspect-Ratio des Hintergrunds und schwarze Balken (padding).

        Args:
            video_width: Ziel-Video-Breite in Pixeln
            video_height: Ziel-Video-Höhe in Pixeln

        Returns:
            dict mit 'x_start', 'y_start', 'usable_width', 'usable_height' in Pixeln
        """
        # Berechne Aspect-Ratios
        bg_aspect = HINTERGRUND_ORIGINAL_WIDTH / HINTERGRUND_ORIGINAL_HEIGHT
        video_aspect = video_width / video_height

        # Berechne tatsächliche Dimensionen des skalierten Hintergrunds
        # force_original_aspect_ratio=decrease bedeutet: Hintergrund passt INNERHALB des Videos
        if bg_aspect > video_aspect:
            # Hintergrund ist breiter -> wird an Breite angepasst
            scaled_bg_width = video_width
            scaled_bg_height = int(video_width / bg_aspect)
            offset_x = 0
            offset_y = (video_height - scaled_bg_height) / 2
        else:
            # Hintergrund ist höher -> wird an Höhe angepasst
            scaled_bg_height = video_height
            scaled_bg_width = int(video_height * bg_aspect)
            offset_x = (video_width - scaled_bg_width) / 2
            offset_y = 0

        # Skalierungsfaktor vom Original zum skalierten Hintergrund
        scale_x = scaled_bg_width / HINTERGRUND_ORIGINAL_WIDTH
        scale_y = scaled_bg_height / HINTERGRUND_ORIGINAL_HEIGHT

        # Skaliere Content-Area-Koordinaten
        content_x1_scaled = CONTENT_AREA_X1 * scale_x + offset_x
        content_y1_scaled = CONTENT_AREA_Y1 * scale_y + offset_y
        content_x2_scaled = CONTENT_AREA_X2 * scale_x + offset_x
        content_y2_scaled = CONTENT_AREA_Y2 * scale_y + offset_y

        # Berechne Breite und Höhe des Content-Bereichs
        content_width = content_x2_scaled - content_x1_scaled
        content_height = content_y2_scaled - content_y1_scaled

        # Wende separate Padding-Werte für jede Seite an
        padding_left = content_width * (CONTENT_AREA_PADDING_LEFT / 100)
        padding_right = content_width * (CONTENT_AREA_PADDING_RIGHT / 100)
        padding_top = content_height * (CONTENT_AREA_PADDING_TOP / 100)
        padding_bottom = content_height * (CONTENT_AREA_PADDING_BOTTOM / 100)

        return {
            'x_start': int(content_x1_scaled + padding_left),
            'y_start': int(content_y1_scaled + padding_top),
            'usable_width': int(content_width - padding_left - padding_right),
            'usable_height': int(content_height - padding_top - padding_bottom)
        }

    def _prepare_text_overlay(self, gast, tandemmaster, videospringer, datum, ort, video_width, video_height, outside_video):
        """
        Bereitet die Text-Overlays für das Video vor.
        Positioniert Labels linksbündig innerhalb des Content-Bereichs mit automatischem Text-Wrapping.

        Args:
            gast, tandemmaster, videospringer, datum, ort: Text-Inhalte
            video_width: Video-Breite in Pixeln
            video_height: Video-Höhe in Pixeln
            outside_video: Boolean, ob Videospringer angezeigt werden soll
        """

        def ffmpeg_escape(text: str) -> str:
            return text.replace(":", r"\:").replace("'", r"\''").replace(",", r"\,")

        def estimate_text_width(text: str, font_size: int) -> int:
            """
            Schätzt die Textbreite in Pixeln (grobe Näherung).
            Arial hat ca. 0.6 * font_size als durchschnittliche Zeichenbreite.
            """
            return int(len(text) * font_size * 0.6)

        def wrap_text(text: str, max_width: int, font_size: int) -> list:
            """
            Bricht Text manuell um, wenn er zu breit ist.
            Gibt eine Liste von Zeilen zurück.
            """
            words = text.split(' ')
            lines = []
            current_line = []

            for word in words:
                test_line = ' '.join(current_line + [word])
                if estimate_text_width(test_line, font_size) <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                    else:
                        # Wort ist zu lang für eine Zeile - nimm es trotzdem
                        lines.append(word)

            if current_line:
                lines.append(' '.join(current_line))

            return lines if lines else [text]

        # Berechne Content-Area basierend auf Video-Dimensionen
        content_area = self._calculate_scaled_content_area(video_width, video_height)

        x_start = content_area['x_start']
        y_start = content_area['y_start']
        usable_width = content_area['usable_width']
        usable_height = content_area['usable_height']

        # Ermittle verwendeten Font
        # HINWEIS: Font-Dateien mit Pfaden verursachen Probleme in FFmpeg-Filtern (Sonderzeichen-Escaping)
        # Daher nutzen wir immer Systemfonts, die FFmpeg über fontconfig findet
        font_name, font_file = self._get_best_available_font()

        if font_file:
            # Auch wenn Font-Datei vorhanden ist, nutzen wir den Font-Namen
            # FFmpeg findet Fonts über fontconfig (funktioniert mit installierten Fonts)
            print(f"Font-Datei gefunden: {font_file}")
            print(f"Nutze Systemfont-Fallback: Segoe UI Semibold (robuster für FFmpeg)")
            font_name = "Segoe UI Semibold"
        else:
            print(f"Verwende Font: {font_name} (Systemfont)")

        # Bereite Text-Inhalte vor - als Tupel (Label, Wert)
        text_data = [
            ("Gast:", gast),
            ("Tandemmaster:", tandemmaster)
        ]
        if outside_video:
            text_data.append(("Videospringer:", videospringer))
        text_data.extend([
            ("Datum:", datum),
            ("Ort:", ort)
        ])

        # Berechne Schriftgröße basierend auf Content-Area-Höhe
        # Mindestgröße von 28px für bessere Lesbarkeit, sonst basierend auf Höhe
        font_size = max(28, int(usable_height / 18))

        # Noch größerer Zeilenabstand für bessere Lesbarkeit (180%)
        line_height = int(font_size * 2.5)

        # Oben beginnen mit etwas Top-Padding (15% der Content-Höhe)
        top_padding = int(usable_height * 0.10)
        current_y = y_start + top_padding

        drawtext_cmds = []

        # Position für Werte: Rechte Hälfte der Content-Box
        # Werte beginnen bei 50% der Content-Breite (linksbündig in der rechten Hälfte)
        value_x_start = x_start + int(usable_width * 0.5)

        # Maximale Breite für Werte (rechte Hälfte der Content-Box)
        max_value_width = int(usable_width * 0.5)

        for label, value in text_data:
            # Prüfe ob Wert zu lang ist und umbrechen muss
            estimated_value_width = estimate_text_width(value, font_size)

            if estimated_value_width > max_value_width:
                # Wert ist zu lang - umbrechen in der rechten Hälfte
                wrapped_values = wrap_text(value, max_value_width, font_size)
            else:
                # Wert passt in eine Zeile
                wrapped_values = [value]

            # Escape für FFmpeg
            label_escaped = ffmpeg_escape(label)

            # Label linksbündig am linken Rand
            label_params = [
                f"text='{label_escaped}'",
                f"x={x_start}",
                f"y={int(current_y)}",
                f"fontsize={font_size}",
                f"fontcolor=white",
                f"borderw=3",
                f"bordercolor=black",
                f"font='{font_name}'"
            ]
            drawtext_cmds.append(f"drawtext={':'.join(label_params)}")

            # Werte linksbündig in der rechten Hälfte (kann mehrere Zeilen sein)
            value_y = current_y
            for wrapped_value in wrapped_values:
                value_escaped = ffmpeg_escape(wrapped_value)

                # Wert linksbündig in rechter Hälfte
                value_params = [
                    f"text='{value_escaped}'",
                    f"x={value_x_start}",  # Linksbündig in rechter Hälfte
                    f"y={int(value_y)}",
                    f"fontsize={font_size}",
                    f"fontcolor=white",
                    f"borderw=3",
                    f"bordercolor=black",
                    f"font='{font_name}'"
                ]
                drawtext_cmds.append(f"drawtext={':'.join(value_params)}")

                # Nächste Zeile des gewrappten Werts
                value_y += line_height

            # Position für nächsten Eintrag
            # Nutze die größere Höhe (entweder 1 Zeile oder mehrere Wert-Zeilen)
            lines_used = max(1, len(wrapped_values))
            current_y += line_height * lines_used

        return ",".join(drawtext_cmds)

    def _generate_base_output_dir(self, gast, tandemmaster, videospringer, datum, speicherort, outside_video):
        """Generiert den Basis-Output-Pfad (nur das Verzeichnis)"""
        try:
            datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
            datum_formatiert = datum_obj.strftime("%Y%m%d")
        except:
            from datetime import datetime
            datum_formatiert = datetime.now().strftime("%Y%m%d")

        base_filename = f"{datum_formatiert}_{gast}_TA_{tandemmaster}"
        if outside_video:
            base_filename += f"_V_{videospringer}"

        base_filename_sanitized = sanitize_filename(base_filename)
        output_dir = os.path.join(speicherort, base_filename_sanitized)

        # Versuche Verzeichnis zu erstellen mit verbesserter Fehlerbehandlung
        try:
            os.makedirs(output_dir, exist_ok=True)
        except PermissionError as e:
            # Detaillierte Fehlerdiagnose
            error_msg = f"Zugriff verweigert beim Erstellen von '{base_filename_sanitized}'\n\n"
            error_msg += f"Mögliche Ursachen:\n"
            error_msg += f"1. Verzeichnis wird von einem anderen Prozess verwendet\n"
            error_msg += f"2. Keine Schreibrechte für: {speicherort}\n"
            error_msg += f"3. Antivirus blockiert den Zugriff\n\n"
            error_msg += f"Bitte prüfen Sie:\n"
            error_msg += f"• Haben Sie Schreibrechte für den Speicherort?\n"
            error_msg += f"• Ist das Verzeichnis in einem anderen Programm geöffnet?\n"
            error_msg += f"• Blockiert Ihr Antivirus den Zugriff?\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise PermissionError(error_msg)
        except OSError as e:
            # Andere OS-Fehler (z.B. ungültiger Pfad, Festplatte voll)
            error_msg = f"Fehler beim Erstellen des Verzeichnisses '{base_filename_sanitized}'\n\n"
            error_msg += f"Speicherort: {speicherort}\n"
            error_msg += f"Voller Pfad: {output_dir}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise OSError(error_msg)

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

        # Versuche Unterverzeichnis zu erstellen mit Fehlerbehandlung
        try:
            os.makedirs(video_dir, exist_ok=True)
        except PermissionError as e:
            error_msg = f"Zugriff verweigert beim Erstellen des Unterordners '{video_subdir_name}'\n\n"
            error_msg += f"Basis-Verzeichnis: {base_output_dir}\n"
            error_msg += f"Unterordner: {video_subdir_name}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise PermissionError(error_msg)
        except OSError as e:
            error_msg = f"Fehler beim Erstellen des Unterordners '{video_subdir_name}'\n\n"
            error_msg += f"Voller Pfad: {video_dir}\n\n"
            error_msg += f"Technische Details: {str(e)}"
            raise OSError(error_msg)

        output_filename = f"{base_filename}.mp4"
        full_output_path = os.path.join(video_dir, output_filename)  # Name bleibt gleich, nur Pfad ändert sich

        return full_output_path

    def _upload_to_server(self, local_directory_path):
        """Lädt das erstellte Verzeichnis auf den Server hoch"""
        try:
            from ..utils.file_utils import upload_to_server_simple
            # Hinzufügen einer Prüfung vor dem langen Upload-Prozess
            self._check_for_cancellation()

            # Übergebe das Verzeichnis und config_manager an die Upload-Funktion
            success, message, server_path = upload_to_server_simple(
                local_directory_path,
                self.config_manager
            )

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

    def _show_success_message(self, created_items):
        """Zeigt die kombinierte Erfolgsmeldung an"""
        if self.status_callback:
            self.status_callback("success", created_items)

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

    def _estimate_stream_copy_mux_duration_sec(self, intro_dauer_str, combined_body_path, mux_segments=None):
        """
        Geschätzte Dauer für Stream-Copy-Remux beim Final-Schnitt (Fortschrittsbalken).
        Berücksichtigt Body-Länge und ob Normalisierung/TS-Konvertierung ansteht.
        """
        try:
            intro_sec = float(intro_dauer_str)
        except (TypeError, ValueError, AttributeError):
            intro_sec = 8.0
        body_sec = 0.0
        if combined_body_path and os.path.exists(combined_body_path):
            try:
                body_sec = float(self._get_video_duration(combined_body_path))
            except Exception:
                body_sec = 0.0

        if body_sec <= 0:
            return max(5.0, intro_sec + 2.0)

        # Grobe I/O-Schätzung: ~0,35× Videodauer pro Voll-Durchlauf (Lesen+Schreiben)
        passes = 1.0
        if mux_segments:
            if mux_segments.get('method') == 'ts':
                passes = 2.0 if mux_segments.get('used_fast_path') else 3.0
            elif not mux_segments.get('used_fast_path'):
                passes = 2.0

        estimate = (intro_sec + body_sec) * 0.35 * passes
        return max(5.0, min(estimate, body_sec * 3.0 + 30.0))

    def _estimate_final_output_duration_sec(self, intro_dauer_str, combined_video_path):
        """Schätzt Intro + Hauptvideo für Validierung und Re-Encode-Fortschritt."""
        try:
            intro_sec = float(intro_dauer_str)
        except (TypeError, ValueError, AttributeError):
            intro_sec = 8.0
        body_sec = 0.0
        if combined_video_path and os.path.exists(combined_video_path):
            try:
                body_sec = float(self._get_video_duration(combined_video_path))
            except Exception:
                body_sec = 0.0
        total = intro_sec + body_sec
        return total if total > 0.1 else None

    def _estimate_final_mux_duration_sec(self, intro_dauer_str, combined_video_path):
        """Alias für Re-Encode-Fortschritt (Abwärtskompatibilität)."""
        return self._estimate_final_output_duration_sec(intro_dauer_str, combined_video_path)

    def _cleanup_temp_files(self, temp_files):
        work_dirs = set()
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except Exception:
                pass
            abs_path = os.path.abspath(temp_file)
            parent = os.path.dirname(abs_path)
            while parent and parent != os.path.dirname(parent):
                if os.path.basename(parent) == ".aerotandem_work":
                    work_dirs.add(parent)
                    break
                parent = os.path.dirname(parent)
        for work_dir in work_dirs:
            try:
                if os.path.isdir(work_dir) and not os.listdir(work_dir):
                    shutil.rmtree(work_dir, ignore_errors=True)
            except Exception:
                pass

    def _cleanup(self):
        self.reset_cancel_event()

    def cancel_process(self):
        print("Cancel event set!")
        self.cancel_event.set()

    def _find_longest_clip(self, video_clip_paths):
        """
        Findet den längsten Clip aus einer Liste von Video-Pfaden.
        Gibt den Pfad des längsten Clips zurück, oder None wenn die Liste leer ist.
        """
        if not video_clip_paths:
            return None

        longest_path = None
        longest_duration = 0.0

        for video_path in video_clip_paths:
            if not video_path or not os.path.exists(video_path):
                continue

            try:
                duration = self._get_video_duration(video_path)
                if duration > longest_duration:
                    longest_duration = duration
                    longest_path = video_path
                    print(f"Neuer längster Clip gefunden: {video_path} ({duration}s)")
            except Exception as e:
                print(f"Fehler beim Ermitteln der Dauer von {video_path}: {e}")
                continue

        print(f"Längster Clip: {longest_path} (Dauer: {longest_duration}s)")
        return longest_path

    def _get_video_duration(self, video_path):
        """
        Ermittelt die Dauer eines Videos in Sekunden mit ffprobe.

        Args:
            video_path: Pfad zur Videodatei

        Returns:
            Dauer in Sekunden als float
        """
        command = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            video_path
        ]
        result = subprocess.run(command, capture_output=True, text=True,
                              timeout=10, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        if result.returncode == 0:
            return float(result.stdout.strip())
        else:
            raise ValueError(f"Konnte Videodauer nicht ermitteln: {video_path}")

    def reset_cancel_event(self):
        self.cancel_event.clear()

    def _run_ffmpeg_with_progress(self, command, total_duration=None, task_name="Encoding", task_id=None,
                                  encoding_lane=0):
        """
        Führt FFmpeg-Befehl aus und liest den Fortschritt live aus.

        Args:
            command: FFmpeg-Befehl als Liste
            total_duration: Gesamtdauer des Videos in Sekunden (für Fortschrittsberechnung)
            task_name: Name der Aufgabe für Status-Updates
            task_id: Optional ID für parallele Tasks (z. B. Drag-Drop-Zeilen)
            encoding_lane: 0/1 zweite Fortschrittszeile in der Haupt-UI (paralleler Final-Job)

        Returns:
            True bei Erfolg, wirft Exception bei Fehler
        """
        # Füge Progress-Ausgabe zu FFmpeg-Befehl hinzu
        progress_command = command.copy()
        # Füge -progress pipe:1 vor dem Output-File ein (letztes Element)
        output_file = progress_command[-1]
        progress_command = progress_command[:-1] + ['-progress', 'pipe:1'] + [output_file]

        # Starte FFmpeg-Prozess
        process = subprocess.Popen(
            progress_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,  # Line buffered
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        start_time = time.time()
        last_update_time = start_time

        # Lese Fortschritt aus stdout
        current_time_sec = 0.0
        fps = 0.0

        # Sammle stderr in separatem Thread um Deadlock zu vermeiden
        stderr_lines = []
        def read_stderr():
            try:
                for line in process.stderr:
                    stderr_lines.append(line)
            except Exception:
                # Ignore exceptions (e.g., when process terminates and closes the pipe)
                pass

        stderr_thread = threading.Thread(target=read_stderr, daemon=True)
        stderr_thread.start()

        try:
            while True:
                self._check_for_cancellation()

                # Non-blocking read mit Timeout
                line = process.stdout.readline()
                if not line:
                    # Prüfe ob Prozess beendet ist
                    if process.poll() is not None:
                        break
                    # Kurze Pause um CPU nicht zu belasten
                    time.sleep(0.01)
                    continue

                line = line.strip()

                # Parse FFmpeg Progress-Ausgabe
                if line.startswith('out_time_ms='):
                    try:
                        time_ms_str = line.split('=')[1].strip()
                        time_ms = int(time_ms_str)
                        current_time_sec = time_ms / 1000000.0
                    except (ValueError, IndexError):
                        pass

                elif line.startswith('fps='):
                    fps_str = line.split('=')[1].strip()
                    try:
                        fps = float(fps_str)
                    except ValueError:
                        # Ignore malformed fps values; continue processing.
                        pass

                # Update nur alle 0.5 Sekunden um UI nicht zu überlasten
                current_update_time = time.time()
                if current_update_time - last_update_time >= 0.5:
                    last_update_time = current_update_time

                    if total_duration and total_duration > 0:
                        progress_percent = min((current_time_sec / total_duration) * 100, 100)

                        # Berechne ETA
                        elapsed_time = current_update_time - start_time
                        if current_time_sec > 0 and elapsed_time > 0:
                            encoding_speed = current_time_sec / elapsed_time
                            remaining_time = (total_duration - current_time_sec) / encoding_speed if encoding_speed > 0 else 0

                            # Formatiere ETA
                            eta_minutes = int(remaining_time // 60)
                            eta_seconds = int(remaining_time % 60)
                            eta_str = f"{eta_minutes}:{eta_seconds:02d}"

                            # Sende Update
                            if self.encoding_progress_callback:
                                self.encoding_progress_callback(
                                    task_name=task_name,
                                    progress=progress_percent,
                                    fps=fps,
                                    eta=eta_str,
                                    current_time=current_time_sec,
                                    total_time=total_duration,
                                    task_id=task_id,
                                    encoding_lane=encoding_lane,
                                )
                    else:
                        # Kein total_duration - zeige nur Zeit und FPS
                        if self.encoding_progress_callback:
                            self.encoding_progress_callback(
                                task_name=task_name,
                                progress=None,
                                fps=fps,
                                eta=None,
                                current_time=current_time_sec,
                                total_time=None,
                                task_id=task_id,
                                encoding_lane=encoding_lane,
                            )

            # Warte auf Prozessende mit Timeout
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("⚠️ FFmpeg antwortet nicht - beende Prozess...")
                process.kill()
                process.wait()

            # Warte auf stderr-Thread
            stderr_thread.join(timeout=2)

            # Prüfe Return Code
            if process.returncode != 0:
                stderr_output = ''.join(stderr_lines)
                if self.cancel_event.is_set():
                    raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")

                # Zeige nur relevante stderr-Zeilen (letzte 20)
                stderr_relevant = '\n'.join(stderr_lines[-20:]) if stderr_lines else "Kein stderr verfügbar"
                print(f"FFmpeg Fehler (Code {process.returncode}):")
                print(stderr_relevant)
                raise subprocess.CalledProcessError(process.returncode, command, stderr=stderr_output)

            # Finale 100% Update
            if self.encoding_progress_callback and total_duration:
                self.encoding_progress_callback(
                    task_name=task_name,
                    progress=100,
                    fps=fps,
                    eta="0:00",
                    current_time=total_duration,
                    total_time=total_duration,
                    task_id=task_id,
                    encoding_lane=encoding_lane,
                )

            return True

        except CancellationError:
            # Beende FFmpeg-Prozess bei Abbruch
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise
        except Exception as e:
            # Beende FFmpeg-Prozess bei Fehler
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            raise

