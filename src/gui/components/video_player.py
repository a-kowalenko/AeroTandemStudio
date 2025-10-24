import tkinter as tk
import vlc
import sys


# Stellt sicher, dass das vlc-Modul gefunden wird, falls es nicht im Standard-PYTHONPATH liegt.
# Passen Sie 'VLC_PATH' an, wenn Sie eine portable VLC-Version verwenden.
# try:
#   	import vlc
# except ImportError:
#   	# VLC_PATH = r"C:\Program Files\VideoLAN\VLC"
#   	# if VLC_PATH not in sys.path:
#   	# 	sys.path.append(VLC_PATH)
#   	import vlc


class VideoPlayer:
    """
    Eine Tkinter-Komponente, die ein Video-Panel, Steuerelemente
    und eine benutzerdefinierte Fortschrittsanzeige mit Clip-Markierungen darstellt.
    """

    def __init__(self, parent, app_instance):
        self.parent = parent
        self.app = app_instance
        self.clip_durations = []
        self.total_duration_ms = 0
        self._updater_job = None

        # --- Status für manuellen Vollbildmodus ---
        self.fullscreen_window = None
        self._is_fullscreen = False
        self._fullscreen_resume_state = {"time": 0, "was_playing": False}
        # ---

        # --- NEU: Referenzen für Vollbild-Steuerelemente ---
        self.fs_controls_frame = None
        self.fs_play_pause_btn = None
        self.fs_time_label = None
        self.fs_volume_scale = None
        self.fs_progress_canvas = None
        self.fs_progress_bar = None
        self.fs_progress_bg = None
        self._fs_volume_block = False  # Für Lautstärke-Sync
        self._main_volume_block = False  # Für Lautstärke-Sync
        # ---

        # VLC-Instanz und Media Player initialisieren
        try:
            self.vlc_instance = vlc.Instance()
            self.media_player = self.vlc_instance.media_player_new()
        except Exception as e:
            print(f"Fehler beim Initialisieren von VLC: {e}")
            print("Stellen Sie sicher, dass VLC (64-bit) installiert und das 'python-vlc' Paket verfügbar ist.")
            self.vlc_instance = None
            self.media_player = None
            return

        self.frame = tk.Frame(parent, bg="#333")

        # Video-Anzeigebereich (Schwarzer Kasten)
        self.video_frame = tk.Frame(self.frame, bg="black", height=250)
        self.video_frame.pack(fill="x", padx=5, pady=5)

        # VLC an das Video-Frame binden
        if sys.platform == "win32":
            self.media_player.set_hwnd(self.video_frame.winfo_id())
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(self.video_frame.winfo_id())
        else:  # Linux
            self.media_player.set_xwindow(self.video_frame.winfo_id())

        # Standard-Lautstärke setzen
        self.media_player.audio_set_volume(50)

        # Steuerungs-Frame
        self.controls_frame = tk.Frame(self.frame, bg="#333")
        self.controls_frame.pack(fill="x", padx=5, pady=(0, 5))

        # Play/Pause Button
        self.play_pause_btn = tk.Button(
            self.controls_frame, text="▶", font=("Arial", 14),
            command=self._toggle_play_pause, state="disabled",
            width=3
        )
        self.play_pause_btn.pack(side="left", padx=5)

        # --- Rechte Steuerelemente (in umgekehrter Reihenfolge gepackt) ---

        # Vollbild-Button (ganz rechts)
        self.fullscreen_btn = tk.Button(
            self.controls_frame, text="⛶",  # Unicode für Vollbild
            font=("Arial", 12),
            command=self._toggle_fullscreen, state="disabled",
            width=3, bg="#333", fg="white", highlightthickness=0, relief="flat"
        )
        self.fullscreen_btn.pack(side="right", padx=(5, 5))

        # Lautstärkeregler (rechts)
        self.volume_scale = tk.Scale(
            self.controls_frame,
            from_=0,
            to=100,
            orient=tk.HORIZONTAL,
            command=self._on_main_volume_change,  # GEÄNDERT
            bg="#333",
            fg="white",
            highlightthickness=0,
            troughcolor="#555",
            width=10,  # Dünnerer Regler
            length=80,  # Kurze Länge
            showvalue=False  # Keine %-Anzeige
        )
        self.volume_scale.set(50)
        self.volume_scale.pack(side="right", padx=(0, 5))

        # Zeit-Label (Aktuell / Gesamt)
        self.time_label = tk.Label(
            self.controls_frame, text="--:-- / --:--",
            font=("Arial", 10), fg="white", bg="#333"
        )
        self.time_label.pack(side="right", padx=(0, 10))

        # Benutzerdefinierte Fortschrittsanzeige (füllt den Rest)
        self.progress_canvas = tk.Canvas(
            self.controls_frame, height=25, bg="#555",
            highlightthickness=0, cursor="hand2"
        )
        self.progress_canvas.pack(fill="x", expand=True, side="left", padx=5)

        # Hintergrund der Leiste
        self.progress_bg = self.progress_canvas.create_rectangle(
            0, 5, 0, 20, fill="#444", tags="bg"
        )
        # Fortschrittsbalken (blau)
        self.progress_bar = self.progress_canvas.create_rectangle(
            0, 5, 0, 20, fill="#0078d4", tags="progress"
        )

        # Event-Bindungen
        self.progress_canvas.bind("<Configure>", self._on_resize_canvas)
        self.progress_canvas.bind("<Button-1>", self._on_progress_click)

        # VLC Event-Manager
        self.event_manager = self.media_player.event_manager()
        self.event_manager.event_attach(vlc.EventType.MediaPlayerEndReached, self._on_end_reached)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerPlaying, self._on_player_playing)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerPaused, self._on_player_paused)
        self.event_manager.event_attach(vlc.EventType.MediaPlayerStopped, self._on_player_stopped)

    def pack(self, **kwargs):
        """Packt das Haupt-Frame des Players."""
        if not self.vlc_instance:
            # Wenn VLC nicht geladen werden konnte, zeige eine Fehlermeldung statt des Players
            error_label = tk.Label(
                self.parent,
                text="Fehler: VLC konnte nicht initialisiert werden.\n"
                     "Stellen Sie sicher, dass VLC (64-bit) installiert ist\n"
                     "und das 'python-vlc' Paket existiert.",
                fg="red", bg="#f0f0f0", justify="left",
                font=("Arial", 10, "bold"),
                relief="solid", borderwidth=1, padx=10, pady=10
            )
            error_label.pack(**kwargs)
            return

        self.frame.pack(**kwargs)
        # Stellen Sie sicher, dass die Canvas-Größe beim Packen aktualisiert wird
        self.frame.update_idletasks()
        self._on_resize_canvas(None)

    def load_video(self, video_path, clip_durations_sec):
        """
        Lädt ein neues Video in den Player.

        :param video_path: Pfad zur kombinierten Videodatei.
        :param clip_durations_sec: Liste der Dauern (in Sekunden) der einzelnen Clips.
        """
        if not self.media_player:
            return

        self.clip_durations = clip_durations_sec
        self.total_duration_ms = sum(self.clip_durations) * 1000

        try:
            media = self.vlc_instance.media_new(video_path)
            self.media_player.set_media(media)

            # UI zurücksetzen
            self.play_pause_btn.config(text="▶", state="normal")
            self.fullscreen_btn.config(state="normal")

            # Lautstärke zurücksetzen (visuell und intern)
            self.volume_scale.set(50)
            self.media_player.audio_set_volume(50)

            self.time_label.config(text=f"00:00 / {self._format_time(self.total_duration_ms)}")

            # Warten Sie kurz, bis die Canvas gezeichnet wurde, bevor Sie Marker setzen
            self.parent.after(100, lambda: self._draw_clip_markers(fullscreen=False))

            self._start_updater()

        except Exception as e:
            print(f"Fehler beim Laden des Videos in den VLC Player: {e}")
            self.play_pause_btn.config(state="disabled")
            self.fullscreen_btn.config(state="disabled")

    def unload_video(self):
        """Entfernt das Video und setzt den Player zurück."""
        if not self.media_player:
            return

        if self._is_fullscreen:
            self._exit_fullscreen()

        if self.media_player.is_playing():
            self.media_player.stop()

        self.media_player.set_media(None)

        self.clip_durations = []
        self.total_duration_ms = 0

        self.play_pause_btn.config(text="▶", state="disabled")
        self.fullscreen_btn.config(state="disabled")
        self.time_label.config(text="--:-- / --:--")
        self.volume_scale.set(50)

        self._stop_updater()
        self._update_progress_ui()  # Setzt den Balken auf 0
        self._draw_clip_markers(fullscreen=False)  # Löscht die Marker

    def _toggle_play_pause(self):
        """Wechselt zwischen Wiedergabe und Pause."""
        if not self.media_player:
            return

        if self.media_player.is_playing():
            self.media_player.pause()
        else:
            self.media_player.play()

    # --- NEU: Geteilte Lautstärke-Handler ---
    def _on_main_volume_change(self, volume_str):
        """Wird aufgerufen, wenn der HAUPT-Lautstärkeregler bewegt wird."""
        if self._main_volume_block:
            return

        volume = int(float(volume_str))
        self.media_player.audio_set_volume(volume)

        if self.fs_volume_scale:
            self._fs_volume_block = True
            self.fs_volume_scale.set(volume)
            self._fs_volume_block = False

    def _on_fs_volume_change(self, volume_str):
        """Wird aufgerufen, wenn der VOLLBILD-Lautstärkeregler bewegt wird."""
        if self._fs_volume_block:
            return

        volume = int(float(volume_str))
        self.media_player.audio_set_volume(volume)

        self._main_volume_block = True
        self.volume_scale.set(volume)
        self._main_volume_block = False

    # ---

    # --- ANGEPASSTE VOLLBILD-LOGIK ---

    def _toggle_fullscreen(self):
        """Schaltet den manuellen Vollbildmodus an oder aus."""
        if not self.media_player:
            return

        if self._is_fullscreen:
            self._exit_fullscreen()
        else:
            self._enter_fullscreen()

    def _enter_fullscreen(self):
        """Erstellt ein Toplevel-Fenster und schaltet in den Vollbildmodus."""
        if self.fullscreen_window:
            return

        self._is_fullscreen = True

        self._fullscreen_resume_state["was_playing"] = self.media_player.is_playing()
        self._fullscreen_resume_state["time"] = self.media_player.get_time()

        if self._fullscreen_resume_state["time"] < 0:
            self._fullscreen_resume_state["time"] = 0

        if self.media_player.get_state() != vlc.State.Stopped:
            self.media_player.stop()

        # 1. Neues Toplevel-Fenster erstellen
        self.fullscreen_window = tk.Toplevel(self.parent)
        self.fullscreen_window.title("Vollbild-Vorschau")

        # 2. Vollbild-Attribute setzen
        self.fullscreen_window.attributes('-fullscreen', True)
        self.fullscreen_window.configure(bg='black')

        # 3. Ein Frame für das Video im neuen Fenster
        video_panel = tk.Frame(self.fullscreen_window, bg='black')
        video_panel.pack(fill=tk.BOTH, expand=True)

        # 4. Events binden
        self.fullscreen_window.bind("<Escape>", self._on_escape_fullscreen)
        self.fullscreen_window.bind("<space>", self._on_spacebar_press)  # HINZUGEFÜGT
        self.fullscreen_window.protocol("WM_DELETE_WINDOW", self._exit_fullscreen)

        # --- NEU: Vollbild-Steuerelemente erstellen ---
        self.fs_controls_frame = tk.Frame(self.fullscreen_window, bg="#333")

        self.fs_play_pause_btn = tk.Button(
            self.fs_controls_frame, text="▶", font=("Arial", 14),
            command=self._toggle_play_pause, width=3
        )
        self.fs_play_pause_btn.pack(side="left", padx=5)

        # Vollbild beenden Button (ersetzt den 'Vollbild' Button)
        fs_exit_btn = tk.Button(
            self.fs_controls_frame, text="X",  # Simples X
            font=("Arial", 12, "bold"),
            command=self._exit_fullscreen,
            width=3, bg="#E74C3C", fg="white", highlightthickness=0, relief="flat"
        )
        fs_exit_btn.pack(side="right", padx=(5, 5))

        self.fs_volume_scale = tk.Scale(
            self.fs_controls_frame, from_=0, to=100, orient=tk.HORIZONTAL,
            command=self._on_fs_volume_change,  # NEUER Handler
            bg="#333", fg="white", highlightthickness=0,
            troughcolor="#555", width=10, length=80, showvalue=False
        )
        self.fs_volume_scale.set(self.volume_scale.get())  # Aktuelle Lautstärke übernehmen
        self.fs_volume_scale.pack(side="right", padx=(0, 5))

        self.fs_time_label = tk.Label(
            self.fs_controls_frame, text="--:-- / --:--",
            font=("Arial", 10), fg="white", bg="#333"
        )
        self.fs_time_label.pack(side="right", padx=(0, 10))

        self.fs_progress_canvas = tk.Canvas(
            self.fs_controls_frame, height=25, bg="#555",
            highlightthickness=0, cursor="hand2"
        )
        self.fs_progress_canvas.pack(fill="x", expand=True, side="left", padx=5)

        self.fs_progress_bg = self.fs_progress_canvas.create_rectangle(
            0, 5, 0, 20, fill="#444", tags="bg"
        )
        self.fs_progress_bar = self.fs_progress_canvas.create_rectangle(
            0, 5, 0, 20, fill="#0078d4", tags="progress"
        )

        self.fs_progress_canvas.bind("<Configure>", self._on_fullscreen_resize_canvas)
        self.fs_progress_canvas.bind("<Button-1>", self._on_fullscreen_progress_click)

        self.fs_controls_frame.pack(side="bottom", fill="x", padx=5, pady=5)
        # --- Ende Steuerelemente ---

        # 5. VLC an das NEUE Fenster binden (mit Verzögerung)
        self.fullscreen_window.after(
            100,
            lambda: self._complete_fullscreen_enter(video_panel)
        )

    def _complete_fullscreen_enter(self, video_panel):
        """Hilfsmethode: Bindet VLC an das Vollbildfenster und setzt Wiedergabe fort."""
        if not self.fullscreen_window:
            return

        video_panel.update_idletasks()

        if sys.platform == "win32":
            self.media_player.set_hwnd(video_panel.winfo_id())
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(video_panel.winfo_id())
        else:
            self.media_player.set_xwindow(video_panel.winfo_id())

        if self._fullscreen_resume_state["was_playing"]:
            self.media_player.play()

            def seek_to_time():
                if self.media_player.is_playing():
                    self.media_player.set_time(self._fullscreen_resume_state["time"])
                else:
                    self.parent.after(100, seek_to_time)

            self.parent.after(100, seek_to_time)

    def _on_escape_fullscreen(self, event=None):
        """Event-Handler für die Escape-Taste."""
        self._exit_fullscreen()

    # NEUE METHODE
    def _on_spacebar_press(self, event=None):
        """Handhabt das Drücken der Leertaste im Vollbildmodus."""
        self._toggle_play_pause()
        return "break"  # Verhindert, dass der Tastendruck "durchfällt"

    def _exit_fullscreen(self):
        """Beendet den Vollbildmodus und stellt die GUI wieder her."""
        if not self.fullscreen_window:
            return

        self._is_fullscreen = False

        was_playing = self.media_player.is_playing()
        current_time = self.media_player.get_time()

        if current_time < 0:
            current_time = 0

        if self.media_player.get_state() != vlc.State.Stopped:
            self.media_player.stop()

        # 1. Vollbild-Fenster zerstören (zerstört auch alle fs_... Widgets)
        self.fullscreen_window.destroy()

        # --- NEU: Alle Referenzen auf fs_... Widgets löschen ---
        self.fullscreen_window = None
        self.fs_controls_frame = None
        self.fs_play_pause_btn = None
        self.fs_time_label = None
        self.fs_volume_scale = None
        self.fs_progress_canvas = None
        self.fs_progress_bar = None
        self.fs_progress_bg = None
        # ---

        self.video_frame.update_idletasks()

        # 2. VLC zurück an das URSPRÜNGLICHE Frame binden
        if sys.platform == "win32":
            self.media_player.set_hwnd(self.video_frame.winfo_id())
        elif sys.platform == "darwin":
            self.media_player.set_nsobject(self.video_frame.winfo_id())
        else:
            self.media_player.set_xwindow(self.video_frame.winfo_id())

        # 3. Wiedergabe fortsetzen (mit kleiner Verzögerung)
        if was_playing:
            self.media_player.play()

            def seek_to_time():
                if self.media_player.is_playing():
                    self.media_player.set_time(current_time)
                else:
                    self.parent.after(100, seek_to_time)

            self.parent.after(100, seek_to_time)

    # --- ENDE VOLLBILD-LOGIK ---

    def _on_progress_click(self, event):
        """Springt zur angeklickten Position im Video (Hauptfenster)."""
        self._handle_progress_click(event, self.progress_canvas)

    # --- NEU: Geteilte Handler für Progress Bar ---
    def _on_fullscreen_progress_click(self, event):
        """Springt zur angeklickten Position im Video (Vollbild)."""
        self._handle_progress_click(event, self.fs_progress_canvas)

    def _handle_progress_click(self, event, canvas):
        """Logik für das Klicken auf eine Fortschrittsanzeige."""
        if not self.media_player or self.total_duration_ms == 0 or not canvas:
            return

        canvas_width = canvas.winfo_width()
        if canvas_width > 0:
            position_percent = max(0, min(1, event.x / canvas_width))
            self.media_player.set_position(position_percent)
            self._update_progress_ui()  # UI sofort aktualisieren

    def _on_resize_canvas(self, event):
        """Zeichnet die Canvas-Elemente bei Größenänderung neu (Hauptfenster)."""
        self._handle_resize_canvas(event, self.progress_canvas, self.progress_bg, fullscreen=False)

    def _on_fullscreen_resize_canvas(self, event):
        """Zeichnet die Canvas-Elemente bei Größenänderung neu (Vollbild)."""
        self._handle_resize_canvas(event, self.fs_progress_canvas, self.fs_progress_bg, fullscreen=True)

    def _handle_resize_canvas(self, event, canvas, bg_rect, fullscreen=False):
        """Logik für die Größenänderung einer Fortschrittsanzeige."""
        if not canvas:
            return

        width = canvas.winfo_width()
        height = canvas.winfo_height()

        canvas.coords(bg_rect, 0, 5, width, 20)
        self._update_progress_ui()
        self._draw_clip_markers(fullscreen=fullscreen)

    def _draw_clip_markers(self, fullscreen=False):
        """Zeichnet die vertikalen Trennlinien für die Clips."""

        # Wähle die richtige Canvas
        if fullscreen:
            canvas = self.fs_progress_canvas
        else:
            canvas = self.progress_canvas

        if not canvas:
            return

        canvas.delete("clip_marker")

        if not self.clip_durations or self.total_duration_ms == 0:
            return

        canvas_width = canvas.winfo_width()
        if canvas_width <= 0:
            return  # Canvas noch nicht gezeichnet

        current_time_sec = 0
        for duration_sec in self.clip_durations[:-1]:  # Letzter Marker ist nicht nötig
            current_time_sec += duration_sec
            position_percent = current_time_sec / (self.total_duration_ms / 1000)
            x_pos = int(position_percent * canvas_width)

            canvas.create_line(
                x_pos, 5, x_pos, 20,
                fill="white", width=2, tags="clip_marker"
            )

    # ---

    def _start_updater(self):
        """Startet die periodische Aktualisierung der Fortschrittsanzeige."""
        if self._updater_job:
            self.parent.after_cancel(self._updater_job)

        self._updater_job = self.parent.after(250, self._update_progress_ui)

    def _stop_updater(self):
        """Stoppt die periodische Aktualisierung."""
        if self._updater_job:
            self.parent.after_cancel(self._updater_job)
            self._updater_job = None

    def _update_progress_ui(self):
        """Aktualisiert die Fortschrittsanzeige und die Zeit-Labels (BEIDE SÄTZE)."""
        if not self.media_player:
            return

        current_time_ms = self.media_player.get_time()

        if self.total_duration_ms == 0:
            media_duration_ms = self.media_player.get_length()
            if media_duration_ms > 0:
                self.total_duration_ms = media_duration_ms

        if self.total_duration_ms > 0:
            position_percent = current_time_ms / self.total_duration_ms
        else:
            position_percent = 0

        current_time_str = self._format_time(current_time_ms)
        total_time_str = self._format_time(self.total_duration_ms)

        # Haupt-UI aktualisieren
        self.time_label.config(text=f"{current_time_str} / {total_time_str}")
        canvas_width = self.progress_canvas.winfo_width()
        if canvas_width > 0:
            progress_x = int(canvas_width * position_percent)
            self.progress_canvas.coords(self.progress_bar, 0, 5, progress_x, 20)

        # Vollbild-UI aktualisieren (falls vorhanden)
        if self._is_fullscreen and self.fs_time_label and self.fs_progress_canvas:
            self.fs_time_label.config(text=f"{current_time_str} / {total_time_str}")
            fs_canvas_width = self.fs_progress_canvas.winfo_width()
            if fs_canvas_width > 0:
                fs_progress_x = int(fs_canvas_width * position_percent)
                self.fs_progress_canvas.coords(self.fs_progress_bar, 0, 5, fs_progress_x, 20)

        if self.media_player.is_playing():
            self._start_updater()

    def _format_time(self, ms):
        """Formatiert Millisekunden in MM:SS."""
        if ms < 0:
            ms = 0

        total_seconds = int(ms / 1000)
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    # --- VLC Event Callbacks (Aktualisiert beide Button-Sätze) ---

    def _on_player_playing(self, event):
        self.play_pause_btn.config(text="⏸")
        if self.fs_play_pause_btn:
            self.fs_play_pause_btn.config(text="⏸")
        self._start_updater()

    def _on_player_paused(self, event):
        self.play_pause_btn.config(text="▶")
        if self.fs_play_pause_btn:
            self.fs_play_pause_btn.config(text="▶")
        self._stop_updater()

    def _on_player_stopped(self, event):
        # Ignoriere 'Stopped'-Events, die wir selbst ausgelöst haben (im Vollbildmodus)
        if self._is_fullscreen:
            # Aktualisiere aber den Button-Text, falls Stop manuell im FS ausgelöst wurde
            if self.fs_play_pause_btn:
                self.fs_play_pause_btn.config(text="▶")
            return

        self.play_pause_btn.config(text="▶")
        self._stop_updater()

        self.time_label.config(text=f"00:00 / {self._format_time(self.total_duration_ms)}")
        self.progress_canvas.coords(self.progress_bar, 0, 5, 0, 20)

    def _on_end_reached(self, event):
        """Wird aufgerufen, wenn das Video zu Ende ist."""
        if self._is_fullscreen:
            self._exit_fullscreen()

        self.play_pause_btn.config(text="▶")
        self._stop_updater()

        self.media_player.set_position(0)
        self.parent.after(50, lambda: self.media_player.stop())

