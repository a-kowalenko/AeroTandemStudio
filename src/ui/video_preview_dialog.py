"""Master-Detail Review-Dialog für KI-Videoschnitt (CapCut-ähnliche Timeline)."""

from __future__ import annotations

import copy
import os
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

import cv2
from PIL import Image, ImageTk

from src.media_ai.phase_segments import timeline_to_phase_segments
from src.ui.capcut_timeline import CapCutTimeline, phase_color
from src.ui.vlc_review_player import create_review_player

PHASE_LABELS: Dict[str, str] = {
    "ground_interview": "Interview (Boden)",
    "briefing": "Briefing",
    "boarding": "Boarding",
    "takeoff": "Start",
    "climb": "Steigflug",
    "door_prep": "Tür vorbereiten",
    "door": "Tür",
    "exit": "Exit",
    "freefall": "Freifall",
    "deployment": "Schirmöffnung",
    "canopy": "Schirmfahrt",
    "landing": "Landung",
    "final_interview": "Final",
    "unknown": "Unbekannt",
}


def format_phase_label(phase: str) -> str:
    key = (phase or "unknown").strip().lower()
    return PHASE_LABELS.get(key, key.replace("_", " ").title())


def format_duration(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    mins = int(seconds // 60)
    secs = seconds % 60
    return f"{mins:d}:{secs:05.2f}"


def ensure_clip_phase_segments(clip: dict, *, sample_interval: float = 1.0) -> List[dict]:
    """Stellt sicher, dass ein Clip phase_segments hat (Migration alter Projekte)."""
    segments = clip.get("phase_segments")
    if segments:
        return segments

    duration = float(clip.get("duration_sec", 0.0))
    timeline_raw = clip.get("timeline") or {}
    timeline = {float(k): v for k, v in timeline_raw.items()}
    if timeline:
        segments = timeline_to_phase_segments(timeline, duration, sample_interval=sample_interval)
    else:
        from src.media_ai.video_analyzer import UNKNOWN_PHASE

        segments = [
            {
                "segment_id": str(clip.get("id", "legacy")),
                "phase": clip.get("dominant_phase", UNKNOWN_PHASE),
                "start_sec": 0.0,
                "end_sec": duration,
                "trim_start": float(clip.get("trim_start", 0.0)),
                "trim_end": float(clip.get("trim_end", duration)),
                "enabled": True,
            }
        ]
    clip["phase_segments"] = segments
    return segments


class ClipTile(tk.Frame):
    """Kachel in der linken Clip-Liste (ohne Schieberegler)."""

    def __init__(
        self,
        master,
        clip: dict,
        *,
        selected: bool = False,
        selected_segment_id: Optional[str] = None,
        on_select: Callable[[str], None],
        on_segment_select: Callable[[str, str], None],
        on_segment_toggle: Callable[[str, str], None],
        on_segment_delete: Callable[[str, str], None],
        on_delete: Callable[[str], None],
        on_drag_start: Callable[[str], None],
        on_drag_motion: Callable[[str, int], None],
    ) -> None:
        super().__init__(master, bd=1, relief=tk.RIDGE, padx=6, pady=6, bg="#ffffff")
        self.clip_id = str(clip["id"])
        self._on_select = on_select
        self._on_segment_select = on_segment_select
        self._on_segment_toggle = on_segment_toggle
        self._on_segment_delete = on_segment_delete
        self._on_delete = on_delete
        self._on_drag_start = on_drag_start
        self._on_drag_motion = on_drag_motion
        self._segment_buttons: Dict[str, tk.Button] = {}

        duration = float(clip.get("duration_sec", 0.0))
        filename = os.path.basename(str(clip.get("path", "")))
        segments = ensure_clip_phase_segments(clip)
        enabled_count = sum(1 for s in segments if s.get("enabled", True))

        header = tk.Frame(self, bg="#ffffff")
        header.pack(fill="x")
        self._thumb_label = tk.Label(header, bg="#222", width=18, height=5)
        self._thumb_label.pack(side="left", padx=(0, 8))
        self._thumb_label.bind("<Button-1>", lambda _e: self._on_select(self.clip_id))

        info = tk.Frame(header, bg="#ffffff")
        info.pack(side="left", fill="x", expand=True)
        tk.Label(info, text=filename, font=("Arial", 10, "bold"), anchor="w", bg="#ffffff").pack(fill="x")
        tk.Label(
            info,
            text=f"{format_duration(duration)}  ·  {enabled_count} Phase(n)",
            font=("Arial", 9),
            fg="#444",
            anchor="w",
            bg="#ffffff",
        ).pack(fill="x")

        phases_row = tk.Frame(self, bg="#ffffff")
        phases_row.pack(fill="x", pady=(6, 0))
        self._phases_wrap = phases_row
        self._rebuild_phase_chips(clip, selected_segment_id)

        actions = tk.Frame(self, bg="#ffffff")
        actions.pack(fill="x", pady=(4, 0))
        tk.Button(
            actions,
            text="Löschen",
            command=lambda: self._on_delete(self.clip_id),
            fg="#b00020",
            relief=tk.FLAT,
        ).pack(side="right")

        for widget in (self, header, info):
            widget.bind("<Button-1>", lambda _e: self._on_select(self.clip_id))
        self.bind("<Button-1>", self._start_drag, add="+")
        self.bind("<B1-Motion>", self._drag, add="+")

        self._set_selected(selected)
        self._load_thumbnail(str(clip.get("path", "")))

    def _rebuild_phase_chips(self, clip: dict, selected_segment_id: Optional[str]) -> None:
        for child in self._phases_wrap.winfo_children():
            child.destroy()
        self._segment_buttons.clear()

        for seg in ensure_clip_phase_segments(clip):
            sid = str(seg.get("segment_id"))
            phase = str(seg.get("phase", "unknown"))
            enabled = bool(seg.get("enabled", True))
            label = format_phase_label(phase)
            t0 = float(seg.get("trim_start", 0.0))
            t1 = float(seg.get("trim_end", 0.0))
            text = f"{label} {t0:.0f}–{t1:.0f}s"
            bg = phase_color(phase) if enabled else "#cccccc"
            fg = "#ffffff" if enabled else "#666666"
            relief = tk.SOLID if sid == selected_segment_id else tk.FLAT
            btn = tk.Button(
                self._phases_wrap,
                text=text,
                font=("Arial", 8),
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                relief=relief,
                bd=1 if sid == selected_segment_id else 0,
                padx=4,
                pady=1,
                command=lambda s=sid: self._on_segment_select(self.clip_id, s),
            )
            btn.pack(side=tk.LEFT, padx=2, pady=2)
            btn.bind(
                "<Button-3>",
                lambda e, s=sid: self._show_segment_menu(e, s),
            )
            self._segment_buttons[sid] = btn

        hint = tk.Label(
            self._phases_wrap,
            text="Rechtsklick: Phase ein/aus · löschen",
            font=("Arial", 7),
            fg="#888",
            bg="#ffffff",
        )
        hint.pack(side=tk.LEFT, padx=4)

    def _show_segment_menu(self, event, segment_id: str) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(
            label="Phase ein/ausschalten",
            command=lambda: self._on_segment_toggle(self.clip_id, segment_id),
        )
        menu.add_command(
            label="Phase löschen",
            command=lambda: self._on_segment_delete(self.clip_id, segment_id),
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _start_drag(self, event) -> None:
        if event.widget not in (self, self._thumb_label):
            return
        self._on_drag_start(self.clip_id)

    def _drag(self, event) -> None:
        self._on_drag_motion(self.clip_id, event.y_root)

    def update_from_clip(
        self,
        clip: dict,
        *,
        selected: bool,
        selected_segment_id: Optional[str] = None,
    ) -> None:
        self._rebuild_phase_chips(clip, selected_segment_id)
        self._set_selected(selected)

    def _set_selected(self, selected: bool) -> None:
        self.configure(bg="#dbeafe" if selected else "#ffffff", highlightthickness=2 if selected else 0)


    def _load_thumbnail(self, path: str) -> None:
        def worker() -> None:
            try:
                cap = cv2.VideoCapture(path)
                ok, frame = cap.read()
                cap.release()
                if not ok or frame is None:
                    return
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb).resize((120, 68), Image.BILINEAR)
                photo = ImageTk.PhotoImage(img)
                self.after(0, lambda: self._apply_thumb(photo))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _apply_thumb(self, photo: ImageTk.PhotoImage) -> None:
        if not self.winfo_exists():
            return
        self._thumb_photo = photo
        self._thumb_label.configure(image=photo, width=120, height=68)


class VideoCutReviewPanel(tk.Frame):
    """Review-UI: mehrere Phasen pro Clip, CapCut-Timeline, schneller Player (einbettbar)."""

    def __init__(
        self,
        master,
        project: dict,
        *,
        on_apply: Callable[[dict, List[dict]], None],
        on_cancel: Optional[Callable[[], None]] = None,
        on_export: Optional[Callable[[dict, List[dict]], None]] = None,
        sample_interval: float = 1.0,
        embedded: bool = False,
    ) -> None:
        super().__init__(master)
        self._embedded = embedded

        self._sample_interval = max(0.1, float(sample_interval))
        self._project = copy.deepcopy(project)
        for clip in self._project.get("clips", []):
            ensure_clip_phase_segments(clip, sample_interval=self._sample_interval)

        self._on_apply = on_apply or on_export
        if not self._on_apply:
            raise ValueError("on_apply (oder on_export) ist erforderlich.")
        self._on_cancel = on_cancel
        self._active_clips: List[dict] = [c for c in self._project.get("clips", []) if not c.get("deleted")]
        self._trash_clips: List[dict] = [c for c in self._project.get("clips", []) if c.get("deleted")]
        self._clip_by_id: Dict[str, dict] = {str(c["id"]): c for c in self._project.get("clips", [])}
        self._selected_id: Optional[str] = self._active_clips[0]["id"] if self._active_clips else None
        self._selected_segment_id: Optional[str] = None
        self._tiles: Dict[str, ClipTile] = {}
        self._drag_id: Optional[str] = None
        self._player: Optional[FastVideoPlayer] = None
        self._capcut: Optional[CapCutTimeline] = None
        self._snap_hint_job: Optional[str] = None
        self._edge_trim_active = False
        self._last_playhead_sync = 0.0
        self._timeline_scrub_active = False
        self.confirmed = False
        self.exported_project: Optional[dict] = None
        self.export_segments: List[dict] = []

        self._build_ui()
        self._refresh_clip_list()
        if self._selected_id:
            self._select_clip(self._selected_id)

    def _build_ui(self) -> None:
        root = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=6, bg="#d0d4d8")
        root.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(root, bg="#f3f4f6")
        root.add(left, minsize=380, stretch="always")

        tk.Label(
            left,
            text="Clips (Import-Reihenfolge)",
            font=("Arial", 11, "bold"),
            bg="#f3f4f6",
        ).pack(anchor="w", padx=10, pady=(10, 4))

        list_frame = tk.Frame(left, bg="#f3f4f6")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        self._list_canvas = tk.Canvas(list_frame, bg="#f3f4f6", highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._tiles_frame = tk.Frame(self._list_canvas, bg="#f3f4f6")
        self._list_window = self._list_canvas.create_window((0, 0), window=self._tiles_frame, anchor="nw")
        self._tiles_frame.bind("<Configure>", self._on_list_configure)
        self._list_canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self._list_canvas)

        trash_hdr = tk.Label(left, text="Papierkorb", font=("Arial", 10, "bold"), bg="#f3f4f6", fg="#666")
        trash_hdr.pack(anchor="w", padx=10, pady=(8, 2))
        self._trash_frame = tk.Frame(left, bg="#f3f4f6")
        self._trash_frame.pack(fill=tk.X, padx=8, pady=(0, 8))

        right = tk.Frame(root, bg="#1a1a1a")
        root.add(right, minsize=520, stretch="always")

        self._video_container = tk.Frame(right, bg="#000000", height=360)
        self._video_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 4))
        self._player = create_review_player(self._video_container)
        self._player.set_time_callback(self._on_player_time)
        if hasattr(self._player, "set_play_state_callback"):
            self._player.set_play_state_callback(self._on_play_state_change)

        timeline_frame = tk.Frame(right, bg="#1e1e1e")
        timeline_frame.pack(fill=tk.X, padx=8, pady=(0, 4))

        tk.Label(
            timeline_frame,
            text="Phasen-Timeline — Kanten ziehen · Phasen markieren & löschen",
            font=("Arial", 9),
            fg="#aaa",
            bg="#1e1e1e",
        ).pack(anchor="w", pady=(0, 2))

        self._capcut = CapCutTimeline(
            timeline_frame,
            duration_sec=10.0,
            segments=[],
            on_seek=self._on_timeline_seek,
            on_scrub_begin=self._on_timeline_scrub_begin,
            on_scrub_move=self._on_timeline_scrub_move,
            on_segment_change=self._on_segment_trim,
            on_select_segment=self._on_timeline_select_segment,
            on_snap=self._on_timeline_snap,
        )
        self._capcut.pack(fill=tk.X)

        self._segment_info = tk.Label(
            timeline_frame,
            text="",
            font=("Arial", 9),
            fg="#ccc",
            bg="#1e1e1e",
            anchor="w",
        )
        self._segment_info.pack(fill=tk.X, pady=(4, 0))

        controls = tk.Frame(right, bg="#2b2b2b")
        controls.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._play_btn = tk.Button(controls, text="▶", width=4, command=self._toggle_play)
        self._play_btn.pack(side=tk.LEFT, padx=4, pady=6)
        self._time_label = tk.Label(controls, text="00:00 / 00:00", fg="white", bg="#2b2b2b")
        self._time_label.pack(side=tk.LEFT, padx=8)
        tk.Button(
            controls,
            text="Phase löschen",
            command=self._delete_selected_segment,
            fg="#ffb4b4",
            bg="#2b2b2b",
            relief=tk.FLAT,
        ).pack(side=tk.LEFT, padx=4)
        tk.Label(
            controls,
            text="Benachbarte aktive Phasen werden pro Clip zu einer Datei zusammengeführt",
            fg="#888",
            bg="#2b2b2b",
            font=("Arial", 8),
        ).pack(side=tk.LEFT, padx=8)

        footer = tk.Frame(self, padx=12, pady=10)
        footer.pack(fill=tk.X)
        tk.Button(footer, text="Abbrechen", width=14, command=self._on_close).pack(side=tk.RIGHT, padx=4)
        tk.Button(
            footer,
            text="Schnitte übernehmen",
            width=18,
            bg="#4CAF50",
            fg="white",
            command=self._on_apply_click,
        ).pack(side=tk.RIGHT, padx=4)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._on_mousewheel))
        widget.bind("<Leave>", lambda _e: self.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event) -> None:
        self._list_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_list_configure(self, _event=None) -> None:
        self._list_canvas.configure(scrollregion=self._list_canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._list_canvas.itemconfig(self._list_window, width=event.width)

    def _refresh_clip_list(self) -> None:
        for child in self._tiles_frame.winfo_children():
            child.destroy()
        for child in self._trash_frame.winfo_children():
            child.destroy()
        self._tiles.clear()

        for clip in self._active_clips:
            tile = ClipTile(
                self._tiles_frame,
                clip,
                selected=str(clip["id"]) == self._selected_id,
                selected_segment_id=self._selected_segment_id if str(clip["id"]) == self._selected_id else None,
                on_select=self._select_clip,
                on_segment_select=self._select_segment,
                on_segment_toggle=self._toggle_segment,
                on_segment_delete=self._delete_segment,
                on_delete=self._delete_clip,
                on_drag_start=self._on_drag_start,
                on_drag_motion=self._on_drag_motion,
            )
            tile.pack(fill=tk.X, pady=4)
            self._tiles[str(clip["id"])] = tile

        if not self._trash_clips:
            tk.Label(self._trash_frame, text="— leer —", fg="#999", bg="#f3f4f6").pack(anchor="w")
        for clip in self._trash_clips:
            row = tk.Frame(self._trash_frame, bg="#f3f4f6")
            row.pack(fill=tk.X, pady=2)
            name = os.path.basename(str(clip.get("path", "")))
            tk.Label(row, text=name, bg="#f3f4f6", fg="#666", anchor="w").pack(side=tk.LEFT, fill=tk.X)
            tk.Button(
                row,
                text="Wiederherstellen",
                command=lambda cid=str(clip["id"]): self._restore_clip(cid),
                relief=tk.FLAT,
            ).pack(side=tk.RIGHT)

        self._on_list_configure()

    def _current_clip(self) -> Optional[dict]:
        if not self._selected_id:
            return None
        return self._clip_by_id.get(self._selected_id)

    def _segment_in_clip(self, clip: dict, segment_id: str) -> Optional[dict]:
        for seg in ensure_clip_phase_segments(clip, sample_interval=self._sample_interval):
            if str(seg.get("segment_id")) == segment_id:
                return seg
        return None

    def _select_clip(self, clip_id: str) -> None:
        self._selected_id = clip_id
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return

        segments = ensure_clip_phase_segments(clip, sample_interval=self._sample_interval)
        if segments:
            first_enabled = next((s for s in segments if s.get("enabled", True)), segments[0])
            self._selected_segment_id = str(first_enabled.get("segment_id"))

        for cid, tile in self._tiles.items():
            tile.update_from_clip(
                self._clip_by_id[cid],
                selected=cid == clip_id,
                selected_segment_id=self._selected_segment_id if cid == clip_id else None,
            )

        duration = float(clip.get("duration_sec", 0.0))
        if self._capcut:
            self._capcut.set_duration(duration)
            self._capcut.set_segments(copy.deepcopy(segments))
            if self._selected_segment_id:
                self._capcut.select_segment(self._selected_segment_id)

        self._update_segment_info()
        try:
            if self._player:
                self._player.load(str(clip["path"]))
                start = float(clip.get("trim_start", 0.0))
                if self._selected_segment_id:
                    seg0 = self._segment_in_clip(clip, self._selected_segment_id)
                    if seg0:
                        start = float(seg0["trim_start"])
                self._player.seek(start, immediate=True)
                if self._capcut:
                    self._capcut.set_playhead(start)
        except Exception as exc:
            messagebox.showerror("Player", str(exc), parent=self)

    def _select_segment(self, clip_id: str, segment_id: str) -> None:
        if clip_id != self._selected_id:
            self._select_clip(clip_id)
        self._selected_segment_id = segment_id
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return
        seg = self._segment_in_clip(clip, segment_id)
        if self._capcut:
            self._capcut.select_segment(segment_id)
        if seg and self._player:
            self._player.seek(float(seg["trim_start"]), immediate=True)
            if self._capcut:
                self._capcut.set_playhead(float(seg["trim_start"]))
        tile = self._tiles.get(clip_id)
        if tile:
            tile.update_from_clip(clip, selected=True, selected_segment_id=segment_id)
        self._update_segment_info()

    def _on_timeline_select_segment(self, segment_id: str) -> None:
        if self._selected_id:
            self._select_segment(self._selected_id, segment_id)

    def _delete_selected_segment(self) -> None:
        if self._selected_id and self._selected_segment_id:
            self._delete_segment(self._selected_id, self._selected_segment_id)

    def _delete_segment(self, clip_id: str, segment_id: str) -> None:
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return
        seg = self._segment_in_clip(clip, segment_id)
        if not seg:
            return
        phase = format_phase_label(str(seg.get("phase", "")))
        if not messagebox.askyesno(
            "Phase löschen",
            f"Phase „{phase}“ wirklich entfernen?",
            parent=self,
        ):
            return

        remaining = [
            s
            for s in ensure_clip_phase_segments(clip, sample_interval=self._sample_interval)
            if str(s.get("segment_id")) != segment_id
        ]
        if not remaining:
            messagebox.showwarning(
                "Phase löschen",
                "Mindestens eine Phase muss im Clip verbleiben.",
                parent=self,
            )
            return

        clip["phase_segments"] = remaining
        if self._selected_segment_id == segment_id:
            first = next((s for s in remaining if s.get("enabled", True)), remaining[0])
            self._selected_segment_id = str(first.get("segment_id"))

        if clip_id == self._selected_id and self._capcut:
            self._capcut.set_segments(copy.deepcopy(remaining))
            if self._selected_segment_id:
                self._capcut.select_segment(self._selected_segment_id)

        tile = self._tiles.get(clip_id)
        if tile:
            tile.update_from_clip(
                clip,
                selected=clip_id == self._selected_id,
                selected_segment_id=self._selected_segment_id if clip_id == self._selected_id else None,
            )
        self._update_segment_info()

    def _toggle_segment(self, clip_id: str, segment_id: str) -> None:
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return
        seg = self._segment_in_clip(clip, segment_id)
        if not seg:
            return
        seg["enabled"] = not bool(seg.get("enabled", True))
        if self._selected_id == clip_id and self._capcut:
            self._capcut.set_segments(copy.deepcopy(ensure_clip_phase_segments(clip)))
            self._capcut.select_segment(segment_id)
        tile = self._tiles.get(clip_id)
        if tile:
            tile.update_from_clip(
                clip,
                selected=clip_id == self._selected_id,
                selected_segment_id=self._selected_segment_id if clip_id == self._selected_id else None,
            )
        self._update_segment_info()

    def _on_timeline_snap(self, joint_sec: float, active: bool) -> None:
        if self._snap_hint_job:
            try:
                self.after_cancel(self._snap_hint_job)
            except tk.TclError:
                pass
            self._snap_hint_job = None

        if active:
            self._segment_info.config(
                text=f"● Verbunden bei {joint_sec:.1f}s — Kanten rasten ein",
                fg="#4ade80",
            )

            def clear_hint() -> None:
                self._snap_hint_job = None
                self._update_segment_info()

            self._snap_hint_job = self.after(900, clear_hint)
        elif not self._edge_trim_active:
            self._update_segment_info()

    def _on_segment_trim(
        self,
        segment_id: str,
        trim_start: float,
        trim_end: float,
        scrubbing: bool,
    ) -> None:
        clip = self._current_clip()
        if not clip:
            return
        seg = self._segment_in_clip(clip, segment_id)
        if not seg:
            return
        seg["trim_start"] = round(trim_start, 1)
        seg["trim_end"] = round(trim_end, 1)
        self._selected_segment_id = segment_id
        self._edge_trim_active = scrubbing

        if scrubbing:
            return

        self._edge_trim_active = False
        if self._player:
            self._player.set_scrubbing(False)
            self._player.seek(trim_start, show=True, immediate=True)
        if self._capcut:
            self._capcut.set_playhead(trim_start)
        tile = self._tiles.get(str(clip["id"]))
        if tile:
            tile.update_from_clip(clip, selected=True, selected_segment_id=segment_id)
        self._update_segment_info()

    def _on_timeline_scrub_begin(self) -> None:
        if self._timeline_scrub_active:
            return
        self._timeline_scrub_active = True
        self.after_idle(self._timeline_scrub_begin_player)

    def _timeline_scrub_begin_player(self) -> None:
        if self._timeline_scrub_active and self._player:
            self._player.set_scrubbing(True)

    def _on_timeline_scrub_move(self, sec: float) -> None:
        duration = float(
            self._current_clip().get("duration_sec", 0.0) if self._current_clip() else 0.0
        )
        self._time_label.config(
            text=f"{format_duration(sec)} / {format_duration(duration)}"
        )

    def _on_timeline_seek(self, sec: float, scrubbing: bool) -> None:
        del scrubbing
        duration = float(
            self._current_clip().get("duration_sec", 0.0) if self._current_clip() else 0.0
        )
        self._time_label.config(
            text=f"{format_duration(sec)} / {format_duration(duration)}"
        )
        if self._capcut:
            self._capcut.set_playhead(sec, force=True)
        self._timeline_scrub_active = False
        if not self._player:
            return
        self._player.set_scrubbing(False)
        self._player.seek(sec, show=True, immediate=True)

    def _update_segment_info(self) -> None:
        clip = self._current_clip()
        if not clip or not self._selected_segment_id:
            self._segment_info.config(text="")
            return
        seg = self._segment_in_clip(clip, self._selected_segment_id)
        if not seg:
            return
        phase = format_phase_label(str(seg.get("phase", "")))
        enabled = "aktiv" if seg.get("enabled", True) else "deaktiviert"
        self._segment_info.config(
            text=(
                f"{phase} · {enabled} · "
                f"{float(seg['trim_start']):.1f}s – {float(seg['trim_end']):.1f}s"
            ),
            fg="#ccc",
        )

    def _delete_clip(self, clip_id: str) -> None:
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return
        clip["deleted"] = True
        self._active_clips = [c for c in self._active_clips if str(c["id"]) != clip_id]
        self._trash_clips = [c for c in self._project.get("clips", []) if c.get("deleted")]
        if self._selected_id == clip_id:
            self._selected_id = self._active_clips[0]["id"] if self._active_clips else None
            self._selected_segment_id = None
        self._refresh_clip_list()
        if self._selected_id:
            self._select_clip(self._selected_id)

    def _restore_clip(self, clip_id: str) -> None:
        clip = self._clip_by_id.get(clip_id)
        if not clip:
            return
        clip["deleted"] = False
        self._active_clips = [c for c in self._project.get("clips", []) if not c.get("deleted")]
        self._trash_clips = [c for c in self._project.get("clips", []) if c.get("deleted")]
        self._refresh_clip_list()

    def _on_drag_start(self, clip_id: str) -> None:
        self._drag_id = clip_id

    def _on_drag_motion(self, clip_id: str, y_root: int) -> None:
        if not self._drag_id:
            return
        target_index = self._index_at_y(y_root)
        if target_index is None:
            return
        current_index = next(
            (i for i, c in enumerate(self._active_clips) if str(c["id"]) == clip_id),
            None,
        )
        if current_index is None or current_index == target_index:
            return
        clip = self._active_clips.pop(current_index)
        self._active_clips.insert(target_index, clip)
        self._refresh_clip_list()

    def _index_at_y(self, y_root: int) -> Optional[int]:
        for idx, clip in enumerate(self._active_clips):
            tile = self._tiles.get(str(clip["id"]))
            if not tile:
                continue
            top = tile.winfo_rooty()
            bottom = top + tile.winfo_height()
            if top <= y_root <= bottom:
                return idx
        return len(self._active_clips) - 1 if self._active_clips else None

    def _toggle_play(self) -> None:
        if not self._player:
            return
        self._player.toggle_play()

    def _on_play_state_change(self, playing: bool) -> None:
        self._play_btn.config(text="⏸" if playing else "▶")

    def _on_player_time(self, pos: float, duration: float) -> None:
        self._time_label.config(text=f"{format_duration(pos)} / {format_duration(duration)}")
        if (
            self._capcut
            and self._player
            and not self._player._scrubbing
            and not self._edge_trim_active
        ):
            now = time.monotonic()
            if now - self._last_playhead_sync < 0.08:
                return
            self._last_playhead_sync = now
            self._capcut.set_playhead(pos, force=False)

    def _count_export_segments(self) -> int:
        from src.media_ai.phase_segments import expand_clips_to_export_segments

        return len(expand_clips_to_export_segments(self._active_clips))

    def _on_apply_click(self) -> None:
        if not self._active_clips:
            messagebox.showwarning("Keine Clips", "Es sind keine aktiven Clips vorhanden.", parent=self)
            return
        n_segments = self._count_export_segments()
        if n_segments == 0:
            messagebox.showwarning(
                "Keine aktiven Phasen",
                "Aktiviere mindestens eine Phase oder lösche keine Phasen vollständig.",
                parent=self,
            )
            return
        if not messagebox.askyesno(
            "Schnitte übernehmen",
            f"{len(self._active_clips)} Quelldatei(en) werden getrimmt und neu importiert "
            f"({n_segments} Schnittblock(s)).",
            parent=self,
        ):
            return
        self.confirmed = True
        self.exported_project = copy.deepcopy(self._project)
        self.export_segments = copy.deepcopy(self._active_clips)
        self._cleanup()
        self._on_apply(self.exported_project, self.export_segments)
        if self._embedded:
            return
        top = self.winfo_toplevel()
        if isinstance(top, tk.Toplevel):
            try:
                top.grab_release()
            except tk.TclError:
                pass
            top.destroy()

    def _on_close(self) -> None:
        if self._on_cancel:
            self._on_cancel()
        self._cleanup()
        if self._embedded:
            return
        top = self.winfo_toplevel()
        if isinstance(top, tk.Toplevel):
            try:
                top.grab_release()
            except tk.TclError:
                pass
            top.destroy()

    def _cleanup(self) -> None:
        if self._player:
            self._player.close()


class VideoCutReviewDialog(tk.Toplevel):
    """Modaler Dialog für den KI-Videoschnitt-Review."""

    def __init__(
        self,
        master,
        project: dict,
        *,
        on_apply: Callable[[dict, List[dict]], None],
        on_cancel: Optional[Callable[[], None]] = None,
        on_export: Optional[Callable[[dict, List[dict]], None]] = None,
        title: str = "KI-Videoschnitt – Review",
        sample_interval: float = 1.0,
    ) -> None:
        super().__init__(master)
        self.withdraw()
        self.title(title)
        self.geometry("1280x820")
        self.minsize(1024, 680)
        self.transient(master)
        self.grab_set()

        self.confirmed = False
        self.exported_project: Optional[dict] = None
        self.export_segments: List[dict] = []

        self._panel = VideoCutReviewPanel(
            self,
            project,
            on_apply=on_apply,
            on_export=on_export,
            on_cancel=on_cancel,
            sample_interval=sample_interval,
            embedded=False,
        )
        self._panel.pack(fill=tk.BOTH, expand=True)
        self.confirmed = self._panel.confirmed
        self.exported_project = self._panel.exported_project
        self.export_segments = self._panel.export_segments

        self._center_over_parent(master)
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._panel._on_close)

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

    def show(self) -> None:
        self.wait_window()
        self.confirmed = self._panel.confirmed
        self.exported_project = self._panel.exported_project
        self.export_segments = self._panel.export_segments


def run_video_cut_review(
    master,
    project: dict,
    on_apply: Callable[[dict, List[dict]], None],
    *,
    sample_interval: float = 1.0,
    on_export: Optional[Callable[[dict, List[dict]], None]] = None,
) -> bool:
    """Review-Dialog; ``on_apply`` übernimmt die geschnittenen Clips (z. B. Re-Import)."""
    dialog = VideoCutReviewDialog(
        master,
        project,
        on_apply=on_apply,
        on_export=on_export,
        sample_interval=sample_interval,
    )
    dialog.show()
    return bool(dialog._panel.confirmed)
