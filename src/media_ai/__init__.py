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
    "VideoAnalyzer",
    "VideoAnalysisResult",
    "build_project_dict",
    "analysis_to_project_clip",
    "smooth_phase_labels",
    "enforce_phase_sequence",
    "find_anchor_run",
    "get_phase_order",
]

_LAZY_IMPORTS = {
    "SkydivePhotoAI": (".classifier", "SkydivePhotoAI"),
    "HANDCAM_PROMPTS": (".classifier", "HANDCAM_PROMPTS"),
    "OUTSIDE_PROMPTS": (".classifier", "OUTSIDE_PROMPTS"),
    "VideoAnalyzer": (".video_analyzer", "VideoAnalyzer"),
    "VideoAnalysisResult": (".video_analyzer", "VideoAnalysisResult"),
    "build_project_dict": (".video_analyzer", "build_project_dict"),
    "analysis_to_project_clip": (".video_analyzer", "analysis_to_project_clip"),
    "smooth_phase_labels": (".video_analyzer", "smooth_phase_labels"),
    "enforce_phase_sequence": (".video_analyzer", "enforce_phase_sequence"),
    "find_anchor_run": (".video_analyzer", "find_anchor_run"),
    "get_phase_order": (".video_analyzer", "get_phase_order"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_name, attr_name = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_name, __name__)
        return getattr(module, attr_name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
