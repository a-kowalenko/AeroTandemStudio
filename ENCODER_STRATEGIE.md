# Strategie zur Einführung einer zentralen `encoder.py` (MediaEncodingService)

## 1. Problemübersicht / Aktueller Zustand
In der aktuellen Codebasis sind Encoding- und Decoding-Prozesse über mehrere Klassen und GUI-Komponenten verteilt:

Betroffene Dateien:
- `video_preview.py` – Vorschau-Erstellung, Re-Encoding, Formatprüfung, Concat, Copy ohne Thumbnails, ffprobe-Abfragen, Progress-Loop (duplicated)
- `processor.py` – Finale Produkterstellung: Intro bauen, Wasserzeichen-Video, Wasserzeichen-Fotos, TS-Konvertierung, Concat, ffprobe, eigener Progress-Loop (duplicated)
- `hardware_acceleration.py` – Hardware-Erkennung + Parametergenerierung
- `parallel_processor.py` – Thread-Pool Wrapper für paralleles Encoding
- `app.py` – Orchestriert UI, reicht Callbacks durch, kennt `VideoProcessor` direkt

Hauptprobleme:
- Doppelte Implementationen: `_run_ffmpeg_with_progress`, FFprobe-Helps, Formatchecks
- Vermischung von UI-/Business- und Encoding-Logik (z.B. Progress-Handler im Encodingcode)
- Uneinheitliche Terminologie ("reencode", "copy", "combine", "standardisieren")
- Fehlende zentrale Stelle für Hardware-Fallback-Strategien (10-bit Problem wird lokal behandelt)
- Caching-/Temp-Handling nur in `VideoPreview` (Zweck gemischt: Preview + Preprocessing + Formatnormalisierung)
- Unterschiedliche Fehlerbehandlung / Rückgabeformen (Exceptions vs. Rückgabewerte)
- Schwierige Testbarkeit (starke GUI-Kopplung)

## 2. Ziele
- Zentrale, testbare Blackbox für alle Media-Verarbeitungsoperationen (Video + Bild) in `encoder.py`
- Einheitliche API (klare Input-/Output-Verträge, strukturierte Rückgaben)
- Einheitliche Fortschritts- und Statusmeldungen (Event-/Callback-Modell)
- Konsequente Hardware-Nutzung mit robustem Fallback auf Software
- Reduzierung von Code-Duplikaten / klarer Separation of Concerns
- Verbesserte Fehlersichtbarkeit & Wiederholbarkeit (strukturierte Fehlerobjekte)
- Bessere Erweiterbarkeit (z.B. zukünftige Codecs, zusätzliche Filter, Subtitle-Merging)

Nicht-Ziele (Phase 1):
- Vollständige Umschreibung aller bestehenden Komponenten
- Entfernung aller bisherigen Klassen sofort
- Tiefe Optimierung einzelner FFmpeg-Parameter für Qualität

## 3. Zielarchitektur (High-Level)
```
GUI (App, VideoPreview, Processor Aufrufer)
        ↓ (nutzt nur öffentliche Methoden + Callback-Schnittstellen)
MediaEncodingService (encoder.py)
  ├─ HardwareContext (wrappet HardwareAccelerationDetector)
  ├─ FFprobeClient (MediaInfo / FormatVergleich)
  ├─ FFmpegCommandBuilder (deklarative Erstellung der Kommando-Listen)
  ├─ ExecutionEngine (Progress-Parsing, Cancellation, Fehlerklassifizierung)
  ├─ ParallelScheduler (nutzt parallel_processor oder ersetzt ihn)
  ├─ TempWorkspaceManager (Preview-/Arbeitsverzeichnis, Kopien, Cleanup)
  └─ Job-/DTO-Klassen (VideoSpec, VideoInfo, WatermarkSpec, IntroSpec, ProgressEvent)
```

## 4. Kern-Klasse: `MediaEncodingService`
Verantwortung: Bereitstellung von klaren Methoden für:
- Probe: `probe_videos()`, `probe_photo()`
- Format- & Kompatibilitätsanalyse: `analyze_compatibility(video_infos)`
- Standardisierung / Re-Encoding: `standardize_videos(paths, target_spec)`
- Schnelles Kombinieren: `concat_stream_copy(paths)`
- Sicheres Kombinieren (Fallback): `concat_with_reencode(paths, target_spec)` (Optional später)
- Vorschau-Erstellung (Workflow): `build_preview(video_paths)`
- Intro-Erstellung: `create_intro(intro_spec)`
- Endprodukt Video: `assemble_final_video(intro_path, main_video_path, output_path, params)`
- Wasserzeichen-Video: `create_watermarked_video(base_clip_path, output_path, wm_spec)`
- Wasserzeichen-Fotos: `create_watermarked_photos(photo_paths, output_dir, wm_spec)`
- Hilfsmethoden: `extract_first_frame(video)`, `remove_mjpeg_thumbnail(...)`, `ensure_temp_workspace()` usw.

WICHTIG: Die durch `build_preview()` erzeugte Combined-Datei ist das „Master“-Artefakt im Workspace und soll – solange der Codec-Setting nicht geändert wird – direkt für das Endprodukt verwendet werden.

Alle Methoden nutzen gemeinsame interne Helfer:
- `_run_ffmpeg(command, progress_config)` → Einheitliches Progress-Streaming + Cancellation
- `_build_filter_chain(spec)` → Declaratives Bauen von Filtergraphen
- `_resolve_encoder(codec, hw_pref)` → Hardware vs. Software
- `_quote(path)` / `_normalize_path` → Windows-sichere Pfade

## 5. Datenmodelle (DTO / Pydantic optional später)
Einfach als `dataclass` starten:

```python
@dataclass
class VideoInfo:
    path: str
    width: int
    height: int
    fps: float
    codec: str
    pix_fmt: str
    duration: float

@dataclass
class VideoSpec:
    target_width: int
    target_height: int
    target_fps: int
    pix_fmt: str = 'yuv420p'
    codec: str = 'h264'

@dataclass
class WatermarkSpec:
    image_path: str
    position: str  # 'center', 'top-right', etc.
    scale_mode: str  # 'fit_width', 'fit_height', 'original'
    alpha: float  # 0.0 - 1.0
    target_resolution: tuple[int,int] | None  # für Preview-Versionen (z.B. 320x240)

@dataclass
class IntroSpec:
    background_image: str
    duration_sec: float
    text_lines: list[str]
    font: str
    font_size: int
    output_resolution: tuple[int,int]

@dataclass
class ProgressEvent:
    task: str
    percent: float | None
    fps: float | None
    eta: str | None
    current_sec: float
    total_sec: float | None
    job_id: str | None
```

## 6. Öffentliche API (Entwurf)
```python
class MediaEncodingService:
    def __init__(self, config_manager, on_progress: Callable[[ProgressEvent], None] = None,
                 hw_detector: HardwareAccelerationDetector | None = None,
                 parallel_scheduler: ParallelVideoProcessor | None = None): ...

    # Ingest / Workspace
    def ingest_media_to_workspace(self, video_paths: list[str], photo_paths: list[str]) -> dict: ...  # kopiert in Working-Folder (nur einmal), Rückgabe: {'videos': [...], 'photos': [...]} (Workspace-Pfade)
    def ensure_workspace(self) -> None: ...  # legt/verifiziert Temp-Root

    # Analyse
    def probe_videos(self, paths: list[str]) -> list[VideoInfo]: ...
    def probe_video(self, path: str) -> VideoInfo: ...
    def probe_photo(self, path: str) -> dict: ...  # width, height, format
    def analyze_compatibility(self, infos: list[VideoInfo]) -> dict: ...  # {'compatible': bool, 'diffs': [...]}  

    # Preview / Master-Artefakt
    def build_preview(self, paths: list[str], mode: str = 'auto', forced_codec: str | None = None) -> dict: ...
    # Rückgabe: {
    #   'combined_path': str,             # authoritative combined preview
    #   'standardized': bool,             # ob Re-Encode stattfand
    #   'workspace_video_paths': list[str],
    #   'target_spec': VideoSpec,
    # }

    # Standardisierung / Kopien
    def standardize_videos(self, paths: list[str], spec: VideoSpec, reuse_cache=True) -> list[str]: ...  # schreibt zuerst in temp, ersetzt dann atomar die Workspace-Kopien
    def stream_copy_videos(self, paths: list[str], remove_thumbnails=True) -> list[str]: ...

    # Kombination
    def concat_stream_copy(self, paths: list[str]) -> str: ...

    # Intro + Finales Produkt
    def create_intro(self, spec: IntroSpec) -> str: ...
    def assemble_final_video_from_preview(self, combined_preview_path: str, output_path: str) -> str: ...  # stream-copy concat aus Intro(gleiche Parameter) + combined_preview

    # Wasserzeichen
    def create_watermarked_video(self, base_clip_path: str, output_path: str, wm_spec: WatermarkSpec) -> str: ...
    def create_watermarked_photos(self, photo_paths: list[str], output_dir: str, wm_spec: WatermarkSpec) -> list[str]: ...

    # Utilities
    def extract_first_frame(self, video_path: str, size_hint: int) -> str: ...
    def remove_mjpeg_thumbnail(self, input_path: str, output_path: str) -> None: ...
    def cleanup(self): ...  # Temp Verzeichnisse löschen
    def cancel_all(self): ...  # Setzt Cancellation Event
```

### 6a. Regeln für Auto/Codec und Re-Use
- Modus „auto“:
  - Wenn alle Clips kompatibel: stream copy je Clip (ggf. Thumbnail-Entfernung), dann stream-copy Concat zur Combined-Datei.
  - Wenn inkompatibel: Re-Encode aller Clips auf `h264 1080p@30 yuv420p`, danach stream-copy Concat.
- Modus „codec=X“ (Benutzer hat expliziten Codec gewählt):
  - Immer Re-Encode aller Clips auf `X 1080p@30 yuv420p`, danach stream-copy Concat.
- Die `combined_preview` ist Master und wird für das Endprodukt verwendet, solange der Codec-Modus unverändert bleibt.
- Wird der Codec-Modus nachträglich geändert, wird die Standardisierung + Combined neu erstellt.

### 6b. Triggers bei Add/Remove/Reorder
- Bei Hinzufügen/Entfernen/Neuordnung der Workspace-Videoliste:
  - Neu prüfen: Kompatibilität aller Clips.
  - Falls kompatibel: nur Concat neu bauen (schnell), keine Neukodierung.
  - Falls inkompatibel: Re-Encode gemäß Regeln oben und danach Concat.
- Umsetzung: Eine zentrale Methode (z. B. `build_preview(...)`) wird von der GUI immer dann aufgerufen, wenn sich die Video-Liste ändert.

## 7. Progress & Cancellation
- Zentraler Cancellation Event: `self.cancel_event = threading.Event()`
- Jede FFmpeg-Ausführung ruft periodisch `_check_cancel()` → Prozess-Termination, sauberes Aufräumen
- Progress-Parsing vereinheitlicht (nur eine Implementierung):
  - Generiert `ProgressEvent`
  - UI-Schichten (VideoPreview, Processor, App) abonnieren nur noch über registrierten Callback
- Parallele Tasks über `parallel_scheduler.process(video_tasks, cancel_event, on_each_complete)` → Unified

## 8. Hardware-Integration
- `HardwareContext` kapselt `HardwareAccelerationDetector` + Caching des letzten Ergebnisses
- Methode `resolve_encoder(codec, prefer_hw=True)` → gibt output_params zurück
- Automatischer Fallback: Wenn Fehlermuster erkannt (Liste zentral definiert), neu mit Software erneut
- 10-bit Handling: Beim Erkennen von 10-bit Input + nicht unterstütztem HW → automatische Umschaltung ohne Rekursionseffekt

## 9. Filter-Building Strategie
Ziel: verbesserte Lesbarkeit vs. Inline Strings.

Beispiel Video-Standardisierung:
```python
filters = [
    f"scale={spec.target_width}:{spec.target_height}:force_original_aspect_ratio=decrease:flags=fast_bilinear",
    f"pad={spec.target_width}:{spec.target_height}:(ow-iw)/2:(oh-ih)/2:color=black",
    f"fps={spec.target_fps}",
    f"format={spec.pix_fmt}"
]
filter_chain = ','.join(filters)
```
Wasserzeichen:
```python
wm_filters = [
    "[0:v]scale=...:pad=...:format=yuv420p[base]",
    "[1:v]scale=...:format=rgba[wm_scaled]",
    "[base][wm_scaled]overlay=(W-w)/2:(H-h)/2"  # position abhängig von WatermarkSpec
]
```

## 10. Fehlerbehandlung
Zentrale Klasse `EncodingError(Exception)` mit Feldern:
- `stage` (z.B. 'probe', 'encode', 'concat')
- `command` (Liste)
- `stderr_excerpt` (gekürzt)
- `recoverable` (bool)

Bei Fehler → Logging + optionaler Fallback. UI zeigt verständliche Nachricht.

## 11. Caching & Temp Handling
`TempWorkspaceManager`:
- Wurzelpfad: `tempfile.mkdtemp(prefix='aero_media_')`
- Map: `(filename,size)` → Pfad
- API: `get_or_create_copy(original_path)`, `register_processed(original_path, processed_path)`
- Schreiben erfolgt robust: Zuerst in eine temporäre Datei (z. B. `.<name>.tmp`) im gleichen Verzeichnis, danach atomarer Replace der Workspace-Kopie via `os.replace()` → verhindert halbfertige Dateien.
- Säuberung: `cleanup()` beim App-Schließen oder explizitem Reset
- Auslagerung Logik aus `VideoPreview._prepare_video_copies`

## 12. Migrations-Plan (Phasen)
Phase 0 – Vorbereitung:
- Neue Datei `encoder.py` anlegen mit Skelett + DTOs + Platzhaltern
- Keine Integration, nur Tests gegen Probe-Funktionen

Phase 1 – Analyse / Probe extrahieren:
- Verschiebe ffprobe Logik aus `video_preview.py` & `processor.py` in Service
- Ersetze Aufrufe in alten Klassen durch Service.probe_* Aufrufe

Phase 2 – Vereinheitlichung Progress-Loop:
- Implementiere `_run_ffmpeg` + Callback Modell
- Entferne duplizierte `_run_ffmpeg_with_progress` aus beiden Klassen, ersetze durch Service

Phase 3 – Standardisierung & Caching:
- Extrahiere Re-Encoding + Stream-Copy + Thumbnail-Entfernung
- VideoPreview nutzt Service für: Standardisierung & Concat

Phase 4 – Intro-Erstellung & Finale Kombination:
- Verschiebe `processor._create_intro_with_silent_audio` & TS-Konvertierung
- Ersetze in `VideoProcessor` durch Service-Methoden
- Stell sicher: `assemble_final_video_from_preview()` nutzt die Combined-Vorschau als Master und erzeugt das Intro mit exakt denselben Parametern (Resolution/FPS/Codec) für stream-copy Concat.

Phase 5 – Wasserzeichen (Video + Foto):
- Konsolidiere Wasserzeichen-Logik (Skalierung, Alpha, Position)
- Vereinheitliche Parameter (keine Inline-Filters mehr in Processor)

Phase 6 – Parallelisierung / Scheduler:
- Integriere `parallel_processor` in Service (Parameter injizieren)
- Vereinheitliche Task-Building

Phase 7 – UI-Dekoupling / Cleanup:
- Entferne Encoding-spezifische Zustandsattribute aus `VideoPreview` / `VideoProcessor`, soweit möglich
- Fokussiere diese Klassen auf rein UI + Orchestrierung

Phase 8 – Tests & Validierung:
- Unit-Tests für Filter-Building, Error-Fallback, Probe, Progress Parsing
- Integrationstests: Preview-Erstellung, Wasserzeichen-Foto, Intro + Concat

Rollback-Strategie: Jede Phase committen; bei Problemen nur betroffene Phase rückgängig machen.

## 13. Test-Strategie
Unit Tests (neue `tests/test_encoder_service.py`):
- `probe_video` mit Dummy-Datei (Mock ffprobe)
- Progress Parsing (simulierter FFmpeg stdout Stream)
- Fehlerklassifizierung (synthetischer stderr Input)
- Filter-Building (expected chain string)

Integration Tests:
- Standardisierung vs. Stream-Copy (zwei Videos mit unterschiedlicher Auflösung)
- Wasserzeichen-Video (Prüfe Existenz + Dimensionen via ffprobe)
- Foto-Wasserzeichen (Verifiziere Existenz + PNG Größe)

Performance Smoke:
- Zeitmessung Standardisierung von N dummy Clips (Mock / kleine Dateien)

## 14. Edge Cases
- 10-bit Quelle + fehlender HW-Encoder Support
- Fehlendes Audio im Hauptvideo (aktuell wird Audio zwingend erwartet) → Plan: optionaler Audio-Fallback
- Leere Eingabeliste (frühes Return, kein Fehler)
- Nicht auffindbare Wasserzeichen-Datei → klarer Fehler
- Pfade mit Sonderzeichen / Leerzeichen (Windows quoting) → sichere Erstellung der Concat-Liste
- Cancellation während Concat (Prozess killen, temporäre Dateien löschen)
- Unvollständige Ausgabe-Dateien bei FFmpeg Fehler (prüfen Dateigröße > Mindestschwelle)

## 15. Logging-Konzept
- Einheitlicher Prefix: `[Encoder]`
- Debug-Level für Kommando-Aufbau optional schaltbar (Config Flag `debug_encoding`)
- Fehler bündeln (stderr letzten 15 Zeilen)

## 16. Sicherheit / Robustheit
- Keine UI-Abhängigkeiten → reine Logik testbar
- Keine globalen Zustände (nur Instanz-Zustand + TempWorkspaceManager)
- Klare Cleanup-Pfade (App-Schließen → Service.cleanup())

## 17. Mapping Alt → Neu (Beispiele)
| Alt (Methode)                               | Neu (Service)                       |
|---------------------------------------------|-------------------------------------|
| `VideoPreview._reencode_single_clip`        | `standardize_videos` (batch) oder intern `_encode_one` |
| `VideoPreview._copy_without_thumbnails`     | `stream_copy_videos(remove_thumbnails=True)` |
| `VideoPreview._create_fast_combined_video`  | `concat_stream_copy`                |
| `VideoProcessor._create_intro_with_silent_audio` | `create_intro`                |
| `VideoProcessor._create_video_with_watermark` | `create_watermarked_video`      |
| `VideoProcessor._create_photo_with_watermark` | `create_watermarked_photos`     |
| Doppelte `_run_ffmpeg_with_progress`        | Gemeinsame `_run_ffmpeg`            |
| Formatprüfung `_check_video_formats`        | `analyze_compatibility`             |
| Hardware-Parameterauswahl                   | `resolve_encoder` / HardwareContext |

## 18. Offene Fragen
1. Soll die Wasserzeichen-Video-Version weiterhin unabhängig vom finalen Produktformat (z.B. heruntergerechnet auf 240p) sein oder parametrisiert werden?
2. Brauchen wir mehr Codec-Flexibilität (AV1/VP9) im UI jetzt oder später?
3. Soll Foto-Wasserzeichen optional mehrere Layer erlauben (Logo + Text)?
4. Persistenter Cache über App-Lebensdauer hinaus sinnvoll? (Aktuell nur temp)
5. Sollen wir ffmpeg/ffprobe Aufrufe optional asynchron machen (Queue) um UI noch responsiver zu halten?

## 19. Nächste Schritte (konkret)
1. Datei `encoder.py` erstellen mit Grundgerüst + DTOs + Platzhaltermethoden.
2. Extraktion ffprobe Logik & Progress-Parsing implementieren.
3. Unit-Tests für Schritt 2 schreiben.
4. VideoPreview auf neue `probe_videos` + `analyze_compatibility` umstellen.
5. Re-Encoding & Copy Konsolidierung implementieren.
6. `processor.py` schrittweise auf neue Intro-/Wasserzeichen-Methoden migrieren.
7. Combined-Preview als Master-Baustein in `assemble_final_video_from_preview()` integrieren.

## 20. Kurzfazit
Mit einer zentralen `MediaEncodingService` gewinnen wir:
- Wartbarkeit (ein Ort für alle Encoding-Fälle)
- Verlässliche Hardware-Fallbacks
- Geringeres Risiko für Inkonsistenzen
- Leichtere Einführung neuer Funktionen (z.B. Untertitel, Kapitel, Multi-Audio)

Diese Strategie erlaubt inkrementelle Migration mit klaren Phasen ohne Big-Bang-Risiko.

---
(Ende Strategie)
