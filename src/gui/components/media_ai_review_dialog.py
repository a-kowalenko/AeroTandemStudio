import os
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional

from concurrent.futures import ThreadPoolExecutor

from PIL import ImageTk

from src.utils.photo_thumbnail import build_pil_thumbnail

try:
    from src.media_ai.camera_resolution import format_camera_type_label
    from src.media_ai.series_analyzer import get_preview_categories, get_preview_category_labels
except ImportError:
    def format_camera_type_label(camera_type: str) -> str:
        normalized = (camera_type or "").strip().lower()
        return {"handcam": "Handcam", "outside": "Outside"}.get(normalized, normalized or "Unbekannt")

    def get_preview_categories(camera_type: str):
        return (
            "boarding", "climb", "door", "exit", "freefall", "canopy", "landing", "final",
        )

    def get_preview_category_labels(camera_type: str):
        return {c: c for c in get_preview_categories(camera_type)}


class AllPhotosSelectionDialog(tk.Toplevel):
    """Kachel-Dialog zur Auswahl eines Fotos aus allen importierten Bildern."""

    def __init__(self, master, all_photo_paths: List[str], preselected_index: Optional[int] = None):
        super().__init__(master)
        self.withdraw()
        self.title("Foto auswählen")
        self.geometry("1120x760")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self._all_photo_paths = list(all_photo_paths)
        self._filtered_indices: List[int] = list(range(len(self._all_photo_paths)))
        self._filter_var = tk.StringVar()
        self._page_size = 50
        self._current_page = 0
        self._total_pages = 1
        self._thumb_refs: Dict[int, ImageTk.PhotoImage] = {}
        self._page_thumb_refs: List[ImageTk.PhotoImage] = []
        self._tile_frames: Dict[int, tk.Frame] = {}
        self._tile_labels: Dict[int, List[tk.Widget]] = {}
        self._selected_index: Optional[int] = preselected_index
        self._render_items: List[tuple[int, str]] = []
        self._thumb_loader = ThreadPoolExecutor(max_workers=2)
        self._thumb_load_generation = 0
        self.result_confirmed = False
        self.selected_index: Optional[int] = None

        self._build_ui()
        self._center_over_parent(master)
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _build_ui(self) -> None:
        root = tk.Frame(self, padx=12, pady=12, bg="#f5f6f8")
        root.pack(fill="both", expand=True)

        filter_row = tk.Frame(root, bg="#f5f6f8")
        filter_row.pack(fill="x", pady=(0, 6))
        tk.Label(filter_row, text="Filter:", bg="#f5f6f8", font=("Arial", 10, "bold")).pack(side="left", padx=(0, 6))
        filter_entry = tk.Entry(filter_row, textvariable=self._filter_var, width=48)
        filter_entry.pack(side="left", fill="x", expand=True)
        self._filter_var.trace_add("write", lambda *_args: self._apply_filter())

        nav = tk.Frame(root, bg="#f5f6f8")
        nav.pack(fill="x", pady=(0, 8))
        self._prev_btn = tk.Button(nav, text="<< Zurück", width=12, command=self._go_prev_page)
        self._prev_btn.pack(side="left")
        self._next_btn = tk.Button(nav, text="Weiter >>", width=12, command=self._go_next_page)
        self._next_btn.pack(side="left", padx=(6, 0))
        self._page_label = tk.Label(nav, text="", bg="#f5f6f8", font=("Arial", 10, "bold"))
        self._page_label.pack(side="left", padx=(12, 0))

        self._canvas = tk.Canvas(root, bg="#ffffff", highlightthickness=0)
        self._canvas.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=self._canvas.yview)
        scrollbar.pack(side="right", fill="y")
        self._canvas.configure(yscrollcommand=scrollbar.set)

        self._grid_container = tk.Frame(self._canvas, bg="#ffffff")
        self._canvas_window = self._canvas.create_window((0, 0), window=self._grid_container, anchor="nw")
        self._grid_container.bind("<Configure>", self._on_grid_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self._bind_mousewheel(self._canvas)
        self._bind_mousewheel(self._grid_container)

        buttons = tk.Frame(self, padx=12, pady=10)
        buttons.pack(fill="x")
        tk.Button(buttons, text="Abbrechen", command=self._on_cancel, width=14, bg="#f44336", fg="white").pack(
            side="right", padx=(5, 0)
        )
        tk.Button(buttons, text="Übernehmen", command=self._on_confirm, width=14, bg="#4CAF50", fg="white").pack(side="right")

        self._apply_filter(initial=True)

    def _bind_mousewheel(self, widget: tk.Widget) -> None:
        widget.bind("<Enter>", self._bind_wheel_active, add="+")
        widget.bind("<Leave>", self._unbind_wheel_active, add="+")

    def _bind_wheel_active(self, _event=None) -> None:
        self.bind_all("<MouseWheel>", self._on_mousewheel)
        self.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _unbind_wheel_active(self, _event=None) -> None:
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _on_mousewheel(self, event) -> None:
        self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event) -> None:
        if event.num == 4:
            self._canvas.yview_scroll(-3, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(3, "units")

    def _apply_filter(self, initial: bool = False) -> None:
        query = self._filter_var.get().strip().lower()
        if query:
            self._filtered_indices = []
            for idx, path in enumerate(self._all_photo_paths):
                if not path:
                    continue
                label = f"#{idx + 1} {os.path.basename(path)}".lower()
                if query in label or query in path.lower():
                    self._filtered_indices.append(idx)
        else:
            self._filtered_indices = list(range(len(self._all_photo_paths)))

        self._total_pages = max(1, (len(self._filtered_indices) + self._page_size - 1) // self._page_size)
        if initial and self._selected_index is not None and self._selected_index in self._filtered_indices:
            pos = self._filtered_indices.index(self._selected_index)
            self._current_page = pos // self._page_size
        else:
            self._current_page = min(self._current_page, self._total_pages - 1)
        self._refresh_grid()

    def _center_over_parent(self, master) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        try:
            master.update_idletasks()
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
            x = mx + max(0, (mw - width) // 2)
            y = my + max(0, (mh - height) // 2)
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _on_grid_configure(self, _event=None) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event) -> None:
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _go_prev_page(self) -> None:
        if self._current_page <= 0:
            return
        self._current_page -= 1
        self._refresh_grid()

    def _go_next_page(self) -> None:
        if self._current_page >= self._total_pages - 1:
            return
        self._current_page += 1
        self._refresh_grid()

    def _refresh_grid(self) -> None:
        for child in self._grid_container.winfo_children():
            child.destroy()
        self._page_thumb_refs.clear()
        self._tile_frames.clear()
        self._tile_labels.clear()
        self._thumb_load_generation += 1
        start = self._current_page * self._page_size
        page_indices = self._filtered_indices[start : start + self._page_size]
        self._render_items = [
            (idx, self._all_photo_paths[idx]) for idx in page_indices if 0 <= idx < len(self._all_photo_paths)
        ]
        if not self._render_items:
            tk.Label(
                self._grid_container,
                text="Keine Fotos passen zum Filter." if self._filter_var.get().strip() else "Keine Fotos verfügbar.",
                bg="#ffffff",
                fg="#666666",
                font=("Arial", 11),
            ).grid(
                row=0, column=0, padx=16, pady=16, sticky="w"
            )
            self._update_page_controls()
            return

        columns = 5
        for col in range(columns):
            self._grid_container.grid_columnconfigure(col, weight=1)
        self._render_current_page()
        self._update_page_controls()
        self._canvas.update_idletasks()
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _update_page_controls(self) -> None:
        self._prev_btn.config(state=tk.NORMAL if self._current_page > 0 else tk.DISABLED)
        self._next_btn.config(state=tk.NORMAL if self._current_page < self._total_pages - 1 else tk.DISABLED)
        self._page_label.config(text=f"Seite {self._current_page + 1} / {self._total_pages}")

    def _render_current_page(self) -> None:
        columns = 5
        generation = self._thumb_load_generation
        page = self._current_page
        for pos, (idx, path) in enumerate(self._render_items):
            row = pos // columns
            col = pos % columns
            tile = tk.Frame(
                self._grid_container,
                bg="#eef4ff" if idx == self._selected_index else "#ffffff",
                bd=2 if idx == self._selected_index else 1,
                relief="solid",
            )
            tile.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            self._tile_frames[idx] = tile
            widgets: List[tk.Widget] = []

            thumb_ref = self._thumb_refs.get(idx)
            img_label = tk.Label(
                tile,
                image=thumb_ref if thumb_ref is not None else "",
                text="" if thumb_ref is not None else "Lade...",
                bg=tile["bg"],
                fg="#777777" if thumb_ref is None else tile["bg"],
                width=24 if thumb_ref is None else 0,
                height=12 if thumb_ref is None else 0,
            )
            img_label.pack(padx=8, pady=(8, 4))
            img_label.bind("<Button-1>", lambda _evt, photo_idx=idx: self._choose(photo_idx))
            widgets.append(img_label)
            if thumb_ref is not None:
                self._page_thumb_refs.append(thumb_ref)
            else:
                self._queue_thumbnail_load(idx, path, img_label, generation, page)

            name = os.path.basename(path)
            text_label = tk.Label(
                tile,
                text=f"#{idx + 1}\n{name}",
                justify="center",
                wraplength=190,
                bg=tile["bg"],
                font=("Arial", 9),
            )
            text_label.pack(fill="x", padx=6, pady=(0, 8))
            text_label.bind("<Button-1>", lambda _evt, photo_idx=idx: self._choose(photo_idx))
            widgets.append(text_label)

            tile.bind("<Button-1>", lambda _evt, photo_idx=idx: self._choose(photo_idx))
            self._tile_labels[idx] = widgets

    def _queue_thumbnail_load(self, idx: int, path: str, img_label: tk.Label, generation: int, page: int) -> None:
        def _worker():
            return build_pil_thumbnail(path, max_size=180)

        future = self._thumb_loader.submit(_worker)

        def _apply(thumb):
            if generation != self._thumb_load_generation:
                return
            if page != self._current_page:
                return
            if not img_label.winfo_exists():
                return
            if thumb is None:
                img_label.configure(text="Kein Thumbnail", image="")
                return
            image = ImageTk.PhotoImage(thumb)
            self._thumb_refs[idx] = image
            self._page_thumb_refs.append(image)
            img_label.configure(image=image, text="", width=0, height=0)

        def _on_done(done_future):
            try:
                thumb = done_future.result()
            except Exception:
                thumb = None
            if self.winfo_exists():
                self.after(0, lambda t=thumb: _apply(t))

        future.add_done_callback(_on_done)

        def _on_done(done_future):
            try:
                thumb = done_future.result()
            except Exception:
                thumb = None
            if self.winfo_exists():
                self.after(0, lambda: _apply(thumb))

    def _choose(self, idx: int) -> None:
        prev = self._selected_index
        self._selected_index = idx
        if prev is not None:
            self._paint_tile_selection(prev, False)
        self._paint_tile_selection(idx, True)

    def _paint_tile_selection(self, idx: int, selected: bool) -> None:
        tile = self._tile_frames.get(idx)
        if not tile:
            return
        bg = "#eef4ff" if selected else "#ffffff"
        tile.configure(bg=bg, bd=2 if selected else 1)
        for widget in self._tile_labels.get(idx, []):
            try:
                widget.configure(bg=bg)
            except Exception:
                pass

    def _on_confirm(self) -> None:
        if self._selected_index is None:
            return
        self.selected_index = self._selected_index
        self.result_confirmed = True
        self._unbind_wheel_active()
        try:
            self._thumb_loader.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.destroy()

    def _on_cancel(self) -> None:
        self.result_confirmed = False
        self.selected_index = None
        self._unbind_wheel_active()
        try:
            self._thumb_loader.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.destroy()


class MediaAIReviewDialog(tk.Toplevel):
    """Dialog zur manuellen Bestätigung/Anpassung der KI-Preview-Auswahl."""

    PREVIEW_GRID_COLUMNS = 4

    def __init__(
        self,
        master,
        category_candidates: Dict[str, List[dict]],
        all_photo_paths: Optional[List[str]] = None,
        *,
        camera_type: Optional[str] = None,
    ):
        super().__init__(master)
        self.withdraw()
        self.title("KI Analyse - Preview Auswahl prüfen")
        self.geometry("1680x980")
        self.resizable(True, True)
        self.minsize(1280, 820)
        self.transient(master)
        self.grab_set()

        self._camera_type = camera_type or "handcam"
        self._preview_categories = get_preview_categories(self._camera_type)
        self.CATEGORY_LABELS = get_preview_category_labels(self._camera_type)
        self._category_candidates = category_candidates
        self._all_photo_paths = list(all_photo_paths or [])
        self.selected_indices: List[int] = []
        self.result_confirmed = False
        self._thumb_refs = {}
        self._selection_indices: Dict[str, int] = {}
        self._preview_labels: Dict[str, tk.Label] = {}
        self._listboxes: Dict[str, tk.Listbox] = {}
        self._display_item_maps: Dict[str, List[dict]] = {}
        self._ai_options_by_category: Dict[str, List[dict]] = {}
        self._info_labels: Dict[str, tk.Label] = {}
        self._confidence_bars: Dict[str, ttk.Progressbar] = {}

        self._create_widgets()
        self._center_over_parent(master)
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _center_over_parent(self, master) -> None:
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        try:
            master.update_idletasks()
            mx = master.winfo_rootx()
            my = master.winfo_rooty()
            mw = master.winfo_width()
            mh = master.winfo_height()
            x = mx + max(0, (mw - width) // 2)
            y = my + max(0, (mh - height) // 2)
        except Exception:
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _create_widgets(self):
        root = tk.Frame(self, padx=12, pady=12, bg="#f5f6f8")
        root.pack(fill="both", expand=True)

        tk.Label(
            root,
            text="Die KI hat pro Kategorie Kandidaten ermittelt. Auswahl prüfen und bei Bedarf aus allen Fotos anpassen.",
            font=("Arial", 11, "bold"),
            anchor="w",
            bg="#f5f6f8",
        ).pack(fill="x", pady=(0, 4))

        camera_label_text = ""
        if self._camera_type in ("handcam", "outside"):
            camera_label_text = f"Kamera-Typ: {format_camera_type_label(self._camera_type)}"
        if camera_label_text:
            tk.Label(
                root,
                text=camera_label_text,
                font=("Arial", 10, "bold"),
                fg="#2d89ef",
                anchor="w",
                bg="#f5f6f8",
            ).pack(fill="x", pady=(0, 10))
        else:
            tk.Frame(root, height=6, bg="#f5f6f8").pack()

        cards = tk.Frame(root, bg="#f5f6f8")
        cards.pack(fill="both", expand=True)
        grid_cols = self.PREVIEW_GRID_COLUMNS
        grid_rows = (len(self._preview_categories) + grid_cols - 1) // grid_cols
        for col in range(grid_cols):
            cards.grid_columnconfigure(col, weight=1, uniform="ai_cards")
        for row in range(grid_rows):
            cards.grid_rowconfigure(row, weight=1, uniform="ai_rows")

        for i, category in enumerate(self._preview_categories):
            candidates = self._category_candidates.get(category, [])

            r = i // grid_cols
            c = i % grid_cols
            card = ttk.LabelFrame(cards, text=self.CATEGORY_LABELS.get(category, category), padding=(8, 8))
            card.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)
            card.grid_columnconfigure(1, weight=1)
            card.grid_rowconfigure(3, weight=1)

            preview_container = tk.Frame(card, bg="#ffffff", relief="solid", bd=1, width=260, height=165)
            preview_container.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(0, 12), pady=2)
            preview_container.grid_propagate(False)
            preview_label = tk.Label(
                preview_container,
                text="(kein Thumbnail)",
                relief="flat",
                bd=0,
                bg="#ffffff",
                anchor="center",
                justify="center",
            )
            preview_label.place(relx=0.5, rely=0.5, anchor="center")
            self._preview_labels[category] = preview_label

            info_title = tk.Label(card, text="Aktuelle Auswahl", font=("Arial", 10, "bold"), anchor="w")
            info_title.grid(row=0, column=1, sticky="w", pady=(0, 4))

            info_text = tk.Label(card, text="", font=("Arial", 9), fg="#333333", anchor="w", justify="left")
            info_text.grid(row=1, column=1, sticky="w")
            self._info_labels[category] = info_text

            confidence_bar = ttk.Progressbar(card, mode="determinate", maximum=100, length=200)
            confidence_bar.grid(row=2, column=1, sticky="ew", pady=(4, 6))
            self._confidence_bars[category] = confidence_bar

            list_frame = tk.Frame(card)
            list_frame.grid(row=3, column=1, sticky="nsew")
            list_frame.grid_columnconfigure(0, weight=1)
            list_frame.grid_rowconfigure(0, weight=1)
            listbox = tk.Listbox(
                list_frame,
                height=5,
                exportselection=False,
                font=("Arial", 9),
                activestyle="none",
            )
            listbox.grid(row=0, column=0, sticky="nsew")
            scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=listbox.yview)
            scrollbar.grid(row=0, column=1, sticky="ns")
            listbox.config(yscrollcommand=scrollbar.set)
            self._listboxes[category] = listbox
            listbox.bind("<<ListboxSelect>>", lambda _evt, cat=category: self._on_listbox_select(cat))

            hint_label = tk.Label(
                card,
                text="Tipp: KI-Vorschläge sind mit [KI] markiert.",
                font=("Arial", 8),
                fg="#666666",
                anchor="w",
            )
            hint_label.grid(row=4, column=1, sticky="w", pady=(4, 0))

            choose_all_btn = tk.Button(
                card,
                text="Aus allen Fotos wählen...",
                command=lambda cat=category: self._open_all_photos_dialog(cat),
                font=("Arial", 9, "bold"),
                bg="#2d89ef",
                fg="white",
            )
            choose_all_btn.grid(row=5, column=1, sticky="ew", pady=(6, 0))

            self._ai_options_by_category[category] = self._build_options_for_category(category, candidates)
            if candidates:
                self._selection_indices[category] = int(candidates[0]["index"])
            self._refresh_listbox(category)

        buttons = tk.Frame(root)
        buttons.pack(fill="x", pady=(10, 0))
        tk.Button(
            buttons,
            text="Abbrechen",
            command=self._on_cancel,
            bg="#f44336",
            fg="white",
            width=14,
        ).pack(side="right", padx=(5, 0))
        tk.Button(
            buttons,
            text="Übernehmen",
            command=self._on_confirm,
            bg="#4CAF50",
            fg="white",
            width=14,
        ).pack(side="right")

    def _build_options_for_category(self, category: str, candidates: List[dict]) -> List[dict]:
        options: List[dict] = []
        seen_paths = set()
        for candidate in candidates:
            path = str(candidate.get("path", ""))
            idx = int(candidate.get("index", -1))
            if not path:
                continue
            seen_paths.add(path)
            options.append(
                {
                    "index": idx,
                    "path": path,
                    "score": float(candidate.get("score", 0.0)),
                    "predicted": str(candidate.get("predicted", "") or ""),
                    "is_ai": True,
                    "category": category,
                }
            )

        return options

    def _format_option_label(self, option: dict) -> str:
        basename = os.path.basename(str(option["path"]))
        idx = int(option["index"]) + 1
        score = option.get("score")
        if option.get("is_ai") and isinstance(score, (int, float)):
            return f"[KI] #{idx}  {basename}  ({float(score) * 100:.1f}%)"
        return f"[Manuell] #{idx}  {basename}"

    def _refresh_listbox(self, category: str) -> None:
        listbox = self._listboxes.get(category)
        if not listbox:
            return
        options = self._ai_options_by_category.get(category, [])
        visible = list(options)
        self._display_item_maps[category] = visible
        listbox.delete(0, tk.END)
        for option in visible:
            listbox.insert(tk.END, self._format_option_label(option))

        preselected_idx = self._selection_indices.get(category)
        select_row = None
        if preselected_idx is not None:
            for row_idx, option in enumerate(visible):
                if int(option["index"]) == preselected_idx:
                    select_row = row_idx
                    break

        if select_row is not None:
            listbox.selection_clear(0, tk.END)
            listbox.selection_set(select_row)
            listbox.see(select_row)
            self._on_listbox_select(category)
        else:
            has_ai = bool(options)
            self._preview_labels[category].config(text="Kein KI-Vorschlag", image="")
            info_widget = self._info_labels.get(category)
            bar_widget = self._confidence_bars.get(category)
            if info_widget:
                info_widget.config(text="Für diese Kategorie gibt es keinen KI-Vorschlag.\nBitte manuell auswählen.")
            if bar_widget:
                bar_widget["value"] = 0

    def _open_all_photos_dialog(self, category: str) -> None:
        dialog = AllPhotosSelectionDialog(self, self._all_photo_paths, self._selection_indices.get(category))
        self.wait_window(dialog)
        if not dialog.result_confirmed or dialog.selected_index is None:
            return
        idx = int(dialog.selected_index)
        if idx < 0 or idx >= len(self._all_photo_paths):
            return
        selected_option = {
            "index": idx,
            "path": self._all_photo_paths[idx],
            "score": None,
            "is_ai": False,
            "category": category,
        }
        self._selection_indices[category] = idx
        self._update_preview(category, selected_option)
        self._listboxes[category].selection_clear(0, tk.END)

    def _on_listbox_select(self, category: str) -> None:
        listbox = self._listboxes.get(category)
        if not listbox:
            return
        selected = listbox.curselection()
        if not selected:
            return
        row = selected[0]
        option_list = self._display_item_maps.get(category, [])
        if row < 0 or row >= len(option_list):
            return
        selected_option = option_list[row]
        self._selection_indices[category] = int(selected_option["index"])
        self._update_preview(category, selected_option)

    def _update_preview(self, category: str, selected_option: dict):
        thumb = build_pil_thumbnail(str(selected_option["path"]), max_size=250)
        if thumb is None:
            return
        photo_img = ImageTk.PhotoImage(thumb)
        self._thumb_refs[category] = photo_img
        self._preview_labels[category].config(image=photo_img, text="")
        info_widget = self._info_labels.get(category)
        bar_widget = self._confidence_bars.get(category)
        score = selected_option.get("score")
        score_text = f"{float(score) * 100:.1f}%" if isinstance(score, (int, float)) else "manuelle Auswahl"
        if isinstance(info_widget, tk.Label):
            basename = os.path.basename(str(selected_option["path"]))
            predicted = str(selected_option.get("predicted", "") or "")
            predicted_line = ""
            if predicted and predicted != category:
                predicted_label = self.CATEGORY_LABELS.get(predicted, predicted)
                tile_label = self.CATEGORY_LABELS.get(category, category)
                predicted_line = f"\nHinweis: KI-Hauptklasse „{predicted_label}“ (Kachel: {tile_label})"
            info_widget.config(
                text=(
                    f"Datei: {basename}\n"
                    f"Index: {int(selected_option['index']) + 1}\n"
                    f"KI-Score ({self.CATEGORY_LABELS.get(category, category)}): {score_text}"
                    f"{predicted_line}"
                )
            )
        if isinstance(bar_widget, ttk.Progressbar):
            if isinstance(score, (int, float)):
                bar_widget["value"] = max(0.0, min(100.0, float(score) * 100.0))
            else:
                bar_widget["value"] = 0

    def _on_confirm(self):
        selected = []
        seen = set()
        for category in self._preview_categories:
            idx = self._selection_indices.get(category)
            if idx is None:
                continue
            if idx in seen:
                continue
            seen.add(idx)
            selected.append(idx)
        self.selected_indices = selected
        self.result_confirmed = True
        self.destroy()

    def _on_cancel(self):
        self.result_confirmed = False
        self.selected_indices = []
        self.destroy()
