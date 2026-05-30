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


def clip_matches_preview_target(fmt: dict) -> bool:
    if not fmt or "error" in fmt:
        return False
    if normalize_target_codec(fmt.get("codec_name")) != "h264":
        return False
    if fmt.get("width") != 1920 or fmt.get("height") != 1080:
        return False
    if not fps_matches_preview_target(fmt.get("r_frame_rate")):
        return False
    codec_name = fmt.get("codec_name", "h264")
    pix_fmt = fmt.get("pix_fmt")
    return not VideoProcessor.pix_fmt_needs_reencode_for_browser(pix_fmt, codec_name)


def all_clips_match_preview_target(format_info: dict) -> bool:
    formats = format_info.get("formats") or []
    valid = [f for f in formats if "error" not in f]
    if not valid:
        return False
    return all(clip_matches_preview_target(f) for f in valid)
