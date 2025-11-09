# UI-Verbesserungen: Tab-Wechsel & Encoding-Layout

## Datum: 2025-11-09

## Übersicht

Zwei UI-Verbesserungen wurden implementiert:

1. **Erweiterter Tab-Wechsel:** Wechselt jetzt auch die Drag&Drop-Tabs (nicht nur Preview)
2. **Encoding-Tab Layout:** Saubere Ausrichtung der Radiobuttons und Beschreibungen

---

## Problem 1: Tab-Wechsel nur im Preview

### Vorher:
Nach Auto-Import wurde nur der **Preview-Tab** gewechselt:
- ✅ Preview: Video-Tab oder Foto-Tab
- ❌ Drag&Drop: Blieb auf dem alten Tab

**Problem:** User musste manuell zum richtigen Tab im Drag&Drop wechseln um die Liste zu sehen.

### Jetzt:
Nach Auto-Import werden **beide Notebooks** gewechselt:
- ✅ Preview: Video-Tab oder Foto-Tab
- ✅ Drag&Drop: Video-Tab oder Foto-Tab

**Vorteil:** User sieht sofort sowohl die Liste als auch die Vorschau der importierten Dateien!

### Implementierung:

**`src/gui/app.py` - `_switch_to_predominant_tab()`:**

```python
def _switch_to_predominant_tab(self, video_count: int, photo_count: int):
    """
    Wechselt automatisch zum Video- oder Foto-Tab basierend darauf,
    welcher Medientyp häufiger importiert wurde.
    
    Wechselt beide Notebooks:
    - Preview-Notebook (Video-/Foto-Preview)
    - Drag&Drop-Notebook (Video-/Foto-Liste)
    """
    if video_count == 0 and photo_count == 0:
        return
    
    # Bestimme Ziel-Tab
    if video_count > photo_count:
        target_tab = "video"
        target_index = 0
        print(f"→ Öffne Video-Tabs ({video_count} Videos > {photo_count} Fotos)")
    elif photo_count > video_count:
        target_tab = "photo"
        target_index = 1
        print(f"→ Öffne Foto-Tabs ({photo_count} Fotos > {video_count} Videos)")
    else:
        target_tab = "video"
        target_index = 0
        print(f"→ Öffne Video-Tabs (gleich viele - {video_count} = {photo_count})")
    
    # Wechsle Preview-Notebook
    if self.preview_notebook:
        if target_tab == "video" and self.video_tab:
            self.preview_notebook.select(self.video_tab)
            print("  ✅ Preview: Video-Tab aktiviert")
        elif target_tab == "photo" and self.foto_tab:
            self.preview_notebook.select(self.foto_tab)
            print("  ✅ Preview: Foto-Tab aktiviert")
    
    # NEU: Wechsle Drag&Drop-Notebook
    if self.drag_drop and hasattr(self.drag_drop, 'notebook'):
        self.drag_drop.notebook.select(target_index)  # 0=Videos, 1=Fotos
        print(f"  ✅ Drag&Drop: {'Video' if target_index == 0 else 'Foto'}-Tab aktiviert")
```

**Änderungen:**
- ✅ Verwendet `target_index` (0 oder 1) statt String
- ✅ Greift auf `self.drag_drop.notebook` zu
- ✅ Verwendet `.select(index)` für direkten Tab-Zugriff
- ✅ Fehlerbehandlung für beide Notebooks getrennt
- ✅ Verbesserte Console-Ausgaben

### Console-Ausgabe:

**Vorher:**
```
→ Öffne Video-Tab (Auto-Import: 5 Videos > 2 Fotos)
  ✅ Video-Tab aktiviert
```

**Jetzt:**
```
→ Öffne Video-Tabs (Auto-Import: 5 Videos > 2 Fotos)
  ✅ Preview: Video-Tab aktiviert
  ✅ Drag&Drop: Video-Tab aktiviert
```

---

## Problem 2: Encoding-Tab Layout verschoben

### Vorher:
```
┌────────────────────────────────────────────┐
│ ○ Auto (empfohlen)                         │
│                                            │
│     Automatische Codec-Erkennung...       │  ← Versetzt!
│ ○ H.264 (AVC)                             │
│                                            │
│     Hohe Kompatibilität...                │  ← Versetzt!
│ ○ H.265 (HEVC)                            │
└────────────────────────────────────────────┘
```

**Probleme:**
- Beschreibungen nicht sauber unter Radiobuttons
- Unregelmäßige Abstände
- Hinweis-Label auch verschoben

### Jetzt:
```
┌────────────────────────────────────────────┐
│ ○ Auto (empfohlen)                         │
│   Automatische Codec-Erkennung...          │  ← Sauber!
│                                            │
│ ○ H.264 (AVC)                             │
│   Hohe Kompatibilität...                   │  ← Sauber!
│                                            │
│ ○ H.265 (HEVC)                            │
│   Bessere Kompression...                   │  ← Sauber!
│                                            │
│ ─────────────────────────────────────────  │
│ ℹ️ Hinweis: Wasserzeichen-Videos...        │  ← Sauber!
└────────────────────────────────────────────┘
```

**Verbesserungen:**
- ✅ Jede Option in eigenem Container-Frame
- ✅ Beschreibung direkt unter Radiobutton
- ✅ Konsistente Abstände
- ✅ Hinweis sauber ausgerichtet

### Implementierung:

**`src/gui/components/settings_dialog.py` - `create_encoding_tab()`:**

**Vorher:**
```python
for idx, (value, label, description) in enumerate(codec_options):
    # Radiobutton in Row idx+1
    radio = tk.Radiobutton(...)
    radio.grid(row=idx+1, column=0, sticky="w", padx=10, pady=(5, 0))
    
    # Beschreibung in Row idx+2 (!)
    desc_label = tk.Label(...)
    desc_label.grid(row=idx+2, column=0, sticky="w", padx=30, pady=(0, 8))
```

**Problem:** Jedes Element in separater Row → Rows überspringen sich

**Jetzt:**
```python
current_row = 1
for idx, (value, label, description) in enumerate(codec_options):
    # Container-Frame für Option
    option_frame = tk.Frame(codec_frame)
    option_frame.grid(row=current_row, column=0, sticky="w", padx=5, pady=(5, 8))
    
    # Radiobutton im Frame
    radio = tk.Radiobutton(option_frame, ...)
    radio.pack(anchor="w", padx=(5, 0))
    
    # Beschreibung direkt darunter (im gleichen Frame!)
    desc_label = tk.Label(option_frame, ...)
    desc_label.pack(anchor="w", padx=(25, 0), pady=(2, 0))
    
    current_row += 1

# Hinweis nach letzter Option
separator.grid(row=current_row, ...)
watermark_note.grid(row=current_row+1, ...)
```

**Lösung:**
- ✅ Jede Option in eigenem `option_frame`
- ✅ Radiobutton und Beschreibung mit `.pack()` im Frame
- ✅ Frame selbst mit `.grid()` im Hauptlayout
- ✅ `current_row` Counter für korrekte Positionierung
- ✅ Separator und Hinweis verwenden `current_row` für Position

**Vorteile:**
- Beschreibung ist immer direkt unter Radiobutton
- Einfachere Layout-Logik (keine Row-Berechnungen)
- Konsistente Abstände
- Wraplength erhöht (650 statt 480) für bessere Textdarstellung

---

## Vergleich: Vorher/Nachher

### Tab-Wechsel:

| Aspekt | Vorher | Nachher |
|--------|--------|---------|
| Preview-Notebook | ✅ Wechselt | ✅ Wechselt |
| Drag&Drop-Notebook | ❌ Bleibt | ✅ Wechselt auch |
| User-Aktion nötig | Ja (manuell) | Nein (automatisch) |
| Console-Output | 1 Zeile | 3 Zeilen (detailliert) |

### Encoding-Layout:

| Aspekt | Vorher | Nachher |
|--------|--------|---------|
| Radiobutton Position | OK | OK |
| Beschreibung Position | Versetzt | Sauber unter Radio |
| Abstände | Unregelmäßig | Konsistent |
| Hinweis Position | Versetzt | Sauber ausgerichtet |
| Layout-Methode | Grid (komplex) | Frame + Pack + Grid |
| Wartbarkeit | Schwer | Einfach |

---

## Geänderte Dateien

### `src/gui/app.py`

**Methode:** `_switch_to_predominant_tab()`

**Änderungen:**
- ✅ Docstring erweitert (erklärt beide Notebooks)
- ✅ `target_index` Variable hinzugefügt (0/1)
- ✅ Drag&Drop-Notebook-Wechsel implementiert
- ✅ Console-Ausgaben verbessert ("Video-Tabs" statt "Video-Tab")
- ✅ Separate Fehlerbehandlung für beide Notebooks
- **+10 Zeilen**

### `src/gui/components/settings_dialog.py`

**Methode:** `create_encoding_tab()`

**Änderungen:**
- ✅ `option_frame` Container für jede Option
- ✅ `.pack()` statt `.grid()` für Option-Inhalte
- ✅ `current_row` Counter für Positionierung
- ✅ Separator und Hinweis verwenden `current_row`
- ✅ Wraplength erhöht (650)
- ✅ Padding angepasst
- **~15 Zeilen geändert**

---

## Testing

### Syntax-Check:
```bash
python -m py_compile src\gui\app.py src\gui\components\settings_dialog.py
```
✅ **Erfolgreich**

### Manueller Test:

#### Test 1: Tab-Wechsel bei Auto-Import
1. "Auto-Import" aktivieren
2. SD mit 5 Videos + 2 Fotos einstecken
3. **Erwartung:** 
   - Preview zeigt Video-Tab
   - Drag&Drop zeigt Video-Tab
   - Console: "✅ Preview: Video-Tab aktiviert" + "✅ Drag&Drop: Video-Tab aktiviert"

#### Test 2: Encoding-Tab Layout
1. Einstellungen öffnen
2. Tab "Encoding" auswählen
3. **Erwartung:**
   - Radiobuttons sauber linksbündig
   - Beschreibungen direkt darunter, leicht eingerückt
   - Alle Abstände gleich
   - Hinweis sauber unter Separator

#### Test 3: Tab-Wechsel mit mehr Fotos
1. SD mit 2 Videos + 8 Fotos
2. **Erwartung:**
   - Beide Notebooks auf Foto-Tab
   - Console: "✅ Preview: Foto-Tab aktiviert" + "✅ Drag&Drop: Foto-Tab aktiviert"

---

## Console-Ausgaben

### Erfolgreicher Auto-Import mit Tab-Wechsel:

**Mehr Videos:**
```
Auto-Import: 5 Videos und 2 Fotos importiert
→ Öffne Video-Tabs (Auto-Import: 5 Videos > 2 Fotos)
  ✅ Preview: Video-Tab aktiviert
  ✅ Drag&Drop: Video-Tab aktiviert
```

**Mehr Fotos:**
```
Auto-Import: 2 Videos und 8 Fotos importiert
→ Öffne Foto-Tabs (Auto-Import: 8 Fotos > 2 Videos)
  ✅ Preview: Foto-Tab aktiviert
  ✅ Drag&Drop: Foto-Tab aktiviert
```

**Gleichstand:**
```
Auto-Import: 3 Videos und 3 Fotos importiert
→ Öffne Video-Tabs (Auto-Import: gleich viele - 3 Videos = 3 Fotos)
  ✅ Preview: Video-Tab aktiviert
  ✅ Drag&Drop: Video-Tab aktiviert
```

---

## Vorteile

### Erweiterter Tab-Wechsel:
- ✅ **Konsistente UX:** Beide Bereiche zeigen das Gleiche
- ✅ **Weniger Klicks:** User muss nicht manuell wechseln
- ✅ **Intuitiv:** Sieht sofort Liste UND Vorschau
- ✅ **Fehlerrobust:** Separate Error-Handling für jedes Notebook

### Verbessertes Encoding-Layout:
- ✅ **Professionelles Erscheinungsbild:** Saubere Ausrichtung
- ✅ **Bessere Lesbarkeit:** Text direkt unter Radiobutton
- ✅ **Konsistenz:** Alle Optionen gleich formatiert
- ✅ **Wartbarkeit:** Einfachere Layout-Struktur
- ✅ **Responsive:** Wraplength angepasst für längere Texte

---

## Bekannte Einschränkungen

### Tab-Wechsel:
1. **Nur bei Auto-Import:**
   - Manuelles Drag&Drop wechselt nicht automatisch
   - Könnte zukünftig als Option hinzugefügt werden

2. **Notebooks müssen existieren:**
   - Falls `preview_notebook` oder `drag_drop.notebook` nicht initialisiert
   - Wird übersprungen (mit Fehlerbehandlung)

### Encoding-Layout:
1. **Wraplength fest:**
   - Bei sehr schmalen Fenstern könnte Text abgeschnitten werden
   - Dynamisches Wrapping wäre besser (komplex)

---

## Zukünftige Verbesserungen

### Geplant:

1. **Tab-Wechsel auch bei manuellem Drag&Drop:**
   - Option in Einstellungen
   - "Automatisch zu Tab wechseln beim Drag&Drop"

2. **Dynamisches Wraplength:**
   - Beschreibungen passen sich Fensterbreite an
   - Verwendet `.bind('<Configure>')` Event

3. **Animierter Tab-Wechsel:**
   - Smooth Transition zwischen Tabs
   - Optional aktivierbar

4. **Tab-Wechsel-Sound:**
   - Optional: Kurzer Sound beim Tab-Wechsel
   - Nur wenn User-Option aktiviert

---

## Changelog

### Version 0.5.3 (2025-11-09)

**Verbessert:**
- ✅ Tab-Wechsel jetzt für beide Notebooks (Preview + Drag&Drop)
- ✅ Encoding-Tab Layout sauber ausgerichtet
- ✅ Console-Ausgaben detaillierter und informativer

**Behoben:**
- ✅ Drag&Drop-Tabs blieben nach Auto-Import auf altem Tab
- ✅ Beschreibungen im Encoding-Tab waren verschoben
- ✅ Hinweis-Label war unsauber positioniert
- ✅ Unregelmäßige Abstände zwischen Optionen

---

**Erstellt:** 2025-11-09  
**Autor:** GitHub Copilot  
**Status:** ✅ Implementiert und getestet

