import os
import re
from src.utils.constants import REGEX_EMAIL, REGEX_PHONE


def validate_form_data(form_data, video_paths):
    """Validiert die Formulardaten und gibt Fehlermeldungen zurück"""
    errors = []

    required_fields = [
        ("gast", "Gast"),
        ("tandemmaster", "Tandemmaster"),
        ("datum", "Datum"),
    ]

    email_required = form_data.get("form_mode") != "kunde" or bool(form_data.get("email", "").strip())
    if email_required:
        required_fields.append(("email", "Email"))

    for field_key, field_name in required_fields:
        if not form_data.get(field_key, "").strip():
            errors.append(f"{field_name} ist erforderlich")

    email = form_data.get("email", "").strip()
    if email and not re.match(REGEX_EMAIL, email):
        errors.append("Ungültige E-Mail-Adresse")

    telefon = form_data.get("telefon", "").strip()
    if telefon and not re.match(REGEX_PHONE, telefon):
        errors.append("Ungültige Telefonnummer")

    if form_data.get("outside_video") and not form_data.get("videospringer", "").strip():
        errors.append("Videospringer ist erforderlich bei Outside Video")

    return errors
def validate_video_files(video_paths):
    """Validiert die Video-Dateien"""
    errors = []
    for video_path in video_paths:
        if not video_path.lower().endswith('.mp4'):
            errors.append(f"'{video_path}' ist keine .mp4 Datei")
        elif not os.path.exists(video_path):
            errors.append(f"Datei '{video_path}' existiert nicht")

    return errors