"""
Eindeutige Anzeige-/Sortier-Zeit für Medien.

Priorität: eingebettete Zeiten (EXIF bzw. Container-Tags / ffprobe) vor Dateisystem-
Zeiten (Import-Snapshot, Originalpfad, Kopie).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.file_times import get_creation_timestamp

# EXIF: DateTimeOriginal, DateTime, SubSecTimeOriginal
_EXIF_DATETIME_ORIGINAL = 36867
_EXIF_DATETIME = 306
_EXIF_SUBSEC_TIME_ORIGINAL = 37521
_EXIF_SUBSEC_TIME = 37520


def _parse_tag_to_epoch(tag_val: str) -> Optional[float]:
    if not tag_val or not isinstance(tag_val, str):
        return None
    s = tag_val.strip()
    if not s:
        return None
    # ISO-ähnlich (z. B. creation_time von FFmpeg)
    if s.endswith("Z") or re.match(r"^\d{4}-\d{2}-\d{2}T", s):
        try:
            if s.endswith("Z"):
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            elif len(s) >= 19 and "+" in s[10:]:
                dt = datetime.fromisoformat(s)
            else:
                dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
            return float(dt.timestamp())
        except (ValueError, OSError, TypeError):
            pass
    # EXIF-Kameraformat
    try:
        if len(s) >= 19:
            dt = datetime.strptime(s[:19], "%Y:%m:%d %H:%M:%S")
            return float(dt.timestamp())
    except ValueError:
        pass
    return None


def get_ffprobe_format_creation_epoch(path: str) -> Optional[float]:
    """Liest creation_time o. ä. aus ffprobe format/tags oder erstem Videostream."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=SUBPROCESS_CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout:
            return None
        data: Dict[str, Any] = json.loads(result.stdout)
        tags_list = []
        fmt = data.get("format") or {}
        tags_list.append(fmt.get("tags") or {})
        for stream in data.get("streams") or []:
            if stream.get("codec_type") == "video":
                tags_list.append(stream.get("tags") or {})
                break
        for tags in tags_list:
            for key in (
                "creation_time",
                "com.apple.quicktime.creationdate",
                "date",
            ):
                raw = tags.get(key)
                if raw:
                    epoch = _parse_tag_to_epoch(str(raw))
                    if epoch is not None:
                        return epoch
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError, TypeError, ValueError):
        pass
    return None


def _decode_exif_text(raw) -> Optional[str]:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    return None


def _normalize_exif_subsec_to_ms(subsec: Optional[str]) -> str:
    """Wandelt EXIF SubSecTime(Original) in 3-stellige Millisekunden um."""
    if not subsec:
        return "000"
    digits = re.sub(r"\D", "", subsec)[:3]
    return digits.ljust(3, "0") if digits else "000"


def get_pil_exif_capture_datetime(path: str) -> Tuple[Optional[datetime], str]:
    """
    Liest EXIF DateTimeOriginal (+ SubSecTimeOriginal) für Dateinamen.
    Returns: (datetime ohne Bruchteil, Millisekunden als 3-stelliger String)
    """
    try:
        from PIL import Image

        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None, "000"
            raw_dt = _decode_exif_text(
                exif.get(_EXIF_DATETIME_ORIGINAL) or exif.get(_EXIF_DATETIME)
            )
            if not raw_dt or len(raw_dt) < 19:
                return None, "000"
            try:
                dt = datetime.strptime(raw_dt[:19], "%Y:%m:%d %H:%M:%S")
            except ValueError:
                return None, "000"
            raw_subsec = _decode_exif_text(
                exif.get(_EXIF_SUBSEC_TIME_ORIGINAL) or exif.get(_EXIF_SUBSEC_TIME)
            )
            return dt, _normalize_exif_subsec_to_ms(raw_subsec)
    except Exception:
        pass
    return None, "000"


def get_pil_exif_epoch(path: str) -> Optional[float]:
    """EXIF DateTimeOriginal / DateTime (z. B. JPG; bei manchen Formaten auch embed)."""
    dt, ms = get_pil_exif_capture_datetime(path)
    if dt is None:
        return None
    try:
        epoch = float(dt.timestamp())
        ms_val = int(ms)
        return epoch + (ms_val / 1000.0)
    except (ValueError, OSError, OverflowError):
        return float(dt.timestamp())


def resolve_video_display_epoch(
    copy_path: str,
    source_import_epoch: Optional[float] = None,
    alternate_original_path: Optional[str] = None,
) -> float:
    """
    Reihenfolge (Prio 1 = eingebettete „Aufnahme“-Zeit):
    1. EXIF im File (PIL), falls vorhanden
    2. Container-/Stream-Tags (ffprobe: creation_time u. ä.)
    3. Snapshot vom Import (Dateizeit der Quelle beim Kopieren)
    4. Dateizeit eines noch lesbaren Originalpfads (von außerhalb des Working-Folders)
    5. Dateisystem der Kopie
    """
    ts = get_pil_exif_epoch(copy_path)
    if ts is not None:
        return float(ts)

    ts = get_ffprobe_format_creation_epoch(copy_path)
    if ts is not None:
        return float(ts)

    if source_import_epoch is not None:
        return float(source_import_epoch)

    if (
        alternate_original_path
        and os.path.normpath(alternate_original_path) != os.path.normpath(copy_path)
        and os.path.exists(alternate_original_path)
    ):
        ts = get_creation_timestamp(alternate_original_path)
        if ts is not None:
            return float(ts)

    ts = get_creation_timestamp(copy_path)
    return float(ts) if ts is not None else 0.0


def get_photo_display_epoch(
    photo_path: str,
    source_import_epoch: Optional[float] = None,
) -> float:
    """
    Gleiche Priorität wie Videos (resolve_video_display_epoch):
    eingebettete Zeiten (EXIF, ffprobe), dann Import-Snapshot der Quelle,
    dann Dateisystem der Kopie.
    """
    return resolve_video_display_epoch(photo_path, source_import_epoch, None)


def format_epoch_date(epoch: float) -> str:
    return time.strftime("%d.%m.%Y", time.localtime(epoch))


def format_epoch_time(epoch: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(epoch))


def format_photo_table_datetime(
    photo_path: str,
    source_import_epoch: Optional[float] = None,
) -> Tuple[str, str]:
    e = get_photo_display_epoch(photo_path, source_import_epoch)
    return format_epoch_date(e), format_epoch_time(e)
