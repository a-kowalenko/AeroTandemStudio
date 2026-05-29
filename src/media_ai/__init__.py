from .camera_resolution import (
    handcam_series_is_plausible,
    infer_camera_type_from_form_data,
    infer_camera_type_from_kunde,
)
from .schemas import ClassificationResult
from .series_analyzer import PREVIEW_CATEGORIES, PREVIEW_CATEGORY_LABELS, analyze_photo_series

__all__ = [
    "SkydivePhotoAI",
    "ClassificationResult",
    "HANDCAM_PROMPTS",
    "OUTSIDE_PROMPTS",
    "PREVIEW_CATEGORIES",
    "PREVIEW_CATEGORY_LABELS",
    "analyze_photo_series",
    "handcam_series_is_plausible",
    "infer_camera_type_from_form_data",
    "infer_camera_type_from_kunde",
]


def __getattr__(name: str):
    if name == "SkydivePhotoAI":
        from .classifier import SkydivePhotoAI

        return SkydivePhotoAI
    if name == "HANDCAM_PROMPTS":
        from .classifier import HANDCAM_PROMPTS

        return HANDCAM_PROMPTS
    if name == "OUTSIDE_PROMPTS":
        from .classifier import OUTSIDE_PROMPTS

        return OUTSIDE_PROMPTS
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
