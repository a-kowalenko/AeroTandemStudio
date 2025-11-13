import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import webbrowser

from src.utils.constants import APP_VERSION, PAYPAL_LOGO_PATH
from src.gui.components.circular_spinner import CircularSpinner


class SettingsDialog:
    """Einstellungs-Dialog für Server- und App-Konfiguration"""

    def __init__(self, parent, config, on_settings_saved=None):
        self.parent = parent
        self.config = config
        self.dialog = None
        self.APP_VERSION = APP_VERSION
        self.on_settings_saved = on_settings_saved  # Callback für nach dem Speichern

    def show(self):
        """Zeigt den Einstellungs-Dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Einstellungen")
        self.dialog.geometry("750x680")  # Höhe erhöht
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
        # Variable für Hardware-Beschleunigung
        self.hardware_acceleration_var = tk.BooleanVar()
        # Variable für Paralleles Processing
        self.parallel_processing_var = tk.BooleanVar()
        # Variable für Codec-Auswahl
        self.codec_var = tk.StringVar(value="auto")

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
        w, h = 750, 680

        x = parent_x + (parent_width - w) // 2
        y = parent_y + (parent_height - h) // 2

        # Verhindere negative Koordinaten
        x = max(0, x)
        y = max(0, y)

        self.dialog.geometry(f"{w}x{h}+{x}+{y}")

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
        self.tab_allgemein = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_allgemein, text="Allgemein")
        self.create_allgemein_tab()

        # --- Tab 2: Encoding ---
        self.tab_encoding = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_encoding, text="Encoding")
        self.create_encoding_tab()

        # --- Tab 3: Server ---
        self.tab_server = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_server, text="Server")
        self.create_server_tab()

        # --- Tab 4: Extras ---
        self.tab_extras = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_extras, text="Extras")
        self.create_extras_tab()

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

        # --- Sektion 2: SD-Karten Backup ---
        backup_frame = ttk.LabelFrame(self.tab_allgemein, text="SD-Karten Backup", padding=(10, 10))
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
        row_idx = 7
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

    def on_codec_changed(self):
        """Wird aufgerufen wenn ein anderer Codec ausgewählt wird"""
        selected_codec = self.codec_var.get()
        print(f"Codec geändert zu: {selected_codec}")

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
            # Zeige abhängige Checkboxen in neuer Reihenfolge (alle eingerückt mit padx=30)
            # 1. Automatisch importieren (ERSTE Option)
            self.sd_auto_import_checkbox.grid(row=2, column=0, sticky="w", padx=30, pady=2)

            # 2. Größen-Limit Option
            self.sd_size_limit_checkbox.grid(row=3, column=0, sticky="w", padx=30, pady=(8, 2))
            self.on_size_limit_toggle()  # Zeige/Verstecke Eingabefeld

            # 3. SD-Karte leeren
            self.sd_clear_checkbox.grid(row=5, column=0, sticky="w", padx=30, pady=2)
        else:
            # Verstecke und deaktiviere alle abhängigen Checkboxen
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
        self.sd_skip_checkbox.grid(row=7, column=0, sticky="w", padx=5, pady=(8, 2))
        self.history_button.grid(row=7, column=1, sticky="e", padx=5, pady=(8, 2))

        # Sub-Option für manuellen Import (conditional)
        self.on_skip_processed_toggle()

    def on_skip_processed_toggle(self):
        """Wird aufgerufen wenn die Skip-Processed Checkbox geändert wird"""
        is_enabled = self.sd_skip_processed_var.get()

        if is_enabled:
            # Zeige Sub-Option für manuellen Import (eingerückt)
            self.sd_skip_manual_checkbox.grid(row=8, column=0, sticky="w", padx=30, pady=(0, 2))
        else:
            # Verstecke Sub-Option
            self.sd_skip_manual_checkbox.grid_forget()
            self.sd_skip_processed_manual_var.set(False)

    def on_size_limit_toggle(self):
        """Wird aufgerufen wenn die Größen-Limit Checkbox geändert wird"""
        is_enabled = self.sd_size_limit_enabled_var.get()

        if is_enabled:
            # Zeige Eingabefeld (noch mehr eingerückt als Checkbox)
            self.sd_size_limit_frame.grid(row=4, column=0, sticky="w", padx=50, pady=(0, 2))
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

    def create_server_tab(self):
        """Erstellt den Tab 'Server'"""
        # --- Server-Verbindung ---
        server_frame = ttk.LabelFrame(self.tab_server, text="Server-Verbindung", padding=(10, 10))
        server_frame.pack(fill="x", pady=(0, 10))
        server_frame.grid_columnconfigure(1, weight=1)

        # Server Adresse
        tk.Label(server_frame, text="Adresse:", font=("Arial", 11)).grid(
            row=0, column=0, sticky="w", padx=5, pady=5)
        self.server_entry = tk.Entry(server_frame, textvariable=self.server_var, font=("Arial", 11))
        self.server_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=5, pady=5)

        tk.Label(server_frame, text="Beispiel: smb://server/share oder \\\\server\\share oder C:\\lokaler\\pfad",
                font=("Arial", 9), fg="gray").grid(row=1, column=1, columnspan=3, sticky="w", padx=5)

        # Login / Passwort
        tk.Label(server_frame, text="Login:", font=("Arial", 11)).grid(
            row=2, column=0, sticky="w", padx=5, pady=(10, 5))
        self.login_entry = tk.Entry(server_frame, textvariable=self.login_var, font=("Arial", 11), width=20)
        self.login_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=(10, 5))

        tk.Label(server_frame, text="Passwort:", font=("Arial", 11)).grid(
            row=2, column=2, sticky="w", padx=(10, 5), pady=(10, 5))
        self.password_entry = tk.Entry(server_frame, textvariable=self.password_var,
                                       font=("Arial", 11), width=20, show="*")
        self.password_entry.grid(row=2, column=3, sticky="ew", padx=5, pady=(10, 5))

    def create_extras_tab(self):
        """Erstellt den Tab 'Extras'"""
        # --- Info & Updates ---
        info_frame = ttk.LabelFrame(self.tab_extras, text="Info & Updates", padding=(10, 10))
        info_frame.pack(fill="x", pady=(0, 10))
        info_frame.grid_columnconfigure(0, weight=1)
        info_frame.grid_columnconfigure(1, weight=1)

        # Update Button
        update_button = tk.Button(
            info_frame, text="Nach Updates suchen", font=("Arial", 10),
            command=self.check_for_updates, bg="#2196F3", fg="white", width=20, height=1
        )
        update_button.grid(row=0, column=0, columnspan=2, pady=5, padx=5)

        # PayPal Button
        try:
            self.paypal_img = tk.PhotoImage(file=PAYPAL_LOGO_PATH, width=30)
            paypal_button = tk.Button(
                info_frame, text="Entwicklung unterstützen", image=self.paypal_img, compound="left",
                font=("Arial", 9), command=self.open_paypal_donation, bg="#f8f9fa",
                fg="#0070ba", relief="flat", cursor="hand2", height=30
            )
        except tk.TclError:
            paypal_button = tk.Button(
                info_frame, text="Entwicklung unterstützen (PayPal)",
                font=("Arial", 9), command=self.open_paypal_donation, bg="#f8f9fa",
                fg="#0070ba", relief="flat", cursor="hand2", height=1
            )
        paypal_button.grid(row=1, column=0, columnspan=2, pady=2, padx=5)

        # Autor
        author_text = f"Aero Tandem Studio v{self.APP_VERSION}\nby Andreas Kowalenko"
        author_label = tk.Label(info_frame, text=author_text, font=("Arial", 9), fg="gray", justify="center")
        author_label.grid(row=2, column=0, columnspan=2, pady=(10, 0), padx=5)


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
        self.dauer_var.set(str(settings.get("dauer", 8)))

        # SD-Karten Backup
        self.sd_backup_folder_var.set(settings.get("sd_backup_folder", ""))
        self.sd_auto_backup_var.set(settings.get("sd_auto_backup", False))
        self.sd_clear_var.set(settings.get("sd_clear_after_backup", False))
        self.sd_auto_import_var.set(settings.get("sd_auto_import", False))
        self.sd_skip_processed_var.set(settings.get("sd_skip_processed", False))  # NEU
        self.sd_skip_processed_manual_var.set(settings.get("sd_skip_processed_manual", False))  # NEU
        self.sd_size_limit_enabled_var.set(settings.get("sd_size_limit_enabled", False))  # NEU
        self.sd_size_limit_mb_var.set(str(settings.get("sd_size_limit_mb", 2000)))  # NEU

        # Hardware-Beschleunigung
        self.hardware_acceleration_var.set(settings.get("hardware_acceleration_enabled", True))

        # Paralleles Processing
        self.parallel_processing_var.set(settings.get("parallel_processing_enabled", True))

        # Codec-Auswahl
        self.codec_var.set(settings.get("video_codec", "auto"))

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

            # Hardware-Beschleunigung
            current_settings["hardware_acceleration_enabled"] = hardware_acceleration_enabled

            # Paralleles Processing
            current_settings["parallel_processing_enabled"] = parallel_processing_enabled

            # Codec-Auswahl
            current_settings["video_codec"] = video_codec

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
