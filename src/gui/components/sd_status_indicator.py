"""
SD-Karten Status Anzeige
Zeigt den Status der SD-Karten Überwachung und Backup-Fortschritt
"""
import tkinter as tk
from tkinter import ttk


class SDStatusIndicator:
    """Zeigt den Status der SD-Karten Überwachung in der UI"""

    def __init__(self, parent):
        self.parent = parent
        self.container = None
        self.icon_label = None
        self.status_label = None
        self.progress_frame = None
        self.progress_bar = None
        self.progress_label = None

        # Status-Variablen
        self.monitoring_active = False
        self.backup_active = False
        self.clearing_active = False  # NEU: SD-Karte wird geleert
        self.sd_detected = False

        # Tooltip-Verwaltung
        self.tooltip = None
        self.tooltip_timer = None

    def create_widgets(self):
        """Erstellt die Status-Widgets"""
        # Haupt-Container (horizontal)
        self.container = tk.Frame(self.parent, bg="#f0f0f0")

        # Icon Label (💾 für Monitoring, 📥 für Backup)
        self.icon_label = tk.Label(
            self.container,
            text="",
            font=("Arial", 16),
            bg="#f0f0f0",
            fg="#009d8b"
        )
        self.icon_label.pack(side="left", padx=(5, 2))

        # Status Text Label
        self.status_label = tk.Label(
            self.container,
            text="",
            font=("Arial", 9),
            bg="#f0f0f0",
            fg="#555"
        )
        self.status_label.pack(side="left", padx=2)

        # Progress Frame (nur sichtbar während Backup)
        self.progress_frame = tk.Frame(self.container, bg="#f0f0f0")

        # Kleine Progress Bar
        self.progress_bar = ttk.Progressbar(
            self.progress_frame,
            orient='horizontal',
            mode='determinate',
            length=100
        )
        self.progress_bar.pack(side="left", padx=5)

        # Progress Text (XX / YY MB, Speed)
        self.progress_label = tk.Label(
            self.progress_frame,
            text="",
            font=("Arial", 8),
            bg="#f0f0f0",
            fg="#555"
        )
        self.progress_label.pack(side="left", padx=2)

        # Tooltip
        self.create_tooltip()

    def create_tooltip(self):
        """Erstellt Tooltip für Status-Anzeige"""
        def show_tooltip(event):
            # Lösche vorhandenen Tooltip falls vorhanden
            self.hide_tooltip()

            if not self.monitoring_active:
                return

            tooltip_text = "SD-Karten Überwachung aktiv"
            if self.backup_active:
                tooltip_text = "Backup läuft..."
            elif self.sd_detected:
                tooltip_text += "\nSD-Karte erkannt"

            # Verzögerung vor Anzeige (verhindert flackern)
            self.tooltip_timer = self.container.after(500, lambda: self._create_tooltip_window(event, tooltip_text))

        def on_leave(event):
            # Tooltip sofort entfernen
            self.hide_tooltip()

        # Binde Events an alle relevanten Widgets
        widgets = [self.container, self.icon_label, self.status_label]
        for widget in widgets:
            if widget:
                widget.bind("<Enter>", show_tooltip)
                widget.bind("<Leave>", on_leave)

    def _create_tooltip_window(self, event, text):
        """Erstellt das Tooltip-Fenster"""
        try:
            self.tooltip = tk.Toplevel()
            self.tooltip.wm_overrideredirect(True)

            # Position berechnen
            x = event.x_root + 10
            y = event.y_root + 10
            self.tooltip.wm_geometry(f"+{x}+{y}")

            label = tk.Label(
                self.tooltip,
                text=text,
                background="#ffffcc",
                relief="solid",
                borderwidth=1,
                font=("Arial", 9),
                padx=5,
                pady=3
            )
            label.pack()

            # Auto-Cleanup nach 5 Sekunden (Sicherheit)
            self.tooltip.after(5000, self.hide_tooltip)

        except tk.TclError:
            # Widget wurde möglicherweise bereits zerstört
            self.tooltip = None

    def hide_tooltip(self):
        """Versteckt und zerstört den Tooltip"""
        # Stoppe Timer falls aktiv
        if self.tooltip_timer:
            try:
                self.container.after_cancel(self.tooltip_timer)
            except:
                pass
            self.tooltip_timer = None

        # Zerstöre Tooltip-Fenster
        if self.tooltip:
            try:
                self.tooltip.destroy()
            except:
                pass
            self.tooltip = None

    def pack(self, **kwargs):
        """Packt den Container"""
        if self.container:
            self.container.pack(**kwargs)

    def set_monitoring_active(self, active):
        """Setzt den Monitoring-Status"""
        self.monitoring_active = active
        self.update_display()

    def set_sd_detected(self, detected):
        """Setzt ob SD-Karte erkannt wurde"""
        self.sd_detected = detected
        self.update_display()

    def set_backup_active(self, active):
        """Setzt den Backup-Status"""
        self.backup_active = active
        if not active:
            # Reset Progress wenn Backup beendet
            self.progress_frame.pack_forget()
        self.update_display()

    def set_clearing_active(self, active):
        """Setzt den Status für SD-Karten Leerung"""
        self.clearing_active = active
        if not active:
            # Reset Progress wenn Leerung beendet
            self.progress_frame.pack_forget()
        self.update_display()

    def show_clearing_progress(self):
        """Zeigt indeterminate Progress-Bar für SD-Karten Leerung"""
        if not self.clearing_active:
            return

        # Wechsel zu indeterminate Mode für Leerung
        self.progress_bar.config(mode='indeterminate')
        self.progress_bar.start(10)

        # Status-Text
        self.progress_label.config(text="SD-Karte wird geleert...")

        # Progress Frame anzeigen
        if not self.progress_frame.winfo_ismapped():
            self.progress_frame.pack(side="left", padx=5)

    def update_backup_progress(self, current_mb, total_mb, speed_mbps):
        """
        Aktualisiert den Backup-Fortschritt

        Args:
            current_mb: Bereits kopierte MB
            total_mb: Gesamt MB
            speed_mbps: Kopiergeschwindigkeit in MB/s
        """
        if not self.backup_active:
            return

        # Progress Bar aktualisieren
        if total_mb > 0:
            progress = (current_mb / total_mb) * 100
            self.progress_bar['value'] = progress

        # Progress Text aktualisieren
        self.progress_label.config(
            text=f"{current_mb:.1f} / {total_mb:.1f} MB ({speed_mbps:.1f} MB/s)"
        )

        # Progress Frame anzeigen
        if not self.progress_frame.winfo_ismapped():
            self.progress_frame.pack(side="left", padx=5)

    def update_display(self):
        """Aktualisiert die Anzeige basierend auf dem aktuellen Status"""
        if not self.monitoring_active:
            # Kein Monitoring aktiv - Container ausblenden
            self.container.pack_forget()
            return

        # Monitoring ist aktiv - Container anzeigen
        if not self.container.winfo_ismapped():
            self.container.pack(side="right", padx=(0, 10))

        # Icon und Text basierend auf Status (Priorität: clearing > backup > detected > normal)
        if self.clearing_active:
            self.icon_label.config(text="🗑️", fg="#f44336")  # Rot für Leerung (Warnung)
            self.status_label.config(text="SD-Karte wird geleert...", fg="#f44336")
            # Stelle sicher dass Progress-Bar im indeterminate mode ist
            self.progress_bar.config(mode='indeterminate')
        elif self.backup_active:
            self.icon_label.config(text="📥", fg="#ff9800")  # Orange für Backup
            self.status_label.config(text="Backup läuft...", fg="#ff9800")
            # Stelle sicher dass Progress-Bar im determinate mode ist
            self.progress_bar.config(mode='determinate')
            self.progress_bar.stop()
        elif self.sd_detected:
            self.icon_label.config(text="💾", fg="#4CAF50")  # Grün für SD erkannt
            self.status_label.config(text="SD-Karte erkannt", fg="#4CAF50")
        else:
            self.icon_label.config(text="💾", fg="#009d8b")  # Normal für Monitoring
            self.status_label.config(text="Überwachung aktiv", fg="#555")

    def hide(self):
        """Versteckt die Anzeige"""
        self.monitoring_active = False
        self.hide_tooltip()  # Cleanup Tooltip
        self.update_display()

