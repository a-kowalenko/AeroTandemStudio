"""FFmpeg-Export: getrimmte Clips zusammenfügen (Stream-Copy oder Re-Encode)."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable, List, Optional

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW

TRIM_TOLERANCE_SEC = 0.15


@dataclass
class ExportClipSegment:
    """Ein aktiver Clip in der vom Nutzer festgelegten Reihenfolge."""

    path: str
    start_sec: float
    end_sec: float
    duration_sec: Optional[float] = None

    def needs_reencode(self) -> bool:
        """True wenn der Clip über die Schieberegler beschnitten wurde."""
        duration = self.duration_sec
        if duration is None:
            duration = _probe_duration_sec(self.path)
            self.duration_sec = duration

        start = max(0.0, float(self.start_sec))
        end = float(self.end_sec)
        if end <= 0 or end > duration + TRIM_TOLERANCE_SEC:
            end = duration

        full_length = end >= duration - TRIM_TOLERANCE_SEC and start <= TRIM_TOLERANCE_SEC
        return not full_length


def _probe_duration_sec(video_path: str) -> float:
    from src.video.cutter_service import VideoCutterService

    info = VideoCutterService().get_video_info(video_path)
    return max(0.001, info.duration_ms / 1000.0)


def _run_ffmpeg(cmd: List[str]) -> None:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        creationflags=SUBPROCESS_CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr[:2000] or "FFmpeg fehlgeschlagen")


class VideoCutExporter:
    """Exportiert die vom Review-Dialog bestätigte Clip-Liste zu einem Kunden-Video."""

    def __init__(
        self,
        *,
        video_codec: str = "libx264",
        crf: int = 23,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
    ) -> None:
        self.video_codec = video_codec
        self.crf = crf
        self.audio_codec = audio_codec
        self.audio_bitrate = audio_bitrate

    def export_combined(
        self,
        segments: List[ExportClipSegment],
        output_path: str,
        *,
        progress_callback: Optional[Callable[[float, str], None]] = None,
    ) -> str:
        """
        Schneidet alle Segmente und fügt sie zu ``output_path`` zusammen.

        Returns:
            Pfad zur fertigen Datei.
        """
        if not segments:
            raise ValueError("Keine Clips zum Exportieren.")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        temp_dir = tempfile.mkdtemp(prefix="aero_video_cut_")
        prepared: List[str] = []
        total = len(segments)

        try:
            for idx, segment in enumerate(segments):
                if progress_callback:
                    progress_callback((idx / max(total, 1)) * 85.0, f"Clip {idx + 1}/{total}")

                part_path = os.path.join(temp_dir, f"part_{idx:04d}.mp4")
                self._export_segment(segment, part_path)
                prepared.append(part_path)

            if progress_callback:
                progress_callback(90.0, "Füge Clips zusammen...")

            if len(prepared) == 1:
                os.replace(prepared[0], output_path)
            else:
                self._concat_parts(prepared, output_path)

            if progress_callback:
                progress_callback(100.0, "Fertig")

            return output_path
        finally:
            for path in prepared:
                if os.path.isfile(path):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass

    def _export_segment(self, segment: ExportClipSegment, output_path: str) -> None:
        duration = segment.duration_sec or _probe_duration_sec(segment.path)
        start = max(0.0, float(segment.start_sec))
        end = float(segment.end_sec)
        if end <= 0 or end > duration:
            end = duration
        clip_duration = max(0.05, end - start)

        if segment.needs_reencode():
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                segment.path,
                "-t",
                f"{clip_duration:.3f}",
                "-c:v",
                self.video_codec,
                "-crf",
                str(self.crf),
                "-preset",
                "veryfast",
                "-c:a",
                self.audio_codec,
                "-b:a",
                self.audio_bitrate,
                "-movflags",
                "+faststart",
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                output_path,
            ]
        else:
            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-i",
                segment.path,
                "-t",
                f"{clip_duration:.3f}",
                "-c:v",
                "copy",
                "-c:a",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                "-map",
                "0:v:0?",
                "-map",
                "0:a:0?",
                output_path,
            ]

        _run_ffmpeg(cmd)

    def _concat_parts(self, part_paths: List[str], output_path: str) -> None:
        list_file = output_path + ".concat.txt"
        try:
            with open(list_file, "w", encoding="utf-8") as handle:
                for path in part_paths:
                    safe = path.replace("\\", "/").replace("'", "'\\''")
                    handle.write(f"file '{safe}'\n")

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_file,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                output_path,
            ]
            _run_ffmpeg(cmd)
        finally:
            if os.path.isfile(list_file):
                try:
                    os.remove(list_file)
                except OSError:
                    pass


def segments_from_project_clips(active_clips: List[dict]) -> List[ExportClipSegment]:
    """Baut Export-Segmente aus aktiven Projekt-Clips (Review-Dialog)."""
    from src.media_ai.phase_segments import expand_clips_to_export_segments

    rows = expand_clips_to_export_segments(active_clips)
    segments: List[ExportClipSegment] = []
    for row in rows:
        path = str(row.get("path") or "").strip()
        if not path:
            continue
        start = row.get("trim_start")
        end = row.get("trim_end")
        if start is None or end is None:
            continue
        duration_raw = row.get("duration_sec")
        duration = None
        if duration_raw is not None:
            try:
                duration = float(duration_raw)
            except (TypeError, ValueError):
                duration = None
        segments.append(
            ExportClipSegment(
                path=path,
                start_sec=float(start),
                end_sec=float(end),
                duration_sec=duration,
            )
        )
    if not segments:
        raise ValueError("Keine gültigen Schnittsegmente (fehlende Zeiten oder Pfade).")
    return segments


def export_clips_for_reimport(
    active_clips: List[dict],
    output_dir: str,
    *,
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> List[str]:
    """
    Exportiert jeden aktiven Quell-Clip als eigene getrimmte Datei (aktive Phasen).

    Returns:
        Pfade der erzeugten MP4-Dateien in ``output_dir``.
    """
    from src.media_ai.phase_segments import expand_clips_to_export_segments

    if not active_clips:
        raise ValueError("Keine Clips zum Schneiden.")

    os.makedirs(output_dir, exist_ok=True)
    exporter = VideoCutExporter()
    exported: List[str] = []
    total = len(active_clips)

    for idx, clip in enumerate(active_clips):
        source_path = str(clip.get("path") or "").strip()
        if not source_path:
            continue

        if progress_callback:
            progress_callback(
                (idx / max(total, 1)) * 100.0,
                f"Clip {idx + 1}/{total}: {os.path.basename(source_path)}",
            )

        rows = expand_clips_to_export_segments([clip])
        if not rows:
            continue

        segments: List[ExportClipSegment] = []
        for row in rows:
            path = str(row.get("path") or source_path).strip()
            start = row.get("trim_start")
            end = row.get("trim_end")
            if start is None or end is None:
                continue
            duration_raw = row.get("duration_sec")
            duration = None
            if duration_raw is not None:
                try:
                    duration = float(duration_raw)
                except (TypeError, ValueError):
                    duration = None
            segments.append(
                ExportClipSegment(
                    path=path,
                    start_sec=float(start),
                    end_sec=float(end),
                    duration_sec=duration,
                )
            )
        if not segments:
            continue

        stem = os.path.splitext(os.path.basename(source_path))[0]
        safe_stem = re.sub(r'[<>:"/\\|?*]', "_", stem)[:96] or "clip"
        out_path = os.path.join(output_dir, f"{safe_stem}_ki_schnitt.mp4")
        if os.path.isfile(out_path):
            out_path = os.path.join(output_dir, f"{safe_stem}_ki_schnitt_{idx + 1}.mp4")

        exporter.export_combined(segments, out_path)
        exported.append(out_path)

    if not exported:
        raise ValueError(
            "Keine Schnitt-Clips erzeugt – mindestens eine Phase pro Video muss aktiv sein."
        )
    return exported
