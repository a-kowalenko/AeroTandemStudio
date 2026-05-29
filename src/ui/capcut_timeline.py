"""CapCut-ähnliche Phasen-Timeline und schneller OpenCV-Player."""

from __future__ import annotations

import threading
import time
import tkinter as tk
from typing import Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageTk

PHASE_COLORS: Dict[str, str] = {
    "ground_interview": "#8e6bb8",
    "briefing": "#7b6d5a",
    "boarding": "#4a90d9",
    "takeoff": "#5ba3c9",
    "climb": "#3d7ea6",
    "door_prep": "#e8a838",
    "door": "#f0b429",
    "exit": "#e85d4c",
    "freefall": "#00b4d8",
    "deployment": "#48cae4",
    "canopy": "#2ec4b6",
    "landing": "#52b788",
    "final_interview": "#9b5de5",
    "unknown": "#6c757d",
}

SNAP_COLOR = "#4ade80"
SNAP_PULSE_COLOR = "#86efac"


def phase_color(phase: str) -> str:
    return PHASE_COLORS.get((phase or "unknown").strip().lower(), "#5c6bc0")


class FastVideoPlayer:
    """
    OpenCV-Player: sequentielles Abspielen, Hintergrund-Decode beim Seek,
    gedrosselte UI-Updates.
    """

    MAX_PREVIEW_FPS = 12
    MAX_DISPLAY_WIDTH = 640
    SCRUB_DEBOUNCE_MS = 140
    UI_CALLBACK_INTERVAL = 0.1

    def __init__(self, label: tk.Label) -> None:
        self._label = label
        self._cap: Optional[cv2.VideoCapture] = None
        self._cap_lock = threading.Lock()
        self._path: Optional[str] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._playing = False
        self._job: Optional[str] = None
        self._scrub_job: Optional[str] = None
        self._position_sec = 0.0
        self._duration_sec = 0.0
        self._fps = 30.0
        self._frame_count = 0
        self._display_size: Optional[Tuple[int, int]] = None
        self._on_time_update: Optional[Callable[[float, float], None]] = None
        self._on_play_state: Optional[Callable[[bool], None]] = None
        self._pending_scrub_sec: Optional[float] = None
        self._scrubbing = False
        self._last_ui_callback = 0.0
        self._decode_generation = 0

    def set_time_callback(self, callback: Callable[[float, float], None]) -> None:
        self._on_time_update = callback

    def set_play_state_callback(self, callback: Callable[[bool], None]) -> None:
        self._on_play_state = callback

    def load(self, path: str) -> None:
        self.stop()
        with self._cap_lock:
            if self._cap:
                self._cap.release()
            self._path = path
            self._cap = cv2.VideoCapture(path)
            if not self._cap.isOpened():
                raise ValueError(f"Video nicht lesbar: {path}")
            try:
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
            except Exception:
                pass
            self._fps = max(1.0, float(self._cap.get(cv2.CAP_PROP_FPS) or 30.0))
            self._frame_count = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._duration_sec = self._frame_count / self._fps if self._frame_count > 0 else 0.0
        self._display_size = None
        self._position_sec = 0.0
        self._decode_generation += 1
        self._request_frame(0.0, immediate=True)

    def seek(self, sec: float, *, show: bool = True, immediate: bool = False) -> None:
        if not self._cap or not show:
            if self._cap:
                self._position_sec = max(0.0, min(float(sec), self._duration_sec))
            return

        sec = max(0.0, min(float(sec), self._duration_sec))
        self._position_sec = sec

        if self._playing and not immediate:
            return

        if immediate or not self._scrubbing:
            self._pending_scrub_sec = None
            self._cancel_scrub_job()
            self._request_frame(sec, immediate=True)
            return

        self._pending_scrub_sec = sec
        self._schedule_scrub()

    def set_scrubbing(self, active: bool) -> None:
        was = self._scrubbing
        self._scrubbing = active
        if active:
            self._playing = False
            self._cancel_play_job()
            self._cancel_scrub_job()
            self._pending_scrub_sec = None
            self._decode_generation += 1
        elif was:
            sec = self._pending_scrub_sec if self._pending_scrub_sec is not None else self._position_sec
            self._pending_scrub_sec = None
            self._cancel_scrub_job()
            self._decode_generation += 1
            self._request_frame(sec, immediate=True)

    def toggle_play(self) -> bool:
        if not self._cap:
            return False
        self._playing = not self._playing
        if self._playing:
            self._cancel_scrub_job()
            self._pending_scrub_sec = None
            with self._cap_lock:
                if self._cap:
                    idx = int(self._position_sec * self._fps)
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, idx))
            self._notify_play_state(True)
            self._tick()
        else:
            self._cancel_play_job()
            self._notify_play_state(False)
        return self._playing

    def _notify_play_state(self, playing: bool) -> None:
        if self._on_play_state:
            self._on_play_state(playing)

    def stop(self) -> None:
        self._playing = False
        self._cancel_scrub_job()
        self._cancel_play_job()
        self._pending_scrub_sec = None
        self._decode_generation += 1

    def close(self) -> None:
        self.stop()
        with self._cap_lock:
            if self._cap:
                self._cap.release()
                self._cap = None

    def _cancel_play_job(self) -> None:
        if self._job and self._label.winfo_exists():
            try:
                self._label.after_cancel(self._job)
            except tk.TclError:
                pass
        self._job = None

    def _cancel_scrub_job(self) -> None:
        if self._scrub_job and self._label.winfo_exists():
            try:
                self._label.after_cancel(self._scrub_job)
            except tk.TclError:
                pass
        self._scrub_job = None

    def _schedule_scrub(self) -> None:
        if self._scrub_job:
            return

        def apply() -> None:
            self._scrub_job = None
            if self._pending_scrub_sec is not None and self._scrubbing:
                sec = self._pending_scrub_sec
                self._request_frame(sec, immediate=False)

        try:
            self._scrub_job = self._label.after(self.SCRUB_DEBOUNCE_MS, apply)
        except tk.TclError:
            pass

    def _request_frame(self, sec: float, *, immediate: bool) -> None:
        gen = self._decode_generation
        threading.Thread(
            target=self._decode_worker,
            args=(sec, gen),
            daemon=True,
        ).start()

    def _decode_worker(self, sec: float, generation: int) -> None:
        frame = self._read_frame_at(sec)
        if frame is None or generation != self._decode_generation:
            return

        def apply() -> None:
            if generation != self._decode_generation:
                return
            try:
                if not self._label.winfo_exists():
                    return
                self._paint_frame(frame)
                self._position_sec = sec
                self._emit_time_update(force=True)
            except tk.TclError:
                pass

        try:
            self._label.after(0, apply)
        except tk.TclError:
            pass

    def _read_frame_at(self, sec: float) -> Optional[np.ndarray]:
        with self._cap_lock:
            if not self._cap:
                return None
            frame_idx = int(sec * self._fps)
            frame_idx = max(0, min(frame_idx, max(0, self._frame_count - 1)))
            self._cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = self._cap.read()
            if not ok or frame is None:
                return None
            return frame

    def _tick(self) -> None:
        if not self._playing or not self._cap or self._scrubbing:
            return

        with self._cap_lock:
            if not self._cap:
                return
            ok, frame = self._cap.read()
            pos_msec = float(self._cap.get(cv2.CAP_PROP_POS_MSEC) or 0) if ok else 0.0

        if not ok or frame is None:
            self._playing = False
            self._notify_play_state(False)
            return

        if pos_msec > 0:
            self._position_sec = min(self._duration_sec, pos_msec / 1000.0)
        else:
            self._position_sec = min(
                self._duration_sec,
                self._position_sec + 1.0 / self.MAX_PREVIEW_FPS,
            )
        self._paint_frame(frame)
        self._emit_time_update(force=False)

        if self._position_sec >= self._duration_sec - 1e-3:
            self._playing = False
            self._notify_play_state(False)
            return

        delay = max(1, int(1000 / self.MAX_PREVIEW_FPS))
        try:
            self._job = self._label.after(delay, self._tick)
        except tk.TclError:
            pass

    def _emit_time_update(self, *, force: bool) -> None:
        if not self._on_time_update:
            return
        now = time.monotonic()
        if not force and now - self._last_ui_callback < self.UI_CALLBACK_INTERVAL:
            return
        self._last_ui_callback = now
        self._on_time_update(self._position_sec, self._duration_sec)

    def _paint_frame(self, frame: np.ndarray) -> None:
        max_w = min(self.MAX_DISPLAY_WIDTH, max(320, self._label.winfo_width() or 640))
        max_h = max(180, self._label.winfo_height() or 360)

        if self._display_size is None:
            h, w = frame.shape[:2]
            scale = min(max_w / max(w, 1), max_h / max(h, 1), 1.0)
            self._display_size = (max(1, int(w * scale)), max(1, int(h * scale)))

        dw, dh = self._display_size
        if frame.shape[1] != dw or frame.shape[0] != dh:
            frame = cv2.resize(frame, (dw, dh), interpolation=cv2.INTER_NEAREST)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
        self._label.configure(image=self._photo, text="")


class CapCutTimeline(tk.Canvas):
    """
    Horizontale Multi-Phasen-Timeline mit Magnet-Snap an Nachbar-Kanten
  und visuellem „Verbunden“-Feedback.
    """

    SNAP_MIN_SEC = 0.18
    SNAP_UNLOCK_FACTOR = 1.75

    def __init__(
        self,
        master,
        *,
        duration_sec: float = 10.0,
        segments: Optional[List[dict]] = None,
        on_seek: Optional[Callable[[float, bool], None]] = None,
        on_scrub_begin: Optional[Callable[[], None]] = None,
        on_scrub_move: Optional[Callable[[float], None]] = None,
        on_segment_change: Optional[Callable[[str, float, float, bool], None]] = None,
        on_select_segment: Optional[Callable[[str], None]] = None,
        on_snap: Optional[Callable[[float, bool], None]] = None,
        **kwargs,
    ) -> None:
        super().__init__(master, height=88, highlightthickness=0, bg="#1e1e1e", **kwargs)
        self._duration = max(0.1, float(duration_sec))
        self._segments: List[dict] = list(segments or [])
        self._on_seek = on_seek
        self._on_scrub_begin = on_scrub_begin
        self._on_scrub_move = on_scrub_move
        self._on_segment_change = on_segment_change
        self._on_select_segment = on_select_segment
        self._on_snap = on_snap
        self._selected_id: Optional[str] = None
        self._playhead_sec = 0.0
        self._pad = 8
        self._drag_mode: Optional[str] = None
        self._drag_segment_id: Optional[str] = None
        self._magnet_locked: Optional[float] = None
        self._snap_active = False
        self._snap_joint: Optional[float] = None
        self._snap_pulse = 0
        self._last_snap_notify = False
        self._playhead_drag = False
        self._ph_line: Optional[int] = None
        self._ph_tri: Optional[int] = None
        self._redraw_job: Optional[str] = None
        self._seek_notify_job: Optional[str] = None
        self._pending_seek_notify: Optional[float] = None

        self.bind("<Configure>", lambda _e: self._request_redraw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_duration(self, duration_sec: float) -> None:
        self._duration = max(0.1, float(duration_sec))
        self._redraw()

    def set_segments(self, segments: List[dict]) -> None:
        self._segments = list(segments)
        if self._segments and self._selected_id is None:
            self._selected_id = str(self._segments[0].get("segment_id", ""))
        self._redraw()

    def set_playhead(self, sec: float, *, force: bool = False) -> None:
        new = max(0.0, min(float(sec), self._duration))
        if not force and not self._playhead_drag and abs(new - self._playhead_sec) < 0.03:
            return
        self._playhead_sec = new
        if self._playhead_drag and self._ph_line is not None:
            self._update_playhead_only()
        else:
            self._request_redraw()

    def select_segment(self, segment_id: Optional[str]) -> None:
        self._selected_id = segment_id
        self._request_redraw()

    def _snap_threshold_sec(self) -> float:
        return max(self.SNAP_MIN_SEC, self._duration * 0.012)

    def _time_to_x(self, sec: float) -> float:
        w = max(1, self.winfo_width() - 2 * self._pad)
        return self._pad + (sec / self._duration) * w

    def _x_to_time(self, x: float) -> float:
        w = max(1, self.winfo_width() - 2 * self._pad)
        ratio = (x - self._pad) / w
        return max(0.0, min(self._duration, ratio * self._duration))

    def _segment_by_id(self, sid: str) -> Optional[dict]:
        for seg in self._segments:
            if str(seg.get("segment_id")) == sid:
                return seg
        return None

    def _snap_targets(self, segment_id: str) -> List[float]:
        targets = [0.0, self._duration]
        for seg in self._segments:
            if not seg.get("enabled", True):
                continue
            if str(seg.get("segment_id")) == segment_id:
                continue
            targets.append(float(seg["trim_start"]))
            targets.append(float(seg["trim_end"]))
        return targets

    def _apply_magnetic_snap(self, raw_t: float, targets: List[float]) -> Tuple[float, bool]:
        threshold = self._snap_threshold_sec()
        unlock = threshold * self.SNAP_UNLOCK_FACTOR

        if self._magnet_locked is not None:
            if abs(raw_t - self._magnet_locked) <= unlock:
                return round(self._magnet_locked, 1), True
            self._magnet_locked = None

        nearest: Optional[float] = None
        nearest_dist = threshold
        for target in targets:
            dist = abs(raw_t - target)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest = target

        if nearest is None:
            return round(raw_t, 1), False

        blend = 1.0 - (nearest_dist / threshold)
        strength = 0.4 + 0.6 * blend
        pulled = raw_t + (nearest - raw_t) * strength

        if nearest_dist <= threshold * 0.2:
            pulled = nearest
            if self._magnet_locked != nearest:
                self._magnet_locked = nearest
                self._snap_pulse = 10
            return round(pulled, 1), True

        return round(pulled, 1), True

    def _notify_snap(self, joint: Optional[float], active: bool) -> None:
        if active == self._last_snap_notify and (joint is None or joint == self._snap_joint):
            return
        self._last_snap_notify = active
        self._snap_joint = joint if active else None
        if self._on_snap:
            self._on_snap(joint or 0.0, active)

    def _hit_test(self, x: float, y: float) -> Tuple[Optional[str], Optional[str]]:
        if y < 18:
            return "ruler", None

        for seg in self._segments:
            if not seg.get("enabled", True):
                continue
            sid = str(seg.get("segment_id"))
            x0 = self._time_to_x(float(seg["trim_start"]))
            x1 = self._time_to_x(float(seg["trim_end"]))
            if abs(x - x0) <= 7:
                return "edge_start", sid
            if abs(x - x1) <= 7:
                return "edge_end", sid
            if x0 <= x <= x1:
                return "block", sid

        px = self._time_to_x(self._playhead_sec)
        if abs(x - px) <= 5:
            return "playhead", None
        return "ruler", None

    def _update_playhead_visual(self) -> None:
        if not self._ph_line or not self._ph_tri:
            self._request_redraw()
            return
        h = max(1, self.winfo_height())
        px = self._time_to_x(self._playhead_sec)
        try:
            self.coords(self._ph_line, px, 16, px, h - 12)
            self.coords(self._ph_tri, px, 14, px - 6, 20, px + 6, 20)
        except tk.TclError:
            self._request_redraw()

    def _update_playhead_only(self) -> None:
        self._update_playhead_visual()

    def _request_redraw(self) -> None:
        if self._redraw_job:
            return

        def do() -> None:
            self._redraw_job = None
            self._redraw()

        try:
            self._redraw_job = self.after(33, do)
        except tk.TclError:
            pass

    def _notify_seek_throttled(self, sec: float, scrubbing: bool) -> None:
        if not self._on_seek:
            return
        if not scrubbing:
            self._pending_seek_notify = None
            if self._seek_notify_job:
                try:
                    self.after_cancel(self._seek_notify_job)
                except tk.TclError:
                    pass
                self._seek_notify_job = None
            self._on_seek(sec, False)
            return

        self._pending_seek_notify = sec

        def fire() -> None:
            self._seek_notify_job = None
            if self._pending_seek_notify is not None and self._on_seek:
                self._on_seek(self._pending_seek_notify, True)

        if self._seek_notify_job:
            return
        try:
            self._seek_notify_job = self.after(100, fire)
        except tk.TclError:
            pass

    def _redraw(self) -> None:
        if self._snap_pulse > 0:
            self._snap_pulse -= 1

        self._ph_line = None
        self._ph_tri = None
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w <= 2:
            return

        self.create_rectangle(0, 0, w, h, fill="#1e1e1e", outline="")
        track_top, track_bot = 20, h - 14
        self.create_rectangle(self._pad, track_top, w - self._pad, track_bot, fill="#2a2a2a", outline="#3a3a3a")

        for seg in self._segments:
            sid = str(seg.get("segment_id"))
            x0 = self._time_to_x(float(seg["trim_start"]))
            x1 = self._time_to_x(float(seg["trim_end"]))
            if x1 <= x0 + 2:
                continue
            color = phase_color(str(seg.get("phase", "unknown")))
            enabled = bool(seg.get("enabled", True))
            fill = color if enabled else "#4a4a4a"
            outline = "#ffffff" if sid == self._selected_id else color
            width = 2 if sid == self._selected_id else 0
            self.create_rectangle(x0, 22, x1, track_bot - 2, fill=fill, outline=outline, width=width)
            label = str(seg.get("phase", ""))[:12]
            self.create_text(
                (x0 + x1) / 2,
                (22 + track_bot - 2) / 2,
                text=label,
                fill="#fff",
                font=("Arial", 8, "bold"),
            )

        if self._snap_active and self._snap_joint is not None:
            jx = self._time_to_x(self._snap_joint)
            pulse_w = 5 if self._snap_pulse > 0 else 3
            color = SNAP_PULSE_COLOR if self._snap_pulse > 0 else SNAP_COLOR
            self.create_line(jx, track_top - 2, jx, track_bot + 2, fill=color, width=pulse_w)
            self.create_oval(jx - 4, track_top - 6, jx + 4, track_top + 2, fill=color, outline="")

        px = self._time_to_x(self._playhead_sec)
        self._ph_line = self.create_line(px, 16, px, h - 12, fill="#ff3b30", width=2, tags="playhead")
        self._ph_tri = self.create_polygon(
            px, 14, px - 6, 20, px + 6, 20, fill="#ff3b30", outline="", tags="playhead"
        )

        step = max(1, int(self._duration // 8))
        for tick in range(0, int(self._duration) + 1, step):
            tx = self._time_to_x(float(tick))
            self.create_line(tx, 18, tx, 22, fill="#666")
            self.create_text(tx, 10, text=str(tick), fill="#aaa", font=("Arial", 7))

    def _on_press(self, event) -> None:
        mode, sid = self._hit_test(event.x, event.y)
        self._drag_segment_id = sid
        self._magnet_locked = None
        self._snap_active = False
        self._last_snap_notify = False

        if mode == "ruler":
            self._drag_mode = "playhead"
            self._playhead_drag = True
            t = self._x_to_time(event.x)
            self._playhead_sec = t
            self._update_playhead_visual()
            if self._on_scrub_begin:
                self._on_scrub_begin()
            if self._on_scrub_move:
                self._on_scrub_move(t)
            return
        if mode == "playhead":
            self._drag_mode = "playhead"
            self._playhead_drag = True
            if self._on_scrub_begin:
                self._on_scrub_begin()
            if self._on_scrub_move:
                self._on_scrub_move(self._playhead_sec)
            return
        if mode in ("edge_start", "edge_end") and sid:
            self._drag_mode = mode
            self._playhead_drag = False
            self._selected_id = sid
            if self._on_select_segment:
                self._on_select_segment(sid)
            self._redraw()
            return
        if mode == "block" and sid:
            self._selected_id = sid
            if self._on_select_segment:
                self._on_select_segment(sid)
            t = self._x_to_time(event.x)
            self._playhead_sec = t
            self._playhead_drag = True
            self._drag_mode = "playhead"
            self._update_playhead_visual()
            if self._on_scrub_begin:
                self._on_scrub_begin()
            if self._on_scrub_move:
                self._on_scrub_move(t)

    def _on_drag(self, event) -> None:
        if self._drag_mode == "playhead":
            t = round(self._x_to_time(event.x), 1)
            self._playhead_sec = t
            self._update_playhead_visual()
            if self._on_scrub_move:
                self._on_scrub_move(t)
            return

        seg = self._segment_by_id(self._drag_segment_id or "")
        if not seg:
            return

        raw_t = self._x_to_time(event.x)
        targets = self._snap_targets(str(seg.get("segment_id")))
        t, snapped = self._apply_magnetic_snap(raw_t, targets)
        self._snap_active = snapped
        self._notify_snap(self._magnet_locked if snapped else None, snapped)

        min_len = 0.2
        if self._drag_mode == "edge_start":
            end = float(seg["trim_end"])
            seg["trim_start"] = round(min(t, end - min_len), 1)
        elif self._drag_mode == "edge_end":
            start = float(seg["trim_start"])
            seg["trim_end"] = round(max(t, start + min_len), 1)

        if self._on_segment_change:
            self._on_segment_change(
                str(seg["segment_id"]),
                float(seg["trim_start"]),
                float(seg["trim_end"]),
                True,
            )
        self._playhead_sec = t
        self._request_redraw()

    def _on_release(self, event) -> None:
        self._playhead_drag = False
        if self._drag_mode == "playhead":
            t = round(self._x_to_time(event.x), 1)
            self._playhead_sec = t
            self._update_playhead_visual()
            if self._on_seek:
                self._on_seek(t, False)
        elif self._drag_mode in ("edge_start", "edge_end") and self._drag_segment_id:
            seg = self._segment_by_id(self._drag_segment_id)
            if seg and self._on_segment_change:
                self._on_segment_change(
                    str(seg["segment_id"]),
                    float(seg["trim_start"]),
                    float(seg["trim_end"]),
                    False,
                )
        if self._snap_active:
            self._snap_pulse = 6
        self._notify_snap(None, False)
        self._snap_active = False
        self._magnet_locked = None
        self._drag_mode = None
        self._drag_segment_id = None
        self._request_redraw()
