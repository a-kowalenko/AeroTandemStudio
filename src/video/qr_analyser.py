import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from pyzbar.pyzbar import decode

from src.model.kunde import Kunde

_MAX_QR_DECODE_WIDTH = 1920
_MAX_QR_VIDEO_DECODE_WIDTH = 1280
DEFAULT_QR_VIDEO_SCAN_SECONDS = 5.0
DEFAULT_QR_VIDEO_FRAME_STEP = 10

try:
    import cv2
except ImportError:
    cv2 = None


def _parse_kunde_aus_qr_string(qr_daten_str: str) -> Kunde:
    """
    Parst den QR-Inhalt in ein Kunde-Objekt.
    Erwartet das neue Format als URL mit JSON-Fragment nach '#'.
    """
    payload_str = qr_daten_str.strip()
    if '#' in payload_str:
        payload_str = payload_str.split('#', 1)[1]

    daten_dict = json.loads(payload_str)

    media_code = str(daten_dict.get('media', 'none'))
    media_mapping = {
        'none': (False, False, False, False),
        'hc_f': (True, False, False, False),
        'hc_v': (False, True, False, False),
        'hc_fv': (True, True, False, False),
        'ou_f': (False, False, True, False),
        'ou_v': (False, False, False, True),
        'ou_fv': (False, False, True, True),
    }

    if media_code not in media_mapping:
        raise ValueError(f"Unbekannter media-Code: {media_code}")

    handcam_foto, handcam_video, outside_foto, outside_video = media_mapping[media_code]

    kunde_id = daten_dict.get('Customer_ID', daten_dict.get('customer_id', daten_dict.get('hashid')))
    if not kunde_id:
        raise KeyError("Customer_ID")

    booking_id = daten_dict.get('Booking_ID', daten_dict.get('booking_id'))

    kunden_id_hash_str = str(kunde_id)
    booking_id_hash_str = str(booking_id) if booking_id is not None else None

    return Kunde(
        kunden_id_hash=kunden_id_hash_str,
        booking_id_hash=booking_id_hash_str,
        email=None,
        vorname=str(daten_dict['vorname']),
        nachname=str(daten_dict['nachname']),
        telefon=None,
        handcam_foto=handcam_foto,
        handcam_video=handcam_video,
        outside_foto=outside_foto,
        outside_video=outside_video,
        ist_bezahlt_handcam_foto=handcam_foto,
        ist_bezahlt_handcam_video=handcam_video,
        ist_bezahlt_outside_foto=outside_foto,
        ist_bezahlt_outside_video=outside_video,
    )


def _is_cancelled(cancel_check: Optional[Callable[[], bool]]) -> bool:
    return cancel_check is not None and cancel_check()


def _emit_video_qr_progress(
    progress_callback: Optional[Callable[..., None]],
    clip_index: int,
    total: int,
    basename: str,
    *,
    phase: str = "scanning",
    active_basenames: Optional[List[str]] = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        clip_index,
        total,
        basename,
        phase=phase,
        active_basenames=active_basenames or [],
    )


class _ParallelClipProgressTracker:
    """Thread-sichere Liste der gerade parallel geprüften Clips."""

    def __init__(
        self,
        progress_callback: Optional[Callable[..., None]],
        total: int,
    ):
        self._progress_callback = progress_callback
        self._total = total
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}

    def clip_started(self, clip_index: int, basename: str) -> None:
        with self._lock:
            self._active[basename] = clip_index
            active = sorted(self._active.keys())
        _emit_video_qr_progress(
            self._progress_callback,
            clip_index,
            self._total,
            basename,
            phase="parallel",
            active_basenames=active,
        )

    def clip_finished(self, clip_index: int, basename: str) -> None:
        with self._lock:
            self._active.pop(basename, None)
            active = sorted(self._active.keys())
        if not active:
            return
        first_name = active[0]
        first_index = self._active.get(first_name, clip_index)
        _emit_video_qr_progress(
            self._progress_callback,
            first_index,
            self._total,
            first_name,
            phase="parallel",
            active_basenames=active,
        )


def _prepare_frame_for_qr(frame):
    """Verkleinert und konvertiert einen Frame für schnellere pyzbar-Erkennung."""
    height, width = frame.shape[:2]
    if width > _MAX_QR_VIDEO_DECODE_WIDTH:
        scale = _MAX_QR_VIDEO_DECODE_WIDTH / width
        new_width = _MAX_QR_VIDEO_DECODE_WIDTH
        new_height = max(1, int(height * scale))
        frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_AREA)

    if len(frame.shape) == 3:
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return frame


def _decode_kunde_from_prepared(prepared_frame) -> Tuple[Optional[Kunde], bool]:
    """Dekodiert QR-Codes in einem vorbereiteten Graustufen-Frame."""
    gefundene_codes = decode(prepared_frame)
    if not gefundene_codes:
        return None, False

    for code in gefundene_codes:
        try:
            qr_daten_str = code.data.decode('utf-8')
            kunden_obj = _parse_kunde_aus_qr_string(qr_daten_str)
            return kunden_obj, True
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            print(f"QR-Code gefunden, aber Parsing fehlgeschlagen: {e}")
            continue

    return None, False


def _target_frame_indices(fps: float, scan_seconds: float, frame_step: int) -> List[int]:
    """Frame-Indizes für die QR-Suche (Frame 0 immer enthalten)."""
    frames_limit = max(1, int(fps * scan_seconds))
    step = max(1, frame_step)
    indices: List[int] = []
    seen = set()
    for frame_index in range(0, frames_limit, step):
        if frame_index not in seen:
            seen.add(frame_index)
            indices.append(frame_index)
    return indices


def _try_decode_frame(frame) -> Tuple[Optional[Kunde], bool]:
    prepared = _prepare_frame_for_qr(frame)
    return _decode_kunde_from_prepared(prepared)


def _scan_target_frames_with_seek(
    cap,
    target_frames: List[int],
    cancel_check: Optional[Callable[[], bool]],
) -> Tuple[Optional[Kunde], bool, int]:
    """Liest Ziel-Frames per Seek. Gibt (Kunde, Erfolg, Anzahl gelesener Frames) zurück."""
    frames_read = 0
    for frame_index in target_frames:
        if _is_cancelled(cancel_check):
            return None, False, frames_read

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        erfolg, frame = cap.read()
        if not erfolg:
            continue

        frames_read += 1
        kunde, ok = _try_decode_frame(frame)
        if ok and kunde:
            print(f"QR-Code bei Frame {frame_index} gefunden und erfolgreich geparst.")
            return kunde, True, frames_read

    return None, False, frames_read


def _scan_sequential_frames(
    cap,
    fps: float,
    scan_seconds: float,
    frame_step: int,
    cancel_check: Optional[Callable[[], bool]],
) -> Tuple[Optional[Kunde], bool]:
    """Fallback: sequentielles Lesen mit Frame-Abstand (ohne Seek)."""
    frames_limit = max(1, int(fps * scan_seconds))
    step = max(1, frame_step)
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    for frame_zaehler in range(frames_limit):
        if _is_cancelled(cancel_check):
            return None, False

        erfolg, frame = cap.read()
        if not erfolg:
            break

        if frame_zaehler % step == 0:
            kunde, ok = _try_decode_frame(frame)
            if ok and kunde:
                print(
                    f"QR-Code bei Frame {frame_zaehler} gefunden "
                    "(sequentieller Fallback)."
                )
                return kunde, True

    return None, False


def analysiere_ersten_clip(
    video_pfad: str,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
    clip_index: Optional[int] = None,
    total_clips: Optional[int] = None,
    progress_callback: Optional[Callable[..., None]] = None,
) -> Tuple[Optional[Kunde], bool]:
    """
    Analysiert die ersten scan_seconds Sekunden eines Videoclips auf einen QR-Code.
    Liest nur ausgewählte Frames (Seek), verkleinert und konvertiert vor pyzbar.

    Args:
        video_pfad: Dateipfad zum Videoclip.
        scan_seconds: Zeitfenster ab Clip-Anfang in Sekunden.
        frame_step: Nur jeden N-ten Frame prüfen.

    Returns:
        (Kunde oder None, Erfolg)
    """

    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False

    if not os.path.isfile(video_pfad):
        print(f"Fehler: Videodatei existiert nicht: {video_pfad}")
        return None, False

    basename = os.path.basename(video_pfad)
    if progress_callback and clip_index is not None and total_clips is not None:
        _emit_video_qr_progress(
            progress_callback,
            clip_index,
            total_clips,
            basename,
            phase="scanning",
        )

    cap = cv2.VideoCapture(video_pfad)
    if not cap.isOpened():
        print(f"Fehler: Videodatei konnte nicht geöffnet werden: {video_pfad}")
        return None, False

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            print("Warnung: FPS ist 0, setze auf Standard 30.")
            fps = 30.0

        scan_seconds = max(0.5, float(scan_seconds))
        target_frames = _target_frame_indices(fps, scan_seconds, frame_step)

        kunde, ok, frames_read = _scan_target_frames_with_seek(
            cap, target_frames, cancel_check
        )
        if _is_cancelled(cancel_check):
            print("QR-Analyse des Clips vom Benutzer abgebrochen.")
            cap.release()
            return None, False
        if ok and kunde:
            cap.release()
            return kunde, True

        if frames_read == 0:
            print(
                f"Seek lieferte keine Frames für {basename}, "
                "nutze sequentiellen Fallback."
            )
            kunde, ok = _scan_sequential_frames(
                cap, fps, scan_seconds, frame_step, cancel_check
            )
            if _is_cancelled(cancel_check):
                print("QR-Analyse des Clips vom Benutzer abgebrochen.")
                cap.release()
                return None, False
            if ok and kunde:
                cap.release()
                return kunde, True

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        cap.release()
        return None, False

    print(
        f"Analyse der ersten {scan_seconds:g} Sekunden beendet. "
        "Keinen gültigen QR-Code gefunden."
    )
    cap.release()
    return None, False


def _load_image_for_qr(foto_pfad: str):
    """Lädt ein Foto und verkleinert es für die QR-Erkennung bei Bedarf."""
    if cv2 is None:
        return None

    image = cv2.imread(foto_pfad)
    if image is None:
        return None

    height, width = image.shape[:2]
    if width > _MAX_QR_DECODE_WIDTH:
        scale = _MAX_QR_DECODE_WIDTH / width
        new_width = _MAX_QR_DECODE_WIDTH
        new_height = max(1, int(height * scale))
        image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)

    return image


def _decode_kunde_from_image(image) -> Tuple[Optional[Kunde], bool]:
    """Dekodiert QR-Codes in einem OpenCV-Bild und parst den ersten gültigen Kunden."""
    prepared = _prepare_frame_for_qr(image) if len(image.shape) == 3 else image
    return _decode_kunde_from_prepared(prepared)


def analysiere_foto(foto_pfad: str) -> Tuple[Optional[Kunde], bool]:
    """
    Analysiert ein Foto auf einen QR-Code, parst diesen in das Kunde-Modell
    und gibt das Modell sowie einen Erfolgsstatus zurück.

    Args:
        foto_pfad (str): Der Dateipfad zum Foto.

    Returns:
        Tuple[Optional[Kunde], bool]: Ein Tupel, bestehend aus dem
                                            geparsten Datenobjekt (oder None) und einem
                                            booleschen Erfolgsstatus.
    """
    try:
        if cv2 is None:
            print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
            return None, False

        image = _load_image_for_qr(foto_pfad)
        if image is None:
            print(f"Fehler: Foto konnte nicht geladen werden: {foto_pfad}")
            return None, False

        kunde, ok = _decode_kunde_from_image(image)
        if ok and kunde:
            print(f"QR-Code im Foto gefunden und erfolgreich geparst: {foto_pfad}")
            return kunde, True

        prepared = _prepare_frame_for_qr(image)
        if not decode(prepared):
            print(f"Kein QR-Code im Foto gefunden: {foto_pfad}")
        else:
            print(f"QR-Code(s) gefunden, aber keine gültigen Kundendaten im Foto: {foto_pfad}")
        return None, False

    except Exception as e:
        print(f"Ein unerwarteter Fehler beim Analysieren des Fotos ist aufgetreten: {e}")
        return None, False


def analysiere_fotos_bis_erster_treffer(
    foto_pfade: list[str],
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Durchsucht Fotos der Reihe nach auf einen gültigen QR-Code.
    Bricht beim ersten erfolgreichen Treffer ab.

    Returns:
        (Kunde oder None, Erfolg, Pfad des Treffer-Fotos oder None, abgebrochen)
    """
    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False, None, False

    total = len(foto_pfade)
    for index, foto_pfad in enumerate(foto_pfade, start=1):
        if _is_cancelled(cancel_check):
            print("Foto-QR-Suche vom Benutzer abgebrochen.")
            return None, False, None, True

        if progress_callback:
            progress_callback(index, total, os.path.basename(foto_pfad))

        image = _load_image_for_qr(foto_pfad)
        if image is None:
            print(f"Fehler: Foto konnte nicht geladen werden: {foto_pfad}")
            continue

        if _is_cancelled(cancel_check):
            print("Foto-QR-Suche vom Benutzer abgebrochen.")
            return None, False, None, True

        kunde, ok = _decode_kunde_from_image(image)
        if ok and kunde:
            print(
                f"QR-Code in Foto {index}/{total} gefunden und geparst: "
                f"{os.path.basename(foto_pfad)}"
            )
            return kunde, True, foto_pfad, False

    print(f"Kein gültiger QR-Code in {total} Foto(s) gefunden.")
    return None, False, None, False


def analysiere_videos_bis_erster_treffer(
    video_pfade: list[str],
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Durchsucht Videoclips der Reihe nach (je erste scan_seconds) auf einen gültigen QR-Code.
    Bricht beim ersten erfolgreichen Treffer oder bei Benutzer-Abbruch ab.

    Returns:
        (Kunde oder None, Erfolg, Pfad des Treffer-Clips oder None, vom Benutzer abgebrochen)
    """
    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False, None, False

    total = len(video_pfade)
    for index, video_pfad in enumerate(video_pfade, start=1):
        if _is_cancelled(cancel_check):
            print("Video-QR-Suche vom Benutzer abgebrochen.")
            return None, False, None, True

        kunde, ok = analysiere_ersten_clip(
            video_pfad,
            cancel_check=cancel_check,
            scan_seconds=scan_seconds,
            frame_step=frame_step,
            clip_index=index,
            total_clips=total,
            progress_callback=progress_callback,
        )
        if _is_cancelled(cancel_check):
            print("Video-QR-Suche vom Benutzer abgebrochen.")
            return None, False, None, True

        if ok and kunde:
            print(
                f"QR-Code in Clip {index}/{total} gefunden und geparst: "
                f"{os.path.basename(video_pfad)}"
            )
            return kunde, True, video_pfad, False

    print(f"Kein gültiger QR-Code in {total} Clip(s) gefunden.")
    return None, False, None, False


def _scan_clip_for_kunde(
    video_pfad: str,
    clip_index: int,
    total: int,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
    parallel_tracker: Optional[_ParallelClipProgressTracker] = None,
) -> Tuple[int, Optional[Kunde], bool, str]:
    """Hilfsfunktion für parallele Clip-Suche."""
    basename = os.path.basename(video_pfad)
    if parallel_tracker:
        parallel_tracker.clip_started(clip_index, basename)
    try:
        kunde, ok = analysiere_ersten_clip(
            video_pfad,
            cancel_check=cancel_check,
            scan_seconds=scan_seconds,
            frame_step=frame_step,
            clip_index=clip_index,
            total_clips=total,
        )
        return clip_index, kunde, ok, video_pfad
    finally:
        if parallel_tracker:
            parallel_tracker.clip_finished(clip_index, basename)


def analysiere_videos_hybrid_bis_erster_treffer(
    video_pfade: list[str],
    *,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
    parallel_workers: int = 2,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Hybrid B: Clip 1 sequentiell, Clips 2..N parallel (ThreadPool).
    Bricht beim ersten gültigen Treffer oder bei Benutzer-Abbruch ab.
    """
    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False, None, False

    if not video_pfade:
        return None, False, None, False

    total = len(video_pfade)

    kunde, ok = analysiere_ersten_clip(
        video_pfade[0],
        cancel_check=cancel_check,
        scan_seconds=scan_seconds,
        frame_step=frame_step,
        clip_index=1,
        total_clips=total,
        progress_callback=progress_callback,
    )
    if _is_cancelled(cancel_check):
        print("Video-QR-Suche vom Benutzer abgebrochen.")
        return None, False, None, True

    if ok and kunde:
        print(
            f"QR-Code in Clip 1/{total} gefunden und geparst: "
            f"{os.path.basename(video_pfade[0])}"
        )
        return kunde, True, video_pfade[0], False

    if total == 1:
        print("Kein gültiger QR-Code im Clip gefunden.")
        return None, False, None, False

    rest_paths = video_pfade[1:]
    workers = max(1, min(int(parallel_workers), len(rest_paths)))

    print(f"QR-Hybrid: Clips 2–{total} mit {workers} parallelen Worker(n)")

    parallel_tracker = _ParallelClipProgressTracker(progress_callback, total)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for offset, video_pfad in enumerate(rest_paths, start=2):
            if _is_cancelled(cancel_check):
                print("Video-QR-Suche vom Benutzer abgebrochen.")
                return None, False, None, True

            future = executor.submit(
                _scan_clip_for_kunde,
                video_pfad,
                offset,
                total,
                cancel_check=cancel_check,
                scan_seconds=scan_seconds,
                frame_step=frame_step,
                parallel_tracker=parallel_tracker,
            )
            futures[future] = video_pfad

        for future in as_completed(futures):
            if _is_cancelled(cancel_check):
                for pending in futures:
                    pending.cancel()
                print("Video-QR-Suche vom Benutzer abgebrochen.")
                return None, False, None, True

            try:
                clip_index, kunde, ok, source_path = future.result()
            except Exception as e:
                print(f"Fehler bei paralleler Clip-QR-Analyse: {e}")
                continue

            if ok and kunde:
                for pending in futures:
                    pending.cancel()
                print(
                    f"QR-Code in Clip {clip_index}/{total} gefunden und geparst: "
                    f"{os.path.basename(source_path)}"
                )
                return kunde, True, source_path, False

    print(f"Kein gültiger QR-Code in {total} Clip(s) gefunden.")
    return None, False, None, False
