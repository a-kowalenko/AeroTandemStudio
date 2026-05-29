"""VLC-Player für den KI-Review-Dialog (Hardware-Decode), Fallback: OpenCV."""

from __future__ import annotations

import sys
import tkinter as tk
from typing import Callable, Optional, Protocol

vlc = None

try:
    from src.utils.path_helper import setup_vlc_paths

    setup_vlc_paths()
except ImportError:
    pass


class ReviewPlayer(Protocol):
    _scrubbing: bool
    _playing: bool

    def set_time_callback(self, callback: Callable[[float, float], None]) -> None: ...
    def set_play_state_callback(self, callback: Callable[[bool], None]) -> None: ...
    def load(self, path: str) -> None: ...
    def seek(self, sec: float, *, show: bool = True, immediate: bool = False) -> None: ...
    def set_scrubbing(self, active: bool) -> None: ...
    def toggle_play(self) -> bool: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


class VlcReviewPlayer:
    """VLC-Player: kein Seek während Scrub (verhindert UI-Freeze)."""

    POLL_MS = 120

    def __init__(self, container: tk.Frame) -> None:
        global vlc
        if vlc is None:
            import vlc as vlc_module

            vlc = vlc_module

        self._container = container
        self._frame = tk.Frame(container, bg="#000000")
        self._frame.pack(fill=tk.BOTH, expand=True)

        self._scrubbing = False
        self._playing = False
        self._position_sec = 0.0
        self._duration_sec = 0.0
        self._path: Optional[str] = None
        self._on_time_update: Optional[Callable[[float, float], None]] = None
        self._on_play_state: Optional[Callable[[bool], None]] = None
        self._poll_job: Optional[str] = None
        self._pending_scrub_sec: Optional[float] = None
        self._hwnd_bound = False
        self._was_playing_before_scrub = False
        self._vlc_callbacks: dict = {}
        vlc_args = [
            "--no-plugins-cache",
            "--ignore-config",
            "--no-xlib",
            "--quiet",
            "--no-video-title-show",
        ]
        self._vlc_instance = vlc.Instance(*vlc_args)
        self._player = self._vlc_instance.media_player_new()
        self._player.audio_set_volume(0)
        self._attach_vlc_events()

    def set_time_callback(self, callback: Callable[[float, float], None]) -> None:
        self._on_time_update = callback

    def set_play_state_callback(self, callback: Callable[[bool], None]) -> None:
        self._on_play_state = callback

    def _attach_vlc_events(self) -> None:
        events = self._player.event_manager()

        def schedule(fn: Callable[[], None]) -> None:
            if self._frame.winfo_exists():
                try:
                    self._frame.after(0, fn)
                except tk.TclError:
                    pass

        def on_playing(_event) -> None:
            schedule(lambda: self._set_playing(True))

        def on_paused(_event) -> None:
            schedule(lambda: self._set_playing(False))

        def on_stopped(_event) -> None:
            schedule(lambda: self._set_playing(False))

        self._vlc_callbacks = {
            "playing": on_playing,
            "paused": on_paused,
            "stopped": on_stopped,
        }
        events.event_attach(vlc.EventType.MediaPlayerPlaying, self._vlc_callbacks["playing"])
        events.event_attach(vlc.EventType.MediaPlayerPaused, self._vlc_callbacks["paused"])
        events.event_attach(vlc.EventType.MediaPlayerStopped, self._vlc_callbacks["stopped"])

    def _bind_hwnd(self) -> None:
        if self._hwnd_bound:
            return
        self._frame.update_idletasks()
        if sys.platform == "win32":
            self._player.set_hwnd(self._frame.winfo_id())
        elif sys.platform == "darwin":
            self._player.set_nsobject(int(self._frame.winfo_id()))
        else:
            self._player.set_xwindow(int(self._frame.winfo_id()))
        self._hwnd_bound = True

    def load(self, path: str) -> None:
        self.stop()
        self._path = path
        self._bind_hwnd()
        media = self._vlc_instance.media_new(path)
        media.parse()
        self._player.set_media(media)
        length_ms = media.get_duration()
        self._duration_sec = max(0.0, length_ms / 1000.0) if length_ms and length_ms > 0 else 0.0
        self.seek(0.0, show=True, immediate=True)

    def seek(self, sec: float, *, show: bool = True, immediate: bool = False) -> None:
        del immediate
        if not self._player:
            return
        sec = max(0.0, min(float(sec), self._duration_sec if self._duration_sec > 0 else sec))
        self._position_sec = sec

        if self._scrubbing:
            self._pending_scrub_sec = sec
            return

        if not show:
            return

        self._apply_vlc_time(sec)

    def _apply_vlc_time(self, sec: float) -> None:
        try:
            if self._duration_sec > 0:
                ratio = max(0.0, min(1.0, sec / self._duration_sec))
                self._player.set_position(ratio)
            else:
                self._player.set_time(int(sec * 1000))
        except Exception:
            pass
        self._position_sec = sec
        if self._on_time_update and not self._scrubbing:
            self._on_time_update(self._position_sec, self._duration_sec)

    def _pause_for_scrub(self) -> None:
        if self._playing:
            try:
                self._player.pause()
            except Exception:
                pass
            self._set_playing(False)

    def _finish_scrub(self, sec: float) -> None:
        self._apply_vlc_time(sec)
        if self._was_playing_before_scrub:
            try:
                self._player.play()
            except Exception:
                pass
            self._set_playing(True)
            self._start_poll()

    def set_scrubbing(self, active: bool) -> None:
        if active and not self._scrubbing:
            self._was_playing_before_scrub = self._playing
            self._pending_scrub_sec = self._position_sec
            self._scrubbing = True
            if self._playing and self._frame.winfo_exists():
                self._frame.after_idle(self._pause_for_scrub)
            return
        if not active and self._scrubbing:
            self._scrubbing = False
            sec = self._pending_scrub_sec if self._pending_scrub_sec is not None else self._position_sec
            self._pending_scrub_sec = None
            if self._frame.winfo_exists():
                self._frame.after_idle(lambda s=sec: self._finish_scrub(s))
            return
        self._scrubbing = active

    def toggle_play(self) -> bool:
        self._bind_hwnd()
        if self._playing:
            self._player.pause()
            self._set_playing(False)
        else:
            self._player.play()
            self._set_playing(True)
            self._start_poll()
        return self._playing

    def stop(self) -> None:
        self._set_playing(False)
        self._cancel_poll()
        if self._player:
            self._player.stop()

    def close(self) -> None:
        self.stop()
        try:
            events = self._player.event_manager()
            events.event_detach(vlc.EventType.MediaPlayerPlaying)
            events.event_detach(vlc.EventType.MediaPlayerPaused)
            events.event_detach(vlc.EventType.MediaPlayerStopped)
        except Exception:
            pass
        try:
            self._player.release()
        except Exception:
            pass
        try:
            self._vlc_instance.release()
        except Exception:
            pass

    def _set_playing(self, playing: bool) -> None:
        if self._playing == playing:
            return
        self._playing = playing
        if not playing:
            self._cancel_poll()
        if self._on_play_state:
            self._on_play_state(playing)

    def _sync_position_from_vlc(self) -> bool:
        if not self._player:
            return False
        ms = self._player.get_time()
        if ms is not None and ms >= 0:
            self._position_sec = min(self._duration_sec or ms / 1000.0, ms / 1000.0)
            return True
        pos = self._player.get_position()
        if pos is not None and pos >= 0 and self._duration_sec > 0:
            self._position_sec = min(self._duration_sec, pos * self._duration_sec)
            return True
        return False

    def _start_poll(self) -> None:
        self._cancel_poll()
        self._poll_tick()

    def _cancel_poll(self) -> None:
        if self._poll_job and self._frame.winfo_exists():
            try:
                self._frame.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        self._poll_job = None

    def _poll_tick(self) -> None:
        if not self._frame.winfo_exists():
            return
        if self._playing and not self._scrubbing:
            self._sync_position_from_vlc()
            if self._on_time_update:
                self._on_time_update(self._position_sec, self._duration_sec)
            state = self._player.get_state()
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.NothingSpecial):
                self._set_playing(False)
        if self._playing:
            self._poll_job = self._frame.after(self.POLL_MS, self._poll_tick)
        else:
            self._poll_job = None


def create_review_player(container: tk.Frame) -> ReviewPlayer:
    try:
        return VlcReviewPlayer(container)
    except Exception as exc:
        print(f"[Review] VLC nicht verfügbar ({exc}), nutze OpenCV-Fallback.")
        from src.ui.capcut_timeline import FastVideoPlayer

        label = tk.Label(container, bg="#000000", text="")
        label.pack(fill=tk.BOTH, expand=True)
        return FastVideoPlayer(label)
