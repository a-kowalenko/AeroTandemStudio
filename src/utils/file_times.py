"""
Dateizeiten für die Anzeige (Erstellung vs. Änderung).

Windows: os.path.getctime = Erstellungszeit.
macOS/BSD: st_birthtime.
Linux: oft keine echte Erstellungszeit → Fallback auf Änderungszeit (mtime).
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional


def get_creation_timestamp(path: str) -> Optional[float]:
    """
    Liefert den Erstellungszeitpunkt als Unix-Timestamp (Sekunden), wenn das OS einen liefert,
    sonst eine sinnvolle Näherung (mtime auf Linux ohne Birth-Time).
    """
    try:
        st = os.stat(path)
    except OSError:
        return None

    if sys.platform == "win32":
        try:
            return float(os.path.getctime(path))
        except OSError:
            return None

    birth = getattr(st, "st_birthtime", None)
    if birth is not None:
        return float(birth)

    # Linux u. a.: keine Birth-Time → mtime (Inhalt zuletzt geschrieben)
    return float(st.st_mtime)


def format_creation_date(path: str) -> str:
    ts = get_creation_timestamp(path)
    if ts is None:
        return "Unbekannt"
    return time.strftime("%d.%m.%Y", time.localtime(ts))


def format_creation_time(path: str) -> str:
    ts = get_creation_timestamp(path)
    if ts is None:
        return "Unbekannt"
    return time.strftime("%H:%M:%S", time.localtime(ts))
