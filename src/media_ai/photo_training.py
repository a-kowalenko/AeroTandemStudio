"""PyTorch-Dataset für Foto-Klassifikator-Training."""

from __future__ import annotations

from torch.utils.data import Dataset
from torchvision.datasets.folder import default_loader

from src.photo_class_layout import ClassLayout

__all__ = [
    "AlignedImageDataset",
    "ClassLayout",
    "build_class_layout",
    "list_dataset_folders",
    "strip_class_prefix",
    "validate_finetune_class_set",
]

from src.photo_class_layout import (  # noqa: E402
    build_class_layout,
    list_dataset_folders,
    strip_class_prefix,
    validate_finetune_class_set,
)


class AlignedImageDataset(Dataset):
    """Image-Dataset mit fester Label-Reihenfolge aus dem Checkpoint."""

    def __init__(
        self,
        layout: ClassLayout,
        transform=None,
        loader=default_loader,
    ) -> None:
        self.layout = layout
        self.transform = transform
        self.loader = loader
        self.samples = layout.samples
        self.classes = list(layout.class_names)
        self.class_to_idx = {name: idx for idx, name in enumerate(self.classes)}

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, index: int):
        path, target = self.samples[index]
        sample = self.loader(path)
        if self.transform is not None:
            sample = self.transform(sample)
        return sample, target

    def __repr__(self) -> str:
        return f"AlignedImageDataset({len(self.samples)} samples, {len(self.classes)} classes)"
