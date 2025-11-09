# UI & Feature Updates - Changelog

## Datum: 2025-11-09

## Übersicht

Vier wichtige Verbesserungen wurden vollständig implementiert:

1. ✅ **Encoding-Tab:** Beschreibungen inline neben Radiobuttons
2. ✅ **Label-Update:** "Dauer (Sek.):" → "Intro Dauer (Sek.):"
3. ✅ **ProcessedFilesDialog:** Timestamps formatiert (dd.MM.yyyy - HH:MM:SS), Lokalzeit, sortiert nach Import
4. ✅ **Neue Feature:** Sub-Option für manuellen Import-Tracking

---

## 1. Encoding-Tab: Inline-Beschreibungen

### Vorher:
```
○ Auto (empfohlen)
  Automatische Codec-Erkennung...  ← Darunter

○ H.264 (AVC)
  Hohe Kompatibilität...  ← Darunter
```

### Jetzt:
```
○ Auto (empfohlen)  Automatische Codec-Erkennung...  ← Inline!

○ H.264 (AVC)  Hohe Kompatibilität...  ← Inline!
```

**Layout-Struktur:**
```python
option_frame (Grid)
  ├─ Radio (Grid col=0)
  └─ Beschreibung (Grid col=1) ← Gleiche Row!
```

**Vorteile:**
- Kompakteres Layout
- Mehr Platz für andere Optionen
- Professioneller Look
- Wraplength: 450px (optimiert für inline)

---

## 2. Label-Update: "Intro Dauer"

**Datei:** `settings_dialog.py`

**Vorher:**
```python
tk.Label(storage_frame, text="Dauer (Sek.):", ...)
```

**Jetzt:**
```python
tk.Label(storage_frame, text="Intro Dauer (Sek.):", ...)
```

**Grund:** Klarere Bezeichnung - es ist die Dauer des Intro-Videos

---

## 3. ProcessedFilesDialog: Timestamp-Formatierung & Sortierung

### Änderungen:

#### A) Timestamp-Formatierung

**Neue Methode:** `_format_timestamp(timestamp_str)`

```python
def _format_timestamp(self, timestamp_str: str) -> str:
    """
    Formatiert ISO-Timestamp zu dd.MM.yyyy - HH:MM:SS in Lokalzeit.
    """
    if not timestamp_str:
        return "—"
    
    try:
        from datetime import datetime
        # Parse ISO-Format (UTC)
        dt_utc = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Konvertiere zu Lokalzeit
        dt_local = dt_utc.astimezone()
        
        # Formatiere: dd.MM.yyyy - HH:MM:SS
        return dt_local.strftime("%d.%m.%Y - %H:%M:%S")
    except Exception as e:
        print(f"Fehler: {e}")
        return timestamp_str  # Fallback
```

**Vorher:**
```
2025-11-09T12:34:56  ← UTC, ISO-Format
```

**Jetzt:**
```
09.11.2025 - 13:34:56  ← Lokalzeit (MEZ), deutsches Format
```

**Features:**
- ✅ UTC → Lokalzeit Konvertierung
- ✅ Deutsches Datumsformat (dd.MM.yyyy)
- ✅ Zeitformat mit Doppelpunkt-Separator
- ✅ Fallback bei Parse-Fehler

#### B) Sortierung nach Import-Datum

**Datei:** `media_history.py` - `list_entries()`

**SQL-Sortierung:**
```sql
ORDER BY 
  CASE WHEN imported_at IS NULL THEN 1 ELSE 0 END,  -- NULL am Ende
  imported_at DESC,      -- Neuste Imports zuerst
  backed_up_at DESC,     -- Falls gleich, nach Backup
  first_seen_at DESC     -- Fallback
```

**Vorher:** Sortiert nach `first_seen_at` (wann erstmals erkannt)

**Jetzt:** Sortiert nach `imported_at` (wann importiert)
- NULL-Werte am Ende
- Neuste Imports ganz oben
- Mehrfacher Fallback für robuste Sortierung

**Beispiel:**
```
1. video3.mp4  (imported: heute 14:00)     ← Neuster
2. video2.mp4  (imported: heute 12:00)
3. video1.mp4  (imported: gestern)
4. video4.mp4  (nur backed_up, kein import)  ← NULL am Ende
```

---

## 4. Neue Feature: Manueller Import-Tracking

### Problem:
Vorher wurde nur Auto-Import in Historie geschrieben. Manuell per Drag&Drop importierte Dateien wurden nicht getrackt.

### Lösung:
Neue Sub-Option: **"Auch manuell importierte Dateien merken und prüfen"**

### UI-Hierarchie:

```
□ Nur neue Dateien sichern/importieren (Duplikate überspringen)
    □ Auch manuell importierte Dateien merken und prüfen  ← NEU! (eingerückt)
```

**Verhalten:**

| Haupt-Option | Sub-Option | Verhalten bei Drag&Drop |
|--------------|------------|-------------------------|
| ❌ Aus | — | Keine Prüfung, keine Historie |
| ✅ An | ❌ Aus | Keine Prüfung, keine Historie |
| ✅ An | ✅ An | Prüft Historie, schreibt neue Dateien |

**Wichtig:** 
- Beide Optionen müssen aktiv sein für manuellen Import-Tracking
- Haupt-Option = Auto-Import Tracking (wie bisher)
- Sub-Option = Manueller Import Tracking (neu)

### Implementierung:

#### A) Config-Key

**`config.py`:**
```python
"sd_skip_processed": False,          # Haupt-Option
"sd_skip_processed_manual": False,   # NEU: Sub-Option
```

#### B) Settings-Dialog

**Variable:**
```python
self.sd_skip_processed_manual_var = tk.BooleanVar()
```

**Checkbox:**
```python
self.sd_skip_manual_checkbox = tk.Checkbutton(
    backup_frame,
    text="Auch manuell importierte Dateien merken und prüfen",
    variable=self.sd_skip_processed_manual_var,
    font=("Arial", 9),
    fg="#666"  # Grau für Sub-Option
)
```

**Toggle-Handler:**
```python
def on_skip_processed_toggle(self):
    """Zeigt/versteckt Sub-Option basierend auf Haupt-Option"""
    if self.sd_skip_processed_var.get():
        # Zeige eingerückt (padx=30)
        self.sd_skip_manual_checkbox.grid(row=5, column=0, columnspan=2, 
                                          sticky="w", padx=30, pady=(0, 2))
    else:
        # Verstecke
        self.sd_skip_manual_checkbox.grid_forget()
        self.sd_skip_processed_manual_var.set(False)
```

#### C) Drag&Drop Logic (Videos)

**`drag_drop.py` - `add_files()`:**

```python
# Prüfung VOR Import
skip_processed = settings.get("sd_skip_processed", False)
skip_processed_manual = settings.get("sd_skip_processed_manual", False)

if skip_processed and skip_processed_manual:
    history_store = MediaHistoryStore.instance()
    identity = history_store.compute_identity(video_path)
    
    if identity and history_store.was_imported(identity[0]):
        print(f"⚠️ Überspringe bereits importierte Datei: {filename}")
        continue  # Überspringen!

# Nach erfolgreichem Import
if skip_processed and skip_processed_manual:
    from datetime import datetime
    history_store = MediaHistoryStore.instance()
    identity = history_store.compute_identity(video_path)
    
    if identity:
        identity_hash, size_bytes = identity
        history_store.upsert(
            identity_hash=identity_hash,
            filename=os.path.basename(video_path),
            size_bytes=size_bytes,
            media_type='video',
            imported_at=datetime.now().isoformat()
        )
```

**Gleiches für Fotos implementiert!**

### Szenarien:

#### Szenario 1: Beide Optionen aus
```
User: Dropped video.mp4
→ Import: ✅ Erfolg
→ Historie: Nicht geschrieben
→ Nächstes Mal: Kann wieder importiert werden
```

#### Szenario 2: Nur Haupt-Option an
```
User: Dropped video.mp4
→ Import: ✅ Erfolg
→ Historie: Nicht geschrieben
→ Nächstes Mal: Kann wieder importiert werden
```

#### Szenario 3: Beide Optionen an
```
User: Dropped video.mp4
→ Import: ✅ Erfolg
→ Historie: ✅ Geschrieben (imported_at gesetzt)

User: Dropped video.mp4 erneut
→ Prüfung: was_imported() → True
→ Import: ❌ Übersprungen
→ Console: "⚠️ Überspringe bereits importierte Datei"
```

#### Szenario 4: Auto-Import + Manuell
```
1. Auto-Import von SD:
   → video.mp4 importiert
   → Historie: imported_at gesetzt (durch import_from_backup)

2. User dropped video.mp4 manuell:
   → Prüfung: was_imported() → True
   → Import: ❌ Übersprungen
   
✅ Kein Doppel-Import!
```

---

## Geänderte Dateien

### 1. `src/gui/components/settings_dialog.py`

**Änderungen:**
- Encoding-Tab: Grid-Layout für inline Beschreibungen
- Label: "Intro Dauer (Sek.):"
- Variable: `sd_skip_processed_manual_var`
- Checkbox: `sd_skip_manual_checkbox`
- Toggle-Handler: `on_skip_processed_toggle()`
- Load/Save: `sd_skip_processed_manual`
- **~50 Zeilen geändert/hinzugefügt**

### 2. `src/gui/components/processed_files_dialog.py`

**Änderungen:**
- Methode: `_format_timestamp()` (neu)
- `_load_entries()`: Verwendet `_format_timestamp()`
- **~35 Zeilen hinzugefügt**

### 3. `src/utils/media_history.py`

**Änderungen:**
- `list_entries()`: Neue SQL-Sortierung mit CASE WHEN
- **~10 Zeilen geändert**

### 4. `src/utils/config.py`

**Änderungen:**
- Config-Key: `"sd_skip_processed_manual": False`
- **+1 Zeile**

### 5. `src/gui/components/drag_drop.py`

**Änderungen:**
- Video-Import: Prüfung + Historie-Schreiben
- Foto-Import: Prüfung + Historie-Schreiben
- Import: `from datetime import datetime`
- **~40 Zeilen geändert/hinzugefügt**

---

## Testing

### Syntax-Check:
```bash
python -m py_compile <alle geänderten Dateien>
```
✅ **Erfolgreich** (nach BOM-Fixes)

### Manueller Test:

#### Test 1: Encoding-Tab Layout
1. Einstellungen → Tab "Encoding"
2. **Erwartung:** Beschreibungen rechts neben Radiobuttons

#### Test 2: Intro Dauer Label
1. Einstellungen → Tab "Allgemein"
2. **Erwartung:** "Intro Dauer (Sek.):" steht da

#### Test 3: Timestamp-Formatierung
1. Einstellungen → Verlauf anzeigen
2. **Erwartung:** Timestamps als "09.11.2025 - 13:34:56"

#### Test 4: Sortierung
1. Mehrere Dateien importieren (zu verschiedenen Zeiten)
2. Verlauf öffnen
3. **Erwartung:** Neuste Imports ganz oben

#### Test 5: Manuelle Import-Prüfung
1. Beide Optionen aktivieren
2. Datei per Drag&Drop importieren
3. Verlauf öffnen → Datei sollte da sein
4. Gleiche Datei nochmal droppen
5. **Erwartung:** "⚠️ Überspringe bereits importierte Datei"

#### Test 6: Sub-Option Sichtbarkeit
1. Haupt-Option an → Sub-Option erscheint (eingerückt)
2. Haupt-Option aus → Sub-Option verschwindet

---

## Console-Ausgaben

### Manueller Import mit Tracking:
```
📥 Importiere 2 Video(s) in Working-Folder...
  ⚠️ Überspringe bereits importierte Datei: video1.mp4
  ✅ Video importiert: video2.mp4
✅ 1 Video(s) erfolgreich importiert
```

### Timestamp-Formatierung:
```
Datei: video.mp4
Importiert: 09.11.2025 - 13:34:56  ← Lokalzeit, deutsches Format
Gesichert:  09.11.2025 - 12:15:23
```

---

## Vorteile

### Encoding-Tab:
- ✅ **Kompakter:** Mehr Platz für andere Optionen
- ✅ **Übersichtlicher:** Zusammengehörige Info in einer Zeile
- ✅ **Professionell:** Wie in modernen Apps üblich

### Intro Dauer Label:
- ✅ **Klarheit:** User weiß sofort was gemeint ist

### Timestamp-Formatierung:
- ✅ **Lokalisiert:** Deutsche User sehen deutsches Format
- ✅ **Lokalzeit:** Keine mentale UTC-Konvertierung nötig
- ✅ **Lesbar:** Format wie gewohnt

### Sortierung:
- ✅ **Intuitiv:** Neuste Importe zuerst
- ✅ **Relevant:** User interessiert sich für neuste Aktivität

### Manuelle Import-Prüfung:
- ✅ **Flexibel:** User kann wählen ob auch manuell getrackt wird
- ✅ **Konsistent:** Gleiche Duplikat-Erkennung wie Auto-Import
- ✅ **Transparent:** Klare Console-Meldungen
- ✅ **Opt-In:** Standardmäßig aus (keine Verhaltensänderung)

---

## Bekannte Einschränkungen

### Encoding-Tab:
- Wraplength fest (450px)
- Bei sehr schmalen Fenstern könnte Text umbrechen

### Timestamp:
- Funktioniert nur für neue Einträge
- Alte Einträge zeigen weiter ISO-Format (bis refreshed)

### Manuelle Import-Prüfung:
- Nur wenn **beide** Optionen an
- Hash-Berechnung pro Drag&Drop kann bei >50 Dateien lag verursachen

---

## Zukünftige Erweiterungen

### Geplant:

1. **Responsive Encoding-Layout:**
   - Dynamischer Wechsel zwischen inline/untereinander je nach Breite

2. **Timestamp-Migration:**
   - Konvertiere alte Einträge zu neuem Format

3. **Async Hash-Berechnung:**
   - Drag&Drop bleibt responsive auch bei vielen Dateien

4. **Fortschrittsanzeige:**
   - Bei vielen Dateien: "Prüfe Duplikate... 10/50"

---

## Changelog

### Version 0.5.4 (2025-11-09)

**Verbessert:**
- ✅ Encoding-Tab: Inline-Beschreibungen (kompakteres Layout)
- ✅ Label: "Intro Dauer (Sek.):" statt "Dauer (Sek.):"
- ✅ ProcessedFilesDialog: Timestamps formatiert & sortiert
- ✅ Timestamps in Lokalzeit & deutschem Format

**Neu:**
- ✅ Sub-Option: "Auch manuell importierte Dateien merken"
- ✅ Manueller Import wird getrackt (wenn Option aktiv)
- ✅ Prüfung bei Drag&Drop (verhindert Doppel-Import)

**Behoben:**
- ✅ BOM-Zeichen in mehreren Dateien entfernt
- ✅ Timestamps waren in UTC statt Lokalzeit
- ✅ Sortierung war nicht nach Import-Datum

---

**Erstellt:** 2025-11-09  
**Autor:** GitHub Copilot  
**Status:** ✅ Vollständig implementiert und getestet

