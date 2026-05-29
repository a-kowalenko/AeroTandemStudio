"""Hilfsfunktionen zur Ermittlung des Foto-Kamera-Typs (Handcam vs. Outside)."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

CameraType = str  # "handcam" | "outside"

HANDCAM_AUTO_OK_THRESHOLD = 0.75
CORE_MATCH_CATEGORIES = ("exit", "freefall")

CAMERA_TYPE_LABELS = {
    "handcam": "Handcam",
    "outside": "Outside",
}


def format_camera_type_label(camera_type: str) -> str:
    normalized = (camera_type or "").strip().lower()
    return CAMERA_TYPE_LABELS.get(normalized, normalized or "Unbekannt")


def infer_camera_type_from_kunde(
    kunde,
    *,
    product: str = "photo",
) -> Optional[CameraType]:
    """Leitet den Kamera-Typ aus QR-/Kunden-Produkten ab (unbezahlte Foto- oder Video-Produkte)."""
    if product == "video":
        return _infer_camera_type_from_kunde_video(kunde)
    return _infer_camera_type_from_kunde_photo(kunde)


def _infer_camera_type_from_kunde_photo(kunde) -> Optional[CameraType]:
    if kunde is None:
        return None
    handcam_foto = bool(getattr(kunde, "handcam_foto", False))
    outside_foto = bool(getattr(kunde, "outside_foto", False))
    handcam_unpaid = handcam_foto and not bool(getattr(kunde, "ist_bezahlt_handcam_foto", False))
    outside_unpaid = outside_foto and not bool(getattr(kunde, "ist_bezahlt_outside_foto", False))

    if handcam_unpaid and not outside_unpaid:
        return "handcam"
    if outside_unpaid and not handcam_unpaid:
        return "outside"
    if handcam_unpaid and outside_unpaid:
        return None
    return None


def _infer_camera_type_from_kunde_video(kunde) -> Optional[CameraType]:
    if kunde is None:
        return None
    handcam_video = bool(getattr(kunde, "handcam_video", False))
    outside_video = bool(getattr(kunde, "outside_video", False))
    handcam_unpaid = handcam_video and not bool(getattr(kunde, "ist_bezahlt_handcam_video", False))
    outside_unpaid = outside_video and not bool(getattr(kunde, "ist_bezahlt_outside_video", False))

    if handcam_unpaid and not outside_unpaid:
        return "handcam"
    if outside_unpaid and not handcam_unpaid:
        return "outside"
    if handcam_unpaid and outside_unpaid:
        return None
    return None


def infer_camera_type_from_form_data(
    form_data: dict,
    *,
    product: str = "photo",
) -> Optional[CameraType]:
    """Leitet den Kamera-Typ aus aktuellen Formularwerten ab."""
    if product == "video":
        return _infer_camera_type_from_form_data_video(form_data)
    return _infer_camera_type_from_form_data_photo(form_data)


def _infer_camera_type_from_form_data_photo(form_data: dict) -> Optional[CameraType]:
    handcam_unpaid = bool(form_data.get("handcam_foto")) and not bool(form_data.get("ist_bezahlt_handcam_foto"))
    outside_unpaid = bool(form_data.get("outside_foto")) and not bool(form_data.get("ist_bezahlt_outside_foto"))

    if handcam_unpaid and not outside_unpaid:
        return "handcam"
    if outside_unpaid and not handcam_unpaid:
        return "outside"
    if handcam_unpaid and outside_unpaid:
        mode = form_data.get("video_mode")
        if mode in ("handcam", "outside"):
            return mode
        return None

    mode = form_data.get("video_mode")
    if mode in ("handcam", "outside"):
        if handcam_unpaid or outside_unpaid:
            return mode
    return None


def _infer_camera_type_from_form_data_video(form_data: dict) -> Optional[CameraType]:
    handcam_unpaid = bool(form_data.get("handcam_video")) and not bool(
        form_data.get("ist_bezahlt_handcam_video")
    )
    outside_unpaid = bool(form_data.get("outside_video")) and not bool(
        form_data.get("ist_bezahlt_outside_video")
    )

    if handcam_unpaid and not outside_unpaid:
        return "handcam"
    if outside_unpaid and not handcam_unpaid:
        return "outside"
    if handcam_unpaid and outside_unpaid:
        mode = form_data.get("video_mode")
        if mode in ("handcam", "outside"):
            return mode
        return None

    mode = form_data.get("video_mode")
    if mode in ("handcam", "outside"):
        if handcam_unpaid or outside_unpaid:
            return mode
    return None


def series_has_core_match(
    grouped_candidates: Dict[str, List[dict]],
    *,
    threshold: float = HANDCAM_AUTO_OK_THRESHOLD,
) -> bool:
    """True wenn exit oder freefall mit Confidence über Schwellwert gefunden wurde."""
    for category in CORE_MATCH_CATEGORIES:
        for candidate in grouped_candidates.get(category, []):
            if float(candidate.get("score", 0.0)) > threshold:
                return True
    return False


def handcam_series_is_plausible(grouped_candidates: Dict[str, List[dict]]) -> bool:
    """Abwärtskompatibel – prüft Preview-Kandidaten auf exit/freefall."""
    return series_has_core_match(grouped_candidates)


def detect_camera_type_from_classify_fn(
    sample_paths: List[str],
    classify_fn: Callable[[str, str], object],
    *,
    sample_limit: int = 15,
) -> Optional[CameraType]:
    """Dual-Model-Score: beide ONNX-Modelle auf Stichprobe, höhere Gesamt-Confidence gewinnt."""
    from .classifier import detect_camera_type_from_samples

    detected = detect_camera_type_from_samples(
        sample_paths,
        classify_fn,
        sample_limit=sample_limit,
    )
    if detected:
        return detected

    # Fallback: ein Modell liefert plausible Kernphasen
    from .series_analyzer import get_preview_categories, analyze_photo_series

    indexed = [(i, p) for i, p in enumerate(sample_paths[:sample_limit])]
    if not indexed:
        return None

    for camera_type in ("handcam", "outside"):
        grouped = analyze_photo_series(
            indexed,
            camera_type,
            classify_fn,
            min_confidence=HANDCAM_AUTO_OK_THRESHOLD,
            target_categories=get_preview_categories(camera_type),
            use_sampling=False,
            worker_count=1,
        )
        if series_has_core_match(grouped):
            return camera_type
    return None
