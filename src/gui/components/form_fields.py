import tkinter as tk
from tkinter import filedialog
from tkcalendar import DateEntry
from datetime import date


class FormFields:
    def __init__(self, parent, config):
        self.parent = parent
        self.config = config
        self.frame = tk.Frame(parent)

        # Variablen
        self.outside_video_var = tk.BooleanVar()
        self.speicherort_var = tk.StringVar()
        self.ort_var = tk.StringVar(value="Calden")
        self.dauer_var = tk.StringVar(value="8")

        self.create_fields()
        self.load_initial_settings()

    def create_fields(self):
        self.create_load_field()
        self.create_gast_field()
        self.create_tandemmaster_field()
        self.create_outside_video_checkbox()
        self.create_videospringer_field()
        self.create_datum_field()
        self.create_dauer_field()
        self.create_ort_field()
        self.create_speicherort_field()

    def create_load_field(self):
        tk.Label(self.frame, text="Load Nr:", font=("Arial", 12)).grid(row=0, column=0, padx=5, pady=5, sticky="w")

        def _validate_digits(new_value):
            return new_value.isdigit() or new_value == ""

        vcmd_loadnr = self.frame.register(_validate_digits)

        self.entry_load = tk.Entry(self.frame, width=40, font=("Arial", 12),
                                   validate='key', validatecommand=(vcmd_loadnr, '%P'))
        self.entry_load.grid(row=0, column=1, padx=5, pady=5)

    def create_gast_field(self):
        tk.Label(self.frame, text="Gast:", font=("Arial", 12)).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.entry_gast = tk.Entry(self.frame, width=40, font=("Arial", 12))
        self.entry_gast.grid(row=1, column=1, padx=5, pady=5)

    def create_tandemmaster_field(self):
        tk.Label(self.frame, text="Tandemmaster:", font=("Arial", 12)).grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.entry_tandemmaster = tk.Entry(self.frame, width=40, font=("Arial", 12))
        self.entry_tandemmaster.grid(row=2, column=1, padx=5, pady=5)

    def create_outside_video_checkbox(self):
        tk.Checkbutton(self.frame, text="Outside Video", variable=self.outside_video_var,
                       onvalue=True, offvalue=False, font=("Arial", 12),
                       command=self.toggle_videospringer_visibility).grid(
            row=3, column=0, columnspan=2, pady=5, sticky="w")

    def create_videospringer_field(self):
        self.label_videospringer = tk.Label(self.frame, text="Videospringer:", font=("Arial", 12))
        self.label_videospringer.grid(row=4, column=0, padx=5, pady=5, sticky="w")

        self.entry_videospringer = tk.Entry(self.frame, width=40, font=("Arial", 12))
        self.entry_videospringer.grid(row=4, column=1, padx=5, pady=5)

    def create_datum_field(self):
        tk.Label(self.frame, text="Datum:", font=("Arial", 12)).grid(row=5, column=0, padx=5, pady=5, sticky="w")
        self.entry_datum = DateEntry(self.frame, width=38, font=("Arial", 12),
                                     date_pattern='dd.mm.yyyy', set_date=date.today())
        self.entry_datum.grid(row=5, column=1, padx=5, pady=5)

    def create_dauer_field(self):
        tk.Label(self.frame, text="Dauer (Sekunden):", font=("Arial", 12)).grid(row=6, column=0, padx=5, pady=5,
                                                                                sticky="w")
        self.dropdown_dauer = tk.OptionMenu(self.frame, self.dauer_var, "1", "3", "4", "5", "6", "7", "8", "9", "10")
        self.dropdown_dauer.grid(row=6, column=1, padx=5, pady=5, sticky="ew")

    def create_ort_field(self):
        tk.Label(self.frame, text="Ort:", font=("Arial", 12)).grid(row=7, column=0, padx=5, pady=5, sticky="w")
        self.dropdown_ort = tk.OptionMenu(self.frame, self.ort_var, "Calden", "Gera")
        self.dropdown_ort.grid(row=7, column=1, padx=5, pady=5, sticky="ew")

    def create_speicherort_field(self):
        tk.Label(self.frame, text="Speicherort:", font=("Arial", 12)).grid(row=8, column=0, padx=5, pady=10, sticky="w")

        speicherort_frame = tk.Frame(self.frame)
        speicherort_frame.grid(row=8, column=1, sticky="ew")

        self.speicherort_button = tk.Button(speicherort_frame, text="Wählen...", command=self.waehle_speicherort)
        self.speicherort_button.pack(side=tk.LEFT)

        self.speicherort_label = tk.Label(speicherort_frame, textvariable=self.speicherort_var,
                                          font=("Arial", 10), anchor="w", fg="grey")
        self.speicherort_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

    def toggle_videospringer_visibility(self):
        if self.outside_video_var.get():
            self.label_videospringer.grid()
            self.entry_videospringer.grid()
        else:
            self.label_videospringer.grid_remove()
            self.entry_videospringer.grid_remove()

    def waehle_speicherort(self):
        directory = filedialog.askdirectory()
        if directory:
            self.speicherort_var.set(directory)

    def load_initial_settings(self):
        settings = self.config.get_settings()
        self.speicherort_var.set(settings.get("speicherort", ""))
        self.ort_var.set(settings.get("ort", "Calden"))
        self.outside_video_var.set(settings.get("outside_video", False))
        self.dauer_var.set(str(settings.get("dauer", 8)))

        self.entry_tandemmaster.delete(0, tk.END)
        self.entry_tandemmaster.insert(0, settings.get("tandemmaster", ""))

        self.entry_videospringer.delete(0, tk.END)
        self.entry_videospringer.insert(0, settings.get("videospringer", ""))

        self.toggle_videospringer_visibility()

    def get_form_data(self):
        return {
            "load": self.entry_load.get().strip(),
            "gast": self.entry_gast.get().strip(),
            "tandemmaster": self.entry_tandemmaster.get().strip(),
            "videospringer": self.entry_videospringer.get().strip() if self.outside_video_var.get() else "",
            "datum": self.entry_datum.get(),
            "dauer": int(self.dauer_var.get()),
            "ort": self.ort_var.get(),
            "speicherort": self.speicherort_var.get(),
            "outside_video": self.outside_video_var.get()
        }

    def get_settings_data(self):
        data = self.get_form_data()
        current_settings_data = self.config.get_settings()
        current_settings_data["speicherort"] = data["speicherort"]
        current_settings_data["ort"] = data["ort"]
        current_settings_data["dauer"] = data["dauer"]
        current_settings_data["outside_video"] = data["outside_video"]
        current_settings_data["tandemmaster"] = data["tandemmaster"]
        current_settings_data["videospringer"] = data["videospringer"]

        return current_settings_data

    def pack(self, **kwargs):
        self.frame.pack(**kwargs)