import cv2
import json
from pyzbar.pyzbar import decode
from typing import Optional, Tuple

from src.model.kunde import Kunde


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

    return Kunde(
        kunde_id=str(daten_dict['hashid']),
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


def analysiere_ersten_clip(video_pfad: str) -> Tuple[Optional[Kunde], bool]:
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
        # Lade das Bild mit OpenCV
        image = cv2.imread(foto_pfad)

        if image is None:
            print(f"Fehler: Foto konnte nicht geladen werden: {foto_pfad}")
            return None, False

        # Finde und dekodiere QR-Codes im Bild
        gefundene_codes = decode(image)

        if not gefundene_codes:
            print(f"Kein QR-Code im Foto gefunden: {foto_pfad}")
            return None, False

        # Versuche den ersten gefundenen Code zu parsen
        for code in gefundene_codes:
            try:
                # Dekodiere die Daten (sind Bytes) in einen String
                qr_daten_str = code.data.decode('utf-8')
                kunden_obj = _parse_kunde_aus_qr_string(qr_daten_str)

                # Erfolgreich gefunden UND geparst!
                print(f"QR-Code im Foto gefunden und erfolgreich geparst: {foto_pfad}")
                return kunden_obj, True

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                # Der QR-Code wurde gefunden, aber die Daten waren ungültig
                print(f"QR-Code im Foto gefunden, aber Parsing fehlgeschlagen: {e}")
                # Versuche nächsten Code falls mehrere vorhanden
                continue

        # Alle gefundenen Codes waren ungültig
        print(f"QR-Code(s) gefunden, aber keine gültigen Kundendaten im Foto: {foto_pfad}")
        return None, False

    except Exception as e:
        print(f"Ein unerwarteter Fehler beim Analysieren des Fotos ist aufgetreten: {e}")
        return None, False

