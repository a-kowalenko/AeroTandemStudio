import tkinter as tk
from tkinter import messagebox, ttk
import threading
import os
import queue
from typing import List
from tkinterdnd2 import TkinterDnD

from .components.form_fields import FormFields
from .components.drag_drop import DragDropFrame
from .components.video_preview import VideoPreview
from .components.progress_indicator import ProgressHandler
from .components.circular_spinner import CircularSpinner
from .components.settings_dialog import SettingsDialog
from .components.video_player import VideoPlayer
from .components.loading_window import LoadingWindow

from ..video.processor import VideoProcessor
from ..utils.config import ConfigManager
from ..utils.validation import validate_form_data
from ..installer.ffmpeg_installer import ensure_ffmpeg_installed
from ..utils.file_utils import test_server_connection
from ..installer.updater import initialize_updater
from ..utils.constants import APP_VERSION


class VideoGeneratorApp:

    def __init__(self):
        self.root = TkinterDnD.Tk()
        self.config = ConfigManager()
        self.video_processor = None
        self.erstellen_button = None
        self.combined_video_path = None
        self.server_status_label = None
        self.server_connected = False
        self.video_player = None
        self.APP_VERSION = APP_VERSION

        # Für Threading und Ladefenster ---
        self.analysis_queue = None
        self.loading_window = None

        # Speichern der Button-Originalzustände
        self.old_button_text = ""
        self.old_button_bg = ""
        self.old_button_cursor = ""

        self.setup_gui()
        self.ensure_dependencies()

    def setup_gui(self):
        self.root.title("Aero Tandem Studio")
        self.root.geometry("1400x800")
        self.root.config(padx=20, pady=0)

        # Header mit Titel und Settings-Button
        self.create_header()

        # Haupt-Container mit zwei Spalten
        self.main_container = tk.Frame(self.root)
        self.main_container.pack(fill="both", expand=True)

        # Linke Spalte für Formular und Drag & Drop
        self.left_frame = tk.Frame(self.main_container, width=600)
        self.left_frame.pack(side="left", fill="both", expand=True, padx=(0, 20))

        # Rechte Spalte für Vorschau und Button
        self.right_frame = tk.Frame(self.main_container, width=350)
        self.right_frame.pack(side="right", fill="y", padx=(20, 0))

        # Linke Spalte: Formular und Drag & Drop
        self.form_fields = FormFields(self.left_frame, self.config)
        self.drag_drop = DragDropFrame(self.left_frame, self)

        # Rechte Spalte: Vorschau, Checkbox und Button
        # Titel
        self.title_label = tk.Label(self.right_frame, text="Video Vorschau", font=("Arial", 14, "bold"))

        # Separator
        self.preview_separator = ttk.Separator(self.right_frame, orient='horizontal')

        self.video_player = VideoPlayer(self.right_frame, self)
        self.video_preview = VideoPreview(self.right_frame, self)

        # Server-Upload Frame mit Status-Anzeige
        self.upload_frame = tk.Frame(self.right_frame)

        # Checkbox für Server-Upload
        self.upload_to_server_var = tk.BooleanVar()
        self.upload_checkbox = tk.Checkbutton(
            self.upload_frame,
            text="Auf Server laden",
            variable=self.upload_to_server_var,
            font=("Arial", 12),
            command=self.on_upload_checkbox_toggle
        )
        self.upload_checkbox.pack(side="left", padx=(0, 10))

        # Server Status Label
        self.server_status_label = tk.Label(
            self.upload_frame,
            text="Prüfe...",
            font=("Arial", 10, "bold"),
            fg="orange"
        )
        self.server_status_label.pack(side="left")

        # Erstellen-Button
        self.erstellen_button = tk.Button(
            self.right_frame,
            text="Erstellen",
            font=("Arial", 14, "bold"),
            command=self.erstelle_video,
            bg="#4CAF50",
            fg="white",
            width=20,
            height=2
        )

        # Progress Handler (unten über beiden Spalten)
        self.progress_handler = ProgressHandler(self.root, self.upload_frame)

        self.pack_components()
        self.load_settings()

        # Server-Verbindung testen (im Hintergrund)
        self.test_server_connection_async()

    def create_header(self):
        """Erstellt den Header mit Titel, Logo und Settings-Button"""
        header_frame = tk.Frame(self.root)
        header_frame.pack(fill="x")

        # Logo links neben dem Titel (80x80)
        img_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "assets", "logo.png"))
        self.logo_image = None
        if os.path.exists(img_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(img_path).convert("RGBA")
                img = img.resize((60, 60), Image.LANCZOS)
                self.logo_image = ImageTk.PhotoImage(img)
            except Exception:
                try:
                    self.logo_image = tk.PhotoImage(file=img_path)
                except Exception:
                    self.logo_image = None

        if self.logo_image:
            logo_label = tk.Label(header_frame, image=self.logo_image, bd=0)
            logo_label.pack(side="left", padx=(0, 10))

        # Titel
        title_label = tk.Label(
            header_frame,
            text="Aero Tandem Studio",
            font=("Arial", 18, "bold"),
            fg="#009d8b"
        )
        title_label.pack(side="left")

        # Settings-Button (rechts)
        self.settings_button = tk.Button(
            header_frame,
            text="⚙",  # Gear Icon
            font=("Arial", 18),
            command=self.show_settings,
            bg="#f0f0f0",
            relief="flat",
            width=3,
        )
        self.settings_button.pack(side="right")

        # Tooltip für Settings-Button
        self.create_tooltip(self.settings_button, "Einstellungen öffnen")

    def create_tooltip(self, widget, text):
        """Erstellt einen Tooltip für ein Widget"""

        def on_enter(event):
            tooltip = tk.Toplevel()
            tooltip.wm_overrideredirect(True)
            tooltip.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

            label = tk.Label(tooltip, text=text, background="yellow", relief="solid", borderwidth=1)
            label.pack()

            widget.tooltip = tooltip

        def on_leave(event):
            if hasattr(widget, 'tooltip'):
                widget.tooltip.destroy()

        widget.bind("<Enter>", on_enter)
        widget.bind("<Leave>", on_leave)

    def show_settings(self):
        """Zeigt den Einstellungs-Dialog"""
        SettingsDialog(self.root, self.config).show()
        # Nach Schließen des Dialogs Verbindung erneut testen
        self.root.after(1000, self.test_server_connection_async)

    def pack_components(self):
        # Linke Spalte
        self.form_fields.pack(pady=10, fill="x")
        self.drag_drop.pack(fill="both", expand=True, pady=10)

        # Rechte Spalte
        self.title_label.pack(pady=0)
        self.preview_separator.pack(fill='x', pady=5)
        self.video_player.pack(fill="x", pady=(0, 10), side="top")
        self.video_preview.pack(fill="x", pady=(0, 8), side="top")

        # Spacer to push the following right-column elements slightly down
        self.right_spacer = tk.Frame(self.right_frame, bg=self.right_frame.cget("bg"))
        self.right_spacer.pack(fill="x", expand=True)

        self.upload_frame.pack(pady=10, fill="x", side="top")
        self.erstellen_button.pack(pady=10, fill="x", side="top")

        # Progress unten
        self.progress_handler.pack_status_label()

    def load_settings(self):
        """Lädt die gespeicherten Einstellungen"""
        try:
            settings = self.config.get_settings()
            self.upload_to_server_var.set(settings.get("upload_to_server", False))
        except:
            self.upload_to_server_var.set(False)

    def test_server_connection_async(self):
        """Testet die Server-Verbindung asynchron"""
        self.server_status_label.config(text="Prüfe...", fg="orange")

        def test_connection():
            success, message = test_server_connection(self.config)
            self.root.after(0, self.update_server_status, success, message)

        thread = threading.Thread(target=test_connection, daemon=True)
        thread.start()

    def update_server_status(self, connected, message):
        """Aktualisiert den Server-Status in der GUI"""
        self.server_connected = connected

        if connected:
            self.server_status_label.config(text="✓ Verbunden", fg="green")
            # Tooltip für erfolgreiche Verbindung
            self.create_tooltip(self.server_status_label, f"Server erreichbar\n{message}")
        else:
            self.server_status_label.config(text="✗ Getrennt", fg="red")
            # Tooltip für Fehler
            self.create_tooltip(self.server_status_label, f"Server nicht erreichbar\n{message}")

            # Deaktiviere Upload-Checkbox falls nicht verbunden
            if self.upload_to_server_var.get():
                self.upload_to_server_var.set(False)
                messagebox.showwarning(
                    "Server nicht erreichbar",
                    f"Server-Verbindung fehlgeschlagen:\n{message}\n\n"
                    "Upload wurde deaktiviert. Bitte überprüfen Sie die Einstellungen."
                )

    def on_upload_checkbox_toggle(self):
        """Wird aufgerufen wenn die Upload-Checkbox geändert wird"""
        if self.upload_to_server_var.get() and not self.server_connected:
            # Wenn Upload aktiviert aber nicht verbunden, zeige Warnung und deaktiviere
            self.upload_to_server_var.set(False)
            messagebox.showwarning(
                "Server nicht erreichbar",
                "Kann nicht auf Server uploaden - keine Verbindung verfügbar.\n\n"
                "Bitte überprüfen Sie:\n"
                "• Server-Einstellungen (⚙)\n"
                "• Netzwerkverbindung\n"
                "• Server-Erreichbarkeit"
            )
            # Starte erneuten Verbindungstest
            self.test_server_connection_async()

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

    def _save_button_state(self):
        """Speichert den aktuellen Zustand des Buttons."""
        self.old_button_text = self.erstellen_button.cget("text")
        self.old_button_bg = self.erstellen_button.cget("bg")
        try:
            self.old_button_cursor = self.erstellen_button.cget("cursor")
        except tk.TclError:
            self.old_button_cursor = ""  # Standard-Cursor

    def _set_button_waiting(self):
        """Setzt den Button in den Wartezustand."""
        self.erstellen_button.config(text="Bitte warten...", bg="#9E9E9E", state="disabled", cursor="watch")

    def _restore_button_state(self):
        """Stellt den ursprünglichen Zustand des Buttons wieder her."""
        # Nur wiederherstellen, wenn der Button nicht im "Abbrechen"-Modus ist
        if self.erstellen_button.cget("text") == "Bitte warten...":
            if self.old_button_text:  # Nur wiederherstellen, wenn ein Zustand gespeichert wurde
                self.erstellen_button.config(text=self.old_button_text,
                                             bg=self.old_button_bg,
                                             state="normal",
                                             cursor=self.old_button_cursor)
            else:
                # Fallback, falls kein Zustand gespeichert wurde
                self.erstellen_button.config(text="Erstellen",
                                             bg="#4CAF50",
                                             state="normal",
                                             cursor="")

    def update_video_preview(self, video_paths: List[str]):
        """
        Aktualisiert die Video-Vorschau. Startet die QR-Analyse in einem
        separaten Thread und zeigt ein Ladefenster an.
        (Diese Methode ersetzt die alte, blockierende Version)
        """
        if not video_paths:
            return

        # 1. Button-Zustand speichern und auf "Warten" setzen
        self._save_button_state()
        self._set_button_waiting()

        # 2. Ladefenster anzeigen (verwendet jetzt die importierte Klasse)
        # self.root ist das Hauptfenster (master)
        self.loading_window = LoadingWindow(self.root, text="Analysiere QR-Code im Video...")

        # 3. Eine Queue erstellen, um das Ergebnis vom Thread zu empfangen
        self.analysis_queue = queue.Queue()

        # 4. Den Analyse-Thread starten
        analysis_thread = threading.Thread(
            target=self._run_analysis_thread,
            args=(video_paths[0], self.analysis_queue),
            daemon=True  # Thread stirbt, wenn die Hauptanwendung schließt
        )
        analysis_thread.start()

        # 5. Eine "Polling"-Funktion starten, die auf das Ergebnis wartet
        self.root.after(100, self._check_analysis_result, video_paths)

    def _run_analysis_thread(self, video_path: str, result_queue: queue.Queue):
        """
        Diese Funktion läuft im separaten Thread.
        Sie führt die blockierende Analyse aus und legt das Ergebnis in die Queue.
        """
        try:
            # WICHTIG: Der Import muss hier erfolgen oder threadsicher sein.
            from src.video.qr_analyser import analysiere_ersten_clip

            kunde, qr_scan_success = analysiere_ersten_clip(video_path)

            # Legen Sie das Ergebnis in die Queue
            result_queue.put(("success", (kunde, qr_scan_success)))

        except Exception as e:
            # Legen Sie im Fehlerfall die Ausnahme in die Queue
            print(f"Fehler im Analyse-Thread: {e}")
            result_queue.put(("error", e))

    def _check_analysis_result(self, video_paths: List[str]):
        """
        Überprüft alle 100ms, ob ein Ergebnis in der Queue liegt.
        Diese Funktion läuft im Haupt-Thread und kann die GUI sicher aktualisieren.
        """
        try:
            # Versuchen, ein Ergebnis zu holen, ohne zu blockieren
            status, result = self.analysis_queue.get_nowait()

            # --- Ergebnis ist da ---

            # 1. Ladefenster schließen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None

            # 2. Ergebnis verarbeiten
            if status == "success":
                kunde, qr_scan_success = result
                self._process_analysis_result(kunde, qr_scan_success, video_paths)
            elif status == "error":
                messagebox.showerror("Analyse-Fehler",
                                     f"Ein unerwarteter Fehler bei der Videoanalyse ist aufgetreten:\n{result}")
                self._restore_button_state()  # Button auch bei Fehler zurücksetzen

        except queue.Empty:
            # Wenn die Queue leer ist, erneut in 100ms prüfen
            self.root.after(100, self._check_analysis_result, video_paths)

        except Exception as e:
            # Allgemeiner Fehler beim Abrufen (sollte nicht passieren)
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None
            messagebox.showerror("Fehler", f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}")
            self._restore_button_state()  # Button auf jeden Fall zurücksetzen

    def _process_analysis_result(self, kunde, qr_scan_success, video_paths):
        """
        Verarbeitet das erfolgreiche Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code gescannt: Kunde ID {kunde.kunde_id}, Email: {kunde.email}, Telefon: {kunde.telefon}, "
                      f"Foto: {kunde.foto}, Video: {kunde.video}")

                info_text = (
                    f"Kunde erkannt:\n\n"
                    f"ID: {kunde.kunde_id}\n"
                    f"Name: {kunde.vorname} {kunde.nachname}\n"
                    f"Email: {kunde.email}\n"
                    f"Telefon: {kunde.telefon}\n"
                    f"Foto: {'Ja' if kunde.foto else 'Nein'}\n"
                    f"Video: {'Ja' if kunde.video else 'Nein'}\n\n"
                    f"Möchten Sie fortfahren?"
                )
                messagebox.showinfo("Kunde erkannt", info_text)

            elif qr_scan_success and not kunde:
                messagebox.showwarning("Ungültiger QR-Code", "Ein QR-Code wurde erkannt, aber die Daten sind ungültig.")

            else:
                messagebox.showinfo("Kein QR-Code", "Kein QR-Code im ersten Video gefunden.")

            # Starten Sie die Aktualisierung der GUI-Vorschau

            update_preview_thread = self.video_preview.update_preview(video_paths, kunde)

            if update_preview_thread and isinstance(update_preview_thread, threading.Thread):
                def enable_button_when_done():
                    update_preview_thread.join()
                    # Stellen Sie sicher, dass die GUI-Änderung im Hauptthread erfolgt
                    self.root.after(0, self._restore_button_state)

                threading.Thread(target=enable_button_when_done, daemon=True).start()
            else:
                # Wenn update_preview nicht blockiert oder keinen Thread zurückgibt
                self._restore_button_state()

        except Exception as e:
            print(f"Fehler in _process_analysis_result: {e}")
            # Stellen Sie sicher, dass der Button auch bei einem Fehler hier wiederhergestellt wird
            self._restore_button_state()

    def erstelle_video(self):
        """Bereitet die Videoerstellung mit Intro vor"""
        # Formulardaten sammeln
        form_data = self.form_fields.get_form_data()

        # Server-Upload Einstellung hinzufügen
        form_data["upload_to_server"] = self.upload_to_server_var.get()

        # Prüfe Server-Verbindung wenn Upload aktiviert
        if form_data["upload_to_server"] and not self.server_connected:
            messagebox.showwarning(
                "Server nicht erreichbar",
                "Server-Upload ist aktiviert, aber keine Verbindung zum Server verfügbar.\n\n"
                "Bitte überprüfen Sie die Server-Einstellungen oder deaktivieren Sie den Upload."
            )
            return

        # Verwende das kombinierte Video aus der Vorschau
        combined_video_path = self.video_preview.get_combined_video_path()
        kunde = self.video_preview.get_kunde()
        if kunde:
            print(f"Verwende Kunde ID {kunde.kunde_id} für die Videoerstellung.")

        if not combined_video_path or not os.path.exists(combined_video_path):
            messagebox.showwarning("Fehler",
                                   "Bitte erstellen Sie zuerst eine Vorschau durch Drag & Drop von Videos oder klicken Sie auf 'Erneut versuchen'.")
            return

        # Foto-Pfade holen
        photo_paths = self.drag_drop.get_photo_paths()

        # Validierung
        errors = validate_form_data(form_data, [combined_video_path])
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
            return

        # Einstellungen speichern
        settings_data = self.form_fields.get_settings_data()
        settings_data["upload_to_server"] = form_data["upload_to_server"]  # Hinzufügen
        self.config.save_settings(settings_data)

        # GUI für Verarbeitung vorbereiten
        video_count = len(self.drag_drop.get_video_paths())
        photo_count = len(photo_paths)
        status_text = f"Status: Verarbeite {video_count} Video(s)"
        if photo_count > 0:
            status_text += f" und kopiere {photo_count} Foto(s)"

        # Server-Upload Info hinzufügen
        if form_data["upload_to_server"]:
            status_text += " - Lade auf Server hoch"

        status_text += "... Bitte warten."

        self.progress_handler.set_status(status_text)
        self._switch_to_cancel_mode()

        # VideoProcessor initialisieren
        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update
        )

        # Videoerstellung im Thread starten
        video_thread = threading.Thread(
            target=self.video_processor.create_video_with_intro_only,
            args=(form_data, combined_video_path, photo_paths, kunde)
        )
        video_thread.start()

    def _update_progress(self, step, total_steps=8):
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
        elif status_type == "update":
            self.root.after(0, self.progress_handler.set_status, f"Status: {message}.")
            return

        self.root.after(0, self._switch_to_create_mode)

    def _switch_to_cancel_mode(self):
        """Wechselt den Button zum Abbrechen-Modus"""
        self.erstellen_button.config(
            text="Abbrechen",
            command=self.abbrechen_prozess,
            bg="#D32F2F",
            state="normal"
        )
        self.progress_handler.progress_bar.pack(side="right", padx=(0, 5), pady=5)
        self.progress_handler.eta_label.pack(side="right", pady=5)

        self.progress_handler.progress_bar['value'] = 0

    def _switch_to_create_mode(self):
        """Wechselt den Button zurück zum Erstellen-Modus"""
        self.erstellen_button.config(
            text="Erstellen",
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

        try:
            initialize_updater(self.root, self.APP_VERSION)
        except Exception as e:
            # Ein Fehler im Updater sollte den Start der App nicht verhindern
            print(f"Fehler beim Initialisieren des Updaters: {e}")
        # <<< ENDE NEU 3/3 >>>

        self.root.mainloop()

