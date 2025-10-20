import tkinter as tk
from tkinter import messagebox, ttk, filedialog
from moviepy import ImageClip, TextClip, CompositeVideoClip, VideoFileClip, concatenate_videoclips
import os
import json
import time
import threading
from tkinter import filedialog
from tkcalendar import DateEntry
from datetime import date
from proglog import ProgressBarLogger
from tkinterdnd2 import DND_FILES, TkinterDnD
import tempfile
import subprocess

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
    """Setzt die GUI nach Abschluss oder Abbruch zurück in den Ursprungszustand."""
    progress_bar.pack_forget()
    eta_label.pack_forget()
    # --- ANPASSUNG: Button wieder zu "Erstellen" zurücksetzen ---
    erstellen_button.config(text="Video Erstellen", command=erstelle_video, bg="#4CAF50", state="normal")
    dropped_video_path_var.set("")
    drop_label.config(text="Optionale .mp4 Datei hierher ziehen", fg="black")

def sanitize_filename(filename):
    """Entfernt ungültige Zeichen aus einem potenziellen Dateinamen."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()

def _video_creation_task(load, gast, tandemmaster, videospringer, datum, dauer, ort, speicherort, dropped_video_path):
    """
    Erstellt das Video. Nutzt einen schnellen FFmpeg-Pfad für kompatible Videos
    oder den langsameren MoviePy-Pfad zur Konvertierung.
    """

    # Eingaben für Dateinamen bereinigen
    gast = sanitize_filename(gast)
    tandemmaster = sanitize_filename(tandemmaster)
    videospringer = sanitize_filename(videospringer)


    full_output_path = ""
    temp_video_to_delete = None
    temp_titel_clip_path = None
    concat_list_path = "concat_list.txt"

    # Clips initialisieren, damit sie im finally-Block sicher geschlossen werden können
    user_clip_original, titel_video, final_clip_to_write, user_clip = None, None, None, None


    try:
        # --- SCHRITT 1: User-Video analysieren ---
        root.after(0, lambda: status_label.config(text="Status: Analysiere User-Video..."))
        user_clip_original = VideoFileClip(dropped_video_path)

        # MODIFIZIERT: Auflösung und FPS dynamisch aus dem Clip lesen
        clip_size = user_clip_original.size
        clip_fps = user_clip_original.fps
        clip_width, clip_height = clip_size

        if not clip_fps:
            raise ValueError("Konnte die FPS des Videos nicht ermitteln. Die Datei ist möglicherweise beschädigt.")

        # --- SCHRITT 2: Intro-Video dynamisch passend zum User-Video erstellen ---
        root.after(0, lambda: status_label.config(text="Status: Erstelle passendes Intro..."))

        # MODIFIZIERT: Schriftgröße wird an die Video-Höhe angepasst für saubere Skalierung
        dynamic_font_size = int(clip_height / 18)  # z.B. 60 bei 1080p, 40 bei 720p

        hintergrund_clip = ImageClip("hintergrund.png", duration=dauer)

        text_inhalte = [f"Gast: {gast}", f"Tandemmaster: {tandemmaster}"]
        if outside_video_var.get():
            text_inhalte.append(f"Videospringer: {videospringer}")
        text_inhalte.extend([f"Datum: {datum}", f"Ort: {ort}"])

        clips_liste = [hintergrund_clip]
        start_y_pos = clip_height * 0.15
        y_increment = clip_height * 0.15

        for i, text_zeile in enumerate(text_inhalte):
            y_pos = start_y_pos + (i * y_increment)
            txt_clip = TextClip(
                text=text_zeile,
                font_size=50,
                color='black',
                method='label',
                duration=dauer,
                margin=(100, 20))
            txt_clip = txt_clip.with_position(('center', y_pos))
            clips_liste.append(txt_clip)

        # MODIFIZIERT: CompositeVideoClip wird mit der dynamischen Größe des User-Videos erstellt
        titel_video = CompositeVideoClip(clips_liste, size=clip_size, use_bgclip=True)
        titel_video.duration = dauer
        titel_video.fps = clip_fps

        # --- SCHRITT 3: Temporären Titel-Clip rendern ---
        # Dieser kurze Schreibvorgang ist der einzige Kodierungsschritt und daher sehr schnell.
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as temp_f:
            temp_titel_clip_path = temp_f.name

        titel_video.write_videofile(
            temp_titel_clip_path,
            codec='libx264',
            preset='ultrafast',
            threads=os.cpu_count(),
            logger=CancellableProgressBarLogger(),
            fps=clip_fps  # MODIFIZIERT: Nutzt die FPS des User-Videos
        )

        # --- SCHRITT 4: Finale Datei mit FFmpeg blitzschnell zusammensetzen ---
        root.after(0, lambda: status_label.config(text="Status: Führe schnelles Zusammenfügen durch..."))

        # Dateinamen vorbereiten
        datum_obj = date.fromisoformat('-'.join(datum.split('.')[::-1]))
        datum_formatiert = datum_obj.strftime("%Y%m%d")
        output_filename = f"{datum_formatiert}_L{load}_{gast}_TA_{tandemmaster}"
        if outside_video_var.get():
            output_filename += f"_V_{videospringer}"
        output_filename += ".mp4"
        full_output_path = os.path.join(speicherort, output_filename)

        # Textdatei für FFmpeg erstellen
        with open(concat_list_path, "w", encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(temp_titel_clip_path)}'\n")
            f.write(f"file '{os.path.abspath(dropped_video_path)}'\n")

        if cancel_event.is_set(): raise CancellationError()

        # FFmpeg-Befehl ausführen
        command = ["ffmpeg", "-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", full_output_path]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE)  # stderr=PIPE fängt Fehler ab

        # Erfolgsmeldung
        if not cancel_event.is_set():
            root.after(0,
                       lambda: status_label.config(text=f"Status: Video '{output_filename}' erfolgreich erstellt!"))
            messagebox.showinfo("Fertig", f"Das Video wurde erfolgreich unter '{full_output_path}' gespeichert.")

    except FileNotFoundError as e:
        print(e)
        messagebox.showerror("Fehler", "Die Datei 'hintergrund.png' wurde nicht gefunden.")
        status_label.config(text="Status: Fehler. Hintergrundbild nicht gefunden.")

    # --- NEU: Abfangen der Abbruch-Exception ---
    except CancellationError:
        status_label.config(text="Status: Videoerstellung vom Benutzer abgebrochen.")
        # Versuch, die unfertige Datei zu löschen
        if full_output_path and os.path.exists(full_output_path):
            try:
                os.remove(full_output_path)
                print(f"Unfertige Datei '{full_output_path}' gelöscht.")
            except OSError as e:
                print(f"Fehler beim Löschen der unfertigen Datei: {e}")

    except Exception as e:
        messagebox.showerror("Fehler", f"Ein unerwarteter Fehler ist aufgetreten:\n{e}")
        status_label.config(text="Status: Ein Fehler ist aufgetreten.")
    finally:
        # WICHTIG: Alle Clips schließen, um Dateihandles freizugeben
        if 'titel_video' in locals(): titel_video.close()
        if 'user_clip' in locals() and user_clip: user_clip.close()
        if 'final_clip_to_write' in locals(): final_clip_to_write.close()
        if temp_video_to_delete and os.path.exists(temp_video_to_delete):
            try:
                os.remove(temp_video_to_delete)
            except Exception as e:
                print(f"Konnte temporäre Datei nicht löschen: {e}")
        root.after(0, reset_gui_state)


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

load_settings()

root.mainloop()