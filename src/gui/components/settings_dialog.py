import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import webbrowser

from src.utils.constants import APP_VERSION, PAYPAL_LOGO_PATH


class SettingsDialog:
    """Einstellungs-Dialog für Server- und App-Konfiguration"""

    def __init__(self, parent, config):
        self.parent = parent
        self.config = config
        self.dialog = None
        self.APP_VERSION = APP_VERSION

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
        # NEU: Variablen für Speicherort und Dauer
        self.speicherort_var = tk.StringVar()
        self.dauer_var = tk.StringVar()

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
        """Erstellt die Widgets für den Dialog (NEUES GRID-LAYOUT)"""

        main_frame = tk.Frame(self.dialog, padx=15, pady=15)
        main_frame.pack(fill="both", expand=True)
        main_frame.grid_columnconfigure(0, weight=1)  # Ganze Spalte dehnbar

        row = 0

        # --- Sektion 1: Server-Verbindung ---
        server_frame = ttk.LabelFrame(main_frame, text="Server-Verbindung", padding=(10, 10))
        server_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        server_frame.grid_columnconfigure(1, weight=1)  # Spalte für Entries dehnbar

        # Server Adresse
        tk.Label(server_frame, text="Adresse:", font=("Arial", 11)).grid(row=0, column=0, sticky="w", padx=5,
                                                                                pady=5)
        self.server_entry = tk.Entry(server_frame, textvariable=self.server_var, font=("Arial", 11))
        self.server_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=5, pady=5)

        tk.Label(server_frame, text="Beispiel: smb://169.254.169.254/aktuell", font=("Arial", 9), fg="gray").grid(row=1,
                                                                                                                  column=1,
                                                                                                                  columnspan=3,
                                                                                                                  sticky="w",
                                                                                                                  padx=5)

        # Login / Passwort
        tk.Label(server_frame, text="Login:", font=("Arial", 11)).grid(row=2, column=0, sticky="w", padx=5,
                                                                              pady=(10, 5))
        self.login_entry = tk.Entry(server_frame, textvariable=self.login_var, font=("Arial", 11), width=20)
        self.login_entry.grid(row=2, column=1, sticky="ew", padx=5, pady=(10, 5))

        tk.Label(server_frame, text="Passwort:", font=("Arial", 11)).grid(row=2, column=2, sticky="w",
                                                                                 padx=(10, 5), pady=(10, 5))
        self.password_entry = tk.Entry(server_frame, textvariable=self.password_var, font=("Arial", 11), width=20,
                                       show="*")
        self.password_entry.grid(row=2, column=3, sticky="ew", padx=5, pady=(10, 5))

        row += 1

        # --- Sektion 2: App-Einstellungen (NEU) ---
        app_settings_frame = ttk.LabelFrame(main_frame, text="App-Einstellungen", padding=(10, 10))
        app_settings_frame.grid(row=row, column=0, sticky="ew", pady=10)
        app_settings_frame.grid_columnconfigure(1, weight=1)  # Spalte 1 (Entry/Dropdown) dehnbar

        # Speicherort
        tk.Label(app_settings_frame, text="Speicherort:", font=("Arial", 11)).grid(row=0, column=0, sticky="w", padx=5,
                                                                                   pady=5)

        speicherort_entry_frame = tk.Frame(app_settings_frame)  # Frame für Entry + Button
        speicherort_entry_frame.grid(row=0, column=1, sticky="ew")
        speicherort_entry_frame.grid_columnconfigure(0, weight=1)

        speicherort_entry = tk.Entry(speicherort_entry_frame, textvariable=self.speicherort_var, font=("Arial", 10),
                                     state="readonly")
        speicherort_entry.grid(row=0, column=0, sticky="ew", padx=5, pady=5)

        speicherort_button = tk.Button(speicherort_entry_frame, text="Wählen...", command=self.waehle_speicherort)
        speicherort_button.grid(row=0, column=1, sticky="e", padx=(0, 5), pady=5)

        # Dauer
        tk.Label(app_settings_frame, text="Dauer (Sek.):", font=("Arial", 11)).grid(row=1, column=0, sticky="w", padx=5,
                                                                                    pady=5)
        dauer_dropdown = tk.OptionMenu(app_settings_frame, self.dauer_var, "1", "3", "4", "5", "6", "7", "8", "9", "10")
        dauer_dropdown.config(font=("Arial", 10), anchor="w")
        dauer_dropdown.grid(row=1, column=1, sticky="w", padx=5, pady=5)  # Nur 'w' sticky

        row += 1

        # --- Sektion 3: Info & Updates ---
        info_frame = ttk.LabelFrame(main_frame, text="Info & Updates", padding=(10, 10))
        info_frame.grid(row=row, column=0, sticky="ew", pady=10)
        info_frame.grid_columnconfigure(0, weight=1)  # Zentriert Buttons/Text
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
            # Fallback, wenn Logo nicht geladen werden kann
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

        row += 1

        # --- Sektion 4: Dialog-Buttons ---
        button_frame = tk.Frame(main_frame)
        button_frame.grid(row=row, column=0, sticky="e", pady=(15, 0))  # Rechtsbündig

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

    def check_for_updates(self):
        """Startet die Update-Prüfung"""
        try:
            # Verwende die gleiche Funktion wie beim App-Start, aber mit Benachrichtigung
            from src.installer.updater import initialize_updater
            initialize_updater(self.dialog, self.APP_VERSION, show_no_update_message=True)
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
        """NEU: Öffnet Dialog zur Auswahl des Speicherorts."""
        directory = filedialog.askdirectory(parent=self.dialog, title="Standard-Speicherort wählen")
        if directory:
            self.speicherort_var.set(directory)

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen (inkl. Speicherort und Dauer)"""
        settings = self.config.get_settings()
        self.server_var.set(settings.get("server_url", "smb://169.254.169.254/aktuell"))
        self.login_var.set(settings.get("server_login", ""))
        self.password_var.set(settings.get("server_password", ""))

        # NEU
        self.speicherort_var.set(settings.get("speicherort", ""))
        self.dauer_var.set(str(settings.get("dauer", 8)))

    def save_settings(self):
        """Speichert die Einstellungen (inkl. Speicherort und Dauer)"""
        server_url = self.server_var.get().strip()
        server_login = self.login_var.get().strip()
        server_password = self.password_var.get()

        # NEU
        speicherort = self.speicherort_var.get()
        dauer = self.dauer_var.get()

        if not server_url:
            messagebox.showwarning("Fehler", "Bitte geben Sie eine Server-Adresse ein.", parent=self.dialog)
            return

        if not server_url.startswith(('smb://', '//', '\\\\')):
            messagebox.showwarning(
                "Format Fehler",
                "Server-Adresse sollte mit 'smb://' beginnen.\n\nBeispiel: smb://169.254.169.254/aktuell",
                parent=self.dialog
            )
            return

        if not speicherort:
            messagebox.showwarning("Fehler", "Bitte geben Sie einen Standard-Speicherort an.", parent=self.dialog)
            return

        try:
            # Aktuelle Einstellungen laden
            current_settings = self.config.get_settings()

            # Server-Daten aktualisieren
            current_settings["server_url"] = server_url
            current_settings["server_login"] = server_login
            current_settings["server_password"] = server_password  # todo: keyring

            # NEU: App-Einstellungen aktualisieren
            current_settings["speicherort"] = speicherort
            current_settings["dauer"] = int(dauer)

            # Speichern
            self.config.save_settings(current_settings)

            messagebox.showinfo("Erfolg", "Einstellungen wurden gespeichert.", parent=self.dialog)
            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("Fehler", f"Einstellungen konnten nicht gespeichert werden:\n{str(e)}",
                                 parent=self.dialog)
