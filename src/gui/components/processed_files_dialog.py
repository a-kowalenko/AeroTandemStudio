import tkinter as tk
from tkinter import ttk, messagebox
from src.utils.media_history import MediaHistoryStore

class ProcessedFilesDialog:
    """Dialog zur Anzeige und Verwaltung bereits verarbeiteter Dateien."""

    def __init__(self, parent):
        self.parent = parent
        self.dialog = None
        self.tree = None
        self.store = MediaHistoryStore.instance()
        self._width = 950
        self._height = 550
        self.search_var = tk.StringVar()
        self.search_var.trace('w', self._on_search_changed)
        # Filter-Variablen
        self.filter_type_var = tk.StringVar(value="Alle")
        self.filter_period_var = tk.StringVar(value="Alle Zeit")

    def _center_dialog_fast(self):
        """Zentriert den Dialog über dem Parent-Fenster ohne teure Layout-Updates."""
        try:
            parent_x = self.parent.winfo_rootx()
            parent_y = self.parent.winfo_rooty()
            parent_w = self.parent.winfo_width()
            parent_h = self.parent.winfo_height()
            # Fallback falls 0 (manchmal vor erstem update)
            if parent_w == 1 or parent_h == 1:
                parent_w = self.parent.winfo_screenwidth()
                parent_h = self.parent.winfo_screenheight()
        except Exception:
            parent_x = 0
            parent_y = 0
            parent_w = self.parent.winfo_screenwidth()
            parent_h = self.parent.winfo_screenheight()

        x = parent_x + (parent_w - self._width) // 2
        y = parent_y + (parent_h - self._height) // 2
        x = max(0, x)
        y = max(0, y)
        self.dialog.geometry(f"{self._width}x{self._height}+{x}+{y}")

    def show(self):
        self.dialog = tk.Toplevel(self.parent)
        self.dialog.title("Verarbeitete Dateien")
        self.dialog.resizable(False, False)
        self.dialog.transient(self.parent)
        # Zunächst verstecken um Flickern zu vermeiden
        self.dialog.withdraw()

        main_frame = tk.Frame(self.dialog, padx=10, pady=10)
        main_frame.pack(fill='both', expand=True)

        # Suchfeld
        search_frame = tk.Frame(main_frame)
        search_frame.pack(fill='x', pady=(0, 8))

        tk.Label(search_frame, text="Suchen:", font=("Arial", 10)).pack(side='left', padx=(0, 5))

        search_entry = tk.Entry(search_frame, textvariable=self.search_var, font=("Arial", 10))
        search_entry.pack(side='left', fill='x', expand=True, padx=(0, 10))

        # Statistiken rechts
        self.stats_label = tk.Label(
            search_frame,
            text="",
            font=("Arial", 9),
            fg="gray"
        )
        self.stats_label.pack(side='right')

        # Filter-Frame
        filter_frame = tk.Frame(main_frame)
        filter_frame.pack(fill='x', pady=(0, 8))

        tk.Label(filter_frame, text="Filter:", font=("Arial", 10, "bold")).pack(side='left', padx=(0, 10))

        # Typ-Filter
        tk.Label(filter_frame, text="Typ:", font=("Arial", 9)).pack(side='left', padx=(0, 5))
        type_options = ["Alle", "Videos", "Fotos"]
        type_menu = ttk.Combobox(filter_frame, textvariable=self.filter_type_var,
                                 values=type_options, state='readonly', width=12)
        type_menu.pack(side='left', padx=(0, 15))
        type_menu.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # Zeitraum-Filter
        tk.Label(filter_frame, text="Importiert:", font=("Arial", 9)).pack(side='left', padx=(0, 5))
        period_options = ["Alle Zeit", "Heute", "Letzte 7 Tage", "Letzter Monat", "Letztes Jahr"]
        period_menu = ttk.Combobox(filter_frame, textvariable=self.filter_period_var,
                                   values=period_options, state='readonly', width=15)
        period_menu.pack(side='left', padx=(0, 10))
        period_menu.bind('<<ComboboxSelected>>', lambda e: self._apply_filters())

        # Reset-Button
        reset_btn = tk.Button(filter_frame, text="Filter zurücksetzen",
                             command=self._reset_filters, font=("Arial", 8))
        reset_btn.pack(side='left', padx=(0, 5))

        # Treeview mit Scrollbar in Container-Frame
        tree_container = tk.Frame(main_frame)
        tree_container.pack(fill='both', expand=True, pady=(0, 10))

        # Scrollbar rechts
        scrollbar = ttk.Scrollbar(tree_container, orient='vertical')
        scrollbar.pack(side='right', fill='y')

        # Treeview links (füllt restlichen Platz)
        columns = ("filename", "media_type", "size", "first_seen", "backed_up", "imported")
        self.tree = ttk.Treeview(tree_container, columns=columns, show='headings',
                                 selectmode='extended', yscrollcommand=scrollbar.set)
        self.tree.pack(side='left', fill='both', expand=True)

        # Verbinde Scrollbar mit Treeview
        scrollbar.config(command=self.tree.yview)

        self.tree.heading("filename", text="Dateiname")
        self.tree.heading("media_type", text="Typ")
        self.tree.heading("size", text="Größe")
        self.tree.heading("first_seen", text="Erstmals gesehen")
        self.tree.heading("backed_up", text="Backup")
        self.tree.heading("imported", text="Import")

        # Spalten konfigurieren mit Padding für äußere Spalten
        self.tree.column("filename", width=260, anchor='w', minwidth=100)
        self.tree.column("media_type", width=60, anchor='center', minwidth=50)
        self.tree.column("size", width=80, anchor='e', minwidth=70)
        self.tree.column("first_seen", width=130, anchor='center', minwidth=120)
        self.tree.column("backed_up", width=130, anchor='center', minwidth=120)
        self.tree.column("imported", width=130, anchor='center', minwidth=120)

        # Style für mehr Padding in den Zellen
        style = ttk.Style()
        style.configure("Treeview", rowheight=25, padding=(10, 2, 10, 2))


        # Buttons
        buttons_frame = tk.Frame(main_frame)
        buttons_frame.pack(fill='x', pady=(8,0))

        delete_btn = tk.Button(buttons_frame, text="Ausgewählte entfernen", command=self._delete_selected, bg="#f44336", fg='white')
        delete_btn.pack(side='left', padx=(0,5))

        purge_btn = tk.Button(buttons_frame, text="Alles löschen…", command=self._purge_all, bg="#9E9E9E", fg='white')
        purge_btn.pack(side='left', padx=(0,5))

        close_btn = tk.Button(buttons_frame, text="Schließen", command=self.dialog.destroy)
        close_btn.pack(side='right')

        info_label = tk.Label(main_frame, text="Hinweis: Das Entfernen von Einträgen löscht keine Dateien. Gelöschte Einträge werden beim nächsten Backup/Import erneut berücksichtigt.", fg='gray', anchor='w', justify='left', wraplength=760)
        info_label.pack(fill='x', pady=(6,0))

        # Einträge laden bevor wir zeigen
        self._load_entries()

        # Zentrieren und anzeigen
        self._center_dialog_fast()
        self.dialog.deiconify()
        self.dialog.grab_set()

    def _load_entries(self, search: str = None):
        """Lädt Einträge in die Treeview mit optionaler Suche und Filtern."""
        for row in self.tree.get_children():
            self.tree.delete(row)

        entries = self.store.list_entries(limit=2000, search=search)

        # Filtere Einträge
        entries = self._apply_filters_to_entries(entries)

        for e in entries:
            size_mb = e['size_bytes'] / (1024*1024)

            # Formatiere Timestamps in dd.MM.yyyy - HH:MM:SS (Lokalzeit)
            first_seen = self._format_timestamp(e['first_seen_at'])
            backed_up = self._format_timestamp(e['backed_up_at'])
            imported = self._format_timestamp(e['imported_at'])

            self.tree.insert('', 'end', iid=str(e['id']), values=(
                e['filename'],
                e['media_type'],
                f"{size_mb:.2f} MB",
                first_seen,
                backed_up,
                imported
            ))

        # Aktualisiere Statistiken
        is_filtered = search is not None or self._has_active_filters()
        self._update_statistics(len(entries), is_filtered)

    def _apply_filters_to_entries(self, entries):
        """Wendet Typ- und Zeitraum-Filter auf Einträge an."""
        filtered = entries

        # Typ-Filter
        filter_type = self.filter_type_var.get()
        if filter_type == "Videos":
            filtered = [e for e in filtered if e['media_type'].lower() == 'video']
        elif filter_type == "Fotos":
            filtered = [e for e in filtered if e['media_type'].lower() == 'photo']

        # Zeitraum-Filter (basierend auf imported_at)
        filter_period = self.filter_period_var.get()
        if filter_period != "Alle Zeit":
            from datetime import datetime, timedelta
            now = datetime.now()

            if filter_period == "Heute":
                start_date = now.replace(hour=0, minute=0, second=0, microsecond=0)
            elif filter_period == "Letzte 7 Tage":
                start_date = now - timedelta(days=7)
            elif filter_period == "Letzter Monat":
                start_date = now - timedelta(days=30)
            elif filter_period == "Letztes Jahr":
                start_date = now - timedelta(days=365)
            else:
                start_date = None

            if start_date:
                filtered_by_date = []
                for e in filtered:
                    if e['imported_at']:
                        try:
                            # Parse ISO timestamp
                            imported_dt = datetime.fromisoformat(e['imported_at'].replace('Z', '+00:00'))
                            # Naive datetime als Lokalzeit behandeln
                            if imported_dt.tzinfo is None:
                                imported_dt = imported_dt.replace(tzinfo=None)
                                # Vergleiche mit naive datetime
                                if imported_dt >= start_date:
                                    filtered_by_date.append(e)
                            else:
                                # Mit Timezone-aware datetime
                                if imported_dt.astimezone() >= start_date.astimezone():
                                    filtered_by_date.append(e)
                        except:
                            # Bei Fehler trotzdem anzeigen
                            filtered_by_date.append(e)
                filtered = filtered_by_date

        return filtered

    def _has_active_filters(self):
        """Prüft ob Filter aktiv sind."""
        return (self.filter_type_var.get() != "Alle" or
                self.filter_period_var.get() != "Alle Zeit")

    def _apply_filters(self):
        """Wendet Filter an (nach Combobox-Änderung)."""
        self._load_entries(search=self.search_var.get().strip() or None)

    def _reset_filters(self):
        """Setzt alle Filter zurück."""
        self.filter_type_var.set("Alle")
        self.filter_period_var.set("Alle Zeit")
        self._apply_filters()

    def _format_timestamp(self, timestamp_str: str) -> str:
        """
        Formatiert ISO-Timestamp zu dd.MM.yyyy - HH:MM:SS in Lokalzeit.

        Args:
            timestamp_str: ISO-Format Timestamp oder None

        Returns:
            Formatierter String oder "—" wenn None
        """
        if not timestamp_str:
            return "—"

        try:
            from datetime import datetime

            # Parse ISO-Format
            dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))

            # Wenn naive datetime (keine Timezone-Info), als Lokalzeit behandeln
            if dt.tzinfo is None:
                # Ist bereits in Lokalzeit, direkt formatieren
                return dt.strftime("%d.%m.%Y - %H:%M:%S")
            else:
                # Mit Timezone → zu Lokalzeit konvertieren
                dt_local = dt.astimezone()
                return dt_local.strftime("%d.%m.%Y - %H:%M:%S")
        except Exception as e:
            print(f"Fehler beim Formatieren von Timestamp '{timestamp_str}': {e}")
            return timestamp_str  # Fallback: Zeige Original

    def _update_statistics(self, count: int, is_filtered: bool):
        """Aktualisiert die Statistik-Anzeige."""
        if is_filtered:
            self.stats_label.config(text=f"{count} Treffer")
        else:
            self.stats_label.config(text=f"Gesamt: {count}")

    def _on_search_changed(self, *args):
        """Wird aufgerufen wenn sich der Suchtext ändert."""
        search_text = self.search_var.get().strip()
        if search_text:
            self._load_entries(search=search_text)
        else:
            self._load_entries()

    def _delete_selected(self):
        selection = self.tree.selection()
        if not selection:
            return
        if not messagebox.askyesno("Bestätigen", f"{len(selection)} Einträge wirklich entfernen?", parent=self.dialog):
            return
        ids = [int(iid) for iid in selection]
        self.store.delete_by_ids(ids)
        self._load_entries()

    def _purge_all(self):
        if not messagebox.askyesno("Bestätigen", "Wirklich alle Einträge löschen?", parent=self.dialog):
            return
        self.store.purge_all()
        self._load_entries()
