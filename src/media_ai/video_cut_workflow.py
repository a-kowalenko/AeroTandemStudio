"""Orchestrierung: KI-Analyse → Review-Dialog → FFmpeg-Export."""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from .video_analyzer import VideoAnalysisProgress, VideoAnalyzer, build_project_dict
from src.ui.video_preview_dialog import VideoCutReviewDialog
from src.video.video_cutter import VideoCutExporter, export_clips_for_reimport, segments_from_project_clips


def run_auto_video_cut_workflow(
    master,
    video_paths: List[str],
    camera_type: str,
    output_path: str,
    *,
    on_analysis_progress: Optional[Callable[[VideoAnalysisProgress], None]] = None,
    on_export_progress: Optional[Callable[[float, str], None]] = None,
    on_log: Optional[Callable[[str], None]] = None,
) -> Optional[str]:
    """
    End-to-End Workflow für automatischen Videoschnitt mit manuellem Review.

    1. KI analysiert alle Clips (Import-Reihenfolge bleibt erhalten)
    2. Review-Dialog zur Feinjustierung
    3. FFmpeg-Export bei Bestätigung

    Args:
        master: Tkinter-Hauptfenster (Parent für modale Dialoge)
        video_paths: Liste der Quellclips in Import-Reihenfolge
        camera_type: ``handcam`` oder ``outside``
        output_path: Zielpfad für das kombinierte Kunden-Video

    Returns:
        Pfad des exportierten Videos oder ``None`` bei Abbruch.
    """
    if not video_paths:
        return None

    if on_log:
        on_log(f"Analysiere {len(video_paths)} Clip(s) ({camera_type})...")

    analyzer = VideoAnalyzer(camera_type)
    results = analyzer.analyze_videos(video_paths, on_progress=on_analysis_progress)
    project = build_project_dict(camera_type, results)

    export_result: List[Optional[str]] = [None]

    def handle_apply(_project: dict, active_clips: list) -> None:
        if on_log:
            on_log(f"Erstelle {len(active_clips)} geschnittene Clip(s)...")
        import os
        import tempfile

        out_dir = os.path.join(tempfile.mkdtemp(prefix="aero_ki_trim_"), "clips")
        export_result[0] = export_clips_for_reimport(
            active_clips,
            out_dir,
            progress_callback=on_export_progress,
        )
        if on_log and export_result[0]:
            on_log(f"Fertig: {len(export_result[0])} Datei(en)")

    dialog = VideoCutReviewDialog(master, project, on_apply=handle_apply)
    dialog.show()
    return export_result[0] if dialog.confirmed else None


def run_auto_video_cut_workflow_async(
    master,
    video_paths: List[str],
    camera_type: str,
    output_path: str,
    *,
    on_done: Callable[[Optional[str]], None],
    on_analysis_progress: Optional[Callable[[VideoAnalysisProgress], None]] = None,
    on_export_progress: Optional[Callable[[float, str], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> None:
    """
    Führt die KI-Analyse im Hintergrund aus und öffnet danach den Review-Dialog
    im Tk-Hauptthread.
    """

    def worker() -> None:
        try:
            analyzer = VideoAnalyzer(camera_type)
            results = analyzer.analyze_videos(video_paths, on_progress=on_analysis_progress)
            project = build_project_dict(camera_type, results)

            def open_dialog() -> None:
                try:
                    path = _open_review_and_export(
                        master,
                        project,
                        output_path,
                        on_export_progress=on_export_progress,
                    )
                    on_done(path)
                except Exception as exc:
                    if on_error:
                        on_error(exc)
                    else:
                        raise

            master.after(0, open_dialog)
        except Exception as exc:
            if on_error:
                master.after(0, lambda: on_error(exc))
            else:
                master.after(0, lambda: (_ for _ in ()).throw(exc))

    threading.Thread(target=worker, daemon=True).start()


def _open_review_and_export(
    master,
    project: dict,
    output_path: str,
    *,
    on_export_progress: Optional[Callable[[float, str], None]] = None,
) -> Optional[str]:
    export_result: List[Optional[str]] = [None]

    def handle_apply(_project: dict, active_clips: list) -> None:
        import os
        import tempfile

        out_dir = os.path.join(tempfile.mkdtemp(prefix="aero_ki_trim_"), "clips")
        export_result[0] = export_clips_for_reimport(
            active_clips,
            out_dir,
            progress_callback=on_export_progress,
        )

    dialog = VideoCutReviewDialog(master, project, on_apply=handle_apply)
    dialog.show()
    return export_result[0] if dialog.confirmed else None
