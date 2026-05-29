"""Parallele Foto-Serien-Analyse mit Stride-Sampling und Nachbarschafts-Trigger."""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Tuple

HANDCAM_PREVIEW_CATEGORIES = (
    "boarding",
    "climb",
    "door",
    "exit",
    "freefall",
    "canopy",
    "landing",
    "final",
)

OUTSIDE_PREVIEW_CATEGORIES = (
    "boarding",
    "climb",
    "door",
    "exit",
    "freefall",
    "deployment",
    "landing",
    "final",
)

# Preview-Key -> Modell-Klassenname (nach Ordner-Prefix-Strip)
PREVIEW_CLASS_ALIASES: Dict[str, str] = {
    "final": "final_interview",
}

HANDCAM_PREVIEW_LABELS = {
    "boarding": "Boarding",
    "climb": "Steigflug",
    "door": "Tür",
    "exit": "Exit",
    "freefall": "Freifall",
    "canopy": "Schirmfahrt",
    "landing": "Landung",
    "final": "Final",
}

OUTSIDE_PREVIEW_LABELS = {
    "boarding": "Boarding",
    "climb": "Steigflug",
    "door": "Tür",
    "exit": "Exit",
    "freefall": "Freifall",
    "deployment": "Deployment",
    "landing": "Landung",
    "final": "Final",
}

# Abwärtskompatibel
PREVIEW_CATEGORIES = HANDCAM_PREVIEW_CATEGORIES
PREVIEW_CATEGORY_LABELS = HANDCAM_PREVIEW_LABELS

ClassifyFn = Callable[[str, str], object]


def get_preview_categories(camera_type: str) -> Tuple[str, ...]:
    normalized = (camera_type or "").strip().lower()
    if normalized == "outside":
        return OUTSIDE_PREVIEW_CATEGORIES
    return HANDCAM_PREVIEW_CATEGORIES


def get_preview_category_labels(camera_type: str) -> Dict[str, str]:
    normalized = (camera_type or "").strip().lower()
    if normalized == "outside":
        return dict(OUTSIDE_PREVIEW_LABELS)
    return dict(HANDCAM_PREVIEW_LABELS)


def preview_key_to_model_class(preview_key: str) -> str:
    return PREVIEW_CLASS_ALIASES.get(preview_key, preview_key)


def model_class_to_preview_key(model_class: str, target_categories: Tuple[str, ...]) -> Optional[str]:
    if model_class in target_categories:
        return model_class
    for preview_key, alias in PREVIEW_CLASS_ALIASES.items():
        if alias == model_class and preview_key in target_categories:
            return preview_key
    return None


def score_for_preview(scores: Dict[str, float], preview_key: str) -> float:
    model_key = preview_key_to_model_class(preview_key)
    return float(scores.get(model_key, 0.0))


def analyze_photo_series(
    indexed_paths: List[Tuple[int, str]],
    camera_type: str,
    classify_fn: ClassifyFn,
    *,
    min_confidence: float,
    max_candidates: int = 3,
    target_categories: Optional[Tuple[str, ...]] = None,
    use_sampling: bool = True,
    worker_count: int = 4,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Dict[str, List[dict]]:
    """
    Analysiert eine Foto-Serie parallel.

    use_sampling=True: jedes 2. Bild (0, 2, 4, …), Nachbar-Trigger bei
    max(all_scores) >= min_confidence - 0.10, finale Filterung >= min_confidence.

    Jedes Foto wird nur einer Ziel-Kategorie zugeordnet (KI-Hauptklasse bzw.
    beste Ziel-Kategorie), nicht in alle Kacheln mit hohem Einzel-Score.
    """
    if target_categories is None:
        target_categories = get_preview_categories(camera_type)

    grouped: Dict[str, List[dict]] = {c: [] for c in target_categories}
    total_available = len(indexed_paths)
    if total_available == 0:
        return grouped

    workers = max(1, min(worker_count, total_available))
    grouped_lock = threading.Lock()
    progress_lock = threading.Lock()
    completed = 0

    def _log(message: str) -> None:
        if on_log:
            on_log(message)

    def _best_score(result) -> float:
        scores = getattr(result, "all_scores", None) or {}
        if not scores:
            return 0.0
        return max(float(v) for v in scores.values())

    def _primary_category_hit(result) -> List[Tuple[str, float, str]]:
        """Ordnet jedes Foto genau einer Ziel-Kategorie zu (Hauptklasse, nicht alle hohen Scores)."""
        scores = getattr(result, "all_scores", None) or {}
        predicted = str(getattr(result, "category", "") or "")
        target_scores = {c: score_for_preview(scores, c) for c in target_categories}
        if not target_scores:
            return []

        predicted_preview = model_class_to_preview_key(predicted, target_categories)
        if predicted_preview:
            primary = predicted_preview
        else:
            primary = max(target_categories, key=lambda c: target_scores[c])

        score = target_scores[primary]
        if score < min_confidence:
            return []
        return [(primary, score, predicted)]

    def _analyze_one(item: Tuple[int, str]):
        photo_index, photo_path = item
        result = classify_fn(photo_path, camera_type)
        local_hits = _primary_category_hit(result)
        return photo_index, photo_path, local_hits, _best_score(result)

    def _merge_hits(
        photo_index: int,
        photo_path: str,
        local_hits: List[Tuple[str, float, str]],
    ) -> None:
        if not local_hits:
            return
        with grouped_lock:
            for category, score, predicted in local_hits:
                grouped[category].append(
                    {
                        "index": photo_index,
                        "path": photo_path,
                        "score": score,
                        "predicted": predicted,
                    }
                )

    def _run_parallel_batch(
        items: List[Tuple[int, str]],
        neighbor_hook=None,
    ) -> None:
        nonlocal completed
        if not items:
            return
        batch_workers = max(1, min(workers, len(items)))
        with ThreadPoolExecutor(max_workers=batch_workers) as executor:
            futures = {executor.submit(_analyze_one, item): item for item in items}
            for future in as_completed(futures):
                photo_index, photo_path = futures[future]
                try:
                    _, _, local_hits, best_conf = future.result()
                    _merge_hits(photo_index, photo_path, local_hits)
                    if neighbor_hook is not None:
                        neighbor_hook(photo_index, photo_path, best_conf)
                except Exception as exc:
                    _log(f"Analyse fehlgeschlagen für {photo_path}: {exc}")
                finally:
                    with progress_lock:
                        completed += 1
                        done = completed
                    if on_progress:
                        on_progress(done, total_available, os.path.basename(photo_path))

    if not use_sampling:
        _log(
            f"KI-Analyse ({camera_type}): alle {total_available} Fotos parallel "
            f"(Vollscan), max. {workers} Worker."
        )
        _run_parallel_batch(indexed_paths)
    else:
        near_threshold = max(0.0, min_confidence - 0.10)
        stride_indices = list(range(0, total_available, 2))
        to_scan_neighbors: set[int] = set()
        stride_items = [indexed_paths[pos] for pos in stride_indices]
        pos_by_item = {indexed_paths[pos]: pos for pos in stride_indices}

        _log(
            f"KI-Analyse ({camera_type}): {len(stride_items)} Stride-Fotos parallel "
            f"(jeden 2.), max. {workers} Worker."
        )

        def _stride_neighbor_hook(photo_index: int, photo_path: str, best_conf: float) -> None:
            pos = pos_by_item.get((photo_index, photo_path))
            if pos is None:
                return
            if best_conf >= near_threshold:
                if pos - 1 >= 0:
                    to_scan_neighbors.add(pos - 1)
                if pos + 1 < total_available:
                    to_scan_neighbors.add(pos + 1)

        _run_parallel_batch(stride_items, neighbor_hook=_stride_neighbor_hook)

        remaining = sorted(i for i in to_scan_neighbors if i not in stride_indices)
        if remaining:
            scan_queue = [indexed_paths[i] for i in remaining]
            _log(f"KI-Analyse ({camera_type}): {len(scan_queue)} Nachbar-Foto(s) nachziehen.")
            _run_parallel_batch(scan_queue)

    for category in target_categories:
        grouped[category].sort(key=lambda x: x["score"], reverse=True)
        grouped[category] = grouped[category][:max_candidates]
        _log(
            f"Kategorie {category} ({camera_type}): "
            f"{len(grouped[category])} Kandidat(en) >= {min_confidence:.2f}"
        )
    return grouped
