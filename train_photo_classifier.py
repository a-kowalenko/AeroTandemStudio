#!/usr/bin/env python3
"""
Trainiert EfficientNet-B0 auf Handcam- oder Outside-Fotos (13 Klassen) und exportiert ONNX.

Beispiel:
  python train_photo_classifier.py --camera handcam
  python train_photo_classifier.py --camera outside
  python train_photo_classifier.py --camera both
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, models, transforms

PROJECT_ROOT = Path(__file__).resolve().parent
MODELS_DIR = PROJECT_ROOT / "models"
TRAINING_ROOT = PROJECT_ROOT / "trainingsdata" / "photo"

EPOCHS = 12
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
VAL_FRACTION = 0.2
RANDOM_SEED = 42
EXPECTED_CLASSES = 13

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def build_transforms() -> transforms.Compose:
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(224),
        transforms.ToTensor(),
        transforms.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
    ])


def build_model(num_classes: int) -> nn.Module:
    try:
        weights = models.EfficientNet_B0_Weights.IMAGENET1K_V1
    except AttributeError:
        weights = "DEFAULT"
    model = models.efficientnet_b0(weights=weights)
    in_features = model.classifier[1].in_features
    model.classifier[1] = nn.Linear(in_features, num_classes)
    return model


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> tuple[float, float]:
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
) -> tuple[float, float]:
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
    """Export als einzelne ONNX-Datei (legacy exporter, ohne .onnx.data auf Windows)."""
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
    # PyTorch 2.x: dynamo=False + external_data=False vermeidet Opset-Downgrade und .onnx.data
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


def train_camera(camera: str) -> None:
    data_dir = TRAINING_ROOT / camera
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Trainingsdaten nicht gefunden: {data_dir}")

    weights_path = MODELS_DIR / f"{camera}_base.pth"
    onnx_path = MODELS_DIR / f"classifier_{camera}.onnx"
    classes_path = MODELS_DIR / f"classifier_{camera}_classes.json"

    random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n=== Training: {camera} ({device}) ===")

    transform = build_transforms()
    full_dataset = datasets.ImageFolder(root=str(data_dir), transform=transform)
    num_classes = len(full_dataset.classes)
    if num_classes != EXPECTED_CLASSES:
        print(
            f"Hinweis: {num_classes} Klassen gefunden (erwartet: {EXPECTED_CLASSES}). "
            f"Klassen: {full_dataset.classes}"
        )

    val_size = max(1, int(len(full_dataset) * VAL_FRACTION))
    train_size = len(full_dataset) - val_size
    train_set, val_set = random_split(
        full_dataset,
        [train_size, val_size],
        generator=torch.Generator().manual_seed(RANDOM_SEED),
    )

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False, num_workers=0)

    print(f"Samples: {len(full_dataset)} (Train: {train_size}, Val: {val_size})")
    print(f"Klassen: {full_dataset.classes}")

    model = build_model(num_classes).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)

    best_val_acc = 0.0
    best_state = None

    for epoch in range(1, EPOCHS + 1):
        train_loss, train_acc = train_one_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = evaluate(model, val_loader, criterion, device)
        print(
            f"Epoch {epoch:02d}/{EPOCHS} | "
            f"train loss={train_loss:.4f} acc={train_acc:.3f} | "
            f"val loss={val_loss:.4f} acc={val_acc:.3f}"
        )
        if val_acc >= best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    if best_state is not None:
        model.load_state_dict(best_state)

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint = {
        "model_state_dict": model.state_dict(),
        "class_names": full_dataset.classes,
        "num_classes": num_classes,
        "arch": "efficientnet_b0",
        "camera": camera,
    }
    torch.save(checkpoint, weights_path)
    print(f"PyTorch-Gewichte: {weights_path}")

    save_classes_json(full_dataset.classes, classes_path)
    export_onnx(model, onnx_path)
    print(f"Training abgeschlossen: {camera}")


def main() -> None:
    parser = argparse.ArgumentParser(description="EfficientNet-B0 Foto-Klassifikator trainieren")
    parser.add_argument(
        "--camera",
        choices=("handcam", "outside", "both"),
        default="both",
        help="Welches Modell trainiert werden soll (Standard: both)",
    )
    args = parser.parse_args()

    cameras = ("handcam", "outside") if args.camera == "both" else (args.camera,)
    for camera in cameras:
        train_camera(camera)


if __name__ == "__main__":
    main()
