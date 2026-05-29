#!/usr/bin/env python3
"""
Trainiert EfficientNet-B0 auf Handcam-Fotos (8 Klassen) und exportiert ONNX für die GUI.

Erwartete Ordnerstruktur:
  trainingsdata/photo/handcam/0_plane
  trainingsdata/photo/handcam/1_door
  ...
  trainingsdata/photo/handcam/7_final

Ausgabe:
  models/handcam_base.pth      – PyTorch-Gewichte (für späteres Nachtrainieren)
  models/classifier_handcam.onnx – ONNX-Inferenz für Aero Tandem Studio
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from torchvision import datasets, models, transforms

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "trainingsdata" / "photo" / "handcam"
MODELS_DIR = PROJECT_ROOT / "models"
WEIGHTS_PATH = MODELS_DIR / "handcam_base.pth"
ONNX_PATH = MODELS_DIR / "classifier_handcam.onnx"

NUM_CLASSES = 8
EPOCHS = 12
BATCH_SIZE = 32
LEARNING_RATE = 1e-3
VAL_FRACTION = 0.2
RANDOM_SEED = 42

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
    model.eval().cpu()
    dummy = torch.randn(1, 3, 224, 224)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["input"],
        output_names=["output"],
        dynamic_axes=None,
        opset_version=12,
    )
    print(f"ONNX exportiert: {onnx_path}")


def main() -> None:
    if not DATA_DIR.is_dir():
        raise FileNotFoundError(
            f"Trainingsdaten nicht gefunden: {DATA_DIR}\n"
            "Bitte die 8 Klassenordner (0_plane … 7_final) anlegen."
        )

    random.seed(RANDOM_SEED)
    torch.manual_seed(RANDOM_SEED)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Gerät: {device}")

    transform = build_transforms()
    full_dataset = datasets.ImageFolder(root=str(DATA_DIR), transform=transform)
    if len(full_dataset.classes) != NUM_CLASSES:
        print(
            f"Hinweis: {len(full_dataset.classes)} Klassen gefunden "
            f"(erwartet: {NUM_CLASSES}). Klassen: {full_dataset.classes}"
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

    print(f"Samples gesamt: {len(full_dataset)} (Train: {train_size}, Val: {val_size})")
    print(f"Klassen (ImageFolder-Reihenfolge): {full_dataset.classes}")

    model = build_model(NUM_CLASSES).to(device)
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
        "num_classes": NUM_CLASSES,
        "arch": "efficientnet_b0",
    }
    torch.save(checkpoint, WEIGHTS_PATH)
    print(f"PyTorch-Gewichte gespeichert: {WEIGHTS_PATH}")

    export_onnx(model, ONNX_PATH)
    print("Training abgeschlossen.")


if __name__ == "__main__":
    main()
