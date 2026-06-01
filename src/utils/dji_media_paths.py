"""DJI SD-Karten Pfad-Hilfen für Foto-Timelapse-Sessions."""
import json
import os
import re
import sys
from datetime import datetime
from typing import Optional

from src.utils.file_times import get_creation_timestamp
from src.utils.media_datetime import get_pil_exif_capture_datetime

_TIMELAPSE_DIR_NAMES = frozenset({"timelapse"})
_DJI_DIR_RE = re.compile(r"^dji_", re.IGNORECASE)
_BACKUP_MANIFEST_NAME = ".aerotandem_manifest.json"
_TIMELAPSE_PHOTO_FILENAME_RE = re.compile(
    r"^Foto_\d{17}(?:_\d{3})?\.(jpg|jpeg)$",
    re.IGNORECASE,
)

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


def normalize_media_path(path: str) -> str:
    """
    Normalisiert Medienpfade, insbesondere Windows E:DCIM -> E:\\DCIM.
    os.path.join('E:', 'DCIM') liefert sonst einen relativen Pfad auf Laufwerk E:.
    """
    if not path:
        return path
    path = os.path.normpath(path)
    if sys.platform == "win32" and len(path) >= 2 and path[1] == ":":
        drive, rest = path[:2], path[2:]
        rest = rest.lstrip("\\/")
        if rest:
            return os.path.join(drive + "\\", rest)
        return drive + "\\"
    return path


def resolve_drive_dcim_path(drive: str) -> str:
    """Liefert den absoluten DCIM-Pfad für ein Laufwerk (z. B. E: -> E:\\DCIM)."""
    drive = (drive or "").rstrip("\\/")
    if not drive:
        return ""
    return normalize_media_path(os.path.join(drive, "DCIM"))


def _dcim_index(parts: list[str]) -> Optional[int]:
    for i, part in enumerate(parts):
        if part.upper() == "DCIM":
            return i
    return None


def resolve_dcim_root(path: str) -> Optional[str]:
    """Findet den DCIM-Ordner zu einem Pfad (SD-Karte, Unterordner oder DCIM selbst)."""
    if not path:
        return None
    norm = normalize_media_path(os.path.abspath(os.path.normpath(path)))
    if not os.path.exists(norm):
        norm = normalize_media_path(os.path.dirname(norm) or norm)
    current = norm
    while True:
        if os.path.basename(current).upper() == "DCIM" and os.path.isdir(current):
            return normalize_media_path(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    child = normalize_media_path(os.path.join(norm, "DCIM"))
    if os.path.isdir(child):
        return child
    return None


def _path_under_dcim(file_path: str, dcim_root: str) -> bool:
    """True wenn file_path logisch unter dcim_root liegt (auch wenn SD entfernt)."""
    if not file_path or not dcim_root:
        return False
    try:
        file_abs = normalize_media_path(os.path.abspath(file_path))
        dcim_abs = normalize_media_path(os.path.abspath(dcim_root))
        return os.path.commonpath([file_abs, dcim_abs]) == dcim_abs
    except ValueError:
        return False


def _path_has_timelapse_segment(parts: list[str], dcim_idx: int) -> bool:
    return any(p.lower() in _TIMELAPSE_DIR_NAMES for p in parts[dcim_idx + 1:])


def _path_has_dji_segment(parts: list[str], dcim_idx: int) -> bool:
    return any(_DJI_DIR_RE.match(p) for p in parts[dcim_idx + 1:])


def dcim_has_timelapse_photo_tree(dcim_root: str) -> bool:
    """True wenn irgendwo unter DCIM ein TIMELAPSE-Ordner mit Fotos existiert."""
    dcim_root = normalize_media_path(dcim_root)
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


def is_under_dji_timelapse_tree(file_path: str, dcim_root: str = "") -> bool:
    """True wenn die Datei unter DCIM/…/TIMELAPSE/… liegt."""
    parts = _norm_parts(normalize_media_path(file_path))
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None:
        return False
    if dcim_root and not _path_under_dcim(file_path, dcim_root):
        return False
    return _path_has_timelapse_segment(parts, dcim_idx)


def _path_is_timelapse_photo_location(file_path: str) -> bool:
    """True wenn Pfadstruktur DCIM/…/TIMELAPSE/… und Foto-Endung."""
    if not file_path:
        return False
    ext = os.path.splitext(file_path.lower())[1]
    if ext not in _PHOTO_EXTENSIONS:
        return False
    return is_under_dji_timelapse_tree(file_path, "")


def _path_is_under_dcim_tree(file_path: str) -> bool:
    parts = _norm_parts(normalize_media_path(file_path))
    return _dcim_index(parts) is not None


def is_under_dji_numbered_folder(file_path: str, dcim_root: str) -> bool:
    """True wenn die Datei unter DCIM/…/DJI_* /… liegt."""
    parts = _norm_parts(file_path)
    dcim_idx = _dcim_index(parts)
    if dcim_idx is None:
        return False
    if dcim_root and not _path_under_dcim(file_path, dcim_root):
        return False
    return _path_has_dji_segment(parts, dcim_idx)


def is_timelapse_photo_path(file_path: str, dcim_root: Optional[str] = None) -> bool:
    """True wenn file_path ein Foto unter DCIM/…/TIMELAPSE/… ist."""
    del dcim_root  # Erkennung erfolgt über Pfadsegmente (robust bei E:DCIM vs E:\\DCIM)
    return _path_is_timelapse_photo_location(file_path)


def is_timelapse_photo_filename(filename: str) -> bool:
    """True wenn der Dateiname bereits im Foto-Timelapse-Schema liegt."""
    return bool(_TIMELAPSE_PHOTO_FILENAME_RE.match(os.path.basename(filename)))


def manifest_has_timelapse_photos(manifest: dict, dcim_source: str = "") -> bool:
    """Erkennt Timelapse-Session anhand gesicherter Manifest-Einträge."""
    del dcim_source
    for entry in manifest.get("files", []):
        if entry.get("media_type") != "photo":
            continue
        src = entry.get("src") or ""
        if _path_is_timelapse_photo_location(src):
            return True
    return False


def paths_indicate_timelapse_session(media_paths: list[str]) -> bool:
    """True wenn mindestens ein Timelapse-Foto in der Pfadliste vorkommt."""
    return any(_path_is_timelapse_photo_location(path) for path in media_paths)


def resolve_timelapse_session_active(
    dcim_source: str = "",
    *,
    manifest: Optional[dict] = None,
) -> bool:
    """
    True wenn eine DJI Foto-Timelapse-Session aktiv ist.
    Nutzt Manifest-Flag, Manifest-Einträge oder live DCIM-Scan (in dieser Reihenfolge).
    """
    if manifest is not None:
        if manifest.get("timelapse_session_active"):
            return True
        if manifest_has_timelapse_photos(manifest, dcim_source):
            return True
    if dcim_source and dcim_has_timelapse_photo_tree(dcim_source):
        return True
    return False


def manifest_src_by_dest(manifest: dict) -> dict[str, str]:
    return {
        entry.get("dest", "").lower(): entry.get("src", "")
        for entry in manifest.get("files", [])
        if entry.get("dest")
    }


def resolve_manifest_source_path(file_path: str, manifest: Optional[dict]) -> str:
    """Quellpfad auf SD-Karte aus Manifest, sonst file_path."""
    if not manifest:
        return file_path
    src = manifest_src_by_dest(manifest).get(os.path.basename(file_path).lower())
    return src or file_path


def manifest_entry_for_dest(manifest: dict, dest_name: str) -> Optional[dict]:
    """Findet den Manifest-Eintrag zu einem Backup-Dateinamen."""
    key = (dest_name or "").lower()
    if not key:
        return None
    for entry in manifest.get("files", []):
        if (entry.get("dest") or "").lower() == key:
            return entry
    return None


def should_skip_file_for_timelapse_session(
    file_path: str,
    dcim_root: str,
    *,
    is_video: bool,
    timelapse_session_active: bool,
    exclude_timelapse_videos: bool = True,
) -> bool:
    """
    DJI Foto-Timelapse: Bei aktiver Session alle Videos überspringen.
    Ohne Session nur Videos unter DCIM/…/TIMELAPSE/….
    """
    del dcim_root
    if not exclude_timelapse_videos:
        return False
    if not is_video:
        return False
    if timelapse_session_active:
        return True
    if is_under_dji_timelapse_tree(file_path, ""):
        return True
    return False


def should_skip_backup_video_file(
    backup_file_path: str,
    *,
    manifest: Optional[dict],
    exclude_timelapse_videos: bool = True,
    timelapse_session_active: Optional[bool] = None,
) -> bool:
    """
    Entscheidet ob eine Video-Datei aus einem Backup-Ordner übersprungen wird.
    Manifest-Flag timelapse_session_active hat Vorrang (auch wenn Einstellung aus).
    """
    ext = os.path.splitext(backup_file_path.lower())[1]
    if ext not in _VIDEO_EXTENSIONS:
        return False
    if not manifest:
        return False

    if manifest.get("timelapse_session_active"):
        return True

    if not exclude_timelapse_videos:
        return False

    dcim_source = normalize_media_path(manifest.get("dcim_source") or "")
    src_by_dest = manifest_src_by_dest(manifest)
    session_active = timelapse_session_active
    if session_active is None:
        session_active = resolve_timelapse_session_active_for_paths(
            dcim_source,
            list(src_by_dest.values()),
            manifest=manifest,
        )
    if not session_active:
        return False

    dest_name = os.path.basename(backup_file_path)
    entry = manifest_entry_for_dest(manifest, dest_name)
    if entry and entry.get("media_type") == "video":
        return True

    src = src_by_dest.get(dest_name.lower()) or (entry.get("src") if entry else "")
    return should_skip_file_for_timelapse_session(
        src or backup_file_path,
        dcim_source,
        is_video=True,
        timelapse_session_active=True,
        exclude_timelapse_videos=True,
    )


def resolve_timelapse_session_active_for_paths(
    dcim_source: str,
    media_paths: list[str],
    *,
    manifest: Optional[dict] = None,
) -> bool:
    """Erkennt Timelapse-Session aus Manifest, DCIM-Scan oder vorliegenden Pfaden."""
    if resolve_timelapse_session_active(dcim_source, manifest=manifest):
        return True
    return paths_indicate_timelapse_session(media_paths)


def filter_media_paths_for_backup(
    media_paths: list[str],
    dcim_root: str,
    *,
    exclude_timelapse_videos: bool = True,
) -> tuple[list[str], int]:
    """Filtert Pfade für SD-Backup/Import; gibt (behalten, übersprungen_anzahl) zurück."""
    if not exclude_timelapse_videos:
        return media_paths, 0
    effective_dcim = normalize_media_path(resolve_dcim_root(dcim_root) or dcim_root)
    session_active = resolve_timelapse_session_active_for_paths(
        effective_dcim,
        media_paths,
    )
    if session_active:
        print("DJI Timelapse-Session erkannt: Videos unter DCIM werden übersprungen")
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


def collect_media_from_backup_folder(
    backup_path: str,
    *,
    exclude_timelapse_videos: bool = True,
) -> tuple[list[str], list[str], int]:
    """
    Sammelt Medien aus einem flachen SD-Backup-Ordner inkl. Manifest-Filter.
    Returns: (videos, photos, skipped_count)
    """
    manifest = read_backup_manifest(backup_path)
    if not manifest:
        videos, photos = [], []
        skipped = 0
        try:
            for name in os.listdir(backup_path):
                if name.startswith("."):
                    continue
                path = os.path.join(backup_path, name)
                if not os.path.isfile(path):
                    continue
                ext = os.path.splitext(name.lower())[1]
                if ext in _VIDEO_EXTENSIONS:
                    videos.append(path)
                elif ext in _PHOTO_EXTENSIONS:
                    photos.append(path)
        except OSError:
            pass
        return videos, photos, skipped

    dcim_source = normalize_media_path(manifest.get("dcim_source") or "")
    src_by_dest = manifest_src_by_dest(manifest)
    session_active = resolve_timelapse_session_active_for_paths(
        dcim_source,
        list(src_by_dest.values()),
        manifest=manifest,
    )
    manifest_session = bool(manifest.get("timelapse_session_active"))
    if (manifest_session or session_active) and exclude_timelapse_videos:
        print("DJI Timelapse-Session (Backup-Import): Videos werden übersprungen")
    elif manifest_session and not exclude_timelapse_videos:
        print(
            "DJI Timelapse-Session (Manifest): Videos werden übersprungen "
            "(timelapse_session_active im Backup)"
        )

    videos = []
    photos = []
    skipped = 0
    try:
        for name in os.listdir(backup_path):
            if name.startswith("."):
                continue
            path = os.path.join(backup_path, name)
            if not os.path.isfile(path):
                continue
            ext = os.path.splitext(name.lower())[1]
            if ext in _VIDEO_EXTENSIONS:
                if should_skip_backup_video_file(
                    path,
                    manifest=manifest,
                    exclude_timelapse_videos=exclude_timelapse_videos,
                    timelapse_session_active=session_active,
                ):
                    skipped += 1
                    print(f"DJI Timelapse-Filter (Import): überspringe {name}")
                    continue
                videos.append(path)
            elif ext in _PHOTO_EXTENSIONS:
                photos.append(path)
    except OSError:
        pass
    return videos, photos, skipped


def build_timelapse_photo_filename(
    photo_path: str,
    used_names: set[str],
) -> str:
    """
    Erzeugt Foto_yyyyMMddHHmmssSSS.JPG aus EXIF; bei Kollision _001, _002, …
    used_names: lowercase Dateinamen, die bereits vergeben sind (wird aktualisiert).
    """
    dt, ms = get_pil_exif_capture_datetime(photo_path)
    if dt is None:
        ts = get_creation_timestamp(photo_path)
        if ts is not None:
            dt = datetime.fromtimestamp(ts)
        else:
            dt = datetime.now()
        ms = "000"

    ext = os.path.splitext(photo_path)[1] or ".JPG"
    if ext.lower() == ".jpg":
        ext = ".JPG"

    base = f"Foto_{dt.strftime('%Y%m%d%H%M%S')}{ms}"
    candidate = f"{base}{ext}"
    key = candidate.lower()
    if key not in used_names:
        used_names.add(key)
        return candidate

    counter = 1
    while True:
        candidate = f"{base}_{counter:03d}{ext}"
        key = candidate.lower()
        if key not in used_names:
            used_names.add(key)
            return candidate
        counter += 1


def write_backup_manifest(
    backup_path: str,
    dcim_source: str,
    copied_entries: list[dict],
    *,
    timelapse_session_active: bool = False,
) -> None:
    """Speichert Quellpfade im Backup für spätere Timelapse-Filterung beim Import."""
    dcim_source = normalize_media_path(dcim_source)
    normalized_entries = []
    for entry in copied_entries:
        item = dict(entry)
        if item.get("src"):
            item["src"] = normalize_media_path(item["src"])
        normalized_entries.append(item)
    manifest = {
        "version": 2,
        "dcim_source": dcim_source,
        "timelapse_session_active": bool(timelapse_session_active),
        "files": normalized_entries,
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

    dcim_source = normalize_media_path(manifest.get("dcim_source") or "")
    src_by_dest = manifest_src_by_dest(manifest)
    if not dcim_source or not src_by_dest:
        return video_paths, photo_paths, 0

    session_active = resolve_timelapse_session_active_for_paths(
        dcim_source,
        list(src_by_dest.values()),
        manifest=manifest,
    )
    kept_videos = []
    skipped = 0
    for path in video_paths:
        if should_skip_backup_video_file(
            path,
            manifest=manifest,
            exclude_timelapse_videos=True,
            timelapse_session_active=session_active,
        ):
            skipped += 1
            print(f"DJI Timelapse-Filter (Import): überspringe {os.path.basename(path)}")
            continue
        kept_videos.append(path)
    return kept_videos, photo_paths, skipped


def should_skip_video_for_import(
    file_path: str,
    *,
    exclude_timelapse_videos: bool = True,
    manifest: Optional[dict] = None,
) -> bool:
    """Sicherheitsnetz beim Import einzelner Videos (SD-Pfad oder Backup-Manifest)."""
    if manifest is None:
        manifest = read_backup_manifest(os.path.dirname(file_path))

    if manifest:
        return should_skip_backup_video_file(
            file_path,
            manifest=manifest,
            exclude_timelapse_videos=exclude_timelapse_videos,
        )

    if not exclude_timelapse_videos:
        return False

    dcim_root = resolve_dcim_root(file_path)
    if not dcim_root:
        return False
    session_active = dcim_has_timelapse_photo_tree(dcim_root)
    return should_skip_file_for_timelapse_session(
        file_path,
        dcim_root,
        is_video=True,
        timelapse_session_active=session_active,
        exclude_timelapse_videos=True,
    )


def resolve_timelapse_photo_import_name(
    source_file_path: str,
    logical_source_path: str,
    dcim_root: Optional[str],
    used_names: set[str],
) -> Optional[str]:
    """
    Liefert Zielnamen für Timelapse-Fotos oder None wenn kein Timelapse-Foto.
    logical_source_path: Pfad auf SD-Karte (Manifest-src) oder source_file_path.
    """
    del dcim_root
    check_path = logical_source_path or source_file_path
    if not is_timelapse_photo_path(check_path):
        return None
    return build_timelapse_photo_filename(source_file_path, used_names)
