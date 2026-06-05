import tkinter as tk
from tkcalendar import DateEntry
from datetime import date

from .circular_spinner import CircularSpinner

_MODE_BTN_BORDER = "#000000"
_MODE_BTN_SELECTED_BG = "#007ACC"
_MODE_BTN_SELECTED_FG = "#FFFFFF"
_MODE_BTN_SELECTED_ACTIVE_BG = "#0066B3"
_MODE_BTN_IDLE_BG = "#FFFFFF"
_MODE_BTN_IDLE_FG = "#1F2937"
_MODE_BTN_IDLE_ACTIVE_BG = "#E8F4FF"
_MODE_BTN_MUTED_FG = "#6B7280"
_MODE_BTN_MUTED_ACTIVE_BG = "#F3F4F6"


class FormFields:
    def __init__(self, parent, config, app_instance):
        self.parent = parent
        self.config = config
        self.app = app_instance  # Referenz zur Haupt-App
        self.frame = tk.Frame(parent)
        self.frame.grid_columnconfigure(1, weight=1)  # Spalte 1 dehnbar machen
        self.frame.grid_columnconfigure(3, weight=1)  # Spalte 3 dehnbar machen

        # --- Variablen für ALLE Formular-Typen ---
        self.ort_var = tk.StringVar(value="Calden")
        self.gast_name_var = tk.StringVar()
        self.tandemmaster_var = tk.StringVar()
        self.videospringer_var = tk.StringVar()

        # Variable für den Videomodus (Handcam vs. Outside)
        self.video_mode_var = tk.StringVar(value="")

        # Variablen für Kunde/Manuell-Form
        self.kunde_id_var = tk.StringVar()
        self.booking_id_var = tk.StringVar()
        self.vorname_var = tk.StringVar()  # NEU
        self.nachname_var = tk.StringVar()  # NEU
        self.email_var = tk.StringVar()
        self.telefon_var = tk.StringVar()

        # Produkt-Checkboxen
        self.handcam_foto_var = tk.BooleanVar()
        self.handcam_video_var = tk.BooleanVar()
        self.outside_foto_var = tk.BooleanVar()
        self.outside_video_var = tk.BooleanVar()

        # "Bezahlt"-Checkboxen
        self.handcam_foto_bezahlt_var = tk.BooleanVar()
        self.handcam_video_bezahlt_var = tk.BooleanVar()
        self.outside_foto_bezahlt_var = tk.BooleanVar()
        self.outside_video_bezahlt_var = tk.BooleanVar()

        # NEU: Callbacks hinzufügen, um Bezahlt-Checkboxen automatisch abzuwählen
        self.handcam_foto_var.trace_add('write', lambda *args: self._on_product_changed('handcam_foto'))
        self.handcam_video_var.trace_add('write', lambda *args: self._on_product_changed('handcam_video'))
        self.outside_foto_var.trace_add('write', lambda *args: self._on_product_changed('outside_foto'))
        self.outside_video_var.trace_add('write', lambda *args: self._on_product_changed('outside_video'))

        # NEU: Callbacks für Bezahlt-Checkboxen, um Wasserzeichen-Spalte zu aktualisieren
        # und um automatisch die entsprechende Produkt-Checkbox zu aktivieren
        self.handcam_foto_bezahlt_var.trace_add('write', lambda *args: self._on_payment_status_changed('handcam_foto'))
        self.handcam_video_bezahlt_var.trace_add('write', lambda *args: self._on_payment_status_changed('handcam_video'))
        self.outside_foto_bezahlt_var.trace_add('write', lambda *args: self._on_payment_status_changed('outside_foto'))
        self.outside_video_bezahlt_var.trace_add('write', lambda *args: self._on_payment_status_changed('outside_video'))

        # --- Widget-Platzhalter ---
        self.entry_kunde_id = None
        self.entry_booking_id = None
        self.entry_vorname = None  # NEU
        self.entry_nachname = None  # NEU
        self.entry_email = None
        self.entry_telefon = None
        self.is_valid = True

        self.entry_gast_name = None
        self.entry_tandemmaster = None
        self.entry_datum = None
        self.label_videospringer = None
        self.entry_videospringer = None

        # NEU: Platzhalter für Bearbeiten-Buttons
        self.btn_gast = None  # Bleibt (kontrolliert jetzt Vor- und Nachname)
        self.btn_video_mode = None
        self.btn_mode_handcam = None
        self.btn_mode_outside = None
        self._mode_toggle_rail = None

        # NEU: Liste für Video-Widgets (Toggle-Buttons, Checkboxen)
        self.video_widgets_list = []

        # Container-Frames für die umschaltbaren Sektionen
        self.handcam_frame = None
        self.outside_frame = None

        # Aktueller Formular-Modus
        self.form_mode = 'manual'  # Startet im manuellen Modus
        self._suspend_trace_callbacks = False
        self._last_layout_signature = None
        self._last_qr_success = False
        self._last_kunde = None
        self._layout_overlay = None
        self._layout_spinner = None

        # Lade Einstellungen und baue initiales Formular
        self.load_initial_settings()
        self.build_manual_form()
        self._last_layout_signature = self._build_layout_signature(False, None)

    def clear_form(self):
        """Entfernt alle Widgets aus dem Frame."""
        for widget in self.frame.winfo_children():
            if widget is self._layout_overlay:
                continue
            widget.destroy()
        # NEU: Widget-Liste leeren
        self.video_widgets_list = []

        # NEU: Referenzen auf zerstörte Widgets löschen, um Fehler zu vermeiden
        self.entry_kunde_id = None
        self.entry_booking_id = None
        self.entry_vorname = None
        self.entry_nachname = None
        self.entry_email = None
        self.entry_telefon = None

        self.entry_gast_name = None
        self.entry_tandemmaster = None
        self.entry_datum = None
        self.label_videospringer = None
        self.entry_videospringer = None
        self.btn_gast = None
        self.btn_video_mode = None
        self.btn_mode_handcam = None
        self.btn_mode_outside = None
        self._mode_toggle_rail = None
        self.handcam_frame = None
        self.outside_frame = None

    def has_qr_kunde_layout(self) -> bool:
        """True, wenn das Formular bereits durch einen erfolgreichen QR-Scan befüllt ist."""
        return self.form_mode == 'kunde'

    def _ensure_layout_overlay(self):
        """Erstellt ein Overlay mit Spinner über dem Formular (lazy, einmalig)."""
        if self._layout_overlay is not None:
            return

        try:
            bg = self.parent.cget("bg")
        except tk.TclError:
            bg = "#f0f0f0"

        self._layout_overlay = tk.Frame(self.frame, bg=bg)
        center = tk.Frame(self._layout_overlay, bg=bg)
        center.place(relx=0.5, rely=0.5, anchor="center")

        self._layout_spinner = CircularSpinner(center, size=48, line_width=4, color="#007ACC")
        self._layout_spinner.pack(pady=(0, 8))
        tk.Label(
            center,
            text="Formular wird aktualisiert…",
            font=("Arial", 10),
            bg=bg,
            fg="#555555",
        ).pack()

    def _show_layout_loading(self):
        """Blendet das Formular-Overlay ein, während Widgets neu aufgebaut werden."""
        self._ensure_layout_overlay()
        self._layout_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self._layout_overlay.lift()
        self.frame.update_idletasks()
        self._layout_spinner.start()

    def _hide_layout_loading(self):
        """Entfernt das Formular-Overlay nach dem Neuaufbau."""
        if self._layout_overlay is None:
            return
        self._layout_spinner.stop()
        self._layout_overlay.place_forget()

    def update_form_layout(self, qr_success, kunde=None):
        """
        Aktualisiert das Formular-Layout basierend auf dem QR-Scan-Ergebnis.
        """
        self._last_qr_success = bool(qr_success)
        self._last_kunde = kunde
        layout_signature = self._build_layout_signature(qr_success, kunde)
        if layout_signature == self._last_layout_signature:
            return

        self._show_layout_loading()
        self._suspend_trace_callbacks = True

        try:
            self.clear_form()

            if qr_success and kunde:
                self.form_mode = 'kunde'
                self.build_kunde_form(kunde)
            else:
                # Dies fängt qr_success=False ODER kunde=None ab
                self.form_mode = 'manual'
                self.build_manual_form()
        finally:
            self._suspend_trace_callbacks = False
            self._hide_layout_loading()

        self._last_layout_signature = layout_signature
        self._notify_watermark_visibility_update()

    def reload_current_layout(self):
        """Rendert das aktuelle Layout erneut (z. B. nach Settings-Änderung)."""
        self._last_layout_signature = None
        self.update_form_layout(self._last_qr_success, self._last_kunde)

    def _build_layout_signature(self, qr_success, kunde):
        """Erstellt eine Signatur zur Erkennung unveränderter Layout-Zustände."""
        oldschool_mode = bool(self.config.get_settings().get("oldschool_mode", False))
        if qr_success and kunde:
            return (
                "kunde",
                oldschool_mode,
                kunde.kunden_id_hash or "",
                kunde.booking_id_hash or "",
                kunde.vorname or "",
                kunde.nachname or "",
                bool(kunde.handcam_foto),
                bool(kunde.handcam_video),
                bool(kunde.outside_foto),
                bool(kunde.outside_video),
                bool(kunde.ist_bezahlt_handcam_foto),
                bool(kunde.ist_bezahlt_handcam_video),
                bool(kunde.ist_bezahlt_outside_foto),
                bool(kunde.ist_bezahlt_outside_video),
            )
        return ("manual", oldschool_mode)

    def _notify_watermark_visibility_update(self):
        # Nur aufrufen, wenn die App vollständig initialisiert ist
        if (self.app and
            hasattr(self.app, 'update_watermark_column_visibility') and
            hasattr(self.app, 'form_fields') and
            hasattr(self.app, 'drag_drop')):
            self.app.update_watermark_column_visibility()

    # --- Methoden zum Erstellen von Formular-Layouts ---

    def _kunde_media_aus_qr(self, kunde) -> bool:
        """True, wenn der QR-Code mindestens ein gebuchtes Produkt enthielt."""
        return bool(
            kunde.handcam_foto or kunde.handcam_video
            or kunde.outside_foto or kunde.outside_video
        )

    def build_kunde_form(self, kunde):
        """Baut das Formular für einen erkannten Kunden."""
        media_aus_qr = self._kunde_media_aus_qr(kunde)
        media_state = 'disabled' if media_aus_qr else 'normal'
        btn_video_text = 'Bearbeiten' if media_aus_qr else 'Übernehmen'

        row = 0
        row = self._create_id_fields(
            row=row,
            mode='kunde',
            kunden_id_val=(kunde.kunden_id_hash or ""),
            booking_id_val=(kunde.booking_id_hash or ""),
            kunden_id_label="Kunden ID Hash:",
            booking_id_label="Booking ID Hash:"
        )

        # Name (Vorname, Nachname) - gleiches Layout wie im manuellen Modus
        tk.Label(self.frame, text="Vorname:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")

        self.vorname_var.set(kunde.vorname)
        self.entry_vorname = tk.Entry(self.frame, textvariable=self.vorname_var, font=("Arial", 11),
                                      state='disabled', relief='flat', bg='#f0f0f0')
        self.entry_vorname.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

        tk.Label(self.frame, text="Nachname:", font=("Arial", 11)).grid(row=row, column=2, padx=(10, 5), pady=5,
                                                                        sticky="w")

        self.nachname_var.set(kunde.nachname)
        self.entry_nachname = tk.Entry(self.frame, textvariable=self.nachname_var, font=("Arial", 11),
                                       state='disabled', relief='flat', bg='#f0f0f0')
        self.entry_nachname.grid(row=row, column=3, padx=5, pady=5, sticky="ew")

        self.btn_gast = tk.Button(self.frame, text="Bearbeiten", command=self.toggle_edit_gast)
        self.btn_gast.grid(row=row, column=4, padx=5, pady=5)
        row += 1

        # QR-Modus: Oldschool vorübergehend deaktiviert — keine Email/Telefon-Felder
        self.email_var.set("")
        self.telefon_var.set("")

        # --- VERSCHOBENE Felder ---
        row = self._create_tandemmaster_field(row)
        row = self._create_datum_ort_fields(row)
        # --- ENDE VERSCHOBEN ---

        # --- Video Modus Toggle-Buttons ---
        self.video_widgets_list = []  # Zurücksetzen
        mode_frame = tk.Frame(self.frame)
        mode_frame.grid(row=row, column=0, columnspan=5, pady=5, sticky="w")

        self._create_mode_toggle_buttons(
            mode_frame,
            lockable=media_aus_qr,
            initial_state=media_state,
        )

        # Videospringer-Widgets
        self.label_videospringer = tk.Label(mode_frame, text="Videospringer:", font=("Arial", 11))
        self.entry_videospringer = tk.Entry(mode_frame, font=("Arial", 11),
                                            textvariable=self.videospringer_var)
        self.videospringer_var.set(self.config.get_settings().get("videospringer", ""))

        if media_aus_qr:
            self.btn_video_mode = tk.Button(mode_frame, text=btn_video_text, command=self.toggle_edit_video_mode)
            self.btn_video_mode.pack(side="left", padx=(20, 5))
        else:
            self.btn_video_mode = None

        row += 1

        # --- Handcam Frame (Checkbuttons state='disabled') ---
        self.handcam_frame = tk.Frame(self.frame)
        self.handcam_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Handcam Foto
        self.handcam_foto_var.set(kunde.handcam_foto)
        chk_hf = tk.Checkbutton(self.handcam_frame, text="Handcam Foto", variable=self.handcam_foto_var,
                                font=("Arial", 11), state=media_state)
        chk_hf.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hf)

        self.handcam_foto_bezahlt_var.set(kunde.ist_bezahlt_handcam_foto)
        chk_hfb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_foto_bezahlt_var,
                                 font=("Arial", 11), state=media_state)
        chk_hfb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hfb)

        # Handcam Video
        self.handcam_video_var.set(kunde.handcam_video)
        chk_hv = tk.Checkbutton(self.handcam_frame, text="Handcam Video", variable=self.handcam_video_var,
                                font=("Arial", 11), state=media_state)
        chk_hv.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hv)

        self.handcam_video_bezahlt_var.set(kunde.ist_bezahlt_handcam_video)
        chk_hvb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_video_bezahlt_var,
                                 font=("Arial", 11), state=media_state)
        chk_hvb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hvb)

        # --- Outside Frame (Checkbuttons state='disabled') ---
        self.outside_frame = tk.Frame(self.frame)
        self.outside_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Outside Foto
        self.outside_foto_var.set(kunde.outside_foto)
        chk_of = tk.Checkbutton(self.outside_frame, text="Outside Foto", variable=self.outside_foto_var,
                                font=("Arial", 11), state=media_state)
        chk_of.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_of)

        self.outside_foto_bezahlt_var.set(kunde.ist_bezahlt_outside_foto)
        chk_ofb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_foto_bezahlt_var,
                                 font=("Arial", 11), state=media_state)
        chk_ofb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ofb)

        # Outside Video
        self.outside_video_var.set(kunde.outside_video)
        chk_ov = tk.Checkbutton(self.outside_frame, text="Outside Video", variable=self.outside_video_var,
                                font=("Arial", 11), state=media_state)
        chk_ov.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ov)

        self.outside_video_bezahlt_var.set(kunde.ist_bezahlt_outside_video)
        chk_ovb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_video_bezahlt_var,
                                 font=("Arial", 11), state=media_state)
        chk_ovb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ovb)

        # Setze initialen Status für Video Modus
        if media_aus_qr:
            if kunde.outside_foto or kunde.outside_video:
                self.video_mode_var.set("outside")
            elif kunde.handcam_foto or kunde.handcam_video:
                self.video_mode_var.set("handcam")
            else:
                self.video_mode_var.set("handcam")
        else:
            self.video_mode_var.set("")

        row += 1  # Wichtig: Zeile für die Frames erhöhen
        self._update_mode_button_styles()
        self.toggle_video_mode_visibility()

        if media_aus_qr and hasattr(self.app, "drag_drop") and self.app.drag_drop:
            self.auto_check_products(
                self.app.drag_drop.has_videos(),
                self.app.drag_drop.has_photos(),
            )

    def build_manual_form(self):
        """Baut das Formular für die manuelle Eingabe."""
        oldschool_mode = bool(self.config.get_settings().get("oldschool_mode", False))
        row = 0
        if not oldschool_mode:
            row = self._create_id_fields(
                row=row,
                mode='manual',
                kunden_id_label="Kunden ID:",
                booking_id_label="Booking ID:"
            )
            # Kontakt-/Namensfelder im manuellen Modus bewusst ausblenden
            self.vorname_var.set("")
            self.nachname_var.set("")
            self.email_var.set("")
            self.telefon_var.set("")
        else:
            self.vorname_var.set("")
            self.nachname_var.set("")
            self.email_var.set("")
            self.telefon_var.set("")
            tk.Label(self.frame, text="Vorname:", font=("Arial", 11)).grid(
                row=row, column=0, padx=5, pady=5, sticky="w"
            )
            self.entry_vorname = tk.Entry(self.frame, textvariable=self.vorname_var, font=("Arial", 11))
            self.entry_vorname.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

            tk.Label(self.frame, text="Nachname:", font=("Arial", 11)).grid(
                row=row, column=2, padx=(10, 5), pady=5, sticky="w"
            )
            self.entry_nachname = tk.Entry(self.frame, textvariable=self.nachname_var, font=("Arial", 11))
            self.entry_nachname.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
            row += 1

            tk.Label(self.frame, text="Email:", font=("Arial", 11)).grid(
                row=row, column=0, padx=5, pady=5, sticky="w"
            )
            self.entry_email = tk.Entry(self.frame, textvariable=self.email_var, font=("Arial", 11))
            self.entry_email.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

            tk.Label(self.frame, text="Telefon:", font=("Arial", 11)).grid(
                row=row, column=2, padx=(10, 5), pady=5, sticky="w"
            )
            self.entry_telefon = tk.Entry(self.frame, textvariable=self.telefon_var, font=("Arial", 11))
            self.entry_telefon.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
            row += 1

        # --- VERSCHOBENE Felder ---
        if not oldschool_mode:
            row = self._create_gast_name_field(row)
        row = self._create_tandemmaster_field(row)
        row = self._create_datum_ort_fields(row)
        # --- ENDE VERSCHOBEN ---

        # --- Video Modus Toggle-Buttons ---
        self.video_widgets_list = []  # Zurücksetzen
        mode_frame = tk.Frame(self.frame)
        mode_frame.grid(row=row, column=0, columnspan=5, pady=5, sticky="w")

        self._create_mode_toggle_buttons(mode_frame)

        # Videospringer-Widgets (normal)
        self.label_videospringer = tk.Label(mode_frame, text="Videospringer:", font=("Arial", 11))
        # Videospringer-Variable aus Settings laden
        self.videospringer_var.set(self.config.get_settings().get("videospringer", ""))
        self.entry_videospringer = tk.Entry(mode_frame, font=("Arial", 11),
                                            textvariable=self.videospringer_var)
        row += 1

        # --- Handcam Frame (normal) ---
        self.handcam_frame = tk.Frame(self.frame)
        self.handcam_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Handcam Foto
        self.handcam_foto_var.set(False)
        chk_hf = tk.Checkbutton(self.handcam_frame, text="Handcam Foto", variable=self.handcam_foto_var,
                                font=("Arial", 11))
        chk_hf.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hf)  # Hinzufügen

        self.handcam_foto_bezahlt_var.set(False)
        chk_hfb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_foto_bezahlt_var,
                                 font=("Arial", 11))
        chk_hfb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hfb)  # Hinzufügen

        # Handcam Video
        self.handcam_video_var.set(False)
        chk_hv = tk.Checkbutton(self.handcam_frame, text="Handcam Video", variable=self.handcam_video_var,
                                font=("Arial", 11))
        chk_hv.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hv)  # Hinzufügen

        self.handcam_video_bezahlt_var.set(False)
        chk_hvb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_video_bezahlt_var,
                                 font=("Arial", 11))
        chk_hvb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hvb)  # Hinzufügen

        # --- Outside Frame (normal) ---
        self.outside_frame = tk.Frame(self.frame)
        self.outside_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Outside Foto
        self.outside_foto_var.set(False)
        chk_of = tk.Checkbutton(self.outside_frame, text="Outside Foto", variable=self.outside_foto_var,
                                font=("Arial", 11))
        chk_of.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_of)  # Hinzufügen

        self.outside_foto_bezahlt_var.set(False)
        chk_ofb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_foto_bezahlt_var,
                                 font=("Arial", 11))
        chk_ofb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ofb)  # Hinzufügen

        # Outside Video
        self.outside_video_var.set(False)
        chk_ov = tk.Checkbutton(self.outside_frame, text="Outside Video", variable=self.outside_video_var,
                                font=("Arial", 11))
        chk_ov.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ov)  # Hinzufügen

        self.outside_video_bezahlt_var.set(False)
        chk_ovb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_video_bezahlt_var,
                                 font=("Arial", 11))
        chk_ovb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ovb)  # Hinzufügen

        self.video_mode_var.set("")
        row += 1  # Wichtig: Zeile für die Frames erhöhen
        self._update_mode_button_styles()
        self.toggle_video_mode_visibility()

    # --- Methoden zum Erstellen gemeinsamer Felder ---

    def _create_id_fields(self, row, mode, kunden_id_val="", booking_id_val="", kunden_id_label="Kunden ID:",
                          booking_id_label="Booking ID:"):
        """Erstellt Kunden-ID und Booking-ID Felder."""
        tk.Label(self.frame, text=kunden_id_label, font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.kunde_id_var.set(kunden_id_val)

        tk.Label(self.frame, text=booking_id_label, font=("Arial", 11)).grid(row=row, column=2, padx=(10, 5), pady=5, sticky="w")
        self.booking_id_var.set(booking_id_val)

        if mode == 'kunde':
            self.entry_kunde_id = tk.Entry(
                self.frame,
                textvariable=self.kunde_id_var,
                font=("Arial", 11),
                state='disabled',
                relief='flat',
                bg='#f0f0f0'
            )
            self.entry_booking_id = tk.Entry(
                self.frame,
                textvariable=self.booking_id_var,
                font=("Arial", 11),
                state='disabled',
                relief='flat',
                bg='#f0f0f0'
            )
        else:
            self.entry_kunde_id = tk.Entry(self.frame, textvariable=self.kunde_id_var, font=("Arial", 11))
            self.entry_booking_id = tk.Entry(self.frame, textvariable=self.booking_id_var, font=("Arial", 11))

        self.entry_kunde_id.grid(row=row, column=1, padx=5, pady=5, sticky="ew")
        self.entry_booking_id.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
        return row + 1

    def _create_gast_name_field(self, row):
        tk.Label(self.frame, text="Name:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5,
                                                                    sticky="w")
        self.gast_name_var.set(self.config.get_settings().get("gast_name", ""))
        self.entry_gast_name = tk.Entry(self.frame, font=("Arial", 11),
                                        textvariable=self.gast_name_var)
        self.entry_gast_name.grid(row=row, column=1, columnspan=4, padx=5, pady=5, sticky="ew")
        return row + 1

    def _create_tandemmaster_field(self, row):
        tk.Label(self.frame, text="Tandemmaster:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5,
                                                                            sticky="w")
        # Tandemmaster-Variable aus Settings laden
        self.tandemmaster_var.set(self.config.get_settings().get("tandemmaster", ""))
        self.entry_tandemmaster = tk.Entry(self.frame, font=("Arial", 11),
                                           textvariable=self.tandemmaster_var)
        self.entry_tandemmaster.grid(row=row, column=1, columnspan=4, padx=5, pady=5, sticky="ew")  # columnspan=4
        return row + 1

    def _create_datum_ort_fields(self, row):
        """Erstellt Datum und Ort in einer Zeile."""
        # Datum
        tk.Label(self.frame, text="Datum:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.entry_datum = DateEntry(self.frame, width=15, font=("Arial", 11),  # Breite angepasst
                                     date_pattern='dd.mm.yyyy', set_date=date.today())
        self.entry_datum.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

        # Ort
        tk.Label(self.frame, text="Ort:", font=("Arial", 11)).grid(row=row, column=2, padx=(10, 5), pady=5, sticky="w")
        # Ort-Variable aus Settings laden
        self.ort_var.set(self.config.get_settings().get("ort", "Calden"))

        # Frame für Dropdown mit Pfeil
        ort_frame = tk.Frame(self.frame, bg="white", relief=tk.RAISED, borderwidth=1)
        ort_frame.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
        ort_frame.grid_columnconfigure(0, weight=1)

        # Label das wie ein Button aussieht mit Pfeil
        ort_display = tk.Label(
            ort_frame,
            textvariable=self.ort_var,
            font=("Arial", 10),
            bg="white",
            fg="black",
            anchor="w",
            padx=8,
            pady=4,
            cursor="hand2"
        )
        ort_display.grid(row=0, column=0, sticky="ew")

        # Pfeil-Label (rechts)
        ort_arrow = tk.Label(
            ort_frame,
            text="▼",
            font=("Arial", 8),
            bg="white",
            fg="black",
            padx=5,
            cursor="hand2"
        )
        ort_arrow.grid(row=0, column=1)

        # Verstecktes OptionMenu (für Funktionalität)
        dropdown_ort = tk.OptionMenu(self.frame, self.ort_var, "Calden", "Gera")

        # Style für das Dropdown-Menü
        dropdown_ort["menu"].config(
            font=("Arial", 10),
            bg="white",
            fg="black",
            activebackground="#2196F3",
            activeforeground="white",
            relief=tk.FLAT,
            borderwidth=0
        )

        # Click-Handler für Frame und Labels
        def show_ort_menu(event):
            dropdown_ort.event_generate("<Button-1>")
            # Positioniere das Menü unter dem Frame
            x = ort_frame.winfo_rootx()
            y = ort_frame.winfo_rooty() + ort_frame.winfo_height()
            try:
                dropdown_ort["menu"].tk_popup(x, y)
            finally:
                dropdown_ort["menu"].grab_release()

        ort_frame.bind("<Button-1>", show_ort_menu)
        ort_display.bind("<Button-1>", show_ort_menu)
        ort_arrow.bind("<Button-1>", show_ort_menu)

        # Hover-Effekte
        def on_enter(e):
            ort_frame.config(bg="#E3F2FD")
            ort_display.config(bg="#E3F2FD")
            ort_arrow.config(bg="#E3F2FD")

        def on_leave(e):
            ort_frame.config(bg="white")
            ort_display.config(bg="white")
            ort_arrow.config(bg="white")

        ort_frame.bind("<Enter>", on_enter)
        ort_frame.bind("<Leave>", on_leave)
        ort_display.bind("<Enter>", on_enter)
        ort_display.bind("<Leave>", on_leave)
        ort_arrow.bind("<Enter>", on_enter)
        ort_arrow.bind("<Leave>", on_leave)
        return row + 1

    # --- Hilfs- und Datenmethoden ---

    def _create_mode_toggle_buttons(
        self,
        parent,
        *,
        lockable: bool = False,
        initial_state: str = 'normal',
    ) -> None:
        """Erstellt Handcam/Outside Toggle-Buttons mit einheitlichem Styling."""
        self._mode_toggle_rail = tk.Frame(parent, bg=_MODE_BTN_BORDER, padx=1, pady=1)
        self._mode_toggle_rail.pack(side="left", padx=5)

        inner = tk.Frame(self._mode_toggle_rail, bg=_MODE_BTN_IDLE_BG)
        inner.pack(fill="both", expand=True)

        self.btn_mode_handcam = tk.Button(
            inner, text="Handcam", font=("Arial", 11, "bold"), width=10,
            cursor="hand2", padx=16, pady=6, bd=0,
            command=lambda: self._select_video_mode("handcam"),
        )
        self.btn_mode_handcam.pack(side="left")

        separator = tk.Frame(inner, bg=_MODE_BTN_BORDER, width=1)
        separator.pack(side="left", fill="y")
        separator.pack_propagate(False)

        self.btn_mode_outside = tk.Button(
            inner, text="Outside", font=("Arial", 11, "bold"), width=10,
            cursor="hand2", padx=16, pady=6, bd=0,
            command=lambda: self._select_video_mode("outside"),
        )
        self.btn_mode_outside.pack(side="left")

        if lockable:
            self.video_widgets_list.append(self.btn_mode_handcam)
            self.video_widgets_list.append(self.btn_mode_outside)
            self.btn_mode_handcam.config(state=initial_state)
            self.btn_mode_outside.config(state=initial_state)

        self._update_mode_button_styles()

    def _select_video_mode(self, mode: str):
        """Wählt Handcam/Outside per Toggle-Button."""
        self.video_mode_var.set(mode)
        self._update_mode_button_styles()
        self.toggle_video_mode_visibility()
        if hasattr(self.app, "drag_drop") and self.app.drag_drop:
            self.auto_check_products(
                self.app.drag_drop.has_videos(),
                self.app.drag_drop.has_photos(),
            )

    def _apply_mode_button_style(self, btn, *, selected: bool, on_rail: bool) -> None:
        """Setzt das einheitliche Styling für einen Modus-Toggle-Button."""
        common = dict(
            relief="flat",
            bd=0,
            highlightbackground=_MODE_BTN_BORDER,
            highlightthickness=1,
        )
        if selected:
            btn.config(
                **common,
                bg=_MODE_BTN_SELECTED_BG,
                fg=_MODE_BTN_SELECTED_FG,
                activebackground=_MODE_BTN_SELECTED_ACTIVE_BG,
                activeforeground=_MODE_BTN_SELECTED_FG,
            )
        elif on_rail:
            btn.config(
                **common,
                bg=_MODE_BTN_IDLE_BG,
                fg=_MODE_BTN_IDLE_FG,
                activebackground=_MODE_BTN_IDLE_ACTIVE_BG,
                activeforeground=_MODE_BTN_SELECTED_BG,
            )
        else:
            btn.config(
                **common,
                bg=_MODE_BTN_IDLE_BG,
                fg=_MODE_BTN_MUTED_FG,
                activebackground=_MODE_BTN_MUTED_ACTIVE_BG,
                activeforeground=_MODE_BTN_SELECTED_BG,
            )

    def _update_mode_button_styles(self):
        """Hebt den aktiven Modus-Toggle-Button hervor."""
        if not self.btn_mode_handcam or not self.btn_mode_outside:
            return

        mode = self.video_mode_var.get()
        for btn, value in (
            (self.btn_mode_handcam, "handcam"),
            (self.btn_mode_outside, "outside"),
        ):
            self._apply_mode_button_style(
                btn,
                selected=(mode == value),
                on_rail=(not mode),
            )

    def toggle_video_mode_visibility(self):
        """Zeigt/versteckt Handcam/Outside Frames basierend auf dem gewählten Modus."""
        mode = self.video_mode_var.get()
        if mode == "handcam":
            if self.handcam_frame:
                self.handcam_frame.grid()
            if self.outside_frame:
                self.outside_frame.grid_remove()
            if self.label_videospringer:
                self.label_videospringer.pack_forget()
            if self.entry_videospringer:
                self.entry_videospringer.pack_forget()
        elif mode == "outside":
            if self.handcam_frame:
                self.handcam_frame.grid_remove()
            if self.outside_frame:
                self.outside_frame.grid()
            if self.label_videospringer:
                self.label_videospringer.pack(side="left", padx=(15, 5))
            if self.entry_videospringer:
                self.entry_videospringer.pack(side="left", fill="x", expand=True, padx=(0, 10))
        else:
            if self.handcam_frame:
                self.handcam_frame.grid_remove()
            if self.outside_frame:
                self.outside_frame.grid_remove()
            if self.label_videospringer:
                self.label_videospringer.pack_forget()
            if self.entry_videospringer:
                self.entry_videospringer.pack_forget()

    # --- NEUE METHODEN ZUM UMSCHALTEN DES BEARBEITEN-STATUS ---

    def toggle_edit_state(self, entry_widget, button_widget):
        """Generische Funktion zum Umschalten eines Feldes."""
        if not entry_widget or not button_widget:
            return

        try:
            if button_widget.cget('text') == "Bearbeiten":
                # Zu "Bearbeiten" wechseln
                entry_widget.config(state='normal', relief='sunken', bg='white')
                button_widget.config(text="Übernehmen")
            else:
                # Zu "Nur-Lesen" wechseln
                entry_widget.config(state='disabled', relief='flat', bg='#f0f0f0')
                button_widget.config(text="Bearbeiten")
        except tk.TclError:
            # Widget existiert möglicherweise nicht mehr
            print("Fehler beim Umschalten des Widget-Status.")

    def toggle_edit_gast(self):
        """Schaltet die 'Vorname' und 'Nachname' Felder um."""
        if not self.btn_gast or not self.entry_vorname or not self.entry_nachname:
            return

        try:
            if self.btn_gast.cget('text') == "Bearbeiten":
                # Zu "Bearbeiten" wechseln
                new_state = 'normal'
                new_text = "Übernehmen"
                new_relief = 'sunken'
                new_bg = 'white'
            else:
                # Zu "Nur-Lesen" wechseln
                new_state = 'disabled'
                new_text = "Bearbeiten"
                new_relief = 'flat'
                new_bg = '#f0f0f0'

            # Button ändern
            self.btn_gast.config(text=new_text)

            # Felder ändern
            self.entry_vorname.config(state=new_state, relief=new_relief, bg=new_bg)
            self.entry_nachname.config(state=new_state, relief=new_relief, bg=new_bg)
            if self.entry_email:
                self.entry_email.config(state=new_state, relief=new_relief, bg=new_bg)
            if self.entry_telefon:
                self.entry_telefon.config(state=new_state, relief=new_relief, bg=new_bg)

        except tk.TclError:
            # Widget existiert möglicherweise nicht mehr
            print("Fehler beim Umschalten des Widget-Status (Gast).")

    def toggle_edit_video_mode(self):
        """Schaltet Modus-Toggle-Buttons und Produkt-Checkboxen um."""
        if not self.btn_video_mode:
            return

        try:
            if self.btn_video_mode.cget('text') == "Bearbeiten":
                new_state = 'normal'
                new_text = "Übernehmen"
            else:
                new_state = 'disabled'
                new_text = "Bearbeiten"

            self.btn_video_mode.config(text=new_text)

            for widget in self.video_widgets_list:
                if widget and widget.winfo_exists():
                    widget.config(state=new_state)

            self._update_mode_button_styles()

        except tk.TclError:
            print("Fehler beim Umschalten des Video-Modus-Status.")

    # --- Bestehende Hilfs- und Datenmethoden ---

    def load_initial_settings(self):
        """Lädt Einstellungen nur in die Variablen (Widgets existieren noch nicht)."""
        settings = self.config.get_settings()
        self.ort_var.set(settings.get("ort", "Calden"))
        self.gast_name_var.set(settings.get("gast_name", ""))
        self.tandemmaster_var.set(settings.get("tandemmaster", ""))
        self.videospringer_var.set(settings.get("videospringer", ""))
        self.video_mode_var.set("")

    def get_form_data(self):
        """Sammelt Daten aus dem *aktuell* angezeigten Formular."""
        mode = self.video_mode_var.get()  # Hol den Modus ZUERST
        oldschool_mode = bool(self.config.get_settings().get("oldschool_mode", False))

        data = {
            "tandemmaster": self.entry_tandemmaster.get().strip() if self.entry_tandemmaster else "",
            # NEU: Videospringer nur im Outside-Modus
            "videospringer": self.videospringer_var.get().strip() if mode == "outside" else "",
            "datum": self.entry_datum.get() if self.entry_datum else date.today().strftime('%d.%m.%Y'),
            "ort": self.ort_var.get(),
            "video_mode": mode,
            "form_mode": self.form_mode,
        }

        # Formular-spezifische Daten
        data["vorname"] = self.vorname_var.get().strip()
        data["nachname"] = self.nachname_var.get().strip()
        data["email"] = self.email_var.get().strip()
        data["telefon"] = self.telefon_var.get().strip()
        data["gast"] = f"{data['vorname']} {data['nachname']}".strip()  # .strip() für leere Felder

        if self.form_mode == 'kunde':
            data["kunden_id_hash"] = self.kunde_id_var.get().strip()
            data["booking_id_hash"] = self.booking_id_var.get().strip()
        else:  # 'manual'
            data["kunden_id"] = self.kunde_id_var.get().strip()
            data["booking_id"] = self.booking_id_var.get().strip()
            if oldschool_mode:
                data["gast"] = data["gast"] or "Unbekannt"
            else:
                name = self.gast_name_var.get().strip()
                data["gast"] = name or data["kunden_id"] or "Unbekannt"

        # Werte nur basierend auf dem Modus setzen
        mode = self.video_mode_var.get()
        if mode == "handcam":
            data["handcam_foto"] = self.handcam_foto_var.get()
            data["ist_bezahlt_handcam_foto"] = self.handcam_foto_bezahlt_var.get()
            data["handcam_video"] = self.handcam_video_var.get()
            data["ist_bezahlt_handcam_video"] = self.handcam_video_bezahlt_var.get()
            data["outside_foto"] = False
            data["ist_bezahlt_outside_foto"] = False
            data["outside_video"] = False
            data["ist_bezahlt_outside_video"] = False
        elif mode == "outside":
            data["outside_foto"] = self.outside_foto_var.get()
            data["ist_bezahlt_outside_foto"] = self.outside_foto_bezahlt_var.get()
            data["outside_video"] = self.outside_video_var.get()
            data["ist_bezahlt_outside_video"] = self.outside_video_bezahlt_var.get()
            data["handcam_foto"] = False
            data["ist_bezahlt_handcam_foto"] = False
            data["handcam_video"] = False
            data["ist_bezahlt_handcam_video"] = False
        else:
            data["handcam_foto"] = False
            data["ist_bezahlt_handcam_foto"] = False
            data["handcam_video"] = False
            data["ist_bezahlt_handcam_video"] = False
            data["outside_foto"] = False
            data["ist_bezahlt_outside_foto"] = False
            data["outside_video"] = False
            data["ist_bezahlt_outside_video"] = False

        return data

    def get_settings_data(self):
        """Sammelt Daten, die als Standard gespeichert werden sollen."""
        current_settings_data = self.config.get_settings()

        # Nur allgemeine, nicht-kunden-spezifische Daten speichern
        current_settings_data["ort"] = self.ort_var.get()
        current_settings_data["gast_name"] = self.gast_name_var.get()
        current_settings_data["tandemmaster"] = self.tandemmaster_var.get()
        mode = self.video_mode_var.get()
        if mode:
            current_settings_data["video_mode"] = mode
        current_settings_data["videospringer"] = self.videospringer_var.get()

        return current_settings_data

    def auto_check_products(self, has_videos, has_photos):
        """
        Aktiviert automatisch die Produkt-Checkboxen basierend auf
        hinzugefügten Dateien und dem aktuellen Modus.

        Funktioniert in beiden Modi (manual und kunde).
        - Bereits aktivierte Optionen werden nicht überschrieben
        - Neu durch diese Methode aktivierte Optionen werden als "nicht bezahlt" markiert
        - Bereits angehakte Produkte (z. B. vom QR) werden nicht verändert
        """
        mode = self.video_mode_var.get()

        if mode == "handcam":
            # Video-Option aktivieren wenn Videos importiert wurden
            # Aber nur wenn noch nicht aktiv
            if has_videos and not self.handcam_video_var.get():
                self.handcam_video_var.set(True)
                self.handcam_video_bezahlt_var.set(False)

            # Foto-Option aktivieren wenn Fotos importiert wurden
            if has_photos and not self.handcam_foto_var.get():
                self.handcam_foto_var.set(True)
                self.handcam_foto_bezahlt_var.set(False)

        elif mode == "outside":
            # Video-Option aktivieren wenn Videos importiert wurden
            if has_videos and not self.outside_video_var.get():
                self.outside_video_var.set(True)
                self.outside_video_bezahlt_var.set(False)

            # Foto-Option aktivieren wenn Fotos importiert wurden
            if has_photos and not self.outside_foto_var.get():
                self.outside_foto_var.set(True)
                self.outside_foto_bezahlt_var.set(False)

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    # NEU: Hilfsmethode für Trace-Callbacks
    def _on_product_changed(self, product_name):
        """
        Trace-Callback, der die entsprechende Bezahlt-Checkbox
        deaktiviert, wenn das Produkt abgewählt wird.
        """
        if self._suspend_trace_callbacks:
            return

        try:
            if product_name == 'handcam_foto' and not self.handcam_foto_var.get():
                self.handcam_foto_bezahlt_var.set(False)
            elif product_name == 'handcam_video' and not self.handcam_video_var.get():
                self.handcam_video_bezahlt_var.set(False)
            elif product_name == 'outside_foto' and not self.outside_foto_var.get():
                self.outside_foto_bezahlt_var.set(False)
            elif product_name == 'outside_video' and not self.outside_video_var.get():
                self.outside_video_bezahlt_var.set(False)
        except tk.TclError:
            # Widget existiert möglicherweise nicht mehr
            print("Fehler beim Zurücksetzen der Bezahlt-Checkbox.")

        self._notify_watermark_visibility_update()

    def _on_payment_status_changed(self, product_name=None):
        """
        Trace-Callback für Bezahlt-Checkboxen.
        Aktiviert automatisch die entsprechende Produkt-Checkbox,
        wenn die Bezahlt-Checkbox ausgewählt wird.
        Aktualisiert die Wasserzeichen-Spalten-Sichtbarkeit.
        """
        if self._suspend_trace_callbacks:
            return

        # Automatisches Aktivieren der Produkt-Checkbox
        if product_name:
            try:
                if product_name == 'handcam_foto' and self.handcam_foto_bezahlt_var.get():
                    self.handcam_foto_var.set(True)
                elif product_name == 'handcam_video' and self.handcam_video_bezahlt_var.get():
                    self.handcam_video_var.set(True)
                elif product_name == 'outside_foto' and self.outside_foto_bezahlt_var.get():
                    self.outside_foto_var.set(True)
                elif product_name == 'outside_video' and self.outside_video_bezahlt_var.get():
                    self.outside_video_var.set(True)
            except tk.TclError as e:
                # Widget existiert möglicherweise nicht mehr
                print(f"Fehler beim Aktivieren der Produkt-Checkbox für {product_name}: {e}")

        self._notify_watermark_visibility_update()


