from __future__ import annotations

import itertools
import json
import math
import os
import re
import threading
from typing import Dict, List, Literal, Optional, Union

import numpy as np
import onnxruntime as ort
from PIL import Image

from src.utils.constants import BASE_DIR

from .schemas import ClassificationResult

CameraType = Literal["handcam", "outside"]
SUPPORTED_CAMERAS = ("handcam", "outside")

HANDCAM_PROMPTS: Dict[str, str] = {}
OUTSIDE_PROMPTS: Dict[str, str] = {}

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_FOLDER_PREFIX_RE = re.compile(r"^\d+_")


def _strip_class_prefix(name: str) -> str:
    """'08_freefall' -> 'freefall', 'freefall' bleibt 'freefall'."""
    return _FOLDER_PREFIX_RE.sub("", name, count=1)


def _load_class_names(camera_type: str) -> List[str]:
    json_path = os.path.join(BASE_DIR, "models", f"classifier_{camera_type}_classes.json")
    if os.path.isfile(json_path):
        with open(json_path, encoding="utf-8") as handle:
            raw = json.load(handle)
        if isinstance(raw, list) and raw:
            return [str(name) for name in raw]

    checkpoint_path = os.path.join(BASE_DIR, "models", f"{camera_type}_base.pth")
    if os.path.isfile(checkpoint_path):
        import torch

        checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
        names = checkpoint.get("class_names")
        if isinstance(names, list) and names:
            return [str(name) for name in names]

    raise FileNotFoundError(
        f"Keine Klassenliste für '{camera_type}' gefunden. "
        f"Erwartet: {json_path} oder Checkpoint mit class_names."
    )


class PhotoAIWorkerPool:
    """Thread-lokale ONNX-Sessions für parallele Inferenz (ein Kamera-Typ)."""

    def __init__(self, parent: "SkydivePhotoAI", camera_type: str, worker_count: int) -> None:
        count = max(1, worker_count)
        self._parent = parent
        self._camera_type = parent._normalize_camera_type(camera_type)
        self._sessions = [parent._create_session(self._camera_type) for _ in range(count)]
        self._session_cycle = itertools.cycle(range(count))
        self._assign_lock = threading.Lock()
        self._thread_local = threading.local()

    def _session_for_thread(self) -> ort.InferenceSession:
        session_idx = getattr(self._thread_local, "session_idx", None)
        if session_idx is None:
            with self._assign_lock:
                session_idx = next(self._session_cycle)
            self._thread_local.session_idx = session_idx
        return self._sessions[session_idx]

    def classify_image(
        self,
        image_or_path: Union[str, Image.Image],
        camera_type: str,
    ) -> ClassificationResult:
        del camera_type
        return self._parent.classify_image_with_session(
            self._session_for_thread(),
            image_or_path,
            self._camera_type,
        )


class SkydivePhotoAI:
    INPUT_NAME = "input"
    OUTPUT_NAME = "output"

    def __init__(self, providers: List[str] | None = None, hf_token: Optional[str] = None) -> None:
        del hf_token

        self.providers = providers or self._default_providers()
        self._model_paths: Dict[str, str] = {}
        self._class_names_raw: Dict[str, List[str]] = {}
        self._class_names: Dict[str, List[str]] = {}

        for camera_type in SUPPORTED_CAMERAS:
            onnx_path = os.path.join(BASE_DIR, "models", f"classifier_{camera_type}.onnx")
            if not os.path.isfile(onnx_path):
                raise FileNotFoundError(
                    f"ONNX für '{camera_type}' nicht gefunden: {onnx_path}\n"
                    "Bitte train_photo_classifier.py ausführen."
                )
            self._model_paths[camera_type] = onnx_path
            raw_names = _load_class_names(camera_type)
            self._class_names_raw[camera_type] = raw_names
            self._class_names[camera_type] = [_strip_class_prefix(n) for n in raw_names]

        self.session = self._create_session("handcam")
        print(f"[MediaAI] Foto-Klassifikatoren geladen ({self.providers[0]}).")

    @staticmethod
    def _default_providers() -> List[str]:
        available = set(ort.get_available_providers())
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _create_session(self, camera_type: str) -> ort.InferenceSession:
        cam = self._normalize_camera_type(camera_type)
        return ort.InferenceSession(self._model_paths[cam], providers=self.providers)

    def create_worker_pool(self, worker_count: int, camera_type: str) -> PhotoAIWorkerPool:
        return PhotoAIWorkerPool(self, camera_type, worker_count)

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits)
        exp_values = np.exp(shifted)
        return exp_values / np.sum(exp_values)

    @staticmethod
    def _normalize_camera_type(camera_type: str) -> CameraType:
        normalized = (camera_type or "").strip().lower()
        if normalized in SUPPORTED_CAMERAS:
            return normalized  # type: ignore[return-value]
        raise ValueError(f"camera_type must be 'handcam' or 'outside', got: {camera_type!r}")

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        image = image.convert("RGB").resize((224, 224), Image.BILINEAR)
        arr = np.asarray(image, dtype=np.float32) / 255.0
        arr = (arr - IMAGENET_MEAN) / IMAGENET_STD
        arr = np.transpose(arr, (2, 0, 1))
        return np.expand_dims(arr, axis=0)

    def classify_image_with_session(
        self,
        session: ort.InferenceSession,
        image_or_path: Union[str, Image.Image],
        camera_type: str,
    ) -> ClassificationResult:
        cam = self._normalize_camera_type(camera_type)
        class_names = self._class_names[cam]

        image = image_or_path
        if isinstance(image_or_path, str):
            image = Image.open(image_or_path)
        if not isinstance(image, Image.Image):
            raise TypeError("image_or_path must be a file path or PIL.Image.Image")

        input_tensor = self._preprocess(image)
        outputs = session.run(
            [self.OUTPUT_NAME],
            {self.INPUT_NAME: input_tensor},
        )
        logits = np.asarray(outputs[0], dtype=np.float32).reshape(-1)
        probs = self._softmax(logits)

        scores: Dict[str, float] = {}
        for idx, class_name in enumerate(class_names):
            scores[class_name] = float(probs[idx])

        best_category = max(scores, key=scores.get)
        return ClassificationResult(
            category=best_category,
            confidence=scores[best_category],
            all_scores=scores,
        )

    def classify_image(
        self,
        image_or_path: Union[str, Image.Image],
        camera_type: str,
    ) -> ClassificationResult:
        cam = self._normalize_camera_type(camera_type)
        session = self._create_session(cam)
        return self.classify_image_with_session(session, image_or_path, cam)

    def analyze_image(
        self,
        image_or_path: Union[str, Image.Image],
        camera_type: str = "handcam",
    ) -> ClassificationResult:
        return self.classify_image(image_or_path, camera_type)


def detect_camera_type_from_samples(
    sample_paths: List[str],
    classify_fn,
    *,
    sample_limit: int = 15,
) -> Optional[str]:
    """
    Vergleicht Handcam- und Outside-Modell auf einer Stichprobe.
    Gewinnt der Kamera-Typ mit höherer Summe log(confidence).
    """
    if not sample_paths:
        return None

    stride = max(1, len(sample_paths) // sample_limit)
    paths = sample_paths[::stride][:sample_limit]

    handcam_score = 0.0
    outside_score = 0.0
    count = 0

    for path in paths:
        try:
            handcam_result = classify_fn(path, "handcam")
            outside_result = classify_fn(path, "outside")
            handcam_score += math.log(max(float(handcam_result.confidence), 1e-9))
            outside_score += math.log(max(float(outside_result.confidence), 1e-9))
            count += 1
        except Exception:
            continue

    if count == 0:
        return None
    return "handcam" if handcam_score >= outside_score else "outside"
