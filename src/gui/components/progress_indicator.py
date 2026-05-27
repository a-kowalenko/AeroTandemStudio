import tkinter as tk
from tkinter import ttk
import math


class ProgressHandler:
    """
    Haupt-App (second_parent): Kompakt „Gesamt“-Balken (live aus Schritten + Encoding-Lanes)
    und per ▾-Icon ein Popover mit Detail-Balken (Schritte + bis zu zwei Kodierungen).
    Detail-UI wird im Toplevel erzeugt (gleicher Tk-Master wie Popover) — kein pack(in_=…) über Toplevel-Grenzen.
    """

    # Detail-Popover: kompakte Balken, breiter genug für längere Labels
    MACRO_BAR_LEN = 200
    ENC_BAR_LEN = 170
    GESAMT_BAR_LEN = 220
    DETAIL_POPOVER_MIN_WIDTH = 520
    DETAIL_TEXT_WRAP = 500
    STEP_WEIGHT_WHEN_ENCODING = 0.35

    def __init__(self, parent, second_parent=None, details_parent=None):
        self.parent = parent
        self.second_parent = second_parent
        self.details_parent = details_parent
        self._encoding_lane1_visible = False
        self._step_pct = 0.0
        self._macro_step = 0
        self._macro_total = 7
        self._lane_pct = [0.0, 0.0]
        self._lane_seen = [False, False]
        self._detail_popover = None
        self._detail_built = False
        self._popover_inner = None
        self._popover_track_active = False
        self._geom_after_id = None

        if second_parent is not None:
            # Nicht gepackt: nur für app.py (progress_handler.progress_bar['value'] = 0)
            self.progress_bar = ttk.Progressbar(
                second_parent, orient="horizontal", mode="determinate", length=self.MACRO_BAR_LEN
            )
            self._stub_encoding_details = tk.Label(second_parent, text="", font=("Arial", 9), fg="gray")
            self.encoding_details_label = self._stub_encoding_details

            self.detail_panel = None
            self.macro_row = None
            self.macro_caption_label = None
            self.detail_step_bar = None
            self.eta_label = None
            self.enc_blocks = []
            self.enc_title_labels = []
            self.enc_progress_bars = []
            self.enc_eta_labels = []
            self.enc_detail_labels = []

            self.compact_frame = tk.Frame(second_parent)
            self.gesamt_caption = tk.Label(
                self.compact_frame, text="Gesamt:", font=("Arial", 9, "bold"), fg="#333"
            )
            self.gesamt_progressbar = ttk.Progressbar(
                self.compact_frame, orient="horizontal", mode="determinate", length=self.GESAMT_BAR_LEN
            )
            self.gesamt_eta_label = tk.Label(self.compact_frame, text="", font=("Arial", 10))
            self.expand_hit = tk.Frame(self.compact_frame, cursor="hand2", highlightthickness=1,
                                       highlightbackground="#ccc", bg="#eee")
            self.expand_label = tk.Label(
                self.expand_hit, text="▾", font=("Arial", 12), fg="#333", bg="#eee", cursor="hand2"
            )
            self.expand_label.pack(padx=4, pady=1)
            self.expand_hit.bind("<Button-1>", lambda e: self._toggle_detail_popover())
            self.expand_label.bind("<Button-1>", lambda e: self._toggle_detail_popover())

            self._tl = second_parent.winfo_toplevel()
            self._tl.bind("<Configure>", self._on_tl_configure_for_popover, add="+")
        else:
            self._tl = None
            self.progress_bar = ttk.Progressbar(parent, orient="horizontal", mode="determinate", length=280)
            self.eta_label = tk.Label(parent, text="", font=("Arial", 10))
            details_master = details_parent if details_parent is not None else parent
            self.encoding_details_label = tk.Label(
                details_master, text="", font=("Arial", 9), fg="gray", anchor="w", justify="left"
            )
            if details_parent is not None:
                self.encoding_details_label.config(wraplength=400)
            self.compact_frame = None
            self.detail_panel = None

        self.status_label = tk.Label(parent, text="Status: Bereit.", font=("Arial", 10),
                                     bd=1, relief=tk.SUNKEN, anchor=tk.W)

    def _detail_ui_alive(self):
        if not self._detail_built or self.detail_panel is None:
            return False
        try:
            return bool(self.detail_panel.winfo_exists())
        except tk.TclError:
            return False

    def _macro_step_label(self):
        """Text neben „Schritte:“ im Detail-Popover: aktueller Schritt / Gesamtzahl."""
        s = int(self._macro_step) if isinstance(self._macro_step, (int, float)) else self._macro_step
        t = int(self._macro_total) if isinstance(self._macro_total, (int, float)) else self._macro_total
        return f"{s}/{t}"

    def _on_tl_configure_for_popover(self, event):
        if not self._popover_track_active:
            return
        self._schedule_popover_geometry_refresh()

    def _schedule_popover_geometry_refresh(self):
        if self.second_parent is None or self._tl is None:
            return
        if self._geom_after_id is not None:
            try:
                self._tl.after_cancel(self._geom_after_id)
            except tk.TclError:
                pass
        self._geom_after_id = self._tl.after(40, self._apply_detail_popover_geometry)

    def _popover_anchor_xy(self, req_w, req_h):
        """Untere rechte Ecke des Popovers an (right_x, top_y - gap): ganz oberhalb der kompakten Zeile."""
        anchor = self.compact_frame
        right_x = anchor.winfo_rootx() + anchor.winfo_width()
        top_y = anchor.winfo_rooty()
        bottom_y = top_y + anchor.winfo_height()
        gap = 8
        ex = right_x - req_w
        ey = top_y - req_h - gap

        sw = self.parent.winfo_screenwidth()
        sh = self.parent.winfo_screenheight()
        if ex < 8:
            ex = 8
        if ex + req_w > sw - 8:
            ex = max(8, sw - req_w - 8)
        # Nicht genug Platz oben oder würde mit der Zeile kollidieren → unter die Zeile schieben
        if ey < 8 or (ey + req_h > top_y - gap):
            ey = bottom_y + gap
        if ey + req_h > sh - 8:
            ey = max(8, sh - req_h - 8)
        return ex, ey

    def _apply_detail_popover_geometry(self):
        if self._geom_after_id is not None and self._tl is not None:
            try:
                self._tl.after_cancel(self._geom_after_id)
            except tk.TclError:
                pass
        self._geom_after_id = None
        if self.second_parent is None:
            return
        pop = self._detail_popover
        inner = self._popover_inner
        if pop is None or inner is None:
            return
        try:
            if not pop.winfo_exists() or not inner.winfo_exists():
                return
        except tk.TclError:
            return

        self.parent.update_idletasks()
        pop.update_idletasks()
        inner.update_idletasks()

        req_w = max(inner.winfo_reqwidth() + 40, self.DETAIL_POPOVER_MIN_WIDTH)
        req_h = inner.winfo_reqheight() + 28
        ex, ey = self._popover_anchor_xy(req_w, req_h)
        pop.geometry(f"{req_w}x{req_h}+{ex}+{ey}")
        try:
            pop.deiconify()
            pop.lift()
        except tk.TclError:
            pass

    def pack_progress_bar(self):
        if self.second_parent is not None:
            self.pack_progress_bar_right()
            return
        if not hasattr(self, "progress_container") or not self.progress_container.winfo_exists():
            self.progress_container = tk.Frame(self.parent)
            self.progress_container.pack(pady=0)

        self.progress_bar.pack(in_=self.progress_container, side=tk.LEFT, padx=(0, 10))
        self.eta_label.pack(in_=self.progress_container, side=tk.LEFT)
        details_target = self.details_parent if self.details_parent is not None else self.parent
        if self.details_parent is not None:
            self.encoding_details_label.pack(in_=details_target, side=tk.TOP, anchor="w", fill="x", pady=(2, 0))
        else:
            self.encoding_details_label.pack(in_=details_target, pady=0)

    def pack_progress_bar_right(self):
        if self.second_parent is None:
            self.progress_bar.pack(side=tk.RIGHT, padx=(10, 0))
            self.eta_label.pack(side=tk.RIGHT, padx=(5, 0))
            if self.details_parent is not None:
                self.encoding_details_label.pack(side=tk.TOP, anchor="w", fill="x", pady=(2, 0))
            else:
                self.encoding_details_label.pack(side=tk.RIGHT, padx=(5, 0))
            return

        self.gesamt_caption.pack(side=tk.LEFT, padx=(0, 6))
        self.gesamt_progressbar.pack(side=tk.LEFT, padx=(0, 8))
        self.gesamt_eta_label.pack(side=tk.LEFT, padx=(0, 6))
        self.expand_hit.pack(side=tk.LEFT)
        self.compact_frame.pack(side=tk.RIGHT, padx=(8, 0), pady=(2, 6), anchor="ne")
        self._refresh_gesamt()

    def pack_status_label(self):
        self.status_label.pack(side=tk.BOTTOM, fill=tk.X, pady=0)

    def _ensure_lane1_visible(self):
        if self.second_parent is None or not self._detail_ui_alive() or self._encoding_lane1_visible:
            return
        if len(self.enc_blocks) > 1:
            self.enc_blocks[1].pack(anchor="e", fill=tk.X, pady=(4, 0), after=self.enc_blocks[0])
            self._encoding_lane1_visible = True
            self._schedule_popover_geometry_refresh()

    def _refresh_gesamt(self):
        if self.second_parent is None or not hasattr(self, "gesamt_progressbar"):
            return
        step = self._step_pct
        active = [self._lane_pct[i] for i in range(2) if self._lane_seen[i]]
        if active:
            enc_mean = sum(active) / len(active)
            w = self.STEP_WEIGHT_WHEN_ENCODING
            g = w * step + (1.0 - w) * enc_mean
        else:
            g = step
        g = min(100.0, max(0.0, g))
        self.gesamt_progressbar["value"] = g
        self.gesamt_eta_label.config(text=f"{math.floor(g)}%")
        self.parent.update_idletasks()

    def _toggle_detail_popover(self):
        if self.second_parent is None:
            return
        pop = self._detail_popover
        open_ok = False
        if pop is not None:
            try:
                open_ok = bool(pop.winfo_exists())
            except tk.TclError:
                open_ok = False
        if open_ok:
            self._close_detail_popover()
        else:
            self._detail_popover = None
            self._open_detail_popover()

    def _build_detail_into(self, master):
        """Erzeugt die komplette Detail-UI unter master (Toplevel-Inhalt)."""
        self._invalidate_detail_soft()

        bg = "#f4f4f4"
        self.detail_panel = tk.Frame(master, bg=bg)
        self.macro_row = tk.Frame(self.detail_panel, bg=bg)
        self.macro_caption_label = tk.Label(
            self.macro_row, text="Schritte:", font=("Arial", 8), fg="#555", bg=bg
        )
        self.macro_bar_row = tk.Frame(self.macro_row, bg=bg)
        self.detail_step_bar = ttk.Progressbar(
            self.macro_bar_row, orient="horizontal", mode="determinate", length=self.MACRO_BAR_LEN
        )
        self.eta_label = tk.Label(self.macro_bar_row, text="", font=("Arial", 10), bg=bg)

        self.enc_blocks = []
        self.enc_title_labels = []
        self.enc_progress_bars = []
        self.enc_eta_labels = []
        self.enc_detail_labels = []

        for _ in range(2):
            block = tk.Frame(self.detail_panel, bg=bg)
            title = tk.Label(
                block, text="", font=("Arial", 9, "bold"), anchor="nw", justify=tk.LEFT, bg=bg,
                wraplength=self.DETAIL_TEXT_WRAP,
            )
            title.pack(anchor="w", fill=tk.X, pady=(0, 2))
            row2 = tk.Frame(block, bg=bg)
            pb = ttk.Progressbar(row2, orient="horizontal", mode="determinate", length=self.ENC_BAR_LEN)
            eta = tk.Label(row2, text="", font=("Arial", 9), bg=bg)
            pb.pack(side=tk.LEFT, padx=(0, 8))
            eta.pack(side=tk.RIGHT)
            row2.pack(fill=tk.X)
            det = tk.Label(
                block, text="", font=("Arial", 8), fg="gray", anchor="w", justify=tk.LEFT, bg=bg,
                wraplength=self.DETAIL_TEXT_WRAP,
            )
            det.pack(anchor="w", fill=tk.X, pady=(2, 4))

            self.enc_blocks.append(block)
            self.enc_title_labels.append(title)
            self.enc_progress_bars.append(pb)
            self.enc_eta_labels.append(eta)
            self.enc_detail_labels.append(det)

        self.enc_title_labels[0].config(text="Kodierung")
        self.enc_title_labels[1].config(text="Wasserzeichen")

        self.macro_caption_label.pack(anchor="w", fill=tk.X, pady=(0, 2))
        self.detail_step_bar.pack(side=tk.LEFT, padx=(0, 8))
        self.eta_label.pack(side=tk.RIGHT)
        self.macro_bar_row.pack(fill=tk.X)
        self.macro_row.pack(anchor="w", pady=(0, 8), fill=tk.X)
        self.enc_blocks[0].pack(anchor="e", fill=tk.X, pady=(0, 0))
        self._encoding_lane1_visible = False

        self._detail_built = True
        self._sync_detail_from_state()

    def _sync_detail_from_state(self):
        if not self._detail_ui_alive():
            return
        self.detail_step_bar["value"] = self._step_pct
        self.eta_label.config(text=self._macro_step_label())
        for i in range(2):
            self.enc_progress_bars[i]["value"] = self._lane_pct[i] if self._lane_seen[i] else 0
            if self._lane_seen[i]:
                self.enc_eta_labels[i].config(text=f"{math.floor(self._lane_pct[i])}%")
        if self._lane_seen[1]:
            self._ensure_lane1_visible()
        self._schedule_popover_geometry_refresh()

    def _invalidate_detail_soft(self):
        """Vorbereitung vor Neuaufbau: Referenzen löschen (Widgets ggf. schon zerstört)."""
        if self.second_parent is None:
            return
        self._detail_built = False
        self._encoding_lane1_visible = False
        self.detail_panel = None
        self.macro_row = None
        self.macro_caption_label = None
        self.macro_bar_row = None
        self.detail_step_bar = None
        self.eta_label = None
        self.enc_blocks = []
        self.enc_title_labels = []
        self.enc_progress_bars = []
        self.enc_eta_labels = []
        self.enc_detail_labels = []
        self.encoding_details_label = self._stub_encoding_details

    def _open_detail_popover(self):
        if self.second_parent is None:
            return
        self._close_detail_popover()
        pop = tk.Toplevel(self.parent)
        pop.wm_overrideredirect(True)
        try:
            pop.attributes("-topmost", True)
        except tk.TclError:
            pass
        pop.configure(bg="#888888")

        outer = tk.Frame(pop, bg="#888888", padx=1, pady=1)
        outer.pack(fill=tk.BOTH, expand=True)
        inner = tk.Frame(outer, bg="#f4f4f4", padx=12, pady=10)
        inner.pack(fill=tk.BOTH, expand=True)

        head = tk.Frame(inner, bg="#f4f4f4")
        head.pack(fill=tk.X, pady=(0, 8))
        tk.Label(
            head, text="Detail-Fortschritt", font=("Arial", 10, "bold"), bg="#f4f4f4", fg="#222"
        ).pack(side=tk.LEFT)
        tk.Button(
            head, text="×", font=("Arial", 11, "bold"), bd=0, padx=6, pady=0,
            command=self._close_detail_popover, cursor="hand2", bg="#f4f4f4", activebackground="#e0e0e0"
        ).pack(side=tk.RIGHT)

        body = tk.Frame(inner, bg="#f4f4f4")
        body.pack(fill=tk.BOTH, expand=True)

        self._build_detail_into(body)
        self.detail_panel.pack(fill=tk.BOTH, expand=True)

        self._detail_popover = pop
        self._popover_inner = inner
        self._popover_track_active = True
        # Kein wm_transient hier: zusammen mit wm_overrideredirect(True) kann das Toplevel unter
        # Windows unsichtbar bleiben oder nicht korrekt mappen. Position folgt per <Configure>.
        if self._geom_after_id is not None and self._tl is not None:
            try:
                self._tl.after_cancel(self._geom_after_id)
            except tk.TclError:
                pass
        self._geom_after_id = self._tl.after(0, self._apply_detail_popover_geometry)

        def on_escape(_):
            self._close_detail_popover()

        pop.bind("<Escape>", on_escape)

    def _close_detail_popover(self):
        if self.second_parent is None:
            return
        self._popover_track_active = False
        self._popover_inner = None
        if self._geom_after_id is not None and self._tl is not None:
            try:
                self._tl.after_cancel(self._geom_after_id)
            except tk.TclError:
                pass
        self._geom_after_id = None
        if self._detail_popover is not None:
            try:
                if self._detail_popover.winfo_exists():
                    self._detail_popover.destroy()
            except tk.TclError:
                pass
            self._detail_popover = None
        self._invalidate_detail_soft()

    def update_progress(self, step, total_steps=7):
        self._macro_step = step
        self._macro_total = total_steps if total_steps else 1
        progress = (step / self._macro_total) * 100
        if self.second_parent is not None:
            self._step_pct = progress
            self.progress_bar["value"] = progress
            if self._detail_ui_alive():
                self.detail_step_bar["value"] = progress
                self.eta_label.config(text=self._macro_step_label())
            self._refresh_gesamt()
        else:
            self.progress_bar["value"] = progress
            self.eta_label.config(text=f"{math.floor(progress)}%")
        self.parent.update_idletasks()

    def update_encoding_progress(self, task_name="Encoding", progress=None, fps=0.0, eta=None,
                                   current_time=0.0, total_time=None, task_id=None, encoding_lane=0):
        lane = 1 if encoding_lane == 1 else 0

        if self.second_parent is None:
            if progress is not None:
                self.progress_bar["value"] = progress
            if eta:
                eta_text = f"{math.floor(progress if progress else 0)}% - ETA: {eta}"
            elif progress is not None:
                eta_text = f"{math.floor(progress)}%"
            else:
                eta_text = ""
            self.eta_label.config(text=eta_text)

            details_parts = []
            if task_id is not None:
                details_parts.append(f"[Task {task_id}]")
            details_parts.append(task_name)
            if fps > 0:
                details_parts.append(f"{fps:.1f} fps")
            if current_time and total_time:
                time_str = f"{self._format_time(current_time)} / {self._format_time(total_time)}"
                details_parts.append(time_str)
            elif current_time:
                details_parts.append(f"{self._format_time(current_time)}")
            self.encoding_details_label.config(text=" • ".join(details_parts))
            self.parent.update_idletasks()
            return

        if lane == 1:
            self._ensure_lane1_visible()

        if task_name:
            t = str(task_name)
            title = (t[:72] + "…") if len(t) > 73 else t
            if self._detail_ui_alive():
                self.enc_title_labels[lane].config(text=title)

        if progress is not None:
            self._lane_seen[lane] = True
            self._lane_pct[lane] = float(progress)

        if self._detail_ui_alive():
            pb = self.enc_progress_bars[lane]
            et = self.enc_eta_labels[lane]
            if progress is not None:
                pb["value"] = progress
            if eta:
                et.config(text=f"{math.floor(progress if progress else 0)}% · ETA {eta}")
            elif progress is not None:
                et.config(text=f"{math.floor(progress)}%")
            else:
                et.config(text="")

            details_parts = []
            if task_id is not None:
                details_parts.append(f"[Task {task_id}]")
            if fps > 0:
                details_parts.append(f"{fps:.1f} fps")
            if current_time and total_time:
                time_str = f"{self._format_time(current_time)} / {self._format_time(total_time)}"
                details_parts.append(time_str)
            elif current_time:
                details_parts.append(f"{self._format_time(current_time)}")
            self.enc_detail_labels[lane].config(text=" • ".join(details_parts) if details_parts else "")

        self._refresh_gesamt()
        self.parent.update_idletasks()

        if self._detail_popover is not None:
            try:
                if self._detail_popover.winfo_exists():
                    self._schedule_popover_geometry_refresh()
            except tk.TclError:
                pass

    def _format_time(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}:{secs:02d}"

    def reset(self):
        self._close_detail_popover()

        if self.second_parent is None:
            self.progress_bar.pack_forget()
            self.eta_label.pack_forget()
            self.encoding_details_label.pack_forget()
            if hasattr(self, "progress_container") and self.progress_container.winfo_exists():
                self.progress_container.pack_forget()
        else:
            if self.compact_frame is not None:
                self.compact_frame.pack_forget()
            self._encoding_lane1_visible = False
            self._step_pct = 0.0
            self._macro_step = 0
            self._macro_total = 7
            self._lane_pct = [0.0, 0.0]
            self._lane_seen = [False, False]

        self.progress_bar["value"] = 0
        if self.second_parent is None:
            self.eta_label.config(text="")
            self.encoding_details_label.config(text="")
        else:
            self.gesamt_progressbar["value"] = 0
            self.gesamt_eta_label.config(text="")
            self._stub_encoding_details.config(text="")

    def set_status(self, text):
        self.status_label.config(text=text)
