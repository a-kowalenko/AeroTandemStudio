# Test-Anleitung: Startup Optimierung

## Voraussetzungen
- Python 3.x mit allen Dependencies installiert
- Optional: GPU (NVIDIA/AMD/Intel) für Hardware-Beschleunigung

## Schnelltest

### 1. Kalter Start (ohne Cache)
```bash
# Cache löschen für echten Kaltstarttest
del %LOCALAPPDATA%\AeroTandemStudio\hw_cache.json

# App starten
python run.py
```

**Erwartetes Verhalten:**
- ✅ Splash erscheint sofort
- ✅ Spinner dreht sich flüssig (keine sichtbaren Freezes)
- ✅ Status-Updates durchlaufen:
  1. "Wird geladen..."
  2. "Erstelle Fenster..."
  3. "Erstelle Layout..."
  4. "Lade Formulare..."
  5. "Initialisiere Video Player..."
  6. "Initialisiere Foto Vorschau..."
  7. "Prüfe FFmpeg Installation..." (falls nicht installiert)
  8. "Finalisiere..."
  9. "Bereit!"
- ✅ Hauptfenster erscheint nach 1.5-2 Sekunden
- ✅ Konsole zeigt: "🔄 Starte Hardware-Erkennung asynchron..."
- ✅ Nach kurzer Zeit: "✓ VideoPreview: Hardware-Beschleunigung aktiviert: [GPU-Typ]"
- ✅ Ca. 800ms nach Hauptfenster: "✅ SD-Karten Monitor gestartet"

---

### 2. Warmer Start (mit Cache)
```bash
# Erneut starten (Cache existiert jetzt)
python run.py
```

**Erwartetes Verhalten:**
- ✅ Noch schneller als Kaltstartstart (0.8-1.2 Sekunden)
- ✅ Konsole zeigt: "✓ Hardware aus Cache geladen: [GPU-Typ]"
- ✅ Kein "Erkenne Hardware"-Schritt sichtbar

---

## Detaillierter Test

### Test 1: Splash Flüssigkeit
**Ziel:** Verifizieren dass Splash durchgehend animiert bleibt

**Ablauf:**
1. Starte App mit `python run.py`
2. Beobachte Spinner im Splash
3. Achte auf Stalls/Freezes

**Pass-Kriterien:**
- [ ] Spinner dreht sich kontinuierlich (60 FPS)
- [ ] Keine sichtbaren Pausen > 100ms
- [ ] Status-Text aktualisiert sich flüssig

---

### Test 2: Status-Updates
**Ziel:** Verifizieren dass granulare Status-Updates funktionieren

**Pass-Kriterien:**
- [ ] Mind. 6 verschiedene Status-Texte sichtbar
- [ ] Jeder Status zeigt spezifischen Schritt
- [ ] Reihenfolge korrekt

---

### Test 3: Hardware-Erkennung Asynchron
**Ziel:** Verifizieren dass Hardware-Erkennung UI nicht blockiert

**Ablauf:**
1. Cache löschen
2. Starte App
3. Beobachte Konsole

**Pass-Kriterien:**
- [ ] Konsole zeigt: "🔄 Starte Hardware-Erkennung asynchron..."
- [ ] Hauptfenster erscheint VOR Hardware-Erkennung abgeschlossen
- [ ] Später: "✓ VideoPreview: Hardware-Beschleunigung aktiviert"

---

### Test 4: Cache-Funktionalität
**Ziel:** Verifizieren dass Cache korrekt funktioniert

**Ablauf:**
1. Kaltstartstart (Cache löschen)
2. Warte auf "Hardware aus Cache geladen"
3. Prüfe Cache-Datei existiert
4. Zweiter Start

**Pass-Kriterien:**
- [ ] Cache-Datei existiert: `%LOCALAPPDATA%\AeroTandemStudio\hw_cache.json`
- [ ] Zweiter Start schneller
- [ ] Konsole zeigt Cache-Hit Meldung

---

### Test 5: Fallback ohne GPU
**Ziel:** Verifizieren Software-Encoding Fallback

**Ablauf:**
1. Auf System ohne dedizierte GPU testen
2. Oder: FFmpeg ohne Hardware-Encoder

**Pass-Kriterien:**
- [ ] App startet trotzdem
- [ ] Konsole: "ℹ VideoPreview: Keine Hardware-Beschleunigung verfügbar..."
- [ ] Kein Fehler/Crash

---

### Test 6: SD-Monitor Verzögerung
**Ziel:** Verifizieren dass SD-Monitor nach UI-Start kommt

**Ablauf:**
1. Starte App
2. Beobachte Konsole Timestamps

**Pass-Kriterien:**
- [ ] "✅ App-Initialisierung abgeschlossen" erscheint zuerst
- [ ] Ca. 800ms später: "✅ SD-Karten Monitor gestartet"
- [ ] SD-Monitor blockiert Startup nicht

---

## Performance-Metriken (Richtwerte)

### Erwartete Zeiten (ohne FFmpeg-Installation):
| Schritt | Kalt (ohne Cache) | Warm (mit Cache) |
|---------|-------------------|------------------|
| Bis Splash | < 200ms | < 200ms |
| GUI Setup | 100-300ms | 100-300ms |
| Hardware-Erkennung | 500-2000ms (async) | < 50ms |
| Bis Hauptfenster | 1500-2000ms | 800-1200ms |
| SD-Monitor Start | +800ms | +800ms |

### Akzeptable Limits:
- ❌ Splash-Freeze > 50ms → Problem
- ⚠️ Hauptfenster > 3s (Kaltstartstart) → Optimierbar
- ✅ Hauptfenster < 2s (Kaltstartstart) → Gut
- ✅ Hauptfenster < 1.5s (Warm) → Sehr gut

---

## Troubleshooting

### Problem: Splash friert weiterhin ein
**Mögliche Ursachen:**
- Threading funktioniert nicht korrekt
- Andere blockierende Operation nicht identifiziert

**Debug:**
```python
# Füge in app.py vor jedem Step hinzu:
import time
start = time.time()
# ... Step Code ...
print(f"Step X dauerte: {time.time() - start:.3f}s")
```

---

### Problem: Hardware-Erkennung findet nichts
**Mögliche Ursachen:**
- FFmpeg nicht installiert/gefunden
- GPU-Treiber veraltet
- Encoder nicht in FFmpeg kompiliert

**Debug:**
```bash
ffmpeg -hide_banner -encoders | findstr "nvenc amf qsv"
```

---

### Problem: Cache wird nicht verwendet
**Prüfen:**
1. Datei existiert: `%LOCALAPPDATA%\AeroTandemStudio\hw_cache.json`
2. Alter < 7 Tage
3. JSON valide

**Cache manuell löschen:**
```bash
del %LOCALAPPDATA%\AeroTandemStudio\hw_cache.json
```

---

## Erfolgskriterien (Gesamt)

✅ **Alle Tests bestanden:**
- [ ] Splash flüssig (Test 1)
- [ ] Status-Updates sichtbar (Test 2)
- [ ] Hardware asynchron (Test 3)
- [ ] Cache funktioniert (Test 4)
- [ ] Fallback ok (Test 5)
- [ ] SD-Monitor verzögert (Test 6)

✅ **Performance akzeptabel:**
- [ ] Kaltstartstart < 2s
- [ ] Warm Start < 1.5s
- [ ] Keine Freezes > 50ms

✅ **Keine Fehler/Crashes:**
- [ ] Konsole zeigt keine Tracebacks
- [ ] App läuft stabil

---

## Rückmeldung

Bitte bei Tests folgende Infos sammeln:
- Windows Version
- Python Version
- GPU vorhanden (Ja/Nein/Typ)
- Gemessene Zeiten
- Beobachtete Probleme
- Konsolen-Output (relevante Teile)

