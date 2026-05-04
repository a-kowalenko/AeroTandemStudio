import tkinter as tk
from tkinter import ttk, messagebox
import os
import threading
import json
import sys
import shutil
from typing import Callable, Dict

try:
    from src.utils.path_helper import setup_vlc_paths

    setup_vlc_paths()
except ImportError:
    print("Warnung: path_helper nicht gefunden.")
    vlc = None

try:
    import vlc
except Exception as e:
    print(f"FATAL: python-vlc Modul konnte nicht geladen werden: {e}")
    vlc = None

from .circular_spinner import CircularSpinner
from src.video.cutter_service import VideoCutterService


class VideoCutterDialog(tk.Toplevel):
    """
    Modales Dialogfenster zum Planen von Trim oder Split für einen Clip.
    Die FFmpeg-Verarbeitung erfolgt über die Warteschlange in der Haupt-App.
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

        # Service-Layer für Metadaten / Keyframes (FFmpeg läuft in der App-Warteschlange)
        self.cutter_service = VideoCutterService()

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
        self.is_processing = False  # Verhindert Aktionen während des Ladens / Verarbeitens
        self.is_dragging_playhead = False
        self._updater_job = None
        self._seek_debounce_timer = None  # Timer für Debouncing beim Seek
        self._pending_seek_ms = None
        self._seek_apply_job = None  # after-Job für Hauptthread-Seek (serialisiert)

        # NEU: VLC-Event-Callbacks speichern für sauberes Detach
        self._vlc_callbacks = {}

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

    def _schedule_gui(self, fn: Callable[[], None]) -> None:
        """VLC ruft Event-Handler in Fremdthreads auf — Tk nur im Hauptthread anfassen."""
        def wrapper():
            try:
                if not self.winfo_exists():
                    return
                fn()
            except tk.TclError:
                pass
            except Exception as e:
                print(f"Cutter GUI-Update: {e}")

        try:
            self.after(0, wrapper)
        except tk.TclError:
            pass

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
            # NEU: Verwende Service für Video-Info
            video_info = self.cutter_service.get_video_info(self.video_path)
            self.total_duration_ms = video_info.duration_ms
            self.fps = video_info.fps
            print(f"Cutter: Video geladen. Dauer: {self.total_duration_ms}ms, FPS: {self.fps}")

            # NEU: Keyframes im Hintergrund laden
            threading.Thread(
                target=self.cutter_service.get_keyframes,
                args=(self.video_path,),
                daemon=True
            ).start()
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

        # Events binden (mit gespeicherten Callbacks für sauberes Detach)
        events = self.media_player.event_manager()

        self._vlc_callbacks['end_reached'] = self._on_end_reached_vlc
        self._vlc_callbacks['time_changed'] = self._on_time_changed_vlc
        self._vlc_callbacks['playing'] = self._on_vlc_playing_vlc
        self._vlc_callbacks['paused'] = self._on_vlc_paused_vlc
        self._vlc_callbacks['stopped'] = self._on_vlc_stopped_vlc

        events.event_attach(vlc.EventType.MediaPlayerEndReached, self._vlc_callbacks['end_reached'])
        events.event_attach(vlc.EventType.MediaPlayerTimeChanged, self._vlc_callbacks['time_changed'])
        events.event_attach(vlc.EventType.MediaPlayerPlaying, self._vlc_callbacks['playing'])
        events.event_attach(vlc.EventType.MediaPlayerPaused, self._vlc_callbacks['paused'])
        events.event_attach(vlc.EventType.MediaPlayerStopped, self._vlc_callbacks['stopped'])

        # UI initialisieren
        self._on_time_changed_ui()  # Zeit-Label initial setzen (Hauptthread)
        self._draw_custom_progress()
        self._set_processing(False)  # Alle Buttons aktivieren

        self.media_player.play()  # Autostart
        self.after(100, self.media_player.pause)  # Aber sofort pausieren
        self.play_pause_btn.config(text="▶")

    # _get_video_info, _find_keyframe_before, _find_keyframe_after ENTFERNT
    # --> Ersetzt durch VideoCutterService

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

        self.buttons["split"] = tk.Button(
            apply_button_frame, text="Teilung planen", command=self._on_split_queue
        )
        self.buttons["split"].pack(side=tk.LEFT, padx=5, ipady=5)

        self.buttons["apply"] = tk.Button(
            apply_button_frame,
            text="Trim zur Warteschlange",
            command=self._on_apply_queue,
            font=("Arial", 10, "bold"),
            bg="#4CAF50",
            fg="white",
        )
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

    def _on_time_changed_vlc(self, event):
        """VLC-Thread: nur in die Tk-Queue einreihen."""
        self._schedule_gui(self._on_time_changed_ui)

    def _on_time_changed_ui(self):
        """Hauptthread: Zeit und Playhead aus dem Player lesen und UI aktualisieren."""
        if self.is_processing or self.is_dragging_playhead:
            return
        if not self.media_player:
            return

        current_time = self.media_player.get_time()
        if current_time < 0:
            current_time = 0

        self.time_label.config(
            text=f"{self._format_time(current_time)} / {self._format_time(self.total_duration_ms)}"
        )
        self._draw_playhead(current_time)

    def _on_vlc_playing_vlc(self, event):
        self._schedule_gui(lambda: self.play_pause_btn.config(text="⏸"))

    def _on_vlc_paused_vlc(self, event):
        self._schedule_gui(lambda: self.play_pause_btn.config(text="▶"))

    def _on_vlc_stopped_vlc(self, event):
        self._schedule_gui(lambda: self.play_pause_btn.config(text="▶"))

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
        if self.is_processing: return
        self.is_dragging_playhead = True  # Beginne Drag
        self._seek_from_event(event, immediate=True)  # Bei Klick sofort seekn

    def _on_progress_drag(self, event):
        """Aktualisiert Position während des Ziehens."""
        if self.is_processing: return
        if not self.is_dragging_playhead: return
        self._seek_from_event(event, immediate=False)  # Bei Drag debounced

    def _on_progress_release(self, event):
        """Beendet das Ziehen."""
        if self.is_processing:
            self.is_dragging_playhead = False
            return
        self.is_dragging_playhead = False
        self._seek_from_event(event, immediate=True)  # Bei Release final seekn

    def _seek_from_event(self, event, immediate=False):
        """
        Hilfsmethode: Berechnet Zeit aus Klick-Event und springt dorthin.

        Args:
            event: Das Maus-Event
            immediate: Wenn True, wird sofort geseekt. Wenn False, wird debounced (für Drag).
        """
        width = self.custom_progress_canvas.winfo_width()
        if width == 0 or self.total_duration_ms == 0: return

        click_x = max(0, min(event.x, width))
        pos_perc = click_x / width
        target_time_ms = int(pos_perc * self.total_duration_ms)

        # Sofortiges visuelles Feedback (ohne auf VLC zu warten)
        self._draw_playhead(target_time_ms)
        self.time_label.config(
            text=f"{self._format_time(target_time_ms)} / {self._format_time(self.total_duration_ms)}")

        if immediate:
            # Sofort seekn (z.B. bei Klick oder Release)
            self._perform_seek(target_time_ms)
        else:
            # Debounced seekn (z.B. beim Dragging)
            self._debounced_seek(target_time_ms)

    def _debounced_seek(self, target_time_ms: int):
        """
        Führt ein Seek mit Debouncing durch (verzögert, um UI-Freeze zu vermeiden).
        Wenn mehrere Seeks schnell hintereinander kommen, wird nur der letzte ausgeführt.
        """
        # Abbreche vorherigen Timer
        if self._seek_debounce_timer is not None:
            try:
                self.after_cancel(self._seek_debounce_timer)
            except:
                pass

        # Starte neuen Timer (50ms Verzögerung)
        self._seek_debounce_timer = self.after(50, lambda: self._perform_seek(target_time_ms))

    def _perform_seek(self, target_time_ms: int):
        """Seek nur im Tk-Hauptthread; überlappende Aufrufe werden zusammengefasst (last wins)."""
        self._pending_seek_ms = target_time_ms
        if self._seek_apply_job is not None:
            try:
                self.after_cancel(self._seek_apply_job)
            except tk.TclError:
                pass
            self._seek_apply_job = None

        def run():
            self._seek_apply_job = None
            self._apply_pending_seek()

        try:
            self._seek_apply_job = self.after(0, run)
        except tk.TclError:
            self._seek_apply_job = None

    def _apply_pending_seek(self):
        if not self.winfo_exists() or not self.media_player:
            return
        t = self._pending_seek_ms
        if t is None:
            return
        try:
            self.media_player.set_time(t)
        except Exception as e:
            print(f"Cutter set_time: {e}")
        self.after(30, self._update_ui_after_seek)

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
        """
        Springt 1 Frame vor oder zurück UND pausiert die Wiedergabe.
        Optimiert für schnelles, wiederholtes Drücken ohne UI-Freeze.
        """
        if self.is_processing or self.fps == 0: return

        # 1. Player sicher pausieren (nur beim ersten Mal)
        if self.media_player.is_playing():
            self.media_player.pause()
            self.play_pause_btn.config(text="▶")

        # 2. Zeit berechnen
        step_ms = (1000 / self.fps) * direction
        current_time = self.media_player.get_time()
        new_time = max(0, min(self.total_duration_ms, current_time + step_ms))

        # 3. Sofortiges visuelles Feedback
        self._draw_playhead(int(new_time))
        self.time_label.config(
            text=f"{self._format_time(int(new_time))} / {self._format_time(self.total_duration_ms)}")

        # 4. Debounced Seek für bessere Performance bei schnellen Tastendrücken
        self._debounced_seek(int(new_time))

    def _update_ui_after_seek(self):
        """Aktualisiert die UI nach einem Seek-Vorgang."""
        try:
            if not self.winfo_exists() or not self.media_player:
                return

            current_time = self.media_player.get_time()
            if current_time >= 0:
                self._draw_playhead(current_time)
                self.time_label.config(
                    text=f"{self._format_time(current_time)} / {self._format_time(self.total_duration_ms)}")
        except Exception as e:
            print(f"Fehler in _update_ui_after_seek: {e}")

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

    def _on_apply_queue(self):
        """Legt einen Trim in die App-Warteschlange (ohne FFmpeg)."""
        if self.is_processing:
            return

        if self.start_time_ms is None and self.end_time_ms is None:
            messagebox.showinfo(
                "Keine Änderung",
                "Sie haben keinen IN- oder OUT-Punkt gesetzt. Es gibt nichts zu schneiden.",
                parent=self,
            )
            return

        start_ms = self.start_time_ms if self.start_time_ms is not None else 0
        end_ms = self.end_time_ms if self.end_time_ms is not None else self.total_duration_ms
        if self.start_time_ms is not None and self.end_time_ms is not None:
            if end_ms < start_ms:
                start_ms, end_ms = end_ms, start_ms

        if self.media_player.is_playing():
            self.media_player.stop()
        self.media_player.set_media(None)

        self._close_dialog_with_result(
            {"action": "queue_trim", "start_ms": start_ms, "end_ms": end_ms}
        )

    def _on_split_queue(self):
        """Legt einen Split in die App-Warteschlange (ohne FFmpeg)."""
        if self.is_processing:
            return

        split_time_ms = self.media_player.get_time()

        if split_time_ms <= 100 or split_time_ms >= (self.total_duration_ms - 100):
            messagebox.showwarning(
                "Ungültiger Split-Punkt",
                "Sie können nicht zu nah am Anfang oder Ende des Clips teilen.",
                parent=self,
            )
            return

        if self.media_player.is_playing():
            self.media_player.stop()
        self.media_player.set_media(None)

        self._close_dialog_with_result({"action": "queue_split", "split_ms": split_time_ms})

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
                self.after(100, self._on_time_changed_ui)  # UI Update erzwingen
        except Exception as e:
            print(f"Fehler beim Neuladen des Mediums: {e}")

    def _close_dialog_with_result(self, result: dict):
        """Schließt den Dialog und meldet das Ergebnis an die App (z. B. Warteschlange)."""
        self._set_processing(False)
        self._cleanup()
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()
        self.on_complete_callback(result)

    def _cleanup(self):
        """Stoppt den Player und gibt VLC-Ressourcen frei."""
        # Cleanup für Debounce-Timer und Seek-Queue
        if hasattr(self, '_seek_debounce_timer') and self._seek_debounce_timer is not None:
            try:
                self.after_cancel(self._seek_debounce_timer)
                self._seek_debounce_timer = None
            except tk.TclError:
                pass
        if getattr(self, '_seek_apply_job', None) is not None:
            try:
                self.after_cancel(self._seek_apply_job)
                self._seek_apply_job = None
            except tk.TclError:
                pass
        self._pending_seek_ms = None

        # VLC-Player cleanup
        if hasattr(self, 'media_player') and self.media_player:
            try:
                # Events entfernen - VLC event_detach nimmt nur EventType als Argument
                if hasattr(self, '_vlc_callbacks') and self._vlc_callbacks:
                    events = self.media_player.event_manager()
                    if 'end_reached' in self._vlc_callbacks:
                        events.event_detach(vlc.EventType.MediaPlayerEndReached)
                    if 'time_changed' in self._vlc_callbacks:
                        events.event_detach(vlc.EventType.MediaPlayerTimeChanged)
                    if 'playing' in self._vlc_callbacks:
                        events.event_detach(vlc.EventType.MediaPlayerPlaying)
                    if 'paused' in self._vlc_callbacks:
                        events.event_detach(vlc.EventType.MediaPlayerPaused)
                    if 'stopped' in self._vlc_callbacks:
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

    def _on_end_reached_vlc(self, event):
        """VLC-Thread: Ende der Wiedergabe — UI/Player nur im Hauptthread."""
        self._schedule_gui(self._on_end_reached_ui)

    def _on_end_reached_ui(self):
        """Hauptthread: Player stoppen und Anzeige zurücksetzen."""
        if not self.media_player:
            return
        self.play_pause_btn.config(text="▶")

        def after_stop():
            if not self.winfo_exists() or not self.media_player:
                return
            try:
                self.media_player.stop()
            except Exception as e:
                print(f"Cutter stop am Ende: {e}")
            self._draw_playhead(0)
            self.time_label.config(
                text=f"{self._format_time(0)} / {self._format_time(self.total_duration_ms)}"
            )

        self.after(50, after_stop)
