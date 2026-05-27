import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, List, Optional, Tuple

from pyzbar.pyzbar import decode

from src.model.kunde import Kunde
from src.video.qr_parallel_allocator import BidirectionalIndexAllocator

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


def _combined_stop_check(
    cancel_check: Optional[Callable[[], bool]],
    stop_event: Optional[threading.Event] = None,
) -> Callable[[], bool]:
    """Kombiniert Benutzer-Abbruch und frühzeitigen Stopp (z. B. nach QR-Treffer)."""

    def check() -> bool:
        if stop_event is not None and stop_event.is_set():
            return True
        return _is_cancelled(cancel_check)

    return check


def _emit_qr_progress(
    progress_callback: Optional[Callable[..., None]],
    item_index: int,
    total: int,
    basename: str,
    *,
    phase: str = "scanning",
    active_basenames: Optional[List[str]] = None,
    completed_count: Optional[int] = None,
) -> None:
    if progress_callback is None:
        return
    progress_callback(
        item_index,
        total,
        basename,
        phase=phase,
        active_basenames=active_basenames or [],
        completed_count=completed_count,
    )


class _ParallelProgressTracker:
    """Thread-sichere Liste der gerade parallel geprüften Dateien."""

    def __init__(
        self,
        progress_callback: Optional[Callable[..., None]],
        total: int,
        *,
        initial_completed: int = 0,
    ):
        self._progress_callback = progress_callback
        self._total = total
        self._completed = initial_completed
        self._lock = threading.Lock()
        self._active: dict[str, int] = {}

    def _emit(self, item_index: int, basename: str, active: List[str]) -> None:
        _emit_qr_progress(
            self._progress_callback,
            item_index,
            self._total,
            basename,
            phase="parallel",
            active_basenames=active,
            completed_count=self._completed,
        )

    def item_started(self, item_index: int, basename: str) -> None:
        with self._lock:
            self._active[basename] = item_index
            active = sorted(self._active.keys())
        self._emit(item_index, basename, active)

    def item_finished(self, item_index: int, basename: str) -> None:
        with self._lock:
            self._active.pop(basename, None)
            self._completed += 1
            completed = self._completed
            active = sorted(self._active.keys())
            if active:
                first_name = active[0]
                first_index = self._active.get(first_name, item_index)
            else:
                first_name = basename
                first_index = item_index

        if active:
            self._emit(first_index, first_name, active)
        else:
            _emit_qr_progress(
                self._progress_callback,
                item_index,
                self._total,
                basename,
                phase="parallel",
                active_basenames=[],
                completed_count=completed,
            )


def _run_parallel_bidirectional_scan(
    items: List[str],
    *,
    index_offset: int,
    total: int,
    scan_one: Callable[
        [str, int, int, Optional[Callable[[], bool]]],
        Tuple[Optional[Kunde], bool],
    ],
    parallel_workers: int,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[..., None]] = None,
    log_label: str = "Item",
    initial_completed: int = 0,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Parallele bidirektionale Suche über items (0-basiert).
    index_offset: 1-basierter Index von items[0] in der Gesamtliste.
    """
    if not items:
        return None, False, None, False

    workers = max(1, min(int(parallel_workers), len(items)))
    allocator = BidirectionalIndexAllocator(0, len(items) - 1)
    parallel_tracker = _ParallelProgressTracker(
        progress_callback,
        total,
        initial_completed=initial_completed,
    )
    stop_event = threading.Event()
    stop_check = _combined_stop_check(cancel_check, stop_event)

    def _worker(direction: str) -> Tuple[Optional[Kunde], bool, Optional[str]]:
        while True:
            if stop_check():
                return None, False, None

            list_index = (
                allocator.next_backward()
                if direction == "backward"
                else allocator.next_forward()
            )
            if list_index is None:
                return None, False, None

            item_path = items[list_index]
            item_index = index_offset + list_index
            basename = os.path.basename(item_path)

            parallel_tracker.item_started(item_index, basename)
            try:
                kunde, ok = scan_one(item_path, item_index, total, stop_check)
                if ok and kunde:
                    stop_event.set()
                    return kunde, True, item_path
            finally:
                if not stop_event.is_set():
                    parallel_tracker.item_finished(item_index, basename)

        return None, False, None

    executor = ThreadPoolExecutor(max_workers=workers)
    futures = []
    try:
        if workers >= 2:
            futures.append(executor.submit(_worker, "backward"))
            for _ in range(workers - 1):
                futures.append(executor.submit(_worker, "forward"))
        else:
            futures.append(executor.submit(_worker, "forward"))

        for future in as_completed(futures):
            if _is_cancelled(cancel_check):
                stop_event.set()
                for pending in futures:
                    pending.cancel()
                return None, False, None, True

            try:
                kunde, ok, source_path = future.result()
            except Exception as e:
                print(f"Fehler bei paralleler QR-Analyse ({log_label}): {e}")
                continue

            if ok and kunde and source_path:
                stop_event.set()
                for pending in futures:
                    pending.cancel()
                return kunde, True, source_path, False
    finally:
        executor.shutdown(wait=not stop_event.is_set(), cancel_futures=True)

    return None, False, None, False


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
    progress_phase: str = "scanning",
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
        _emit_qr_progress(
            progress_callback,
            clip_index,
            total_clips,
            basename,
            phase=progress_phase,
            completed_count=clip_index - 1,
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
            progress_callback(
                index,
                total,
                os.path.basename(foto_pfad),
                phase="scanning",
                completed_count=index - 1,
            )

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

        if progress_callback:
            progress_callback(
                index,
                total,
                os.path.basename(foto_pfad),
                phase="scanning",
                completed_count=index,
            )

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

        if progress_callback:
            _emit_qr_progress(
                progress_callback,
                index,
                total,
                os.path.basename(video_pfad),
                phase="scanning",
                completed_count=index,
            )

    print(f"Kein gültiger QR-Code in {total} Clip(s) gefunden.")
    return None, False, None, False


def _scan_video_for_kunde(
    video_pfad: str,
    item_index: int,
    total: int,
    cancel_check: Optional[Callable[[], bool]],
    *,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
) -> Tuple[Optional[Kunde], bool]:
    """Scannt einen Videoclip ohne Progress-Callback (für parallele Phase)."""
    return analysiere_ersten_clip(
        video_pfad,
        cancel_check=cancel_check,
        scan_seconds=scan_seconds,
        frame_step=frame_step,
    )


def _scan_foto_for_kunde(
    foto_pfad: str,
    item_index: int,
    total: int,
    cancel_check: Optional[Callable[[], bool]],
) -> Tuple[Optional[Kunde], bool]:
    """Scannt ein Foto ohne Progress-Callback (für parallele Phase)."""
    if _is_cancelled(cancel_check):
        return None, False

    image = _load_image_for_qr(foto_pfad)
    if image is None:
        print(f"Fehler: Foto konnte nicht geladen werden: {foto_pfad}")
        return None, False

    if _is_cancelled(cancel_check):
        return None, False

    return _decode_kunde_from_image(image)


def analysiere_videos_hybrid_bis_erster_treffer(
    video_pfade: list[str],
    *,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    scan_seconds: float = DEFAULT_QR_VIDEO_SCAN_SECONDS,
    frame_step: int = DEFAULT_QR_VIDEO_FRAME_STEP,
    parallel_workers: int = 2,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Hybrid: Clip 1 sequentiell, Clips 2..N parallel bidirektional.
    Bricht beim ersten gültigen Treffer oder bei Benutzer-Abbruch ab.
    """
    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False, None, False

    if not video_pfade:
        return None, False, None, False

    total = len(video_pfade)
    progress_phase = "hybrid_first" if total > 1 else "scanning"

    kunde, ok = analysiere_ersten_clip(
        video_pfade[0],
        cancel_check=cancel_check,
        scan_seconds=scan_seconds,
        frame_step=frame_step,
        clip_index=1,
        total_clips=total,
        progress_callback=progress_callback,
        progress_phase=progress_phase,
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

    print(
        f"QR-Hybrid: Clips 2–{total} mit {workers} parallelen Worker(n) "
        "(bidirektional)"
    )

    if progress_callback:
        _emit_qr_progress(
            progress_callback,
            1,
            total,
            os.path.basename(video_pfade[0]),
            phase="parallel",
            completed_count=1,
        )

    def _scan_one(
        path: str,
        item_index: int,
        item_total: int,
        check: Optional[Callable[[], bool]],
    ) -> Tuple[Optional[Kunde], bool]:
        return _scan_video_for_kunde(
            path,
            item_index,
            item_total,
            check,
            scan_seconds=scan_seconds,
            frame_step=frame_step,
        )

    kunde, ok, source_path, cancelled = _run_parallel_bidirectional_scan(
        rest_paths,
        index_offset=2,
        total=total,
        scan_one=_scan_one,
        parallel_workers=workers,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        log_label="Clip",
        initial_completed=1,
    )
    if cancelled:
        print("Video-QR-Suche vom Benutzer abgebrochen.")
        return None, False, None, True

    if ok and kunde and source_path:
        clip_index = video_pfade.index(source_path) + 1
        print(
            f"QR-Code in Clip {clip_index}/{total} gefunden und geparst: "
            f"{os.path.basename(source_path)}"
        )
        return kunde, True, source_path, False

    print(f"Kein gültiger QR-Code in {total} Clip(s) gefunden.")
    return None, False, None, False


def analysiere_fotos_hybrid_bis_erster_treffer(
    foto_pfade: list[str],
    *,
    progress_callback: Optional[Callable[..., None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
    parallel_workers: int = 2,
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Parallele bidirektionale Foto-Suche über die gesamte Liste.
    Ab 2 Workern: ein Worker startet am Ende, die übrigen am Anfang.
    Bricht beim ersten gültigen Treffer oder bei Benutzer-Abbruch ab.
    """
    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False, None, False

    if not foto_pfade:
        return None, False, None, False

    total = len(foto_pfade)
    workers = max(1, min(int(parallel_workers), total))

    print(
        f"QR-Parallel: {total} Foto(s) mit {workers} Worker(n) (bidirektional)"
    )

    if progress_callback:
        _emit_qr_progress(
            progress_callback,
            1,
            total,
            os.path.basename(foto_pfade[0]),
            phase="parallel",
            completed_count=0,
        )

    kunde, ok, source_path, cancelled = _run_parallel_bidirectional_scan(
        foto_pfade,
        index_offset=1,
        total=total,
        scan_one=_scan_foto_for_kunde,
        parallel_workers=workers,
        cancel_check=cancel_check,
        progress_callback=progress_callback,
        log_label="Foto",
        initial_completed=0,
    )
    if cancelled:
        print("Foto-QR-Suche vom Benutzer abgebrochen.")
        return None, False, None, True

    if ok and kunde and source_path:
        foto_index = foto_pfade.index(source_path) + 1
        print(
            f"QR-Code in Foto {foto_index}/{total} gefunden und geparst: "
            f"{os.path.basename(source_path)}"
        )
        return kunde, True, source_path, False

    print(f"Kein gültiger QR-Code in {total} Foto(s) gefunden.")
    return None, False, None, False
