import tkinter as tk
from tkinter import messagebox
import threading
from tkinterdnd2 import TkinterDnD

from .components.form_fields import FormFields
from .components.drag_drop import DragDropFrame
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

        self.setup_gui()
        self.ensure_dependencies()

    def setup_gui(self):
        self.root.title("Tandemvideo Generator")
        self.root.geometry("600x750")
        self.root.config(padx=20, pady=20)

        # Hauptkomponenten erstellen
        self.form_fields = FormFields(self.root, self.config)
        self.drag_drop = DragDropFrame(self.root)
        self.progress_handler = ProgressHandler(self.root)

        # Erstellen-Button
        self.erstellen_button = tk.Button(
            self.root,
            text="Video Erstellen",
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
        self.erstellen_button.pack(pady=20, ipady=5)
        self.progress_handler.pack_status_label()

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        pass  # Wird bereits in FormFields behandelt

    def ensure_dependencies(self):
        """Stellt sicher, dass FFmpeg installiert ist"""
        self._start_ffmpeg_installer_overlayed()

    def _create_install_overlay(self):
        """
        Create and return an in-window modal overlay (Frame), a circular spinner instance and a status StringVar.
        The overlay covers the entire root window and prevents interaction with underlying widgets.
        """
        overlay = tk.Frame(self.root, bg="#000000")
        # place to cover whole window
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()

        # Intercept mouse and keyboard events so underlying widgets can't be used
        def _block_event(e):
            return "break"

        # common events to block
        for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>", "<Button>"):
            overlay.bind_all(seq, _block_event)

        # semi-opaque effect by a slightly transparent-like color is not natively supported for Frames;
        # use a darker color but keep the spinner container white for contrast
        overlay.configure(bg="#000000")  # dark background
        overlay.attributes = getattr(overlay, "attributes", None)  # no-op for safety

        container = tk.Frame(overlay, bg='white', bd=2, relief=tk.RIDGE)
        container_width = min(420, int(self.root.winfo_width() * 0.7 or 300))
        container.place(relx=0.5, rely=0.5, anchor='center', width=container_width)

        # Spinner (circular)
        spinner = CircularSpinner(container, size=80, line_width=8, color="#2E86C1", speed=10)
        spinner.pack(padx=20, pady=(20, 6))

        status_var = tk.StringVar(value="Installing FFmpeg...")
        status_lbl = tk.Label(container, textvariable=status_var, font=("Arial", 10), bg='white',
                              wraplength=container_width - 40)
        status_lbl.pack(padx=20, pady=(0, 20))

        return overlay, spinner, status_var

    def _start_ffmpeg_installer_overlayed(self):
        """Show in-window overlay and run ensure_ffmpeg_installed in a background thread."""

        overlay, spinner, status_var = self._create_install_overlay()
        spinner.start()

        def progress_callback(msg):
            self.root.after(0, status_var.set, msg)

        def finish(success_path=None, error=None):
            try:
                spinner.stop()
            except Exception:
                pass
            # unbind the blocking event handlers
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

    def erstelle_video(self):
        """Bereitet die Videoerstellung vor und startet sie in einem separaten Thread."""
        # Formulardaten sammeln
        form_data = self.form_fields.get_form_data()
        video_path = self.drag_drop.get_video_path()

        # Validierung
        errors = validate_form_data(form_data, video_path)
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
            return

        # Einstellungen speichern
        settings_data = self.form_fields.get_settings_data()
        self.config.save_settings(settings_data)

        # GUI für Verarbeitung vorbereiten
        self.progress_handler.pack_progress_bar()
        self.progress_handler.set_status("Status: Video wird erstellt... Bitte warten.")
        self._switch_to_cancel_mode()

        # VideoProcessor initialisieren
        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update
        )

        # Videoerstellung im Thread starten
        video_thread = threading.Thread(
            target=self.video_processor.create_video,
            args=(form_data, video_path)
        )
        video_thread.start()

    def _update_progress(self, step, total_steps=7):
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
            text="Video Erstellen",
            command=self.erstelle_video,
            bg="#4CAF50",
            state="normal"
        )
        self.progress_handler.reset()
        self.drag_drop.reset()

    def abbrechen_prozess(self):
        """Bricht die laufende Videoerstellung ab"""
        self.progress_handler.set_status("Status: Abbruch wird eingeleitet...")
        self.erstellen_button.config(state="disabled")  # Verhindert mehrfaches Klicken

        if self.video_processor:
            self.video_processor.cancel_process()

    def run(self):
        """Startet die Hauptloop der Anwendung"""
        self.root.mainloop()