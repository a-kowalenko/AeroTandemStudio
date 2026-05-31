"""DJI SD-Karten Pfad-Hilfen für Foto-Timelapse-Sessions."""
import json
import os
import re
from typing import Optional

_TIMELAPSE_DIR_NAMES = frozenset({"timelapse"})
_DJI_DIR_RE = re.compile(r"^dji_", re.IGNORECASE)
_BACKUP_MANIFEST_NAME = ".aerotandem_manifest.json"

_PHOTO_EXTENSIONS = frozenset({
    ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp",
    ".heic", ".raw", ".cr2", ".nef", ".arw", ".dng",
})
_VIDEO_EXTENSIONS = frozenset({
    ".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mpg", ".mpeg", ".wmv", ".flv", ".webm",
})
_MEDIA_EXTENSIONS = _PHOTO_EXTENSIONS | _VIDEO_EXTENSIONS


def _norm_parts(path: str) -> list[str]:
    return [p for p in os.path.normpath(path).split(os.sep) if p]


def _dcim_index(parts: list[str]) -> Optional[int]:
    for i, part in enumerate(parts):
        if part.upper() == "DCIM":
            return i
    return None


def resolve_dcim_root(path: str) -> Optional[str]:
    """Findet den DCIM-Ordner zu einem Pfad (SD-Karte, Unterordner oder DCIM selbst)."""
    if not path:
        return None
    norm = os.path.abspath(os.path.normpath(path))
    if not os.path.exists(norm):
        norm = os.path.dirname(norm) or norm
    current = norm
    while True:
        if os.path.basename(current).upper() == "DCIM" and os.path.isdir(current):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    child = os.path.join(norm, "DCIM")
    if os.path.isdir(child):
        return child
    return None


def _path_has_timelapse_segment(parts: list[str], dcim_idx: int) -> bool:
    return any(p.lower() in _TIMELAPSE_DIR_NAMES for p in parts[dcim_idx + 1:])


def _path_has_dji_segment(parts: list[str], dcim_idx: int) -> bool:
    return any(_DJI_DIR_RE.match(p) for p in parts[dcim_idx + 1:])


def dcim_has_timelapse_photo_tree(dcim_root: str) -> bool:
    """True wenn irgendwo unter DCIM ein TIMELAPSE-Ordner mit Fotos existiert."""
    if not dcim_root or not os.path.isdir(dcim_root):
        return False
    dcim_parts = _norm_parts(os.path.abspath(dcim_root))
    try:
        for root, _dirs, files in os.walk(dcim_root):
            root_parts = _norm_parts(root)
            if len(root_parts) <= len(dcim_parts):
                continue
            relative_parts = root_parts[len(dcim_parts):]
            if not any(p.lower() in _TIMELAPSE_DIR_NAMES for p in relative_parts):
                continue
            for name in files:
                ext = os.path.splitext(name.lower())[1]
                if ext in _PHOTO_EXTENSIONS:
                    return True
    except OSError:
        return False
    return False


def is_under_dji_timelapse_tree(file_path: str, dcim_root: str) -> bool:
    """True wenn die Datei unter DCIM/…/TIMELAPSE/… liegt."""
    parts = _norm_parts(file_path)
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None:
        return False
    return _path_has_timelapse_segment(parts, dcim_idx)


def is_under_dji_numbered_folder(file_path: str, dcim_root: str) -> bool:
    """True wenn die Datei unter DCIM/…/DJI_* /… liegt."""
    parts = _norm_parts(file_path)
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None:
        return False
    return _path_has_dji_segment(parts, dcim_idx)


def should_skip_file_for_timelapse_session(
    file_path: str,
    dcim_root: str,
    *,
    is_video: bool,
    timelapse_session_active: bool,
    exclude_timelapse_videos: bool = True,
) -> bool:
    """
    DJI Foto-Timelapse: Videos in DJI_* oder TIMELAPSE überspringen wenn Foto-Timelapse aktiv.
    Fotos unter TIMELAPSE/** werden nie übersprungen.
    """
    if not exclude_timelapse_videos:
        return False
    if not is_video:
        return False
    if not dcim_root or not resolve_dcim_root(file_path):
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
    """Filtert Pfade für SD-Backup/Import; gibt (behalten, übersprungen_anzahl) zurück."""
    if not exclude_timelapse_videos:
        return media_paths, 0
    effective_dcim = resolve_dcim_root(dcim_root) or dcim_root
    session_active = dcim_has_timelapse_photo_tree(effective_dcim)
    kept = []
    skipped = 0
    for path in media_paths:
        ext = os.path.splitext(path.lower())[1]
        is_video = ext in _VIDEO_EXTENSIONS
        if should_skip_file_for_timelapse_session(
            path,
            effective_dcim,
            is_video=is_video,
            timelapse_session_active=session_active,
            exclude_timelapse_videos=exclude_timelapse_videos,
        ):
            skipped += 1
            continue
        kept.append(path)
    return kept, skipped


def collect_media_paths_from_tree(
    scan_root: str,
    *,
    extensions: frozenset[str] | None = None,
) -> list[str]:
    """Sammelt Mediendateien rekursiv unter scan_root."""
    if not scan_root or not os.path.isdir(scan_root):
        return []
    valid = extensions or _MEDIA_EXTENSIONS
    found = []
    try:
        for root, _dirs, files in os.walk(scan_root):
            for name in files:
                ext = os.path.splitext(name.lower())[1]
                if ext in valid:
                    found.append(os.path.join(root, name))
    except OSError:
        return found
    return found


def filter_collected_media_for_timelapse(
    media_paths: list[str],
    scan_root: str,
    *,
    exclude_timelapse_videos: bool = True,
) -> tuple[list[str], list[str], int]:
    """
    Teilt gefilterte Pfade in Videos und Fotos auf.
    Returns: (videos, photos, skipped_count)
    """
    dcim_root = resolve_dcim_root(scan_root)
    if dcim_root and exclude_timelapse_videos:
        filtered, skipped = filter_media_paths_for_backup(
            media_paths, dcim_root, exclude_timelapse_videos=True,
        )
    else:
        filtered, skipped = media_paths, 0

    videos = []
    photos = []
    for path in filtered:
        ext = os.path.splitext(path.lower())[1]
        if ext in _VIDEO_EXTENSIONS:
            videos.append(path)
        elif ext in _PHOTO_EXTENSIONS:
            photos.append(path)
    return videos, photos, skipped


def write_backup_manifest(backup_path: str, dcim_source: str, copied_entries: list[dict]) -> None:
    """Speichert Quellpfade im Backup für spätere Timelapse-Filterung beim Import."""
    manifest = {
        "version": 1,
        "dcim_source": dcim_source,
        "files": copied_entries,
    }
    manifest_path = os.path.join(backup_path, _BACKUP_MANIFEST_NAME)
    try:
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, ensure_ascii=False)
    except OSError as exc:
        print(f"Warnung: Backup-Manifest konnte nicht geschrieben werden: {exc}")


def read_backup_manifest(backup_path: str) -> Optional[dict]:
    manifest_path = os.path.join(backup_path, _BACKUP_MANIFEST_NAME)
    if not os.path.isfile(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def filter_backup_import_paths(
    video_paths: list[str],
    photo_paths: list[str],
    backup_path: str,
    *,
    exclude_timelapse_videos: bool = True,
) -> tuple[list[str], list[str], int]:
    """
    Filtert flache Backup-Dateien anhand des Manifests (Quellpfade auf der SD-Karte).
    """
    if not exclude_timelapse_videos:
        return video_paths, photo_paths, 0

    manifest = read_backup_manifest(backup_path)
    if not manifest:
        return video_paths, photo_paths, 0

    dcim_source = manifest.get("dcim_source") or ""
    src_by_dest = {
        entry.get("dest", "").lower(): entry.get("src", "")
        for entry in manifest.get("files", [])
        if entry.get("dest")
    }
    if not dcim_source or not src_by_dest:
        return video_paths, photo_paths, 0

    session_active = dcim_has_timelapse_photo_tree(dcim_source)
    kept_videos = []
    skipped = 0
    for path in video_paths:
        src = src_by_dest.get(os.path.basename(path).lower(), path)
        if should_skip_file_for_timelapse_session(
            src,
            dcim_source,
            is_video=True,
            timelapse_session_active=session_active,
            exclude_timelapse_videos=True,
        ):
            skipped += 1
            print(f"DJI Timelapse-Filter (Import): überspringe {os.path.basename(path)}")
            continue
        kept_videos.append(path)
    return kept_videos, photo_paths, skipped
