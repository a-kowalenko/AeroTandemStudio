﻿import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import webbrowser

from src.utils.constants import APP_VERSION, PAYPAL_LOGO_PATH


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
        self.dialog.geometry("550x580")  # Größe angepasst
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

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

        # Zentriere den Dialog
        self._center_dialog()

        self.create_widgets()
        self.load_settings()

        # Fokus auf den Server-Eintrag setzen
        self.server_entry.focus_set()

    def _center_dialog(self):
        """Zentriert den Dialog über dem Parent-Fenster"""
        self.parent.update_idletasks()
        parent_x = self.parent.winfo_rootx()
        parent_y = self.parent.winfo_rooty()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        # Dialog-Dimensionen aus geometry() holen
        try:
            w, h = map(int, self.dialog.geometry().split('x')[0].split('+')[0].split('-')[0])
        except Exception:
            w, h = 550, 580  # Fallback

        x = parent_x + (parent_width - w) // 2
        y = parent_y + (parent_height - h) // 2

        self.dialog.geometry(f"+{x}+{y}")

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

        # --- Tab 2: Server ---
        self.tab_server = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.tab_server, text="Server")
        self.create_server_tab()

        # --- Tab 3: Extras ---
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

        # Dauer
        tk.Label(storage_frame, text="Dauer (Sek.):", font=("Arial", 11)).grid(row=1, column=0, sticky="w", padx=5, pady=5)

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

        # Backup Ordner
        tk.Label(backup_frame, text="Backup Ordner:", font=("Arial", 11)).grid(row=0, column=0, sticky="w", padx=5, pady=5)

        backup_folder_frame = tk.Frame(backup_frame)
        backup_folder_frame.grid(row=0, column=1, sticky="ew", padx=5)
        backup_folder_frame.grid_columnconfigure(0, weight=1)

        backup_folder_entry = tk.Entry(backup_folder_frame, textvariable=self.sd_backup_folder_var,
                                       font=("Arial", 10), state="readonly")
        backup_folder_entry.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        backup_folder_button = tk.Button(backup_folder_frame, text="Wählen...",
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
        self.sd_auto_backup_checkbox.grid(row=1, column=0, columnspan=2, sticky="w", padx=5, pady=2)

        # Abhängige Checkboxen (nur sichtbar wenn Auto-Backup aktiviert)
        self.sd_clear_checkbox = tk.Checkbutton(
            backup_frame,
            text="SD-Karte nach Backup leeren",
            variable=self.sd_clear_var,
            font=("Arial", 10)
        )

        self.sd_auto_import_checkbox = tk.Checkbutton(
            backup_frame,
            text="Automatisch importieren in Aero Tandem Studio",
            variable=self.sd_auto_import_var,
            font=("Arial", 10)
        )

        # Werden nur angezeigt wenn Auto-Backup aktiviert ist
        # Initial-Zustand wird in load_settings() gesetzt

    def on_auto_backup_toggle(self):
        """Wird aufgerufen wenn die Auto-Backup Checkbox geändert wird"""
        is_enabled = self.sd_auto_backup_var.get()

        if is_enabled:
            # Zeige abhängige Checkboxen
            self.sd_clear_checkbox.grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=2)
            self.sd_auto_import_checkbox.grid(row=3, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        else:
            # Verstecke und deaktiviere abhängige Checkboxen
            self.sd_clear_checkbox.grid_forget()
            self.sd_auto_import_checkbox.grid_forget()
            self.sd_clear_var.set(False)
            self.sd_auto_import_var.set(False)

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

        # Trigger checkbox visibility based on auto_backup setting
        self.on_auto_backup_toggle()

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
