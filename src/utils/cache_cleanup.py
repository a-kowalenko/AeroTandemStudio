"""
Zentraler Dienst zum Löschen temporärer App-Dateien und -Ordner.
"""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.utils.constants import CONFIG_DIR

HW_CACHE_FILE = os.path.join(CONFIG_DIR, "hw_cache.json")


@dataclass
class CacheCleanupResult:
    deleted_dirs: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    bytes_freed: int = 0

    def summary_message(self) -> str:
        dir_count = len(self.deleted_dirs)
        file_count = len(self.deleted_files)
        size = format_bytes(self.bytes_freed)
        lines = [
            f"{dir_count} Ordner und {file_count} Dateien gelöscht ({size}).",
        ]
        if self.errors:
            lines.append(f"{len(self.errors)} Element(e) konnten nicht gelöscht werden.")
        return "\n".join(lines)


def format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} MB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"


class CacheCleanupService:
    PREVIEW_DIR_PREFIX = "aero_studio_preview_"
    KNOWN_TEMP_FILES = ("preview_combined_fast.mp4", "preview_concat_list.txt")
    AEROTANDEM_WORK_DIRNAME = ".aerotandem_work"

    @classmethod
    def cleanup_orphans_only(cls, exclude_temp_dir: Optional[str] = None) -> CacheCleanupResult:
        """Löscht nur verwaiste Temp-Ordner/Dateien, ohne .aerotandem_work."""
        result = CacheCleanupResult()
        cls._delete_orphan_preview_dirs(result, exclude=exclude_temp_dir)
        cls._delete_known_temp_files(result)
        return result

    @classmethod
    def cleanup_all(
        cls,
        *,
        exclude_temp_dir: Optional[str] = None,
        base_paths_for_work: Optional[Iterable[str]] = None,
        include_hw_cache: bool = False,
    ) -> CacheCleanupResult:
        result = CacheCleanupResult()
        cls._delete_orphan_preview_dirs(result, exclude=exclude_temp_dir)
        cls._delete_known_temp_files(result)
        if base_paths_for_work:
            cls._delete_aerotandem_work_dirs(result, base_paths_for_work)
        if include_hw_cache:
            cls._delete_hw_cache(result)
        return result

    @classmethod
    def collect_work_base_paths(
        cls,
        speicherort: Optional[str] = None,
        import_paths: Optional[Iterable[str]] = None,
    ) -> list[str]:
        bases: list[str] = []
        seen: set[str] = set()

        def add_base(path: Optional[str]) -> None:
            if not path:
                return
            path = os.path.abspath(path)
            if os.path.isfile(path):
                path = os.path.dirname(path)
            if not os.path.isdir(path):
                return
            if path not in seen:
                seen.add(path)
                bases.append(path)

        add_base(speicherort)
        if import_paths:
            for item in import_paths:
                add_base(item)
        return bases

    @classmethod
    def _delete_orphan_preview_dirs(
        cls, result: CacheCleanupResult, exclude: Optional[str] = None
    ) -> None:
        temp_root = tempfile.gettempdir()
        exclude_norm = os.path.normcase(os.path.abspath(exclude)) if exclude else None
        pattern = os.path.join(temp_root, f"{cls.PREVIEW_DIR_PREFIX}*")
        for path in glob.glob(pattern):
            if not os.path.isdir(path):
                continue
            path_norm = os.path.normcase(os.path.abspath(path))
            if exclude_norm and path_norm == exclude_norm:
                continue
            cls._rmtree(path, result)

    @classmethod
    def _delete_known_temp_files(cls, result: CacheCleanupResult) -> None:
        temp_root = tempfile.gettempdir()
        for name in cls.KNOWN_TEMP_FILES:
            path = os.path.join(temp_root, name)
            cls._remove_file(path, result)

    @classmethod
    def _delete_aerotandem_work_dirs(
        cls, result: CacheCleanupResult, base_paths: Iterable[str]
    ) -> None:
        work_dirs: set[str] = set()
        for base in base_paths:
            if not base:
                continue
            if os.path.isfile(base):
                base = os.path.dirname(os.path.abspath(base))
            work = os.path.join(base, cls.AEROTANDEM_WORK_DIRNAME)
            work_dirs.add(os.path.abspath(work))
        for work_dir in work_dirs:
            if os.path.isdir(work_dir):
                cls._rmtree(work_dir, result)

    @classmethod
    def _delete_hw_cache(cls, result: CacheCleanupResult) -> None:
        cls._remove_file(HW_CACHE_FILE, result)

    @classmethod
    def _rmtree(cls, path: str, result: CacheCleanupResult) -> None:
        if not os.path.exists(path):
            return
        try:
            size = cls._path_size(path)
            shutil.rmtree(path)
            result.deleted_dirs.append(path)
            result.bytes_freed += size
        except Exception as exc:
            result.errors.append(f"{path}: {exc}")

    @classmethod
    def _remove_file(cls, path: str, result: CacheCleanupResult) -> None:
        if not os.path.isfile(path):
            return
        try:
            size = os.path.getsize(path)
            os.remove(path)
            result.deleted_files.append(path)
            result.bytes_freed += size
        except Exception as exc:
            result.errors.append(f"{path}: {exc}")

    @classmethod
    def _path_size(cls, path: str) -> int:
        total = 0
        if os.path.isfile(path):
            try:
                return os.path.getsize(path)
            except OSError:
                return 0
        for root, _dirs, files in os.walk(path):
            for name in files:
                file_path = os.path.join(root, name)
                try:
                    total += os.path.getsize(file_path)
                except OSError:
                    pass
        return total
