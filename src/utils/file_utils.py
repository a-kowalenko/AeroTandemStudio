import os

def sanitize_filename(filename):
    """Entfernt ungültige Zeichen aus einem potenziellen Dateinamen."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '')
    return filename.strip()

def ensure_directory_exists(directory):
    """Stellt sicher, dass ein Verzeichnis existiert"""
    if not os.path.exists(directory):
        os.makedirs(directory)
    return directory