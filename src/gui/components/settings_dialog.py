import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from src.utils.constants import APP_VERSION, PAYPAL_LOGO_PATH

class SettingsDialog:
    """Einstellungs-Dialog für Server-Konfiguration"""

    def __init__(self, parent, config):
        self.parent = parent
        self.config = config
        self.dialog = None
        self.APP_VERSION = APP_VERSION

    def show(self):
        """Zeigt den Einstellungs-Dialog"""
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Einstellungen")
        self.dialog.geometry("600x500")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        self.dialog.grab_set()

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

        dialog_width = 400
        dialog_height = 350

        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2

        self.dialog.geometry(f"+{x}+{y}")

    def create_widgets(self):
        """Erstellt die Widgets für den Dialog"""
        # Haupt-Container
        main_frame = tk.Frame(self.dialog, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        # Titel
        title_label = tk.Label(
            main_frame,
            text="Server Einstellungen",
            font=("Arial", 16, "bold"),
            pady=10
        )
        title_label.pack()

        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=10)

        # Server-Adresse Frame
        server_frame = tk.Frame(main_frame)
        server_frame.pack(fill="x", pady=15)

        tk.Label(
            server_frame,
            text="Server Adresse:",
            font=("Arial", 11),
            anchor="w"
        ).pack(fill="x")

        self.server_var = tk.StringVar()
        self.server_entry = tk.Entry(
            server_frame,
            textvariable=self.server_var,
            font=("Arial", 11),
            width=40
        )
        self.server_entry.pack(fill="x", pady=5)

        # Hilfstext
        help_text = "Beispiel: smb://169.254.169.254/aktuell"
        help_label = tk.Label(
            server_frame,
            text=help_text,
            font=("Arial", 9),
            fg="gray",
            anchor="w"
        )
        help_label.pack(fill="x")

        # Button Frame
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill="x", pady=20)

        # Speichern Button
        save_button = tk.Button(
            button_frame,
            text="Speichern",
            font=("Arial", 11, "bold"),
            command=self.save_settings,
            bg="#4CAF50",
            fg="white",
            width=15,
            height=1
        )
        save_button.pack(pady=5)

        # Abbrechen Button
        cancel_button = tk.Button(
            button_frame,
            text="Abbrechen",
            font=("Arial", 11),
            command=self.dialog.destroy,
            bg="#f44336",
            fg="white",
            width=15,
            height=1
        )
        cancel_button.pack(pady=5)

        # Separator
        ttk.Separator(main_frame, orient='horizontal').pack(fill='x', pady=10)

        # PayPal Donation Frame
        donation_frame = tk.Frame(main_frame)
        donation_frame.pack(fill="x", pady=5)

        # PayPal Donation Button (dezent) with logo
        self.paypal_img = tk.PhotoImage(file=PAYPAL_LOGO_PATH, width=30)
        paypal_button = tk.Button(
            donation_frame,
            text="Entwicklung unterstützen",
            image=self.paypal_img,
            compound="left",
            font=("Arial", 9),
            command=self.open_paypal_donation,
            bg="#f8f9fa",
            fg="#0070ba",
            relief="flat",
            cursor="hand2",
            height=30
        )
        paypal_button.pack(pady=2)

        # Autor Information
        author_frame = tk.Frame(main_frame)
        author_frame.pack(fill="x", pady=10)

        author_text = f"""Aero Tandem Studio v{self.APP_VERSION}\nby Andreas Kowalenko"""

        author_label = tk.Label(
            author_frame,
            text=author_text,
            font=("Arial", 9),
            fg="gray",
            justify="center"
        )
        author_label.pack()

        # Enter-Taste binden
        self.dialog.bind('<Return>', lambda e: self.save_settings())
        # Escape-Taste binden
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def open_paypal_donation(self):
        """Öffnet die PayPal Donations-Seite"""
        try:
            # Ersetzen Sie diese URL mit Ihrer tatsächlichen PayPal Donations-URL
            paypal_url = "https://www.paypal.com/donate/?hosted_button_id=DUNVHWC5FBN3N"
            webbrowser.open_new(paypal_url)
        except Exception as e:
            messagebox.showerror("Fehler", f"PayPal Seite konnte nicht geöffnet werden:\n{str(e)}")

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        settings = self.config.get_settings()
        self.server_var.set(settings.get("server_url", "smb://169.254.169.254/aktuell"))

    def save_settings(self):
        """Speichert die Einstellungen"""
        server_url = self.server_var.get().strip()

        if not server_url:
            messagebox.showwarning("Fehler", "Bitte geben Sie eine Server-Adresse ein.")
            return

        # Validiere das Format (einfache Validierung)
        if not server_url.startswith(('smb://', '//', '\\\\')):
            messagebox.showwarning(
                "Format Fehler",
                "Server-Adresse sollte mit 'smb://' beginnen.\n\nBeispiel: smb://169.254.169.254/aktuell"
            )
            return

        try:
            # Aktuelle Einstellungen laden
            current_settings = self.config.get_settings()
            # Server-URL aktualisieren
            current_settings["server_url"] = server_url
            # Speichern
            self.config.save_settings(current_settings)

            messagebox.showinfo("Erfolg", "Einstellungen wurden gespeichert.")
            self.dialog.destroy()

        except Exception as e:
            messagebox.showerror("Fehler", f"Einstellungen konnten nicht gespeichert werden:\n{str(e)}")