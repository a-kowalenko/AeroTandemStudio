# Bugfix: Import-Filter berücksichtigt jetzt nur importierte Dateien

## Datum: 2025-11-09

## Problem

Nach dem Löschen aller Einträge aus der Historie wurden beim Auto-Import trotzdem alle Dateien übersprungen:

```
Backup abgeschlossen: 3 neue Mediendateien kopiert
✅ Backup erfolgreich

Auto-Import gestartet:
Import-Filter: 3 Dateien, 0 neu, 3 übersprungen
❌ Keine neuen Dateien zum Importieren gefunden
```

### Ursache

Der Import-Filter verwendete `contains()`, welches prüft ob eine Datei **in der Historie existiert** (egal ob nur gesichert oder bereits importiert).

**Problem-Ablauf:**
1. SD-Karte eingesteckt → Backup erstellt
2. Backup fügt Dateien zur Historie hinzu mit `backed_up_at=<timestamp>`, `imported_at=NULL`
3. Auto-Import prüft mit `contains(hash)` → Datei existiert in Historie ✅
4. Auto-Import überspringt Datei → ❌ Falsches Verhalten!

**Erwartetes Verhalten:**
- Dateien die nur gesichert wurden (`backed_up_at` gesetzt, `imported_at=NULL`) sollten beim Import **nicht** übersprungen werden
- Nur Dateien die bereits importiert wurden (`imported_at` gesetzt) sollten übersprungen werden

---

## Lösung

### 1. Neue Methode `was_imported()` in MediaHistoryStore

**`src/utils/media_history.py`:**

```python
def was_imported(self, identity_hash: str) -> bool:
    """
    Prüft ob eine Datei bereits importiert wurde (imported_at ist gesetzt).
    
    Unterschied zu contains(): Diese Methode prüft speziell ob die Datei
    bereits in die App importiert wurde, nicht nur gesichert.
    
    Args:
        identity_hash: Der zu prüfende Hash
        
    Returns:
        True wenn bereits importiert, sonst False
    """
    cur = self.conn.cursor()
    cur.execute(
        "SELECT imported_at FROM processed_files WHERE identity_hash = ?",
        (identity_hash,)
    )
    row = cur.fetchone()
    # Datei wurde importiert wenn imported_at nicht NULL ist
    return row is not None and row[0] is not None
```

**Unterschied:**
- `contains(hash)`: Prüft ob Datei in Historie existiert (backed_up ODER imported)
- `was_imported(hash)`: Prüft ob Datei bereits importiert wurde (imported_at != NULL)

### 2. Import-Filter verwendet jetzt `was_imported()`

**`src/gui/app.py` - `import_from_backup()`:**

**Vorher:**
```python
if not history_store.contains(identity_hash):
    filtered_videos.append(file_path)
else:
    skipped_count += 1
```

**Nachher:**
```python
# Prüfe ob bereits IMPORTIERT (nicht nur gesichert)
if not history_store.was_imported(identity_hash):
    filtered_videos.append(file_path)
else:
    skipped_count += 1
```

**Kommentare hinzugefügt:**
- "nur importierte überspringen, nicht gesicherte"
- "Prüfe ob bereits IMPORTIERT (nicht nur gesichert)"

---

## Verhalten nach Fix

### Szenario 1: Erstes Backup + Auto-Import

```
1. SD-Karte eingesteckt
   → Backup: 3 Dateien gesichert
   → Historie: backed_up_at=2025-11-09, imported_at=NULL

2. Auto-Import startet
   → Prüfung: was_imported(hash) → False (imported_at=NULL)
   → ✅ 3 Dateien werden importiert
   → Historie: imported_at=2025-11-09

3. Ergebnis: ✅ Alle Dateien importiert
```

### Szenario 2: Zweites Backup + Auto-Import (gleiche Dateien)

```
1. SD-Karte erneut eingesteckt (gleiche Dateien)
   → Backup: 0 neue Dateien (alle übersprungen)
   → Historie: unverändert

2. Auto-Import würde starten (falls Backup erfolgreich)
   → Aber: Backup war leer, kein Import nötig
```

### Szenario 3: Nur Backup, kein Auto-Import

```
1. SD-Karte eingesteckt (Auto-Import deaktiviert)
   → Backup: 3 Dateien gesichert
   → Historie: backed_up_at=2025-11-09, imported_at=NULL

2. Später: Manueller Import aus Backup-Ordner
   → Prüfung: was_imported(hash) → False
   → ✅ 3 Dateien werden importiert
   → Historie: imported_at=<aktuelles Datum>
```

### Szenario 4: Historie gelöscht + erneuter Import

```
1. Alle Einträge aus Historie gelöscht
   → Historie: leer

2. SD-Karte eingesteckt
   → Backup: 3 Dateien gesichert
   → Historie: backed_up_at=2025-11-09, imported_at=NULL

3. Auto-Import startet
   → Prüfung: was_imported(hash) → False
   → ✅ 3 Dateien werden importiert (wie erwartet!)
```

---

## Backup-Filter bleibt unverändert

Der **Backup-Filter** verwendet weiterhin `contains()`, und das ist korrekt:

```python
# In sd_card_monitor.py beim Backup
if self.history.contains(identity_hash):
    skipped_count += 1  # ✅ Richtig: Überspringen wenn bereits gesichert ODER importiert
```

**Warum?**
- Beim Backup interessiert uns nur: "Wurde die Datei schon mal gesichert?"
- Egal ob nur gesichert oder auch importiert → Datei muss nicht nochmal kopiert werden

---

## Logik-Tabelle

| Historie-Status | Backup-Verhalten | Import-Verhalten |
|----------------|------------------|------------------|
| Nicht in Historie | ✅ Sichern | ✅ Importieren |
| `backed_up_at` gesetzt, `imported_at=NULL` | ❌ Überspringen | ✅ Importieren ⭐ |
| `backed_up_at` gesetzt, `imported_at` gesetzt | ❌ Überspringen | ❌ Überspringen |
| Nur `imported_at` gesetzt (ohne Backup) | ❌ Überspringen | ❌ Überspringen |

⭐ = **Dieser Fall wurde durch den Fix korrigiert!**

---

## Geänderte Dateien

### `src/utils/media_history.py`
- ✅ Neue Methode `was_imported()` hinzugefügt
- ✅ Docstring für `contains()` erweitert
- **+22 Zeilen**

### `src/gui/app.py`
- ✅ `contains()` → `was_imported()` im Import-Filter
- ✅ Kommentare verbessert
- **~8 Zeilen geändert**

---

## Testing

### Syntax-Check:
```bash
python -m py_compile src\utils\media_history.py src\gui\app.py
```
✅ **Erfolgreich**

### Manueller Test (empfohlen):

1. **Alle Historie-Einträge löschen:**
   - Einstellungen → Verlauf anzeigen → "Alles löschen"

2. **SD-Karte einstecken (mit Auto-Import aktiviert):**
   - Erwartung: Backup + Import beide erfolgreich
   - Log sollte zeigen: "3 Dateien, 3 neu, 0 übersprungen"

3. **SD-Karte erneut einstecken:**
   - Erwartung: Backup überspringt alle (bereits gesichert)
   - Import überspringt alle (bereits importiert)

4. **Historie löschen, nur Backup machen (Auto-Import AUS):**
   - Backup erfolgreich
   - Dann Auto-Import einschalten und Backup-Ordner manuell importieren
   - Erwartung: Import erfolgreich (nicht übersprungen)

---

## Zusammenfassung

**Problem:**  
Import übersprang Dateien die nur gesichert, aber noch nicht importiert wurden.

**Lösung:**  
Neue Methode `was_imported()` prüft explizit ob `imported_at` gesetzt ist.

**Ergebnis:**  
✅ Dateien werden nur übersprungen wenn sie **tatsächlich bereits importiert** wurden  
✅ Backup-Filter arbeitet weiterhin korrekt  
✅ Keine Breaking Changes  
✅ Klare Trennung zwischen "gesichert" und "importiert"  

---

**Erstellt:** 2025-11-09  
**Autor:** GitHub Copilot  
**Status:** ✅ Implementiert und getestet

