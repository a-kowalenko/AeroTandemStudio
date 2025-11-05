Spezifikation: Feature - Foto-Wasserzeichen

1. Zielsetzung

Implementierung einer Wasserzeichen-Funktion (WM) für die Foto-Tabelle (photo_tree in drag_drop.py). Die Funktionalität soll die bestehende Logik der Video-Wasserzeichen spiegeln, jedoch mit der Möglichkeit zur Mehrfachauswahl von Fotos.

Bei der Erstellung (processor.py) sollen alle als "WM" markierten Fotos in 720p-Auflösung (Höhe, Seitenverhältnis beibehalten) und mit dem Wasserzeichen skydivede_wasserzeichen.png (mit 80% Transparenz) in einem separaten Ordner namens Preview_Foto gespeichert werden.

Zusätzlich wird der bestehende Video-Wasserzeichen-Ordner von Wasserzeichen_Video in Preview_Video umbenannt.

2. Änderungen an drag_drop.py (UI & State)

Klasse: DragDropFrame

2.1. __init__ (Konstruktor)

Füge eine neue Variable hinzu, um die Indizes der ausgewählten Fotos zu speichern (analog zu watermark_clip_index):

self.watermark_photo_indices = [] # NEU: Liste für Foto-Mehrfachauswahl


2.2. create_photo_tab

Neue Spalte "WM" zur photo_tree hinzufügen:

Ändere die columns-Definition des ttk.Treeview:

# ALT:
# columns=("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit"),
# NEU:
columns=("Nr", "Dateiname", "Größe", "Datum", "Uhrzeit", "WM"),


Füge das Spalten-Heading hinzu (analog zu video_tree):

self.photo_tree.heading("WM", text="💧")


Füge die Spalten-Konfiguration hinzu (initial versteckt):

self.photo_tree.column("WM", width=0, minwidth=0, stretch=False, anchor="center")


Event-Binding für Klicks hinzufügen:

Binde (analog zu video_tree) das ButtonRelease-1-Ereignis, um Klicks auf die Checkboxen zu verarbeiten:

self.photo_tree.bind("<ButtonRelease-1>", self._on_photo_watermark_checkbox_click)


2.3. _update_photo_table

Passe die self.photo_tree.insert-Methode an, um den Wert für die "WM"-Spalte (Checkbox-Status) einzufügen:

# ... (i, photo_path in enumerate...)
filename = os.path.basename(photo_path)
# ... (size, date, timestamp) ...

# NEU: Wasserzeichen-Status bestimmen
watermark_value = "☑" if (i - 1) in self.watermark_photo_indices else "☐"

# NEU: 'watermark_value' als letztes Element im 'values'-Tupel hinzufügen
self.photo_tree.insert("", "end", values=(i, filename, size, date, timestamp, watermark_value))


2.4. remove_selected_photo

Erweitere die Funktion, um self.watermark_photo_indices zu aktualisieren, wenn ein Foto entfernt wird (Indizes müssen neu berechnet werden):

def remove_selected_photo(self):
    """Entfernt ausgewähltes Foto"""
    selection = self.photo_tree.selection()
    if selection:
        index = self.photo_tree.index(selection[0])
        self.photo_paths.pop(index)

        # NEU: Wasserzeichen-Indizes aktualisieren
        # Wenn der gelöschte Index markiert war, entferne ihn
        if index in self.watermark_photo_indices:
            self.watermark_photo_indices.remove(index)
        
        # Indizes verschieben, die größer als der entfernte Index sind
        updated_indices = []
        for i in self.watermark_photo_indices:
            if i > index:
                updated_indices.append(i - 1)
            else:
                updated_indices.append(i)
        self.watermark_photo_indices = updated_indices
        # /NEU

        self._update_photo_table()
        self._update_photo_preview()


2.5. clear_photos

Füge einen Aufruf hinzu, um die Foto-Wasserzeichen-Auswahl zurückzusetzen:

def clear_photos(self):
    """Entfernt alle Fotos"""
    self.photo_paths.clear()
    self.clear_photo_watermark_selection() # NEU
    self._update_photo_table()
    self._update_photo_preview()


2.6. Neue Methoden (analog zu Video-WM)

Füge die folgenden neuen Methoden zur DragDropFrame-Klasse hinzu:

def set_photo_watermark_column_visible(self, visible: bool):
    """Zeigt oder verbirgt die Wasserzeichen-Spalte für Fotos"""
    if visible:
        self.photo_tree.column("WM", width=20, minwidth=30, stretch=False)
    else:
        self.photo_tree.column("WM", width=0, minwidth=0, stretch=False)
    self.photo_tree.update_idletasks()

def get_watermark_photo_indices(self):
    """Gibt die Liste der für Wasserzeichen ausgewählten Foto-Indizes zurück"""
    return self.watermark_photo_indices

def clear_photo_watermark_selection(self):
    """Löscht die Foto-Wasserzeichen-Auswahl"""
    self.watermark_photo_indices = []
    self._update_photo_table()

def _on_photo_watermark_checkbox_click(self, event):
    """Verarbeitet Klicks auf die Foto-Wasserzeichen-Spalte (Mehrfachauswahl)"""
    # Prüfen, ob Spalte überhaupt sichtbar ist
    if self.photo_tree.column("WM", "width") == 0:
        return

    region = self.photo_tree.identify_region(event.x, event.y)
    if region != "cell":
        return

    column = self.photo_tree.identify_column(event.x)
    # Spalten: #0 (tree), #1 (Nr), #2 (Datei), #3 (Größe), #4 (Datum), #5 (Uhrzeit), #6 (WM)
    if column != "#6":
        return

    item = self.photo_tree.identify_row(event.y)
    if not item:
        return

    index = self.photo_tree.index(item)

    # Multi-Auswahl-Logik (Toggle):
    if index in self.watermark_photo_indices:
        self.watermark_photo_indices.remove(index)
    else:
        self.watermark_photo_indices.append(index)

    self._update_photo_table()

    # Verhindere, dass die Reihe ausgewählt wird (optional, aber gut für Checkbox-Feeling)
    self.photo_tree.selection_remove(self.photo_tree.selection())


3. Änderungen an app.py (Orchestrierung)

Klasse: VideoGeneratorApp

3.1. update_watermark_column_visibility

Modifiziere diese bestehende Methode, um auch die Sichtbarkeit der Foto-WM-Spalte zu steuern (Validierung angepasst an Anforderung).

def update_watermark_column_visibility(self):
    """Aktualisiert die Sichtbarkeit der Wasserzeichen-Spalte basierend auf Kunde-Status"""
    form_data = self.form_fields.get_form_data()

    # --- Video-Logik (bleibt unverändert) ---
    video_gewaehlt = form_data.get("handcam_video", False) or form_data.get("outside_video", False)
    video_bezahlt = form_data.get("ist_bezahlt_handcam_video", False) or form_data.get("ist_bezahlt_outside_video", False)
    video_wm_sichtbar = video_gewaehlt and not video_bezahlt
    
    # ... (Debug-Ausgaben für Video) ...
    
    self.drag_drop.set_watermark_column_visible(video_wm_sichtbar)
    if not video_wm_sichtbar:
        self.drag_drop.clear_watermark_selection()
    
    # --- NEU: Foto-Logik ---
    foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
    foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
    foto_wm_sichtbar = foto_gewaehlt and not foto_bezahlt

    print(f"🔍 Foto-Wasserzeichen-Spalte Update:")
    print(f"   Foto gewählt: {foto_gewaehlt}, Foto bezahlt: {foto_bezahlt}")
    print(f"   → Spalte sichtbar: {foto_wm_sichtbar}")

    # Rufe die neue Methode in drag_drop auf
    self.drag_drop.set_photo_watermark_column_visible(foto_wm_sichtbar)

    # Wenn Spalte nicht mehr sichtbar, lösche Auswahl
    if not foto_wm_sichtbar:
        self.drag_drop.clear_photo_watermark_selection()


3.2. erstelle_video

Modifiziere diese Methode, um die Foto-WM-Auswahl zu validieren und die Indizes an den payload zu übergeben.

Neue Validierung hinzufügen:

Füge (nach der if error_messages:-Prüfung) eine Validierung für die Foto-WM-Auswahl hinzu.

# ... (nach 'if error_messages:' Block)

# NEU: Foto-Wasserzeichen-Validierung (Validierung angepasst)
foto_gewaehlt = form_data.get("handcam_foto", False) or form_data.get("outside_foto", False)
foto_bezahlt = form_data.get("ist_bezahlt_handcam_foto", False) or form_data.get("ist_bezahlt_outside_foto", False)
foto_wm_erforderlich = foto_gewaehlt and not foto_bezahlt

watermark_photo_indices = self.drag_drop.get_watermark_photo_indices()

if foto_wm_erforderlich and not watermark_photo_indices:
    messagebox.showwarning("Fehlende Auswahl", 
                           "Sie haben ein Foto-Produkt als 'nicht bezahlt' markiert, aber kein Foto für das Wasserzeichen ausgewählt.\n\n"
                           "Bitte wählen Sie mindestens ein Foto in der '💧' Spalte aus.")
    return
# /NEU

# ... (Restliche Validierung, z.B. 'kunde = Kunde(...)')


payload erweitern:

Füge dem payload-Dictionary die Liste der Foto-Indizes hinzu.

payload = {
    # ... (bestehende keys)
    "create_watermark_version": video_gewaehlt and not video_bezahlt, # Angepasste Logik
    "watermark_clip_index": self.drag_drop.get_watermark_clip_index(),
    "watermark_photo_indices": watermark_photo_indices # NEU
}


4. Änderungen an processor.py (Backend)

Klasse: VideoProcessor

4.1. _execute_video_creation_with_intro_only

Modifiziere diese Methode, um die Foto-Wasserzeichen-Verarbeitung auszulösen.

Daten aus Payload holen:

Am Anfang der Methode:

watermark_clip_index = payload.get("watermark_clip_index", None)
watermark_photo_indices = payload.get("watermark_photo_indices", []) # NEU


Neuen Verarbeitungsblock hinzufügen:

Füge diesen Block nach der Video-Verarbeitung (nach dem else: ... self._update_progress(10, TOTAL_STEPS)) und vor der finalen Foto-Verarbeitung (# --- FOTO VERARBEITUNG (Schritt 11) ---) ein.

# ... (Ende des Video-Verarbeitungsblocks)

# --- NEU: FOTO WASSERZEICHEN VERARBEITUNG ---
if watermark_photo_indices and photo_paths:
    self._check_for_cancellation()
    self._update_status("Erstelle Wasserzeichen-Vorschau für Fotos...")

    # 1. Pfade der ausgewählten Fotos holen
    selected_photo_paths = []
    for i in watermark_photo_indices:
        if i < len(photo_paths):
            selected_photo_paths.append(photo_paths[i])

    if selected_photo_paths:
        # 2. Preview-Verzeichnis erstellen (Ziel: base_output_dir/Preview_Foto)
        try:
            preview_dir = self._generate_watermark_photo_directory(base_output_dir)

            # 3. Jedes ausgewählte Foto verarbeiten
            processed_count = 0
            for photo_path in selected_photo_paths:
                self._check_for_cancellation()
                if os.path.exists(photo_path):
                    self._create_photo_with_watermark(photo_path, preview_dir)
                    processed_count += 1

            print(f"{processed_count} Foto(s) mit Wasserzeichen verarbeitet und in {preview_dir} gespeichert.")

        except Exception as e:
            print(f"Fehler bei der Erstellung der Foto-Wasserzeichen: {e}")
            self._update_status(f"Fehler bei Foto-WM: {e}")

# --- FOTO VERARBEITUNG (Schritt 11) ---
self._check_for_cancellation()
# ... (Rest der Methode)


4.2. Modifikation bestehender Methoden in processor.py

Modifiziere _generate_watermark_video_path:

Benenne den Ordner Wasserzeichen_Video in Preview_Video um.

def _generate_watermark_video_path(self, base_output_dir, base_filename):
    """Generiert den Pfad für die Wasserzeichen-Video-Version"""
    # ALT: watermark_dir = os.path.join(base_output_dir, "Wasserzeichen_Video")
    watermark_dir = os.path.join(base_output_dir, "Preview_Video") # NEU

    try:
        os.makedirs(watermark_dir, exist_ok=True)
    except PermissionError as e:
        error_msg = f"Zugriff verweigert beim Erstellen des Vorschau-Ordners\n\n" # Name geändert
        error_msg += f"Basis-Verzeichnis: {base_output_dir}\n"
        error_msg += f"Unterordner: Preview_Video\n\n" # Name geändert
        error_msg += f"Technische Details: {str(e)}"
        raise PermissionError(error_msg)
    except OSError as e:
        error_msg = f"Fehler beim Erstellen des Vorschau-Ordners\n\n" # Name geändert
        error_msg += f"Voller Pfad: {watermark_dir}\n\n"
        error_msg += f"Technische Details: {str(e)}"
        raise OSError(error_msg)

    output_filename = f"{base_filename}_preview.mp4"
    full_output_path = os.path.join(watermark_dir, output_filename)

    return full_output_path


4.3. Neue Helper-Methoden in processor.py

Füge die folgenden zwei neuen Methoden zur VideoProcessor-Klasse hinzu:

def _generate_watermark_photo_directory(self, base_output_dir):
    """
    Erstellt den Ordner 'Preview_Foto' innerhalb des base_output_dir.
    """
    preview_dir_path = os.path.join(base_output_dir, "Preview_Foto")

    try:
        os.makedirs(preview_dir_path, exist_ok=True)
        return preview_dir_path
    except PermissionError as e:
        error_msg = f"Zugriff verweigert beim Erstellen des Foto-Vorschau-Ordners\n\n"
        error_msg += f"Pfad: {preview_dir_path}\n\n"
        error_msg += f"Technische Details: {str(e)}"
        raise PermissionError(error_msg)
    except OSError as e:
        error_msg = f"Fehler beim Erstellen des Foto-Vorschau-Ordners\n\n"
        error_msg += f"Pfad: {preview_dir_path}\n\n"
        error_msg += f"Technische Details: {str(e)}"
        raise OSError(error_msg)

def _create_photo_with_watermark(self, input_photo_path, output_dir):
    """
    Verwendet FFmpeg, um ein einzelnes Foto auf 720p (Höhe) zu skalieren
    und ein Wasserzeichen (80% Transparenz) darüber zu legen.
    """
    wasserzeichen_path = os.path.join(os.path.dirname(self.hintergrund_path), "skydivede_wasserzeichen.png")

    if not os.path.exists(wasserzeichen_path):
        print(f"Warnung: Wasserzeichen-Datei nicht gefunden: {wasserzeichen_path}")
        return
    if not os.path.exists(input_photo_path):
        print(f"Warnung: Eingabe-Foto nicht gefunden: {input_photo_path}")
        return

    output_filename = os.path.basename(input_photo_path)
    # Entferne evtl. ".png" Suffix falls das Original-Format .jpg war, aber ffmpeg .png erzwingt
    # Wir behalten das Original-Format bei, indem wir den Original-Dateinamen verwenden.
    output_path = os.path.join(output_dir, output_filename)
    
    target_height = 720
    alpha_level = 0.8 # NEU: 80% Transparenz

    # FFmpeg Filter:
    # 1. [0:v] (Input-Foto) skalieren auf 720px Höhe, Seitenverhältnis beibehalten
    # 2. [1:v] (Wasserzeichen) skalieren, so dass es in 720px Höhe passt
    # 3. [wm_orig] (Wasserzeichen) Transparenz auf 80% setzen
    # 4. [v][wm_scaled] (beide) überlagern (mittig)
    
    watermark_filter = (
        f"[0:v]scale=w=-2:h={target_height}[v];"
        f"[1:v]scale=w=-2:h={target_height}:force_original_aspect_ratio=decrease[wm_orig];"
        f"[wm_orig]colorchannelmixer=aa={alpha_level}[wm_scaled];"
        f"[v][wm_scaled]overlay=(W-w)/2:(H-h)/2"
    )

    command = [
        "ffmpeg", "-y",
        "-i", input_photo_path,
        "-i", wasserzeichen_path,
        "-filter_complex", watermark_filter,
        "-frames:v", "1",  # Wichtig: Nur einen Frame (das Bild) ausgeben
        # '-q:v', '2' # Optional: Qualität für JPG sichern
        output_path
    ]

    try:
        subprocess.run(command, capture_output=True, text=True, check=True, creationflags=SUBPROCESS_CREATE_NO_WINDOW)
    except subprocess.CalledProcessError as e:
        print(f"Fehler bei FFmpeg-Foto-Wasserzeichen für {output_filename}:")
        print(f"STDERR: {e.stderr}")
        raise e
