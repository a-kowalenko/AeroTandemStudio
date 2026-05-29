from .camera_resolution import (
    detect_camera_type_from_classify_fn,
    handcam_series_is_plausible,
    infer_camera_type_from_form_data,
    infer_camera_type_from_kunde,
)
from .schemas import ClassificationResult
from .series_analyzer import (
    HANDCAM_PREVIEW_CATEGORIES,
    OUTSIDE_PREVIEW_CATEGORIES,
    PREVIEW_CATEGORIES,
    PREVIEW_CATEGORY_LABELS,
    analyze_photo_series,
    get_preview_categories,
    get_preview_category_labels,
)

__all__ = [
    "SkydivePhotoAI",
    "ClassificationResult",
    "HANDCAM_PROMPTS",
    "OUTSIDE_PROMPTS",
    "HANDCAM_PREVIEW_CATEGORIES",
    "OUTSIDE_PREVIEW_CATEGORIES",
    "PREVIEW_CATEGORIES",
    "PREVIEW_CATEGORY_LABELS",
    "analyze_photo_series",
    "get_preview_categories",
    "get_preview_category_labels",
    "detect_camera_type_from_classify_fn",
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
