"""Encoding-Qualität und gelockerte Format-Vergleiche für Preview-Re-Encode."""
from __future__ import annotations

from src.utils.preview_encode_target import fps_matches_preview_target
from src.video.processor import VideoProcessor


def clamp_crf(crf, default: int = 18) -> int:
    try:
        value = int(crf)
    except (TypeError, ValueError):
        value = default
    return max(0, min(51, value))


def parse_fps(r_frame_rate) -> float | None:
    if not r_frame_rate or r_frame_rate == "0/0":
        return None
    try:
        rate = str(r_frame_rate).strip()
        if "/" in rate:
            num_s, den_s = rate.split("/", 1)
            num, den = int(num_s), int(den_s)
            return num / den if den else None
        return float(rate)
    except (ValueError, ZeroDivisionError):
        return None


def fps_values_equivalent(rate_a, rate_b) -> bool:
    if rate_a == rate_b:
        return True
    fps_a = parse_fps(rate_a)
    fps_b = parse_fps(rate_b)
    if fps_a is not None and fps_b is not None and abs(fps_a - fps_b) < 0.05:
        return True
    return fps_matches_preview_target(rate_a) and fps_matches_preview_target(rate_b)


def stream_format_values_equivalent(key: str, val_a, val_b, vcodec: str) -> bool:
    if val_a == val_b:
        return True
    if key == "r_frame_rate":
        return fps_values_equivalent(val_a, val_b)
    if key == "pix_fmt":
        return VideoProcessor._pix_fmts_compatible_for_mux(val_a, val_b, vcodec)
    if key == "profile":
        return VideoProcessor._normalize_profile_name(val_a) == VideoProcessor._normalize_profile_name(val_b)
    return False


def build_software_quality_params(encoder: str, crf: int, codec: str = "h264") -> list[str]:
    crf = clamp_crf(crf)
    encoder = (encoder or "libx264").lower()
    params = ["-g", "30", "-keyint_min", "30"]
    if encoder == "libx264":
        params.extend(["-preset", "medium", "-crf", str(crf)])
    elif encoder == "libx265":
        hevc_crf = min(51, crf + 2)
        params.extend(["-preset", "medium", "-crf", str(hevc_crf)])
    elif encoder == "libvpx-vp9":
        params.extend(["-deadline", "good", "-cpu-used", "2", "-b:v", "0", "-crf", "31"])
    elif encoder in ("libaom-av1", "libsvtav1"):
        params.extend(["-cpu-used", "6", "-crf", str(min(51, crf + 6)), "-b:v", "0"])
    else:
        params.extend(["-preset", "medium", "-crf", str(crf)])
    return params


def build_hw_quality_params(hw_type: str | None, encoder: str | None, crf: int, codec: str = "h264") -> list[str]:
    """FFmpeg-Qualitätsparameter für Hardware-Encoder (CRF-ähnlich)."""
    crf = clamp_crf(crf)
    hevc = codec in ("hevc", "h265")
    gop = ["-g", "30", "-keyint_min", "30"]
    enc = (encoder or "").lower()
    hw = (hw_type or "").lower()

    if hw == "nvidia" or "nvenc" in enc:
        cq = min(51, crf + 2) if hevc else crf
        return ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"] + gop

    if hw == "amd" or "amf" in enc:
        qp = min(51, crf + 2) if hevc else crf
        return [
            "-usage", "transcoding",
            "-quality", "quality",
            "-rc", "cqp",
            "-qp_i", str(qp),
            "-qp_p", str(qp),
            "-qp_b", str(qp),
        ] + gop

    if hw == "intel" or "qsv" in enc:
        q = min(51, crf + 2) if hevc else crf
        return ["-global_quality", str(q), "-preset", "medium", "-look_ahead", "0", "-bf", "0"] + gop

    if hw == "videotoolbox" or "videotoolbox" in enc:
        q = max(40, min(90, 100 - crf))
        return ["-profile:v", "high", "-q:v", str(q), "-b:v", "0"] + gop

    if hw == "vaapi" or "vaapi" in enc:
        qp = min(51, crf + 2) if hevc else crf
        return ["-qp", str(qp)] + gop

    return build_software_quality_params("libx264", crf, codec)


def clip_needs_video_filter(fmt: dict | None, target_width=1920, target_height=1080, target_fps=30) -> bool:
    """True wenn Scale/Pad/FPS-Filter vor dem Encode nötig sind."""
    if not fmt or "error" in fmt:
        return True
    if fmt.get("width") != target_width or fmt.get("height") != target_height:
        return True
    if not fps_matches_preview_target(fmt.get("r_frame_rate")):
        return True
    pix_fmt = fmt.get("pix_fmt")
    codec_name = fmt.get("codec_name", "h264")
    if VideoProcessor.pix_fmt_needs_reencode_for_browser(pix_fmt, codec_name):
        return True
    if pix_fmt and str(pix_fmt) not in ("yuv420p", "yuvj420p"):
        return True
    return False
