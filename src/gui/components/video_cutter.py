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
import multiprocessing

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
from src.utils.hardware_acceleration import HardwareAccelerationDetector
from src.utils.config import ConfigManager


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

        # Lade Config und Hardware-Acceleration
        self.config_manager = ConfigManager()
        self.config = self.config_manager.get_settings()
        self.hw_detector = HardwareAccelerationDetector()
        self.hw_info = self.hw_detector.detect_hardware() if self.config.get('hardware_acceleration_enabled', True) else None

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
        self._seek_debounce_timer = None  # NEU: Timer für Debouncing beim Seek

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
            "-show_streams", "-show_format", video_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                creationflags=SUBPROCESS_CREATE_NO_WINDOW)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        format_info = data.get("format", {})

        video_stream = next((s for s in streams if s['codec_type'] == 'video'), None)
        audio_stream = next((s for s in streams if s['codec_type'] == 'audio'), None)

        if not video_stream:
            raise ValueError("Kein Video-Stream gefunden.")

        # Dauer
        duration_s_str = video_stream.get('duration') or format_info.get('duration', '0')
        duration_ms = int(float(duration_s_str) * 1000)

        # FPS
        r_frame_rate = video_stream.get('r_frame_rate', '30/1')
        try:
            num, den = map(int, r_frame_rate.split('/'))
            fps = num / den if den != 0 else 30.0
        except:
            fps = 30.0

        # NEU: Detaillierte Video-Parameter erfassen
        video_info = {
            "duration_ms": duration_ms,
            "fps": fps,
            "width": video_stream.get('width', 1920),
            "height": video_stream.get('height', 1080),
            "vcodec": video_stream.get('codec_name', 'h264'),
            "pix_fmt": video_stream.get('pix_fmt', 'yuv420p'),
            "video_bitrate": video_stream.get('bit_rate'),
        }

        # Audio-Parameter (falls vorhanden)
        if audio_stream:
            video_info.update({
                "acodec": audio_stream.get('codec_name', 'aac'),
                "audio_bitrate": audio_stream.get('bit_rate'),
                "sample_rate": audio_stream.get('sample_rate', '48000'),
                "channels": audio_stream.get('channels', 2),
            })
        else:
            video_info.update({
                "acodec": None,
                "audio_bitrate": None,
                "sample_rate": None,
                "channels": None,
            })

        return video_info

    def _find_keyframe_before(self, video_path: str, target_sec: float) -> float:
        """
        Findet den Keyframe VOR der angegebenen Zeit.
        Gibt die Zeit des Keyframes in Sekunden zurück.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "frame=key_frame,pts_time",
            "-of", "json",
            "-read_intervals", f"%+#{int(target_sec * self.fps + 50)}",  # Etwas mehr Frames lesen
            video_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                  creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            data = json.loads(result.stdout)
            frames = data.get("frames", [])

            # Finde den letzten Keyframe vor target_sec
            keyframe_time = 0.0
            for frame in frames:
                if frame.get("key_frame") == 1:
                    pts_time = float(frame.get("pts_time", 0))
                    if pts_time <= target_sec:
                        keyframe_time = pts_time
                    else:
                        break  # Wir sind über target_sec hinaus

            print(f"Keyframe vor {target_sec}s gefunden bei: {keyframe_time}s")
            return keyframe_time

        except Exception as e:
            print(f"Fehler beim Finden des Keyframes: {e}, verwende target_sec")
            return target_sec

    def _find_keyframe_after(self, video_path: str, target_sec: float) -> float:
        """
        Findet den Keyframe NACH der angegebenen Zeit.
        Gibt die Zeit des Keyframes in Sekunden zurück.
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "frame=key_frame,pts_time",
            "-of", "json",
            "-read_intervals", f"{target_sec}%+#{int(self.fps * 5)}",  # 5 Sekunden voraus suchen
            video_path
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                  creationflags=SUBPROCESS_CREATE_NO_WINDOW)
            data = json.loads(result.stdout)
            frames = data.get("frames", [])

            # Finde den ersten Keyframe nach target_sec
            for frame in frames:
                if frame.get("key_frame") == 1:
                    pts_time = float(frame.get("pts_time", 0))
                    if pts_time >= target_sec:
                        print(f"Keyframe nach {target_sec}s gefunden bei: {pts_time}s")
                        return pts_time

            # Falls kein Keyframe gefunden, verwende target_sec
            print(f"Kein Keyframe nach {target_sec}s gefunden, verwende target_sec")
            return target_sec

        except Exception as e:
            print(f"Fehler beim Finden des Keyframes: {e}, verwende target_sec")
            return target_sec

    def _build_encode_cmd(self, input_path: str, video_info: dict, output_path: str,
                         ss: float, duration: float, force_keyframe_at_start: bool = True,
                         use_software_fallback: bool = False) -> list:
        """
        Erstellt einen FFmpeg-Befehl für hochqualitatives Re-Encoding eines Segments
        mit Hardware-Beschleunigung und Multicore-Processing.

        Args:
            input_path: Eingabe-Video
            video_info: Video-Metadaten
            output_path: Ausgabe-Datei
            ss: Start-Zeit in Sekunden
            duration: Dauer in Sekunden
            force_keyframe_at_start: Keyframe am Anfang erzwingen
            use_software_fallback: Erzwingt Software-Encoding (bei HW-Fehlern)
        """
        cmd = ["ffmpeg", "-y"]

        # Hardware-Beschleunigung für Input (Decoding)
        use_hw_accel = (not use_software_fallback and
                       self.config.get('hardware_acceleration_enabled', True) and
                       self.hw_info and
                       self.hw_info.get('available', False))

        if use_hw_accel and self.hw_info.get('hwaccel'):
            # Nur hwaccel, KEIN hwaccel_output_format
            # Das vermeidet Pixel-Format-Probleme
            cmd.extend(['-hwaccel', self.hw_info['hwaccel']])
            if self.hw_info.get('device'):
                cmd.extend(['-hwaccel_device', self.hw_info['device']])

        cmd.extend([
            "-ss", str(ss),
            "-i", input_path,
            "-t", str(duration),
        ])

        # Codec-Auswahl mit Hardware-Beschleunigung
        if use_hw_accel and self.hw_info.get('encoder'):
            # Hardware-Encoder verwenden
            encoder = self.hw_info['encoder']
            cmd.extend(["-c:v", encoder])

            # Hardware-spezifische Parameter
            hw_type = self.hw_info.get('type')
            if hw_type == 'nvidia':
                # NVIDIA NVENC - hochqualitative Presets
                cmd.extend([
                    "-preset", "p7",  # p7 = höchste Qualität (p1=schnellste, p7=beste)
                    "-tune", "hq",    # High Quality
                    "-rc", "vbr",     # Variable Bitrate
                    "-cq", "19",      # Constant Quality (niedriger = besser, 0-51)
                    "-b:v", "0",      # Unlimitierte Bitrate für VBR
                ])
                # NVIDIA bevorzugt yuv420p
                cmd.extend(["-pix_fmt", "yuv420p"])
            elif hw_type == 'intel':
                # Intel QSV - ICQ Mode für beste Qualität
                cmd.extend([
                    "-global_quality", "19",  # 18-23 ist gut (niedriger = besser)
                    "-preset", "veryslow",    # Beste Qualität
                    "-look_ahead", "1",       # Lookahead für bessere Qualität
                ])
                # Intel QSV bevorzugt nv12
                cmd.extend(["-pix_fmt", "nv12"])
            elif hw_type == 'amd':
                # AMD AMF
                cmd.extend([
                    "-quality", "quality",  # Quality mode statt speed
                    "-rc", "cqp",          # Constant QP
                    "-qp_i", "19",         # I-Frame QP
                    "-qp_p", "19",         # P-Frame QP
                ])
                # AMD bevorzugt nv12
                cmd.extend(["-pix_fmt", "nv12"])
            elif hw_type == 'videotoolbox':
                # Apple VideoToolbox
                cmd.extend([
                    "-b:v", "0",           # Variable Bitrate
                    "-q:v", "65",          # Quality (0-100, höher = besser)
                ])
                # VideoToolbox bevorzugt nv12
                cmd.extend(["-pix_fmt", "nv12"])
        else:
            # Software-Encoder mit hoher Qualität
            if video_info['vcodec'] == 'hevc':
                cmd.extend(["-c:v", "libx265"])
            else:
                cmd.extend(["-c:v", "libx264"])

            cmd.extend([
                "-crf", "18",  # Sehr hohe Qualität (18 ist nahezu verlustfrei)
                "-preset", "medium",
            ])

            # Multicore-Processing nur bei Software-Encoding
            if self.config.get('parallel_processing_enabled', True):
                threads = max(1, multiprocessing.cpu_count() - 1)  # Einen Kern für OS freilassen
                cmd.extend(["-threads", str(threads)])

            # Software-Encoder: yuv420p ist sicher
            cmd.extend(["-pix_fmt", "yuv420p"])

        # FPS nur wenn vorhanden und gültig
        if video_info.get('fps') and video_info['fps'] > 0:
            cmd.extend(["-r", str(video_info['fps'])])

        # Keyframe am Anfang erzwingen (wichtig für Concatenation)
        if force_keyframe_at_start:
            cmd.extend(["-force_key_frames", "expr:gte(t,0)"])

        # Audio-Codec
        if video_info.get('acodec'):
            # Verwende korrekte FFmpeg Encoder-Namen
            if video_info['acodec'] == 'aac':
                cmd.extend(["-c:a", "aac"])
            elif video_info['acodec'] == 'mp3':
                cmd.extend(["-c:a", "libmp3lame"])
            elif video_info['acodec'] == 'opus':
                cmd.extend(["-c:a", "libopus"])
            elif video_info['acodec'] == 'vorbis':
                cmd.extend(["-c:a", "libvorbis"])
            else:
                cmd.extend(["-c:a", "aac"])  # Sicherer Fallback

            # Audio-Bitrate
            if video_info.get('audio_bitrate'):
                try:
                    bitrate = int(video_info['audio_bitrate']) // 1000
                    cmd.extend(["-b:a", f"{min(bitrate, 320)}k"])
                except:
                    cmd.extend(["-b:a", "192k"])
            else:
                cmd.extend(["-b:a", "192k"])

            # Audio-Parameter
            if video_info.get('sample_rate'):
                cmd.extend(["-ar", str(video_info['sample_rate'])])
            if video_info.get('channels'):
                cmd.extend(["-ac", str(min(int(video_info['channels']), 2))])
        else:
            cmd.extend(["-an"])  # Kein Audio

        # Timestamp-Handling und Optimierungen
        cmd.extend([
            "-avoid_negative_ts", "make_zero",
            "-fflags", "+genpts",
            "-movflags", "+faststart",
            "-map", "0:v:0?", "-map", "0:a:0?",
            output_path
        ])

        return cmd

    def _encode_segment_robust(self, input_path: str, video_info: dict, output_path: str,
                               ss: float, duration: float, force_keyframe_at_start: bool = True,
                               segment_name: str = "Segment") -> bool:
        """
        Führt Encoding mit automatischem Software-Fallback bei Hardware-Fehlern aus.

        Args:
            input_path: Eingabe-Video
            video_info: Video-Metadaten
            output_path: Ausgabe-Datei
            ss: Start-Zeit in Sekunden
            duration: Dauer in Sekunden
            force_keyframe_at_start: Keyframe am Anfang erzwingen
            segment_name: Name für Logging

        Returns:
            True bei Erfolg, False bei Fehler
        """
        # Erst mit Hardware versuchen
        cmd = self._build_encode_cmd(input_path, video_info, output_path,
                                     ss, duration, force_keyframe_at_start,
                                     use_software_fallback=False)

        print(f"Encode {segment_name}: {' '.join(cmd[:15])}...")  # Erste 15 Argumente
        result = subprocess.run(cmd, capture_output=True, text=True,
                              creationflags=SUBPROCESS_CREATE_NO_WINDOW)

        if result.returncode == 0 and os.path.exists(output_path):
            print(f"✅ {segment_name} erfolgreich (Hardware)")
            return True

        # Bei Fehler: Prüfe ob es ein Hardware-Problem ist
        stderr_lower = result.stderr.lower()
        hw_errors = [
            'incompatible pixel format',
            'impossible to convert',
            'could not open encoder',
            'hwaccel',
            'qsv',
            'nvenc',
            'amf',
            'videotoolbox'
        ]

        is_hw_error = any(err in stderr_lower for err in hw_errors)

        if is_hw_error:
            print(f"⚠️ Hardware-Encoding fehlgeschlagen, versuche Software-Fallback...")
            print(f"   Fehler: {result.stderr[:200]}")

            # Cleanup fehlgeschlagener Output
            if os.path.exists(output_path):
                try:
                    os.remove(output_path)
                except:
                    pass

            # Erneuter Versuch mit Software-Encoding
            cmd_sw = self._build_encode_cmd(input_path, video_info, output_path,
                                           ss, duration, force_keyframe_at_start,
                                           use_software_fallback=True)

            print(f"Encode {segment_name} (Software): {' '.join(cmd_sw[:15])}...")
            result_sw = subprocess.run(cmd_sw, capture_output=True, text=True,
                                      creationflags=SUBPROCESS_CREATE_NO_WINDOW)

            if result_sw.returncode == 0 and os.path.exists(output_path):
                print(f"✅ {segment_name} erfolgreich (Software-Fallback)")
                return True
            else:
                print(f"❌ {segment_name} fehlgeschlagen (auch mit Software)")
                raise subprocess.CalledProcessError(result_sw.returncode, cmd_sw,
                                                   result_sw.stdout, result_sw.stderr)
        else:
            # Kein Hardware-Fehler, anderer Fehler
            raise subprocess.CalledProcessError(result.returncode, cmd,
                                              result.stdout, result.stderr)

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
        """Führt den eigentlichen Seek-Vorgang in einem Thread durch."""
        threading.Thread(
            target=self._set_time_thread_safe,
            args=(target_time_ms,),
            daemon=True
        ).start()

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

    def _set_time_thread_safe(self, target_time_ms: int):
        """
        [THREAD] Setzt die Zeit im VLC-Player mit Timeout-Schutz.
        Optimiert für schnelles Zapping ohne UI-Freeze.
        """
        try:
            # Direkt set_time aufrufen (VLC ist thread-safe)
            # Das Blocking passiert im Thread, nicht im UI-Thread
            self.media_player.set_time(target_time_ms)

            # Kurz warten, damit VLC die Position aktualisiert
            time.sleep(0.02)  # 20ms - minimal aber ausreichend

            # UI-Update nur wenn Fenster noch existiert
            if self.winfo_exists():
                # Update mit kleiner Verzögerung für glatte Darstellung
                self.after(30, self._update_ui_after_seek)

        except Exception as e:
            print(f"Fehler in _set_time_thread_safe: {e}")

    def _update_ui_after_seek(self):
        """Aktualisiert die UI nach einem Seek-Vorgang."""
        try:
            if not self.winfo_exists():
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
        [THREAD] Führt präzisen Cut aus mit Smart-Cut-Technologie.

        Smart-Cut bedeutet:
        - Wenn Cut-Punkte auf Keyframes liegen: Stream-Copy (verlustfrei, schnell)
        - Wenn Cut-Punkte zwischen Keyframes liegen: Re-encode nur die Übergänge
        - Mittelteil wird mit Stream-Copy übernommen (verlustfrei)

        Das getrimmt Video ersetzt das Input-Video.
        """
        temp_output_path = f"{self.video_path}.__temp_cut__.mp4"
        try:
            input_path = self.video_path

            start_sec = start_ms / 1000.0
            end_sec = end_ms / 1000.0
            duration_sec = end_sec - start_sec

            # Video-Info abrufen
            video_info = self._get_video_info(input_path)

            print(f"\n=== SMART CUT START ===")
            print(f"Gewünschter Bereich: {start_sec:.3f}s - {end_sec:.3f}s (Dauer: {duration_sec:.3f}s)")

            # Finde Keyframes um Start und Ende
            self.after(0, lambda: self.status_label.config(text="Analysiere Keyframes..."))
            keyframe_before_start = self._find_keyframe_before(input_path, start_sec)
            keyframe_after_start = self._find_keyframe_after(input_path, start_sec)
            keyframe_before_end = self._find_keyframe_before(input_path, end_sec)
            keyframe_after_end = self._find_keyframe_after(input_path, end_sec)

            print(f"Start: {start_sec:.3f}s (Keyframe davor: {keyframe_before_start:.3f}s, danach: {keyframe_after_start:.3f}s)")
            print(f"Ende:  {end_sec:.3f}s (Keyframe davor: {keyframe_before_end:.3f}s, danach: {keyframe_after_end:.3f}s)")

            # Prüfe ob Start/Ende auf Keyframes liegen (±33ms Toleranz = ~1 Frame bei 30fps)
            start_on_keyframe = abs(start_sec - keyframe_before_start) < 0.033 or abs(start_sec - keyframe_after_start) < 0.033
            end_on_keyframe = abs(end_sec - keyframe_before_end) < 0.033 or abs(end_sec - keyframe_after_end) < 0.033

            if start_on_keyframe and end_on_keyframe:
                # === FALL 1: Beide Punkte auf Keyframes - Perfekt! Stream-Copy ===
                print("✅ Start und Ende auf Keyframes - nutze reinen Stream-Copy (perfekt)")
                self.after(0, lambda: self.status_label.config(text="Schneide Video (Stream-Copy)..."))

                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_sec),
                    "-i", input_path,
                    "-t", str(duration_sec),
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-map", "0:v:0?", "-map", "0:a:0?",
                    temp_output_path
                ]

                print(f"FFmpeg: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                if result.returncode != 0:
                    raise subprocess.CalledProcessError(result.returncode, cmd, result.stdout, result.stderr)

            elif not start_on_keyframe and not end_on_keyframe and (keyframe_after_start < keyframe_before_end - 1.0):
                # === FALL 2: Beide Punkte zwischen Keyframes - Smart-Cut (3 Segmente) ===
                print("⚠️ Start und Ende zwischen Keyframes - nutze Smart-Cut (re-encode nur Übergänge)")
                self.after(0, lambda: self.status_label.config(text="Schneide Video (Smart-Cut)..."))

                # Segment 1: Re-encode von Start bis nächstem Keyframe
                seg1_path = f"{input_path}.__seg1__.mp4"
                seg2_path = f"{input_path}.__seg2__.mp4"
                seg3_path = f"{input_path}.__seg3__.mp4"
                concat_list = f"{input_path}.__concat__.txt"

                try:
                    # Segment 1: Re-encode Start bis erster Keyframe danach
                    seg1_duration = keyframe_after_start - start_sec
                    print(f"Segment 1 (re-encode): {start_sec:.3f}s - {keyframe_after_start:.3f}s ({seg1_duration:.3f}s)")
                    self._encode_segment_robust(input_path, video_info, seg1_path,
                                               ss=start_sec, duration=seg1_duration,
                                               force_keyframe_at_start=True,
                                               segment_name="Segment 1")

                    # Segment 2: Stream-Copy vom ersten Keyframe nach Start bis letzten Keyframe vor Ende
                    seg2_duration = keyframe_before_end - keyframe_after_start
                    print(f"Segment 2 (stream-copy): {keyframe_after_start:.3f}s - {keyframe_before_end:.3f}s ({seg2_duration:.3f}s)")
                    cmd2 = [
                        "ffmpeg", "-y",
                        "-ss", str(keyframe_after_start),
                        "-i", input_path,
                        "-t", str(seg2_duration),
                        "-c", "copy",
                        "-avoid_negative_ts", "make_zero",
                        "-map", "0:v:0?", "-map", "0:a:0?",
                        seg2_path
                    ]
                    result = subprocess.run(cmd2, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                    if result.returncode != 0:
                        raise subprocess.CalledProcessError(result.returncode, cmd2, result.stdout, result.stderr)

                    # Segment 3: Re-encode vom letzten Keyframe vor Ende bis Ende
                    seg3_duration = end_sec - keyframe_before_end
                    print(f"Segment 3 (re-encode): {keyframe_before_end:.3f}s - {end_sec:.3f}s ({seg3_duration:.3f}s)")
                    self._encode_segment_robust(input_path, video_info, seg3_path,
                                               ss=keyframe_before_end, duration=seg3_duration,
                                               force_keyframe_at_start=False,
                                               segment_name="Segment 3")

                    # Concatenate alle 3 Segmente
                    with open(concat_list, 'w', encoding='utf-8') as f:
                        f.write(f"file '{seg1_path.replace(chr(92), '/')}'\n")
                        f.write(f"file '{seg2_path.replace(chr(92), '/')}'\n")
                        f.write(f"file '{seg3_path.replace(chr(92), '/')}'\n")

                    cmd_concat = [
                        "ffmpeg", "-y",
                        "-f", "concat", "-safe", "0",
                        "-i", concat_list,
                        "-c", "copy",
                        temp_output_path
                    ]
                    result = subprocess.run(cmd_concat, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                    if result.returncode != 0:
                        raise subprocess.CalledProcessError(result.returncode, cmd_concat, result.stdout, result.stderr)

                finally:
                    # Cleanup
                    for f in [seg1_path, seg2_path, seg3_path, concat_list]:
                        if os.path.exists(f):
                            try: os.remove(f)
                            except: pass

            else:
                # === FALL 3: Gemischt oder kurzes Video - Re-encode das ganze Segment ===
                print("⚠️ Kurzes Segment oder gemischte Keyframe-Situation - re-encode gesamtes Segment")
                self.after(0, lambda: self.status_label.config(text="Schneide Video (Re-encode)..."))

                self._encode_segment_robust(input_path, video_info, temp_output_path,
                                           ss=start_sec, duration=duration_sec,
                                           force_keyframe_at_start=True,
                                           segment_name="Gesamt-Segment")

            # Original überschreiben
            self.after(0, lambda: self.status_label.config(text="Überschreibe Original..."))
            try:
                time.sleep(0.2)
                shutil.copy2(temp_output_path, input_path)
                time.sleep(0.1)
                os.remove(temp_output_path)
                print("\n=== SMART CUT ERFOLGREICH ===")
                print(f"✅ Video erfolgreich getrimmt und gespeichert: {input_path}")
                if start_on_keyframe and end_on_keyframe:
                    print("   Methode: Stream-Copy (100% verlustfrei)")
                elif not start_on_keyframe and not end_on_keyframe:
                    print("   Methode: Smart-Cut (nur Übergänge re-encoded)")
                else:
                    print("   Methode: Re-encode (hochqualitativ)")
                print()
            except Exception as e:
                raise Exception(f"Fehler beim Überschreiben der Original-Kopie nach Schnitt: {e}")

            # Callback im Haupt-Thread auslösen
            self.after(0, self._handle_processing_complete, {"action": "cut"})

        except subprocess.CalledProcessError as e:
            self._handle_error_in_thread(f"FFmpeg (Smart Cut) fehlgeschlagen (Code {e.returncode}):\n{e.stderr}")
        except Exception as e:
            self._handle_error_in_thread(f"Fehler beim Smart Cut: {e}")
        finally:
            # Sicherstellen, dass temporäre Datei gelöscht wird
            if os.path.exists(temp_output_path):
                try:
                    os.remove(temp_output_path)
                except Exception as del_e:
                    print(f"Konnte temp. Schnittdatei nicht löschen: {del_e}")

    def _run_split_task(self, split_time_ms: int):
        """
        [THREAD] Führt präzisen Split aus mit Smart-Cut (re-encodiert nur an Split-Punkt).
        Teil 1 überschreibt das Original, Teil 2 erhält das Suffix _2.
        Verhindert Freeze-Frames durch gezieltes Re-Encoding an den Übergängen.
        """
        temp_part1_path = None
        part2_path = None
        try:
            input_path = self.video_path
            base, ext = os.path.splitext(input_path)
            temp_part1_path = f"{base}.__temp_part1__{ext}"
            part2_path = f"{base}_2{ext}"  # GEÄNDERT: Suffix _2 statt __part2__

            split_sec = split_time_ms / 1000.0

            # Video-Info für Re-Encoding
            video_info = self._get_video_info(input_path)

            print(f"\n=== SMART SPLIT START (Anti-Freeze) ===")
            print(f"Split-Position: {split_sec:.3f}s")

            # Finde Keyframes um Split-Position
            self.after(0, lambda: self.status_label.config(text="Analysiere Keyframes..."))
            keyframe_before = self._find_keyframe_before(input_path, split_sec)
            keyframe_after = self._find_keyframe_after(input_path, split_sec)

            print(f"Keyframe vor Split: {keyframe_before:.3f}s")
            print(f"Keyframe nach Split: {keyframe_after:.3f}s")

            # Prüfe ob Split auf Keyframe liegt
            split_on_keyframe = abs(split_sec - keyframe_before) < 0.01 or abs(split_sec - keyframe_after) < 0.01

            if split_on_keyframe:
                print("✅ Split liegt auf Keyframe - nutze Stream-Copy (perfekt)")
                # --- TEIL 1: Stream-Copy bis Split ---
                self.after(0, lambda: self.status_label.config(text="Erstelle Teil 1 (Stream-Copy)..."))
                cmd1 = [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-t", str(split_sec),
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-map", "0:v:0?", "-map", "0:a:0?",
                    temp_part1_path
                ]
                print(f"FFmpeg Teil 1: {' '.join(cmd1)}")
                result1 = subprocess.run(cmd1, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                if result1.returncode != 0:
                    raise subprocess.CalledProcessError(result1.returncode, cmd1, result1.stdout, result1.stderr)

                # --- TEIL 2: Stream-Copy ab Split ---
                self.after(0, lambda: self.status_label.config(text="Erstelle Teil 2 (Stream-Copy)..."))
                cmd2 = [
                    "ffmpeg", "-y",
                    "-i", input_path,
                    "-ss", str(split_sec),
                    "-c", "copy",
                    "-avoid_negative_ts", "make_zero",
                    "-map", "0:v:0?", "-map", "0:a:0?",
                    part2_path
                ]
                print(f"FFmpeg Teil 2: {' '.join(cmd2)}")
                result2 = subprocess.run(cmd2, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                if result2.returncode != 0:
                    raise subprocess.CalledProcessError(result2.returncode, cmd2, result2.stdout, result2.stderr)
            else:
                print("⚠️ Split liegt NICHT auf Keyframe - nutze Smart-Cut (re-encode an Übergängen)")

                # --- TEIL 1: Smart-Cut (Stream-Copy + Re-encode Ende) ---
                self.after(0, lambda: self.status_label.config(text="Erstelle Teil 1 (Smart-Cut)..."))

                if keyframe_before < split_sec - 0.1:  # Mehr als 100ms vor Split
                    # Teile in Segmente: Stream-Copy + Re-encode
                    seg1_path = f"{input_path}.__part1_seg1__.mp4"
                    seg2_path = f"{input_path}.__part1_seg2__.mp4"
                    concat_list = f"{input_path}.__part1_concat__.txt"

                    try:
                        # Segment 1: Stream-Copy bis Keyframe vor Split
                        cmd1a = [
                            "ffmpeg", "-y",
                            "-i", input_path,
                            "-t", str(keyframe_before),
                            "-c", "copy",
                            "-avoid_negative_ts", "make_zero",
                            "-map", "0:v:0?", "-map", "0:a:0?",
                            seg1_path
                        ]
                        result = subprocess.run(cmd1a, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, cmd1a, result.stdout, result.stderr)

                        # Segment 2: Re-encode von Keyframe vor Split bis Split
                        seg2_duration = split_sec - keyframe_before
                        self._encode_segment_robust(input_path, video_info, seg2_path,
                                                   ss=keyframe_before, duration=seg2_duration,
                                                   force_keyframe_at_start=False,
                                                   segment_name="Teil1-Seg2")

                        # Concat
                        with open(concat_list, 'w', encoding='utf-8') as f:
                            f.write(f"file '{seg1_path.replace(chr(92), '/')}'\n")
                            f.write(f"file '{seg2_path.replace(chr(92), '/')}'\n")

                        cmd1_concat = [
                            "ffmpeg", "-y",
                            "-f", "concat", "-safe", "0",
                            "-i", concat_list,
                            "-c", "copy",
                            temp_part1_path
                        ]
                        result = subprocess.run(cmd1_concat, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, cmd1_concat, result.stdout, result.stderr)
                    finally:
                        for f in [seg1_path, seg2_path, concat_list]:
                            if os.path.exists(f):
                                try: os.remove(f)
                                except: pass
                else:
                    # Zu nah am Anfang, re-encode das ganze Teil 1
                    self._encode_segment_robust(input_path, video_info, temp_part1_path,
                                               ss=0, duration=split_sec,
                                               force_keyframe_at_start=True,
                                               segment_name="Teil 1 (komplett)")

                # --- TEIL 2: Smart-Cut (Re-encode Anfang + Stream-Copy Rest) ---
                self.after(0, lambda: self.status_label.config(text="Erstelle Teil 2 (Smart-Cut)..."))

                if keyframe_after > split_sec + 0.1:  # Mehr als 100ms nach Split
                    # Teile in Segmente: Re-encode + Stream-Copy
                    seg1_path = f"{input_path}.__part2_seg1__.mp4"
                    seg2_path = f"{input_path}.__part2_seg2__.mp4"
                    concat_list = f"{input_path}.__part2_concat__.txt"

                    try:
                        # Segment 1: Re-encode von Split bis Keyframe nach Split
                        seg1_duration = keyframe_after - split_sec
                        self._encode_segment_robust(input_path, video_info, seg1_path,
                                                   ss=split_sec, duration=seg1_duration,
                                                   force_keyframe_at_start=True,
                                                   segment_name="Teil2-Seg1")

                        # Segment 2: Stream-Copy ab Keyframe nach Split
                        cmd2b = [
                            "ffmpeg", "-y",
                            "-i", input_path,
                            "-ss", str(keyframe_after),
                            "-c", "copy",
                            "-avoid_negative_ts", "make_zero",
                            "-map", "0:v:0?", "-map", "0:a:0?",
                            seg2_path
                        ]
                        result = subprocess.run(cmd2b, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, cmd2b, result.stdout, result.stderr)

                        # Concat
                        with open(concat_list, 'w', encoding='utf-8') as f:
                            f.write(f"file '{seg1_path.replace(chr(92), '/')}'\n")
                            f.write(f"file '{seg2_path.replace(chr(92), '/')}'\n")

                        cmd2_concat = [
                            "ffmpeg", "-y",
                            "-f", "concat", "-safe", "0",
                            "-i", concat_list,
                            "-c", "copy",
                            part2_path
                        ]
                        result = subprocess.run(cmd2_concat, capture_output=True, text=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
                        if result.returncode != 0:
                            raise subprocess.CalledProcessError(result.returncode, cmd2_concat, result.stdout, result.stderr)
                    finally:
                        for f in [seg1_path, seg2_path, concat_list]:
                            if os.path.exists(f):
                                try: os.remove(f)
                                except: pass
                else:
                    # Rest des Videos ist klein, re-encode alles
                    self._encode_segment_robust(input_path, video_info, part2_path,
                                               ss=split_sec, duration=999999,
                                               force_keyframe_at_start=True,
                                               segment_name="Teil 2 (komplett)")

            print("✅ Teil 1 erfolgreich")
            print("✅ Teil 2 erfolgreich")

            # Original mit Teil 1 überschreiben und dann zu _1 umbenennen
            self.after(0, lambda: self.status_label.config(text="Finalisiere Split..."))

            # Definiere part1_path außerhalb des try-Blocks
            base, ext = os.path.splitext(input_path)
            part1_path = f"{base}_1{ext}"

            try:
                time.sleep(0.2)
                # Schritt 1: Original wird mit Teil 1 überschrieben
                shutil.copy2(temp_part1_path, input_path)
                time.sleep(0.1)
                os.remove(temp_part1_path)

                # Schritt 2: Original-Video wird zu _1 umbenannt
                shutil.move(input_path, part1_path)

                print("\n=== PRECISE SPLIT ERFOLGREICH ===")
                print(f"Teil 1: {part1_path}")
                print(f"Teil 2: {part2_path}")
                print("⚠️ Hinweis: Split ist frame-genau mit Smart-Cut")
                print("   Nur die Bereiche um den Split-Punkt wurden re-encoded\n")
            except Exception as e:
                raise Exception(f"Fehler beim Finalisieren des Splits: {e}")

            # Callback im Haupt-Thread auslösen
            result = {"action": "split", "part1_path": part1_path, "part2_path": part2_path}
            self.after(0, self._handle_processing_complete, result)

        except subprocess.CalledProcessError as e:
            self._handle_error_in_thread(f"FFmpeg (Precise Split) fehlgeschlagen (Code {e.returncode}):\n{e.stderr}")
        except Exception as e:
            self._handle_error_in_thread(f"Fehler beim Precise Split: {e}")
        finally:
            # Sicherstellen, dass temporäre Dateien gelöscht werden
            if temp_part1_path and os.path.exists(temp_part1_path):
                try:
                    os.remove(temp_part1_path)
                except Exception as del_e:
                    print(f"Konnte temp. Teil 1 nicht löschen: {del_e}")

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
        # Cleanup für Debounce-Timer
        if hasattr(self, '_seek_debounce_timer') and self._seek_debounce_timer is not None:
            try:
                self.after_cancel(self._seek_debounce_timer)
                self._seek_debounce_timer = None
            except:
                pass

        # VLC-Player cleanup
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
