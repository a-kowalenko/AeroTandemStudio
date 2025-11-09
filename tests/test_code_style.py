"""
Test-Skript für Code-Stil-Updates und import_from_backup
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_imports():
    """Test ob alle Module korrekt importieren"""
    print("Testing imports...")

    try:
        from src.gui.app import VideoGeneratorApp
        print("✓ VideoGeneratorApp importiert")
    except Exception as e:
        print(f"✗ Fehler beim Import von VideoGeneratorApp: {e}")
        return False

    try:
        from src.utils.media_history import MediaHistoryStore
        print("✓ MediaHistoryStore importiert")
    except Exception as e:
        print(f"✗ Fehler beim Import von MediaHistoryStore: {e}")
        return False

    try:
        from src.gui.components.processed_files_dialog import ProcessedFilesDialog
        print("✓ ProcessedFilesDialog importiert")
    except Exception as e:
        print(f"✗ Fehler beim Import von ProcessedFilesDialog: {e}")
        return False

    return True

def test_method_existence():
    """Test ob wichtige Methoden existieren"""
    print("\nTesting method existence...")

    from src.gui.app import VideoGeneratorApp

    # Check if import_from_backup exists
    if hasattr(VideoGeneratorApp, 'import_from_backup'):
        print("✓ import_from_backup() existiert")
    else:
        print("✗ import_from_backup() fehlt!")
        return False

    # Check if on_sd_backup_complete exists
    if hasattr(VideoGeneratorApp, 'on_sd_backup_complete'):
        print("✓ on_sd_backup_complete() existiert")
    else:
        print("✗ on_sd_backup_complete() fehlt!")
        return False

    # Check if on_settings_saved exists
    if hasattr(VideoGeneratorApp, 'on_settings_saved'):
        print("✓ on_settings_saved() existiert")
    else:
        print("✗ on_settings_saved() fehlt!")
        return False

    # Check if show_settings exists
    if hasattr(VideoGeneratorApp, 'show_settings'):
        print("✓ show_settings() existiert")
    else:
        print("✗ show_settings() fehlt!")
        return False

    return True

def test_docstrings():
    """Test ob Docstrings vorhanden sind"""
    print("\nTesting docstrings...")

    from src.gui.app import VideoGeneratorApp

    # Check import_from_backup docstring
    doc = VideoGeneratorApp.import_from_backup.__doc__
    if doc and len(doc) > 50:
        print(f"✓ import_from_backup() hat ausführlichen Docstring ({len(doc)} Zeichen)")
    else:
        print(f"⚠ import_from_backup() Docstring könnte ausführlicher sein")

    # Check on_sd_backup_complete docstring
    doc = VideoGeneratorApp.on_sd_backup_complete.__doc__
    if doc and len(doc) > 50:
        print(f"✓ on_sd_backup_complete() hat ausführlichen Docstring ({len(doc)} Zeichen)")
    else:
        print(f"⚠ on_sd_backup_complete() Docstring könnte ausführlicher sein")

    # Check on_settings_saved docstring
    doc = VideoGeneratorApp.on_settings_saved.__doc__
    if doc and len(doc) > 50:
        print(f"✓ on_settings_saved() hat ausführlichen Docstring ({len(doc)} Zeichen)")
    else:
        print(f"⚠ on_settings_saved() Docstring könnte ausführlicher sein")

    return True

def main():
    """Hauptfunktion"""
    print("=" * 60)
    print("Code-Stil-Update Test Suite")
    print("=" * 60)

    success = True

    # Test 1: Imports
    if not test_imports():
        success = False

    # Test 2: Method Existence
    if not test_method_existence():
        success = False

    # Test 3: Docstrings
    if not test_docstrings():
        success = False

    print("\n" + "=" * 60)
    if success:
        print("✓ Alle Tests erfolgreich!")
        print("=" * 60)
        return 0
    else:
        print("✗ Einige Tests fehlgeschlagen")
        print("=" * 60)
        return 1

if __name__ == "__main__":
    sys.exit(main())

