#!/usr/bin/env python3
"""
Trainiert EfficientNet-B0 auf Handcam- oder Outside-Fotos und exportiert ONNX.

Full-Training (von ImageNet):
  python train_photo_classifier.py --camera handcam
  python train_photo_classifier.py --camera both

Fine-Tuning (vom bestehenden Checkpoint):
  python train_photo_classifier.py --camera handcam --finetune
  python train_photo_classifier.py --camera both --finetune --epochs 8 --lr 1e-4
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, models, transforms

from src.media_ai.photo_training import (
    AlignedImageDataset,
    build_class_layout,
    list_dataset_folders,
    validate_finetune_class_set,
)

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"
TRAINING_ROOT = PROJECT_ROOT / "trainingsdata" / "photo"

DEFAULT_EPOCHS_FULL = 12
DEFAULT_EPOCHS_FINETUNE = 6
DEFAULT_LR_FULL = 1e-3
DEFAULT_LR_FINETUNE = 1e-4
DEFAULT_BATCH_SIZE = 32
DEFAULT_VAL_FRACTION = 0.2
DEFAULT_SEED = 42
EXPECTED_CLASSES = 13

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


@dataclass
class TrainConfig:
    camera: str
    finetune: bool = False
    checkpoint: Optional[Path] = None
    epochs: int = DEFAULT_EPOCHS_FULL
    lr: float = DEFAULT_LR_FULL
    batch_size: int = DEFAULT_BATCH_SIZE
    val_fraction: float = DEFAULT_VAL_FRACTION
    seed: int = DEFAULT_SEED
    freeze_backbone: bool = False
    augment: bool = False
    allow_missing_folders: bool = False

    @classmethod
    def for_camera(cls, camera: str, args: argparse.Namespace) -> "TrainConfig":
        finetune = bool(args.finetune)

        if args.no_freeze_backbone:
            freeze_backbone = False
        elif args.freeze_backbone:
            freeze_backbone = True
        else:
            freeze_backbone = finetune

        checkpoint = (
            Path(args.checkpoint)
            if args.checkpoint
            else MODELS_DIR / f"{camera}_base.pth"
        )

        return cls(
            camera=camera,
            finetune=finetune,
            checkpoint=checkpoint,
            epochs=args.epochs
            if args.epochs is not None
            else (DEFAULT_EPOCHS_FINETUNE if finetune else DEFAULT_EPOCHS_FULL),
            lr=args.lr
            if args.lr is not None
            else (DEFAULT_LR_FINETUNE if finetune else DEFAULT_LR_FULL),
            batch_size=args.batch_size or DEFAULT_BATCH_SIZE,
            val_fraction=args.val_fraction
            if args.val_fraction is not None
            else DEFAULT_VAL_FRACTION,
            seed=args.seed if args.seed is not None else DEFAULT_SEED,
            freeze_backbone=freeze_backbone,
            augment=finetune and not args.no_augment,
            allow_missing_folders=bool(args.allow_missing_folders),
        )


def build_transforms(*, augment: bool) -> transforms.Compose:
    if augment:
        return transforms.Compose([
            transforms.RandomResizedCrop(224, scale=(0.85, 1.0)),
            transforms.RandomHorizontalFlip(),
            transforms.ToTensor(),
            transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ])
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def build_model(num_classes: int, *, pretrained: bool = True) -> nn.Module:
    weights = None
    if pretrained:
        try:
            weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
        except AttributeError:
            weights = "DEFAULT"
    model = models.efficientnet_b0(weights=weights)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, num_classes)
    return model


def load_checkpoint(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(
            f"Checkpoint nicht gefunden: {path}\n"
            "Für Fine-Tuning zuerst ein Full-Training ohne --finetune ausführen."
        )
    return torch.load(path, map_location="cpu", weights_only=False)


def load_model_from_checkpoint(
    checkpoint: dict,
    device: torch.device,
) -> Tuple[nn.Module, List[str]]:
    class_names = list(checkpoint.get("class_names") or [])
    num_classes = int(checkpoint.get("num_classes") or len(class_names))
    if not class_names or num_classes != len(class_names):
        raise ValueError("Checkpoint enthält keine gültige class_names-Liste.")

    arch = str(checkpoint.get("arch") or "efficientnet_b0")
    if arch != "efficientnet_b0":
        raise ValueError(f"Nicht unterstützte Architektur im Checkpoint: {arch}")

    model = build_model(num_classes, pretrained=False)
    state = checkpoint.get("model_state_dict")
    if state is None:
        raise ValueError("Checkpoint enthält kein model_state_dict.")
    model.load_state_dict(state)
    return model.to(device), class_names


def backup_model_artifacts(camera: str) -> None:
    for pattern in (
        f"classifier_{camera}.onnx",
        f"{camera}_base.pth",
        f"classifier_{camera}_classes.json",
    ):
        path = MODELS_DIR / pattern
        if path.is_file():
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
            print(f"Backup: {backup}")


def build_full_train_dataset(
    data_dir: Path,
    transform,
    *,
    allow_missing_folders: bool = False,
) -> Tuple[AlignedImageDataset, List[str]]:
    """Full-Train: Klassenliste alphabetisch (wie ImageFolder)."""
    probe = datasets.ImageFolder(root=str(data_dir))
    class_names = list(probe.classes)
    layout = build_class_layout(
        data_dir,
        class_names,
        allow_missing_folders=allow_missing_folders,
    )
    return AlignedImageDataset(layout, transform=transform), class_names


def configure_optimizer(
    model: nn.Module,
    lr: float,
    *,
    freeze_backbone: bool,
) -> torch.optim.Optimizer:
    if freeze_backbone:
        for param in model.features.parameters():
            param.requires_grad = False
        return torch.optim.Adam(model.classifier.parameters(), lr=lr)

    return torch.optim.Adam(
        [
            {"params": model.features.parameters(), "lr": lr * 0.1},
            {"params": model.classifier.parameters(), "lr": lr},
        ]
    )


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> Tuple[float, float]:
    model.train()
    running_loss = 0.0
    correct = 0
    total = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        optimizer.zero_grad()
        outputs = model(images)
        loss = criterion(outputs, labels)
        loss.backward()
        optimizer.step()

        running_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return running_loss / max(total, 1), correct / max(total, 1)


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> Tuple[float, float]:
    model.eval()
    running_loss = 0.0
    correct = 0
    total = 0

    for images, labels in loader:
        images = images.to(device)
        labels = labels.to(device)
        outputs = model(images)
        loss = criterion(outputs, labels)

        running_loss += loss.item() * images.size(0)
        preds = outputs.argmax(dim=1)
        correct += (preds == labels).sum().item()
        total += labels.size(0)

    return running_loss / max(total, 1), correct / max(total, 1)


def export_onnx(model: nn.Module, onnx_path: Path) -> None:
    model.eval().cpu()
    dummy = torch.randn(1, 3, 224, 224)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    export_kwargs = {
        "input_names": ["input"],
        "output_names": ["output"],
        "opset_version": 17,
        "dynamic_axes": None,
        "export_params": True,
        "do_constant_folding": True,
    }
    try:
        torch.onnx.export(
            model,
            dummy,
            str(onnx_path),
            dynamo=False,
            external_data=False,
            **export_kwargs,
        )
    except TypeError:
        torch.onnx.export(model, dummy, str(onnx_path), **export_kwargs)

    print(f"ONNX exportiert: {onnx_path}")


def save_classes_json(class_names: list[str], json_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(class_names, indent=2), encoding="utf-8")
    print(f"Klassenliste gespeichert: {json_path}")


def train_camera(config: TrainConfig) -> None:
    camera = config.camera
    data_dir = TRAINING_ROOT / camera
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Trainingsdaten nicht gefunden: {data_dir}")

    weights_path = MODELS_DIR / f"{camera}_base.pth"
    onnx_path = MODELS_DIR / f"classifier_{camera}.onnx"
    classes_path = MODELS_DIR / f"classifier_{camera}_classes.json"

    random.seed(config.seed)
    torch.manual_seed(config.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    mode_label = "Fine-Tuning" if config.finetune else "Full-Training"
    print(f"\n=== {mode_label}: {camera} ({device}) ===")

    transform = build_transforms(augment=config.augment)
    parent_checkpoint: Optional[str] = None

    if config.finetune:
        checkpoint = load_checkpoint(config.checkpoint)
        class_names = list(checkpoint.get("class_names") or [])
        layout = validate_finetune_class_set(data_dir, class_names)
        full_dataset = AlignedImageDataset(layout, transform=transform)
        model, class_names = load_model_from_checkpoint(checkpoint, device)
        parent_checkpoint = str(config.checkpoint.resolve())
        print(f"Checkpoint: {config.checkpoint}")
    else:
        full_dataset, class_names = build_full_train_dataset(
            data_dir,
            transform,
            allow_missing_folders=config.allow_missing_folders,
        )
        model = build_model(len(class_names), pretrained=True).to(device)

    num_classes = len(class_names)
    if num_classes != EXPECTED_CLASSES:
        print(
            f"Hinweis: {num_classes} Klassen (erwartet oft {EXPECTED_CLASSES}). "
            f"Klassen: {class_names}"
        )

    val_size = max(1, int(len(full_dataset) * config.val_fraction))
    train_size = len(full_dataset) - val_size
    train_set, val_set = random_split(
        full_dataset,
        [train_size, val_size],
        generator=torch.Generator().manual_seed(config.seed),
    )

    train_loader = DataLoader(
        train_set,
        batch_size=config.batch_size,
        shuffle=True,
        num_workers=0,
    )
    val_loader = DataLoader(
        val_set,
        batch_size=config.batch_size,
        shuffle=False,
        num_workers=0,
    )

    print(f"Samples: {len(full_dataset)} (Train: {train_size}, Val: {val_size})")
    print(f"Klassen ({num_classes}): {class_names}")
    print(f"Ordner auf Platte: {sorted(list_dataset_folders(data_dir).keys())}")

    criterion = nn.CrossEntropyLoss()
    optimizer = configure_optimizer(
        model, config.lr, freeze_backbone=config.freeze_backbone
    )
    if config.freeze_backbone:
        print("Backbone eingefroren – trainiere nur den Klassifikationskopf.")

    best_val_acc = 0.0
    best_state = None

    for epoch in range(1, config.epochs + 1):
        train_loss, train_acc = train_one_epoch(
            model, train_loader, criterion, optimizer, device
        )
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        print(
            f"Epoch {epoch:02d}/{config.epochs} | "
            f"train loss={train_loss:.4f} acc={train_acc:.3f} | "
            f"val loss={val_loss:.4f} acc={val_acc:.3f}"
        )
        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    backup_model_artifacts(camera)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_out = {
        "model_state_dict": model.state_dict(),
        "class_names": class_names,
        "num_classes": num_classes,
        "arch": "efficientnet_b0",
        "camera": camera,
        "training_mode": "finetune" if config.finetune else "full",
        "parent_checkpoint": parent_checkpoint,
        "best_val_acc": float(best_val_acc),
        "epochs_run": config.epochs,
        "learning_rate": config.lr,
        "freeze_backbone": config.freeze_backbone,
    }
    torch.save(checkpoint_out, weights_path)
    print(f"PyTorch-Gewichte: {weights_path}")

    save_classes_json(class_names, classes_path)
    export_onnx(model, onnx_path)
    print(f"{mode_label} abgeschlossen: {camera} (beste Val-Acc: {best_val_acc:.3f})")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="EfficientNet-B0 Foto-Klassifikator trainieren oder fine-tunen"
    )
    parser.add_argument(
        "--camera",
        choices=("handcam", "outside", "both"),
        default="both",
        help="Welches Modell trainiert werden soll (Standard: both)",
    )
    parser.add_argument(
        "--finetune",
        action="store_true",
        help="Vom bestehenden Checkpoint fine-tunen statt ImageNet-Pretraining",
    )
    parser.add_argument(
        "--checkpoint",
        type=str,
        default=None,
        help="Pfad zum .pth-Checkpoint (Standard: models/{camera}_base.pth)",
    )
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--val-fraction", type=float, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--freeze-backbone",
        action="store_true",
        help="Nur classifier-Layer trainieren (Default bei --finetune)",
    )
    parser.add_argument(
        "--no-freeze-backbone",
        action="store_true",
        help="Auch features-Layer trainieren (differenzierte LRs)",
    )
    parser.add_argument(
        "--no-augment",
        action="store_true",
        help="Keine Augmentation (CenterCrop; Standard bei Full-Train)",
    )
    parser.add_argument(
        "--allow-missing-folders",
        action="store_true",
        help="Fehlende Klassen-Ordner überspringen (nur ohne --finetune)",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    cameras = ("handcam", "outside") if args.camera == "both" else (args.camera,)
    for camera in cameras:
        config = TrainConfig.for_camera(camera, args)
        train_camera(config)


if __name__ == "__main__":
    main()
