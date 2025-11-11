"""
Video Cutter Service - Kapselung der ffmpeg/ffprobe-Logik

Trennt die Video-Verarbeitung von der UI für bessere Testbarkeit und Wartbarkeit.
Implementiert Smart-Trim/Cut mit minimalem Re-Encoding.
"""
import os
import json
import subprocess
import threading
import time
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass
from bisect import bisect_left, bisect_right

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.hardware_acceleration import HardwareAccelerationDetector
from src.utils.config import ConfigManager


@dataclass
class VideoInfo:
    """Video-Metadaten"""
    duration_ms: int
    fps: float
    width: int
    height: int
    vcodec: str
    pix_fmt: str
    video_bitrate: Optional[int]
    acodec: Optional[str]
    audio_bitrate: Optional[int]
    sample_rate: Optional[str]
    channels: Optional[int]


@dataclass
class CutPlan:
    """Plan für Smart-Cut-Verarbeitung"""
    strategy: str  # 'stream_copy', 'smart_cut_3seg', 're_encode'
    segments: List[Dict]  # Liste von Segment-Specs


class VideoCutterService:
    """Service für Video-Schnitt-Operationen"""

    def __init__(self):
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_settings()
        self.hw_detector = HardwareAccelerationDetector()
        self.hw_info = self.hw_detector.detect_hardware() if self.config.get('hardware_acceleration_enabled', True) else None

        self._keyframe_cache: Dict[str, List[float]] = {}
        self._cancel_flag = False
        self._current_process: Optional[subprocess.Popen] = None

    def get_video_info(self, video_path: str) -> VideoInfo:
        """
        Liest Video-Metadaten mit ffprobe.

        Args:
            video_path: Pfad zur Videodatei

        Returns:
            VideoInfo-Objekt mit allen Metadaten
        """
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", "-show_format", video_path
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        format_info = data.get("format", {})

        video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in streams if s['codec_type'] == 'audio'), None)

        if not video_stream:
            raise ValueError("Kein Video-Stream gefunden.")

        # Dauer
        duration_s_str = video_stream.get('duration') or format_info.get('duration', '0')
        duration_ms = int(float(duration_s_str) * 1000)

        # FPS
        r_frame_rate = video_stream.get('r_frame_rate', '30/1')
        try:
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den if den != 0 else 30.0
        except:
            fps = 30.0

        # Video-Parameter
        video_info = VideoInfo(
            duration_ms=duration_ms,
            fps=fps,
            width=video_stream.get('width', 1920),
            height=video_stream.get('height', 1080),
            vcodec=video_stream.get('codec_name', 'h264'),
            pix_fmt=video_stream.get('pix_fmt', 'yuv420p'),
            video_bitrate=int(video_stream.get('bit_rate', 0)) if video_stream.get('bit_rate') else None,
            acodec=audio_stream.get('codec_name') if audio_stream else None,
            audio_bitrate=int(audio_stream.get('bit_rate', 0)) if audio_stream and audio_stream.get('bit_rate') else None,
            sample_rate=audio_stream.get('sample_rate') if audio_stream else None,
            channels=audio_stream.get('channels') if audio_stream else None,
        )

        return video_info

    def get_keyframes(self, video_path: str, force_refresh: bool = False) -> List[float]:
        """
        Holt alle Keyframe-Zeitstempel des Videos (gecacht).
        Verwendet ffprobe mit -skip_frame nokey für maximale Effizienz.

        Args:
            video_path: Pfad zur Videodatei
            force_refresh: Cache ignorieren und neu laden

        Returns:
            Liste von Keyframe-Zeitstempeln in Sekunden (sortiert)
        """
        if not force_refresh and video_path in self._keyframe_cache:
            return self._keyframe_cache[video_path]

        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-skip_frame", "nokey",
            "-select_streams", "v:0",
            "-show_frames",
            "-show_entries", "frame=pkt_pts_time",
            "-of", "json",
            video_path
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, check=True,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )
            data = json.loads(result.stdout)
            frames = data.get("frames", [])

            keyframes = []
            for frame in frames:
                pts_time = frame.get("pkt_pts_time")
                if pts_time is not None:
                    try:
                        keyframes.append(float(pts_time))
                    except (ValueError, TypeError):
                        continue

            keyframes.sort()
            self._keyframe_cache[video_path] = keyframes
            print(f"✓ {len(keyframes)} Keyframes gecacht für {os.path.basename(video_path)}")
            return keyframes

        except Exception as e:
            print(f"Fehler beim Laden der Keyframes: {e}")
            return []

    def get_keyframe_before(self, video_path: str, target_sec: float) -> float:
        """
        Findet den Keyframe VOR der angegebenen Zeit.

        Args:
            video_path: Pfad zur Videodatei
            target_sec: Zielzeit in Sekunden

        Returns:
            Zeit des Keyframes in Sekunden
        """
        keyframes = self.get_keyframes(video_path)
        if not keyframes:
            return 0.0

        idx = bisect_right(keyframes, target_sec) - 1
        return keyframes[max(0, idx)]

    def get_keyframe_after(self, video_path: str, target_sec: float) -> float:
        """
        Findet den Keyframe NACH der angegebenen Zeit.

        Args:
            video_path: Pfad zur Videodatei
            target_sec: Zielzeit in Sekunden

        Returns:
            Zeit des Keyframes in Sekunden
        """
        keyframes = self.get_keyframes(video_path)
        if not keyframes:
            return target_sec

        idx = bisect_left(keyframes, target_sec)
        if idx < len(keyframes) and keyframes[idx] >= target_sec:
            return keyframes[idx]
        return target_sec

    def is_on_keyframe(self, video_path: str, target_sec: float, fps: float) -> bool:
        """
        Prüft, ob die gegebene Zeit auf einem Keyframe liegt.

        Args:
            video_path: Pfad zur Videodatei
            target_sec: Zielzeit in Sekunden
            fps: Framerate für Toleranzberechnung

        Returns:
            True wenn auf Keyframe, sonst False
        """
        tolerance = 1.0 / fps  # 1 Frame Toleranz
        keyframes = self.get_keyframes(video_path)

        for kf in keyframes:
            if abs(kf - target_sec) <= tolerance:
                return True
            if kf > target_sec + tolerance:
                break
        return False

    def plan_trim(self, video_path: str, start_sec: float, end_sec: float,
                  video_info: VideoInfo) -> CutPlan:
        """
        Erstellt einen optimalen Plan für Trim-Operation.

        IMMER Stream-Copy - niemals re-encoden!
        Bei DJI-Videos sind Keyframes alle 1-2s, eventuelle Artefakte minimal.

        Args:
            video_path: Pfad zur Videodatei
            start_sec: Startzeit in Sekunden
            end_sec: Endzeit in Sekunden
            video_info: Video-Metadaten

        Returns:
            CutPlan mit Strategie und Segmenten
        """
        duration_sec = end_sec - start_sec

        print(f"\n=== TRIM PLAN ===")
        print(f"Bereich: {start_sec:.3f}s - {end_sec:.3f}s (Dauer: {duration_sec:.3f}s)")
        print("Strategie: STREAM_COPY (100% Original, lossless)")

        # IMMER Stream-Copy - behält Original-Encoding 1:1
        return CutPlan(
            strategy='stream_copy',
            segments=[{
                'type': 'copy',
                'start': start_sec,
                'duration': duration_sec
            }]
        )

    def build_ffmpeg_cmd(self, input_path: str, output_path: str, segment: Dict,
                        video_info: VideoInfo, use_sw_fallback: bool = False) -> List[str]:
        """
        Baut einen ffmpeg-Befehl für ein Segment.

        Args:
            input_path: Eingabedatei
            output_path: Ausgabedatei
            segment: Segment-Spec aus CutPlan
            video_info: Video-Metadaten
            use_sw_fallback: Software-Encoding erzwingen

        Returns:
            ffmpeg-Kommando als Liste
        """
        cmd = ["ffmpeg", "-y"]

        # Hardware-Beschleunigung für Decoding
        use_hw = (not use_sw_fallback and
                 self.config.get('hardware_acceleration_enabled', True) and
                 self.hw_info and self.hw_info.get('available', False))

        # WICHTIG: Bei QSV kein hwaccel für Decoding verwenden, wenn wir auch QSV für Encoding nutzen
        # Dies verhindert Ressourcen-Konflikte und "Cannot load" Fehler
        hw_type = self.hw_info.get('type') if use_hw else None
        use_hw_decode = use_hw and hw_type != 'intel' and segment['type'] == 'encode'

        if use_hw_decode and self.hw_info.get('hwaccel'):
            cmd.extend(['-hwaccel', self.hw_info['hwaccel']])
            if self.hw_info.get('device'):
                cmd.extend(['-hwaccel_device', self.hw_info['device']])

        # Input mit Seek
        cmd.extend([
            "-ss", str(segment['start']),
            "-i", input_path,
            "-t", str(segment['duration'])
        ])

        # Encoding-Parameter je nach Segment-Typ
        if segment['type'] == 'copy':
            cmd.extend(["-c", "copy"])
        else:  # encode
            # Video-Codec
            if use_hw and self.hw_info.get('encoder'):
                encoder = self.hw_info['encoder']
                cmd.extend(["-c:v", encoder])

                if hw_type == 'nvidia':
                    cmd.extend([
                        "-preset", "p6",  # Gute Balance (p6 statt p7)
                        "-tune", "hq",
                        "-rc", "vbr",
                        "-cq", "19",
                        "-b:v", "0",
                        "-g", "30",
                        "-keyint_min", "30",
                        "-pix_fmt", "yuv420p"
                    ])
                elif hw_type == 'intel':
                    # QSV: Verwende nv12 (natives Format für QSV)
                    cmd.extend([
                        "-global_quality", "19",
                        "-preset", "medium",
                        "-look_ahead", "0",  # Deaktiviert für Stabilität
                        "-g", "30",  # GOP-Size fest auf 30 (bei 30fps = 1 Keyframe/Sekunde)
                        "-keyint_min", "30",
                        "-bf", "0",  # Keine B-Frames für bessere Schneidbarkeit
                        "-pix_fmt", "nv12"
                    ])
                elif hw_type == 'amd':
                    cmd.extend([
                        "-quality", "quality",
                        "-rc", "cqp",
                        "-qp_i", "19",
                        "-qp_p", "19",
                        "-g", "30",
                        "-keyint_min", "30",
                        "-pix_fmt", "nv12"
                    ])
                elif hw_type == 'videotoolbox':
                    cmd.extend([
                        "-b:v", "0",
                        "-q:v", "65",
                        "-g", "30",
                        "-keyint_min", "30",
                        "-pix_fmt", "nv12"
                    ])
            else:
                # Software-Encoding
                if video_info.vcodec == 'hevc':
                    cmd.extend(["-c:v", "libx265"])
                else:
                    cmd.extend(["-c:v", "libx264"])

                cmd.extend([
                    "-crf", "18",
                    "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                    "-g", "30",  # GOP-Size fest auf 30
                    "-keyint_min", "30",
                    "-bf", "0"  # Keine B-Frames
                ])

            # Keyframe am Anfang erzwingen wenn gefordert
            if segment.get('force_keyframe'):
                cmd.extend(["-force_key_frames", "0"])

            # Audio-Codec
            if video_info.acodec:
                acodec_map = {
                    'aac': 'aac',
                    'mp3': 'libmp3lame',
                    'opus': 'libopus',
                    'vorbis': 'libvorbis'
                }
                cmd.extend(["-c:a", acodec_map.get(video_info.acodec, 'aac')])

                if video_info.audio_bitrate:
                    bitrate = min(video_info.audio_bitrate // 1000, 320)
                    cmd.extend(["-b:a", f"{bitrate}k"])
                else:
                    cmd.extend(["-b:a", "192k"])

                if video_info.sample_rate:
                    cmd.extend(["-ar", str(video_info.sample_rate)])
                if video_info.channels:
                    cmd.extend(["-ac", str(min(int(video_info.channels), 2))])
            else:
                cmd.extend(["-an"])

        # Allgemeine Parameter
        cmd.extend([
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",
            "-movflags", "+faststart",
            "-map", "0:v:0?", "-map", "0:a:0?",
            output_path
        ])

        return cmd

    def execute_trim(self, video_path: str, start_sec: float, end_sec: float,
                    output_path: str, progress_callback: Optional[Callable] = None) -> bool:
        """
        Führt SMART-CUT Trim aus (minimales Re-encode an Übergängen).

        Strategien:
        - Auf Keyframes: Stream-Copy (instant, lossless)
        - Zwischen Keyframes: Smart-Cut (minimal re-encode)
        - Keine Keyframes: Stream-Copy mit Warnung

        Args:
            video_path: Eingabedatei
            start_sec: Startzeit in Sekunden
            end_sec: Endzeit in Sekunden
            output_path: Ausgabedatei
            progress_callback: Callback(percent, status_text)

        Returns:
            True bei Erfolg, False bei Fehler
        """
        self._cancel_flag = False

        try:
            # Video-Info laden
            if progress_callback:
                progress_callback(5, "Lade Video-Info...")
            video_info = self.get_video_info(video_path)

            # Keyframes laden
            if progress_callback:
                progress_callback(10, "Analysiere Keyframes...")
            keyframes = self.get_keyframes(video_path)

            duration_sec = end_sec - start_sec

            print(f"\n=== SMART-CUT TRIM START ===")
            print(f"Bereich: {start_sec:.3f}s - {end_sec:.3f}s (Dauer: {duration_sec:.3f}s)")
            print(f"Keyframes: {len(keyframes)}")

            # Prüfe ob Start/Ende auf Keyframes
            start_on_kf = self.is_on_keyframe(video_path, start_sec, video_info.fps)
            end_on_kf = self.is_on_keyframe(video_path, end_sec, video_info.fps)

            if start_on_kf and end_on_kf:
                # Fall A: Beide auf Keyframes → Stream-Copy
                print("✅ Beide auf Keyframes → Stream-Copy (perfekt)")
                return self._trim_stream_copy(
                    video_path, start_sec, duration_sec, output_path, progress_callback
                )

            elif not keyframes or len(keyframes) == 0:
                # Fall B: Keine Keyframes → Re-Encoding (Stream-Copy würde zu Problemen führen)
                print("⚠️ Keine Keyframes → Re-Encoding für sauberen Schnitt")
                return self._trim_reencode(
                    video_path, start_sec, end_sec, output_path, video_info, progress_callback
                )

            else:
                # Fall C: Smart-Cut
                kf_before_start = self.get_keyframe_before(video_path, start_sec)
                kf_after_start = self.get_keyframe_after(video_path, start_sec)
                kf_before_end = self.get_keyframe_before(video_path, end_sec)

                print(f"⚡ Smart-Cut → Minimal re-encode")
                print(f"   Start: {start_sec:.3f}s (KF vor: {kf_before_start:.3f}s, nach: {kf_after_start:.3f}s)")
                print(f"   Ende: {end_sec:.3f}s (KF vor: {kf_before_end:.3f}s)")

                # Prüfe ob genug Platz für Smart-Cut (Mittelteil >= 1s)
                if not start_on_kf and not end_on_kf and (kf_after_start < kf_before_end - 1.0):
                    return self._trim_smart_cut(
                        video_path, start_sec, end_sec,
                        kf_after_start, kf_before_end,
                        output_path, video_info, progress_callback
                    )
                else:
                    # Zu kurz oder auf Rand → Stream-Copy
                    print("⚠️ Segment zu kurz für Smart-Cut → Stream-Copy")
                    return self._trim_stream_copy(
                        video_path, start_sec, duration_sec, output_path, progress_callback
                    )

        except Exception as e:
            print(f"Fehler beim Trim: {e}")
            if progress_callback:
                progress_callback(0, f"Fehler: {str(e)}")
            return False

    def _trim_stream_copy(self, video_path: str, start_sec: float, duration_sec: float,
                         output_path: str, progress_callback: Optional[Callable]) -> bool:
        """Stream-Copy Trim (schnell, lossless)"""
        if progress_callback:
            progress_callback(20, "Schneide (Stream-Copy)...")

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_sec),
            "-i", video_path,
            "-t", str(duration_sec),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            "-map", "0:v:0?", "-map", "0:a:0?",
            output_path
        ]

        result = subprocess.run(cmd, capture_output=True, text=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        if result.returncode != 0:
            print(f"Fehler: {result.stderr[:500]}")
            return False

        if progress_callback:
            progress_callback(100, "Fertig!")

        print("✅ Stream-Copy Trim erfolgreich")
        return True

    def _trim_reencode(self, video_path: str, start_sec: float, end_sec: float,
                      output_path: str, video_info: VideoInfo,
                      progress_callback: Optional[Callable]) -> bool:
        """
        Re-Encoding Trim (präzise, langsamer als Stream-Copy).
        Wird verwendet, wenn keine Keyframes verfügbar sind.
        """
        if progress_callback:
            progress_callback(20, "Schneide (Re-Encoding)...")

        duration_sec = end_sec - start_sec

        # Baue Encoding-Parameter basierend auf Video-Info und Hardware
        segment = {
            'type': 'encode',
            'start': start_sec,
            'duration': duration_sec,
            'force_keyframe': True
        }

        cmd = self.build_ffmpeg_cmd(video_path, output_path, segment, video_info)

        try:
            # Führe mit Progress-Tracking aus
            self._run_ffmpeg(
                cmd, duration_sec,
                start_percent=20, end_percent=100,
                progress_callback=progress_callback,
                video_info=video_info,
                segment=segment,
                input_path=video_path,
                output_path=output_path
            )

            if progress_callback:
                progress_callback(100, "Fertig!")

            print("✅ Re-Encoding Trim erfolgreich")

            # Keyframe-Cache für Output erneuern, da wir gerade neu enkodiert haben
            if os.path.exists(output_path):
                self.get_keyframes(output_path, force_refresh=True)

            return True

        except Exception as e:
            print(f"Fehler beim Re-Encoding Trim: {e}")
            if progress_callback:
                progress_callback(0, f"Fehler: {str(e)}")
            return False

    def _trim_smart_cut(self, video_path: str, start_sec: float, end_sec: float,
                       kf_after_start: float, kf_before_end: float,
                       output_path: str, video_info: VideoInfo,
                       progress_callback: Optional[Callable]) -> bool:
        """Smart-Cut Trim (minimal re-encode)"""
        base, ext = os.path.splitext(output_path)

        seg1_path = f"{base}.__seg1__{ext}"
        seg2_path = f"{base}.__seg2__{ext}"
        seg3_path = f"{base}.__seg3__{ext}"
        concat_list = f"{base}.__concat__.txt"

        try:
            # Segment 1: Re-encode von Start bis nächstem Keyframe
            if progress_callback:
                progress_callback(20, "Seg1: Re-encode...")

            seg = {'type': 'encode', 'start': start_sec,
                  'duration': kf_after_start - start_sec, 'force_keyframe': True}
            cmd = self.build_ffmpeg_cmd(video_path, seg1_path, seg, video_info)
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Segment 2: Stream-Copy Mittelteil
            if progress_callback:
                progress_callback(50, "Seg2: Copy...")

            cmd = ["ffmpeg", "-y",
                  "-ss", str(kf_after_start), "-i", video_path,
                  "-t", str(kf_before_end - kf_after_start),
                  "-c", "copy",
                  "-avoid_negative_ts", "make_zero",
                  "-map", "0:v:0?", "-map", "0:a:0?",
                  seg2_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Segment 3: Re-encode von letztem Keyframe bis Ende
            if progress_callback:
                progress_callback(70, "Seg3: Re-encode...")

            seg = {'type': 'encode', 'start': kf_before_end,
                  'duration': end_sec - kf_before_end, 'force_keyframe': False}
            cmd = self.build_ffmpeg_cmd(video_path, seg3_path, seg, video_info)
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # Concat
            if progress_callback:
                progress_callback(90, "Füge Segmente zusammen...")

            with open(concat_list, 'w', encoding='utf-8') as f:
                f.write(f"file '{seg1_path.replace(chr(92), '/')}'\n")
                f.write(f"file '{seg2_path.replace(chr(92), '/')}'\n")
                f.write(f"file '{seg3_path.replace(chr(92), '/')}'\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                  "-i", concat_list, "-c", "copy", output_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(100, "Fertig!")

            print("✅ Smart-Cut Trim erfolgreich")

            # Keyframe-Cache für Output erneuern
            if os.path.exists(output_path):
                self.get_keyframes(output_path, force_refresh=True)

            return True

        finally:
            for path in [seg1_path, seg2_path, seg3_path, concat_list]:
                if os.path.exists(path):
                    try: os.remove(path)
                    except: pass

    def _run_ffmpeg(self, cmd: List[str], duration_sec: float,
                   start_percent: int, end_percent: int,
                   progress_callback: Optional[Callable],
                   video_info: VideoInfo = None,
                   segment: dict = None,
                   input_path: str = None,
                   output_path: str = None) -> bool:
        """
        Führt ffmpeg-Befehl aus mit automatischem Software-Fallback.

        Args:
            cmd: ffmpeg-Kommando
            duration_sec: Erwartete Dauer für Progress-Berechnung
            start_percent: Start-Prozent für Progress
            end_percent: End-Prozent für Progress
            progress_callback: Callback(percent, status)
            video_info: Video-Metadaten für Fallback
            segment: Segment-Spec für Fallback
            input_path: Input-Pfad für Fallback
            output_path: Output-Pfad für Fallback

        Returns:
            True bei Erfolg, False bei Fehler
        """
        print(f"FFmpeg: {' '.join(cmd[:15])}...")

        result = subprocess.run(
            cmd, capture_output=True, text=True,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW
        )

        if result.returncode == 0:
            if progress_callback:
                progress_callback(end_percent, "Segment fertig")
            return True

        # Fehler - prüfe ob Hardware-Problem
        stderr_lower = result.stderr.lower()

        # Spezifischere Hardware-Fehler-Erkennung (nur echte Fehler, keine Warnungen)
        hw_errors = [
            'cannot load qsv',
            'cannot initialize qsv',
            'failed to create qsv',
            'qsv not available',
            'could not open encoder',
            'failed to open encoder',
            'encoder not found',
            'no device available',
            'cannot initialize hardware',
            'unsupported pixel format',
            'incompatible pixel format',
        ]

        # Nur als HW-Fehler werten, wenn es wirklich ein kritischer Fehler ist
        is_hw_error = any(err in stderr_lower for err in hw_errors)

        # Zusätzlich: Prüfe ob "error" oder "failed" im Zusammenhang mit HW vorkommt
        if not is_hw_error and ('qsv' in stderr_lower or 'nvenc' in stderr_lower or 'amf' in stderr_lower):
            # Nur als HW-Fehler werten wenn auch "error", "failed", "cannot" etc. dabei ist
            if any(word in stderr_lower for word in ['error', 'failed', 'cannot', 'unable to']):
                is_hw_error = True

        if is_hw_error and video_info and segment and input_path and output_path:
            print(f"⚠️ Hardware-Fehler erkannt, versuche Software-Fallback...")
            print(f"   Fehler: {result.stderr[:300]}")

            # Cleanup fehlgeschlagener Output
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass

            # Baue Software-Command
            cmd_sw = self.build_ffmpeg_cmd(input_path, output_path, segment,
                                          video_info, use_sw_fallback=True)

            print(f"Software-Fallback: {' '.join(cmd_sw[:15])}...")

            if progress_callback:
                progress_callback(start_percent, "Hardware-Fehler, nutze Software...")

            result_sw = subprocess.run(
                cmd_sw, capture_output=True, text=True,
                creationflags=SUBPROCESS_CREATE_NO_WINDOW
            )

            if result_sw.returncode == 0:
                print("✅ Software-Fallback erfolgreich")
                if progress_callback:
                    progress_callback(end_percent, "Segment fertig (Software)")
                return True
            else:
                print(f"❌ Software-Fallback fehlgeschlagen: {result_sw.stderr[:500]}")
                return False
        else:
            print(f"FFmpeg Fehler: {result.stderr[:500]}")
            return False

    def execute_split(self, video_path: str, split_sec: float,
                     part1_path: str, part2_path: str,
                     progress_callback: Optional[Callable] = None) -> bool:
        """
        Führt SMART-CUT Split aus (minimales Re-encode an Übergängen).

        Strategien:
        - Auf Keyframe: Stream-Copy (instant, lossless)
        - Zwischen Keyframes: Smart-Cut (minimal re-encode)
        - Keine Keyframes: Stream-Copy mit Warnung

        Args:
            video_path: Eingabedatei
            split_sec: Split-Zeit in Sekunden
            part1_path: Ausgabepfad Teil 1
            part2_path: Ausgabepfad Teil 2
            progress_callback: Callback(percent, status_text)

        Returns:
            True bei Erfolg, False bei Fehler
        """
        self._cancel_flag = False

        try:
            # Video-Info laden
            if progress_callback:
                progress_callback(5, "Lade Video-Info...")
            video_info = self.get_video_info(video_path)

            # Keyframes laden
            if progress_callback:
                progress_callback(10, "Analysiere Keyframes...")
            keyframes = self.get_keyframes(video_path)

            print(f"\n=== SMART-CUT SPLIT START ===")
            print(f"Split-Position: {split_sec:.3f}s")
            print(f"Keyframes: {len(keyframes)}")

            # Prüfe ob Split auf Keyframe
            split_on_kf = self.is_on_keyframe(video_path, split_sec, video_info.fps)

            if split_on_kf:
                # Fall A: Auf Keyframe → Stream-Copy
                print("✅ Auf Keyframe → Stream-Copy (perfekt)")
                return self._split_stream_copy(
                    video_path, split_sec, part1_path, part2_path, progress_callback
                )

            elif not keyframes or len(keyframes) == 0:
                # Fall B: Keine Keyframes → Stream-Copy
                print("⚠️ Keine Keyframes → Stream-Copy")
                return self._split_stream_copy(
                    video_path, split_sec, part1_path, part2_path, progress_callback
                )

            else:
                # Fall C: Smart-Cut
                kf_before = self.get_keyframe_before(video_path, split_sec)
                kf_after = self.get_keyframe_after(video_path, split_sec)

                print(f"⚡ Smart-Cut → Minimal re-encode")
                print(f"   Keyframe vor: {kf_before:.3f}s")
                print(f"   Keyframe nach: {kf_after:.3f}s")

                duration_sec = video_info.duration_ms / 1000.0

                # Prüfe ob genug Platz für Smart-Cut
                if kf_before > 0.5 and kf_after < duration_sec - 0.5:
                    return self._split_smart_cut(
                        video_path, split_sec, kf_before, kf_after,
                        part1_path, part2_path, video_info, progress_callback
                    )
                else:
                    print("⚠️ Zu nah am Rand → Stream-Copy")
                    return self._split_stream_copy(
                        video_path, split_sec, part1_path, part2_path, progress_callback
                    )

        except Exception as e:
            print(f"Fehler: {e}")
            if progress_callback:
                progress_callback(0, f"Fehler: {str(e)}")
            return False

    def _split_stream_copy(self, video_path: str, split_sec: float,
                          part1_path: str, part2_path: str,
                          progress_callback: Optional[Callable]) -> bool:
        """Stream-Copy Split (schnell, lossless)"""
        if progress_callback:
            progress_callback(20, "Teil 1 (Stream-Copy)...")

        cmd1 = [
            "ffmpeg", "-y", "-i", video_path, "-t", str(split_sec),
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-map", "0:v:0?", "-map", "0:a:0?", part1_path
        ]

        result1 = subprocess.run(cmd1, capture_output=True, text=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        if result1.returncode != 0:
            raise subprocess.CalledProcessError(result1.returncode, cmd1,
                                               result1.stdout, result1.stderr)

        if progress_callback:
            progress_callback(60, "Teil 2 (Stream-Copy)...")

        cmd2 = [
            "ffmpeg", "-y", "-ss", str(split_sec), "-i", video_path,
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            "-map", "0:v:0?", "-map", "0:a:0?", part2_path
        ]

        result2 = subprocess.run(cmd2, capture_output=True, text=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        if result2.returncode != 0:
            raise subprocess.CalledProcessError(result2.returncode, cmd2,
                                               result2.stdout, result2.stderr)

        if progress_callback:
            progress_callback(100, "Fertig!")

        print("✅ Stream-Copy Split erfolgreich")
        return True

    def _split_smart_cut(self, video_path: str, split_sec: float,
                        kf_before: float, kf_after: float,
                        part1_path: str, part2_path: str,
                        video_info: VideoInfo,
                        progress_callback: Optional[Callable]) -> bool:
        """Smart-Cut Split (minimal re-encode)"""
        base, ext = os.path.splitext(video_path)

        part1_seg1 = f"{base}.__p1s1__{ext}"
        part1_seg2 = f"{base}.__p1s2__{ext}"
        part1_list = f"{base}.__p1list__.txt"

        part2_seg1 = f"{base}.__p2s1__{ext}"
        part2_seg2 = f"{base}.__p2s2__{ext}"
        part2_list = f"{base}.__p2list__.txt"

        try:
            # TEIL 1: Stream-Copy + Re-encode Ende
            if progress_callback:
                progress_callback(20, "Teil 1 Seg1: Copy...")

            if kf_before > 0.1:
                cmd = ["ffmpeg", "-y", "-i", video_path, "-t", str(kf_before),
                      "-c", "copy", "-avoid_negative_ts", "make_zero",
                      "-map", "0:v:0?", "-map", "0:a:0?", part1_seg1]
                subprocess.run(cmd, check=True, capture_output=True, text=True,
                             creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(35, "Teil 1 Seg2: Re-encode...")

            seg = {'type': 'encode', 'start': kf_before,
                  'duration': split_sec - kf_before, 'force_keyframe': False}
            cmd = self.build_ffmpeg_cmd(video_path, part1_seg2, seg, video_info)
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(45, "Teil 1: Concat...")

            with open(part1_list, 'w', encoding='utf-8') as f:
                if kf_before > 0.1:
                    f.write(f"file '{part1_seg1.replace(chr(92), '/')}'\n")
                f.write(f"file '{part1_seg2.replace(chr(92), '/')}'\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                  "-i", part1_list, "-c", "copy", part1_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            # TEIL 2: Re-encode Anfang + Stream-Copy
            if progress_callback:
                progress_callback(60, "Teil 2 Seg1: Re-encode...")

            seg = {'type': 'encode', 'start': split_sec,
                  'duration': kf_after - split_sec, 'force_keyframe': True}
            cmd = self.build_ffmpeg_cmd(video_path, part2_seg1, seg, video_info)
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(75, "Teil 2 Seg2: Copy...")

            duration_sec = video_info.duration_ms / 1000.0
            if kf_after < duration_sec - 0.1:
                cmd = ["ffmpeg", "-y", "-ss", str(kf_after), "-i", video_path,
                      "-c", "copy", "-avoid_negative_ts", "make_zero",
                      "-map", "0:v:0?", "-map", "0:a:0?", part2_seg2]
                subprocess.run(cmd, check=True, capture_output=True, text=True,
                             creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(90, "Teil 2: Concat...")

            with open(part2_list, 'w', encoding='utf-8') as f:
                f.write(f"file '{part2_seg1.replace(chr(92), '/')}'\n")
                if kf_after < duration_sec - 0.1:
                    f.write(f"file '{part2_seg2.replace(chr(92), '/')}'\n")

            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                  "-i", part2_list, "-c", "copy", part2_path]
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                         creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if progress_callback:
                progress_callback(100, "Smart-Cut fertig!")

            print("✅ Smart-Cut Split erfolgreich")

            # Keyframe-Cache für beide Output-Dateien erneuern
            if os.path.exists(part1_path):
                self.get_keyframes(part1_path, force_refresh=True)
            if os.path.exists(part2_path):
                self.get_keyframes(part2_path, force_refresh=True)

            return True

        finally:
            for path in [part1_seg1, part1_seg2, part1_list,
                        part2_seg1, part2_seg2, part2_list]:
                if os.path.exists(path):
                    try: os.remove(path)
                    except: pass

    def cancel(self):
        """Bricht die laufende Operation ab."""
        self._cancel_flag = True
        if self._current_process:
            try:
                self._current_process.terminate()
            except:
                pass

