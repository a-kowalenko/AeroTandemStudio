"""Klassen-Alignment für Foto-Training (ohne PyTorch-/media_ai-Abhängigkeit)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_FOLDER_PREFIX_RE = re.compile(r"^\d+_")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".ppm", ".bmp", ".pgm", ".tif", ".tiff", ".webp"}


def strip_class_prefix(name: str) -> str:
    """'08_freefall' -> 'freefall' (wie in classifier.py)."""
    return _FOLDER_PREFIX_RE.sub("", name, count=1)


@dataclass(frozen=True)
class ClassLayout:
    """Zuordnung Checkpoint-Klassennamen zu Ordnern auf der Festplatte."""

    class_names: Tuple[str, ...]
    folder_by_class: Dict[str, str]
    samples: List[Tuple[str, int]]

    @property
    def num_classes(self) -> int:
        return len(self.class_names)


def list_dataset_folders(data_dir: Path) -> Dict[str, str]:
    """Ordnername -> absoluter Pfad (nur direkte Unterordner mit Bildern)."""
    folders: Dict[str, str] = {}
    if not data_dir.is_dir():
        return folders
    for entry in sorted(data_dir.iterdir()):
        if not entry.is_dir():
            continue
        if _folder_has_images(entry):
            folders[entry.name] = str(entry.resolve())
    return folders


def _folder_has_images(folder: Path) -> bool:
    for child in folder.rglob("*"):
        if child.is_file() and child.suffix.lower() in _IMAGE_EXTENSIONS:
            return True
    return False


def resolve_folder_for_class(class_name: str, folders: Dict[str, str]) -> Optional[str]:
    if class_name in folders:
        return folders[class_name]
    stripped = strip_class_prefix(class_name)
    if stripped in folders:
        return folders[stripped]
    for folder_name, path in folders.items():
        if strip_class_prefix(folder_name) == stripped:
            return path
    return None


def build_class_layout(
    data_dir: Path,
    class_names: Sequence[str],
    *,
    allow_missing_folders: bool = False,
) -> ClassLayout:
    """
    Sammelt alle Bildpfade mit Labels gemäß ``class_names``-Reihenfolge.

    Raises:
        FileNotFoundError: fehlende Ordner (wenn nicht erlaubt)
        ValueError: keine Bilder
    """
    folders = list_dataset_folders(data_dir)
    folder_by_class: Dict[str, str] = {}
    missing: List[str] = []

    for class_name in class_names:
        resolved = resolve_folder_for_class(class_name, folders)
        if resolved is None:
            missing.append(class_name)
            continue
        folder_by_class[class_name] = resolved

    if missing and not allow_missing_folders:
        raise FileNotFoundError(
            f"Keine Ordner für Klassen gefunden unter {data_dir}:\n"
            + "\n".join(f"  - {name}" for name in missing)
        )

    samples: List[Tuple[str, int]] = []
    for class_idx, class_name in enumerate(class_names):
        folder_path = folder_by_class.get(class_name)
        if not folder_path:
            continue
        folder = Path(folder_path)
        for image_path in sorted(folder.rglob("*")):
            if image_path.is_file() and image_path.suffix.lower() in _IMAGE_EXTENSIONS:
                samples.append((str(image_path.resolve()), class_idx))

    if not samples:
        raise ValueError(f"Keine Trainingsbilder unter {data_dir} gefunden.")

    return ClassLayout(
        class_names=tuple(class_names),
        folder_by_class=folder_by_class,
        samples=samples,
    )


def validate_finetune_class_set(
    data_dir: Path,
    checkpoint_class_names: Sequence[str],
) -> ClassLayout:
    """
    Fine-Tune: exakt dieselben Klassen wie im Checkpoint.

    Raises:
        ValueError: neue Klassen-Ordner im Dateisystem
    """
    folders = list_dataset_folders(data_dir)
    checkpoint_stripped = {strip_class_prefix(c) for c in checkpoint_class_names}
    extra: List[str] = []

    for folder_name in folders:
        if folder_name in checkpoint_class_names:
            continue
        if strip_class_prefix(folder_name) in checkpoint_stripped:
            continue
        extra.append(folder_name)

    if extra:
        raise ValueError(
            "Fine-Tuning unterstützt keine neuen Klassen-Ordner. "
            "Bitte ohne --finetune (Full-Train) ausführen.\n"
            f"Neue Ordner: {', '.join(sorted(extra))}"
        )

    return build_class_layout(data_dir, checkpoint_class_names)
