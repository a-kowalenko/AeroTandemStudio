"""Hilfsfunktionen für PIL-Thumbnails beim Foto-Import."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Optional

THUMB_MAX_SIZE = int(60 * 1.3)


def build_pil_thumbnail(photo_path: str, max_size: int = THUMB_MAX_SIZE):
    """
    Lädt ein Foto und erzeugt ein quadratisches PIL-Thumbnail (max. max_size px).
    Gibt None zurück bei Fehler (wie bisher im Import-Thread).
    """
    from PIL import Image

    try:
        img = Image.open(photo_path)
        try:
            img.load()
            img.thumbnail((max_size, max_size), Image.LANCZOS)
            return img.copy()
        finally:
            img.close()
    except Exception as e:
        print(f"Fehler beim Vorberechnen des Thumbnails für {photo_path}: {e}")
        return None


def _should_emit_progress(completed: int, total: int) -> bool:
    if completed >= total:
        return True
    step = max(1, total // 20)
    return completed % step == 0


def build_pil_thumbnails_parallel(
    paths: list[str],
    max_size: int = THUMB_MAX_SIZE,
    workers: int = 2,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> dict[str, object]:
    """
    Erzeugt Thumbnails parallel via ThreadPoolExecutor.

    Args:
        paths: Liste der Foto-Pfade
        max_size: Maximale Kantenlänge des Thumbnails
        workers: Gewünschte Worker-Anzahl (wird auf 1..4 und len(paths) begrenzt)
        cancel_check: Optional; True = Abbruch anfordern
        on_progress: Optional; (completed, total, basename) nach jedem Fortschrittsschritt

    Returns:
        Dict path -> PIL.Image für erfolgreich erzeugte Thumbnails
    """
    if not paths:
        return {}

    if cancel_check and cancel_check():
        return {}

    worker_count = max(1, min(int(workers), len(paths), 4))
    total = len(paths)
    result: dict[str, object] = {}
    result_lock = threading.Lock()
    progress_lock = threading.Lock()
    completed = 0
    cancelled = False

    def _report_progress(last_basename: str) -> None:
        if on_progress is None:
            return
        with progress_lock:
            if not _should_emit_progress(completed, total):
                return
            on_progress(completed, total, last_basename)

    def _process_one(photo_path: str):
        if cancel_check and cancel_check():
            return photo_path, None
        thumb = build_pil_thumbnail(photo_path, max_size)
        return photo_path, thumb

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for photo_path in paths:
            if cancel_check and cancel_check():
                cancelled = True
                break
            futures[executor.submit(_process_one, photo_path)] = photo_path

        for future in as_completed(futures):
            if cancel_check and cancel_check():
                cancelled = True
                break

            photo_path = futures[future]
            try:
                path, thumb = future.result()
            except Exception as e:
                print(f"Fehler bei paralleler Thumbnail-Erzeugung für {photo_path}: {e}")
                path, thumb = photo_path, None

            if thumb is not None:
                with result_lock:
                    result[path] = thumb

            with progress_lock:
                completed += 1
                basename = os.path.basename(path)
            _report_progress(basename)

        if cancelled:
            for pending in futures:
                pending.cancel()

    return result
