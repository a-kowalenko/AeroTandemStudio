"""Natürliche alphanumerische Sortierung für Dateinamen (z. B. clip2 vor clip10)."""

import os
import re
from typing import List


def natural_sort_key(text: str):
    """
    Key-Funktion für sorted(...): zerlegt String in Text- und Zahlteile.
    """
    parts = re.split(r"(\d+)", text)
    key = []
    for p in parts:
        if p.isdigit():
            key.append(int(p))
        else:
            key.append(p.lower())
    return key


def sort_paths_by_basename(paths: List[str]) -> List[str]:
    """Sortiert Pfade nach Basisnamen (natürliche Reihenfolge)."""
    return sorted(paths, key=lambda p: natural_sort_key(os.path.basename(p)))
