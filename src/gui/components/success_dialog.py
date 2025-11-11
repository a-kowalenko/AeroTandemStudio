import tkinter as tk


class SuccessDialog:
    """Schöner Success-Dialog mit kompakter Auflistung"""

    def __init__(self, parent, created_items):
        """
        Args:
            parent: Parent-Fenster
            created_items: Dict mit erstellten Dateien/Elementen
                {
                    'video': bool/str,  # Video-Pfad oder False
                    'watermark_video': bool/str,  # Wasserzeichen-Video oder False
                    'photos': int,  # Anzahl der Fotos
                    'watermark_photos': int,  # Anzahl Wasserzeichen-Fotos
                    'server_uploaded': bool  # Server-Upload erfolgreich
                }
        """
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Erfolgreich erstellt")
        self.dialog.transient(parent)

        # WICHTIG: Verstecke Dialog initial, um Flackern zu vermeiden
        self.dialog.withdraw()

        # Counter für vorhandene Medien
        self.media_count = 0
        if created_items.get('video'):
            self.media_count += 1
        if created_items.get('watermark_video'):
            self.media_count += 1
        if created_items.get('photos', 0) > 0:
            self.media_count += 1
        if created_items.get('watermark_photos', 0) > 0:
            self.media_count += 1
        if created_items.get('server_uploaded'):
            self.media_count += 1

        # Größe des Dialogs basierend auf der Medienanzahl
        width = 450
        height = 250 + (self.media_count - 1) * 35
        self.dialog.geometry(f"{width}x{height}")

        # Style
        self.dialog.configure(bg='#f0f0f0')

        self._create_widgets(created_items)

        # Zentrieren
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

        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()

        dialog_width = self.dialog.winfo_width()
        dialog_height = self.dialog.winfo_height()

        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2

        self.dialog.geometry(f"+{x}+{y}")

    def _create_widgets(self, created_items):
        """Erstellt die Dialog-Widgets"""

        # Header mit grünem Haken
        header_frame = tk.Frame(self.dialog, bg='#4CAF50', height=80)
        header_frame.pack(fill='x', padx=0, pady=0)
        header_frame.pack_propagate(False)

        # Success Icon (großes Checkmark)
        check_label = tk.Label(
            header_frame,
            text="✓",
            font=('Arial', 48, 'bold'),
            fg='white',
            bg='#4CAF50'
        )
        check_label.pack(pady=10)

        # Content Frame
        content_frame = tk.Frame(self.dialog, bg='#f0f0f0')
        content_frame.pack(fill='both', expand=True, padx=20, pady=20)

        # Titel
        title_label = tk.Label(
            content_frame,
            text="Erfolgreich erstellt!",
            font=('Arial', 16, 'bold'),
            bg='#f0f0f0',
            fg='#333333'
        )
        title_label.pack(pady=(0, 15))

        # Auflistung der erstellten Elemente
        items_frame = tk.Frame(content_frame, bg='#f0f0f0')
        items_frame.pack(fill='both', expand=True)

        # Erstelle Liste der Items
        item_count = 0

        if created_items.get('video'):
            self._add_item(items_frame, "Video erstellt", "🎥")
            item_count += 1

        if created_items.get('watermark_video'):
            self._add_item(items_frame, "Vorschau-Video erstellt", "👁")
            item_count += 1

        photo_count = created_items.get('photos', 0)
        if photo_count > 0:
            text = f"{photo_count} Foto{'s' if photo_count > 1 else ''} kopiert"
            self._add_item(items_frame, text, "📷")
            item_count += 1

        watermark_photo_count = created_items.get('watermark_photos', 0)
        if watermark_photo_count > 0:
            text = f"{watermark_photo_count} Vorschau-Foto{'s' if watermark_photo_count > 1 else ''} erstellt"
            self._add_item(items_frame, text, "🖼")
            item_count += 1

        if created_items.get('server_uploaded'):
            self._add_item(items_frame, "Auf Server hochgeladen", "⬆")
            item_count += 1

        # Falls keine Items (sollte nicht passieren)
        if item_count == 0:
            empty_label = tk.Label(
                items_frame,
                text="Verzeichnis wurde erstellt",
                font=('Arial', 10),
                bg='#f0f0f0',
                fg='#666666'
            )
            empty_label.pack(pady=10)

        # OK Button
        button_frame = tk.Frame(self.dialog, bg='#f0f0f0')
        button_frame.pack(fill='x', padx=20, pady=(0, 20))

        ok_button = tk.Button(
            button_frame,
            text="OK",
            command=self.dialog.destroy,
            font=('Arial', 11, 'bold'),
            bg='#4CAF50',
            fg='white',
            activebackground='#45a049',
            activeforeground='white',
            cursor='hand2',
            relief='flat',
            padx=40,
            pady=10,
            borderwidth=0
        )
        ok_button.pack()

        # Enter-Taste zum Schließen
        self.dialog.bind('<Return>', lambda e: self.dialog.destroy())
        self.dialog.bind('<Escape>', lambda e: self.dialog.destroy())

        # Focus auf OK Button
        ok_button.focus_set()

    def _add_item(self, parent, text, icon):
        """Fügt ein Item zur Liste hinzu"""
        item_frame = tk.Frame(parent, bg='#f0f0f0')
        item_frame.pack(fill='x', pady=3)

        # Icon
        icon_label = tk.Label(
            item_frame,
            text=icon,
            font=('Arial', 14),
            bg='#f0f0f0',
            width=3
        )
        icon_label.pack(side='left')

        # Text
        text_label = tk.Label(
            item_frame,
            text=text,
            font=('Arial', 11),
            bg='#f0f0f0',
            fg='#333333',
            anchor='w'
        )
        text_label.pack(side='left', fill='x', expand=True)


def show_success_dialog(parent, created_items):
    """
    Zeigt den Success-Dialog an.

    Args:
        parent: Parent-Fenster
        created_items: Dict mit erstellten Elementen
    """
    dialog = SuccessDialog(parent, created_items)
    parent.wait_window(dialog.dialog)

