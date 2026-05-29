"""Phasen-Segmente aus KI-Timeline (Export-Merge ohne Schnitt bei direkter Nachbarschaft)."""

from __future__ import annotations

import copy
import uuid
from typing import Dict, List, Optional

from .video_analyzer import UNKNOWN_PHASE, normalize_phase_name

ADJACENCY_EPSILON = 0.12


def _coerce_float(value: object, default: float = 0.0) -> float:
    """Robustes float — schützt vor explizitem ``None`` in JSON/Dicts."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _segment_trim_start(seg: dict, duration: float = 0.0) -> float:
    if seg.get("trim_start") is not None:
        return _coerce_float(seg.get("trim_start"), 0.0)
    return _coerce_float(seg.get("start_sec"), 0.0)


def _segment_trim_end(seg: dict, duration: float = 0.0) -> float:
    if seg.get("trim_end") is not None:
        end = _coerce_float(seg.get("trim_end"), duration)
    else:
        end = _coerce_float(seg.get("end_sec"), duration)
    if duration > 0:
        return min(duration, max(0.0, end))
    return max(0.0, end)


def timeline_to_phase_segments(
    timeline: Dict[float, str],
    duration_sec: float,
    sample_interval: float = 1.0,
) -> List[dict]:
    """
    Zerlegt die geglättete Timeline in zusammenhängende Phasen-Blöcke.

    Jeder Block erhält trim_start/trim_end (initial = KI-Grenzen) und enabled
    (unknown-Segmente standardmäßig deaktiviert).
    """
    duration_sec = max(0.0, float(duration_sec))
    interval = max(0.1, float(sample_interval))

    if not timeline:
        return [_make_segment(UNKNOWN_PHASE, 0.0, duration_sec, enabled=False)]

    keyed = sorted((float(t), normalize_phase_name(p)) for t, p in timeline.items())
    runs: List[List[float | str]] = []
    for t, phase in keyed:
        if not runs or runs[-1][0] != phase:
            runs.append([phase, t, t])
        else:
            runs[-1][2] = t

    segments: List[dict] = []
    for idx, (phase, first_key, last_key) in enumerate(runs):
        start_sec = max(0.0, float(first_key) - interval)
        if idx + 1 < len(runs):
            next_start = float(runs[idx + 1][1]) - interval
            end_sec = min(duration_sec, max(start_sec + interval, next_start))
        else:
            end_sec = duration_sec
        if end_sec <= start_sec:
            end_sec = min(duration_sec, start_sec + interval)
        enabled = phase != UNKNOWN_PHASE
        segments.append(_make_segment(str(phase), start_sec, end_sec, enabled=enabled))

    return segments


def _make_segment(phase: str, start_sec: float, end_sec: float, *, enabled: bool) -> dict:
    return {
        "segment_id": str(uuid.uuid4()),
        "phase": phase,
        "start_sec": round(start_sec, 1),
        "end_sec": round(end_sec, 1),
        "trim_start": round(start_sec, 1),
        "trim_end": round(end_sec, 1),
        "enabled": enabled,
    }


def _has_unknown_gap_between(
    timeline: Dict[float, str],
    end_sec: float,
    start_sec: float,
    sample_interval: float,
) -> bool:
    """True wenn zwischen zwei Zeiten ein unknown-Sample liegt (Unterbrechung)."""
    if start_sec <= end_sec + ADJACENCY_EPSILON:
        return False
    for t, phase in timeline.items():
        tf = float(t)
        if tf <= end_sec + ADJACENCY_EPSILON:
            continue
        if tf >= start_sec - ADJACENCY_EPSILON:
            break
        if normalize_phase_name(phase) == UNKNOWN_PHASE:
            return True
    return False


def merge_adjacent_export_segments(
    segments: List[dict],
    timeline: Optional[Dict[float, str]] = None,
    *,
    sample_interval: float = 1.0,
    clip_duration: float = 0.0,
) -> List[dict]:
    """
    Fasst für den Export zusammen: Direkt benachbarte aktive Phasen ohne
    unknown-Unterbrechung dazwischen werden zu einem Schnittblock (kein Schnitt dazwischen).
    """
    timeline_f = {float(k): v for k, v in (timeline or {}).items()}
    enabled = [
        s
        for s in segments
        if s.get("enabled", True) and normalize_phase_name(str(s.get("phase", ""))) != UNKNOWN_PHASE
    ]
    if not enabled:
        return []

    enabled = sorted(enabled, key=lambda s: _segment_trim_start(s, clip_duration))
    merged: List[dict] = []
    current = _export_slice_from_segment(enabled[0], clip_duration)

    for seg in enabled[1:]:
        prev_end = _coerce_float(current["trim_end"], clip_duration)
        next_start = _segment_trim_start(seg, clip_duration)
        gap = _has_unknown_gap_between(timeline_f, prev_end, next_start, sample_interval)
        touching = next_start <= prev_end + ADJACENCY_EPSILON

        if touching and not gap:
            current["trim_end"] = max(prev_end, _segment_trim_end(seg, clip_duration))
            current["phases"].append(normalize_phase_name(str(seg.get("phase", ""))))
        else:
            merged.append(current)
            current = _export_slice_from_segment(seg, clip_duration)

    merged.append(current)
    return merged


def _export_slice_from_segment(seg: dict, clip_duration: float = 0.0) -> dict:
    phase = normalize_phase_name(str(seg.get("phase", "")))
    path = seg.get("path")
    return {
        "path": str(path) if path else "",
        "phase": phase,
        "phases": [phase],
        "trim_start": _segment_trim_start(seg, clip_duration),
        "trim_end": _segment_trim_end(seg, clip_duration),
        "duration_sec": _coerce_float(seg.get("duration_sec"), clip_duration) or clip_duration,
        "source_clip_id": seg.get("source_clip_id"),
    }


def expand_clips_to_export_segments(active_clips: List[dict]) -> List[dict]:
    """Alle aktiven Clips → flache Export-Liste (mit Nachbar-Merge pro Quelldatei)."""
    export_rows: List[dict] = []
    for clip in active_clips:
        path = str(clip.get("path") or "")
        if not path:
            continue
        duration = _coerce_float(clip.get("duration_sec"), 0.0)
        timeline_raw = clip.get("timeline") or {}
        timeline = {float(k): v for k, v in timeline_raw.items()}

        segments = clip.get("phase_segments") or []
        if not segments:
            segments = [
                _make_segment(
                    normalize_phase_name(str(clip.get("dominant_phase", UNKNOWN_PHASE))),
                    _coerce_float(clip.get("trim_start"), 0.0),
                    _segment_trim_end(
                        {
                            "trim_end": clip.get("trim_end"),
                            "end_sec": duration,
                        },
                        duration,
                    ),
                    enabled=True,
                )
            ]

        prepared: List[dict] = []
        for seg in segments:
            item = copy.copy(seg)
            item["path"] = path
            item["duration_sec"] = duration
            item["source_clip_id"] = clip.get("id")
            prepared.append(item)

        merged = merge_adjacent_export_segments(prepared, timeline, clip_duration=duration)
        export_rows.extend(merged)

    return export_rows
