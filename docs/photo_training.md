# Foto-Klassifikator trainieren

Die KI-Fotoerkennung nutzt ONNX-Modelle unter `models/` (`classifier_handcam.onnx`, `classifier_outside.onnx`). Trainingsdaten liegen in:

```
trainingsdata/photo/handcam/<klassen_ordner>/*.jpg
trainingsdata/photo/outside/<klassen_ordner>/*.jpg
```

Ordnernamen können Präfixe haben (z. B. `08_freefall`); die Semantik entspricht dem Namen ohne Ziffernpräfix.

## Full-Training (erstes Training oder neue Klassen)

Startet von ImageNet-Gewichten, 12 Epochen, LR `1e-3`, CenterCrop:

```powershell
python train_photo_classifier.py --camera handcam
python train_photo_classifier.py --camera both
```

Erzeugt u. a.:

- `models/{camera}_base.pth` – PyTorch-Checkpoint inkl. `class_names`
- `models/classifier_{camera}.onnx` – Modell für die App
- `models/classifier_{camera}_classes.json`

## Fine-Tuning (neue Bilder in bestehenden Klassen)

Lädt den bestehenden Checkpoint, 6 Epochen, LR `1e-4`, leichte Augmentation, Backbone standardmäßig eingefroren:

```powershell
python train_photo_classifier.py --camera handcam --finetune
python train_photo_classifier.py --camera outside --finetune --epochs 8 --lr 5e-5
```

Optionen:

| Flag | Bedeutung |
|------|-----------|
| `--checkpoint PATH` | Anderes `.pth` (Standard: `models/{camera}_base.pth`) |
| `--no-freeze-backbone` | Auch Feature-Layer mittrainieren |
| `--no-augment` | Nur CenterCrop |
| `--epochs`, `--lr`, `--batch-size` | Hyperparameter überschreiben |

Vor dem Überschreiben werden bestehende ONNX/PTH-Dateien nach `.bak` gesichert.

**Wichtig:** Fine-Tuning erlaubt **keine neuen Klassen-Ordner**. Dafür Full-Training ohne `--finetune` ausführen.

Die Klassen-Reihenfolge im Checkpoint ist maßgeblich – Labels werden danach gemappt, nicht nach beliebiger Ordner-Reihenfolge.

## Nach dem Training

1. AeroTandemStudio neu starten (ONNX wird beim Start geladen).
2. KI-Foto-Review mit echten Sprüngen testen.
3. Video-KI nutzt dieselben Foto-ONNX-Dateien für Frame-Klassifikation.

## Wrapper

`train_handcam.py` delegiert an `train_photo_classifier.py` und setzt standardmäßig `--camera handcam` (inkl. `--finetune` wenn übergeben).
