import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class _MediaAISectionWidgets:
    frame: tk.LabelFrame
    status_label: tk.Label
    progress_label: tk.Label
    file_label: tk.Label
    active_label: tk.Label
    progress: ttk.Progressbar
    active_label_packed: bool = field(default=False)
    visible: bool = field(default=False)


class LoadingWindow(tk.Toplevel):
    """
    Ein einfaches "modal" Fenster, das eine Ladeanimation anzeigt,
    während im Hintergrund ein Thread arbeitet.
    """

    _SECTION_HEIGHT = 155
    _DUAL_WIDTH = 520

    def __init__(
        self,
        master,
        text="Bitte warten...",
        on_cancel: Optional[Callable[[], None]] = None,
        *,
        detail_mode: bool = False,
        grab_focus: bool = True,
        media_ai_dual: bool = False,
    ):
        super().__init__(master)
        self.title("Verarbeitung")
        self._on_cancel = on_cancel
        self._detail_mode = detail_mode
        self._media_ai_dual = media_ai_dual
        self._sections: Dict[str, _MediaAISectionWidgets] = {}
        self._sections_container: Optional[tk.Frame] = None
        self._dual_pos_x = 0
        self._dual_pos_y = 0

        if media_ai_dual:
            self.title("KI-Analyse")
            width = self._DUAL_WIDTH
            height = self._SECTION_HEIGHT
            self.geometry(f"{width}x{height}")
            self.resizable(False, False)
            self.transient(master)
            if grab_focus:
                self.grab_set()
            self._center_over_master(master, width, height)
            self._sections_container = tk.Frame(self)
            self._sections_container.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
            if on_cancel is not None:
                self.cancel_button = tk.Button(
                    self,
                    text="Abbrechen",
                    command=self._handle_cancel,
                    width=12,
                )
                self.cancel_button.pack(pady=(0, 10))
            self.update_idletasks()
            return

        width = 520 if detail_mode else 300
        height = 220 if detail_mode and on_cancel else (195 if detail_mode else (155 if on_cancel else 120))
        self.geometry(f"{width}x{height}")
        self.resizable(False, False)

        self.transient(master)
        if grab_focus:
            self.grab_set()

        self._center_over_master(master, width, height)

        if detail_mode:
            initial_status = text if text else "Prüfe auf QR-Code"
            self.status_label = tk.Label(
                self,
                text=initial_status,
                padx=20,
                pady=2,
                font=("Helvetica", 10),
            )
            self.status_label.pack(pady=(10, 0))

            self.progress_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 9),
                fg="#555555",
            )
            self.progress_label.pack()

            self.file_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 11, "bold"),
                wraplength=480,
                justify="center",
            )
            self.file_label.pack(pady=(4, 0))

            self.active_label = tk.Label(
                self,
                text="",
                padx=20,
                pady=2,
                font=("Helvetica", 10),
                wraplength=480,
                justify="center",
                fg="#333333",
            )
            self._active_label_packed = False
        else:
            self.label = tk.Label(self, text=text, padx=20, pady=10, font=("Helvetica", 10))
            self.label.pack(pady=(10, 0))

        bar_width = 460 if detail_mode else 260
        if detail_mode:
            self.progress = ttk.Progressbar(
                self,
                mode="determinate",
                length=bar_width,
                maximum=100,
            )
        else:
            self.progress = ttk.Progressbar(
                self,
                mode="indeterminate",
                length=bar_width,
            )
        self.progress.pack(pady=10, padx=20, fill="x")
        if not detail_mode:
            self.progress.start(15)

        if on_cancel is not None:
            self.cancel_button = tk.Button(
                self,
                text="Abbrechen",
                command=self._handle_cancel,
                width=12,
            )
            self.cancel_button.pack(pady=(0, 10))

        if detail_mode:
            initial_status = text if text else "Prüfe auf QR-Code"
            self.update_qr_progress(
                initial_status,
                "",
                "—",
                completed_count=0,
                total=1,
            )

        self.update_idletasks()

    def _center_over_master(self, master, width: int, height: int) -> None:
        master_x = master.winfo_x()
        master_y = master.winfo_y()
        master_w = master.winfo_width()
        master_h = master.winfo_height()
        pos_x = master_x + (master_w - width) // 2
        pos_y = master_y + (master_h - height) // 2
        self._dual_pos_x = pos_x
        self._dual_pos_y = pos_y
        self.geometry(f"+{pos_x}+{pos_y}")

    def _ensure_media_ai_section(self, section: str) -> _MediaAISectionWidgets:
        existing = self._sections.get(section)
        if existing is not None:
            return existing

        titles = {"photo": "Foto-KI", "video": "Video-KI"}
        frame = tk.LabelFrame(
            self._sections_container,
            text=titles.get(section, section),
            padx=8,
            pady=6,
        )
        status_label = tk.Label(frame, text="", font=("Helvetica", 10), anchor="w")
        status_label.pack(fill="x")

        progress_label = tk.Label(
            frame,
            text="",
            font=("Helvetica", 9),
            fg="#555555",
            anchor="w",
        )
        progress_label.pack(fill="x")

        file_label = tk.Label(
            frame,
            text="",
            font=("Helvetica", 11, "bold"),
            wraplength=480,
            justify="left",
            anchor="w",
        )
        file_label.pack(fill="x", pady=(4, 0))

        active_label = tk.Label(
            frame,
            text="",
            font=("Helvetica", 10),
            wraplength=480,
            justify="left",
            anchor="w",
            fg="#333333",
        )

        progress = ttk.Progressbar(frame, mode="determinate", length=460, maximum=100)
        progress.pack(fill="x", pady=(8, 0))

        widgets = _MediaAISectionWidgets(
            frame=frame,
            status_label=status_label,
            progress_label=progress_label,
            file_label=file_label,
            active_label=active_label,
            progress=progress,
        )
        self._sections[section] = widgets
        return widgets

    def set_media_ai_section_active(self, section: str, active: bool) -> None:
        """Zeigt oder verbirgt einen Foto-/Video-KI-Abschnitt im Dual-Dialog."""
        if not self._media_ai_dual:
            return

        widgets = self._ensure_media_ai_section(section)
        if active and not widgets.visible:
            widgets.frame.pack(fill="x", pady=(0, 8))
            widgets.visible = True
        elif not active and widgets.visible:
            widgets.frame.pack_forget()
            widgets.visible = False
            widgets.active_label_packed = False

        self._resize_dual_window()

    def _resize_dual_window(self) -> None:
        visible_count = sum(1 for section in self._sections.values() if section.visible)
        if visible_count <= 0:
            visible_count = 1
        cancel_extra = 42 if self._on_cancel is not None else 0
        height = 24 + (visible_count * self._SECTION_HEIGHT) + cancel_extra
        self.geometry(f"{self._DUAL_WIDTH}x{height}+{self._dual_pos_x}+{self._dual_pos_y}")
        self.update_idletasks()

    @staticmethod
    def _format_mmss(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def _apply_qr_progress_to_widgets(
        self,
        widgets: _MediaAISectionWidgets,
        status: str,
        progress_text: str,
        primary_file: str,
        active_files: Optional[List[str]] = None,
        *,
        completed_count: Optional[int] = None,
        total: Optional[int] = None,
    ) -> None:
        widgets.status_label.config(text=status)
        widgets.progress_label.config(text=progress_text)

        if completed_count is not None and total is not None and total > 0:
            percent = min(100.0, max(0.0, (completed_count / total) * 100))
            widgets.progress.config(mode="determinate", maximum=100)
            widgets.progress["value"] = percent

        active = [f for f in (active_files or []) if f]
        if len(active) > 1:
            widgets.file_label.config(text=active[0])
            widgets.active_label.config(text="\n".join(active[1:]))
            if not widgets.active_label_packed:
                widgets.active_label.pack(fill="x", pady=(0, 4))
                widgets.active_label_packed = True
        else:
            display_name = primary_file or (active[0] if active else "")
            widgets.file_label.config(text=display_name)
            if widgets.active_label_packed:
                widgets.active_label.pack_forget()
                widgets.active_label_packed = False

    def _apply_video_progress_to_widgets(
        self,
        widgets: _MediaAISectionWidgets,
        status: str,
        *,
        videos_done: int,
        videos_total: int,
        seconds_done: float,
        seconds_total: float,
        filename: str,
    ) -> None:
        videos_total = max(1, int(videos_total))
        videos_done = max(0, min(int(videos_done), videos_total))
        seconds_total = max(0.1, float(seconds_total))
        seconds_done = max(0.0, min(float(seconds_done), seconds_total))

        current_video = min(videos_done + 1, videos_total) if videos_done < videos_total else videos_total
        progress_text = (
            f"Video {current_video}/{videos_total}  ·  "
            f"{self._format_mmss(seconds_done)}/{self._format_mmss(seconds_total)}"
        )
        percent = min(100.0, max(0.0, (seconds_done / seconds_total) * 100.0))

        widgets.status_label.config(text=status)
        widgets.progress_label.config(text=progress_text)
        widgets.file_label.config(text=filename or "—")
        if widgets.active_label_packed:
            widgets.active_label.pack_forget()
            widgets.active_label_packed = False
        widgets.progress.config(mode="determinate", maximum=100)
        widgets.progress["value"] = percent

    def update_video_ai_progress(
        self,
        status: str,
        *,
        videos_done: int,
        videos_total: int,
        seconds_done: float,
        seconds_total: float,
        filename: str,
    ) -> None:
        """Fortschritt Video-KI: Videos + analysierte Gesamtzeit."""
        if self._media_ai_dual:
            self.set_media_ai_section_active("video", True)
            widgets = self._ensure_media_ai_section("video")
            self._apply_video_progress_to_widgets(
                widgets,
                status,
                videos_done=videos_done,
                videos_total=videos_total,
                seconds_done=seconds_done,
                seconds_total=seconds_total,
                filename=filename,
            )
            self.update_idletasks()
            return

        videos_total = max(1, int(videos_total))
        videos_done = max(0, min(int(videos_done), videos_total))
        seconds_total = max(0.1, float(seconds_total))
        seconds_done = max(0.0, min(float(seconds_done), seconds_total))

        current_video = min(videos_done + 1, videos_total) if videos_done < videos_total else videos_total
        progress_text = (
            f"Video {current_video}/{videos_total}  ·  "
            f"{self._format_mmss(seconds_done)}/{self._format_mmss(seconds_total)}"
        )
        percent = min(100.0, max(0.0, (seconds_done / seconds_total) * 100.0))

        if self._detail_mode:
            self.status_label.config(text=status)
            self.progress_label.config(text=progress_text)
            self.file_label.config(text=filename or "—")
            if self._active_label_packed:
                self.active_label.pack_forget()
                self._active_label_packed = False
            self.progress.config(mode="determinate", maximum=100)
            self.progress["value"] = percent
        else:
            self.update_text(f"{status}\n{progress_text}\n{filename}")

        self.update_idletasks()

    def _handle_cancel(self):
        if self._on_cancel is not None:
            self._on_cancel()
        if hasattr(self, "cancel_button"):
            self.cancel_button.config(state=tk.DISABLED)

    def update_text(self, text: str):
        """Aktualisiert den angezeigten Ladetext (einfacher Modus)."""
        if self._detail_mode and hasattr(self, "file_label"):
            lines = text.split("\n")
            primary = lines[-1] if lines else text
            status = lines[0] if len(lines) > 1 else "Bitte warten..."
            self.update_qr_progress(status, "", primary)
            return
        if hasattr(self, "label"):
            self.label.config(text=text)
        self.update_idletasks()

    def update_qr_progress(
        self,
        status: str,
        progress_text: str,
        primary_file: str,
        active_files: Optional[List[str]] = None,
        *,
        completed_count: Optional[int] = None,
        total: Optional[int] = None,
    ):
        """Detail-Anzeige für QR-Suche (aktueller Clip / parallele Clips)."""
        if self._media_ai_dual:
            self.set_media_ai_section_active("photo", True)
            widgets = self._ensure_media_ai_section("photo")
            self._apply_qr_progress_to_widgets(
                widgets,
                status,
                progress_text,
                primary_file,
                active_files,
                completed_count=completed_count,
                total=total,
            )
            self.update_idletasks()
            return

        if not self._detail_mode:
            combined = status
            if progress_text:
                combined += f"\n{progress_text}"
            if primary_file:
                combined += f"\n{primary_file}"
            self.update_text(combined)
            return

        self.status_label.config(text=status)
        self.progress_label.config(text=progress_text)

        if completed_count is not None and total is not None and total > 0:
            percent = min(100.0, max(0.0, (completed_count / total) * 100))
            self.progress.config(mode="determinate", maximum=100)
            self.progress["value"] = percent

        active = [f for f in (active_files or []) if f]
        if len(active) > 1:
            self.file_label.config(text=active[0])
            self.active_label.config(text="\n".join(active[1:]))
            if not self._active_label_packed:
                self.active_label.pack(pady=(0, 4))
                self._active_label_packed = True
        else:
            display_name = primary_file or (active[0] if active else "")
            self.file_label.config(text=display_name)
            if self._active_label_packed:
                self.active_label.pack_forget()
                self._active_label_packed = False

        self.update_idletasks()
