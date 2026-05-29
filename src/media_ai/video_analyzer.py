"""Video-Klassifikation per ONNX (1 Frame/s) mit Phasen-Glättung."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from .classifier import SkydivePhotoAI, _strip_class_prefix

_FOLDER_PREFIX_RE = re.compile(r"^\d+_")
UNKNOWN_PHASE = "unknown"
DEFAULT_SAMPLE_INTERVAL = 1.0
DEFAULT_MIN_STABLE_SECONDS = 2
DEFAULT_UNKNOWN_CONFIDENCE = 0.30

IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


@dataclass
class VideoAnalysisProgress:
    """Fortschritt über alle Videos (für Lade-Dialog)."""

    videos_done: int
    videos_total: int
    seconds_done: float
    seconds_total: float
    current_video: str


@dataclass
class VideoAnalysisResult:
    """Ergebnis der KI-Analyse für einen einzelnen Videoclip."""

    path: str
    duration_sec: float
    timeline: Dict[float, str] = field(default_factory=dict)
    dominant_phase: str = UNKNOWN_PHASE
    suggested_start_sec: float = 0.0
    suggested_end_sec: float = 0.0
  # suggested_end_sec ist exklusiv (FFmpeg -t = end - start)


def normalize_phase_name(raw: str) -> str:
    """'08_freefall' -> 'freefall'; leer -> 'unknown'."""
    name = (raw or "").strip()
    if not name:
        return UNKNOWN_PHASE
    return _strip_class_prefix(name) if _FOLDER_PREFIX_RE.match(name) else name


def smooth_phase_labels(labels: List[str], min_stable_seconds: int = DEFAULT_MIN_STABLE_SECONDS) -> List[str]:
    """
    Glättet kurze Ausreißer: Eine Phase muss mindestens ``min_stable_seconds``
    aufeinanderfolgende Samples halten, sonst wird sie durch die dominante Umgebung ersetzt.
    """
    if not labels or min_stable_seconds <= 1:
        return list(labels)

    result = list(labels)
    changed = True
    while changed:
        changed = False
        i = 0
        while i < len(result):
            j = i
            while j < len(result) and result[j] == result[i]:
                j += 1
            run_len = j - i
            if run_len < min_stable_seconds:
                replacement = _replacement_for_short_run(result, i, j)
                if any(result[k] != replacement for k in range(i, j)):
                    for k in range(i, j):
                        result[k] = replacement
                    changed = True
            i = j
    return result


def _replacement_for_short_run(labels: List[str], start: int, end: int) -> str:
    left = labels[start - 1] if start > 0 else None
    right = labels[end] if end < len(labels) else None
    if left and right:
        return left if left == right else left
    if left:
        return left
    if right:
        return right
    return labels[start]


def _dominant_phase(labels: List[str]) -> str:
    filtered = [p for p in labels if p and p != UNKNOWN_PHASE]
    if not filtered:
        return UNKNOWN_PHASE
    return Counter(filtered).most_common(1)[0][0]


def _suggested_trim_from_dominant(
    keyed_labels: List[Tuple[float, str]],
    dominant: str,
    duration_sec: float,
) -> Tuple[float, float]:
    """Start/Ende (exklusiv) aus längster zusammenhängender Dominant-Phase."""
    if not keyed_labels or dominant == UNKNOWN_PHASE:
        return 0.0, max(duration_sec, keyed_labels[-1][0] if keyed_labels else 0.0)

    best_start_idx = 0
    best_len = 0
    cur_start = 0
    cur_len = 0

    for idx, (_t, phase) in enumerate(keyed_labels):
        if phase == dominant:
            if cur_len == 0:
                cur_start = idx
            cur_len += 1
            if cur_len > best_len:
                best_len = cur_len
                best_start_idx = cur_start
        else:
            cur_len = 0

    if best_len == 0:
        return 0.0, duration_sec

    first_key = keyed_labels[best_start_idx][0]
    last_key = keyed_labels[best_start_idx + best_len - 1][0]
    start_sec = max(0.0, first_key - DEFAULT_SAMPLE_INTERVAL)
    end_sec = min(duration_sec, last_key)
    if end_sec <= start_sec:
        end_sec = min(duration_sec, start_sec + DEFAULT_SAMPLE_INTERVAL)
    return start_sec, end_sec


def probe_video_duration_sec(video_path: str) -> float:
    """Ermittelt die Videolänge in Sekunden (für Gesamt-Fortschritt)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        if fps > 0 and frame_count > 0:
            return max(0.0, frame_count / fps)
        return VideoAnalyzer._probe_duration(cap)
    finally:
        cap.release()


class VideoAnalyzer:
    """Analysiert Videoclips mit dem trainierten EfficientNet-ONNX-Modell."""

    def __init__(
        self,
        camera_type: str,
        *,
        ai: Optional[SkydivePhotoAI] = None,
        sample_interval_seconds: float = DEFAULT_SAMPLE_INTERVAL,
        min_stable_seconds: int = DEFAULT_MIN_STABLE_SECONDS,
        unknown_confidence_threshold: float = DEFAULT_UNKNOWN_CONFIDENCE,
    ) -> None:
        self.camera_type = (camera_type or "handcam").strip().lower()
        self._ai = ai or SkydivePhotoAI()
        self.sample_interval_seconds = max(0.1, float(sample_interval_seconds))
        self.min_stable_seconds = max(1, int(min_stable_seconds))
        self.unknown_confidence_threshold = float(unknown_confidence_threshold)
        self._session = self._ai._create_session(self.camera_type)

    def analyze_video(
        self,
        video_path: str,
        *,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> VideoAnalysisResult:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Video konnte nicht geöffnet werden: {video_path}")

        try:
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration_sec = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
            if duration_sec <= 0:
                duration_sec = self._probe_duration(cap)

            sample_times, raw_labels, confidences = self._sample_and_classify(
                cap, duration_sec, on_progress=on_progress
            )
        finally:
            cap.release()

        smoothed = smooth_phase_labels(raw_labels, self.min_stable_seconds)
        keyed = list(zip(sample_times, smoothed))
        timeline = {float(t): phase for t, phase in keyed}
        dominant = _dominant_phase(smoothed)
        start_sec, end_sec = _suggested_trim_from_dominant(keyed, dominant, duration_sec)

        return VideoAnalysisResult(
            path=video_path,
            duration_sec=duration_sec,
            timeline=timeline,
            dominant_phase=dominant,
            suggested_start_sec=start_sec,
            suggested_end_sec=end_sec if end_sec > 0 else duration_sec,
        )

    def analyze_videos(
        self,
        video_paths: List[str],
        *,
        on_progress: Optional[Callable[[VideoAnalysisProgress], None]] = None,
    ) -> List[VideoAnalysisResult]:
        results: List[VideoAnalysisResult] = []
        total_videos = len(video_paths)
        if total_videos == 0:
            return results

        durations = [probe_video_duration_sec(path) for path in video_paths]
        total_seconds = sum(durations) or float(total_videos)
        seconds_before = 0.0

        def emit(videos_done: int, seconds_done: float, current_video: str) -> None:
            if on_progress:
                on_progress(
                    VideoAnalysisProgress(
                        videos_done=videos_done,
                        videos_total=total_videos,
                        seconds_done=min(seconds_done, total_seconds),
                        seconds_total=total_seconds,
                        current_video=current_video,
                    )
                )

        for idx, path in enumerate(video_paths):
            clip_duration = durations[idx] or 1.0
            emit(idx, seconds_before, path)

            def clip_progress(sample_done: int, sample_total: int, _detail: str) -> None:
                frac = sample_done / max(1, sample_total)
                emit(idx, seconds_before + frac * clip_duration, path)

            results.append(
                self.analyze_video(path, on_progress=clip_progress if on_progress else None)
            )
            seconds_before += clip_duration
            emit(idx + 1, seconds_before, path)

        return results

    def _sample_and_classify(
        self,
        cap,
        duration_sec: float,
        *,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> Tuple[List[float], List[str], List[float]]:
        sample_times: List[float] = []
        raw_labels: List[str] = []
        confidences: List[float] = []

        if duration_sec <= 0:
            return sample_times, raw_labels, confidences

        interval = self.sample_interval_seconds
        t = interval
        sample_index = 0
        estimated_samples = max(1, int(duration_sec / interval))

        while t <= duration_sec + 1e-6:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, (t - interval) * 1000.0))
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            label, confidence = self._classify_frame(frame)
            sample_times.append(round(t, 1))
            raw_labels.append(label)
            confidences.append(confidence)

            if on_progress:
                on_progress(sample_index + 1, estimated_samples, f"{t:.1f}s")
            sample_index += 1
            t += interval

        return sample_times, raw_labels, confidences

    def _classify_frame(self, frame_bgr: np.ndarray) -> Tuple[str, float]:
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        result = self._ai.classify_image_with_session(
            self._session, image, self.camera_type
        )
        phase = normalize_phase_name(result.category)
        if float(result.confidence) < self.unknown_confidence_threshold:
            phase = UNKNOWN_PHASE
        return phase, float(result.confidence)

    @staticmethod
    def _probe_duration(cap) -> float:
        ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        cap.set(cv2.CAP_PROP_POS_AVI_RATIO, 1.0)
        end_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
        if end_ms and end_ms > 0:
            return end_ms / 1000.0
        return ms / 1000.0 if ms else 0.0


def analysis_to_project_clip(
    result: VideoAnalysisResult,
    *,
    clip_id: Optional[str] = None,
    sample_interval: float = DEFAULT_SAMPLE_INTERVAL,
) -> dict:
    """Wandelt ein Analyseergebnis in einen Eintrag für das Review-JSON um."""
    import uuid

    from .phase_segments import timeline_to_phase_segments

    phase_segments = timeline_to_phase_segments(
        result.timeline,
        result.duration_sec,
        sample_interval=sample_interval,
    )

    return {
        "id": clip_id or str(uuid.uuid4()),
        "path": result.path,
        "duration_sec": round(result.duration_sec, 3),
        "dominant_phase": result.dominant_phase,
        "timeline": {str(k): v for k, v in sorted(result.timeline.items())},
        "phase_segments": phase_segments,
        "trim_start": round(result.suggested_start_sec, 1),
        "trim_end": round(result.suggested_end_sec, 1),
        "deleted": False,
    }


def build_project_dict(
    camera_type: str,
    analysis_results: List[VideoAnalysisResult],
    *,
    sample_interval: float = DEFAULT_SAMPLE_INTERVAL,
) -> dict:
    """Projekt-Dictionary für den Review-Dialog (Import-Reihenfolge)."""
    return {
        "version": 2,
        "camera_type": camera_type,
        "clips": [
            analysis_to_project_clip(r, sample_interval=sample_interval) for r in analysis_results
        ],
    }
