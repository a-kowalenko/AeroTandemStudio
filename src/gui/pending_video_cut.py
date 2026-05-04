"""Geplante Video-Schnitte (Warteschlange vor FFmpeg)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class PendingVideoCut:
    """Ein geplanter Trim- oder Split-Vorgang für eine Arbeitskopie."""

    source_path: str
    list_index: int
    kind: str  # "trim" | "split"
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    split_ms: Optional[int] = None

    def summary_line(self) -> str:
        name = self.source_path.replace("\\", "/").split("/")[-1]
        if self.kind == "trim":
            return f"Trim: {name}  ({self._fmt(self.start_ms)} – {self._fmt(self.end_ms)})"
        return f"Teilen: {name}  bei {self._fmt(self.split_ms)}"

    @staticmethod
    def _fmt(ms: Optional[int]) -> str:
        if ms is None:
            return "?"
        s = ms // 1000
        m = s // 60
        s = s % 60
        frac = ms % 1000
        return f"{m:02d}:{s:02d}.{frac:03d}"
