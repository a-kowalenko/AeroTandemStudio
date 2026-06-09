"""Erkennung ob Video-Clips bereits dem Preview-Zielformat entsprechen."""
from src.video.processor import VideoProcessor


def normalize_target_codec(codec_name) -> str:
    if not codec_name:
        return "h264"
    name = str(codec_name).lower()
    if name in ("hevc", "h265"):
        return "h265"
    return name


def fps_matches_preview_target(r_frame_rate) -> bool:
    if not r_frame_rate or r_frame_rate == "0/0":
        return False
    try:
        rate = str(r_frame_rate)
        if "/" in rate:
            num_s, den_s = rate.split("/", 1)
            num, den = int(num_s), int(den_s)
            fps = num / den if den else 0.0
        else:
            fps = float(rate)
        return abs(fps - 30.0) < 0.05 or abs(fps - 29.97) < 0.05
    except (ValueError, ZeroDivisionError):
        return False


def _clip_matches_resolution_and_fps(fmt: dict) -> bool:
    if not fmt or "error" in fmt:
        return False
    if fmt.get("width") != 1920 or fmt.get("height") != 1080:
        return False
    return fps_matches_preview_target(fmt.get("r_frame_rate"))


def clip_matches_preview_target(fmt: dict) -> bool:
    """True wenn Clip bereits 1080p@30 im Ziel-Codec (H.264 oder HEVC) ist."""
    if not _clip_matches_resolution_and_fps(fmt):
        return False
    codec_name = normalize_target_codec(fmt.get("codec_name"))
    if codec_name not in ("h264", "h265"):
        return False
    vcodec = "hevc" if codec_name == "h265" else "h264"
    pix_fmt = fmt.get("pix_fmt")
    return not VideoProcessor.pix_fmt_needs_reencode_for_browser(pix_fmt, vcodec)


def all_clips_match_preview_target(format_info: dict) -> bool:
    formats = format_info.get("formats") or []
    valid = [f for f in formats if "error" not in f]
    if not valid:
        return False
    return all(clip_matches_preview_target(f) for f in valid)


def resolve_auto_target_codec(format_info: dict, default: str = "h264") -> str:
    """
    Ermittelt den Ziel-Codec für AUTO aus den Quellclips.
    Alle gleich → dieser Codec; gemischt → Codec des ersten gültigen Clips.
    """
    formats = format_info.get("formats") or []
    valid = [f for f in formats if "error" not in f]
    if not valid:
        return default
    codecs = [normalize_target_codec(f.get("codec_name")) for f in valid]
    if len(set(codecs)) == 1:
        return codecs[0]
    return codecs[0]
