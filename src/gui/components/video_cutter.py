import tkinter as tk
from tkinter import ttk, messagebox
import os
import threading
import subprocess
import json
import time
import sys
import shutil
from typing import Callable, Dict

try:
    from src.utils.path_helper import setup_vlc_paths

    setup_vlc_paths()
except ImportError:
    print("Warnung: path_helper nicht gefunden. VLC funktioniert möglicherweise nicht in der gebündelten App.")

try:
    import vlc
except ImportError:
    print("FATAL: python-vlc Modul nicht gefunden. Bitte installieren Sie es.")
    vlc = None

from .circular_spinner import CircularSpinner
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW


class VideoCutterDialog(tk.Toplevel):
    """
    Ein modales Dialogfenster zum Schneiden (Trimmen) oder Teilen (Splitten)
    eines einzelnen Videoclips (einer temporären Kopie).
    """

    # --- Farben für die benutzerdefinierte Fortschrittsanzeige ---
    COLOR_BACKGROUND = "#404040"
    COLOR_PROGRESS_BAR = "#555555"
    COLOR_KEEP_SEGMENT = "#0078d4"
    COLOR_CUT_SEGMENT = "#888888"
    COLOR_PLAYHEAD = "#E74C3C"

    # ---

    def __init__(self, parent, video_path: str, on_complete_callback: Callable[[Dict], None]):
        if not vlc:
            # Zeigen Sie den Fehler im übergeordneten Fenster an, da der Dialog möglicherweise nicht erstellt werden kann
            messagebox.showerror("VLC Fehler", "Das VLC-Modul (python-vlc) konnte nicht geladen werden.", parent=parent)
            # Verhindern, dass Toplevel initialisiert wird, wenn VLC fehlt
            # Rufen Sie super().__init__ NICHT auf und geben Sie None oder eine Exception zurück
            # Hier entscheiden wir uns dafür, einfach zurückzukehren, was die Instanziierung fehlschlagen lässt.
            return

        super().__init__(parent)
        self.parent = parent
        self.video_path = video_path
        self.on_complete_callback = on_complete_callback

        self.title("Video schneiden")
        self.geometry("800x600")

        # --- Interne Status-Variablen ---
        try:
            self.vlc_instance = vlc.Instance("--no-xlib")
            self.media_player = self.vlc_instance.media_player_new()
        except Exception as e:
            messagebox.showerror("VLC Init Fehler", f"VLC konnte nicht initialisiert werden:\n{e}", parent=parent)
            self.destroy()  # Dialog sofort schließen
            return

        self.total_duration_ms = 0
        self.fps = 30.0  # Standard, wird überschrieben
        self.start_time_ms = None
        self.end_time_ms = None
        self.is_processing = False  # Verhindert Aktionen während FFmpeg läuft
        self.is_dragging_playhead = False
        self._updater_job = None

        # --- UI-Referenzen ---
        self.video_frame = None
        self.custom_progress_canvas = None
        self.time_label = None
        self.play_pause_btn = None
        self.spinner = None
        self.status_label = None
        self.buttons = {}  # Dict für alle Steuerungs-Buttons

        # --- Dialog-Setup ---
        self._create_widgets()

        # NEU: Tastatur-Bindings hinzufügen
        self.bind('<q>', self._on_key_frame_back)
        self.bind('<Q>', self._on_key_frame_back) # Für Umschalt/CapsLock
        self.bind('<e>', self._on_key_frame_fwd)
        self.bind('<E>', self._on_key_frame_fwd) # Für Umschalt/CapsLock
        self.bind('<space>', self._on_key_toggle_play_pause)

        # Modalen Dialog einrichten
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.transient(parent)
        self.grab_set()

        # Video laden (synchrone Info, asynchrones Laden)
        self._load_video_info_and_start()

    def show(self):
        """Macht das Fenster sichtbar und zentriert es auf dem Parent-Fenster."""
        # Überprüfen, ob die Initialisierung fehlgeschlagen ist (VLC nicht geladen)
        if not hasattr(self, 'vlc_instance') or not self.vlc_instance:
            print("Dialog kann nicht angezeigt werden, VLC-Initialisierung fehlgeschlagen.")
            return  # Verhindert das Anzeigen eines leeren/fehlerhaften Fensters

        # NEU: Zentriere den Dialog auf dem Parent-Fenster
        self.update_idletasks()  # Erzwinge Layout-Update, um Größe zu berechnen

        # Hole die Größe und Position des Parent-Fensters
        parent_x = self.parent.winfo_x()
        parent_y = self.parent.winfo_y()
        parent_width = self.parent.winfo_width()
        parent_height = self.parent.winfo_height()

        # Hole die Größe des Dialog-Fensters
        dialog_width = self.winfo_width()
        dialog_height = self.winfo_height()

        # Berechne die Position für die Zentrierung
        x = parent_x + (parent_width - dialog_width) // 2
        y = parent_y + (parent_height - dialog_height) // 2

        # Stelle sicher, dass der Dialog nicht außerhalb des Bildschirms positioniert wird
        if x < 0:
            x = 0
        if y < 0:
            y = 0

        # Setze die Fensterposition
        self.geometry(f"+{x}+{y}")

        self.lift()
        self.focus_force()
        self.wait_window()

    def _load_video_info_and_start(self):
        """Holt synchron Metadaten und startet dann das asynchrone Laden."""
        try:
            info = self._get_video_info(self.video_path)
            self.total_duration_ms = info["duration_ms"]
            self.fps = info["fps"]
            print(f"Cutter: Video geladen. Dauer: {self.total_duration_ms}ms, FPS: {self.fps}")
        except Exception as e:
            self._handle_error(f"Fehler beim Laden der Video-Metadaten: {e}")
            self.after(100, self._on_cancel)  # Dialog schließen, wenn Video nicht geladen werden kann
            return

        # VLC an das (jetzt gezeichnete) Fenster binden
        self.video_frame.update_idletasks()
        if os.name == 'nt':
            self.media_player.set_hwnd(self.video_frame.winfo_id())
        elif sys.platform == "darwin":
            # Sicherstellen, dass die ID ein Integer ist
            try:
                win_id = int(self.video_frame.winfo_id())
                self.media_player.set_nsobject(win_id)
            except (ValueError, TypeError, AttributeError) as e:
                messagebox.showerror("VLC Fehler (macOS)", f"Ungültige Fenster-ID für VLC: {e}", parent=self)
                self.destroy()
                return
        else:  # Linux
            # Sicherstellen, dass die ID ein Integer ist
            try:
                win_id = int(self.video_frame.winfo_id())
                self.media_player.set_xwindow(win_id)
            except (ValueError, TypeError, AttributeError) as e:
                messagebox.showerror("VLC Fehler (Linux)", f"Ungültige Fenster-ID für VLC: {e}", parent=self)
                self.destroy()
                return

        media = self.vlc_instance.media_new(self.video_path)
        self.media_player.set_media(media)

        # Events binden
        events = self.media_player.event_manager()
        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end_reached)
        events.event_attach(vlc.EventType.MediaPlayerTimeChanged, self._on_time_changed)
        # Player Status Events für Button-Updates
        events.event_attach(vlc.EventType.MediaPlayerPlaying, lambda e: self.play_pause_btn.config(text="⏸"))
        events.event_attach(vlc.EventType.MediaPlayerPaused, lambda e: self.play_pause_btn.config(text="▶"))
        events.event_attach(vlc.EventType.MediaPlayerStopped, lambda e: self.play_pause_btn.config(text="▶"))

        # UI initialisieren
        self._on_time_changed(None)  # Zeit-Label initial setzen
        self._draw_custom_progress()
        self._set_processing(False)  # Alle Buttons aktivieren

        self.media_player.play()  # Autostart
        self.after(100, self.media_player.pause)  # Aber sofort pausieren
        self.play_pause_btn.config(text="▶")

    def _get_video_info(self, video_path: str) -> Dict:
        """Liest Dauer und FPS eines Videos mit ffprobe aus."""
        cmd = [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_streams", video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        streams = json.loads(result.stdout)["streams"]
        video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)

        if not video_stream:
            raise ValueError("Kein Video-Stream gefunden.")

        # Dauer
        duration_s_str = video_stream.get('duration', '0')
        duration_ms = int(float(duration_s_str) * 1000)

        # FPS
        r_frame_rate = video_stream.get('r_frame_rate', '30/1')
        try:
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den if den != 0 else 30.0
        except:
            fps = 30.0

        return {"duration_ms": duration_ms, "fps": fps}

    def _create_widgets(self):
        """Erstellt die UI-Elemente des Dialogs."""

        # 1. Haupt-Container
        main_frame = tk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.rowconfigure(0, weight=1)  # Videobereich
        main_frame.rowconfigure(1, weight=0)  # Progress
        main_frame.rowconfigure(2, weight=0)  # Controls
        main_frame.columnconfigure(0, weight=1)

        # 2. Videoplayer-Bereich
        self.video_frame = tk.Frame(main_frame, bg="black")
        self.video_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # 3. Benutzerdefinierte Fortschrittsanzeige
        self.custom_progress_canvas = tk.Canvas(
            main_frame, height=40, bg=self.COLOR_BACKGROUND,
            highlightthickness=0, cursor="hand2"
        )
        self.custom_progress_canvas.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.custom_progress_canvas.bind("<Configure>", lambda e: self._draw_custom_progress())
        self.custom_progress_canvas.bind("<Button-1>", self._on_progress_click)
        self.custom_progress_canvas.bind("<B1-Motion>", self._on_progress_drag)
        self.custom_progress_canvas.bind("<ButtonRelease-1>", self._on_progress_release)

        # 4. Steuerungs-Container
        controls_container = tk.Frame(main_frame)
        controls_container.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        controls_container.columnconfigure(2, weight=1)  # Spacer

        # 4a. Play/Zeit-Steuerung
        play_frame = tk.Frame(controls_container)
        play_frame.grid(row=0, column=0, sticky="ns")

        self.play_pause_btn = tk.Button(play_frame, text="▶", font=("Arial", 14), width=3,
                                        command=self._toggle_play_pause)
        self.play_pause_btn.pack(side=tk.LEFT, padx=5)

        self.time_label = tk.Label(play_frame, text="00:00:000 / 00:00:000", font=("Arial", 10, "bold"))
        self.time_label.pack(side=tk.LEFT, padx=5)

        # 4b. Frame-Steuerung
        frame_step_frame = tk.Frame(controls_container)
        frame_step_frame.grid(row=0, column=1, sticky="ns", padx=10)

        self.buttons["frame_back"] = tk.Button(frame_step_frame, text="[ ◀ 1F (Q) ]", command=lambda: self._step_frame(-1))
        self.buttons["frame_back"].pack(side=tk.LEFT, padx=2)

        self.buttons["frame_fwd"] = tk.Button(frame_step_frame, text="[ (E) 1F ▶ ]", command=lambda: self._step_frame(1))
        self.buttons["frame_fwd"].pack(side=tk.LEFT, padx=2)

        # 4c. Spacer
        tk.Frame(controls_container).grid(row=0, column=2, sticky="ew")

        # 4d. IN/OUT-Steuerung
        in_out_frame = tk.Frame(controls_container)
        in_out_frame.grid(row=0, column=3, sticky="ns", padx=10)

        self.buttons["set_in"] = tk.Button(in_out_frame, text="[ IN ☝ ]", font=("Arial", 10, "bold"),
                                           command=self._set_in, fg="#0078d4")
        self.buttons["set_in"].pack(side=tk.LEFT, padx=2)

        self.buttons["set_out"] = tk.Button(in_out_frame, text="[ OUT ☝ ]", font=("Arial", 10, "bold"),
                                            command=self._set_out, fg="#E74C3C")
        self.buttons["set_out"].pack(side=tk.LEFT, padx=2)

        # 5. Haupt-Aktions-Container (Split / Apply)
        action_frame = tk.Frame(main_frame)
        action_frame.grid(row=3, column=0, sticky="ew", padx=5, pady=5)
        action_frame.columnconfigure(0, weight=1)  # Linke Seite (Spinner/Status)
        action_frame.columnconfigure(1, weight=1)  # Rechte Seite (Buttons)

        status_spinner_frame = tk.Frame(action_frame)
        status_spinner_frame.grid(row=0, column=0, sticky="w")

        self.spinner = CircularSpinner(status_spinner_frame, size=30, line_width=3)
        self.spinner.pack(side=tk.LEFT, padx=5)

        self.status_label = tk.Label(status_spinner_frame, text="Verarbeite...", font=("Arial", 10, "bold"),
                                     fg="orange")
        # Status-Label initial ausblenden
        # self.status_label.pack(side=tk.LEFT, padx=5)

        # Rechte Seite (Buttons)
        apply_button_frame = tk.Frame(action_frame)
        apply_button_frame.grid(row=0, column=1, sticky="e")

        self.buttons["split"] = tk.Button(apply_button_frame, text="Am Playhead teilen", command=self._on_split)
        self.buttons["split"].pack(side=tk.LEFT, padx=5, ipady=5)

        self.buttons["apply"] = tk.Button(apply_button_frame, text="Übernehmen (Schneiden)", command=self._on_apply,
                                          font=("Arial", 10, "bold"), bg="#4CAF50", fg="white")
        self.buttons["apply"].pack(side=tk.LEFT, padx=5, ipady=5)

        self._set_processing(True)  # Starte im deaktivierten Modus, bis Video geladen ist

    # --- Tastatur-Handler (NEU) ---

    def _on_key_frame_back(self, event=None):
        """Tastatur-Handler für 'Q' (1 Frame zurück)."""
        # Die Logik (inkl. is_processing Check) ist in _step_frame()
        self._step_frame(-1)

    def _on_key_frame_fwd(self, event=None):
        """Tastatur-Handler für 'E' (1 Frame vor)."""
        self._step_frame(1)

    def _on_key_toggle_play_pause(self, event=None):
        """Tastatur-Handler für 'Space' (Play/Pause)."""
        self._toggle_play_pause()


    # --- UI Update & Event Handler ---

    def _on_time_changed(self, event):
        """Wird vom VLC Event aufgerufen, um Zeit und Playhead zu aktualisieren."""
        # Verhindere Updates während der Verarbeitung oder beim Ziehen durch den Benutzer
        if self.is_processing or self.is_dragging_playhead:
            return

        current_time = self.media_player.get_time()
        if current_time < 0: current_time = 0

        # Aktualisiere Zeit-Label
        self.time_label.config(text=f"{self._format_time(current_time)} / {self._format_time(self.total_duration_ms)}")

        # Zeichne nur den Playhead neu
        self._draw_playhead(current_time)

    def _format_time(self, ms: int) -> str:
        """Formatiert Millisekunden in MM:SS:mmm."""
        if ms < 0: ms = 0
        secs = ms // 1000
        mins = secs // 60
        secs = secs % 60
        millis = ms % 1000
        return f"{mins:02d}:{secs:02d}:{millis:03d}"

    def _draw_custom_progress(self):
        """Zeichnet die gesamte Fortschrittsanzeige neu (Segmente + Playhead)."""
        canvas = self.custom_progress_canvas
        canvas.delete("all")

        width = canvas.winfo_width()
        height = canvas.winfo_height()

        if width <= 0: return

        bar_y_start = height * 0.25
        bar_y_end = height * 0.75

        # 1. Hintergrund-Leiste
        canvas.create_rectangle(0, bar_y_start, width, bar_y_end, fill=self.COLOR_PROGRESS_BAR, width=0, tags="bg")

        # 2. Start/End-Zeiten holen (Standard: 0 und Ende)
        start_ms = self.start_time_ms if self.start_time_ms is not None else 0
        end_ms = self.end_time_ms if self.end_time_ms is not None else self.total_duration_ms

        if self.start_time_ms is not None and self.end_time_ms is not None:
            if end_ms < start_ms:
                start_ms, end_ms = end_ms, start_ms  # Sicherstellen, dass Start < Ende

        # 3. Prozentuale Positionen berechnen
        start_perc = start_ms / self.total_duration_ms if self.total_duration_ms > 0 else 0
        end_perc = end_ms / self.total_duration_ms if self.total_duration_ms > 0 else 1

        start_x = width * start_perc
        end_x = width * end_perc

        # 4. Segmente zeichnen
        # Graues Segment (Anfang)
        if start_x > 0:
            canvas.create_rectangle(0, bar_y_start, start_x, bar_y_end, fill=self.COLOR_CUT_SEGMENT, width=0,
                                    tags="cut")
        # Blaues Segment (Behalten)
        canvas.create_rectangle(start_x, bar_y_start, end_x, bar_y_end, fill=self.COLOR_KEEP_SEGMENT, width=0,
                                tags="keep")
        # Graues Segment (Ende)
        if end_x < width:
            canvas.create_rectangle(end_x, bar_y_start, width, bar_y_end, fill=self.COLOR_CUT_SEGMENT, width=0,
                                    tags="cut")

        # 5. Playhead zeichnen
        self._draw_playhead(self.media_player.get_time())

    def _draw_playhead(self, current_time_ms: int):
        """Zeichnet nur den Playhead (roter Strich) neu."""
        canvas = self.custom_progress_canvas
        canvas.delete("playhead")

        width = canvas.winfo_width()
        height = canvas.winfo_height()

        if width <= 0 or not self.winfo_exists():  # Prüfe auch, ob Fenster noch da ist
            return

        current_time_ms = max(0, min(current_time_ms, self.total_duration_ms))

        play_perc = current_time_ms / self.total_duration_ms if self.total_duration_ms > 0 else 0
        play_x = width * play_perc

        canvas.create_rectangle(play_x - 1, 0, play_x + 1, height, fill=self.COLOR_PLAYHEAD, width=0, tags="playhead")

    def _on_progress_click(self, event):
        """Springt zur angeklickten Position."""
        # KORREKTUR: Klicks während Verarbeitung ignorieren
        if self.is_processing: return
        self.is_dragging_playhead = True  # Beginne Drag
        self._seek_from_event(event)

    def _on_progress_drag(self, event):
        """Aktualisiert Position während des Ziehens."""
        # KORREKTUR: Klicks während Verarbeitung ignorieren
        if self.is_processing: return
        if not self.is_dragging_playhead: return
        self._seek_from_event(event)

    def _on_progress_release(self, event):
        """Beendet das Ziehen."""
        # KORREKTUR: Klicks während Verarbeitung ignorieren
        if self.is_processing:
            self.is_dragging_playhead = False  # Sicherstellen, dass Drag beendet wird
            return
        self.is_dragging_playhead = False
        self._seek_from_event(event)  # Letzte Position setzen

    def _seek_from_event(self, event):
        """Hilfsmethode: Berechnet Zeit aus Klick-Event und springt dorthin."""
        width = self.custom_progress_canvas.winfo_width()
        if width == 0 or self.total_duration_ms == 0: return

        click_x = max(0, min(event.x, width))
        pos_perc = click_x / width

        target_time_ms = int(pos_perc * self.total_duration_ms)

        self.media_player.set_time(target_time_ms)
        self._draw_playhead(target_time_ms)  # Sofortiges Feedback
        self.time_label.config(
            text=f"{self._format_time(target_time_ms)} / {self._format_time(self.total_duration_ms)}")

    # --- Button-Aktionen ---

    def _toggle_play_pause(self):
        """Schaltet Play/Pause um."""
        if self.is_processing: return
        if self.media_player.is_playing():
            self.media_player.pause()
            # Button-Text wird durch Event-Handler aktualisiert
        else:
            # Wenn am Ende, springe zum Anfang
            if self.media_player.get_state() == vlc.State.Ended:
                self.media_player.set_time(0)
                # Warte kurz, bis der Player bereit ist, sonst startet er nicht
                self.after(50, self.media_player.play)
            else:
                self.media_player.play()
            # Button-Text wird durch Event-Handler aktualisiert

    def _step_frame(self, direction: int):
        """Springt 1 Frame vor oder zurück UND pausiert die Wiedergabe."""
        # KORREKTUR: Stellt sicher, dass der Player pausiert ist und bleibt
        if self.is_processing or self.fps == 0: return

        # 1. Player sicher pausieren
        if self.media_player.is_playing():
            self.media_player.pause()

        # 2. Zeit berechnen
        step_ms = (1000 / self.fps) * direction
        current_time = self.media_player.get_time()
        new_time = max(0, min(self.total_duration_ms, current_time + step_ms))

        # 3. FIX: set_time() in separatem Thread, um UI nicht einzufrieren
        threading.Thread(
            target=self._set_time_thread_safe,
            args=(int(new_time),),
            daemon=True
        ).start()

        # 4. Sicherstellen, dass Button auf Play steht (da wir pausiert haben)
        self.play_pause_btn.config(text="▶")

    def _set_time_thread_safe(self, target_time_ms: int):
        """[THREAD] Setzt die Zeit im VLC-Player mit Timeout-Schutz."""
        try:
            # Setze Timeout mit threading Event
            timeout_event = threading.Event()

            def set_time_with_timeout():
                try:
                    self.media_player.set_time(target_time_ms)
                except Exception as e:
                    print(f"Fehler beim set_time: {e}")

            thread = threading.Thread(target=set_time_with_timeout, daemon=True)
            thread.start()
            thread.join(timeout=1.0)  # Warte max 1 Sekunde

            if thread.is_alive():
                print(f"WARNUNG: VLC set_time() hat timeout (>1s)")

            # UI aktualisieren im Main-Thread
            if self.winfo_exists():
                self.after(100, lambda: self._on_time_changed(None))
        except Exception as e:
            print(f"Fehler in _set_time_thread_safe: {e}")

    def _set_in(self):
        """Setzt den IN-Punkt (Start) auf die aktuelle Playhead-Position."""
        if self.is_processing: return
        current_time = self.media_player.get_time()

        # Validierung: IN kann nicht nach OUT gesetzt werden (wenn OUT existiert)
        if self.end_time_ms is not None and current_time > self.end_time_ms:
            self.start_time_ms = self.end_time_ms
            self.end_time_ms = current_time
        else:
            self.start_time_ms = current_time

        print(f"IN gesetzt: {self.start_time_ms}ms")
        self._draw_custom_progress()

    def _set_out(self):
        """Setzt den OUT-Punkt (Ende) auf die aktuelle Playhead-Position."""
        if self.is_processing: return
        current_time = self.media_player.get_time()

        # Validierung: OUT kann nicht vor IN gesetzt werden (wenn IN existiert)
        if self.start_time_ms is not None and current_time < self.start_time_ms:
            self.end_time_ms = self.start_time_ms
            self.start_time_ms = current_time
        else:
            self.end_time_ms = current_time

        print(f"OUT gesetzt: {self.end_time_ms}ms")
        self._draw_custom_progress()

    def _on_cancel(self):
        """Wird aufgerufen, wenn das Fenster geschlossen wird (X-Button)."""
        if self.is_processing:
            print("Verarbeitung läuft, Abbruch nicht möglich.")
            return

        print("Cutter: Vorgang abgebrochen.")
        self._cleanup()
        # WICHTIG: grab_release() vor destroy(), sonst kann Hauptfenster blockieren
        self.grab_release()
        self.destroy()  # Dialog selbst schließen
        self.on_complete_callback({"action": "cancel"})  # App benachrichtigen

    def _on_apply(self):
        """Startet den 'Trim'-Vorgang (Überschreiben)."""
        if self.is_processing: return

        if self.start_time_ms is None and self.end_time_ms is None:
            messagebox.showinfo("Keine Änderung",
                                "Sie haben keinen IN- or OUT-Punkt gesetzt. Es gibt nichts zu schneiden.", parent=self)
            return

        # Sicherstellen, dass Start < Ende
        start_ms = self.start_time_ms if self.start_time_ms is not None else 0
        end_ms = self.end_time_ms if self.end_time_ms is not None else self.total_duration_ms
        if self.start_time_ms is not None and self.end_time_ms is not None:
            if end_ms < start_ms:
                start_ms, end_ms = end_ms, start_ms

        # Player stoppen UND Mediendatei freigeben, um WinError 32 zu verhindern
        if self.media_player.is_playing():
            self.media_player.stop()
        self.media_player.set_media(None)  # Wichtig! Gibt Datei frei

        self._set_processing(True)
        self.status_label.config(text="Video wird geschnitten (Trim)...")

        threading.Thread(
            target=self._run_cut_task,
            args=(start_ms, end_ms),
            daemon=True
        ).start()

    def _on_split(self):
        """Startet den 'Split'-Vorgang."""
        if self.is_processing: return

        split_time_ms = self.media_player.get_time()

        if split_time_ms <= 100 or split_time_ms >= (self.total_duration_ms - 100):  # Toleranz
            messagebox.showwarning("Ungültiger Split-Punkt",
                                   "Sie können nicht zu nah am Anfang oder Ende des Clips teilen.", parent=self)
            return

        # Player stoppen UND Mediendatei freigeben, um WinError 32 zu verhindern
        if self.media_player.is_playing():
            self.media_player.stop()
        self.media_player.set_media(None)  # Wichtig! Gibt Datei frei

        self._set_processing(True)
        self.status_label.config(text="Video wird geteilt (Split)...")

        threading.Thread(
            target=self._run_split_task,
            args=(split_time_ms,),
            daemon=True
        ).start()

    # --- Verarbeitungs-Threads (FFmpeg) ---

    def _run_cut_task(self, start_ms: int, end_ms: int):
        """
        [THREAD] Führt FFmpeg aus, um die Datei zu trimmen und zu überschreiben.
        """
        try:
            input_path = self.video_path
            temp_output_path = f"{input_path}.__temp_cut__.mp4"

            start_sec = start_ms / 1000.0
            duration_sec = (end_ms - start_ms) / 1000.0

            cmd = [
                "ffmpeg", "-y",
                "-i", input_path,  # Input zuerst für genaueres Seeking mit -ss
                "-ss", str(start_sec),  # Startzeit (genauer nach -i)
                "-t", str(duration_sec),  # Dauer
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",  # Re-encode
                "-c:a", "aac", "-b:a", "128k",  # Re-encode Audio
                # "-avoid_negative_ts", "make_zero", # Sicherstellen, dass Zeitstempel bei 0 beginnt
                "-map", "0:v:0?", "-map", "0:a:0?",  # Nur Video- und Audio-Stream
                temp_output_path
            ]

            print(f"Starte FFmpeg (Cut): {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result.returncode != 0:
                raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

            # Erfolgreich? Original überschreiben
            try:
                # Kurze Pause, um sicherzustellen, dass FFmpeg die Datei vollständig freigegeben hat
                time.sleep(0.2)
                # Verwende copy2 + remove für mehr Robustheit unter Windows
                shutil.copy2(temp_output_path, input_path)
                time.sleep(0.1)  # Kurze Pause vor dem Löschen
                os.remove(temp_output_path)
                print("FFmpeg (Cut) erfolgreich. Original überschrieben.")
            except Exception as e:
                raise Exception(f"Fehler beim Überschreiben der Original-Kopie nach Schnitt: {e}")

            # Callback im Haupt-Thread auslösen
            self.after(0, self._handle_processing_complete, {"action": "cut"})

        except subprocess.CalledProcessError as e:
            self._handle_error_in_thread(f"FFmpeg (Cut) fehlgeschlagen (Code {e.returncode}):\n{e.stderr}")
        except Exception as e:
            self._handle_error_in_thread(f"Fehler beim Schneiden: {e}")
        finally:
            # Sicherstellen, dass temporäre Datei gelöscht wird, falls vorhanden
            if os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except Exception as del_e:
                    print(f"Konnte temp. Schnittdatei nicht löschen: {del_e}")

    def _run_split_task(self, split_time_ms: int):
        """
        [THREAD] Führt FFmpeg aus, um die Datei zu teilen.
        Teil 1 überschreibt das Original, Teil 2 wird neu erstellt.
        """
        temp_part1_path = None  # Definition außerhalb des try-Blocks
        part2_path = None
        try:
            input_path = self.video_path
            base, ext = os.path.splitext(input_path)
            temp_part1_path = f"{base}.__temp_part1__{ext}"
            part2_path = f"{base}__part2__{ext}"  # Finaler Pfad für Teil 2

            split_sec = split_time_ms / 1000.0

            # --- Befehl für Teil 1 (Anfang bis Split-Punkt) ---
            cmd1 = [
                "ffmpeg", "-y", "-i", input_path,
                "-t", str(split_sec),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                # "-avoid_negative_ts", "make_zero",
                "-map", "0:v:0?", "-map", "0:a:0?",
                temp_part1_path
            ]

            print(f"Starte FFmpeg (Split 1): {' '.join(cmd1)}")
            result1 = subprocess.run(cmd1, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            if result1.returncode != 0:
                raise subprocess.CalledProcessError(result1.returncode, cmd1, result1.stdout, result1.stderr)

            # --- Befehl für Teil 2 (Split-Punkt bis Ende) ---
            cmd2 = [
                "ffmpeg", "-y",
                "-i", input_path,  # Input zuerst
                "-ss", str(split_sec),  # Startzeit nach -i
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                # "-avoid_negative_ts", "make_zero",
                "-map", "0:v:0?", "-map", "0:a:0?",
                part2_path
            ]

            print(f"Starte FFmpeg (Split 2): {' '.join(cmd2)}")
            result2 = subprocess.run(cmd2, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            if result2.returncode != 0:
                raise subprocess.CalledProcessError(result2.returncode, cmd2, result2.stdout, result2.stderr)

            # Beide erfolgreich? Original überschreiben
            try:
                # Kurze Pause
                time.sleep(0.2)
                # Verwende copy2 + remove für Teil 1
                shutil.copy2(temp_part1_path, input_path)
                time.sleep(0.1)
                os.remove(temp_part1_path)
                print("FFmpeg (Split) erfolgreich. Original (Teil 1) überschrieben.")
            except Exception as e:
                raise Exception(f"Fehler beim Überschreiben (Teil 1) nach Split: {e}")

            # Callback im Haupt-Thread auslösen
            result = {"action": "split", "new_copy_path": part2_path}
            self.after(0, self._handle_processing_complete, result)

        except subprocess.CalledProcessError as e:
            # Wenn Teil 2 fehlschlägt, Teil 1 (temp) löschen
            self._handle_error_in_thread(f"FFmpeg (Split) fehlgeschlagen (Code {e.returncode}):\n{e.stderr}")
        except Exception as e:
            self._handle_error_in_thread(f"Fehler beim Teilen: {e}")
        finally:
            # Sicherstellen, dass temporäre Dateien gelöscht werden
            if temp_part1_path and os.path.exists(temp_part1_path):
                try:
                    os.remove(temp_part1_path)
                except Exception as del_e:
                    print(f"Konnte temp. Teil 1 nicht löschen: {del_e}")
            # Wenn Teil 2 fehlschlägt, aber existiert, lösche es auch
            if 'result2' in locals() and result2.returncode != 0 and part2_path and os.path.exists(part2_path):
                try:
                    os.remove(part2_path)
                except Exception as del_e:
                    print(f"Konnte fehlgeschlagenen Teil 2 nicht löschen: {del_e}")

    # --- Thread-Kommunikation & Status ---

    def _set_processing(self, is_processing: bool):
        """Aktiviert/Deaktiviert die UI während der FFmpeg-Verarbeitung."""
        self.is_processing = is_processing

        if is_processing:
            # self._stop_updater() # Nicht mehr nötig
            self.spinner.start()
            self.status_label.pack(side=tk.LEFT, padx=5)  # Status anzeigen
        else:
            self.spinner.stop()
            self.status_label.pack_forget()  # Status ausblenden
            # Updater wird NICHT automatisch gestartet, nur bei Play

        for name, button in self.buttons.items():
            button.config(state=tk.DISABLED if is_processing else tk.NORMAL)

        # Play-Button separat
        self.play_pause_btn.config(state=tk.DISABLED if is_processing else tk.NORMAL)

    def _handle_error_in_thread(self, error_msg: str):
        """[THREAD-SAFE] Zeigt einen Fehler im Haupt-Thread an."""
        self.after(0, self._handle_error, error_msg)

    def _handle_error(self, error_msg: str):
        """[MAIN-THREAD] Zeigt Fehler an und setzt UI zurück."""
        print(f"FEHLER: {error_msg}")  # Logge den Fehler

        # UI zurücksetzen
        self._set_processing(False)

        # Zeige die Fehlermeldung dem Benutzer
        messagebox.showerror("Verarbeitungsfehler", error_msg, parent=self)

        # Versuche, den Player wiederherzustellen, falls das Medium entfernt wurde
        try:
            # Player braucht Zeit, um sich zu erholen, wenn Medium weg war
            self.after(100, self._reload_media_after_error)
        except Exception as e:
            print(f"Konnte Player nach Fehler nicht wiederherstellen: {e}")
            # Wenn alles fehlschlägt, Dialog schließen
            self._on_cancel()

    def _reload_media_after_error(self):
        """Lädt das Medium neu, falls es nach einem Fehler entfernt wurde."""
        try:
            # Prüfe, ob das Fenster noch existiert
            if not self.winfo_exists(): return

            # Prüfe, ob der Player noch eine Medieninstanz hat
            current_media = self.media_player.get_media()
            if not current_media:
                print("Lade Medium nach Fehler neu...")
                media = self.vlc_instance.media_new(self.video_path)
                self.media_player.set_media(media)
                self.play_pause_btn.config(text="▶")
                # Zeit auf 0 setzen
                self.after(50, lambda: self.media_player.set_time(0))
                self.after(100, lambda: self._on_time_changed(None))  # UI Update erzwingen
        except Exception as e:
            print(f"Fehler beim Neuladen des Mediums: {e}")

    def _handle_processing_complete(self, result: dict):
        """[MAIN-THREAD] Wird aufgerufen, wenn Cut/Split erfolgreich war."""
        print("Verarbeitung erfolgreich abgeschlossen.")
        # KORREKTUR: Setze UI zurück *bevor* der Callback die App benachrichtigt
        self._set_processing(False)

        # Räume VLC-Ressourcen auf *bevor* der Dialog zerstört wird
        self._cleanup()

        # WICHTIG: grab_release() vor destroy(), sonst kann Hauptfenster blockieren
        self.grab_release()
        self.destroy()  # Dialog selbst schließen

        # App benachrichtigen, dass alles fertig ist
        self.on_complete_callback(result)

    def _cleanup(self):
        """Stoppt den Player und gibt VLC-Ressourcen frei."""
        # self._stop_updater() # Nicht mehr nötig
        if hasattr(self, 'media_player') and self.media_player:
            try:
                # Events entfernen, um Fehler nach dem Schließen zu vermeiden
                events = self.media_player.event_manager()
                events.event_detach(vlc.EventType.MediaPlayerEndReached)
                events.event_detach(vlc.EventType.MediaPlayerTimeChanged)
                events.event_detach(vlc.EventType.MediaPlayerPlaying)
                events.event_detach(vlc.EventType.MediaPlayerPaused)
                events.event_detach(vlc.EventType.MediaPlayerStopped)

                if self.media_player.is_playing():
                    self.media_player.stop()
                self.media_player.set_media(None)  # Explizit freigeben
                self.media_player.release()
                self.media_player = None  # Referenz entfernen
            except Exception as e:
                print(f"Fehler beim Freigeben des Media-Players: {e}")
        if hasattr(self, 'vlc_instance') and self.vlc_instance:
            try:
                self.vlc_instance.release()
                self.vlc_instance = None  # Referenz entfernen
            except Exception as e:
                print(f"Fehler beim Freigeben der VLC-Instanz: {e}")

    def _on_end_reached(self, event):
        """Setzt den Player auf Anfang zurück, wenn das Ende erreicht ist."""
        # self._stop_updater() # Nicht mehr nötig
        self.play_pause_btn.config(text="▶")
        # Setze Zeit auf 0 und stoppe den Player explizit
        self.after(50, lambda: (
            self.media_player.stop(),  # Wichtig: Stoppen, nicht nur Zeit setzen
            self._draw_playhead(0),
            self.time_label.config(text=f"{self._format_time(0)} / {self._format_time(self.total_duration_ms)}")
        ))
