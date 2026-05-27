import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import webbrowser

from src.utils.constants import APP_VERSION, PAYPAL_LOGO_PATH
from src.gui.components.circular_spinner import CircularSpinner
from src.gui.components.warning_dialog import WarningDialog


class SettingsDialog:
    """Einstellungs-Dialog für Server- und App-Konfiguration"""

    def __init__(self, parent, config, on_settings_saved=None, app=None):
        self.parent = parent
        self.config = config
        self.app = app
        self.dialog = None
        self.APP_VERSION = APP_VERSION
        self.on_settings_saved = on_settings_saved  # Callback für nach dem Speichern
        self._cache_clear_in_progress = False
        self._settings_wheel_active_inner = None

    def show(self):
        """Zeigt den Einstellungs-Dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Einstellungen")
        self.dialog.geometry("750x750")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)

        # WICHTIG: Verstecke Dialog zunächst, um Springen zu vermeiden
        self.dialog.withdraw()

        # --- Variablen ---
        self.server_var = tk.StringVar()
        self.login_var = tk.StringVar()
        self.password_var = tk.StringVar()
        # Variablen für Speicherort und Dauer
        self.speicherort_var = tk.StringVar()
        self.dauer_var = tk.StringVar()
        # Variablen für SD-Karten Backup
        self.sd_backup_folder_var = tk.StringVar()
        self.sd_auto_backup_var = tk.BooleanVar()
        self.sd_clear_var = tk.BooleanVar()
        self.sd_auto_import_var = tk.BooleanVar()
        self.sd_skip_processed_var = tk.BooleanVar()
        self.sd_skip_processed_manual_var = tk.BooleanVar()
        self.sd_size_limit_enabled_var = tk.BooleanVar()  # NEU: Größen-Limit
        self.sd_size_limit_mb_var = tk.StringVar(value="2000")  # NEU: Limit in MB
        self.sd_pc_name_var = tk.StringVar()
        # Variable für Hardware-Beschleunigung
        self.hardware_acceleration_var = tk.BooleanVar()
        # Variable für Paralleles Processing
        self.parallel_processing_var = tk.BooleanVar()
        # Variable für Codec-Auswahl
        self.codec_var = tk.StringVar(value="auto")
        # Encoding-Strategie bei festem Codec (per_clip | combined)
        self.encoding_strategy_var = tk.StringVar(value="per_clip")
        self.reencode_matching_clips_var = tk.BooleanVar(value=False)
        # Session-Zurücksetzen: Tandemmaster / Videospringer optional beibehalten
        self.keep_tandemmaster_on_session_reset_var = tk.BooleanVar()
        self.keep_videospringer_on_session_reset_var = tk.BooleanVar()
        # Video-QR (Tab Erweitert)
        self.qr_video_scan_seconds_var = tk.StringVar(value="5")
        self.qr_video_frame_step_var = tk.StringVar(value="10")
        self.qr_video_scan_scope_var = tk.StringVar(value="all")
        self.qr_video_parallel_enabled_var = tk.BooleanVar()
        self.qr_video_parallel_workers_var = tk.StringVar(value="2")
        self.qr_photo_parallel_enabled_var = tk.BooleanVar()
        self.import_photo_parallel_enabled_var = tk.BooleanVar()
        self.clear_hw_cache_var = tk.BooleanVar(value=False)
        self.oldschool_mode_var = tk.BooleanVar(value=False)

        self.create_widgets()
        self.load_settings()

        # Zentriere den Dialog BEVOR er sichtbar wird (optimiert)
        self._center_dialog_fast()

        # Jetzt zeige den Dialog an (bereits zentriert)
        self.dialog.deiconify()
        self.dialog.grab_set()

        # Fokus auf den Server-Eintrag setzen (verzögert, um schnelleres Öffnen zu ermöglichen)
        self.dialog.after(10, lambda: self.server_entry.focus_set())

    def _center_dialog_fast(self):
        """Zentriert den Dialog über dem Parent-Fenster (optimierte Version)"""
        # Berechne Position ohne update_idletasks (schneller)
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        # Dialog-Dimensionen (fest definiert)
        w, h = 750, 750

        x = parent_x + (parent_width - w) // 2
        y = parent_y + (parent_height - h) // 2

        # Verhindere negative Koordinaten
        x = max(0, x)
        y = max(0, y)

        self.dialog.geometry(f"{w}x{h}+{x}+{y}")

    def _deactivate_tab_mousewheel(self):
        """Entfernt globale Mausrad-Bindings für Settings-Tabs."""
        if not self._settings_wheel_active_inner or not self.dialog:
            return
        try:
            if self.dialog.winfo_exists():
                self.dialog.unbind_all("<MouseWheel>")
                self.dialog.unbind_all("<Button-4>")
                self.dialog.unbind_all("<Button-5>")
        except tk.TclError:
            pass
        self._settings_wheel_active_inner = None

    def _activate_tab_mousewheel(self, tab_inner):
        """Aktiviert Mausrad-Scroll für den Tab unter dem Cursor."""
        if self._settings_wheel_active_inner is tab_inner:
            return
        self._deactivate_tab_mousewheel()
        handlers = getattr(tab_inner, "_scroll_wheel_handlers", None)
        if not handlers or not self.dialog:
            return
        self._settings_wheel_active_inner = tab_inner
        self.dialog.bind_all("<MouseWheel>", handlers["mousewheel"])
        self.dialog.bind_all("<Button-4>", handlers["linux_up"])
        self.dialog.bind_all("<Button-5>", handlers["linux_down"])

    def _attach_tab_mousewheel(self, tab_inner):
        """Bindet Mausrad rekursiv an alle Widgets im Tab (nach Tab-Aufbau)."""
        bind_fn = getattr(tab_inner, "_bind_mousewheel_to_widget", None)
        if bind_fn:
            bind_fn(tab_inner)

    def _on_settings_notebook_tab_changed(self, event=None):
        """Deaktiviert Mausrad-Scroll beim Tab-Wechsel bis der Cursor den Bereich betritt."""
        self._deactivate_tab_mousewheel()

    def _on_settings_dialog_destroy(self, event=None):
        if event and event.widget is not self.dialog:
            return
        self._deactivate_tab_mousewheel()

    def _widget_is_descendant(self, widget, ancestor):
        w = widget
        while w is not None:
            if w == ancestor:
                return True
            try:
                w = w.master
            except tk.TclError:
                break
        return False

    def _create_scrollable_tab_content(self, parent, padding=10):
        """
        Umschließt Tab-Inhalt mit vertikalem Scroll (Canvas + Scrollbar).
        Gibt den inneren Frame zurück — bestehende create_*_tab-Methoden bleiben unverändert.
        """
        parent.grid_rowconfigure(0, weight=1)
        parent.grid_columnconfigure(0, weight=1)

        container = tk.Frame(parent)
        container.grid(row=0, column=0, sticky="nsew")
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0)
        scrollbar = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
        canvas.grid(row=0, column=0, sticky="nsew")

        inner = tk.Frame(canvas, padx=padding, pady=padding)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _update_scrollbar_visibility():
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if not bbox or canvas.winfo_height() <= 0:
                scrollbar.grid_remove()
                return
            content_height = bbox[3] - bbox[1]
            if content_height > canvas.winfo_height():
                scrollbar.grid(row=0, column=1, sticky="ns")
            else:
                scrollbar.grid_remove()

        def _refresh_scroll():
            canvas.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            _update_scrollbar_visibility()

        def _on_inner_configure(event=None):
            _refresh_scroll()

        def _on_canvas_configure(event):
            canvas.itemconfig(window_id, width=event.width)
            _update_scrollbar_visibility()

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        canvas.configure(yscrollcommand=scrollbar.set)

        def _should_scroll():
            bbox = canvas.bbox("all")
            if not bbox or canvas.winfo_height() <= 0:
                return False
            return (bbox[3] - bbox[1]) > canvas.winfo_height()

        def _on_mousewheel(event):
            if self._settings_wheel_active_inner is not inner:
                return
            if _should_scroll():
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_linux_scroll_up(event):
            if self._settings_wheel_active_inner is not inner:
                return
            if _should_scroll():
                canvas.yview_scroll(-1, "units")

        def _on_linux_scroll_down(event):
            if self._settings_wheel_active_inner is not inner:
                return
            if _should_scroll():
                canvas.yview_scroll(1, "units")

        inner._scroll_wheel_handlers = {
            "mousewheel": _on_mousewheel,
            "linux_up": _on_linux_scroll_up,
            "linux_down": _on_linux_scroll_down,
        }

        def _bind_mousewheel(widget):
            widget.bind("<MouseWheel>", _on_mousewheel)
            widget.bind("<Button-4>", _on_linux_scroll_up)
            widget.bind("<Button-5>", _on_linux_scroll_down)
            for child in widget.winfo_children():
                _bind_mousewheel(child)

        def _on_scroll_area_enter(event):
            self._activate_tab_mousewheel(inner)

        def _on_scroll_area_leave(event):
            if self._settings_wheel_active_inner is not inner:
                return
            target = event.widget.winfo_containing(event.x_root, event.y_root)
            if target is not None and self._widget_is_descendant(target, container):
                return
            self._deactivate_tab_mousewheel()

        for widget in (container, canvas, inner):
            widget.bind("<Enter>", _on_scroll_area_enter, add="+")
            widget.bind("<Leave>", _on_scroll_area_leave, add="+")

        inner._scroll_canvas = canvas
        inner._scroll_container = container
        inner._scroll_refresh = _refresh_scroll
        inner._bind_mousewheel_to_widget = _bind_mousewheel

        return inner

    def _add_scrollable_notebook_tab(self, title):
        """Notebook-Tab mit scrollbarem Inhalts-Frame anlegen."""
        shell = ttk.Frame(self.notebook)
        self.notebook.add(shell, text=title)
        return self._create_scrollable_tab_content(shell, padding=10)

    def create_widgets(self):
        """Erstellt die Widgets für den Dialog mit Tab-Layout"""

        main_frame = tk.Frame(self.dialog, padx=15, pady=15)
        main_frame.pack(fill="both", expand=True)
        main_frame.grid_columnconfigure(0, weight=1)

        # Tab-View erstellen
        style = ttk.Style()
        style.configure('Settings.TNotebook.Tab',
                       font=('Arial', 10, 'bold'),
                       padding=[20, 8])

        self.notebook = ttk.Notebook(main_frame, style='Settings.TNotebook')
        self.notebook.pack(fill="both", expand=True, pady=(0, 15))

        # --- Tab 1: Allgemein ---
        self.tab_allgemein = self._add_scrollable_notebook_tab("Allgemein")
        self.create_allgemein_tab()
        self._attach_tab_mousewheel(self.tab_allgemein)

        # --- Tab 2: Encoding ---
        self.tab_encoding = self._add_scrollable_notebook_tab("Encoding")
        self.create_encoding_tab()
        self._attach_tab_mousewheel(self.tab_encoding)

        # --- Tab 3: Backup ---
        self.tab_backup = self._add_scrollable_notebook_tab("Backup")
        self.create_backup_tab()
        self._attach_tab_mousewheel(self.tab_backup)

        # --- Tab 4: Version ---
        self.tab_extras = self._add_scrollable_notebook_tab("Version")
        self.create_extras_tab()
        self._attach_tab_mousewheel(self.tab_extras)

        # --- Tab 5: Erweitert (Video-QR) ---
        self.tab_erweitert = self._add_scrollable_notebook_tab("Erweitert")
        self.create_erweitert_tab()
        self._attach_tab_mousewheel(self.tab_erweitert)

        self.notebook.bind("<<NotebookTabChanged>>", self._on_settings_notebook_tab_changed)
        self.dialog.bind("<Destroy>", self._on_settings_dialog_destroy, add="+")

        # --- Dialog-Buttons (außerhalb der Tabs) ---
        button_frame = tk.Frame(main_frame)
        button_frame.pack(side="bottom", fill="x", pady=(10, 0))

        cancel_button = tk.Button(
            button_frame, text="Abbrechen", font=("Arial", 11),
            command=self.dialog.destroy, bg="#f44336", fg="white", width=12, height=1
        )
        cancel_button.pack(side="right", padx=5)

        save_button = tk.Button(
            button_frame, text="Speichern", font=("Arial", 11, "bold"),
            command=self.save_settings, bg="#4CAF50", fg="white", width=12, height=1
        )
        save_button.pack(side="right", padx=5)

        # Enter-Taste binden
        self.dialog.bind('<Return>', lambda e: self.save_settings())
        # Escape-Taste binden
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def create_allgemein_tab(self):
        """Erstellt den Tab 'Allgemein'"""
        # --- Sektion 1: Speicherort & Dauer ---
        storage_frame = ttk.LabelFrame(self.tab_allgemein, text="Speicherort", padding=(10, 10))
        storage_frame.pack(fill="x", pady=(0, 15))
        storage_frame.grid_columnconfigure(1, weight=1)

        # Speicherort
        tk.Label(storage_frame, text="Speicherort:", font=("Arial", 11)).grid(row=0, column=0, sticky="w", padx=5, pady=5)

        speicherort_entry_frame = tk.Frame(storage_frame)
        speicherort_entry_frame.grid(row=0, column=1, sticky="ew", padx=5)
        speicherort_entry_frame.grid_columnconfigure(0, weight=1)

        speicherort_entry = tk.Entry(speicherort_entry_frame, textvariable=self.speicherort_var,
                                     font=("Arial", 10), state="readonly")
        speicherort_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        speicherort_button = tk.Button(speicherort_entry_frame, text="Wählen...",
                                       command=self.waehle_speicherort)
        speicherort_button.grid(row=0, column=1, sticky="e")

        # Intro Dauer
        tk.Label(storage_frame, text="Intro Dauer (Sek.):", font=("Arial", 11)).grid(row=1, column=0, sticky="w", padx=5, pady=5)

        dauer_frame = tk.Frame(storage_frame, bg="white", relief=tk.RAISED, borderwidth=1)
        dauer_frame.grid(row=1, column=1, sticky="w", padx=5, pady=5)

        self.dauer_display = tk.Label(
            dauer_frame, textvariable=self.dauer_var, font=("Arial", 10),
            bg="white", fg="black", anchor="w", width=6, padx=8, pady=4, cursor="hand2"
        )
        self.dauer_display.grid(row=0, column=0, sticky="ew")

        dauer_arrow = tk.Label(dauer_frame, text="▼", font=("Arial", 8),
                              bg="white", fg="black", padx=5, cursor="hand2")
        dauer_arrow.grid(row=0, column=1)

        dauer_dropdown = tk.OptionMenu(storage_frame, self.dauer_var, "1", "3", "4", "5", "6", "7", "8", "9", "10")
        dauer_dropdown["menu"].config(font=("Arial", 10), bg="white", fg="black",
                                      activebackground="#2196F3", activeforeground="white")

        def show_dauer_menu(event):
            dauer_dropdown.event_generate("<Button-1>")
            x = dauer_frame.winfo_rootx()
            y = dauer_frame.winfo_rooty() + dauer_frame.winfo_height()
            try:
                dauer_dropdown["menu"].tk_popup(x, y)
            finally:
                dauer_dropdown["menu"].grab_release()

        dauer_frame.bind("<Button-1>", show_dauer_menu)
        self.dauer_display.bind("<Button-1>", show_dauer_menu)
        dauer_arrow.bind("<Button-1>", show_dauer_menu)

        def on_enter(e):
            dauer_frame.config(bg="#E3F2FD")
            self.dauer_display.config(bg="#E3F2FD")
            dauer_arrow.config(bg="#E3F2FD")

        def on_leave(e):
            dauer_frame.config(bg="white")
            self.dauer_display.config(bg="white")
            dauer_arrow.config(bg="white")

        for widget in [dauer_frame, self.dauer_display, dauer_arrow]:
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)

        # --- Sektion: Formular beim Zurücksetzen ---
        reset_form_frame = ttk.LabelFrame(self.tab_allgemein, text="Formular beim Zurücksetzen", padding=(10, 10))
        reset_form_frame.pack(fill="x", pady=(0, 15))
        tk.Checkbutton(
            reset_form_frame,
            text="Tandemmaster beim Zurücksetzen beibehalten",
            variable=self.keep_tandemmaster_on_session_reset_var,
            font=("Arial", 10),
        ).pack(anchor="w", padx=5, pady=2)
        tk.Checkbutton(
            reset_form_frame,
            text="Videospringer beim Zurücksetzen beibehalten",
            variable=self.keep_videospringer_on_session_reset_var,
            font=("Arial", 10),
        ).pack(anchor="w", padx=5, pady=2)

        # --- Sektion: Formular-Modus ---
        form_mode_frame = ttk.LabelFrame(self.tab_allgemein, text="Formular", padding=(10, 10))
        form_mode_frame.pack(fill="x", pady=(0, 15))
        tk.Checkbutton(
            form_mode_frame,
            text="Oldschool Modus (Vorname/Nachname/Email/Telefon statt Kunden-/Booking-ID)",
            variable=self.oldschool_mode_var,
            font=("Arial", 10),
        ).pack(anchor="w", padx=5, pady=2)

        # --- Sektion: Server-Verbindung ---
        server_frame = ttk.LabelFrame(self.tab_allgemein, text="Server-Verbindung", padding=(10, 10))
        server_frame.pack(fill="x", pady=(0, 10))
        server_frame.grid_columnconfigure(1, weight=1)

        tk.Label(server_frame, text="Adresse:", font=("Arial", 11)).grid(
            row=0, column=0, sticky="w", padx=5, pady=5)
        self.server_entry = tk.Entry(server_frame, textvariable=self.server_var, font=("Arial", 11))
        self.server_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=5, pady=5)

        tk.Label(server_frame, text="Beispiel: smb://server/share oder \\\\server\\share oder C:\\lokaler\\pfad",
                font=("Arial", 9), fg="gray").grid(row=1, column=1, columnspan=3, sticky="w", padx=5)

        tk.Label(server_frame, text="Login:", font=("Arial", 11)).grid(
            row=2, column=0, sticky="w", padx=5, pady=(10, 5))
        self.login_entry = tk.Entry(server_frame, textvariable=self.login_var, font=("Arial", 11), width=20)
        self.login_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=(10, 5))

        tk.Label(server_frame, text="Passwort:", font=("Arial", 11)).grid(
            row=2, column=2, sticky="w", padx=(10, 5), pady=(10, 5))
        self.password_entry = tk.Entry(server_frame, textvariable=self.password_var,
                                       font=("Arial", 11), width=20, show="*")
        self.password_entry.grid(row=2, column=3, sticky="ew", padx=5, pady=(10, 5))

    def create_backup_tab(self):
        """Erstellt den Tab 'Backup'"""
        # --- SD-Karten Backup ---
        backup_frame = ttk.LabelFrame(self.tab_backup, text="SD-Karten Backup", padding=(10, 10))
        backup_frame.pack(fill="x", pady=(0, 10))
        backup_frame.grid_columnconfigure(1, weight=1)

        # Backup Ordner - Entry-Feld über beide Spalten damit es die volle Breite nutzt
        backup_folder_container = tk.Frame(backup_frame)
        backup_folder_container.grid(row=0, column=0, columnspan=2, sticky="ew", padx=5, pady=5)
        backup_folder_container.grid_columnconfigure(1, weight=1)

        tk.Label(backup_folder_container, text="Backup Ordner:", font=("Arial", 11)).grid(row=0, column=0, sticky="w", padx=(0, 5))

        backup_folder_entry_frame = tk.Frame(backup_folder_container)
        backup_folder_entry_frame.grid(row=0, column=1, sticky="ew")
        backup_folder_entry_frame.grid_columnconfigure(0, weight=1)

        backup_folder_entry = tk.Entry(backup_folder_entry_frame, textvariable=self.sd_backup_folder_var,
                                       font=("Arial", 10), state="readonly")
        backup_folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        backup_folder_button = tk.Button(backup_folder_entry_frame, text="Wählen...",
                                         command=self.waehle_backup_ordner)
        backup_folder_button.grid(row=0, column=1, sticky="e")

        # Haupt-Checkbox: Automatischer Backup
        self.sd_auto_backup_checkbox = tk.Checkbutton(
            backup_frame,
            text="Automatischer Backup von SD-Karte",
            variable=self.sd_auto_backup_var,
            font=("Arial", 10),
            command=self.on_auto_backup_toggle
        )
        self.sd_auto_backup_checkbox.grid(row=1, column=0, sticky="w", padx=5, pady=2)

        # PC Name (nur sichtbar wenn Auto-Backup aktiviert)
        self.sd_pc_name_frame = tk.Frame(backup_frame)
        tk.Label(self.sd_pc_name_frame, text="PC Name:", font=("Arial", 10)).pack(side="left", padx=(0, 8))
        tk.Entry(self.sd_pc_name_frame, textvariable=self.sd_pc_name_var, font=("Arial", 10), width=28).pack(
            side="left", fill="x", expand=True
        )

        # Abhängige Checkboxen (nur sichtbar wenn Auto-Backup aktiviert)

        # 1. Automatisch importieren (ERSTE Option)
        self.sd_auto_import_checkbox = tk.Checkbutton(
            backup_frame,
            text="Automatisch importieren in Aero Tandem Studio",
            variable=self.sd_auto_import_var,
            font=("Arial", 10)
        )

        # 2. Größen-Limit Option
        self.sd_size_limit_checkbox = tk.Checkbutton(
            backup_frame,
            text="Warnung bei zu vielen Dateien auf SD-Karte",
            variable=self.sd_size_limit_enabled_var,
            font=("Arial", 10),
            command=self.on_size_limit_toggle
        )

        # Sub-Option: Größen-Eingabe (noch mehr eingerückt)
        size_limit_frame = tk.Frame(backup_frame)
        self.sd_size_limit_frame = size_limit_frame  # Referenz speichern

        tk.Label(size_limit_frame, text="Maximale Dateigröße (MB):", font=("Arial", 9)).pack(side='left', padx=(0, 5))

        size_limit_entry = tk.Entry(size_limit_frame, textvariable=self.sd_size_limit_mb_var,
                                    font=("Arial", 9), width=10)
        size_limit_entry.pack(side='left')

        tk.Label(size_limit_frame, text="(z.B. 2000 für 2GB)", font=("Arial", 8), fg="gray").pack(side='left', padx=(5, 0))

        # 3. SD-Karte nach Backup leeren
        self.sd_clear_checkbox = tk.Checkbutton(
            backup_frame,
            text="SD-Karte nach Backup leeren (löscht nur erfolgreich gesicherte Dateien)",
            variable=self.sd_clear_var,
            font=("Arial", 10)
        )

        # NEU: Nur-neue-Dateien Checkbox + Verlauf-Button (gleiche Ebene)
        row_idx = 8
        self.sd_skip_checkbox = tk.Checkbutton(
            backup_frame,
            text="Nur neue Dateien sichern/importieren (Duplikate überspringen)",
            variable=self.sd_skip_processed_var,
            font=("Arial", 10),
            command=self.on_skip_processed_toggle
        )
        self.sd_skip_checkbox.grid(row=row_idx, column=0, sticky="w", padx=5, pady=(8, 2))

        self.history_button = tk.Button(
            backup_frame,
            text="Verlauf anzeigen…",
            command=self._open_processed_history_dialog,
            width=18
        )
        self.history_button.grid(row=row_idx, column=1, sticky="e", padx=5, pady=(8, 2))

        # NEU: Sub-Option für manuellen Import (eingerückt, nur sichtbar wenn skip_processed aktiv)
        row_idx += 1
        self.sd_skip_manual_checkbox = tk.Checkbutton(
            backup_frame,
            text="Auch manuell importierte Dateien merken und prüfen",
            variable=self.sd_skip_processed_manual_var,
            font=("Arial", 9),
        )
        # Wird nur angezeigt wenn sd_skip_processed aktiv ist


    def _open_processed_history_dialog(self):
        try:
            from src.gui.components.processed_files_dialog import ProcessedFilesDialog
            dlg = ProcessedFilesDialog(self.dialog)
            dlg.show()
        except Exception as e:
            messagebox.showerror("Fehler", f"Verlauf konnte nicht geöffnet werden:\n{e}", parent=self.dialog)

    def create_encoding_tab(self):
        """Erstellt den Tab 'Encoding'"""

        # --- Sektion 1: Codec-Auswahl ---
        codec_frame = ttk.LabelFrame(self.tab_encoding, text="Video-Codec", padding=(10, 10))
        codec_frame.pack(fill="x", pady=(0, 15))
        codec_frame.grid_columnconfigure(0, weight=1)

        # Info-Text oben
        info_text = "Wählen Sie den Codec für die finale Videoerstellung:"
        tk.Label(codec_frame, text=info_text, font=("Arial", 10), fg="gray", wraplength=500, justify="left").grid(
            row=0, column=0, sticky="w", padx=5, pady=(0, 10))

        # Radio-Buttons für Codec-Auswahl mit inline Beschreibungen
        codec_options = [
            ("auto", "Auto (empfohlen)", "Automatische Codec-Erkennung. Keine Neucodierung wenn alle Clips kompatibel sind."),
            ("h264", "H.264 (AVC)", "Hohe Kompatibilität, gute Qualität und effiziente Kompression."),
            ("h265", "H.265 (HEVC)", "Bessere Kompression als H.264, benötigt jedoch mehr Rechenleistung."),
            ("vp9", "VP9", "Optimiert für Web-Streaming, Open-Source."),
            ("av1", "AV1", "Beste Kompression, langsameres Encoding, zukunftssicher.")
        ]

        current_row = 1
        # Feste Breite für Radiobutton-Spalte, damit Beschreibungen ausgerichtet sind
        max_label_width = 25  # Breite in Zeichen

        for idx, (value, label, description) in enumerate(codec_options):
            # Container-Frame für Option (horizontal layout)
            option_frame = tk.Frame(codec_frame)
            option_frame.grid(row=current_row, column=0, sticky="ew", padx=5, pady=5)
            option_frame.grid_columnconfigure(1, weight=1)  # Beschreibung kann expandieren

            # Radiobutton links mit fester Breite
            radio = tk.Radiobutton(
                option_frame,
                text=label,
                variable=self.codec_var,
                value=value,
                font=("Arial", 10, "bold"),
                command=self.on_codec_changed,
                width=max_label_width,
                anchor="w"
            )
            radio.grid(row=0, column=0, sticky="w", padx=(5, 10))

            # Beschreibung rechts daneben (inline, alle starten an gleicher Position!)
            desc_label = tk.Label(
                option_frame,
                text=description,
                font=("Arial", 9),
                fg="gray",
                wraplength=450,
                justify="left",
                anchor="w"
            )
            desc_label.grid(row=0, column=1, sticky="w")

            current_row += 1

        # Hinweis für Wasserzeichen-Video
        separator = ttk.Separator(codec_frame, orient='horizontal')
        separator.grid(row=current_row, column=0, sticky="ew", pady=(10, 10), padx=5)

        watermark_note = tk.Label(
            codec_frame,
            text="ℹ️ Hinweis: Wasserzeichen-Videos werden immer mit H.264 codiert (240p, optimiert für Vorschau).",
            font=("Arial", 9),
            fg="#2196F3",
            wraplength=650,
            justify="left"
        )
        watermark_note.grid(row=current_row+1, column=0, sticky="w", padx=10, pady=(0, 5))

        # --- Sektion 2: Erweitert ---
        advanced_frame = ttk.LabelFrame(self.tab_encoding, text="Erweitert", padding=(10, 10))
        advanced_frame.pack(fill="x", pady=(0, 10))
        advanced_frame.grid_columnconfigure(0, weight=1)

        # Hardware-Beschleunigung Container
        hw_container = tk.Frame(advanced_frame)
        hw_container.grid(row=0, column=0, sticky="w", padx=5, pady=5)

        # Hardware-Beschleunigung Checkbox
        self.hw_accel_checkbox = tk.Checkbutton(
            hw_container,
            text="Hardware-Beschleunigung aktivieren (empfohlen)",
            variable=self.hardware_acceleration_var,
            font=("Arial", 10),
            command=self.on_hw_accel_toggle
        )
        self.hw_accel_checkbox.pack(side="left")

        # CircularSpinner für Hardware-Erkennung (zunächst versteckt)
        self.hw_spinner = CircularSpinner(hw_container, size=20, line_width=3, color="#007ACC", speed=8)
        # Wird nur angezeigt während Hardware erkannt wird

        # Info-Label für erkannte Hardware
        self.hw_info_label = tk.Label(
            advanced_frame,
            text="Erkannte Hardware wird beim Laden angezeigt",
            font=("Arial", 9),
            fg="gray",
            anchor="w"
        )
        self.hw_info_label.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 5))

        # Flag für laufende Hardware-Erkennung
        self.hw_detection_running = False

        # --- Paralleles Processing ---
        # Separator-Linie
        separator2 = ttk.Separator(advanced_frame, orient='horizontal')
        separator2.grid(row=2, column=0, sticky="ew", pady=10)

        # Paralleles Processing Container
        parallel_container = tk.Frame(advanced_frame)
        parallel_container.grid(row=3, column=0, sticky="w", padx=5, pady=5)

        # Paralleles Processing Checkbox
        self.parallel_processing_checkbox = tk.Checkbutton(
            parallel_container,
            text="Paralleles Video-Processing aktivieren (Multi-Core)",
            variable=self.parallel_processing_var,
            font=("Arial", 10),
            command=self.on_parallel_processing_toggle
        )
        self.parallel_processing_checkbox.pack(side="left")

        # Info-Label für paralleles Processing
        self.parallel_info_label = tk.Label(
            advanced_frame,
            text="Paralleles Processing wird beim Laden konfiguriert",
            font=("Arial", 9),
            fg="gray",
            anchor="w"
        )
        self.parallel_info_label.grid(row=4, column=0, sticky="w", padx=20, pady=(0, 5))

        # --- Encoding-Strategie (nur bei festem Codec) ---
        separator3 = ttk.Separator(advanced_frame, orient='horizontal')
        separator3.grid(row=5, column=0, sticky="ew", pady=10)

        strategy_header = tk.Label(
            advanced_frame,
            text="Encoding-Strategie (bei festem Codec):",
            font=("Arial", 10, "bold"),
            anchor="w",
        )
        strategy_header.grid(row=6, column=0, sticky="w", padx=5, pady=(0, 5))

        self.encoding_strategy_per_clip_radio = tk.Radiobutton(
            advanced_frame,
            text="Pro Clip encodieren, dann zusammenfügen",
            variable=self.encoding_strategy_var,
            value="per_clip",
            font=("Arial", 10),
            anchor="w",
        )
        self.encoding_strategy_per_clip_radio.grid(row=7, column=0, sticky="w", padx=20, pady=2)

        self.encoding_strategy_combined_radio = tk.Radiobutton(
            advanced_frame,
            text="Zuerst zusammenfügen, dann einmal encodieren",
            variable=self.encoding_strategy_var,
            value="combined",
            font=("Arial", 10),
            anchor="w",
        )
        self.encoding_strategy_combined_radio.grid(row=8, column=0, sticky="w", padx=20, pady=2)

        self.encoding_strategy_hint_label = tk.Label(
            advanced_frame,
            text="Combined ist meist schneller bei wenigen einheitlichen Clips. "
                 "Pro Clip nutzt parallele Encodierung und besseren Cache.",
            font=("Arial", 9),
            fg="gray",
            wraplength=650,
            justify="left",
            anchor="w",
        )
        self.encoding_strategy_hint_label.grid(row=9, column=0, sticky="w", padx=20, pady=(0, 5))

        self.encoding_strategy_auto_hint_label = tk.Label(
            advanced_frame,
            text="Nur relevant bei festem Codec (H.264, H.265, VP9, AV1) — bei Auto deaktiviert.",
            font=("Arial", 9),
            fg="#888888",
            wraplength=650,
            justify="left",
            anchor="w",
        )
        self.encoding_strategy_auto_hint_label.grid(row=10, column=0, sticky="w", padx=20, pady=(0, 5))

        self.reencode_matching_clips_checkbox = tk.Checkbutton(
            advanced_frame,
            text="Neu encodieren, auch wenn alle Clips bereits den gewählten Codec haben",
            variable=self.reencode_matching_clips_var,
            font=("Arial", 10),
            anchor="w",
        )
        self.reencode_matching_clips_checkbox.grid(row=11, column=0, sticky="w", padx=20, pady=(5, 2))

        self.reencode_matching_clips_hint_label = tk.Label(
            advanced_frame,
            text="Standard: Stream-Copy wenn Codec und Formate bereits passen (schneller).",
            font=("Arial", 9),
            fg="gray",
            wraplength=650,
            justify="left",
            anchor="w",
        )
        self.reencode_matching_clips_hint_label.grid(row=12, column=0, sticky="w", padx=20, pady=(0, 5))

    def _update_encoding_strategy_state(self):
        """Aktiviert/deaktiviert Encoding-Strategie abhängig von Codec-Auswahl."""
        is_auto = self.codec_var.get() == "auto"
        state = tk.DISABLED if is_auto else tk.NORMAL
        for widget in (
            self.encoding_strategy_per_clip_radio,
            self.encoding_strategy_combined_radio,
            self.encoding_strategy_hint_label,
            self.reencode_matching_clips_checkbox,
            self.reencode_matching_clips_hint_label,
        ):
            widget.config(state=state)
        if is_auto:
            self.encoding_strategy_auto_hint_label.config(fg="#2196F3")
        else:
            self.encoding_strategy_auto_hint_label.config(fg="gray")

    def on_codec_changed(self):
        """Wird aufgerufen wenn ein anderer Codec ausgewählt wird"""
        selected_codec = self.codec_var.get()
        print(f"Codec geändert zu: {selected_codec}")
        self._update_encoding_strategy_state()

        # Aktualisiere Hardware-Info mit dem neuen Codec (falls Hardware-Beschleunigung aktiv)
        if self.hardware_acceleration_var.get() and not self.hw_detection_running:
            self._update_hardware_info_for_codec(selected_codec)

    def on_hw_accel_toggle(self):
        """Wird aufgerufen wenn die Hardware-Beschleunigung Checkbox geändert wird"""
        is_enabled = self.hardware_acceleration_var.get()

        if is_enabled:
            # Zeige und starte Spinner sofort
            self.hw_spinner.pack(side="left", padx=(5, 0))
            self.hw_spinner.start()
            self.hw_info_label.config(text="Erkenne Hardware...", fg="gray")

            # Verhindere mehrfache gleichzeitige Erkennung
            if self.hw_detection_running:
                return

            self.hw_detection_running = True

            # Starte Hardware-Erkennung asynchron im Hintergrund
            import threading
            def detect_hardware_async():
                try:
                    from src.utils.hardware_acceleration import HardwareAccelerationDetector
                    detector = HardwareAccelerationDetector()

                    # Hole den aktuell gewählten Codec
                    selected_codec = self.codec_var.get()
                    display_codec = selected_codec if selected_codec != "auto" else "h264"

                    hw_info_text = detector.get_hardware_info_string(display_codec)

                    # Aktualisiere UI im Haupt-Thread
                    self.dialog.after(0, self._update_hw_info_success, hw_info_text)
                except Exception as e:
                    # Fehler im Haupt-Thread anzeigen
                    self.dialog.after(0, self._update_hw_info_error, str(e))

            # Starte Thread
            threading.Thread(target=detect_hardware_async, daemon=True).start()
        else:
            # Hardware-Beschleunigung deaktiviert
            self.hw_spinner.stop()
            self.hw_spinner.pack_forget()
            self.hw_info_label.config(text="Hardware-Beschleunigung deaktiviert (Software-Encoding)", fg="gray")
            self.hw_detection_running = False

            # Aktualisiere auch die Paralleles Processing Info, falls aktiviert
            if self.parallel_processing_var.get():
                self._update_parallel_processing_info()

    def _update_hw_info_success(self, hw_info_text):
        """Aktualisiert die Hardware-Info nach erfolgreicher Erkennung (im Haupt-Thread)"""
        self.hw_spinner.stop()
        self.hw_spinner.pack_forget()
        self.hw_info_label.config(text=f"✓ {hw_info_text}", fg="green")
        self.hw_detection_running = False

        # Aktualisiere auch die Paralleles Processing Info, falls aktiviert
        if self.parallel_processing_var.get():
            self._update_parallel_processing_info()

    def _update_hw_info_error(self, error_msg):
        """Aktualisiert die Hardware-Info bei Fehler (im Haupt-Thread)"""
        self.hw_spinner.stop()
        self.hw_spinner.pack_forget()
        self.hw_info_label.config(text=f"⚠ Fehler bei Hardware-Erkennung: {error_msg}", fg="orange")
        self.hw_detection_running = False

        # Aktualisiere auch die Paralleles Processing Info, falls aktiviert
        if self.parallel_processing_var.get():
            self._update_parallel_processing_info()

    def _update_hardware_info_for_codec(self, codec):
        """
        Aktualisiert die Hardware-Info für einen spezifischen Codec

        Args:
            codec: Der Codec (z.B. 'h264', 'h265', 'vp9', 'av1')
        """
        try:
            from src.utils.hardware_acceleration import HardwareAccelerationDetector
            detector = HardwareAccelerationDetector()

            # Mappe "auto" auf h264
            display_codec = codec if codec != "auto" else "h264"

            hw_info_text = detector.get_hardware_info_string(display_codec)
            self.hw_info_label.config(text=f"✓ {hw_info_text}", fg="green")
        except Exception as e:
            print(f"Fehler beim Aktualisieren der Hardware-Info: {e}")
            # Behalte die alte Info bei Fehler

    def on_auto_backup_toggle(self):
        """Wird aufgerufen wenn die Auto-Backup Checkbox geändert wird"""
        is_enabled = self.sd_auto_backup_var.get()

        if is_enabled:
            self.sd_pc_name_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=30, pady=2)
            # Zeige abhängige Checkboxen in neuer Reihenfolge (alle eingerückt mit padx=30)
            # 1. Automatisch importieren (ERSTE Option)
            self.sd_auto_import_checkbox.grid(row=3, column=0, sticky="w", padx=30, pady=2)

            # 2. Größen-Limit Option
            self.sd_size_limit_checkbox.grid(row=4, column=0, sticky="w", padx=30, pady=(8, 2))
            self.on_size_limit_toggle()  # Zeige/Verstecke Eingabefeld

            # 3. SD-Karte leeren
            self.sd_clear_checkbox.grid(row=6, column=0, sticky="w", padx=30, pady=2)
        else:
            # Verstecke und deaktiviere alle abhängigen Checkboxen
            self.sd_pc_name_frame.grid_forget()
            self.sd_auto_import_checkbox.grid_forget()
            self.sd_size_limit_checkbox.grid_forget()
            self.sd_size_limit_frame.grid_forget()
            self.sd_clear_checkbox.grid_forget()
            self.sd_skip_manual_checkbox.grid_forget()
            self.sd_auto_import_var.set(False)
            self.sd_size_limit_enabled_var.set(False)
            self.sd_clear_var.set(False)
            self.sd_skip_processed_manual_var.set(False)

        # "Nur neue Dateien" Checkbox und Verlauf-Button IMMER anzeigen
        self.sd_skip_checkbox.grid(row=8, column=0, sticky="w", padx=5, pady=(8, 2))
        self.history_button.grid(row=8, column=1, sticky="e", padx=5, pady=(8, 2))

        # Sub-Option für manuellen Import (conditional)
        self.on_skip_processed_toggle()

    def on_skip_processed_toggle(self):
        """Wird aufgerufen wenn die Skip-Processed Checkbox geändert wird"""
        is_enabled = self.sd_skip_processed_var.get()

        if is_enabled:
            # Zeige Sub-Option für manuellen Import (eingerückt)
            self.sd_skip_manual_checkbox.grid(row=9, column=0, sticky="w", padx=30, pady=(0, 2))
        else:
            # Verstecke Sub-Option
            self.sd_skip_manual_checkbox.grid_forget()
            self.sd_skip_processed_manual_var.set(False)

    def on_size_limit_toggle(self):
        """Wird aufgerufen wenn die Größen-Limit Checkbox geändert wird"""
        is_enabled = self.sd_size_limit_enabled_var.get()

        if is_enabled:
            # Zeige Eingabefeld (noch mehr eingerückt als Checkbox)
            self.sd_size_limit_frame.grid(row=5, column=0, sticky="w", padx=50, pady=(0, 2))
        else:
            # Verstecke Eingabefeld
            self.sd_size_limit_frame.grid_forget()

    def on_parallel_processing_toggle(self):
        """Wird aufgerufen wenn die Paralleles Processing Checkbox geändert wird"""
        is_enabled = self.parallel_processing_var.get()

        if is_enabled:
            self._update_parallel_processing_info()
        else:
            self.parallel_info_label.config(text="Paralleles Processing deaktiviert (sequenziell)", fg="gray")

    def _update_parallel_processing_info(self):
        """Aktualisiert die Paralleles Processing Info basierend auf aktuellen Einstellungen"""
        # Zeige CPU-Info und optimale Worker-Anzahl
        import threading
        def detect_cpu_info_async():
            try:
                import multiprocessing
                cpu_count = multiprocessing.cpu_count()

                # Hole Hardware-Beschleunigung Status für Worker-Berechnung
                hw_accel_enabled = self.hardware_acceleration_var.get()

                if hw_accel_enabled:
                    workers = min(cpu_count, 4)
                    info_text = f"✓ {workers} Worker-Threads (Hardware-Encoding, {cpu_count} CPU-Kerne)"
                else:
                    workers = max(1, cpu_count // 2)
                    info_text = f"✓ {workers} Worker-Threads (Software-Encoding, {cpu_count} CPU-Kerne)"

                # Aktualisiere UI im Haupt-Thread
                self.dialog.after(0, lambda: self.parallel_info_label.config(text=info_text, fg="green"))
            except Exception as e:
                error_text = f"⚠ Fehler bei CPU-Erkennung: {str(e)}"
                self.dialog.after(0, lambda: self.parallel_info_label.config(text=error_text, fg="orange"))

        # Starte Thread
        threading.Thread(target=detect_cpu_info_async, daemon=True).start()

    def create_erweitert_tab(self):
        """Erstellt den Tab 'Erweitert' (QR-Code-Analyse)."""
        qr_root_frame = ttk.LabelFrame(
            self.tab_erweitert,
            text="QR-Code Analyse",
            padding=(10, 10),
        )
        qr_root_frame.pack(fill="x", pady=(0, 10))
        qr_root_frame.grid_columnconfigure(1, weight=1)

        tk.Label(
            qr_root_frame,
            text="Parallele Worker:",
            font=("Arial", 10),
        ).grid(row=0, column=0, sticky="w", padx=5, pady=(0, 5))
        workers_frame = tk.Frame(qr_root_frame)
        workers_frame.grid(row=0, column=1, sticky="w", padx=5, pady=(0, 5))
        self.qr_workers_entry = tk.Entry(
            workers_frame,
            textvariable=self.qr_video_parallel_workers_var,
            font=("Arial", 10),
            width=5,
        )
        self.qr_workers_entry.pack(side="left")
        tk.Label(
            workers_frame,
            text="(1–4, Standard: 2)",
            font=("Arial", 9),
            fg="gray",
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            qr_root_frame,
            text="Gilt für Video- und Foto-Parallelmodus. Ab 2 Workern startet ein Worker "
                 "am Ende der Liste, die übrigen am Anfang.",
            font=("Arial", 9),
            fg="gray",
            justify="left",
            wraplength=620,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 10))

        qr_separator = ttk.Separator(qr_root_frame, orient="horizontal")
        qr_separator.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))

        video_qr_frame = ttk.LabelFrame(
            qr_root_frame,
            text="Videos",
            padding=(8, 8),
        )
        video_qr_frame.grid(row=3, column=0, columnspan=2, sticky="ew", padx=2, pady=(0, 8))
        video_qr_frame.grid_columnconfigure(1, weight=1)

        tk.Label(video_qr_frame, text="Zu prüfende Clips:", font=("Arial", 10)).grid(
            row=0, column=0, sticky="nw", padx=5, pady=5,
        )
        scope_frame = tk.Frame(video_qr_frame)
        scope_frame.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        tk.Radiobutton(
            scope_frame,
            text="Nur erster Clip",
            variable=self.qr_video_scan_scope_var,
            value="first",
            font=("Arial", 10),
            command=self._on_qr_scan_scope_changed,
        ).pack(anchor="w")
        tk.Radiobutton(
            scope_frame,
            text="Alle Clips (Abbruch beim ersten Treffer)",
            variable=self.qr_video_scan_scope_var,
            value="all",
            font=("Arial", 10),
            command=self._on_qr_scan_scope_changed,
        ).pack(anchor="w")

        tk.Label(video_qr_frame, text="Scan-Dauer pro Clip (Sek.):", font=("Arial", 10)).grid(
            row=1, column=0, sticky="w", padx=5, pady=5,
        )
        tk.Entry(
            video_qr_frame,
            textvariable=self.qr_video_scan_seconds_var,
            font=("Arial", 10),
            width=8,
        ).grid(row=1, column=1, sticky="w", padx=5, pady=5)
        tk.Label(
            video_qr_frame,
            text="Wie viele Sekunden ab Clip-Anfang geprüft werden (z. B. 3–5).",
            font=("Arial", 9),
            fg="gray",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 6))

        tk.Label(video_qr_frame, text="Frame-Abstand:", font=("Arial", 10)).grid(
            row=3, column=0, sticky="w", padx=5, pady=5,
        )
        tk.Entry(
            video_qr_frame,
            textvariable=self.qr_video_frame_step_var,
            font=("Arial", 10),
            width=8,
        ).grid(row=3, column=1, sticky="w", padx=5, pady=5)
        tk.Label(
            video_qr_frame,
            text="Nur jeden N-ten Frame prüfen (10 ≈ 3×/s bei 30 fps). Höher = schneller.",
            font=("Arial", 9),
            fg="gray",
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 8))

        self.qr_parallel_checkbox = tk.Checkbutton(
            video_qr_frame,
            text="Parallele Clip-Prüfung (Hybrid)",
            variable=self.qr_video_parallel_enabled_var,
            font=("Arial", 10, "bold"),
        )
        self.qr_parallel_checkbox.grid(row=5, column=0, columnspan=2, sticky="w", padx=5, pady=(0, 4))
        tk.Label(
            video_qr_frame,
            text="Clip 1 wird zuerst allein geprüft. Danach werden die übrigen Clips parallel "
                 "durchsucht (nur bei „Alle Clips“).",
            font=("Arial", 9),
            fg="gray",
            justify="left",
            wraplength=580,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 4))

        photo_qr_frame = ttk.LabelFrame(
            qr_root_frame,
            text="Fotos",
            padding=(8, 8),
        )
        photo_qr_frame.grid(row=4, column=0, columnspan=2, sticky="ew", padx=2, pady=(0, 2))

        self.qr_photo_parallel_checkbox = tk.Checkbutton(
            photo_qr_frame,
            text="Parallele Foto-Prüfung (bidirektional)",
            variable=self.qr_photo_parallel_enabled_var,
            font=("Arial", 10, "bold"),
        )
        self.qr_photo_parallel_checkbox.pack(anchor="w", padx=5, pady=(0, 4))
        tk.Label(
            photo_qr_frame,
            text="Alle Fotos werden parallel durchsucht (Abbruch beim ersten Treffer).",
            font=("Arial", 9),
            fg="gray",
            justify="left",
            wraplength=580,
        ).pack(anchor="w", padx=20, pady=(0, 4))

        self.import_photo_parallel_checkbox = tk.Checkbutton(
            photo_qr_frame,
            text="Parallele Thumbnail-Erzeugung beim Import",
            variable=self.import_photo_parallel_enabled_var,
            font=("Arial", 10, "bold"),
        )
        self.import_photo_parallel_checkbox.pack(anchor="w", padx=5, pady=(4, 4))
        tk.Label(
            photo_qr_frame,
            text="Beschleunigt den Import bei vielen Fotos. Nutzt dieselbe Worker-Anzahl "
                 "wie die parallele QR-Prüfung.",
            font=("Arial", 9),
            fg="gray",
            justify="left",
            wraplength=580,
        ).pack(anchor="w", padx=20, pady=(0, 4))

        cache_frame = ttk.LabelFrame(
            self.tab_erweitert,
            text="Speicher & Cache",
            padding=(10, 10),
        )
        cache_frame.pack(fill="x", pady=(10, 0))

        tk.Label(
            cache_frame,
            text=(
                "Entfernt temporäre Vorschau-Ordner, kombinierte Preview-Dateien und "
                "Encode-Arbeitsordner (.aerotandem_work) am konfigurierten Speicherort.\n"
                "Importierte Videos und Fotos in der aktuellen Sitzung werden verworfen. "
                "Formular-Eingaben und Einstellungen bleiben erhalten."
            ),
            font=("Arial", 9),
            fg="gray",
            wraplength=650,
            justify="left",
        ).pack(anchor="w", padx=5, pady=(0, 8))

        tk.Checkbutton(
            cache_frame,
            text="Hardware-Erkennung neu laden (hw_cache.json)",
            variable=self.clear_hw_cache_var,
            font=("Arial", 10),
        ).pack(anchor="w", padx=5, pady=(0, 8))

        self.clear_cache_button = tk.Button(
            cache_frame,
            text="Cache löschen…",
            font=("Arial", 10, "bold"),
            command=self._on_clear_cache_clicked,
            bg="#9E9E9E",
            fg="white",
            width=18,
            cursor="hand2",
        )
        self.clear_cache_button.pack(anchor="w", padx=5, pady=(0, 4))

    def _on_clear_cache_clicked(self):
        if not self.app:
            messagebox.showerror(
                "Fehler",
                "Cache-Löschen ist nicht verfügbar (App-Referenz fehlt).",
                parent=self.dialog,
            )
            return
        if self._cache_clear_in_progress:
            return

        blocked, reason = self.app._is_session_reset_blocked()
        if blocked:
            messagebox.showwarning("Cache löschen nicht möglich", reason, parent=self.dialog)
            return

        warning = WarningDialog(
            self.dialog,
            title="Cache löschen bestätigen",
            message=(
                "Alle importierten Videos und Fotos sowie temporäre Vorschau-Dateien "
                "werden gelöscht.\n\n"
                "Formular-Eingaben und gespeicherte Einstellungen bleiben unverändert.\n\n"
                "Fortfahren?"
            ),
            confirm_text="Cache löschen",
            cancel_text="Abbrechen",
        )
        if not warning.result:
            return

        blocked, reason = self.app._is_session_reset_blocked()
        if blocked:
            messagebox.showwarning("Cache löschen nicht möglich", reason, parent=self.dialog)
            return

        self._cache_clear_in_progress = True
        self.clear_cache_button.config(state=tk.DISABLED)
        include_hw = self.clear_hw_cache_var.get()

        def run_cleanup():
            try:
                result = self.app.clear_application_cache(include_hw_cache=include_hw)
            except Exception as exc:
                self.dialog.after(
                    0,
                    lambda: self._on_cache_clear_finished(None, str(exc)),
                )
                return
            self.dialog.after(
                0,
                lambda: self._on_cache_clear_finished(result, None),
            )

        threading.Thread(target=run_cleanup, daemon=True).start()

    def _on_cache_clear_finished(self, result, error_message):
        self._cache_clear_in_progress = False
        self.clear_cache_button.config(state=tk.NORMAL)
        if error_message:
            messagebox.showerror(
                "Fehler",
                f"Cache konnte nicht vollständig gelöscht werden:\n{error_message}",
                parent=self.dialog,
            )
            return
        if result is None:
            return

        message = result.summary_message()
        if result.errors:
            detail = "\n".join(result.errors[:5])
            if len(result.errors) > 5:
                detail += f"\n… und {len(result.errors) - 5} weitere"
            message += f"\n\nDetails:\n{detail}"
            messagebox.showwarning("Cache teilweise gelöscht", message, parent=self.dialog)
        else:
            messagebox.showinfo("Cache gelöscht", message, parent=self.dialog)

        if self.clear_hw_cache_var.get() and self.on_settings_saved:
            self.on_settings_saved()

    def _on_qr_scan_scope_changed(self):
        """Deaktiviert Video-Parallelisierung, wenn nur der erste Clip geprüft wird."""
        first_only = self.qr_video_scan_scope_var.get() == "first"
        parallel_state = tk.DISABLED if first_only else tk.NORMAL
        self.qr_parallel_checkbox.config(state=parallel_state)
        if first_only:
            self.qr_video_parallel_enabled_var.set(False)

    def create_extras_tab(self):
        """Erstellt den Tab 'Version'"""
        # --- Updates & Versionen ---
        version_frame = ttk.LabelFrame(self.tab_extras, text="Updates & Versionen", padding=(10, 10))
        version_frame.pack(fill="x", pady=(0, 10))
        version_frame.grid_columnconfigure(1, weight=1)

        # Variables for version switcher
        self.available_versions = []  # Will be filled when loading
        self.selected_version_data = None
        self.version_var = tk.StringVar()

        # Row 0: Update Button (top left) and empty space
        update_button = tk.Button(
            version_frame, text="Nach Updates suchen", font=("Arial", 10),
            command=self.check_for_updates, bg="#2196F3", fg="white", width=20, height=1
        )
        update_button.grid(row=0, column=0, sticky="w", pady=(5, 10), padx=5)

        # Row 1: Dropdown Label, Dropdown, and Apply Button in same row
        dropdown_label = tk.Label(version_frame, text="Verfügbare Versionen:", font=("Arial", 10))
        dropdown_label.grid(row=1, column=0, sticky="w", padx=(5, 10), pady=(5, 10))

        self.version_dropdown = ttk.Combobox(
            version_frame,
            textvariable=self.version_var,
            state="readonly",
            font=("Arial", 10),
            width=25,
            height=10  # Maximal 10 Einträge gleichzeitig sichtbar
        )
        self.version_dropdown.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(5, 10))
        self.version_dropdown.bind("<<ComboboxSelected>>", self.on_version_selected)

        self.apply_version_button = tk.Button(
            version_frame,
            text="Version übernehmen",
            font=("Arial", 10, "bold"),
            command=self.on_apply_version,
            bg="#FF9800",
            fg="white",
            width=18,
            height=1,
            state="disabled"
        )
        self.apply_version_button.grid(row=1, column=2, sticky="e", padx=5, pady=(5, 10))

        # Row 2: Release-Info (Tab-Scroll übernimmt vertikales Scrollen)
        info_panel_container = tk.Frame(version_frame, relief=tk.SUNKEN, borderwidth=1, bg="white")
        info_panel_container.grid(row=2, column=0, columnspan=3, sticky="ew", padx=5, pady=(0, 10))

        self.version_info_label = tk.Label(
            info_panel_container,
            text="Wählen Sie eine Version aus der Liste",
            font=("Arial", 10, "bold"),
            bg="white",
            anchor="w",
            justify="left"
        )
        self.version_info_label.pack(fill="x", padx=10, pady=(10, 5))

        self.release_date_label = tk.Label(
            info_panel_container,
            text="",
            font=("Arial", 9),
            bg="white",
            anchor="w",
            fg="#666666"
        )
        self.release_date_label.pack(fill="x", padx=10, pady=(0, 10))

        notes_label = tk.Label(
            info_panel_container,
            text="Release Notes:",
            font=("Arial", 9, "bold"),
            bg="white",
            anchor="w"
        )
        notes_label.pack(fill="x", padx=10, pady=(0, 5))

        self.patch_notes_container = tk.Frame(info_panel_container, bg="white")
        self.patch_notes_container.pack(fill="x", padx=0, pady=(0, 10))

        # Status/Error label for loading failures (initially shown)
        self.version_status_label = tk.Label(
            version_frame,
            text="Lade verfügbare Versionen...",
            font=("Arial", 9),
            fg="#666666"
        )
        self.version_status_label.grid(row=3, column=0, columnspan=3, pady=(0, 5), padx=5)

        # Store reference to status label grid info
        self.version_status_label_shown = True

        # Load available versions in background
        self.load_available_versions()

        # --- PayPal Button (outside the group, below) ---
        try:
            self.paypal_img = tk.PhotoImage(file=PAYPAL_LOGO_PATH, width=30)
            paypal_button = tk.Button(
                self.tab_extras, text="Entwicklung unterstützen", image=self.paypal_img, compound="left",
                font=("Arial", 9), command=self.open_paypal_donation, bg="#f8f9fa",
                fg="#0070ba", relief="flat", cursor="hand2", height=30
            )
        except tk.TclError:
            paypal_button = tk.Button(
                self.tab_extras, text="Entwicklung unterstützen (PayPal)",
                font=("Arial", 9), command=self.open_paypal_donation, bg="#f8f9fa",
                fg="#0070ba", relief="flat", cursor="hand2", height=1
            )
        paypal_button.pack(pady=(5, 5))

        # --- Autor (outside the group, at bottom) ---
        author_text = f"Aero Tandem Studio v{self.APP_VERSION}\nby Andreas Kowalenko"
        author_label = tk.Label(self.tab_extras, text=author_text, font=("Arial", 9), fg="gray", justify="center")
        author_label.pack(pady=(5, 10))


    def check_for_updates(self):
        """Startet die Update-Prüfung"""
        try:
            # Verwende die gleiche Funktion wie beim App-Start, aber mit Benachrichtigung
            # force_check=True zeigt auch ignorierte Versionen an
            from src.installer.updater import initialize_updater
            initialize_updater(self.dialog, self.APP_VERSION, show_no_update_message=True, force_check=True)
        except Exception as e:
            messagebox.showerror("Fehler", f"Update-Prüfung konnte nicht gestartet werden:\n{str(e)}",
                                 parent=self.dialog)

    def open_paypal_donation(self):
        """Öffnet die PayPal Donations-Seite"""
        try:
            # Ersetzen Sie diese URL mit Ihrer tatsächlichen PayPal Donations-URL
            paypal_url = "https://www.paypal.com/donate/?hosted_button_id=DUNVHWC5FBN3N"
            webbrowser.open_new(paypal_url)
        except Exception as e:
            messagebox.showerror("Fehler", f"PayPal Seite konnte nicht geöffnet werden:\n{str(e)}", parent=self.dialog)

    def load_available_versions(self):
        """Lädt verfügbare Versionen von GitHub im Hintergrund"""
        import threading
        from src.utils.constants import MIN_SWITCHABLE_VERSION

        def fetch_versions():
            from src.installer.updater import get_all_releases
            releases = get_all_releases(min_version=MIN_SWITCHABLE_VERSION)

            # Update UI in main thread
            self.dialog.after(0, lambda: self._populate_version_dropdown(releases))

        # Start in background thread
        thread = threading.Thread(target=fetch_versions, daemon=True)
        thread.start()

    def _populate_version_dropdown(self, releases):
        """Füllt Dropdown mit verfügbaren Versionen (wird im Main Thread aufgerufen)"""
        if releases is None:
            # Error loading releases
            self.version_status_label.config(
                text="Fehler beim Laden der Versionen. Bitte Internetverbindung prüfen.",
                fg="red"
            )
            if not self.version_status_label_shown:
                self.version_status_label.grid(row=3, column=0, columnspan=3, pady=(0, 5), padx=5)
                self.version_status_label_shown = True
            self.version_dropdown.config(state="disabled")
            return

        if not releases:
            self.version_status_label.config(
                text="Keine Versionen verfügbar.",
                fg="#666666"
            )
            if not self.version_status_label_shown:
                self.version_status_label.grid(row=3, column=0, columnspan=3, pady=(0, 5), padx=5)
                self.version_status_label_shown = True
            self.version_dropdown.config(state="disabled")
            return

        # Store releases data
        self.available_versions = releases

        # Build dropdown values (mark current version)
        dropdown_values = []
        for release in releases:
            version_text = release['tag_name']
            if version_text == self.APP_VERSION:
                version_text += " (Installiert)"
            dropdown_values.append(version_text)

        self.version_dropdown['values'] = dropdown_values

        # Hide status label when successful
        if self.version_status_label_shown:
            self.version_status_label.grid_forget()
            self.version_status_label_shown = False

        # Select current version by default if available
        for idx, release in enumerate(releases):
            if release['tag_name'] == self.APP_VERSION:
                self.version_dropdown.current(idx)
                self.on_version_selected(None)
                break

    def on_version_selected(self, event):
        """Event handler wenn eine Version im Dropdown ausgewählt wird"""
        selected_index = self.version_dropdown.current()
        if selected_index < 0 or selected_index >= len(self.available_versions):
            return

        # Get selected version data
        version_data = self.available_versions[selected_index]
        self.selected_version_data = version_data

        # Update info labels
        version_tag = version_data['tag_name']
        is_current = (version_tag == self.APP_VERSION)

        self.version_info_label.config(text=f"Version: {version_tag}")

        # Format and display release date
        try:
            from datetime import datetime
            date_str = version_data['published_at']
            # Parse ISO format: "2024-01-15T10:30:00Z"
            dt = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            formatted_date = dt.strftime("%d.%m.%Y")
            self.release_date_label.config(text=f"Veröffentlicht: {formatted_date}")
        except:
            self.release_date_label.config(text="Veröffentlicht: Unbekannt")

        # Update patch notes by clearing and re-rendering content
        # Clear all existing widgets in the container
        for widget in self.patch_notes_container.winfo_children():
            widget.destroy()

        from src.installer.updater import render_markdown_to_frame
        patch_notes = version_data['body']
        if patch_notes:
            render_markdown_to_frame(self.patch_notes_container, patch_notes)
        else:
            # Show "no notes available" message
            no_notes_label = tk.Label(
                self.patch_notes_container,
                text="Keine Release Notes verfügbar.",
                font=("Arial", 9),
                bg="white",
                fg="#666666",
                anchor="w"
            )
            no_notes_label.pack(fill="x", padx=10, pady=5)

        # Update Tab-Scroll nach dynamischem Patch-Notes-Inhalt
        self.patch_notes_container.update_idletasks()
        if hasattr(self.tab_extras, "_scroll_refresh"):
            self.tab_extras._scroll_refresh()
        self._attach_tab_mousewheel(self.tab_extras)

        # Enable/disable apply button (disable if current version is selected)
        if is_current:
            self.apply_version_button.config(state="disabled")
        else:
            self.apply_version_button.config(state="normal")

    def on_apply_version(self):
        """Event handler wenn 'Version übernehmen' geklickt wird"""
        if not self.selected_version_data:
            return

        version_tag = self.selected_version_data['tag_name']
        installer_url = self.selected_version_data['installer_url']

        # Show warning dialog
        from src.gui.components.warning_dialog import WarningDialog

        warning_message = (
            f"Möchten Sie wirklich zu Version {version_tag} wechseln?\n\n"
            "Die Anwendung wird neu gestartet, um die Installation durchzuführen.\n"
            "Bitte stellen Sie sicher, dass alle Arbeiten gespeichert sind."
        )

        dialog = WarningDialog(
            self.dialog,
            title="Versions-Wechsel bestätigen",
            message=warning_message,
            confirm_text="Jetzt wechseln",
            cancel_text="Abbrechen"
        )

        if dialog.result:
            # User confirmed - start installation
            from src.installer.updater import install_specific_version

            # Close settings dialog first
            self.dialog.destroy()

            # Start installation (will restart app)
            install_specific_version(self.parent, installer_url)

    def waehle_speicherort(self):
        """Öffnet Dialog zur Auswahl des Speicherorts."""
        directory = filedialog.askdirectory(parent=self.dialog, title="Standard-Speicherort wählen")
        if directory:
            self.speicherort_var.set(directory)

    def waehle_backup_ordner(self):
        """Öffnet Dialog zur Auswahl des Backup-Ordners."""
        directory = filedialog.askdirectory(parent=self.dialog, title="SD-Karten Backup-Ordner wählen")
        if directory:
            self.sd_backup_folder_var.set(directory)

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        settings = self.config.get_settings()
        self.server_var.set(settings.get("server_url", "smb://169.254.169.254/aktuell"))
        self.login_var.set(settings.get("server_login", ""))
        self.password_var.set(settings.get("server_password", ""))

        # Allgemein
        self.speicherort_var.set(settings.get("speicherort", ""))
        self.dauer_var.set(str(settings.get("dauer", 5)))

        # SD-Karten Backup
        self.sd_backup_folder_var.set(settings.get("sd_backup_folder", ""))
        self.sd_auto_backup_var.set(settings.get("sd_auto_backup", False))
        self.sd_clear_var.set(settings.get("sd_clear_after_backup", False))
        self.sd_auto_import_var.set(settings.get("sd_auto_import", False))
        self.sd_skip_processed_var.set(settings.get("sd_skip_processed", False))  # NEU
        self.sd_skip_processed_manual_var.set(settings.get("sd_skip_processed_manual", False))  # NEU
        self.sd_size_limit_enabled_var.set(settings.get("sd_size_limit_enabled", False))  # NEU
        self.sd_size_limit_mb_var.set(str(settings.get("sd_size_limit_mb", 2000)))  # NEU

        pc_name = settings.get("sd_pc_name", "")
        if not pc_name:
            try:
                pc_name = os.environ.get("COMPUTERNAME") or socket.gethostname() or ""
            except Exception:
                pc_name = ""
        self.sd_pc_name_var.set(pc_name)

        # Hardware-Beschleunigung
        self.hardware_acceleration_var.set(settings.get("hardware_acceleration_enabled", True))

        # Paralleles Processing
        self.parallel_processing_var.set(settings.get("parallel_processing_enabled", True))

        # Codec-Auswahl
        self.codec_var.set(settings.get("video_codec", "auto"))
        self.encoding_strategy_var.set(settings.get("encoding_strategy", "per_clip"))
        self.reencode_matching_clips_var.set(settings.get("reencode_matching_clips", False))
        self._update_encoding_strategy_state()

        # Formular beim Session-Zurücksetzen
        self.keep_tandemmaster_on_session_reset_var.set(
            settings.get("keep_tandemmaster_on_session_reset", False))
        self.keep_videospringer_on_session_reset_var.set(
            settings.get("keep_videospringer_on_session_reset", False))
        self.oldschool_mode_var.set(bool(settings.get("oldschool_mode", False)))

        scan_all_clips = settings.get("qr_video_scan_all_clips", True)
        self.qr_video_scan_scope_var.set("all" if scan_all_clips else "first")
        self.qr_video_scan_seconds_var.set(str(settings.get("qr_video_scan_seconds", 5)))
        self.qr_video_frame_step_var.set(str(settings.get("qr_video_frame_step", 10)))
        self.qr_video_parallel_enabled_var.set(settings.get("qr_video_parallel_enabled", False))
        self.qr_video_parallel_workers_var.set(str(settings.get("qr_video_parallel_workers", 2)))
        self.qr_photo_parallel_enabled_var.set(settings.get("qr_photo_parallel_enabled", False))
        self.import_photo_parallel_enabled_var.set(
            settings.get("import_photo_parallel_enabled", True)
        )
        self._on_qr_scan_scope_changed()

        # Trigger checkbox visibility based on auto_backup setting
        self.on_auto_backup_toggle()

        # Trigger hardware info update
        self.on_hw_accel_toggle()

        # Trigger parallel processing info update
        self.on_parallel_processing_toggle()

    def save_settings(self):
        """Speichert die Einstellungen"""
        server_url = self.server_var.get().strip()
        server_login = self.login_var.get().strip()
        server_password = self.password_var.get()

        # Allgemein
        speicherort = self.speicherort_var.get()
        dauer = self.dauer_var.get()

        # SD-Karten Backup
        sd_backup_folder = self.sd_backup_folder_var.get()
        sd_auto_backup = self.sd_auto_backup_var.get()
        sd_clear = self.sd_clear_var.get()
        sd_auto_import = self.sd_auto_import_var.get()
        sd_skip_processed = self.sd_skip_processed_var.get()  # NEU
        sd_skip_processed_manual = self.sd_skip_processed_manual_var.get()  # NEU
        sd_size_limit_enabled = self.sd_size_limit_enabled_var.get()  # NEU

        # Validiere Größen-Limit
        sd_size_limit_mb = 2000  # Default
        if sd_size_limit_enabled:
            try:
                sd_size_limit_mb = int(self.sd_size_limit_mb_var.get())
                if sd_size_limit_mb <= 0:
                    raise ValueError("Wert muss größer als 0 sein")
            except ValueError:
                messagebox.showwarning("Ungültige Eingabe",
                                      "Bitte geben Sie eine gültige Zahl für das Größen-Limit ein (z.B. 2000).",
                                      parent=self.dialog)
                return

        # Hardware-Beschleunigung
        hardware_acceleration_enabled = self.hardware_acceleration_var.get()

        # Paralleles Processing
        parallel_processing_enabled = self.parallel_processing_var.get()

        # Codec-Auswahl
        video_codec = self.codec_var.get()
        encoding_strategy = self.encoding_strategy_var.get()
        if encoding_strategy not in ("per_clip", "combined"):
            encoding_strategy = "per_clip"
        reencode_matching_clips = self.reencode_matching_clips_var.get()

        keep_tandemmaster_on_session_reset = self.keep_tandemmaster_on_session_reset_var.get()
        keep_videospringer_on_session_reset = self.keep_videospringer_on_session_reset_var.get()
        oldschool_mode = bool(self.oldschool_mode_var.get())

        try:
            qr_video_scan_seconds = float(self.qr_video_scan_seconds_var.get().strip())
            if qr_video_scan_seconds < 0.5:
                raise ValueError("zu kurz")
        except ValueError:
            messagebox.showwarning(
                "Ungültige Eingabe",
                "Bitte eine gültige Scan-Dauer in Sekunden angeben (mindestens 0,5).",
                parent=self.dialog,
            )
            return

        try:
            qr_video_frame_step = int(self.qr_video_frame_step_var.get().strip())
            if qr_video_frame_step < 1:
                raise ValueError("zu klein")
        except ValueError:
            messagebox.showwarning(
                "Ungültige Eingabe",
                "Bitte einen gültigen Frame-Abstand angeben (ganze Zahl ≥ 1).",
                parent=self.dialog,
            )
            return

        qr_video_parallel_enabled = self.qr_video_parallel_enabled_var.get()
        qr_photo_parallel_enabled = self.qr_photo_parallel_enabled_var.get()
        import_photo_parallel_enabled = self.import_photo_parallel_enabled_var.get()
        try:
            qr_video_parallel_workers = int(self.qr_video_parallel_workers_var.get().strip())
            if qr_video_parallel_workers < 1 or qr_video_parallel_workers > 4:
                raise ValueError("außerhalb Bereich")
        except ValueError:
            messagebox.showwarning(
                "Ungültige Eingabe",
                "Parallele Worker: ganze Zahl zwischen 1 und 4.",
                parent=self.dialog,
            )
            return

        if not server_url:
            messagebox.showwarning("Fehler", "Bitte geben Sie eine Server-Adresse ein.", parent=self.dialog)
            return

        if not speicherort:
            messagebox.showwarning("Fehler", "Bitte geben Sie einen Standard-Speicherort an.", parent=self.dialog)
            return

        # Prüfe SD-Backup Einstellungen wenn aktiviert
        if sd_auto_backup and not sd_backup_folder:
            messagebox.showwarning("Fehler", "Bitte geben Sie einen Backup-Ordner an.", parent=self.dialog)
            return

        try:
            # Aktuelle Einstellungen laden
            current_settings = self.config.get_settings()

            # Server-Daten aktualisieren
            current_settings["server_url"] = server_url
            current_settings["server_login"] = server_login
            current_settings["server_password"] = server_password

            # App-Einstellungen aktualisieren
            current_settings["speicherort"] = speicherort
            current_settings["dauer"] = int(dauer)

            # SD-Karten Backup Einstellungen
            current_settings["sd_backup_folder"] = sd_backup_folder
            current_settings["sd_auto_backup"] = sd_auto_backup
            current_settings["sd_clear_after_backup"] = sd_clear
            current_settings["sd_auto_import"] = sd_auto_import
            current_settings["sd_skip_processed"] = sd_skip_processed  # NEU
            current_settings["sd_skip_processed_manual"] = sd_skip_processed_manual  # NEU
            current_settings["sd_size_limit_enabled"] = sd_size_limit_enabled  # NEU
            current_settings["sd_size_limit_mb"] = sd_size_limit_mb  # NEU
            current_settings["sd_pc_name"] = self.sd_pc_name_var.get().strip()

            # Hardware-Beschleunigung
            current_settings["hardware_acceleration_enabled"] = hardware_acceleration_enabled

            # Paralleles Processing
            current_settings["parallel_processing_enabled"] = parallel_processing_enabled

            # Codec-Auswahl
            current_settings["video_codec"] = video_codec
            current_settings["encoding_strategy"] = encoding_strategy
            current_settings["reencode_matching_clips"] = reencode_matching_clips

            # Formular beim Session-Zurücksetzen
            current_settings["keep_tandemmaster_on_session_reset"] = keep_tandemmaster_on_session_reset
            current_settings["keep_videospringer_on_session_reset"] = keep_videospringer_on_session_reset
            current_settings["oldschool_mode"] = oldschool_mode

            current_settings["qr_video_scan_all_clips"] = (
                self.qr_video_scan_scope_var.get() == "all"
            )
            current_settings["qr_video_scan_seconds"] = qr_video_scan_seconds
            current_settings["qr_video_frame_step"] = qr_video_frame_step
            current_settings["qr_video_parallel_enabled"] = qr_video_parallel_enabled
            current_settings["qr_video_parallel_workers"] = qr_video_parallel_workers
            current_settings["qr_photo_parallel_enabled"] = qr_photo_parallel_enabled
            current_settings["import_photo_parallel_enabled"] = import_photo_parallel_enabled

            # Speichern
            self.config.save_settings(current_settings)

            messagebox.showinfo("Erfolg", "Einstellungen wurden gespeichert.", parent=self.dialog)

            # Callback aufrufen bevor Dialog geschlossen wird
            if self.on_settings_saved:
                self.on_settings_saved()

            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("Fehler", f"Einstellungen konnten nicht gespeichert werden:\n{str(e)}",
                                 parent=self.dialog)
