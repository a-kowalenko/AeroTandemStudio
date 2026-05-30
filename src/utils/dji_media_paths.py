"""DJI SD-Karten Pfad-Hilfen für Foto-Timelapse-Sessions."""
import os
import re
from typing import Optional

_TIMELAPSE_DIR_NAMES = frozenset({"timelapse"})
_DJI_NUMBERED_DIR_RE = re.compile(r"^dji_\d+$", re.IGNORECASE)


def _norm_parts(path: str) -> list[str]:
    return [p for p in os.path.normpath(path).split(os.sep) if p]


def _dcim_index(parts: list[str]) -> Optional[int]:
    for i, part in enumerate(parts):
        if part.upper() == "DCIM":
            return i
    return None


def dcim_has_timelapse_photo_tree(dcim_root: str) -> bool:
    """True wenn DCIM/TIMELAPSE (beliebige Schreibweise) existiert."""
    if not dcim_root or not os.path.isdir(dcim_root):
        return False
    try:
        for name in os.listdir(dcim_root):
            if name.lower() in _TIMELAPSE_DIR_NAMES:
                candidate = os.path.join(dcim_root, name)
                if os.path.isdir(candidate):
                    return True
    except OSError:
        return False
    return False


def is_under_dji_timelapse_tree(file_path: str, dcim_root: str) -> bool:
    """True wenn die Datei unter DCIM/TIMELAPSE/ liegt."""
    parts = _norm_parts(file_path)
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None or dcim_idx + 1 >= len(parts):
        return False
    return parts[dcim_idx + 1].lower() in _TIMELAPSE_DIR_NAMES


def is_under_dji_numbered_folder(file_path: str, dcim_root: str) -> bool:
    """True wenn die Datei unter DCIM/DJI_<nr>/ liegt (z. B. DJI_001)."""
    parts = _norm_parts(file_path)
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None or dcim_idx + 1 >= len(parts):
        return False
    return bool(_DJI_NUMBERED_DIR_RE.match(parts[dcim_idx + 1]))


def should_skip_file_for_timelapse_session(
    file_path: str,
    dcim_root: str,
    *,
    is_video: bool,
    timelapse_session_active: bool,
    exclude_timelapse_videos: bool = True,
) -> bool:
    """
    DJI Foto-Timelapse: Videos in DJI_* überspringen wenn TIMELAPSE-Ordner existiert.
    Fotos unter TIMELAPSE/** werden nie übersprungen.
    """
    if not exclude_timelapse_videos:
        return False
    if not is_video:
        return False
    if is_under_dji_timelapse_tree(file_path, dcim_root):
        return True
    if timelapse_session_active and is_under_dji_numbered_folder(file_path, dcim_root):
        return True
    return False


def filter_media_paths_for_backup(
    media_paths: list[str],
    dcim_root: str,
    *,
    exclude_timelapse_videos: bool = True,
) -> tuple[list[str], int]:
    """Filtert Pfade für SD-Backup; gibt (behalten, übersprungen_anzahl) zurück."""
    if not exclude_timelapse_videos:
        return media_paths, 0
    session_active = dcim_has_timelapse_photo_tree(dcim_root)
    kept = []
    skipped = 0
    video_exts = (
        ".mp4", ".mov", ".avi", ".mkv", ".m4v",
        ".mpg", ".mpeg", ".wmv", ".flv", ".webm",
    )
    for path in media_paths:
        ext = os.path.splitext(path.lower())[1]
        is_video = ext in video_exts
        if should_skip_file_for_timelapse_session(
            path,
            dcim_root,
            is_video=is_video,
            timelapse_session_active=session_active,
            exclude_timelapse_videos=True,
        ):
            skipped += 1
            continue
        kept.append(path)
    return kept, skipped
