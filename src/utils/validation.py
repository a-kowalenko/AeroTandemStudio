def validate_form_data(form_data, video_path):
    """Validiert die Formulardaten und gibt Fehlermeldungen zurück"""
    errors = []

    required_fields = [
        ("load", "Load Nr"),
        ("gast", "Gast"),
        ("tandemmaster", "Tandemmaster"),
        ("datum", "Datum"),
        ("speicherort", "Speicherort")
    ]

    for field_key, field_name in required_fields:
        if not form_data.get(field_key, "").strip():
            errors.append(f"{field_name} ist erforderlich")

    if not video_path:
        errors.append("Bitte ziehen Sie eine Video-Datei in das Feld")

    if form_data.get("outside_video") and not form_data.get("videospringer", "").strip():
        errors.append("Videospringer ist erforderlich bei Outside Video")

    return errors


def validate_load_number(load):
    """Validiert die Load-Nummer"""
    return load.isdigit()