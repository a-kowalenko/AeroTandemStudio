"""
Error Dialog - Angelehnt an den Success Dialog
"""
import tkinter as tk


class ErrorDialog:
    """Schöner Error-Dialog für Fehlermeldungen"""

    def __init__(self, parent, title, message, details=None):
        """
        Args:
            parent: Parent-Fenster
            title: Titel des Fehlers
            message: Hauptnachricht
            details: Optionale zusätzliche Details (Liste von Strings)
        """
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Fehler")
        self.dialog.transient(parent)

        # WICHTIG: Verstecke Dialog initial, um Flackern zu vermeiden
        self.dialog.withdraw()

        # Größe des Dialogs (initial, wird später angepasst)
        width = 450
        self.dialog.geometry(f"{width}x300")

        # Style
        self.dialog.configure(bg='#f0f0f0')

        self._create_widgets(title, message, details)

        # Nach Widget-Erstellung: Update und berechne tatsächliche Höhe
        self.dialog.update_idletasks()

        # Hole tatsächliche benötigte Höhe
        required_height = self.dialog.winfo_reqheight()

        # Setze finale Größe mit min/max Grenzen
        final_height = max(250, min(required_height + 20, 600))  # Min 250px, Max 600px
        self.dialog.geometry(f"{width}x{final_height}")

        # Jetzt zentrieren mit finaler Größe
        self._center_window(parent)

        # Nicht in der Größe änderbar
        self.dialog.resizable(False, False)

        # Jetzt erst anzeigen (nach Positionierung)
        self.dialog.deiconify()

        # Jetzt grab_set aufrufen (muss nach deiconify sein)
        self.dialog.grab_set()

    def _center_window(self, parent):
        """Zentriert den Dialog über dem Parent"""
        self.dialog.update_idletasks()

        try:
            parent_x = parent.winfo_x()
            parent_y = parent.winfo_y()
            parent_width = parent.winfo_width()
            parent_height = parent.winfo_height()
        except:
            # Fallback wenn Parent nicht verfügbar
            parent_x = 0
            parent_y = 0
            parent_width = self.dialog.winfo_screenwidth()
            parent_height = self.dialog.winfo_screenheight()

        dialog_width = self.dialog.winfo_width()
        dialog_height = self.dialog.winfo_height()

        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2

        # Verhindere negative Koordinaten
        x = max(0, x)
        y = max(0, y)

        self.dialog.geometry(f"+{x}+{y}")

    def _create_widgets(self, title, message, details):
        """Erstellt die Dialog-Widgets"""

        # Header mit rotem X
        header_frame = tk.Frame(self.dialog, bg='#f44336', height=80)
        header_frame.pack(fill='x', padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Error Icon (großes X)
        error_label = tk.Label(
            header_frame,
            text="✕",
            font=('Arial', 48, 'bold'),
            fg='white',
            bg='#f44336'
        )
        error_label.pack(pady=10)

        # Content Frame
        content_frame = tk.Frame(self.dialog, bg='#f0f0f0')
        content_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Titel
        title_label = tk.Label(
            content_frame,
            text=title,
            font=('Arial', 16, 'bold'),
            bg='#f0f0f0',
            fg='#333333'
        )
        title_label.pack(pady=(0, 10))

        # Hauptnachricht
        message_label = tk.Label(
            content_frame,
            text=message,
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#555555',
            wraplength=400,
            justify='center'
        )
        message_label.pack(pady=(0, 15))

        # Details (falls vorhanden)
        if details:
            details_frame = tk.Frame(content_frame, bg='#ffffff', relief='solid', borderwidth=1)
            details_frame.pack(fill='both', pady=(0, 15), padx=5)

            for detail in details:
                detail_label = tk.Label(
                    details_frame,
                    text=f"• {detail}",
                    font=('Arial', 9),
                    bg='#ffffff',
                    fg='#666666',
                    anchor='w',
                    wraplength=380,  # Textumbruch bei 380px (passt zu 400px Frame - 20px Padding)
                    justify='left'
                )
                detail_label.pack(fill='both', padx=10, pady=3, anchor='w')

        # OK Button
        ok_button = tk.Button(
            content_frame,
            text="OK",
            command=self.dialog.destroy,
            bg='#f44336',
            fg='white',
            font=('Arial', 11, 'bold'),
            width=15,
            height=1,
            relief='raised',
            bd=0,
            cursor='hand2',
            activebackground='#d32f2f',
            activeforeground='white'
        )
        ok_button.pack(pady=(0, 5))

        # X-Button soll wie OK funktionieren
        self.dialog.protocol("WM_DELETE_WINDOW", self.dialog.destroy)

        # Enter-Taste zum Schließen
        self.dialog.bind('<Return>', lambda e: self.dialog.destroy())
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

    def show(self):
        """Zeigt den Dialog an und wartet auf Schließung"""
        self.dialog.wait_window()


def show_error_dialog(parent, title, message, details=None):
    """
    Zeigt einen Error-Dialog an.

    Args:
        parent: Parent-Fenster
        title: Titel des Fehlers
        message: Hauptnachricht
        details: Optionale zusätzliche Details (Liste von Strings)
    """
    dialog = ErrorDialog(parent, title, message, details)
    dialog.show()

