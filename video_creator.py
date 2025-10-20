import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from moviepy import ImageClip, TextClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips
import os
import json
import threading
from tkinter import filedialog
from tkcalendar import DateEntry
from datetime import date
from proglog import ProgressBarLogger
from tkinterdnd2 import DND_FILES, TkinterDnD
import tempfile
import subprocess

from ffmpeg_installer import ensure_ffmpeg_installed

# --- KONSTANTEN ---
CONFIG_FILE = "config.json"

# --- NEU: Threading-Event für den Abbruch ---
cancel_event = threading.Event()


# --- NEU: Eigene Exception für den Abbruch ---
class CancellationError(Exception):
    """Eigene Exception, um einen sauberen Abbruch zu signalisieren."""
    pass


# --- NEU: Eigener Logger, der auf Abbruch prüfen kann ---
class CancellableProgressBarLogger(ProgressBarLogger):
    """
    Dieser Logger prüft bei jedem Fortschritts-Update, ob das
    cancel_event gesetzt wurde und wirft dann eine Exception.
    """

    def callback(self, **changes):
        # Every time the logger message is updated, this function is called with
        # the `changes` dictionary of the form `parameter: new value`.
        for (parameter, value) in changes.items():
            print('Parameter %s is now %s' % (parameter, value))

    def bars_callback(self, bar, attr, value, old_value=None):
        percentage = (value / self.bars[bar]['total']) * 100
        print(bar, attr, percentage)
        if cancel_event.is_set():
            raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")


# --- HILFSFUNKTIONEN FÜR EINSTELLUNGEN ---
def save_settings():
    """Speichert die aktuellen Einstellungen in einer JSON-Datei."""
    settings = {
        "gast": entry_gast.get(),
        "speicherort": speicherort_var.get(),
        "ort": ort_var.get(),
        "outside_video": outside_video_var.get(),
        "tandemmaster": entry_tandemmaster.get() if not outside_video_var.get() else "",
        "videospringer": entry_videospringer.get() if outside_video_var.get() else ""
    }
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        print(f"Fehler beim Speichern der Einstellungen: {e}")


def load_settings():
    """Lädt die Einstellungen aus der JSON-Datei, falls vorhanden."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                settings = json.load(f)
                speicherort_var.set(settings.get("speicherort", ""))
                ort_var.set(settings.get("ort", "Calden"))
                outside_video_var.set(settings.get("outside_video", False))
                entry_gast.delete(0, tk.END)
                entry_gast.insert(0, settings.get("gast", ""))
                entry_tandemmaster.delete(0, tk.END)
                entry_tandemmaster.insert(0, settings.get("tandemmaster", ""))
                entry_videospringer.delete(0, tk.END)
                entry_videospringer.insert(0, settings.get("videospringer", ""))
        except json.JSONDecodeError:
            print("Fehler beim Lesen der Konfigurationsdatei. Standardwerte werden verwendet.")
    toggle_videospringer_visibility()


def toggle_videospringer_visibility():
    """Schaltet die Sichtbarkeit des Videospringer-Feldes um."""
    if outside_video_var.get():
        label_videospringer.grid()
        entry_videospringer.grid()
    else:
        label_videospringer.grid_remove()
        entry_videospringer.grid_remove()


def waehle_speicherort():
    """Öffnet einen Dialog zur Auswahl eines Speicherordners."""
    directory = filedialog.askdirectory()
    if directory:
        speicherort_var.set(directory)


# --- NEU: FUNKTIONEN FÜR DRAG AND DROP ---
def handle_drop(event):
    """Verarbeitet die hier abgelegte Datei."""
    # event.data kann von geschweiften Klammern umschlossen sein, diese entfernen wir
    filepath = event.data.strip('{}')

    if os.path.isfile(filepath) and filepath.lower().endswith('.mp4'):
        dropped_video_path_var.set(filepath)
        drop_label.config(text=f"Datei: {os.path.basename(filepath)}", fg="green")
    else:
        dropped_video_path_var.set("")
        drop_label.config(text="Ungültig! Bitte nur eine einzelne .mp4 Datei ablegen.", fg="red")
        messagebox.showerror("Ungültiger Dateityp", "Bitte ziehen Sie nur .mp4-Dateien in das Feld.")


# --- FUNKTIONEN ZUR VIDEOERSTELLUNG UND STEUERUNG ---

def erstelle_video():
    """
    Bereitet die Videoerstellung vor und startet sie in einem separaten Thread.
    Ändert den Button zu einem "Abbrechen"-Button.
    """
    load = entry_load.get()
    gast = entry_gast.get()
    tandemmaster = entry_tandemmaster.get()
    videospringer = entry_videospringer.get() if outside_video_var.get() else "N/A"
    datum = entry_datum.get()
    dauer = int(dauer_var.get())
    ort = ort_var.get()
    speicherort = speicherort_var.get()
    dropped_video_path = dropped_video_path_var.get()

    required_fields = [load, gast, tandemmaster, datum, speicherort, dropped_video_path]
    if outside_video_var.get():
        required_fields.append(videospringer)

    if not all(field.strip() for field in required_fields if isinstance(field, str)):
        messagebox.showwarning("Fehlende Eingabe", "Bitte füllen Sie alle Felder aus und wählen Sie einen Speicherort.")
        return

    save_settings()
    status_label.config(text="Status: Video wird erstellt... Bitte warten.")

    # --- ANPASSUNG: Button zu "Abbrechen" ändern ---
    erstellen_button.config(text="Abbrechen", command=abbrechen_prozess, bg="#D32F2F")

    progress_bar['mode'] = 'determinate'
    progress_bar['value'] = 0
    eta_label.config(text="Geschätzte Restlaufzeit: wird berechnet...")
    progress_bar.pack(pady=5)
    eta_label.pack(pady=2)

    # --- NEU: Sicherstellen, dass das Abbruch-Event zurückgesetzt ist ---
    cancel_event.clear()

    video_thread = threading.Thread(
        target=_video_creation_task,
        args=(load, gast, tandemmaster, videospringer, datum, dauer, ort, speicherort, dropped_video_path)
    )
    video_thread.start()


def abbrechen_prozess():
    """
    Wird vom "Abbrechen"-Button aufgerufen. Setzt das Event und ändert den Status.
    """
    status_label.config(text="Status: Abbruch wird eingeleitet...")
    erstellen_button.config(state="disabled")  # Verhindert mehrfaches Klicken
    cancel_event.set()


def reset_gui_state():
    print('call reset_gui_state')
    """Setzt die GUI nach Abschluss oder Abbruch zurück in den Ursprungszustand."""
    progress_bar.pack_forget()
    eta_label.pack_forget()
    # --- ANPASSUNG: Button wieder zu "Erstellen" zurücksetzen ---
    erstellen_button.config(text="Video Erstellen", command=erstelle_video, bg="#4CAF50", state="normal")
    dropped_video_path_var.set("")
    drop_label.config(text="Geschnittene .mp4 Datei hierher ziehen", fg="black")

def sanitize_filename(filename):
    """Entfernt ungültige Zeichen aus einem potenziellen Dateinamen."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()

def _video_creation_task(load, gast, tandemmaster, videospringer, datum, dauer, ort, speicherort, dropped_video_path):
    import os, subprocess, tempfile
    from datetime import date
    from moviepy import VideoFileClip
    from tkinter import messagebox

    def ffmpeg_escape(text: str) -> str:
        return text.replace(":", r"\:").replace("'", r"\''").replace(",", r"\,")

    def run_ffmpeg(cmd, description=""):
        """Führt FFmpeg aus und gibt Fortschritt über Logger aus. Prüft auf Abbruch."""
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        try:
            for line in process.stdout:
                print(f"[FFmpeg {description}] {line.strip()}")
                if cancel_event.is_set():
                    process.kill()
                    raise CancellationError("Videoerstellung vom Benutzer abgebrochen.")
            process.wait()
            if process.returncode != 0:
                raise Exception(f"FFmpeg ({description}) beendet mit Fehlercode {process.returncode}")
        except Exception:
            process.kill()
            raise

    full_output_path = ""
    concat_list_path = os.path.join(tempfile.gettempdir(), "concat_list.txt")
    temp_video_noaudio = os.path.join(tempfile.gettempdir(), "temp_video_noaudio.mp4")
    extracted_audio = os.path.join(tempfile.gettempdir(), "original_audio.aac")
    delayed_audio = os.path.join(tempfile.gettempdir(), "delayed_audio.aac")

    try:
        user_clip = VideoFileClip(dropped_video_path)
        clip_width, clip_height = user_clip.size
        clip_fps = user_clip.fps or 30
        user_clip.close()

        text_inhalte = [f"Gast: {gast}", f"Tandemmaster: {tandemmaster}"]
        if outside_video_var.get():
            text_inhalte.append(f"Videospringer: {videospringer}")
        text_inhalte.extend([f"Datum: {datum}", f"Ort: {ort}"])
        text_inhalte = [ffmpeg_escape(t) for t in text_inhalte]

        font_size = int(clip_height / 18)
        y = clip_height * 0.15
        y_step = clip_height * 0.15
        drawtext_cmds = []
        for t in text_inhalte:
            drawtext_cmds.append(
                f"drawtext=text='{t}':x=(w-text_w)/2:y={int(y)}:fontsize={font_size}:fontcolor=black:font='Arial'"
            )
            y += y_step
        drawtext_filter = ",".join(drawtext_cmds)

        temp_titel_clip_path = os.path.join(tempfile.gettempdir(), "titel_intro.mp4")
        if not os.path.exists("hintergrund.png"):
            raise FileNotFoundError("hintergrund.png fehlt")

        # Titelclip ohne Audio erzeugen
        run_ffmpeg([
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", "hintergrund.png",
            "-vf", drawtext_filter,
            "-t", str(dauer),
            "-r", str(clip_fps),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "ultrafast",
            temp_titel_clip_path
        ], description="Titelclip")

        # Original-Audio extrahieren
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", dropped_video_path,
            "-vn",
            "-acodec", "copy",
            extracted_audio
        ], description="Audio extrahieren")

        # Audio um Intro verschieben
        intro_ms = int(dauer * 1000)
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", extracted_audio,
            "-af", f"adelay={intro_ms}|{intro_ms}",
            delayed_audio
        ], description="Audio verschieben")

        datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
        datum_formatiert = datum_obj.strftime("%Y%m%d")
        output_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video_var.get():
            output_filename += f"_V_{videospringer}"
        output_filename += ".mp4"
        full_output_path = os.path.join(speicherort, output_filename)

        # Concat-Textdatei für Videos ohne Audio
        with open(concat_list_path, "w", encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(temp_titel_clip_path)}'\n")
            f.write(f"file '{os.path.abspath(dropped_video_path)}'\n")

        # Video ohne Rekodierung zusammenfügen
        run_ffmpeg([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            temp_video_noaudio
        ], description="Video zusammenfügen")

        # Delayed-Audio hinzufügen
        run_ffmpeg([
            "ffmpeg", "-y",
            "-i", temp_video_noaudio,
            "-i", delayed_audio,
            "-c:v", "copy",
            "-c:a", "copy",
            full_output_path
        ], description="Audio hinzufügen")

        messagebox.showinfo("Fertig", f"Das Video wurde unter '{full_output_path}' gespeichert.")

    except CancellationError:
        status_label.config(text="Status: Erstellung abgebrochen.")
        if full_output_path and os.path.exists(full_output_path):
            os.remove(full_output_path)
    except Exception as e:
        messagebox.showerror("Fehler", f"Fehler bei der Videoerstellung:\n{e}")
        status_label.config(text="Status: Fehler aufgetreten.")
    finally:
        root.after(0, reset_gui_state)
        for f in [temp_titel_clip_path, temp_video_noaudio, extracted_audio, delayed_audio]:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except:
                pass





# --- GUI ERSTELLUNG (TKINTER) ---
root = TkinterDnD.Tk()
root.title("Tandemvideo Generator")
root.geometry("600x750")
root.config(padx=20, pady=20)

form_frame = tk.Frame(root)
form_frame.pack(pady=10)

outside_video_var = tk.BooleanVar()
speicherort_var = tk.StringVar()
dropped_video_path_var = tk.StringVar()

# Eingabefelder und Labels
tk.Label(form_frame, text="Load Nr:", font=("Arial", 12)).grid(row=0, column=0, padx=5, pady=5, sticky="w")
def _validate_digits(new_value):
    return new_value.isdigit() or new_value == ""
vcmd_loadnr = form_frame.register(_validate_digits)
entry_load = tk.Entry(form_frame, width=40, font=("Arial", 12), validate='key', validatecommand=(vcmd_loadnr, '%P'))
entry_load.grid(row=0, column=1, padx=5, pady=5)

tk.Label(form_frame, text="Gast:", font=("Arial", 12)).grid(row=1, column=0, padx=5, pady=5, sticky="w")
entry_gast = tk.Entry(form_frame, width=40, font=("Arial", 12))
entry_gast.grid(row=1, column=1, padx=5, pady=5)

tk.Label(form_frame, text="Tandemmaster:", font=("Arial", 12)).grid(row=2, column=0, padx=5, pady=5, sticky="w")
entry_tandemmaster = tk.Entry(form_frame, width=40, font=("Arial", 12))
entry_tandemmaster.grid(row=2, column=1, padx=5, pady=5)

tk.Checkbutton(form_frame, text="Outside Video", variable=outside_video_var, onvalue=True, offvalue=False,
               font=("Arial", 12), command=toggle_videospringer_visibility).grid(row=3, column=0, columnspan=2, pady=5,
                                                                                 sticky="w")

label_videospringer = tk.Label(form_frame, text="Videospringer:", font=("Arial", 12))
label_videospringer.grid(row=4, column=0, padx=5, pady=5, sticky="w")
entry_videospringer = tk.Entry(form_frame, width=40, font=("Arial", 12))
entry_videospringer.grid(row=4, column=1, padx=5, pady=5)

tk.Label(form_frame, text="Datum:", font=("Arial", 12)).grid(row=5, column=0, padx=5, pady=5, sticky="w")
entry_datum = DateEntry(form_frame, width=38, font=("Arial", 12), date_pattern='dd.mm.yyyy', set_date=date.today())
entry_datum.grid(row=5, column=1, padx=5, pady=5)

tk.Label(form_frame, text="Dauer (Sekunden):", font=("Arial", 12)).grid(row=6, column=0, padx=5, pady=5, sticky="w")
dauer_var = tk.StringVar(value="1")
dropdown_dauer = tk.OptionMenu(form_frame, dauer_var, "1", "3", "4", "5", "6", "7", "8", "9", "10")
dropdown_dauer.grid(row=6, column=1, padx=5, pady=5, sticky="ew")

tk.Label(form_frame, text="Ort:", font=("Arial", 12)).grid(row=7, column=0, padx=5, pady=5, sticky="w")
ort_var = tk.StringVar(value="Calden")
dropdown_ort = tk.OptionMenu(form_frame, ort_var, "Calden", "Gera")
dropdown_ort.grid(row=7, column=1, padx=5, pady=5, sticky="ew")

tk.Label(form_frame, text="Speicherort:", font=("Arial", 12)).grid(row=8, column=0, padx=5, pady=10, sticky="w")
speicherort_frame = tk.Frame(form_frame)
speicherort_frame.grid(row=8, column=1, sticky="ew")
speicherort_button = tk.Button(speicherort_frame, text="Wählen...", command=waehle_speicherort)
speicherort_button.pack(side=tk.LEFT)
speicherort_label = tk.Label(speicherort_frame, textvariable=speicherort_var, font=("Arial", 10), anchor="w", fg="grey")
speicherort_label.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)

# --- NEU: Drag-and-Drop-Feld ---
drop_frame = tk.Frame(root, relief="sunken", borderwidth=2, padx=10, pady=10)
drop_frame.pack(fill="x", pady=10, ipady=20)

drop_label = tk.Label(drop_frame, text="Geschnittene .mp4 Datei hierher ziehen", font=("Arial", 12))
drop_label.pack(expand=True)

# Registrierung des Drop-Ziels
drop_label.drop_target_register(DND_FILES)
drop_label.dnd_bind('<<Drop>>', handle_drop)

erstellen_button = tk.Button(root, text="Video Erstellen", font=("Arial", 14, "bold"), command=erstelle_video,
                             bg="#4CAF50", fg="white")
erstellen_button.pack(pady=20, ipady=5)

progress_bar = ttk.Progressbar(root, orient='horizontal', mode='determinate', length=280)
eta_label = tk.Label(root, text="", font=("Arial", 10))

status_label = tk.Label(root, text="Status: Bereit.", font=("Arial", 10), bd=1, relief=tk.SUNKEN, anchor=tk.W)
status_label.pack(side=tk.BOTTOM, fill=tk.X)


ffmpeg_path = None

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

def _create_install_overlay():
    """
    Create and return an in-window modal overlay (Frame), a circular spinner instance and a status StringVar.
    The overlay covers the entire root window and prevents interaction with underlying widgets.
    """
    overlay = tk.Frame(root, bg="#000000")
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
    container_width = min(420, int(root.winfo_width() * 0.7 or 300))
    container.place(relx=0.5, rely=0.5, anchor='center', width=container_width)

    # Spinner (circular)
    spinner = CircularSpinner(container, size=80, line_width=8, color="#2E86C1", speed=10)
    spinner.pack(padx=20, pady=(20, 6))

    status_var = tk.StringVar(value="Installing FFmpeg...")
    status_lbl = tk.Label(container, textvariable=status_var, font=("Arial", 10), bg='white', wraplength=container_width-40)
    status_lbl.pack(padx=20, pady=(0, 20))

    return overlay, spinner, status_var

def _start_ffmpeg_installer_overlayed():
    """Show in-window overlay and run ensure_ffmpeg_installed in a background thread."""

    overlay, spinner, status_var = _create_install_overlay()
    spinner.start()

    def progress_callback(msg):
        root.after(0, status_var.set, msg)

    def finish(success_path=None, error=None):
        try:
            spinner.stop()
        except Exception:
            pass
        # unbind the blocking event handlers
        for seq in ("<Button-1>", "<Button-2>", "<Button-3>", "<ButtonRelease>", "<Key>", "<MouseWheel>", "<Button>"):
            try:
                overlay.unbind_all(seq)
            except Exception:
                pass
        try:
            overlay.destroy()
        except Exception:
            pass
        if error:
            root.after(0, lambda: messagebox.showerror("FFmpeg installation failed", str(error)))

    def installer_thread():
        global ffmpeg_path
        try:
            path = ensure_ffmpeg_installed(progress_callback=progress_callback)
            ffmpeg_path = path
            finish(success_path=path)
        except Exception as e:
            finish(error=e)

    t = threading.Thread(target=installer_thread, daemon=True)
    t.start()

# start installer with overlay before entering mainloop
_start_ffmpeg_installer_overlayed()

load_settings()

root.mainloop()