import cv2
import json
from pyzbar.pyzbar import decode
from dataclasses import dataclass
from typing import Optional, Tuple

from src.model.kunde import Kunde


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

                        # Parse den String (vermutlich JSON) in ein Dictionary
                        daten_dict = json.loads(qr_daten_str)

                        # Versuche, das Dictionary in unser Datenmodell zu parsen
                        # Dies validiert auch, ob alle Felder vorhanden und vom richtigen Typ sind
                        kunden_obj = Kunde(
                            kunde_id=int(daten_dict.get('kunde_id')),
                            email=str(daten_dict.get('email')),
                            vorname=str(daten_dict.get('vorname')),
                            nachname=str(daten_dict.get('nachname')),
                            telefon=str(daten_dict.get('telefon')),
                            handcam_foto=bool(daten_dict.get('handcam_foto')),
                            handcam_video=bool(daten_dict.get('handcam_video')),
                            outside_foto=bool(daten_dict.get('outside_foto')),
                            outside_video=bool(daten_dict.get('outside_video')),
                            ist_bezahlt_handcam_foto=bool(daten_dict.get('ist_bezahlt_handcam_foto')),
                            ist_bezahlt_handcam_video=bool(daten_dict.get('ist_bezahlt_handcam_video')),
                            ist_bezahlt_outside_foto=bool(daten_dict.get('ist_bezahlt_outside_foto')),
                            ist_bezahlt_outside_video=bool(daten_dict.get('ist_bezahlt_outside_video'))
                        )

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
                        pass

            frame_zaehler += 1

    except Exception as e:
        print(f"Ein unerwarteter Fehler ist aufgetreten: {e}")
        cap.release()
        return None, False

    # Schleife beendet, ohne einen gültigen Code zu finden
    print("Analyse der ersten 5 Sekunden beendet. Keinen gültigen QR-Code gefunden.")
    cap.release()
    return None, False
