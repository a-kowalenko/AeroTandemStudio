﻿import tkinter as tk
from tkinter import messagebox, ttk
import threading
import os
import queue
import uuid  # NEU
from typing import List
from tkinterdnd2 import TkinterDnD

from .components.form_fields import FormFields
from .components.drag_drop import DragDropFrame
from .components.video_preview import VideoPreview
from .components.photo_preview import PhotoPreview
from .components.progress_indicator import ProgressHandler
from .components.circular_spinner import CircularSpinner
from .components.settings_dialog import SettingsDialog
from .components.video_player import VideoPlayer
from .components.video_cutter import VideoCutterDialog  # Importiert
from .components.loading_window import LoadingWindow
from .components.sd_status_indicator import SDStatusIndicator
from ..model.kunde import Kunde

from ..video.processor import VideoProcessor
from ..utils.config import ConfigManager
from ..utils.validation import validate_form_data
from ..utils.sd_card_monitor import SDCardMonitor
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
        self.video_cutter_dialog = None  # NEU: Referenz auf offenen Dialog
        self.APP_VERSION = APP_VERSION

        # Preview Tab-Elemente
        # self.title_label = None
        # self.preview_separator = None
        self.preview_notebook = None
        self.video_tab = None
        self.foto_tab = None

        # Für Threading und Ladefenster ---
        self.analysis_queue = None
        self.loading_window = None

        # SD-Karten Monitor
        self.sd_card_monitor = None
        self.sd_status_indicator = None

        # Speichern der Button-Originalzustände
        self.old_button_text = ""
        self.old_button_bg = ""
        self.old_button_cursor = ""

        self.setup_gui()
        self.ensure_dependencies()
        self.initialize_sd_card_monitor()

        # NEU: Schließ-Ereignis abfangen
        self.root.protocol("WM_DELETE_WINDOW", self.on_app_close)

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
        self.form_fields = FormFields(self.left_frame, self.config, self)
        self.drag_drop = DragDropFrame(self.left_frame, self)

        # Rechte Spalte: Tab-View für Vorschau-Inhalte
        # Tab-View erstellen mit gleichem Style wie Drag-and-Drop
        style = ttk.Style()
        style.configure('Preview.TNotebook.Tab',
                       font=('Arial', 8, 'bold'),
                       padding=[20, 5])  # [horizontal, vertical] padding

        self.preview_notebook = ttk.Notebook(self.right_frame, style='Preview.TNotebook')

        # Tab für Video Vorschau
        self.video_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.video_tab, text="Video Vorschau")

        # Tab für Foto Vorschau
        self.foto_tab = ttk.Frame(self.preview_notebook)
        self.preview_notebook.add(self.foto_tab, text="Foto Vorschau")

        # Video-Tab Inhalt
        # Titel im Video-Tab
        # self.title_label = tk.Label(self.video_tab, text="Video Vorschau", font=("Arial", 14, "bold"))

        # Separator im Video-Tab
        # self.preview_separator = ttk.Separator(self.video_tab, orient='horizontal')

        # Video Player und Preview im Video-Tab
        self.video_player = VideoPlayer(self.video_tab, self)
        self.video_preview = VideoPreview(self.video_tab, self)

        # Foto-Tab Inhalt
        self.photo_preview = PhotoPreview(self.foto_tab, self)

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
        self.upload_checkbox.pack(side="left", padx=(0, 5))

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

        # SD-Status Indikator (wird rechts vom Titel angezeigt, wenn aktiv)
        self.sd_status_indicator = SDStatusIndicator(header_frame)
        self.sd_status_indicator.create_widgets()
        # Wird später gepackt wenn Monitoring aktiv ist

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

        tooltip_window = None
        tooltip_timer = None

        def show_tooltip(event):
            nonlocal tooltip_window, tooltip_timer

            # Cleanup vorhandener Tooltip
            hide_tooltip()

            # Verzögerte Anzeige (verhindert Flackern)
            def create_window():
                nonlocal tooltip_window
                try:
                    tooltip_window = tk.Toplevel()
                    tooltip_window.wm_overrideredirect(True)
                    tooltip_window.wm_geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

                    label = tk.Label(
                        tooltip_window,
                        text=text,
                        background="#ffffcc",
                        relief="solid",
                        borderwidth=1,
                        padx=5,
                        pady=3
                    )
                    label.pack()

                    # Auto-Cleanup nach 5 Sekunden
                    tooltip_window.after(5000, hide_tooltip)
                except tk.TclError:
                    tooltip_window = None

            tooltip_timer = widget.after(500, create_window)

        def hide_tooltip(event=None):
            nonlocal tooltip_window, tooltip_timer

            # Stoppe Timer
            if tooltip_timer:
                try:
                    widget.after_cancel(tooltip_timer)
                except:
                    pass
                tooltip_timer = None

            # Zerstöre Fenster
            if tooltip_window:
                try:
                    tooltip_window.destroy()
                except:
                    pass
                tooltip_window = None

        widget.bind("<Enter>", show_tooltip)
        widget.bind("<Leave>", hide_tooltip)

    def show_settings(self):
        """Zeigt den Einstellungs-Dialog"""
        SettingsDialog(self.root, self.config, on_settings_saved=self.on_settings_saved).show()

    def on_settings_saved(self):
        """Wird aufgerufen nachdem Settings gespeichert wurden"""
        # Server-Verbindung testen
        self.test_server_connection_async()
        # SD-Monitor sofort neu starten
        self._restart_sd_monitor_if_needed()

    def pack_components(self):
        # Linke Spalte
        self.form_fields.pack(pady=10, fill="x")
        self.drag_drop.pack(fill="both", expand=True, pady=10)

        # Rechte Spalte
        # Tab-View packen
        self.preview_notebook.pack(fill="both", expand=True, pady=(0, 10))

        # Video-Tab Inhalt packen
        # self.title_label.pack(pady=0)
        # self.preview_separator.pack(fill='x', pady=5)
        self.video_player.pack(fill="x", pady=(0, 10), side="top")
        self.video_preview.pack(fill="x", pady=(0, 8), side="top")

        # Foto-Tab Inhalt packen
        self.photo_preview.pack(fill="both", expand=True, padx=5, pady=5)

        # Upload-Frame und Button bleiben außerhalb der Tabs
        self.upload_frame.pack(pady=0, fill="x", side="top")
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
        current_text = self.erstellen_button.cget("text")

        # Speichere nur gültige Button-Zustände (nicht "Bitte warten..." oder "Abbrechen")
        # Wenn der Button bereits in einem temporären Zustand ist, behalte den gespeicherten Wert
        if current_text not in ("Bitte warten...", "Abbrechen"):
            self.old_button_text = current_text
            self.old_button_bg = self.erstellen_button.cget("bg")
            try:
                self.old_button_cursor = self.erstellen_button.cget("cursor")
            except tk.TclError:
                self.old_button_cursor = ""  # Standard-Cursor
        # Sonst: Behalte die vorher gespeicherten Werte
        # Falls keine gespeichert wurden, setze Default-Werte
        elif not hasattr(self, 'old_button_text') or not self.old_button_text:
            self.old_button_text = "Erstellen"
            self.old_button_bg = "#4CAF50"
            self.old_button_cursor = ""

    def _set_button_waiting(self):
        """Setzt den Button in den Wartezustand."""
        self.erstellen_button.config(text="Bitte warten...", bg="#9E9E9E", state="disabled", cursor="watch")

    def _restore_button_state(self):
        """Stellt den ursprünglichen Zustand des Buttons wieder her."""
        # Nur wiederherstellen, wenn der Button nicht im "Abbrechen"-Modus ist
        current_text = self.erstellen_button.cget("text")
        if current_text == "Bitte warten..." or current_text == "Erstellen":
            if self.old_button_text and self.old_button_text != "Abbrechen":  # Nur wiederherstellen, wenn ein gültiger Zustand gespeichert wurde
                self.erstellen_button.config(text=self.old_button_text,
                                             bg=self.old_button_bg,
                                             state="normal",
                                             cursor=self.old_button_cursor)
            else:
                # Fallback, falls kein Zustand gespeichert wurde oder "Abbrechen" gespeichert war
                self.erstellen_button.config(text="Erstellen",
                                             bg="#4CAF50",
                                             state="normal",
                                             cursor="")
        # Wenn der Button "Abbrechen" anzeigt, ändere nichts

    def update_video_preview(self, video_paths: List[str], run_qr_check: bool = True):
        """
        Aktualisiert die Video-Vorschau. Startet die QR-Analyse in einem
        separaten Thread oder setzt das Formular zurück, wenn keine Videos vorhanden sind.
        NEU: run_qr_check steuert, ob die QR-Analyse durchgeführt werden soll.
        """
        if not video_paths:
            # --- NEU: Anforderung des Users umsetzen ---
            # Wenn alle Videos gelöscht wurden, setze das Formular
            # auf den manuellen Modus zurück.
            print("Keine Videos gefunden, setze Formular auf manuell zurück.")
            self.form_fields.update_form_layout(qr_success=False, kunde=None)

            # Auch Vorschau und Player leeren
            try:
                if self.video_preview:
                    self.video_preview.clear_preview()
            except AttributeError:
                print("Hinweis: video_preview hat keine 'clear_preview' Methode.")
            except Exception as e:
                print(f"Fehler beim Leeren der Vorschau: {e}")

            try:
                if self.video_player:
                    self.video_player.unload_video()
            except AttributeError:
                print("Hinweis: video_player hat keine 'unload_video' Methode.")
            except Exception as e:
                print(f"Fehler beim Entladen des Players: {e}")

            # Button-Status wiederherstellen - WICHTIG: Setze Button explizit auf "Erstellen"
            # um sicherzustellen dass er nicht im "Bitte warten"-Zustand hängen bleibt
            print("Stelle Button-Status nach Video-Löschung wieder her")
            self.erstellen_button.config(
                text="Erstellen",
                bg="#4CAF50",
                state="normal",
                cursor=""
            )
            # Speichere den korrekten Status für zukünftige Wiederherstellungen
            self.old_button_text = "Erstellen"
            self.old_button_bg = "#4CAF50"
            self.old_button_cursor = ""

            return
            # --- ENDE NEU ---

        # NEU: QR-Prüfung nur starten, wenn run_qr_check True ist
        if run_qr_check:
            # 1. Button-Zustand speichern und auf "Warten" setzen
            self.run_qr_analysis(video_paths)
        else:
            # Keine QR-Prüfung, nur Vorschau aktualisieren
            print("QR-Prüfung übersprungen - erster Clip hat sich nicht geändert.")
            if self.video_preview:
                self.video_preview.update_preview(video_paths)

    def run_qr_analysis(self, video_paths: list[str]):
        self._save_button_state()
        self._set_button_waiting()

        # 2. Ladefenster anzeigen (verwendet jetzt die importierte Klasse)
        self.loading_window = LoadingWindow(self.root, text="Analysiere QR-Code im Video...")

        # 3. Eine Queue erstellen, um das Ergebnis vom Thread zu empfangen
        self.analysis_queue = queue.Queue()

        # 4. Den Analyse-Thread starten
        analysis_thread = threading.Thread(
            target=self._run_analysis_thread,
            args=(video_paths[0], self.analysis_queue),
            daemon=True
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
            from src.video.qr_analyser import analysiere_ersten_clip

            kunde, qr_scan_success = analysiere_ersten_clip(video_path)
            result_queue.put(("success", (kunde, qr_scan_success)))

        except Exception as e:
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
                self._restore_button_state()
                self.form_fields.update_form_layout(False, None)


        except queue.Empty:
            # Wenn die Queue leer ist, erneut in 100ms prüfen
            self.root.after(100, self._check_analysis_result, video_paths)

        except Exception as e:
            # Allgemeiner Fehler beim Abrufen
            if self.loading_window:
                self.loading_window.destroy()
                self.loading_window = None
            messagebox.showerror("Fehler", f"Ein Fehler beim Verarbeiten des Ergebnisses ist aufgetreten: {e}")
            self._restore_button_state()
            self.form_fields.update_form_layout(False, None)

    def _process_analysis_result(self, kunde, qr_scan_success, video_paths):
        """
        Verarbeitet das erfolgreiche Analyseergebnis (im Haupt-Thread).
        """
        try:
            if qr_scan_success and kunde:
                print(f"QR-Code gescannt: Kunde ID {kunde.kunde_id}, Email: {kunde.email}, Telefon: {kunde.telefon}, "
                      f"Handcam Foto: {kunde.handcam_foto}, Handcam Video: {kunde.handcam_video}, "
                      f"Outside Foto: {kunde.outside_foto}, Outside Video: {kunde.outside_video}")

                info_text = (
                    f"Kunde erkannt:\n\n"
                    f"ID: {kunde.kunde_id}\n"
                    f"Name: {kunde.vorname} {kunde.nachname}\n"
                    f"Email: {kunde.email}\n"
                    f"Telefon: {kunde.telefon}\n"
                    f"Handcam Foto: {'Ja' if kunde.handcam_foto else 'Nein'}\n"
                    f"Handcam Video: {'Ja' if kunde.handcam_video else 'Nein'}\n"
                    f"Outside Foto: {'Ja' if kunde.outside_foto else 'Nein'}\n"
                    f"Outside Video: {'Ja' if kunde.outside_video else 'Nein'}\n"
                    f"Möchten Sie fortfahren?"
                )
                # Dialog entfernt - QR-Code wurde gefunden und wird automatisch verarbeitet
                print(f"QR-Code erfolgreich gescannt: {kunde.vorname} {kunde.nachname}")

            elif qr_scan_success and not kunde:
                messagebox.showwarning("Ungültiger QR-Code", "Ein QR-Code wurde erkannt, aber die Daten sind ungültig.")

            else:
                # Dialog entfernt - Wechsel zu manueller Eingabe erfolgt automatisch
                print("Kein QR-Code im ersten Video gefunden. Wechsle zu manueller Eingabe.")

            # Formular-Layout aktualisieren
            self.form_fields.update_form_layout(qr_scan_success, kunde)

            # Starten Sie die Aktualisierung der GUI-Vorschau
            # update_preview startet einen Thread (_create_combined_preview)
            # self.video_preview.update_preview(video_paths)

            # WICHTIG: _create_combined_preview (im Thread) ruft _finalize_processing auf.
            # Wir müssen den Button dort wiederherstellen, NICHT hier.
            # _finalize_processing ruft _restore_button_state auf, wenn es fertig ist.

            # Warten, bis der Thread in update_preview fertig ist, um den Button wiederherzustellen
            def wait_for_preview_thread():
                if self.video_preview.processing_thread:
                    self.video_preview.processing_thread.join()  # Warte auf den Thread (Vorschau-Erstellung)

                # Jetzt im Haupt-Thread den Button wiederherstellen
                self.root.after(0, self._restore_button_state)

            threading.Thread(target=wait_for_preview_thread, daemon=True).start()


        except Exception as e:
            print(f"Fehler in _process_analysis_result: {e}")
            self._restore_button_state()
            self.form_fields.update_form_layout(False, None)

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
        # Foto-Pfade holen
        photo_paths = self.drag_drop.get_photo_paths()

        # Physische Anwesenheit von Dateien prüfen
        has_video = combined_video_path and os.path.exists(combined_video_path)
        has_photos = photo_paths and len(photo_paths) > 0

        # Ausgewählte Produkte aus form_data holen
        video_produkt_gewaehlt = form_data.get("handcam_video", False) or form_data.get("outside_video", False)
        foto_produkt_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)

        # Prüfen ob Video gewählt aber nicht bezahlt ist
        video_gewaehlt_aber_nicht_bezahlt = (
                (form_data.get("handcam_video", False) and not form_data.get("ist_bezahlt_handcam_video", False)) or
                (form_data.get("outside_video", False) and not form_data.get("ist_bezahlt_outside_video", False))
        )

        # 1. Prüfen, ob überhaupt ein Produkt ausgewählt ist.
        if not video_produkt_gewaehlt and not foto_produkt_gewaehlt:
            messagebox.showwarning("Fehler",
                                   "Bitte wählen Sie mindestens ein Produkt aus\n"
                                   "(Handcam Foto/Video oder Outside Foto/Video).")
            return

        # 2. Prüfen auf Diskrepanz: Produkt ausgewählt, aber keine Datei da
        error_messages = []
        if video_produkt_gewaehlt and not has_video:
            error_messages.append("Sie haben ein Video-Produkt ausgewählt, aber keine Videos hinzugefügt.")

        if foto_produkt_gewaehlt and not has_photos:
            error_messages.append("Sie haben ein Foto-Produkt ausgewählt, aber keine Fotos hinzugefügt.")

        # Zeige Fehler, wenn Produkt ausgewählt, aber Datei fehlt
        if error_messages:
            messagebox.showwarning("Fehlende Dateien", "\n\n".join(error_messages))
            return

        # Parse Kundendaten aus der Formular-Eingabe
        kunde_id_val = form_data.get("kunde_id")
        kunde = Kunde(
            kunde_id=int(kunde_id_val) if kunde_id_val and kunde_id_val.isdigit() else 0,
            vorname=str(form_data["vorname"]),
            nachname=str(form_data["nachname"]),
            email=str(form_data["email"]),
            telefon=str(form_data["telefon"]),
            handcam_foto=bool(form_data["handcam_foto"]),
            handcam_video=bool(form_data["handcam_video"]),
            outside_foto=bool(form_data["outside_foto"]),
            outside_video=bool(form_data["outside_video"]),
            ist_bezahlt_handcam_foto=bool(form_data["ist_bezahlt_handcam_foto"]),
            ist_bezahlt_handcam_video=bool(form_data["ist_bezahlt_handcam_video"]),
            ist_bezahlt_outside_foto=bool(form_data["ist_bezahlt_outside_foto"]),
            ist_bezahlt_outside_video=bool(form_data["ist_bezahlt_outside_video"])
        )

        # Validierung der Formulardaten (Textfelder)
        errors = validate_form_data(form_data, (video_produkt_gewaehlt or foto_produkt_gewaehlt))
        if errors:
            messagebox.showwarning("Fehlende Eingabe", "\n".join(errors))
            return

        # Einstellungen speichern
        settings_data = self.form_fields.get_settings_data()
        settings_data["upload_to_server"] = form_data["upload_to_server"]
        self.config.save_settings(settings_data)

        # GUI für Verarbeitung vorbereiten
        video_count = len(self.drag_drop.get_video_paths()) if has_video else 0
        photo_count = len(photo_paths)

        status_parts = []
        if video_produkt_gewaehlt:
            if video_gewaehlt_aber_nicht_bezahlt:
                status_parts.append(f"Erstelle {video_count} Video(s) mit Wasserzeichen (nicht bezahlt)")
            else:
                status_parts.append(f"Verarbeite {video_count} Video(s)")

        if foto_produkt_gewaehlt:
            status_parts.append(f"Kopiere {photo_count} Foto(s)")

        status_text = "Status: " + " und ".join(status_parts)

        if form_data["upload_to_server"]:
            status_text += " - Lade auf Server hoch"

        status_text += "... Bitte warten."

        self.progress_handler.set_status(status_text)
        self._switch_to_cancel_mode()

        # VideoProcessor initialisieren
        self.video_processor = VideoProcessor(
            progress_callback=self._update_progress,
            status_callback=self._handle_status_update,
            config_manager=self.config  # Config Manager übergeben
        )

        payload = {
            "form_data": form_data,
            "combined_video_path": combined_video_path if has_video else None,
            "video_clip_paths": self.drag_drop.get_video_paths() if has_video else [],  # NEU: Einzelne Clips
            "kunde": kunde,
            "photo_paths": photo_paths,
            "settings": self.config.get_settings(),
            "create_watermark_version": video_gewaehlt_aber_nicht_bezahlt,
            "watermark_clip_index": self.drag_drop.get_watermark_clip_index()  # NEU: Index des ausgewählten Clips
        }

        print('kunde in erstelle_video:', kunde)

        video_thread = threading.Thread(
            target=self.video_processor.create_video_with_intro_only,
            args=(payload,)
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

    def on_files_added(self, has_videos, has_photos):
        """Wird von DragDropFrame aufgerufen, um FormFields zu aktualisieren."""
        if self.form_fields:
            self.form_fields.auto_check_products(has_videos, has_photos)

    def update_watermark_column_visibility(self):
        """Aktualisiert die Sichtbarkeit der Wasserzeichen-Spalte basierend auf Kunde-Status"""
        form_data = self.form_fields.get_form_data()

        # Prüfe, ob Video gewählt aber nicht bezahlt ist
        video_gewaehlt_aber_nicht_bezahlt = (
                (form_data.get("handcam_video", False) and not form_data.get("ist_bezahlt_handcam_video", False)) or
                (form_data.get("outside_video", False) and not form_data.get("ist_bezahlt_outside_video", False))
        )

        # Debug-Ausgabe
        print(f"🔍 Wasserzeichen-Spalte Update:")
        print(f"   Handcam Video: {form_data.get('handcam_video', False)}, Bezahlt: {form_data.get('ist_bezahlt_handcam_video', False)}")
        print(f"   Outside Video: {form_data.get('outside_video', False)}, Bezahlt: {form_data.get('ist_bezahlt_outside_video', False)}")
        print(f"   → Spalte sichtbar: {video_gewaehlt_aber_nicht_bezahlt}")

        # Zeige Spalte wenn Video ausgewählt aber nicht bezahlt ist
        self.drag_drop.set_watermark_column_visible(video_gewaehlt_aber_nicht_bezahlt)

        # Wenn Spalte nicht mehr sichtbar, lösche Auswahl
        if not video_gewaehlt_aber_nicht_bezahlt:
            self.drag_drop.clear_watermark_selection()


    def _switch_to_cancel_mode(self):
        """Wechselt den Button zum Abbrechen-Modus"""
        # Initial: Button deaktivieren während der Kodierung
        self.erstellen_button.config(
            text="Kodierung läuft...",
            bg="#808080",
            state="disabled"
        )

        # Nach kurzer Verzögerung: Button als "Abbrechen" aktivieren
        def enable_cancel_button():
            self.erstellen_button.config(
                text="Abbrechen",
                command=self.abbrechen_prozess,
                bg="#D32F2F",
                state="normal"
            )

        # Aktiviere den Abbrechen-Button nach 500ms
        self.root.after(500, enable_cancel_button)

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

    # --- NEUE METHODEN FÜR DEN SCHNEIDE-DIALOG ---

    def request_cut_dialog(self, original_video_path: str):
        """Wird von drag_drop.py aufgerufen, um den Schneide-Dialog zu öffnen."""
        if self.video_cutter_dialog is not None:
            print("Ein Schneide-Dialog ist bereits geöffnet.")
            self.video_cutter_dialog.lift()
            return

        if not self.video_preview:
            print("Fehler: video_preview ist nicht initialisiert.")
            return

        # 1. Finde den Pfad zur *Kopie* des Videos
        copy_path = self.video_preview.get_copy_path(original_video_path)

        if not copy_path or not os.path.exists(copy_path):
            messagebox.showerror("Fehler",
                                 f"Konnte die temporäre Videokopie für '{os.path.basename(original_video_path)}' nicht finden.\n"
                                 "Bitte erstellen Sie die Vorschau neu (z.B. durch Hinzufügen/Entfernen eines Clips).")
            return

        # 2. Finde den Index des Clips (für späteres Splitten)
        try:
            index = self.drag_drop.get_video_paths().index(original_video_path)
        except ValueError:
            print(f"Fehler: Konnte Index für {original_video_path} nicht finden.")
            index = -1  # Fallback

        # 3. Dialog erstellen
        self.video_cutter_dialog = VideoCutterDialog(
            self.root,
            video_path=copy_path,
            on_complete_callback=lambda result: self.on_cut_complete(original_video_path, index, result)
        )

        # 4. Callback binden, um Referenz zu löschen, wenn Dialog geschlossen wird
        self.video_cutter_dialog.bind("<Destroy>", self._on_cutter_dialog_close)

        self.video_cutter_dialog.show()

    def on_cut_complete(self, original_path: str, index: int, result: dict):
        """
        Callback vom VideoCutterDialog.
        NEU: Stößt asynchrone Metadaten-Aktualisierung an.
        """
        action = result.get("action")
        paths_to_refresh = []

        if action == "cut":
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geschnitten (getrimmt).")
            paths_to_refresh.append(original_path)

        elif action == "split":
            new_copy_path = result.get("new_copy_path")
            print(f"App: Clip '{os.path.basename(original_path)}' wurde geteilt. Neuer Clip: {new_copy_path}")

            # 1. Neuen (Platzhalter) Originalpfad erstellen
            base, ext = os.path.splitext(original_path)
            new_original_placeholder = f"{base}_split_{uuid.uuid4().hex[:6]}{ext}"

            # 2. Neuen Pfad in der DragDrop-Liste an der richtigen Stelle einfügen
            if self.drag_drop:
                self.drag_drop.insert_video_path_at_index(new_original_placeholder, index + 1)

            # 3. Die neue Kopie in der Vorschau-Map registrieren
            if self.video_preview:
                self.video_preview.register_new_copy(new_original_placeholder, new_copy_path)

            paths_to_refresh.append(original_path)
            paths_to_refresh.append(new_original_placeholder)

        elif action == "cancel":
            print(f"App: Schneiden von '{os.path.basename(original_path)}' abgebrochen.")
            # Nichts tun
            return

        # Starte die asynchrone Aktualisierung der Metadaten für die geänderten Clips
        if paths_to_refresh and self.video_preview:
            self.video_preview.refresh_metadata_async(
                paths_to_refresh,
                on_complete_callback=self._on_metadata_refreshed
            )

    def _on_metadata_refreshed(self):
        """
        [MAIN-THREAD] Callback, der aufgerufen wird, nachdem die Metadaten
        im Cache aktualisiert wurden. JETZT ist es sicher, die GUI zu aktualisieren.
        """
        print("App: Metadaten-Aktualisierung abgeschlossen. Aktualisiere GUI.")

        # 1. DragDrop-Tabelle aktualisieren (liest jetzt aus dem aktualisierten Cache)
        if self.drag_drop:
            self.drag_drop.refresh_table()

        # 2. Video-Vorschau regenerieren (verwendet die *neue* Liste der Originale)
        if self.video_preview and self.drag_drop:
            original_paths = self.drag_drop.get_video_paths()
            self.video_preview.regenerate_preview_after_cut(original_paths)

    def _on_cutter_dialog_close(self, event=None):
        """Wird aufgerufen, wenn der Cutter-Dialog zerstört wird."""
        if self.video_cutter_dialog:
            print("Cutter-Dialog geschlossen, Referenz wird gelöscht.")
            self.video_cutter_dialog = None

    # --- ENDE NEUE METHODEN ---

    def on_app_close(self):
        """Aufräumen beim Schließen der App."""
        print("App wird geschlossen...")

        # 1. Aktiven Schneide-Dialog schließen (falls offen)
        if self.video_cutter_dialog:
            try:
                self.video_cutter_dialog.destroy()
            except tk.TclError:
                pass  # Fenster vielleicht schon weg

        # 2. SD-Karten Monitor stoppen
        if self.sd_card_monitor:
            self.sd_card_monitor.stop_monitoring()

        # 3. Temporäre Vorschau-Kopien löschen
        if self.video_preview:
            self.video_preview._cleanup_temp_copies()  # Zugriff auf private Methode für Cleanup

        # 4. Root-Fenster zerstören
        self.root.destroy()

    def initialize_sd_card_monitor(self):
        """Initialisiert und startet den SD-Karten Monitor"""
        try:
            self.sd_card_monitor = SDCardMonitor(
                self.config,
                on_backup_complete=self.on_sd_backup_complete,
                on_progress_update=self.on_sd_progress_update,
                on_status_change=self.on_sd_status_change
            )
            self.sd_card_monitor.start_monitoring()
            print("SD-Karten Monitor initialisiert")
        except Exception as e:
            print(f"Fehler beim Initialisieren des SD-Karten Monitors: {e}")
            # Nicht kritisch, App kann weiter laufen
            self.sd_card_monitor = None

    def on_sd_status_change(self, status_type, data):
        """
        Callback wenn sich der SD-Karten Status ändert

        Args:
            status_type: Art des Status ('monitoring_started', 'sd_detected', 'backup_started',
                        'backup_finished', 'clearing_started', 'clearing_finished')
            data: Zusätzliche Daten je nach Status
        """
        def update_ui():
            if not self.sd_status_indicator:
                return

            if status_type == 'monitoring_started':
                self.sd_status_indicator.set_monitoring_active(True)
                self.progress_handler.set_status("Status: SD-Überwachung aktiv")

            elif status_type == 'sd_detected':
                self.sd_status_indicator.set_sd_detected(True)
                self.progress_handler.set_status(f"Status: SD-Karte erkannt ({data})")

            elif status_type == 'backup_started':
                self.sd_status_indicator.set_backup_active(True)
                self.sd_status_indicator.set_sd_detected(False)
                self.progress_handler.set_status("Status: SD-Karten Backup läuft...")

            elif status_type == 'backup_finished':
                self.sd_status_indicator.set_backup_active(False)
                self.sd_status_indicator.set_sd_detected(False)
                if data:  # Erfolg
                    self.progress_handler.set_status("Status: Backup abgeschlossen")
                else:  # Fehler
                    self.progress_handler.set_status("Status: Backup fehlgeschlagen")

            elif status_type == 'clearing_started':
                self.sd_status_indicator.set_clearing_active(True)
                self.sd_status_indicator.show_clearing_progress()
                self.progress_handler.set_status("Status: SD-Karte wird geleert...")

            elif status_type == 'clearing_finished':
                self.sd_status_indicator.set_clearing_active(False)
                self.progress_handler.set_status("Status: SD-Karte geleert")

        # UI-Update im Haupt-Thread
        self.root.after(0, update_ui)

    def on_sd_progress_update(self, current_mb, total_mb, speed_mbps):
        """
        Callback für SD-Backup Progress-Updates

        Args:
            current_mb: Bereits kopierte MB
            total_mb: Gesamt MB
            speed_mbps: Kopiergeschwindigkeit in MB/s
        """
        def update_ui():
            if self.sd_status_indicator:
                self.sd_status_indicator.update_backup_progress(current_mb, total_mb, speed_mbps)

            # Auch in der Status-Bar anzeigen
            progress_percent = (current_mb / total_mb * 100) if total_mb > 0 else 0
            self.progress_handler.set_status(
                f"Status: SD-Backup {progress_percent:.0f}% ({current_mb:.0f}/{total_mb:.0f} MB, {speed_mbps:.1f} MB/s)"
            )

        # UI-Update im Haupt-Thread
        self.root.after(0, update_ui)

    def _restart_sd_monitor_if_needed(self):
        """Startet den SD-Monitor neu wenn Einstellungen geändert wurden"""
        settings = self.config.get_settings()
        should_monitor = settings.get("sd_auto_backup", False)

        if self.sd_card_monitor:
            is_monitoring = self.sd_card_monitor.monitoring

            if should_monitor and not is_monitoring:
                # Monitoring wurde aktiviert
                self.sd_card_monitor.start_monitoring()
            elif not should_monitor and is_monitoring:
                # Monitoring wurde deaktiviert
                self.sd_card_monitor.stop_monitoring()
                if self.sd_status_indicator:
                    self.sd_status_indicator.hide()
                self.progress_handler.set_status("Status: Bereit.")

    def on_sd_backup_complete(self, backup_path, success):
        """
        Wird aufgerufen wenn SD-Karten Backup abgeschlossen ist

        Args:
            backup_path: Pfad zum Backup-Ordner oder None bei Fehler
            success: True wenn Backup erfolgreich war
        """
        if not success:
            print("SD-Karten Backup fehlgeschlagen")
            messagebox.showerror("Backup Fehler",
                               "Das Backup von der SD-Karte ist fehlgeschlagen.",
                               parent=self.root)
            return

        print(f"SD-Karten Backup erfolgreich: {backup_path}")

        settings = self.config.get_settings()

        # Prüfe ob automatischer Import aktiviert ist
        if settings.get("sd_auto_import", False):
            self.import_from_backup(backup_path)
        else:
            # Zeige Info-Nachricht
            messagebox.showinfo("Backup erfolgreich",
                              f"SD-Karten Backup wurde erfolgreich erstellt:\n{backup_path}",
                              parent=self.root)

    def import_from_backup(self, backup_path):
        """
        Importiert Dateien aus dem Backup-Ordner (simuliert Drag&Drop)

        Args:
            backup_path: Pfad zum Backup-Ordner
        """
        # Merke QR-Check Status und deaktiviere temporär
        qr_check_was_enabled = False
        if self.drag_drop and hasattr(self.drag_drop, 'qr_check_enabled'):
            qr_check_was_enabled = self.drag_drop.qr_check_enabled.get()
            if qr_check_was_enabled:
                print("QR-Code-Prüfung temporär deaktiviert für Auto-Import")
                self.drag_drop.qr_check_enabled.set(False)

        # Variable für finally-Block
        videos_imported = False

        try:
            # Sammle alle Dateien aus dem Backup
            video_files = []
            photo_files = []

            # Dateien liegen jetzt direkt im Backup-Ordner (flache Struktur)
            if os.path.isdir(backup_path):
                for file in os.listdir(backup_path):
                    file_lower = file.lower()
                    file_path = os.path.join(backup_path, file)

                    # Nur Dateien, keine Ordner
                    if not os.path.isfile(file_path):
                        continue

                    # Video-Formate
                    if file_lower.endswith(('.mp4', '.mov', '.avi', '.mkv', '.m4v', '.mpg', '.mpeg', '.wmv', '.flv', '.webm')):
                        video_files.append(file_path)
                    # Foto-Formate
                    elif file_lower.endswith(('.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.gif', '.webp', '.heic', '.raw', '.cr2', '.nef', '.arw', '.dng')):
                        photo_files.append(file_path)

            if video_files or photo_files:
                # Füge Dateien zum Drag&Drop hinzu
                if self.drag_drop:
                    self.drag_drop.add_files(video_files, photo_files)

                if video_files:
                    videos_imported = True

                print(f"Auto-Import: {len(video_files)} Videos und {len(photo_files)} Fotos importiert")

                # messagebox.showinfo("Import erfolgreich",
                #                   f"SD-Karten Backup erfolgreich importiert:\n"
                #                   f"{len(video_files)} Videos und {len(photo_files)} Fotos",
                #                   parent=self.root)
            else:
                print("Keine Dateien zum Importieren gefunden")
                messagebox.showwarning("Keine Dateien",
                                     "Im Backup wurden keine Videos oder Fotos gefunden.",
                                     parent=self.root)

        except Exception as e:
            print(f"Fehler beim Importieren aus Backup: {e}")
            messagebox.showerror("Import Fehler",
                               f"Fehler beim Importieren der Dateien:\n{str(e)}",
                               parent=self.root)
        finally:
            # Stelle QR-Check Status wieder her
            if qr_check_was_enabled and self.drag_drop and hasattr(self.drag_drop, 'qr_check_enabled'):
                print("QR-Code-Prüfung wieder aktiviert nach Auto-Import")
                self.drag_drop.qr_check_enabled.set(True)

                # Trigger QR-Analyse für das erste importierte Video
                if videos_imported:
                    print("Starte QR-Analyse für erstes importiertes Video")
                    video_paths = self.drag_drop.get_video_paths()
                    if video_paths:
                        self.run_qr_analysis(video_paths)

    def run(self):
        """Startet die Hauptloop der Anwendung"""

        try:
            initialize_updater(self.root, self.APP_VERSION)
        except Exception as e:
            print(f"Fehler beim Initialisieren des Updaters: {e}")

        self.root.mainloop()

