# Datenfluss Dokumentation - AeroTandemStudio Video-Verarbeitung

## 🎯 Überblick

Dieser Dokument beschreibt den **kompletten Datenfluss** der Video-Verarbeitung von der Auswahl bis zur Finalisierung.

---

## 📊 Der komplette Workflow

### **Phase 1: Drag & Drop (Videos hinzufügen)**

```
Benutzer zieht Videos in drag_drop.py
         ↓
drag_drop.handle_drop() wird aufgerufen
         ↓
Videos werden in self.video_paths gespeichert (ORIGINAL-PFADE!)
         ↓
_check_if_reencoding_needed() prüft, ob alle Videos das gleiche Format haben
         ↓
add_files() wird aufgerufen
         ↓
_update_app_preview() wird aufgerufen
         ↓
app.update_video_preview(video_paths) wird aufgerufen
```

---

### **Phase 2: Vorschau-Erstellung (video_preview.py)**

```
app.update_video_preview(original_video_paths)
         ↓
video_preview.update_preview(original_paths)
         ↓
_start_preview_creation_thread(video_paths)
         ↓
_create_temp_directory() ← Erstellt work-folder (temp_dir)
         ↓
_create_combined_preview() wird in separatem Thread gestartet
         ↓
_check_video_formats() ← Prüft Kompatibilität aller Videos
         ↓
         ├─→ Fall A: Alle Videos kompatibel?
         │        ↓
         │   _prepare_video_copies(needs_reencoding=False)
         │        ↓
         │   Kopiert Videos in work-folder (keine Neukodierung)
         │        ↓
         │   _cache_metadata_for_copy() ← Speichert Metadaten im Cache
         │
         └─→ Fall B: Verschiedene Formate?
                  ↓
              _prepare_video_copies(needs_reencoding=True)
                  ↓
              Kodiert alle Videos auf 1080p@30fps
                  ↓
              _reencode_single_clip() ← FFmpeg-Aufruf
                  ↓
              Videos in work-folder gespeichert
                  ↓
              _cache_metadata_for_copy() ← Speichert Metadaten im Cache
         ↓
_create_fast_combined_video(temp_copy_paths)
         ↓
Kombiniert alle Kopien zu einer Vorschau (ohne Re-Encoding)
         ↓
_update_ui_success() ← UI wird aktualisiert
         ↓
video_player.load_video() ← Video wird in der UI angezeigt
```

**Wichtige Zuordnungen nach dieser Phase:**
- `video_copies_map`: { original_path → temp_copy_path }
- `metadata_cache`: { original_path → {duration, size, date, ...} }
- `drag_drop.video_paths`: [ original_path1, original_path2, ... ]

---

### **Phase 3: Video-Schneiden/Teilen (video_cutter.py)**

```
Benutzer klickt auf "✂ Schneiden" Button
         ↓
drag_drop.open_cut_dialog(original_path)
         ↓
app.request_cut_dialog(original_path)
         ↓
VideoCutterDialog wird geöffnet
         ↓
Dialog zeigt die KOPIE aus work-folder (copy_path)
         ↓
Benutzer schneidet oder teilt das Video
         ↓
         ├─→ SCHNEIDEN (Trim):
         │        ↓
         │   _run_cut_task(start_ms, end_ms)
         │        ↓
         │   FFmpeg schneidet die Kopie
         │        ↓
         │   Überschreibt die KOPIE im work-folder
         │        ↓
         │   on_complete_callback({"action": "cut"})
         │
         └─→ TEILEN (Split):
                  ↓
              _run_split_task(split_time_ms)
                  ↓
              FFmpeg erstellt:
              - Teil 1: Überschreibt die KOPIE im work-folder
              - Teil 2: Neue Datei mit __part2__ Suffix
                  ↓
              on_complete_callback({"action": "split", "new_copy_path": part2_path})
         ↓
Dialog schließt sich
         ↓
on_complete_callback wird aufgerufen (app.on_cut_complete)
```

---

### **Phase 4: Nach Schneiden/Teilen - Automatische Vorschau-Regenerierung**

```
app.on_cut_complete(original_path, index, result)
         ↓
         ├─→ Wenn action == "cut":
         │        ↓
         │   Die Kopie im work-folder wurde überschrieben
         │   paths_to_refresh = [original_path]
         │
         └─→ Wenn action == "split":
                  ↓
              Neue Kopie existiert jetzt auch im work-folder
              new_original_placeholder = base + "_split_" + uuid
                  ↓
              drag_drop.insert_video_path_at_index(new_placeholder, index+1)
                  ↓
              video_preview.register_new_copy(new_placeholder, new_copy_path)
                  ↓
              paths_to_refresh = [original_path, new_placeholder]
         ↓
video_preview.refresh_metadata_async(paths_to_refresh)
         ↓
Thread wird gestartet
         ↓
_run_refresh_metadata_task()
         ↓
Für jeden Clip im paths_to_refresh:
  - _cache_metadata_for_copy() ← Aktualisiert Cache mit neuen Metadaten
         ↓
on_complete_callback() wird aufgerufen
         ↓
app._on_metadata_refreshed()
         ↓
drag_drop.refresh_table() ← Tabelle wird neu gezeichnet (mit aktualisierten Metadaten aus Cache)
         ↓
video_preview.regenerate_preview_after_cut(original_paths)
         ↓
_regenerate_task()
         ↓
_create_fast_combined_video(copy_paths)
         ↓
Kombiniert die (möglicherweise veränderten) Kopien
         ↓
_update_ui_success_after_cut()
         ↓
video_player.load_video() ← Neue Vorschau wird angezeigt
```

---

## 🔑 Kritische Konzepte

### **1. Original-Pfade vs. Kopie-Pfade**

- **Original-Pfade**: Vom Benutzer hereingezogene Videos (nicht verändert)
  - Gespeichert in: `drag_drop.video_paths[]`
  
- **Kopie-Pfade**: Videos im work-folder (werden modifiziert)
  - Mapping: `video_preview.video_copies_map{original → copy}`
  - Physischer Speicherort: `video_preview.temp_dir`

### **2. Der Metadaten-Cache**

```python
video_preview.metadata_cache = {
    "original_path_1": {
        "duration": "00:15",
        "duration_sec_str": "15.5",
        "size": "42.3 MB",
        "size_bytes": 44390400,
        "date": "29.01.2025",
        "timestamp": "14:32:45"
    },
    ...
}
```

- **Zweck**: Schnelle Anzeige von Metadaten in der Tabelle
- **Aktualisiert nach**:
  - Initiale Vorschau-Erstellung
  - Nach Schneiden/Teilen (_cache_metadata_for_copy)
  - Über refresh_metadata_async()

### **3. Encoding-Logik (Fall A vs. Fall B)**

**Fall A: Kompatibel (Schnell)**
- Alle Videos haben: gleicher Codec, gleiche Auflösung, gleiche Framerate, gleicher Pixelformat
- ✅ Werden NUR kopiert (keine Neukodierung)
- ✅ Schnelle Vorschau-Erstellung

**Fall B: Nicht kompatibel (Langsam)**
- Videos haben unterschiedliche Codecs/Auflösungen/Framerates
- ❌ Werden alle auf 1080p@30fps neu kodiert
- ⚠️ Längere Vorschau-Erstellung

---

## 🔄 Callback-Kette nach Schneiden

```
VideoCutterDialog.on_complete_callback()
  ↓
app.on_cut_complete()
  ↓
app._on_metadata_refreshed() ← Nach Metadaten-Aktualisierung
  ↓
drag_drop.refresh_table() ← Tabelle aktualisiert
video_preview.regenerate_preview_after_cut() ← Vorschau regeneriert
  ↓
video_preview._regenerate_task()
  ↓
app.video_player.load_video() ← UI zeigt neue Vorschau
```

---

## 📝 Wichtige Dateien & Methoden

| Datei | Klasse | Methode | Zweck |
|-------|--------|---------|-------|
| drag_drop.py | DragDropFrame | handle_drop() | Dateien hereingezogen |
| drag_drop.py | DragDropFrame | insert_video_path_at_index() | Neuen Split-Clip hinzufügen |
| drag_drop.py | DragDropFrame | refresh_table() | Tabelle neu zeichnen |
| video_preview.py | VideoPreview | update_preview() | Vorschau erstellen |
| video_preview.py | VideoPreview | regenerate_preview_after_cut() | Nach Schneiden neu kombinieren |
| video_preview.py | VideoPreview | refresh_metadata_async() | Metadaten asynchron aktualisieren |
| video_cutter.py | VideoCutterDialog | _on_apply() | Schneiden starten |
| video_cutter.py | VideoCutterDialog | _on_split() | Teilen starten |
| app.py | VideoGeneratorApp | request_cut_dialog() | Dialog öffnen |
| app.py | VideoGeneratorApp | on_cut_complete() | Nach Schneiden/Teilen |
| app.py | VideoGeneratorApp | _on_metadata_refreshed() | Nach Metadaten-Update |

---

## ⚙️ Technische Details

### **Temporärer Work-Folder**
- Erstellt in: `tempfile.gettempdir()/aero_studio_preview_*`
- Gelöscht wenn:
  - Neue Vorschau erstellt wird
  - App geschlossen wird
  - Alle Videos gelöscht werden

### **Metadaten-Caching**
- **Wann gefüllt**: Bei der Erstellung der Kopien
- **Wann aktualisiert**: Mit `refresh_metadata_async()` nach Schneiden
- **Wann geleert**: Mit `clear_metadata_cache()` oder `clear_preview()`

### **FFmpeg-Encoding-Parameter (Fall B)**
```
Auflösung:    1920x1080 (Full HD)
Framerate:    30 fps
Video-Codec:  libx264 (H.264)
Audio-Codec:  aac
Audio-Rate:   48000 Hz
Channels:     2 (Stereo)
CRF:          23 (Qualität)
Preset:       fast
```

---

## 🐛 Häufige Fehlerquellen

1. **Kopie nicht gefunden**: Wenn video_preview.temp_dir gelöscht wurde
2. **WinError 32**: Wenn Player-Datei noch geladen ist (wird handled via clear_preview())
3. **Metadaten veraltet**: Wenn refresh_metadata_async() nicht aufgerufen wurde
4. **Split-Clip nicht in Tabelle**: Wenn insert_video_path_at_index() nicht aufgerufen wurde

---

## ✅ Validierungs-Checkliste

Nach der Implementierung prüfen:

- [ ] Videos können hereingezogen werden
- [ ] Vorschau wird erstellt (Fall A: schnell, Fall B: mit Kodierung)
- [ ] Metadaten werden in Tabelle angezeigt
- [ ] Schneiden-Dialog öffnet sich
- [ ] Nach Schneiden wird Vorschau automatisch regeneriert
- [ ] Tabelle zeigt neue Dauer nach Schneiden
- [ ] Teilen erzeugt neues Clip mit __part2__
- [ ] Beide Clips werden in Tabelle angezeigt
- [ ] Player zeigt neue Vorschau nach Schneiden
- [ ] Temp-Folder wird beim Beenden gelöscht


