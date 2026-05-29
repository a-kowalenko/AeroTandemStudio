from __future__ import annotations

import itertools
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

HANDCAM_CLASS_NAMES = (
    "plane",
    "door",
    "exit",
    "freefall",
    "deployment",
    "canopy",
    "landing",
    "final",
)

# Abwärtskompatibel für Imports (kein CLIP-Prompt-Set mehr)
HANDCAM_PROMPTS: Dict[str, str] = {}
OUTSIDE_PROMPTS: Dict[str, str] = {}

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
_FOLDER_PREFIX_RE = re.compile(r"^\d+_")


def _strip_class_prefix(name: str) -> str:
    """'3_freefall' -> 'freefall', 'freefall' bleibt 'freefall'."""
    return _FOLDER_PREFIX_RE.sub("", name, count=1)


class PhotoAIWorkerPool:
    """Thread-lokale ONNX-Sessions für parallele Inferenz."""

    def __init__(self, parent: "SkydivePhotoAI", worker_count: int) -> None:
        count = max(1, worker_count)
        self._parent = parent
        self._sessions = [parent._create_session() for _ in range(count)]
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
        return self._parent.classify_image_with_session(
            self._session_for_thread(),
            image_or_path,
            camera_type,
        )


class SkydivePhotoAI:
    ONNX_FILENAME = "classifier_handcam.onnx"
    INPUT_NAME = "input"
    OUTPUT_NAME = "output"

    def __init__(self, providers: List[str] | None = None, hf_token: Optional[str] = None) -> None:
        del hf_token  # nicht mehr benötigt (lokales ONNX)

        onnx_path = os.path.join(BASE_DIR, "models", self.ONNX_FILENAME)
        if not os.path.isfile(onnx_path):
            raise FileNotFoundError(
                f"Handcam-ONNX nicht gefunden: {onnx_path}\n"
                "Bitte zuerst train_handcam.py ausführen."
            )
        self._model_path = onnx_path
        self._class_names = list(HANDCAM_CLASS_NAMES)
        self.providers = providers or self._default_providers()
        self.session = self._create_session()
        print(f"[MediaAI] Handcam EfficientNet ONNX geladen ({self.providers[0]}).")

    @staticmethod
    def _default_providers() -> List[str]:
        available = set(ort.get_available_providers())
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _create_session(self) -> ort.InferenceSession:
        return ort.InferenceSession(self._model_path, providers=self.providers)

    def create_worker_pool(self, worker_count: int) -> PhotoAIWorkerPool:
        return PhotoAIWorkerPool(self, worker_count)

    @staticmethod
    def _softmax(logits: np.ndarray) -> np.ndarray:
        shifted = logits - np.max(logits)
        exp_values = np.exp(shifted)
        return exp_values / np.sum(exp_values)

    @staticmethod
    def _normalize_camera_type(camera_type: str) -> CameraType:
        normalized = (camera_type or "").strip().lower()
        if normalized == "handcam":
            return "handcam"
        if normalized == "outside":
            raise NotImplementedError(
                "Outside-Klassifikation ist noch nicht implementiert (nur handcam)."
            )
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
        self._normalize_camera_type(camera_type)

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
        for idx, class_name in enumerate(self._class_names):
            label = _strip_class_prefix(class_name)
            scores[label] = float(probs[idx])

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
        """
        Klassifiziert ein Handcam-Bild (plane, exit, freefall, …) mit lokalem EfficientNet-ONNX.
        """
        return self.classify_image_with_session(self.session, image_or_path, camera_type)

    def analyze_image(
        self,
        image_or_path: Union[str, Image.Image],
        camera_type: str = "handcam",
    ) -> ClassificationResult:
        """Abwärtskompatibel – delegiert an classify_image."""
        return self.classify_image(image_or_path, camera_type)
