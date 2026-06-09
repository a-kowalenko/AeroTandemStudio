"""Gemeinsame HEVC/H.264 Stream-Copy-Concat-Helfer (Avidemux-ähnlicher Remux)."""
from __future__ import annotations

import os
import subprocess

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


def normalize_vcodec_name(codec_name) -> str:
    if not codec_name:
        return "h264"
    name = str(codec_name).lower()
    if name in ("hevc", "h265"):
        return "hevc"
    return name


def hevc_stream_copy_video_tag(video_params: dict | None = None) -> str:
    """
    hev1 = Parameter Sets im Bitstream (in-band) — robuster für Concat als hvc1.
    Avidemux-ähnliche Splice-Kompatibilität zwischen Intro und Kamera-Body.
    """
    if not video_params:
        return "hev1"
    tag = (video_params.get("vtag") or "").lower()
    if tag in ("hev1", "hvc1"):
        return "hev1"
    return "hev1"


def _run_ffmpeg(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        creationflags=SUBPROCESS_CREATE_NO_WINDOW,
    )


def body_starts_with_keyframe(video_path: str) -> bool:
    """True wenn der erste Video-Frame ein Keyframe (I/IDR) ist."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=pict_type",
        "-of", "csv=p=0",
        "-read_intervals", "%+1",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False
        first = (result.stdout or "").strip().splitlines()
        if not first:
            return False
        pict = first[0].strip().upper()
        return pict in ("I", "IDR")
    except (subprocess.TimeoutExpired, OSError):
        return False


def get_first_keyframe_time(video_path: str, max_scan_sec: float = 10.0) -> float | None:
    """Liefert den Zeitstempel des ersten Keyframes oder None."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_frames",
        "-show_entries", "frame=pict_type,best_effort_timestamp_time",
        "-of", "csv=p=0",
        "-read_intervals", f"%+{int(max_scan_sec)}",
        video_path,
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return None
        for line in (result.stdout or "").splitlines():
            parts = line.strip().split(",")
            if len(parts) < 2:
                continue
            pict = parts[0].strip().upper()
            if pict not in ("I", "IDR"):
                continue
            try:
                return float(parts[1])
            except ValueError:
                continue
        return None
    except (subprocess.TimeoutExpired, OSError):
        return None


def normalize_mp4_for_concat(input_path: str, output_path: str, has_audio: bool = True) -> None:
    """Remux mit sauberen Timestamps (Stream-Copy)."""
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", input_path, "-map", "0:v:0"]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ])
    _run_ffmpeg(cmd)


def prep_hevc_mp4_for_splice(
    input_path: str,
    output_path: str,
    has_audio: bool = True,
    video_tag: str = "hev1",
) -> None:
    """HEVC-MP4 für Splice vorbereiten: AUD einfügen, hev1 (in-band Parameter Sets)."""
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", input_path, "-map", "0:v:0"]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-c", "copy",
        "-bsf:v", "hevc_metadata=aud=insert",
        "-tag:v", video_tag,
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ])
    _run_ffmpeg(cmd)


def trim_body_start_to_keyframe(
    input_path: str,
    output_path: str,
    has_audio: bool = True,
) -> str:
    """
    Stellt sicher, dass der Body mit einem Keyframe beginnt (Stream-Copy).
    Returns: Pfad zur (ggf. getrimmten) Ausgabedatei.
    """
    if body_starts_with_keyframe(input_path):
        if os.path.normpath(input_path) == os.path.normpath(output_path):
            return input_path
        normalize_mp4_for_concat(input_path, output_path, has_audio=has_audio)
        return output_path

    kf_time = get_first_keyframe_time(input_path)
    if kf_time is None or kf_time <= 0:
        normalize_mp4_for_concat(input_path, output_path, has_audio=has_audio)
        return output_path

    cmd = ["ffmpeg", "-y", "-ss", str(kf_time), "-i", input_path, "-map", "0:v:0"]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-c", "copy",
        "-copyinkf",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        output_path,
    ])
    _run_ffmpeg(cmd)
    return output_path


def write_concat_file_list(segment_paths: list[str], list_path: str) -> None:
    with open(list_path, "w", encoding="utf-8") as handle:
        for segment_path in segment_paths:
            escaped = os.path.abspath(segment_path).replace("\\", "/")
            handle.write(f"file '{escaped}'\n")


def concat_mp4_segments_to_mkv(concat_list_path: str, output_mkv: str) -> None:
    """Avidemux-ähnlich: segmentweise demuxen und in MKV remuxen (Stream-Copy)."""
    cmd = [
        "ffmpeg", "-y", "-fflags", "+genpts",
        "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        output_mkv,
    ]
    _run_ffmpeg(cmd)


def remux_mkv_to_mp4(
    input_mkv: str,
    output_mp4: str,
    vcodec: str = "hevc",
    has_audio: bool = True,
    video_tag: str = "hev1",
) -> None:
    """MKV → MP4 Stream-Copy mit frischem Container-Index (kein reset_timestamps)."""
    vcodec = normalize_vcodec_name(vcodec)
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", input_mkv, "-map", "0:v:0"]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-movflags", "+faststart",
        "-max_interleave_delta", "0",
    ])
    if vcodec == "hevc":
        cmd.extend(["-bsf:v", "hevc_metadata=aud=insert", "-tag:v", video_tag])
    elif vcodec == "h264":
        cmd.extend(["-bsf:v", "h264_metadata=aud=insert", "-tag:v", "avc1"])
    if has_audio:
        cmd.extend(["-bsf:a", "aac_adtstoasc"])
    cmd.append(output_mp4)
    _run_ffmpeg(cmd)


def mp4_to_mpegts_stream_copy(
    input_path: str,
    output_ts: str,
    vcodec: str,
    has_audio: bool = True,
) -> None:
    """MP4 → MPEG-TS per Stream-Copy (Annex-B) für robustes Concat."""
    vcodec = normalize_vcodec_name(vcodec)
    bsf_map = {"h264": "h264_mp4toannexb", "hevc": "hevc_mp4toannexb"}
    bsf = bsf_map.get(vcodec)

    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", input_path, "-map", "0:v:0"]
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend(["-c", "copy", "-avoid_negative_ts", "make_zero"])
    if bsf:
        cmd.extend(["-bsf:v", bsf])
    cmd.extend(["-f", "mpegts", output_ts])
    _run_ffmpeg(cmd)


def build_mpegts_concat_to_mp4_command(
    output_mp4: str,
    ts_paths: list[str],
    vcodec: str,
    has_audio: bool = True,
    video_tag: str = "hev1",
) -> list[str]:
    """MPEG-TS-Streams zu einer MP4 zusammenfügen (Stream-Copy, ohne reset_timestamps)."""
    vcodec = normalize_vcodec_name(vcodec)
    concat_input = "concat:" + "|".join(ts_paths)
    cmd = ["ffmpeg", "-y", "-fflags", "+genpts", "-i", concat_input]
    cmd.extend(["-map", "0:v:0"])
    if has_audio:
        cmd.extend(["-map", "0:a:0"])
    cmd.extend([
        "-c", "copy",
        "-avoid_negative_ts", "make_zero",
        "-max_interleave_delta", "0",
    ])
    if has_audio:
        cmd.extend(["-bsf:a", "aac_adtstoasc"])
    cmd.extend(["-movflags", "+faststart"])
    if vcodec == "hevc":
        cmd.extend(["-bsf:v", "hevc_metadata=aud=insert", f"-tag:v", video_tag])
    elif vcodec == "h264":
        cmd.extend(["-bsf:v", "h264_metadata=aud=insert", "-tag:v", "avc1"])
    cmd.append(output_mp4)
    return cmd


def validate_splice_decode(output_path: str, intro_duration_sec, scan_sec: float = 2.0) -> tuple[bool, str]:
    """Dekodiert kurz ab der Intro-Nahtstelle; erkennt kaputte Stream-Copy-Splices."""
    try:
        intro_sec = float(intro_duration_sec)
    except (TypeError, ValueError):
        intro_sec = 0.0
    seek = max(0.0, intro_sec - 0.25)
    cmd = [
        "ffmpeg", "-v", "error", "-nostats",
        "-ss", str(seek),
        "-i", output_path,
        "-t", str(scan_sec),
        "-map", "0:v:0",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            return False, err or "Decode an Nahtstelle fehlgeschlagen"
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Decode-Validierung an Nahtstelle timeout"
    except OSError as exc:
        return False, str(exc)
