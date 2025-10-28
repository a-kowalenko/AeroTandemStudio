import os


def validate_form_data(form_data, video_paths):
    """Validiert die Formulardaten und gibt Fehlermeldungen zurück"""
    errors = []

    required_fields = [
        ("load", "Load Nr"),
        ("gast", "Gast"),
        ("tandemmaster", "Tandemmaster"),
        ("datum", "Datum")
    ]

    for field_key, field_name in required_fields:
        if not form_data.get(field_key, "").strip():
            errors.append(f"{field_name} ist erforderlich")

    if form_data.get("outside_video") and not form_data.get("videospringer", "").strip():
        errors.append("Videospringer ist erforderlich bei Outside Video")

    return errors


def validate_load_number(load):
    """Validiert die Load-Nummer"""
    return load.isdigit()


def validate_video_files(video_paths):
    """Validiert die Video-Dateien"""
    errors = []
    for video_path in video_paths:
        if not video_path.lower().endswith('.mp4'):
            errors.append(f"'{video_path}' ist keine .mp4 Datei")
        elif not os.path.exists(video_path):
            errors.append(f"Datei '{video_path}' existiert nicht")

    return errors