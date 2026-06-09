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


def is_hevc_codec(codec: str) -> bool:
    return normalize_codec_name(codec) == "hevc"


def normalize_codec_name(codec: str) -> str:
    name = (codec or "h264").lower()
    if name in ("hevc", "h265"):
        return "hevc"
    return name


def append_hevc_splice_encode_params(params: list[str], encoder: str, fps: int = 30) -> list[str]:
    """HEVC-Parameter für splice-taugliche Clips (wie Intro-Encoding)."""
    encoder = (encoder or "").lower()
    fps = max(1, int(fps))
    params.extend(["-bf", "0", "-fps_mode", "cfr", "-tag:v", "hvc1"])
    if encoder == "libx265":
        params.extend([
            "-x265-params",
            f"keyint={fps}:min-keyint={fps}:scenecut=0:open-gop=0:"
            f"repeat-headers=1:aud=1:bframes=0",
        ])
    elif encoder.endswith("_nvenc"):
        params.extend(["-no-scenecut", "1"])
    elif encoder.endswith("_qsv"):
        params.extend(["-look_ahead", "0", "-forced_idr", "1"])
    return params


def build_software_quality_params(encoder: str, crf: int, codec: str = "h264") -> list[str]:
    crf = clamp_crf(crf)
    encoder = (encoder or "libx264").lower()
    hevc = is_hevc_codec(codec)
    params = ["-g", "30", "-keyint_min", "30", "-sc_threshold", "0"]
    if encoder == "libx264":
        params.extend(["-preset", "medium", "-crf", str(crf)])
        if not hevc:
            params.extend(["-x264-params", "repeat-headers=1:nal-hrd=none:open-gop=0"])
    elif encoder == "libx265":
        hevc_crf = min(51, crf + 2)
        params.extend(["-preset", "medium", "-crf", str(hevc_crf)])
        append_hevc_splice_encode_params(params, encoder, fps=30)
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
        params = ["-preset", "p4", "-tune", "hq", "-rc", "vbr", "-cq", str(cq), "-b:v", "0"] + gop
        if hevc:
            append_hevc_splice_encode_params(params, enc, fps=30)
        return params

    if hw == "amd" or "amf" in enc:
        qp = min(51, crf + 2) if hevc else crf
        params = [
            "-usage", "transcoding",
            "-quality", "quality",
            "-rc", "cqp",
            "-qp_i", str(qp),
            "-qp_p", str(qp),
            "-qp_b", str(qp),
        ] + gop
        if hevc:
            append_hevc_splice_encode_params(params, enc, fps=30)
        return params

    if hw == "intel" or "qsv" in enc:
        q = min(51, crf + 2) if hevc else crf
        params = ["-global_quality", str(q), "-preset", "medium", "-look_ahead", "0", "-bf", "0"] + gop
        if hevc:
            append_hevc_splice_encode_params(params, enc, fps=30)
        return params

    if hw == "videotoolbox" or "videotoolbox" in enc:
        q = max(40, min(90, 100 - crf))
        return ["-profile:v", "high", "-q:v", str(q), "-b:v", "0"] + gop

    if hw == "vaapi" or "vaapi" in enc:
        qp = min(51, crf + 2) if hevc else crf
        return ["-qp", str(qp)] + gop

    return build_software_quality_params("libx264", crf, codec)


def strip_hwaccel_input_params(input_params: list) -> list:
    """Entfernt -hwaccel/-hwaccel_device — nötig wenn CPU-Filter (scale/pad) verwendet werden."""
    stripped = []
    i = 0
    while i < len(input_params):
        if input_params[i] in ("-hwaccel", "-hwaccel_device"):
            i += 2
            continue
        stripped.append(input_params[i])
        i += 1
    return stripped


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
    codec = VideoProcessor._normalize_vcodec_name(codec_name)
    if codec == "hevc":
        if pix_fmt and str(pix_fmt) not in ("yuv420p", "yuv420p10le"):
            return True
        return False
    if pix_fmt and str(pix_fmt) not in ("yuv420p", "yuvj420p"):
        return True
    return False
