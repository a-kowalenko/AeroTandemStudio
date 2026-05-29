"""Vereinter KI-Review-Dialog (Fotos + Video in Tabs)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable, Dict, List, Optional

from src.gui.components.media_ai_review_dialog import MediaAIReviewPanel
from src.media_ai.camera_resolution import format_camera_type_label
from src.ui.video_preview_dialog import VideoCutReviewPanel

if TYPE_CHECKING:
    from src.gui.components.drag_drop import DragDropFrame


class UnifiedMediaAIDialog(tk.Toplevel):
    """
    Tabs für Foto- und Video-KI.

    Foto-Tab wird aktiv, sobald die Foto-Analyse fertig ist.
    Video-Analyse kann parallel im Hintergrund laufen.
    """

    def __init__(
        self,
        master,
        drag_drop: "DragDropFrame",
        ai_settings: Dict[str, object],
        *,
        sample_interval: float = 1.0,
    ) -> None:
        super().__init__(master)
        self.withdraw()
        self.title("KI-Analyse – Fotos & Video")
        self.geometry("1680x960")
        self.minsize(1280, 760)
        self.transient(master)
        self.grab_set()

        self._dd = drag_drop
        self._ai_settings = ai_settings
        self._sample_interval = sample_interval
        self.result_confirmed = False
        self._photo_panel: Optional[MediaAIReviewPanel] = None
        self._video_panel: Optional[VideoCutReviewPanel] = None
        self._camera_type: Optional[str] = None
        self._photo_applied = False

        header = tk.Label(
            self,
            text="Foto-Auswahl und Video-Schnitt in einem Schritt",
            font=("Arial", 11, "bold"),
            anchor="w",
        )
        header.pack(fill="x", padx=12, pady=(10, 4))

        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._photo_tab = tk.Frame(self._notebook, bg="#f5f6f8")
        self._video_tab = tk.Frame(self._notebook, bg="#1a1a1a")
        self._notebook.add(self._photo_tab, text="Fotos")
        self._notebook.add(self._video_tab, text="Video")

        self._photo_host = tk.Frame(self._photo_tab, bg="#f5f6f8")
        self._photo_host.pack(fill=tk.BOTH, expand=True)
        self._photo_status = tk.Label(
            self._photo_host,
            text="Foto-KI analysiert…",
            font=("Arial", 12),
            bg="#f5f6f8",
            fg="#333",
        )
        self._photo_status.pack(expand=True)

        self._video_host = tk.Frame(self._video_tab, bg="#1a1a1a")
        self._video_host.pack(fill=tk.BOTH, expand=True)
        self._video_status = tk.Label(
            self._video_host,
            text="Video-KI startet nach Kamera-Erkennung…",
            font=("Arial", 12),
            bg="#1a1a1a",
            fg="#cccccc",
        )
        self._video_status.pack(expand=True)

        footer = tk.Frame(self, padx=12, pady=8)
        footer.pack(fill=tk.X)
        tk.Button(footer, text="Abbrechen", width=14, command=self._on_cancel).pack(side=tk.RIGHT)

        self._center_over_parent(master)
        self.deiconify()
        try:
            self.lift()
            self.focus_force()
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _center_over_parent(self, master) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        try:
            master.update_idletasks()
            x = master.winfo_rootx() + max(0, (master.winfo_width() - w) // 2)
            y = master.winfo_rooty() + max(0, (master.winfo_height() - h) // 2)
        except Exception:
            x = (self.winfo_screenwidth() - w) // 2
            y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

    def set_photo_progress(self, text: str) -> None:
        if self._photo_panel:
            return
        self._photo_status.config(text=text)

    def set_video_progress(self, text: str) -> None:
        if self._video_panel:
            return
        self._video_status.config(text=text)

    def show_photo_ready(
        self,
        grouped_candidates: Dict[str, List[dict]],
        camera_type: str,
    ) -> None:
        self._camera_type = camera_type
        self._photo_status.destroy()
        self._photo_panel = MediaAIReviewPanel(
            self._photo_host,
            grouped_candidates,
            self._dd.photo_paths,
            camera_type=camera_type,
            on_apply=self._on_photo_apply,
            on_cancel=self._on_cancel,
        )
        self._photo_panel.pack(fill=tk.BOTH, expand=True)
        self._notebook.tab(0, text=f"Fotos ({format_camera_type_label(camera_type)})")
        self._notebook.select(0)

    def show_video_ready(self, project: dict, camera_type: str) -> None:
        self._camera_type = camera_type
        self._video_status.destroy()

        def on_apply(exported_project: dict, active_clips: List[dict]) -> None:
            self._dd.handle_unified_video_apply(exported_project, active_clips, self)

        self._video_panel = VideoCutReviewPanel(
            self._video_host,
            project,
            on_apply=on_apply,
            on_cancel=self._on_cancel,
            sample_interval=self._sample_interval,
            embedded=True,
        )
        self._video_panel.pack(fill=tk.BOTH, expand=True)
        self._notebook.tab(1, text=f"Video ({format_camera_type_label(camera_type)})")
        if self._photo_applied:
            self._notebook.select(1)
            self._video_panel.focus_set()

    def _on_photo_apply(self, selected_indices: List[int]) -> None:
        self._photo_applied = True
        self._dd.apply_media_ai_preview_indices_public(selected_indices)
        self._notebook.select(1)
        if self._video_panel:
            self._video_panel.focus_set()
        else:
            self.set_video_progress(
                "Video-KI läuft noch im Hintergrund – bitte kurz warten…"
            )

    def _on_cancel(self) -> None:
        self.result_confirmed = False
        if self._video_panel:
            self._video_panel._cleanup()
        self.grab_release()
        self.destroy()
        self._dd._end_unified_workflow()
