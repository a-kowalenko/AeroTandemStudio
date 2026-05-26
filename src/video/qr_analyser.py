import json
import os
from typing import Callable, Optional, Tuple

from pyzbar.pyzbar import decode

from src.model.kunde import Kunde

_MAX_QR_DECODE_WIDTH = 1920

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


def analysiere_ersten_clip(
    video_pfad: str,
    *,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[Optional[Kunde], bool]:
    """
    Analysiert die ersten 5 Sekunden eines Videoclips auf einen QR-Code,
    parst diesen in das Kunde-Modell und gibt das Modell sowie einen Erfolgsstatus zurück.

    Args:
        video_pfad (str): Der Dateipfad zum Videoclip.

    Returns:
        Tuple[Optional[Kunde], bool]: Ein Tupel, bestehend aus dem
                                            geparsten Datenobjekt (oder None) und einem
                                            booleschen Erfolgsstatus.
    """

    if cv2 is None:
        print("Fehler: OpenCV (cv2) ist nicht installiert. Bitte 'opencv-python' installieren.")
        return None, False

    cap = cv2.VideoCapture(video_pfad)
    if not cap.isOpened():
        print(f"Fehler: Videodatei konnte nicht geöffnet werden: {video_pfad}")
        return None, False

    try:
        # Erhalte die FPS (Frames pro Sekunde) des Videos
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps == 0:
            print("Warnung: FPS ist 0, setze auf Standard 30.")
            fps = 30  # Setze einen Standardwert, falls FPS nicht gelesen werden kann

        # Berechne die Gesamtanzahl der zu scannenden Frames (für 5 Sekunden)
        frames_limit = int(fps * 5)

        frame_zaehler = 0

        while frame_zaehler < frames_limit:
            if _is_cancelled(cancel_check):
                print("QR-Analyse des Clips vom Benutzer abgebrochen.")
                cap.release()
                return None, False

            erfolg, frame = cap.read()

            # Wenn kein Frame mehr gelesen werden kann (z.B. Video kürzer als 5 Sek.)
            if not erfolg:
                break

            # --- Effizienz-Optimierung ---
            # Wir müssen nicht JEDEN Frame scannen. Das ist sehr rechenintensiv.
            # Ein QR-Code ist normalerweise für mehrere Frames sichtbar.
            # Wir scannen z.B. nur jeden 5. Frame.
            if frame_zaehler % 5 == 0:
                # Finde und dekodiere QR-Codes im aktuellen Frame
                gefundene_codes = decode(frame)

                for code in gefundene_codes:
                    # Sobald wir einen Code finden, versuchen wir ihn zu parsen
                    try:
                        # Dekodiere die Daten (sind Bytes) in einen String
                        qr_daten_str = code.data.decode('utf-8')
                        kunden_obj = _parse_kunde_aus_qr_string(qr_daten_str)

                        # Erfolgreich gefunden UND geparst!
                        # Wir können die Schleife sofort verlassen (effizient).
                        print(f"QR-Code bei Frame {frame_zaehler} gefunden und erfolgreich geparst.")
                        cap.release()
                        return kunden_obj, True

                    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                        # Der QR-Code wurde gefunden, aber die Daten waren ungültig
                        # (z.B. kein JSON, falsche Felder, falscher Datentyp)
                        print(f"QR-Code bei Frame {frame_zaehler} gefunden, aber Parsing fehlgeschlagen: {e}")
                        # Wir machen weiter und suchen nach einem *gültigen* Code

            frame_zaehler += 1

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        cap.release()
        return None, False

    # Schleife beendet, ohne einen gültigen Code zu finden
    print("Analyse der ersten 5 Sekunden beendet. Keinen gültigen QR-Code gefunden.")
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
    gefundene_codes = decode(image)
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

        if not decode(image):
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
        (Kunde oder None, Erfolg, Pfad des Treffer-Fotos oder None)
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
) -> Tuple[Optional[Kunde], bool, Optional[str], bool]:
    """
    Durchsucht Videoclips der Reihe nach (je erste 5 s) auf einen gültigen QR-Code.
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

        if progress_callback:
            progress_callback(index, total, os.path.basename(video_pfad))

        kunde, ok = analysiere_ersten_clip(video_pfad, cancel_check=cancel_check)
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

