from dataclasses import dataclass


@dataclass
class Kunde:
    kunde_id: int
    vorname: str
    nachname: str
    email: str
    telefon: str
    foto: bool
    video: bool