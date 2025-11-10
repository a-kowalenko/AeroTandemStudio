"""
MediaEncodingService - Zentrale Blackbox für Video/Foto-Encoding und -Decoding

Diese Klasse konsolidiert alle FFmpeg-/FFprobe-Operationen in einer testbaren,
UI-unabhängigen API. Sie verwaltet einen Working-Folder für Clips, erkennt
Hardware-Beschleunigung, führt Formatprüfungen durch, standardisiert Videos
bei Bedarf und kombiniert sie zu einem Master-Artefakt (combined_preview).

Ziele:
- Einheitliche API für alle Encoding-Operationen
- Hardware-Fallback bei Fehlern (10-bit, Driver-Probleme)
- Progress-Reporting via Callbacks
- Robuste Fehlerbehandlung mit strukturierten Exceptions
- Atomares Schreiben (temp → replace) für Datei-Integrität

Autor: AeroTandemStudio
Datum: 2025-01-10
"""

import os
import sys
import json
import time
import shutil
import tempfile
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Callable, List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

# Imports aus dem Projekt
from src.utils.constants import SUBPROCESS_CREATE_NO_WINDOW
from src.utils.hardware_acceleration import HardwareAccelerationDetector
from .parallel_processor import ParallelVideoProcessor


# ============================================================================
# DTOs (Data Transfer Objects)
# ============================================================================

@dataclass
class VideoInfo:
    """Metadaten eines Video-Clips (aus ffprobe)"""
    path: str
    width: int
    height: int
    fps: float
    codec: str
    pix_fmt: str
    duration: float
    audio_codec: Optional[str] = None
    sample_rate: Optional[int] = None

    def __str__(self):
        return f"{self.codec} {self.width}x{self.height}@{self.fps:.2f}fps {self.pix_fmt}"


@dataclass
class VideoSpec:
    """Ziel-Spezifikation für Video-Encoding"""
    target_width: int = 1920
    target_height: int = 1080
    target_fps: int = 30
    pix_fmt: str = 'yuv420p'
    codec: str = 'h264'

    def __str__(self):
        return f"{self.codec} {self.target_width}x{self.target_height}@{self.target_fps}fps {self.pix_fmt}"


@dataclass
class WatermarkSpec:
    """Spezifikation für Wasserzeichen-Anwendung"""
    image_path: str
    position: str = 'center'  # 'center', 'top-right', 'bottom-left', etc.
    scale_mode: str = 'fit_width'  # 'fit_width', 'fit_height', 'original'
    alpha: float = 0.8  # Transparenz (0.0 - 1.0)
    target_resolution: Optional[Tuple[int, int]] = None  # Für Preview-Versionen (z.B. 320x240)


@dataclass
class IntroSpec:
    """Spezifikation für Intro-Erstellung"""
    background_image: str
    duration_sec: float
    text_lines: List[str]
    font: str = 'Arial'
    font_size: int = 48
    output_resolution: Tuple[int, int] = (1920, 1080)
    output_fps: int = 30
    output_codec: str = 'h264'
    output_pix_fmt: str = 'yuv420p'


@dataclass
class ProgressEvent:
    """Event für Fortschritts-Updates"""
    task: str
    percent: Optional[float] = None
    fps: Optional[float] = None
    eta: Optional[str] = None
    current_sec: float = 0.0
    total_sec: Optional[float] = None
    job_id: Optional[str] = None

    def __str__(self):
        parts = [self.task]
        if self.percent is not None:
            parts.append(f"{self.percent:.1f}%")
        if self.fps is not None:
            parts.append(f"{self.fps:.1f}fps")
        if self.eta:
            parts.append(f"ETA: {self.eta}")
        return " | ".join(parts)


# ============================================================================
# Exceptions
# ============================================================================

class EncodingError(Exception):
    """Basis-Exception für Encoding-Fehler"""

    def __init__(self, message: str, stage: str = 'unknown',
                 command: Optional[List[str]] = None,
                 stderr_excerpt: Optional[str] = None,
                 recoverable: bool = False):
        super().__init__(message)
        self.stage = stage
        self.command = command
        self.stderr_excerpt = stderr_excerpt
        self.recoverable = recoverable

    def __str__(self):
        msg = f"[{self.stage}] {super().__str__()}"
        if self.stderr_excerpt:
            msg += f"\nFFmpeg Output: {self.stderr_excerpt}"
        return msg


# ============================================================================
# TempWorkspaceManager
# ============================================================================

class TempWorkspaceManager:
    """
    Verwaltet temporären Working-Folder für Medien-Dateien.

    Funktionen:
    - Erstellt persistenten Workspace-Ordner (bleibt bis cleanup())
    - Mapping: (filename, size) → workspace_path
    - Atomares Schreiben: temp-Datei → os.replace()
    - Cleanup beim App-Ende
    """

    def __init__(self):
        self.workspace_root: Optional[str] = None
        self.file_map: Dict[Tuple[str, int], str] = {}  # (filename, size) → path

    def ensure_workspace(self) -> str:
        """Erstellt/verifiziert Workspace-Root"""
        if self.workspace_root and os.path.exists(self.workspace_root):
            return self.workspace_root

        self.workspace_root = tempfile.mkdtemp(prefix='aero_media_')
        print(f"[Workspace] Erstellt: {self.workspace_root}")
        return self.workspace_root

    def get_file_identity(self, file_path: str) -> Optional[Tuple[str, int]]:
        """Erstellt Identität für Datei (filename, size)"""
        try:
            filename = os.path.basename(file_path)
            size = os.path.getsize(file_path)
            return (filename, size)
        except Exception as e:
            print(f"[Workspace] Fehler bei Identity-Erstellung: {e}")
            return None

    def get_workspace_path(self, original_path: str) -> Optional[str]:
        """Gibt Workspace-Pfad für Original-Datei zurück (falls vorhanden)"""
        identity = self.get_file_identity(original_path)
        if not identity:
            return None
        return self.file_map.get(identity)

    def register_file(self, original_path: str, workspace_path: str) -> None:
        """Registriert Mapping: Original → Workspace"""
        identity = self.get_file_identity(original_path)
        if identity:
            self.file_map[identity] = workspace_path

    def atomic_write(self, target_path: str, source_data_or_path: str,
                     is_path: bool = True) -> None:
        """
        Schreibt Datei atomar (temp → replace).

        Args:
            target_path: Ziel-Pfad im Workspace
            source_data_or_path: Entweder Pfad zu Quelldatei oder Daten-String
            is_path: True wenn source ist Pfad, False wenn Daten-String
        """
        target_dir = os.path.dirname(target_path)
        target_name = os.path.basename(target_path)

        # Temporäre Datei im gleichen Verzeichnis
        temp_path = os.path.join(target_dir, f".{target_name}.tmp")

        try:
            if is_path:
                # Kopiere Datei
                shutil.copy2(source_data_or_path, temp_path)
            else:
                # Schreibe Daten
                with open(temp_path, 'w', encoding='utf-8') as f:
                    f.write(source_data_or_path)

            # Atomarer Replace
            os.replace(temp_path, target_path)

        except Exception as e:
            # Cleanup bei Fehler
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass
            raise e

    def cleanup(self) -> None:
        """Löscht Workspace und alle Mappings"""
        if self.workspace_root and os.path.exists(self.workspace_root):
            try:
                shutil.rmtree(self.workspace_root)
                print(f"[Workspace] Gelöscht: {self.workspace_root}")
            except Exception as e:
                print(f"[Workspace] Fehler beim Löschen: {e}")

        self.workspace_root = None
        self.file_map.clear()


# ============================================================================
# MediaEncodingService (Hauptklasse)
# ============================================================================

class MediaEncodingService:
    """
    Zentrale Service-Klasse für alle Video-/Foto-Encoding-Operationen.

    Verwendung:
        service = MediaEncodingService(config_manager, on_progress=my_callback)
        service.ingest_media_to_workspace(videos, photos)
        result = service.build_preview(service.workspace_videos, mode='auto')
        combined_path = result['combined_path']
    """

    def __init__(self,
                 config_manager,
                 on_progress: Optional[Callable[[ProgressEvent], None]] = None,
                 hw_detector: Optional[HardwareAccelerationDetector] = None,
                 parallel_scheduler: Optional[ParallelVideoProcessor] = None):
        """
        Initialisiert MediaEncodingService.

        Args:
            config_manager: ConfigManager-Instanz für Settings
            on_progress: Callback für Progress-Events
            hw_detector: Optional HardwareAccelerationDetector (wird erstellt falls None)
            parallel_scheduler: Optional ParallelVideoProcessor (wird erstellt falls None)
        """
        self.config = config_manager
        self.on_progress = on_progress

        # Hardware-Beschleunigung
        self.hw_detector = hw_detector or HardwareAccelerationDetector()
        self.hw_accel_enabled = False
        self._init_hardware_acceleration()

        # Paralleles Processing
        self.parallel_scheduler = parallel_scheduler
        if parallel_scheduler is None and self.config:
            settings = self.config.get_settings()
            if settings.get("parallel_processing_enabled", True):
                self.parallel_scheduler = ParallelVideoProcessor(self.hw_accel_enabled)

        # Workspace Management
        self.workspace_manager = TempWorkspaceManager()

        # Cancellation
        self.cancel_event = threading.Event()

        # State
        self.workspace_videos: List[str] = []
        self.workspace_photos: List[str] = []
        self.combined_preview_path: Optional[str] = None
        self.current_spec: Optional[VideoSpec] = None

    def _init_hardware_acceleration(self):
        """Initialisiert Hardware-Beschleunigung basierend auf Config"""
        if self.config:
            settings = self.config.get_settings()
            self.hw_accel_enabled = settings.get("hardware_acceleration_enabled", True)

            if self.hw_accel_enabled:
                hw_info = self.hw_detector.detect_hardware()
                if hw_info['available']:
                    print(f"[Encoder] Hardware-Beschleunigung: {self.hw_detector.get_hardware_info_string()}")
                else:
                    print(f"[Encoder] Hardware-Beschleunigung aktiviert, aber nicht verfügbar → Software-Fallback")
            else:
                print(f"[Encoder] Hardware-Beschleunigung deaktiviert")

    # ========================================================================
    # Ingest / Workspace
    # ========================================================================

    def ingest_media_to_workspace(self, video_paths: List[str],
                                  photo_paths: List[str]) -> Dict[str, List[str]]:
        """
        Kopiert Media-Dateien in den Working-Folder.

        Args:
            video_paths: Liste Original-Video-Pfade
            photo_paths: Liste Original-Foto-Pfade

        Returns:
            {'videos': [workspace_paths], 'photos': [workspace_paths]}
        """
        self.workspace_manager.ensure_workspace()

        workspace_videos = []
        workspace_photos = []

        # Videos kopieren
        for orig_path in video_paths:
            if not os.path.exists(orig_path):
                print(f"[Encoder] Warnung: Datei nicht gefunden: {orig_path}")
                continue

            # Prüfe ob bereits im Workspace
            existing = self.workspace_manager.get_workspace_path(orig_path)
            if existing and os.path.exists(existing):
                workspace_videos.append(existing)
                continue

            # Kopiere neu
            filename = os.path.basename(orig_path)
            # Sanitize filename (entferne ungültige Zeichen)
            safe_filename = self._sanitize_filename(filename)
            target_path = os.path.join(self.workspace_manager.workspace_root, safe_filename)

            # Handle Kollisionen
            if os.path.exists(target_path):
                base, ext = os.path.splitext(safe_filename)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(self.workspace_manager.workspace_root,
                                              f"{base}_{counter}{ext}")
                    counter += 1

            # Atomares Kopieren
            self.workspace_manager.atomic_write(target_path, orig_path, is_path=True)
            self.workspace_manager.register_file(orig_path, target_path)
            workspace_videos.append(target_path)
            print(f"[Encoder] Kopiert: {filename} → Workspace")

        # Fotos kopieren (analog)
        for orig_path in photo_paths:
            if not os.path.exists(orig_path):
                continue

            existing = self.workspace_manager.get_workspace_path(orig_path)
            if existing and os.path.exists(existing):
                workspace_photos.append(existing)
                continue

            filename = os.path.basename(orig_path)
            safe_filename = self._sanitize_filename(filename)
            target_path = os.path.join(self.workspace_manager.workspace_root, safe_filename)

            if os.path.exists(target_path):
                base, ext = os.path.splitext(safe_filename)
                counter = 1
                while os.path.exists(target_path):
                    target_path = os.path.join(self.workspace_manager.workspace_root,
                                              f"{base}_{counter}{ext}")
                    counter += 1

            self.workspace_manager.atomic_write(target_path, orig_path, is_path=True)
            self.workspace_manager.register_file(orig_path, target_path)
            workspace_photos.append(target_path)

        # State aktualisieren
        self.workspace_videos = workspace_videos
        self.workspace_photos = workspace_photos

        return {
            'videos': workspace_videos,
            'photos': workspace_photos
        }

    def ensure_workspace(self) -> None:
        """Stellt sicher dass Workspace existiert"""
        self.workspace_manager.ensure_workspace()

    # ========================================================================
    # Analyse / Probe
    # ========================================================================

    def probe_video(self, path: str) -> VideoInfo:
        """
        Analysiert ein Video mit ffprobe.

        Args:
            path: Pfad zur Video-Datei

        Returns:
            VideoInfo-Objekt mit Metadaten

        Raises:
            EncodingError: Bei Probe-Fehler
        """
        # TODO: Implementierung
        raise NotImplementedError("probe_video noch nicht implementiert")

    def probe_videos(self, paths: List[str]) -> List[VideoInfo]:
        """
        Analysiert mehrere Videos.

        Args:
            paths: Liste von Video-Pfaden

        Returns:
            Liste von VideoInfo-Objekten
        """
        results = []
        for path in paths:
            try:
                info = self.probe_video(path)
                results.append(info)
            except Exception as e:
                print(f"[Encoder] Probe-Fehler für {path}: {e}")
                # Überspringe fehlerhafte Dateien
        return results

    def probe_photo(self, path: str) -> Dict:
        """
        Analysiert ein Foto.

        Args:
            path: Pfad zur Foto-Datei

        Returns:
            Dict mit width, height, format
        """
        # TODO: Implementierung
        raise NotImplementedError("probe_photo noch nicht implementiert")

    def analyze_compatibility(self, infos: List[VideoInfo]) -> Dict:
        """
        Prüft ob Videos kompatibel sind (gleiche Parameter).

        Args:
            infos: Liste von VideoInfo-Objekten

        Returns:
            {'compatible': bool, 'diffs': [str], 'details': str}
        """
        # TODO: Implementierung
        raise NotImplementedError("analyze_compatibility noch nicht implementiert")

    # ========================================================================
    # Preview / Master-Artefakt
    # ========================================================================

    def build_preview(self, paths: List[str], mode: str = 'auto',
                     forced_codec: Optional[str] = None) -> Dict:
        """
        Erstellt Combined-Preview (Master-Artefakt).

        Workflow:
        1. Probe alle Videos
        2. Prüfe Kompatibilität
        3. Wenn mode='auto':
           - kompatibel → stream_copy
           - inkompatibel → standardize → stream_copy
        4. Wenn forced_codec:
           - immer standardize(codec) → stream_copy
        5. Concat zu combined_preview

        Args:
            paths: Liste von Video-Pfaden (aus Workspace)
            mode: 'auto' oder codec-Name
            forced_codec: Erzwinge spezifischen Codec (überschreibt mode)

        Returns:
            {
                'combined_path': str,
                'standardized': bool,
                'workspace_video_paths': List[str],
                'target_spec': VideoSpec,
            }
        """
        # TODO: Implementierung
        raise NotImplementedError("build_preview noch nicht implementiert")

    # ========================================================================
    # Standardisierung / Kopien
    # ========================================================================

    def standardize_videos(self, paths: List[str], spec: VideoSpec,
                          reuse_cache: bool = True) -> List[str]:
        """
        Re-Encoded Videos auf Ziel-Spezifikation.

        Schreibt zuerst in temp-Dateien, ersetzt dann atomar die Workspace-Kopien.

        Args:
            paths: Liste von Video-Pfaden
            spec: Ziel-Spezifikation
            reuse_cache: Wiederverwendung gecachter Ergebnisse

        Returns:
            Liste der standardisierten Pfade (gleiche Pfade, neue Inhalte)
        """
        # TODO: Implementierung
        raise NotImplementedError("standardize_videos noch nicht implementiert")

    def stream_copy_videos(self, paths: List[str],
                          remove_thumbnails: bool = True) -> List[str]:
        """
        Kopiert Videos ohne Re-Encoding (entfernt optional MJPEG-Thumbnails).

        Args:
            paths: Liste von Video-Pfaden
            remove_thumbnails: Entferne eingebettete Thumbnails

        Returns:
            Liste der kopierten/bereinigten Pfade
        """
        # TODO: Implementierung
        raise NotImplementedError("stream_copy_videos noch nicht implementiert")

    # ========================================================================
    # Kombination
    # ========================================================================

    def concat_stream_copy(self, paths: List[str],
                          output_path: Optional[str] = None) -> str:
        """
        Kombiniert Videos via FFmpeg concat (stream copy).

        Args:
            paths: Liste von Video-Pfaden
            output_path: Optional Ausgabe-Pfad (sonst temp)

        Returns:
            Pfad zum kombinierten Video
        """
        # TODO: Implementierung
        raise NotImplementedError("concat_stream_copy noch nicht implementiert")

    # ========================================================================
    # Intro + Finales Produkt
    # ========================================================================

    def create_intro(self, spec: IntroSpec) -> str:
        """
        Erstellt Intro-Clip.

        Args:
            spec: IntroSpec mit allen Parametern

        Returns:
            Pfad zum Intro-Video
        """
        # TODO: Implementierung
        raise NotImplementedError("create_intro noch nicht implementiert")

    def assemble_final_video_from_preview(self, combined_preview_path: str,
                                         output_path: str,
                                         intro_spec: Optional[IntroSpec] = None) -> str:
        """
        Erstellt finales Video aus Combined-Preview.

        Workflow:
        1. Probe combined_preview (hole Parameter)
        2. Erstelle Intro mit exakt gleichen Parametern
        3. Concat via stream_copy (Intro + Combined)

        Args:
            combined_preview_path: Pfad zur Combined-Preview (Master)
            output_path: Pfad für finales Video
            intro_spec: Optional IntroSpec (wenn None, kein Intro)

        Returns:
            Pfad zum finalen Video
        """
        # TODO: Implementierung
        raise NotImplementedError("assemble_final_video_from_preview noch nicht implementiert")

    # ========================================================================
    # Wasserzeichen
    # ========================================================================

    def create_watermarked_video(self, base_clip_path: str,
                                 output_path: str,
                                 wm_spec: WatermarkSpec) -> str:
        """
        Erstellt Video mit Wasserzeichen.

        Args:
            base_clip_path: Pfad zum Basis-Video
            output_path: Ausgabe-Pfad
            wm_spec: WatermarkSpec mit Wasserzeichen-Parametern

        Returns:
            Pfad zum Video mit Wasserzeichen
        """
        # TODO: Implementierung
        raise NotImplementedError("create_watermarked_video noch nicht implementiert")

    def create_watermarked_photos(self, photo_paths: List[str],
                                  output_dir: str,
                                  wm_spec: WatermarkSpec) -> List[str]:
        """
        Erstellt Fotos mit Wasserzeichen.

        Args:
            photo_paths: Liste von Foto-Pfaden
            output_dir: Ausgabe-Verzeichnis
            wm_spec: WatermarkSpec mit Wasserzeichen-Parametern

        Returns:
            Liste der Pfade zu Fotos mit Wasserzeichen
        """
        # TODO: Implementierung
        raise NotImplementedError("create_watermarked_photos noch nicht implementiert")

    # ========================================================================
    # Utilities
    # ========================================================================

    def extract_first_frame(self, video_path: str, size_hint: int = 300) -> str:
        """
        Extrahiert ersten Frame als Bild.

        Args:
            video_path: Pfad zum Video
            size_hint: Gewünschte Breite in Pixel

        Returns:
            Pfad zum extrahierten Frame (JPG)
        """
        # TODO: Implementierung
        raise NotImplementedError("extract_first_frame noch nicht implementiert")

    def remove_mjpeg_thumbnail(self, input_path: str, output_path: str) -> None:
        """
        Entfernt MJPEG-Thumbnail aus Video (via stream copy).

        Args:
            input_path: Eingabe-Video
            output_path: Ausgabe-Video
        """
        # TODO: Implementierung
        raise NotImplementedError("remove_mjpeg_thumbnail noch nicht implementiert")

    def cleanup(self) -> None:
        """Löscht Workspace und alle temporären Dateien"""
        self.workspace_manager.cleanup()
        self.workspace_videos.clear()
        self.workspace_photos.clear()
        self.combined_preview_path = None
        self.current_spec = None
        print("[Encoder] Cleanup abgeschlossen")

    def cancel_all(self) -> None:
        """Setzt Cancellation-Event für alle laufenden Operationen"""
        self.cancel_event.set()
        print("[Encoder] Cancellation angefordert")

    # ========================================================================
    # Interne Helfer
    # ========================================================================

    def _sanitize_filename(self, filename: str) -> str:
        """Entfernt ungültige Zeichen aus Dateinamen"""
        import re
        # Ersetze ungültige Windows-Zeichen
        return re.sub(r'[<>:"/\\|?*]', '_', filename)

    def _check_cancel(self) -> None:
        """Prüft Cancellation und wirft Exception"""
        if self.cancel_event.is_set():
            raise EncodingError("Operation abgebrochen", stage='cancel', recoverable=True)

    def _run_ffmpeg(self, command: List[str],
                   total_duration: Optional[float] = None,
                   task_name: str = "FFmpeg",
                   job_id: Optional[str] = None) -> bool:
        """
        Führt FFmpeg-Befehl aus mit Progress-Parsing.

        Args:
            command: FFmpeg-Befehl als Liste
            total_duration: Gesamt-Dauer für Progress-Berechnung
            task_name: Name für Progress-Event
            job_id: Optional Job-ID

        Returns:
            True bei Erfolg

        Raises:
            EncodingError: Bei Fehler oder Cancellation
        """
        # TODO: Implementierung (Progress-Loop aus video_preview/processor konsolidieren)
        raise NotImplementedError("_run_ffmpeg noch nicht implementiert")

    def _build_filter_chain(self, spec: VideoSpec) -> str:
        """
        Baut FFmpeg-Filter-Chain für Video-Standardisierung.

        Args:
            spec: VideoSpec mit Ziel-Parametern

        Returns:
            Filter-Chain als String
        """
        filters = [
            f"scale={spec.target_width}:{spec.target_height}:force_original_aspect_ratio=decrease:flags=fast_bilinear",
            f"pad={spec.target_width}:{spec.target_height}:(ow-iw)/2:(oh-ih)/2:color=black",
            f"fps={spec.target_fps}",
            f"format={spec.pix_fmt}"
        ]
        return ','.join(filters)

    def _resolve_encoder(self, codec: str, prefer_hw: bool = True) -> Dict:
        """
        Gibt Encoder-Parameter zurück (Hardware oder Software).

        Args:
            codec: Codec-Name ('h264', 'hevc', etc.)
            prefer_hw: Hardware-Beschleunigung bevorzugen

        Returns:
            Dict mit 'input_params', 'output_params', 'encoder'
        """
        if prefer_hw and self.hw_accel_enabled:
            return self.hw_detector.get_encoding_params(codec, enable_hw_accel=True)
        else:
            return self.hw_detector.get_encoding_params(codec, enable_hw_accel=False)

    def _emit_progress(self, event: ProgressEvent) -> None:
        """Sendet Progress-Event an registrierten Callback"""
        if self.on_progress:
            try:
                self.on_progress(event)
            except Exception as e:
                print(f"[Encoder] Fehler in Progress-Callback: {e}")

