from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Kunde:
    kunde_id: Optional[int] = None
    vorname: Optional[str] = None
    nachname: Optional[str] = None
    email: Optional[str] = None
    telefon: Optional[str] = None
    handcam_foto: bool = False
    handcam_video: bool = False
    outside_foto: bool = False
    outside_video: bool = False
    ist_bezahlt_handcam_foto: bool = False
    ist_bezahlt_handcam_video: bool = False
    ist_bezahlt_outside_foto: bool = False
    ist_bezahlt_outside_video: bool = False