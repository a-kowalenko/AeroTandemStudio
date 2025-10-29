import tkinter as tk
from tkcalendar import DateEntry
from datetime import date


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
        self.tandemmaster_var = tk.StringVar()
        self.videospringer_var = tk.StringVar()

        # Variable für den Videomodus (Handcam vs. Outside)
        self.video_mode_var = tk.StringVar(value="handcam")

        # Variablen für Kunde/Manuell-Form
        self.kunde_id_var = tk.StringVar()
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

        # --- Widget-Platzhalter ---
        self.entry_load = None
        self.entry_kunde_id = None
        self.entry_vorname = None  # NEU
        self.entry_nachname = None  # NEU
        self.entry_email = None
        self.entry_telefon = None
        self.entry_tandemmaster = None
        self.entry_datum = None
        self.label_videospringer = None
        self.entry_videospringer = None

        # NEU: Platzhalter für Bearbeiten-Buttons
        self.btn_gast = None  # Bleibt (kontrolliert jetzt Vor- und Nachname)
        self.btn_email = None
        self.btn_telefon = None
        self.btn_video_mode = None

        # NEU: Liste für Video-Widgets (Radios, Checkboxen)
        self.video_widgets_list = []

        # Container-Frames für die umschaltbaren Sektionen
        self.handcam_frame = None
        self.outside_frame = None

        # Aktueller Formular-Modus
        self.form_mode = 'manual'  # Startet im manuellen Modus

        # Lade Einstellungen und baue initiales Formular
        self.load_initial_settings()
        self.build_manual_form()

    def clear_form(self):
        """Entfernt alle Widgets aus dem Frame."""
        for widget in self.frame.winfo_children():
            widget.destroy()
        # NEU: Widget-Liste leeren
        self.video_widgets_list = []

        # NEU: Referenzen auf zerstörte Widgets löschen, um Fehler zu vermeiden
        self.entry_load = None
        self.entry_kunde_id = None
        self.entry_vorname = None
        self.entry_nachname = None
        self.entry_email = None
        self.entry_telefon = None
        self.entry_tandemmaster = None
        self.entry_datum = None
        self.label_videospringer = None
        self.entry_videospringer = None
        self.btn_gast = None
        self.btn_email = None
        self.btn_telefon = None
        self.btn_video_mode = None
        self.handcam_frame = None
        self.outside_frame = None

    def update_form_layout(self, qr_success, kunde=None):
        """
        Aktualisiert das Formular-Layout basierend auf dem QR-Scan-Ergebnis.
        """
        # Aktuelle Load Nr speichern, falls vorhanden
        load_nr_val = self.entry_load.get() if self.entry_load else ""

        self.clear_form()

        if qr_success and kunde:
            self.form_mode = 'kunde'
            self.build_kunde_form(kunde, load_nr_val)
        else:
            # Dies fängt qr_success=False ODER kunde=None ab
            self.form_mode = 'manual'
            self.build_manual_form(load_nr_val)

    # --- Methoden zum Erstellen von Formular-Layouts ---

    def build_kunde_form(self, kunde, load_nr_val=""):
        """Baut das Formular für einen erkannten Kunden."""
        row = 0
        # Load Nr und Kunde ID in einer Zeile
        row = self._create_load_kunde_id_fields(row, 'kunde', load_nr_val, kunde.kunde_id)

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

        # Email (vorbelegt, nicht bearbeitbar)
        tk.Label(self.frame, text="Email:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.email_var.set(kunde.email)
        self.entry_email = tk.Entry(self.frame, textvariable=self.email_var, font=("Arial", 11),
                                    state='disabled', relief='flat', bg='#f0f0f0')
        self.entry_email.grid(row=row, column=1, columnspan=3, padx=5, pady=5, sticky="ew")  # Colspan 3
        self.btn_email = tk.Button(self.frame, text="Bearbeiten", command=self.toggle_edit_email)
        self.btn_email.grid(row=row, column=4, padx=5, pady=5)
        row += 1

        # Telefon (vorbelegt, nicht bearbeitbar)
        tk.Label(self.frame, text="Telefon:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.telefon_var.set(kunde.telefon)
        self.entry_telefon = tk.Entry(self.frame, textvariable=self.telefon_var, font=("Arial", 11),
                                      state='disabled', relief='flat', bg='#f0f0f0')
        self.entry_telefon.grid(row=row, column=1, columnspan=3, padx=5, pady=5, sticky="ew")  # Colspan 3
        self.btn_telefon = tk.Button(self.frame, text="Bearbeiten", command=self.toggle_edit_telefon)
        self.btn_telefon.grid(row=row, column=4, padx=5, pady=5)
        row += 1

        # --- VERSCHOBENE Felder ---
        row = self._create_tandemmaster_field(row)
        row = self._create_datum_ort_fields(row)
        # --- ENDE VERSCHOBEN ---

        # --- Video Modus Radio-Buttons (nicht bearbeitbar) ---
        self.video_widgets_list = []  # Zurücksetzen
        mode_frame = tk.Frame(self.frame)
        mode_frame.grid(row=row, column=0, columnspan=5, pady=5, sticky="w")

        self.radio_handcam = tk.Radiobutton(mode_frame, text="Handcam", variable=self.video_mode_var, value="handcam",
                                            command=self.toggle_video_mode_visibility, font=("Arial", 11, "bold"),
                                            state='disabled')
        self.radio_handcam.pack(side="left", padx=5)
        self.video_widgets_list.append(self.radio_handcam)

        self.radio_outside = tk.Radiobutton(mode_frame, text="Outside", variable=self.video_mode_var, value="outside",
                                            command=self.toggle_video_mode_visibility, font=("Arial", 11, "bold"),
                                            state='disabled')
        self.radio_outside.pack(side="left", padx=5)
        self.video_widgets_list.append(self.radio_outside)

        # Videospringer-Widgets (state='disabled')
        self.label_videospringer = tk.Label(mode_frame, text="Videospringer:", font=("Arial", 11))
        self.entry_videospringer = tk.Entry(mode_frame, font=("Arial", 11),
                                            textvariable=self.videospringer_var)
        # Videospringer-Variable aus Settings laden, falls vorhanden (wird im Kunde-Modus oft leer sein)
        self.videospringer_var.set(self.config.get_settings().get("videospringer", ""))

        # Button für Video-Modus
        self.btn_video_mode = tk.Button(mode_frame, text="Bearbeiten", command=self.toggle_edit_video_mode)
        self.btn_video_mode.pack(side="left", padx=(20, 5))

        row += 1

        # --- Handcam Frame (Checkbuttons state='disabled') ---
        self.handcam_frame = tk.Frame(self.frame)
        self.handcam_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Handcam Foto
        self.handcam_foto_var.set(kunde.handcam_foto)
        chk_hf = tk.Checkbutton(self.handcam_frame, text="Handcam Foto", variable=self.handcam_foto_var,
                                font=("Arial", 11), state='disabled')
        chk_hf.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hf)

        self.handcam_foto_bezahlt_var.set(kunde.ist_bezahlt_handcam_foto)
        chk_hfb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_foto_bezahlt_var,
                                 font=("Arial", 11), state='disabled')
        chk_hfb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hfb)

        # Handcam Video
        self.handcam_video_var.set(kunde.handcam_video)
        chk_hv = tk.Checkbutton(self.handcam_frame, text="Handcam Video", variable=self.handcam_video_var,
                                font=("Arial", 11), state='disabled')
        chk_hv.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hv)

        self.handcam_video_bezahlt_var.set(kunde.ist_bezahlt_handcam_video)
        chk_hvb = tk.Checkbutton(self.handcam_frame, text="Bezahlt", variable=self.handcam_video_bezahlt_var,
                                 font=("Arial", 11), state='disabled')
        chk_hvb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_hvb)

        # --- Outside Frame (Checkbuttons state='disabled') ---
        self.outside_frame = tk.Frame(self.frame)
        self.outside_frame.grid(row=row, column=0, columnspan=5, sticky="w", padx=(20, 0))

        # Outside Foto
        self.outside_foto_var.set(kunde.outside_foto)
        chk_of = tk.Checkbutton(self.outside_frame, text="Outside Foto", variable=self.outside_foto_var,
                                font=("Arial", 11), state='disabled')
        chk_of.grid(row=0, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_of)

        self.outside_foto_bezahlt_var.set(kunde.ist_bezahlt_outside_foto)
        chk_ofb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_foto_bezahlt_var,
                                 font=("Arial", 11), state='disabled')
        chk_ofb.grid(row=0, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ofb)

        # Outside Video
        self.outside_video_var.set(kunde.outside_video)
        chk_ov = tk.Checkbutton(self.outside_frame, text="Outside Video", variable=self.outside_video_var,
                                font=("Arial", 11), state='disabled')
        chk_ov.grid(row=1, column=0, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ov)

        self.outside_video_bezahlt_var.set(kunde.ist_bezahlt_outside_video)
        chk_ovb = tk.Checkbutton(self.outside_frame, text="Bezahlt", variable=self.outside_video_bezahlt_var,
                                 font=("Arial", 11), state='disabled')
        chk_ovb.grid(row=1, column=1, padx=10, pady=5, sticky="w")
        self.video_widgets_list.append(chk_ovb)

        # Setze initialen Status für Video Modus
        if kunde.outside_foto or kunde.outside_video:
            self.video_mode_var.set("outside")
        else:
            # Fallback, falls weder Handcam noch Outside gebucht, aber QR gescannt wurde
            # (sollte nicht passieren, aber sicher ist sicher)
            mode = self.config.get_settings().get("video_mode", "handcam")
            if not (kunde.handcam_foto or kunde.handcam_video):
                self.video_mode_var.set(mode)
            else:
                self.video_mode_var.set("handcam")  # Standard ist Handcam, wenn Handcam gebucht

        row += 1  # Wichtig: Zeile für die Frames erhöhen
        self.toggle_video_mode_visibility()  # Rufe auf, um korrekte Sektion anzuzeigen

    def build_manual_form(self, load_nr_val=""):
        """Baut das Formular für die manuelle Eingabe."""
        row = 0
        # Load Nr und Kunde ID in einer Zeile
        row = self._create_load_kunde_id_fields(row, 'manual', load_nr_val)

        # Vorname (bearbeitbar)
        tk.Label(self.frame, text="Vorname:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")
        self.vorname_var.set("")  # Zurücksetzen
        self.entry_vorname = tk.Entry(self.frame, textvariable=self.vorname_var, font=("Arial", 11))
        self.entry_vorname.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

        # Nachname (bearbeitbar)
        tk.Label(self.frame, text="Nachname:", font=("Arial", 11)).grid(row=row, column=2, padx=(10, 5), pady=5,
                                                                        sticky="w")
        self.nachname_var.set("")  # Zurücksetzen
        self.entry_nachname = tk.Entry(self.frame, textvariable=self.nachname_var, font=("Arial", 11))
        self.entry_nachname.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
        row += 1

        # Email (im manuellen Modus nicht vorhanden)
        self.email_var.set("")
        # Telefon (im manuellen Modus nicht vorhanden)
        self.telefon_var.set("")

        # --- VERSCHOBENE Felder ---
        row = self._create_tandemmaster_field(row)
        row = self._create_datum_ort_fields(row)
        # --- ENDE VERSCHOBEN ---

        # --- Video Modus Radio-Buttons (normal) ---
        self.video_widgets_list = []  # Zurücksetzen
        mode_frame = tk.Frame(self.frame)
        mode_frame.grid(row=row, column=0, columnspan=5, pady=5, sticky="w")

        radio_handcam = tk.Radiobutton(mode_frame, text="Handcam", variable=self.video_mode_var, value="handcam",
                                       command=self.toggle_video_mode_visibility, font=("Arial", 11, "bold"))
        radio_handcam.pack(side="left", padx=5)
        self.video_widgets_list.append(radio_handcam)  # Hinzufügen zur Liste (für Kunde-Modus)

        radio_outside = tk.Radiobutton(mode_frame, text="Outside", variable=self.video_mode_var, value="outside",
                                       command=self.toggle_video_mode_visibility, font=("Arial", 11, "bold"))
        radio_outside.pack(side="left", padx=5)
        self.video_widgets_list.append(radio_outside)  # Hinzufügen zur Liste (für Kunde-Modus)

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

        # Setze initialen Modus (aus geladenen Settings)
        self.video_mode_var.set(self.config.get_settings().get("video_mode", "handcam"))
        row += 1  # Wichtig: Zeile für die Frames erhöhen
        self.toggle_video_mode_visibility()  # Rufe auf, um korrekte Sektion anzuzeigen

        # Prüfe auf bereits vorhandene Dateien ---
        # Dies geschieht, wenn ein QR-Scan fehlschlägt, aber Dateien vorhanden sind.
        if hasattr(self.app, 'drag_drop') and self.app.drag_drop:
            has_videos = self.app.drag_drop.has_videos()
            has_photos = self.app.drag_drop.has_photos()

            # Rufe die bestehende auto_check-Logik auf
            self.auto_check_products(has_videos, has_photos)

    # --- Methoden zum Erstellen gemeinsamer Felder ---

    def _create_load_kunde_id_fields(self, row, mode, load_nr_val="", kunde_id_val=""):
        """Erstellt Load Nr und Kunde ID in einer Zeile."""
        # Load Nr
        tk.Label(self.frame, text="Load Nr:", font=("Arial", 11)).grid(row=row, column=0, padx=5, pady=5, sticky="w")

        def _validate_digits(new_value):
            return new_value.isdigit() or new_value == ""

        vcmd_loadnr = self.frame.register(_validate_digits)

        self.entry_load = tk.Entry(self.frame, font=("Arial", 11),
                                   validate='key', validatecommand=(vcmd_loadnr, '%P'))
        self.entry_load.insert(0, load_nr_val)
        self.entry_load.grid(row=row, column=1, padx=5, pady=5, sticky="ew")

        # Kunde ID
        tk.Label(self.frame, text="Kunde ID:", font=("Arial", 11)).grid(row=row, column=2, padx=(10, 5), pady=5,
                                                                        sticky="w")

        self.kunde_id_var.set(kunde_id_val)

        if mode == 'kunde':
            self.entry_kunde_id = tk.Entry(self.frame, textvariable=self.kunde_id_var, font=("Arial", 11),
                                           state='disabled', relief='flat', bg='#f0f0f0')
        else:  # 'manual'
            self.entry_kunde_id = tk.Entry(self.frame, textvariable=self.kunde_id_var, font=("Arial", 11))

        self.entry_kunde_id.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
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
        dropdown_ort = tk.OptionMenu(self.frame, self.ort_var, "Calden", "Gera")
        dropdown_ort.config(font=("Arial", 10), width=10)  # Etwas Styling
        dropdown_ort.grid(row=row, column=3, padx=5, pady=5, sticky="ew")
        return row + 1

    # --- Hilfs- und Datenmethoden ---

    def toggle_video_mode_visibility(self):
        """Zeigt/versteckt Handcam/Outside Frames basierend auf dem Radio-Button."""
        mode = self.video_mode_var.get()
        if mode == "handcam":
            if self.handcam_frame:
                self.handcam_frame.grid()
            if self.outside_frame:
                self.outside_frame.grid_remove()
            # Videospringer ausblenden (mit pack_forget)
            if self.label_videospringer:
                self.label_videospringer.pack_forget()
            if self.entry_videospringer:
                self.entry_videospringer.pack_forget()
        elif mode == "outside":
            if self.handcam_frame:
                self.handcam_frame.grid_remove()
            if self.outside_frame:
                self.outside_frame.grid()
            # Videospringer einblenden (mit pack)
            if self.label_videospringer:
                # Packt rechts von den Radio-Buttons
                self.label_videospringer.pack(side="left", padx=(15, 5))
            if self.entry_videospringer:
                self.entry_videospringer.pack(side="left", fill="x", expand=True, padx=(0, 10))

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

        except tk.TclError:
            # Widget existiert möglicherweise nicht mehr
            print("Fehler beim Umschalten des Widget-Status (Gast).")

    def toggle_edit_email(self):
        """Schaltet das 'Email'-Feld um."""
        self.toggle_edit_state(self.entry_email, self.btn_email)

    def toggle_edit_telefon(self):
        """Schaltet das 'Telefon'-Feld um."""
        self.toggle_edit_state(self.entry_telefon, self.btn_telefon)

    def toggle_edit_video_mode(self):
        """Schaltet alle Radio-Buttons und Checkboxen für den Video-Modus um."""
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

            # Alle Radios und Checkboxen umschalten
            for widget in self.video_widgets_list:
                if widget and widget.winfo_exists():  # Prüfen ob Widget noch existiert
                    widget.config(state=new_state)

        except tk.TclError:
            print("Fehler beim Umschalten des Video-Modus-Status.")

    # --- Bestehende Hilfs- und Datenmethoden ---

    def load_initial_settings(self):
        """Lädt Einstellungen nur in die Variablen (Widgets existieren noch nicht)."""
        settings = self.config.get_settings()
        self.ort_var.set(settings.get("ort", "Calden"))
        self.tandemmaster_var.set(settings.get("tandemmaster", ""))
        self.videospringer_var.set(settings.get("videospringer", ""))
        self.video_mode_var.set(settings.get("video_mode", "handcam"))

    def get_form_data(self):
        """Sammelt Daten aus dem *aktuell* angezeigten Formular."""
        mode = self.video_mode_var.get()  # Hol den Modus ZUERST

        data = {
            "load": self.entry_load.get().strip() if self.entry_load else "",
            "tandemmaster": self.entry_tandemmaster.get().strip() if self.entry_tandemmaster else "",
            # NEU: Videospringer nur im Outside-Modus
            "videospringer": self.videospringer_var.get().strip() if mode == "outside" else "",
            "datum": self.entry_datum.get() if self.entry_datum else date.today().strftime('%d.%m.%Y'),
            "ort": self.ort_var.get(),
            "video_mode": mode,
        }

        # Formular-spezifische Daten
        data["vorname"] = self.vorname_var.get().strip()
        data["nachname"] = self.nachname_var.get().strip()
        data["gast"] = f"{data['vorname']} {data['nachname']}".strip()  # .strip() für leere Felder

        if self.form_mode == 'kunde':
            data["kunde_id"] = self.kunde_id_var.get()
            # gast, vorname, nachname sind schon gesetzt
            data["email"] = self.email_var.get()
            data["telefon"] = self.telefon_var.get()
        else:  # 'manual'
            data["kunde_id"] = self.kunde_id_var.get().strip()
            # gast, vorname, nachname sind schon gesetzt
            data["email"] = ""  # Nicht im Formular
            data["telefon"] = ""  # Nicht im Formular

        # Werte nur basierend auf dem Modus setzen
        mode = self.video_mode_var.get()
        if mode == "handcam":
            data["handcam_foto"] = self.handcam_foto_var.get()
            data["ist_bezahlt_handcam_foto"] = self.handcam_foto_bezahlt_var.get()
            data["handcam_video"] = self.handcam_video_var.get()
            data["ist_bezahlt_handcam_video"] = self.handcam_video_bezahlt_var.get()
            # Inaktive auf False setzen
            data["outside_foto"] = False
            data["ist_bezahlt_outside_foto"] = False
            data["outside_video"] = False
            data["ist_bezahlt_outside_video"] = False
        else:  # mode == "outside"
            data["outside_foto"] = self.outside_foto_var.get()
            data["ist_bezahlt_outside_foto"] = self.outside_foto_bezahlt_var.get()
            data["outside_video"] = self.outside_video_var.get()
            data["ist_bezahlt_outside_video"] = self.outside_video_bezahlt_var.get()
            # Inaktive auf False setzen
            data["handcam_foto"] = False
            data["ist_bezahlt_handcam_foto"] = False
            data["handcam_video"] = False
            data["ist_bezahlt_handcam_video"] = False

        return data

    def get_settings_data(self):
        """Sammelt Daten, die als Standard gespeichert werden sollen."""
        current_settings_data = self.config.get_settings()

        # Nur allgemeine, nicht-kunden-spezifische Daten speichern
        current_settings_data["ort"] = self.ort_var.get()
        current_settings_data["tandemmaster"] = self.tandemmaster_var.get()
        current_settings_data["video_mode"] = self.video_mode_var.get()
        current_settings_data["videospringer"] = self.videospringer_var.get()

        return current_settings_data

    def auto_check_products(self, has_videos, has_photos):
        """
        Aktiviert automatisch die Produkt-Checkboxen basierend auf
        hinzugefügten Dateien und dem aktuellen Modus.
        Funktioniert nur im 'manual'-Modus.
        """
        # Nur im manuellen Modus automatisch ändern
        if self.form_mode != 'manual':
            return

        mode = self.video_mode_var.get()

        if mode == "handcam":
            if has_videos:
                self.handcam_video_var.set(True)
            if has_photos:
                self.handcam_foto_var.set(True)
        elif mode == "outside":
            if has_videos:
                self.outside_video_var.set(True)
            if has_photos:
                self.outside_foto_var.set(True)

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)

    # NEU: Hilfsmethode für Trace-Callbacks
    def _on_product_changed(self, product_name):
        """
        Trace-Callback, der die entsprechende Bezahlt-Checkbox
        deaktiviert, wenn das Produkt abgewählt wird.
        """
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
