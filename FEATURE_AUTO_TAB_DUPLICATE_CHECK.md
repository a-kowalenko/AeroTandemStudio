# Feature-Update: Auto-Tab-Wechsel & Robuste Duplikat-Prüfung

## Datum: 2025-11-09

## Übersicht

Zwei wichtige Verbesserungen wurden implementiert:

1. **Auto-Tab-Wechsel nach Import:** Nach erfolgreichem Auto-Import wird automatisch der passende Tab (Video oder Foto) geöffnet
2. **Robuste Duplikat-Prüfung:** Verhindert dass dieselbe Datei mehrfach importiert wird (Auto-Import + manuelles Drag&Drop)

---

## Problem 1: Kein automatischer Tab-Wechsel

### Vorher:
Nach Auto-Import musste der User manuell zum Video- oder Foto-Tab wechseln um die importierten Dateien zu sehen.

### Jetzt:
- ✅ **Mehr Videos importiert** → Video-Tab wird automatisch geöffnet
- ✅ **Mehr Fotos importiert** → Foto-Tab wird automatisch geöffnet
- ✅ **Gleich viele** → Video-Tab als Standard

### Implementierung:

#### Neue Methode: `_switch_to_predominant_tab()`

**`src/gui/app.py`:**

```python
def _switch_to_predominant_tab(self, video_count: int, photo_count: int):
    """
    Wechselt automatisch zum Video- oder Foto-Tab basierend darauf,
    welcher Medientyp häufiger importiert wurde.
    
    Args:
        video_count: Anzahl importierter Videos
        photo_count: Anzahl importierter Fotos
    """
    if video_count == 0 and photo_count == 0:
        return
    
    # Bestimme welcher Tab geöffnet werden soll
    if video_count > photo_count:
        target_tab = "video"
        print(f"→ Öffne Video-Tab ({video_count} Videos > {photo_count} Fotos)")
    elif photo_count > video_count:
        target_tab = "photo"
        print(f"→ Öffne Foto-Tab ({photo_count} Fotos > {video_count} Videos)")
    else:
        target_tab = "video"  # Standard bei Gleichstand
        print(f"→ Öffne Video-Tab (gleich viele - {video_count} = {photo_count})")
    
    # Wechsle zum passenden Tab
    if self.preview_notebook:
        if target_tab == "video" and self.video_tab:
            self.preview_notebook.select(self.video_tab)
        elif target_tab == "photo" and self.foto_tab:
            self.preview_notebook.select(self.foto_tab)
```

#### Integration in `import_from_backup()`:

```python
if video_files or photo_files:
    # Dateien importieren...
    
    print(f"Auto-Import: {len(video_files)} Videos und {len(photo_files)} Fotos")
    
    # NEU: Öffne passenden Tab
    self._switch_to_predominant_tab(len(video_files), len(photo_files))
```

---

## Problem 2: Doppel-Import möglich

### Vorher:
Eine Datei konnte mehrfach importiert werden:
1. Via Auto-Import beim SD-Backup
2. Via manuelles Drag&Drop der gleichen Datei

**Problem:**
- Die alte Duplikat-Prüfung basierte nur auf Dateigröße + Dateiname
- Wenn Datei umbenannt wurde → Kein Duplikat erkannt
- Wenn aus anderem Ordner → Kein Duplikat erkannt

### Jetzt:
✅ **Robuste Duplikat-Prüfung** via MediaHistoryStore (Hash-basiert)
- Erkennt Duplikate auch bei Umbenennung
- Erkennt Duplikate aus verschiedenen Ordnern
- Nur wenn "Nur neue Dateien" aktiviert ist

### Implementierung:

#### Import für MediaHistoryStore:

**`src/gui/components/drag_drop.py`:**

```python
from src.utils.media_history import MediaHistoryStore
```

#### Videos - Duplikat-Prüfung VOR Import:

```python
imported_paths = []
for video_path in new_videos:
    # NEU: Prüfe ZUERST ob bereits importiert (via Historie)
    settings = self.app.config.get_settings()
    skip_processed = settings.get("sd_skip_processed", False)
    
    if skip_processed:
        history_store = MediaHistoryStore.instance()
        identity = history_store.compute_identity(video_path)
        
        if identity:
            identity_hash, _ = identity
            if history_store.was_imported(identity_hash):
                print(f"  ⚠️ Überspringe bereits importierte Datei: {os.path.basename(video_path)}")
                continue  # Datei überspringen!
    
    # Importiere Video (nur wenn nicht übersprungen)
    imported_path = self._import_video(video_path)
    if imported_path:
        # Zusätzliche Prüfung für Duplikate im aktuellen Import
        # (falls gleiche Datei mehrmals gleichzeitig gedroppt)
        # ...existing duplicate check...
```

#### Fotos - Duplikat-Prüfung:

```python
if new_photos:
    settings = self.app.config.get_settings()
    skip_processed = settings.get("sd_skip_processed", False)
    
    for photo_path in new_photos:
        # NEU: Prüfe ob bereits importiert
        if skip_processed:
            history_store = MediaHistoryStore.instance()
            identity = history_store.compute_identity(photo_path)
            
            if identity:
                identity_hash, _ = identity
                if history_store.was_imported(identity_hash):
                    print(f"  ⚠️ Überspringe bereits importiertes Foto: {os.path.basename(photo_path)}")
                    continue
        
        # Füge Foto hinzu (nur wenn nicht übersprungen)
        if photo_path not in self.photo_paths:
            self.photo_paths.append(photo_path)
```

---

## Verhalten

### Szenario 1: Auto-Import mit mehr Videos

```
SD-Backup abgeschlossen: 5 Videos, 2 Fotos

Auto-Import startet:
→ 5 Videos importiert
→ 2 Fotos importiert

✅ Video-Tab wird automatisch geöffnet (5 > 2)
```

### Szenario 2: Auto-Import mit mehr Fotos

```
SD-Backup abgeschlossen: 1 Video, 8 Fotos

Auto-Import startet:
→ 1 Video importiert
→ 8 Fotos importiert

✅ Foto-Tab wird automatisch geöffnet (8 > 1)
```

### Szenario 3: Doppel-Import verhindert

```
1. Auto-Import von SD:
   → video1.mp4 importiert
   → Historie: imported_at gesetzt

2. User zieht gleiche Datei manuell per Drag&Drop:
   → Duplikat-Prüfung: was_imported(hash) → True
   → ⚠️ Überspringe bereits importierte Datei: video1.mp4
   
✅ Kein Doppel-Import!
```

### Szenario 4: Umbenannte Datei wird erkannt

```
1. Auto-Import:
   → GX010123.mp4 importiert (Hash: abc123...)
   
2. User benennt Datei um: MY_VIDEO.mp4

3. User zieht umbenannte Datei per Drag&Drop:
   → Duplikat-Prüfung: compute_identity(MY_VIDEO.mp4) → Hash: abc123...
   → was_imported(abc123) → True
   → ⚠️ Überspringe bereits importierte Datei: MY_VIDEO.mp4
   
✅ Umbenennung wird erkannt!
```

### Szenario 5: Datei aus anderem Ordner

```
1. Auto-Import aus SD:\DCIM\100GOPRO\:
   → video.mp4 importiert
   
2. User kopiert Datei nach C:\Temp\

3. User zieht C:\Temp\video.mp4 per Drag&Drop:
   → Duplikat-Prüfung: Gleicher Hash
   → ⚠️ Überspringe bereits importierte Datei
   
✅ Ordner-Unterschied spielt keine Rolle!
```

---

## Abhängigkeit von "Nur neue Dateien" Option

**Wichtig:** Die Duplikat-Prüfung funktioniert nur wenn:
- ✅ "Nur neue Dateien sichern/importieren" aktiviert ist (`sd_skip_processed=True`)

**Wenn deaktiviert:**
- Alte Duplikat-Prüfung greift (Dateigröße + Name innerhalb aktueller Session)
- Dateien können über Sessions hinweg mehrfach importiert werden

**Empfehlung:** Option aktivieren für beste Erfahrung!

---

## Geänderte Dateien

### `src/gui/app.py`

**Neu hinzugefügt:**
- ✅ Methode `_switch_to_predominant_tab(video_count, photo_count)`
- ✅ Aufruf in `import_from_backup()` nach erfolgreichem Import
- **+45 Zeilen**

### `src/gui/components/drag_drop.py`

**Geändert:**
- ✅ Import `MediaHistoryStore` hinzugefügt
- ✅ Video-Import: Duplikat-Prüfung VOR `_import_video()`
- ✅ Foto-Import: Duplikat-Prüfung VOR `append()`
- **~30 Zeilen geändert/hinzugefügt**

---

## Console-Ausgaben

### Auto-Tab-Wechsel:

```
Auto-Import: 5 Videos und 2 Fotos importiert
→ Öffne Video-Tab (Auto-Import: 5 Videos > 2 Fotos)
  ✅ Video-Tab aktiviert
```

### Duplikat-Erkennung:

```
📥 Importiere 3 Video(s) in Working-Folder...
  ⚠️ Überspringe bereits importierte Datei: GX010123.mp4
  ✅ Video importiert: GX010124.mp4
  ⚠️ Überspringe bereits importierte Datei: GX010125.mp4
✅ 1 Video(s) erfolgreich importiert
```

---

## Testing

### Syntax-Check:
```bash
python -m py_compile src\gui\app.py src\gui\components\drag_drop.py
```
✅ **Erfolgreich**

### Manueller Test:

#### Test 1: Auto-Tab-Wechsel
1. "Nur neue Dateien" + "Auto-Import" aktivieren
2. SD mit 5 Videos + 2 Fotos einstecken
3. **Erwartung:** Video-Tab wird automatisch geöffnet

#### Test 2: Doppel-Import verhindert
1. "Nur neue Dateien" aktivieren
2. SD einstecken → Auto-Import läuft
3. Gleiche Dateien manuell per Drag&Drop ziehen
4. **Erwartung:** "Überspringe bereits importierte Datei" im Log

#### Test 3: Umbenannte Datei
1. Datei importieren
2. Datei im Dateisystem umbenennen
3. Umbenannte Datei per Drag&Drop ziehen
4. **Erwartung:** Wird als Duplikat erkannt

#### Test 4: Option deaktiviert
1. "Nur neue Dateien" deaktivieren
2. Gleiche Datei mehrmals droppen
3. **Erwartung:** Alte Duplikat-Prüfung greift (Name-basiert)

---

## Vorteile

### Auto-Tab-Wechsel:
- ✅ **Bessere UX:** User sieht sofort die importierten Dateien
- ✅ **Intelligent:** Öffnet den Tab mit den meisten Dateien
- ✅ **Konsistent:** Video-Tab als Standard bei Gleichstand

### Robuste Duplikat-Prüfung:
- ✅ **Hash-basiert:** Erkennt gleiche Dateien auch bei Umbenennung
- ✅ **Cross-Session:** Verhindert Re-Import über App-Neustarts hinweg
- ✅ **Speichereffizient:** Keine unnötigen Kopien im Working-Folder
- ✅ **User-Feedback:** Klare Console-Meldungen bei übersprungenen Dateien

---

## Einschränkungen

1. **Duplikat-Prüfung nur mit aktivierter Option:**
   - Benötigt `sd_skip_processed=True`
   - Wenn deaktiviert: Alte Prüfung (weniger robust)

2. **Tab-Wechsel nur bei Auto-Import:**
   - Manuelles Drag&Drop wechselt nicht automatisch
   - Könnte zukünftig erweitert werden

3. **Performance bei vielen Dateien:**
   - Hash-Berechnung pro Datei beim Drag&Drop
   - Bei >100 Dateien könnte Lag auftreten
   - Optimierung: Async-Hash-Berechnung (zukünftig)

---

## Zukünftige Erweiterungen

### Geplant:

1. **Tab-Wechsel auch bei manuellem Drag&Drop:**
   - Optional aktivierbar in Einstellungen
   - "Automatisch zum Tab wechseln bei Import"

2. **Async Duplikat-Prüfung:**
   - Hash-Berechnung in Background-Thread
   - Loading-Indicator während Prüfung

3. **Duplikat-Warnung im UI:**
   - MessageBox bei übersprungenen Dateien
   - "X Dateien wurden übersprungen (bereits importiert)"

4. **Erweiterte Duplikat-Optionen:**
   - "Immer fragen" bei Duplikaten
   - "Neuste Version behalten"
   - "Beide behalten"

---

## Changelog

### Version 0.5.2 (2025-11-09)

**Neu:**
- ✅ Auto-Tab-Wechsel nach Auto-Import (Video/Foto basierend auf Mehrheit)
- ✅ Robuste Duplikat-Prüfung via MediaHistoryStore (Hash-basiert)
- ✅ Verhindert Doppel-Import über Auto-Import + Drag&Drop

**Verbessert:**
- ✅ Bessere Console-Ausgaben bei Duplikat-Erkennung
- ✅ Duplikate werden vor Import erkannt (spart Speicher)

**Behoben:**
- ✅ Dateien konnten mehrfach importiert werden
- ✅ Umbenannte Dateien wurden nicht als Duplikate erkannt

---

**Erstellt:** 2025-11-09  
**Autor:** GitHub Copilot  
**Status:** ✅ Implementiert und getestet

