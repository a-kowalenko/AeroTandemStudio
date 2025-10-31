# 🎬 Aero Tandem Studio

![Version](https://img.shields.io/badge/version-0.1.0.7-blue.svg)
![Python](https://img.shields.io/badge/python-3.10+-green.svg)
![License](https://img.shields.io/badge/license-proprietary-red.svg)

**Aero Tandem Studio** ist eine professionelle Desktop-Anwendung zur automatisierten Erstellung von Tandem-Fallschirmsprung-Videos mit Intro, Kundendaten und optionaler QR-Code-Analyse.

---

## 📋 Inhaltsverzeichnis

- [Features](#-features)
- [Systemanforderungen](#-systemanforderungen)
- [Installation](#-installation)
- [Verwendung](#-verwendung)
- [Projektstruktur](#-projektstruktur)
- [Entwicklung](#-entwicklung)
- [Build & Deployment](#-build--deployment)
- [Konfiguration](#-konfiguration)
- [Troubleshooting](#-troubleshooting)
- [Lizenz](#-lizenz)

---

## ✨ Features

### Kernfunktionen
- **📹 Video-Verarbeitung**
  - Drag & Drop für mehrere Videos
  - Automatische Format-Erkennung und Re-Encoding (1080p@30fps)
  - Video-Schneiden und Teilen mit integriertem Editor
  - Live-Vorschau kombinierter Videos
  - QR-Code-Analyse für automatische Kundenerkennung

- **📝 Kundenverwaltung**
  - Formularbasierte Dateneingabe (Name, Email, Telefon, gebuchte Medienoptionen, etc.)
  - Automatisches Ausfüllen via QR-Code-Scanner direkt aus der Action-Cam-Aufnahme
  - Konfigurierbare Standardwerte

- **🎨 Video-Produktion**
  - Automatische Intro-Erstellung mit Kunden- und Springer-Daten
  - Hintergrund-Branding (konfigurierbar)
  - Optionale Outside-Video-Integration
  - Verschiedene Auflösungen (720p, 1080p, 4K)

- **☁️ Server-Integration**
  - Upload zu SMB/Netzwerk-Shares
  - Server-Status-Überwachung
  - Automatische Fehlerbehandlung

- **💾 SD-Karten Auto-Backup** ✨ NEU
  - Automatische Erkennung von Action-Cam SD-Karten
  - Automatisches Backup beim Einstecken
  - Optionales Leeren der SD-Karte nach Backup
  - Automatischer Import in die Anwendung
  - Zeitstempel-basierte Backup-Ordner

- **🔄 Auto-Update**
  - Automatische Update-Prüfung beim Start
  - Download und Installation neuer Versionen
  - Versionsverwaltung

### Technische Features
- Multi-Threading für flüssige UI
- Fortschrittsanzeige mit Abbrechen-Funktion
- Metadaten-Caching für Performance
- Arbeitsverzeichnis-Management
- Umfangreiche Fehlerbehandlung und Logging

---

## 💻 Systemanforderungen

### Minimum
- **Betriebssystem:** Windows 10 oder höher
- **Prozessor:** Dual-Core CPU (2 GHz+)
- **RAM:** 4 GB
- **Festplatte:** 2 GB freier Speicher
- **Grafik:** DirectX 11 kompatibel

### Empfohlen
- **Betriebssystem:** Windows 11
- **Prozessor:** Quad-Core CPU (3 GHz+)
- **RAM:** 8 GB oder mehr
- **Festplatte:** SSD mit 5 GB+ freiem Speicher
- **Grafik:** Dedizierte GPU für Video-Encoding

---

## 🚀 Installation

### Für Endbenutzer (Windows Installer)

1. **Download** der neuesten Version:
   ```
   setup_builds_releases/AeroTandemStudio_Installer_v0.1.0.7.exe
   ```

2. **Installation** ausführen und Anweisungen folgen

3. **Starten** über Desktop-Verknüpfung oder Startmenü

Die Anwendung installiert automatisch erforderliche Abhängigkeiten:
- FFmpeg (Video-Encoding)
- VLC Media Player (Video-Wiedergabe)

### Für Entwickler (Source Code)

1. **Repository klonen:**
   ```bash
   git clone <repository-url>
   cd TandemIntro
   ```

2. **Python-Umgebung erstellen:**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   ```

3. **Abhängigkeiten installieren:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Anwendung starten:**
   ```bash
   python run.py
   ```

---

## 📖 Verwendung

### Schnellstart

1. **Videos hinzufügen**
   - Videos per Drag & Drop in die Anwendung ziehen
   - Vorschau wird automatisch generiert

2. **Kundendaten eingeben**
   - Formular ausfüllen ODER
   - QR-Code scannen für automatisches Ausfüllen

3. **Einstellungen prüfen**
   - Speicherort festlegen
   - Optional: Server-Upload aktivieren
   - Video-Qualität wählen

4. **Video erstellen**
   - "Video erstellen" klicken
   - Fortschritt überwachen
   - Fertig!

### Video-Bearbeitung

**Videos schneiden:**
1. Video in der Liste auswählen
2. "✂ Schneiden" klicken
3. Start- und Endpunkt markieren
4. Übernehmen

**Videos teilen:**
1. Video auswählen
2. "✂ Schneiden" klicken
3. Split-Position markieren
4. "Teilen" klicken

### QR-Code-Funktion

Die Anwendung kann QR-Codes aus Videos analysieren:
- Automatische Erkennung in den ersten 5 Sekunden
- Unterstützte Formate: QR-Codes mit Kundendaten
- JSON-Format für strukturierte Daten

### SD-Karten Auto-Backup ✨ NEU

Die Anwendung überwacht automatisch SD-Karten und erstellt Backups:

**Einrichtung:**
1. Einstellungen öffnen (⚙️ Button)
2. Tab "Allgemein" auswählen
3. Backup-Ordner festlegen
4. Gewünschte Optionen aktivieren:
   - ☑ **Automatischer Backup von SD-Karte**: Aktiviert die Überwachung
   - ☑ **SD-Karte nach Backup leeren**: Löscht DCIM-Ordner nach erfolgreichem Backup
   - ☑ **Automatisch importieren**: Importiert Dateien direkt in die App
5. Speichern

**Verwendung:**
1. SD-Karte einstecken (mit DCIM-Ordner)
2. Backup wird automatisch erstellt
3. Bei aktiviertem Auto-Import werden Videos und Fotos direkt geladen
4. Fertig! ☕

**Sicherheit:**
- SD-Karte wird nur nach ERFOLGREICHEM Backup geleert
- Backup-Ordner haben Zeitstempel (z.B. `SD_Backup_20231031_143025`)
- Fehlerbehandlung mit aussagekräftigen Meldungen

---

## 📁 Projektstruktur

```
TandemIntro/
├── src/                          # Quellcode
│   ├── gui/                      # GUI-Komponenten
│   │   ├── app.py               # Haupt-App
│   │   └── components/          # UI-Komponenten
│   │       ├── drag_drop.py     # Drag & Drop
│   │       ├── video_preview.py # Video-Vorschau
│   │       ├── video_player.py  # Video-Player
│   │       ├── video_cutter.py  # Video-Editor
│   │       ├── form_fields.py   # Formular
│   │       └── ...
│   ├── video/                   # Video-Verarbeitung
│   │   ├── processor.py         # Haupt-Prozessor
│   │   ├── qr_analyser.py      # QR-Code-Analyse
│   │   └── logger.py           # Progress-Logging
│   ├── model/                   # Datenmodelle
│   │   └── kunde.py            # Kunden-Datenklasse
│   ├── utils/                   # Hilfsfunktionen
│   │   ├── config.py           # Konfigurations-Manager
│   │   ├── file_utils.py       # Datei-Operationen
│   │   ├── sd_card_monitor.py  # SD-Karten Überwachung ✨ NEU
│   │   ├── validation.py       # Validierung
│   │   └── constants.py        # Konstanten
│   └── installer/               # Installation & Updates
│       ├── ffmpeg_installer.py # FFmpeg-Setup
│       └── updater.py          # Auto-Update
├── assets/                      # Ressourcen
│   ├── icon.ico                # App-Icon
│   ├── logo.png                # Logo
│   └── hintergrund.png         # Video-Hintergrund
├── config/                      # Konfiguration
│   └── config.json             # Einstellungen
├── build/                       # Build-Artefakte
├── run.py                       # Einstiegspunkt
├── build.py                     # Build-Skript
├── requirements.txt             # Python-Pakete
└── README.md                    # Diese Datei
```

---

## 🛠️ Entwicklung

### Technologie-Stack

- **GUI:** Tkinter / TkinterDnD2
- **Video-Processing:** MoviePy, FFmpeg, OpenCV
- **Media Player:** python-vlc
- **QR-Codes:** pyzbar
- **Deployment:** PyInstaller, NSIS

### Wichtige Module

#### VideoProcessor (`src/video/processor.py`)
Hauptklasse für Video-Erstellung:
- Intro-Generierung
- Video-Kombination
- Format-Konvertierung
- Fortschritts-Callbacks

#### DragDropFrame (`src/gui/components/drag_drop.py`)
Verwaltet Video-Eingabe:
- Drag & Drop Funktionalität
- Video-Liste
- Re-Encoding-Koordination

#### VideoPreview (`src/gui/components/video_preview.py`)
Erstellt kombinierte Vorschau:
- Temporäres Arbeitsverzeichnis
- Format-Prüfung
- Metadaten-Caching

### Entwickler-Befehle

**Tests ausführen:**
```bash
# Aktuell keine Tests implementiert
```

**Code-Formatierung:**
```bash
# Empfohlen: black, flake8
pip install black flake8
black src/
flake8 src/
```

**Abhängigkeiten aktualisieren:**
```bash
pip freeze > requirements.txt
```

---

## 🏗️ Build & Deployment

### Lokaler Build

**Nur PyInstaller Build (Build-Nummer erhöhen):**
```bash
python build.py
```

**Mit Installer (NSIS):**
```bash
python build.py setup
```

### Versionsverwaltung

**Minor-Version erhöhen:**
```bash
python build.py minor setup
```

**Patch-Version erhöhen:**
```bash
python build.py patch setup
```

**Major-Version erhöhen:**
```bash
python build.py major setup
```

### Build-Prozess

1. **build.py** erhöht **Version** in `VERSION.txt` und ruft **PyInstaller** und **NSIS** auf
2. **PyInstaller** erstellt `.exe`:
   - Bundled mit allen Abhängigkeiten
   - Icon und Versionsinformationen
   - Ausgabe: `build/Aero Tandem Studio/`
3. **NSIS** erstellt Installer:
   - Dependency-Installation (FFmpeg, VLC)
   - Start-Menü Verknüpfungen
   - Deinstallations-Unterstützung
   - Ausgabe: `AeroTandemStudio_Installer_vX.Y.Z.exe`

### Deployment-Anforderungen

- **PyInstaller** 6.0+
- **NSIS** (Nullsoft Scriptable Install System)
- Windows SDK (für Icon-Ressourcen)

---

## ⚙️ Konfiguration

### Konfigurations-Datei

Pfad: `config/config.json`

```json
{
  "speicherort": "C:\\Videos\\Tandem",
  "ort": "Calden",
  "dauer": 8,
  "outside_video": false,
  "tandemmaster": "",
  "videospringer": "",
  "upload_to_server": false,
  "server_url": "smb://169.254.169.254/aktuell"
}
```

### Wichtige Einstellungen

| Einstellung | Beschreibung | Standard |
|-------------|--------------|----------|
| `speicherort` | Zielordner für fertige Videos | `""` |
| `ort` | Dropzone-Standort | `"Calden"` |
| `dauer` | Video-Intro-Dauer (Sekunden) | `8` |
| `outside_video` | Outside-Kamera-Video einbinden | `false` |
| `upload_to_server` | Automatischer Server-Upload | `false` |
| `server_url` | SMB/Netzwerk-Pfad | `"smb://..."` |

### Umgebungsvariablen

Die Anwendung verwendet keine Umgebungsvariablen.

---

## 🔧 Troubleshooting

### Häufige Probleme

**Videos werden nicht geladen**
- ✅ Prüfen: Unterstützte Formate (MP4, MOV, AVI, MKV)
- ✅ FFmpeg korrekt installiert?
- ✅ Ausreichend Speicherplatz im Temp-Ordner?

**Re-Encoding schlägt fehl**
- ✅ Videos beschädigt?
- ✅ Codec-Unterstützung vorhanden?
- ✅ FFmpeg-Logs prüfen

**Server-Upload funktioniert nicht**
- ✅ Netzwerkverbindung aktiv?
- ✅ Server-URL korrekt?
- ✅ Zugriffsrechte vorhanden?

**QR-Code wird nicht erkannt**
- ✅ QR-Code in ersten 5 Sekunden sichtbar?
- ✅ Ausreichende Bildqualität?
- ✅ Korrekte Formatierung des QR-Codes?

### Logs & Debugging

**Log-Dateien:**
- Aktuell keine persistenten Logs implementiert
- Konsolen-Output bei Entwickler-Version verfügbar

**Debug-Modus aktivieren:**
```bash
# Im Code: Setze DEBUG-Flag in constants.py
DEBUG = True
```

### Support

Bei Problemen:
1. Anwendung neu starten
2. Temp-Ordner leeren
3. Neuinstallation versuchen
4. Entwickler kontaktieren

---

## 📄 Lizenz

Proprietäre Software - Alle Rechte vorbehalten.

Diese Software ist urheberrechtlich geschützt und darf ohne ausdrückliche Genehmigung nicht:
- Vervielfältigt
- Verbreitet
- Modifiziert
- Öffentlich zugänglich gemacht werden

---

## 👨‍💻 Entwickler

**Projekt:** Aero Tandem Studio  
**Version:** 0.1.0.7  
**Letztes Update:** Oktober 2025

---

## 🙏 Danksagungen

Verwendete Open-Source-Bibliotheken:
- [MoviePy](https://zulko.github.io/moviepy/) - Video-Bearbeitung
- [FFmpeg](https://ffmpeg.org/) - Video-Encoding
- [pyzbar](https://github.com/NaturalHistoryMuseum/pyzbar) - QR-Code-Erkennung
- [tkinterdnd2](https://github.com/pmgagne/tkinterdnd2) - Drag & Drop
- [python-vlc](https://github.com/oaubert/python-vlc) - Video-Wiedergabe

---

## 📝 Changelog

### Version 0.1.0.7 (Aktuell)
- ✨ Vollständige GUI-Implementierung
- ✨ Video-Schneiden und Teilen
- ✨ QR-Code-Analyse
- ✨ Auto-Update-Funktion
- ✨ Server-Upload-Integration
- 🐛 Diverse Bugfixes

### Version 0.0.1
- 🎉 Initiale Version
- ✨ Basis-Funktionalität

---

**Made with ❤️ for Tandem Skydivers**

