import tkinter as tk
from tkinter import messagebox
import threading
import os
from tkinterdnd2 import TkinterDnD

from .components.form_fields import FormFields
from .components.drag_drop import DragDropFrame
from .components.video_preview import VideoPreview  # Neue Import
from .components.progress_indicator import ProgressHandler
from ..video.processor import VideoProcessor
from ..utils.config import ConfigManager
from ..utils.validation import validate_form_data
from ..installer.ffmpeg_installer import ensure_ffmpeg_installed


class CircularSpinner:
    """Simple rotating arc spinner on a Canvas."""

    def __init__(self, parent, size=80, line_width=8, color="#333", speed=8):
        self.parent = parent
        self.size = size
        self.line_width = line_width
        self.color = color
        self.speed = speed  # degrees per frame
        self.angle = 0
        self._job = None

        self.canvas = tk.Canvas(parent, width=size, height=size, highlightthickness=0, bg='white')
        pad = line_width // 2
        self.arc = self.canvas.create_arc(
            pad, pad, size - pad, size - pad,
            start=self.angle, extent=300, style='arc', width=line_width, outline=self.color
        )

    def pack(self, **kwargs):
        self.canvas.pack(**kwargs)

    def start(self, delay=50):
        if self._job:
            return
        self._animate(delay)

    def _animate(self, delay):
        self.angle = (self.angle + self.speed) % 360
        try:
            self.canvas.itemconfigure(self.arc, start=self.angle)
        except Exception:
            return
        self._job = self.parent.after(delay, lambda: self._animate(delay))

    def stop(self):
        if self._job:
            try:
                self.parent.after_cancel(self._job)
            except Exception:
                pass
            self._job = None


class VideoGeneratorApp:
    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.config = ConfigManager()
        self.video_processor = None
        self.erstellen_button = None
        self.combined_video_path = None

        self.setup_gui()
        self.ensure_dependencies()

    def setup_gui(self):
        self.root.title("Tandemvideo Generator")
        self.root.geometry("600x850")  # Höher für Vorschau
        self.root.config(padx=20, pady=20)

        # Hauptkomponenten erstellen
        self.form_fields = FormFields(self.root, self.config)
        self.drag_drop = DragDropFrame(self.root, self)  # App-Instanz übergeben
        self.video_preview = VideoPreview(self.root)
        self.progress_handler = ProgressHandler(self.root)

        # Erstellen-Button
        self.erstellen_button = tk.Button(
            self.root,
            text="Video mit Intro erstellen",
            font=("Arial", 14, "bold"),
            command=self.erstelle_video,
            bg="#4CAF50",
            fg="white"
        )

        self.pack_components()
        self.load_settings()

    def pack_components(self):
        self.form_fields.pack(pady=10)
        self.drag_drop.pack(fill="x", pady=10, ipady=20)
        self.video_preview.pack(fill="x", pady=10)
        self.erstellen_button.pack(pady=20, ipady=5)
        self.progress_handler.pack_status_label()

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        pass

    def ensure_dependencies(self):
        """Stellt sicher, dass FFmpeg installiert ist"""
        self._start_ffmpeg_installer_overlayed()

    def _create_install_overlay(self):
        """Erstellt Installations-Overlay"""
        overlay = tk.Frame(self.root, bg="#000000")
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()

        def _block_event(e):
            return "break"

        for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>", "<Button>"):
            overlay.bind_all(seq, _block_event)

        container = tk.Frame(overlay, bg='white', bd=2, relief=tk.RIDGE)
        container_width = min(420, int(self.root.winfo_width() * 0.7 or 300))
        container.place(relx=0.5, rely=0.5, anchor='center', width=container_width)

        spinner = CircularSpinner(container, size=80, line_width=8, color="#2E86C1", speed=10)
        spinner.pack(padx=20, pady=(20, 6))

        status_var = tk.StringVar(value="Installing FFmpeg...")
        status_lbl = tk.Label(container, textvariable=status_var, font=("Arial", 10), bg='white',
                              wraplength=container_width - 40)
        status_lbl.pack(padx=20, pady=(0, 20))

        return overlay, spinner, status_var

    def _start_ffmpeg_installer_overlayed(self):
        """Startet FFmpeg-Installation mit Overlay"""
        overlay, spinner, status_var = self._create_install_overlay()
        spinner.start()

        def progress_callback(msg):
            self.root.after(0, status_var.set, msg)

        def finish(success_path=None, error=None):
            try:
                spinner.stop()
            except Exception:
                pass
            for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>",
                        "<Button>"):
                try:
                    overlay.unbind_all(seq)
                except Exception:
                    pass
            try:
                overlay.destroy()
            except Exception:
                pass
            if error:
                self.root.after(0, lambda: messagebox.showerror("FFmpeg installation failed", str(error)))

        def installer_thread():
            try:
                path = ensure_ffmpeg_installed(progress_callback=progress_callback)
                finish(success_path=path)
            except Exception as e:
                finish(error=e)

        t = threading.Thread(target=installer_thread, daemon=True)
        t.start()

    def update_video_preview(self, video_paths):
        """Aktualisiert die Video-Vorschau (wird von DragDrop aufgerufen)"""
        self.video_preview.update_preview(video_paths)

    def erstelle_video(self):
        """Bereitet die Videoerstellung mit Intro vor"""
        # Formulardaten sammeln
        form_data = self.form_fields.get_form_data()

        # Verwende das kombinierte Video aus der Vorschau
        combined_video_path = self.video_preview.get_combined_video_path()
        if not combined_video_path or not os.path.exists(combined_video_path):
            messagebox.showwarning("Fehler", "Bitte erstellen Sie zuerst eine Vorschau durch Drag & Drop von Videos.")
            return

        # Validierung
        errors = validate_form_data(form_data, [combined_video_path])
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
            return

        # Einstellungen speichern
        settings_data = self.form_fields.get_settings_data()
        self.config.save_settings(settings_data)

        # GUI für Verarbeitung vorbereiten
        self.progress_handler.set_status("Status: Füge Intro hinzu... Bitte warten.")
        self._switch_to_cancel_mode()

        # VideoProcessor initialisieren
        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update
        )

        # Videoerstellung im Thread starten
        video_thread = threading.Thread(
            target=self.video_processor.create_video_with_intro_only,
            args=(form_data, combined_video_path)
        )
        video_thread.start()

    def _update_progress(self, step, total_steps=6):
        """Callback für Fortschrittsupdates"""
        self.root.after(0, self.progress_handler.update_progress, step, total_steps)

    def _handle_status_update(self, status_type, message):
        """Callback für Statusupdates"""
        if status_type == "success":
            self.root.after(0, lambda: messagebox.showinfo("Fertig", message))
            self.root.after(0, self.progress_handler.set_status, "Status: Fertig.")
        elif status_type == "error":
            self.root.after(0, lambda: messagebox.showerror("Fehler", message))
            self.root.after(0, self.progress_handler.set_status, "Status: Fehler aufgetreten.")
        elif status_type == "cancelled":
            self.root.after(0, self.progress_handler.set_status, "Status: Erstellung abgebrochen.")

        self.root.after(0, self._switch_to_create_mode)

    def _switch_to_cancel_mode(self):
        """Wechselt den Button zum Abbrechen-Modus"""
        self.erstellen_button.config(
            text="Abbrechen",
            command=self.abbrechen_prozess,
            bg="#D32F2F",
            state="normal"
        )
        self.progress_handler.progress_bar.pack(pady=5)
        self.progress_handler.eta_label.pack(pady=2)
        self.progress_handler.progress_bar['value'] = 0

    def _switch_to_create_mode(self):
        """Wechselt den Button zurück zum Erstellen-Modus"""
        self.erstellen_button.config(
            text="Video mit Intro erstellen",
            command=self.erstelle_video,
            bg="#4CAF50",
            state="normal"
        )
        self.progress_handler.reset()

    def abbrechen_prozess(self):
        """Bricht die laufende Videoerstellung ab"""
        self.progress_handler.set_status("Status: Abbruch wird eingeleitet...")
        self.erstellen_button.config(state="disabled")

        if self.video_processor:
            self.video_processor.cancel_process()

    def run(self):
        """Startet die Hauptloop der Anwendung"""
        self.root.mainloop()