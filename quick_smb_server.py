"""
Quick SMB Tool - Schneller Test, Server starten oder Netzwerkadresse testen
"""
import os
import sys
import tempfile
import time

# Pfad zum Projekt
project_root = os.path.dirname(__file__)
sys.path.insert(0, project_root)

from tests.simple_smb_server import SimpleSMBMock, WindowsSMBShare
from src.utils.file_utils import test_server_connection, upload_to_server_simple
from src.utils.config import ConfigManager


def option_1_quick_test():
    """Option 1: Schneller lokaler Test mit Mock-Server"""
    print("\n" + "=" * 70)
    print("🚀 OPTION 1: SCHNELLER LOKALER TEST")
    print("=" * 70)
    print("\n✅ Kein Administrator nötig")
    print("✅ Perfekt für schnelle Tests\n")

    # Erstelle Mock-Server
    server = SimpleSMBMock(share_name="uploads")
    server.start()

    print("\n" + "=" * 70)
    print("✅ MOCK-SERVER LÄUFT")
    print("=" * 70)

    print(f"\n📍 LOKALE ADRESSE:")
    print(f"   {server.share_path}")

    print(f"\n💡 Kopieren Sie diese Adresse und verwenden Sie sie in:")
    print(f"   - Einstellungen → Server-Adresse")
    print(f"   - config.json → \"server_url\": \"{server.share_path}\"")

    print("\n" + "-" * 70)
    print("⏸️  Drücken Sie STRG+C zum Stoppen")
    print("-" * 70 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stoppe Mock-Server...")
        server.cleanup()
        print("✅ Server gestoppt\n")


def option_2_test_smb_address():
    """Option 2: SMB-Adresse testen (mit oder ohne Credentials)"""
    print("\n" + "=" * 70)
    print("🔍 OPTION 2: SMB-ADRESSE TESTEN")
    print("=" * 70)

    print("\n💡 Geben Sie die SMB-Adresse ein die Sie testen möchten:")
    print("   Beispiele:")
    print("   - smb://169.254.169.254/aktuell")
    print("   - \\\\server\\share")
    print("   - //192.168.1.100/videos")
    print("   - C:\\lokaler\\pfad (für Tests)\n")

    server_url = input("📍 Server-Adresse: ").strip()

    if not server_url:
        print("❌ Keine Adresse eingegeben!")
        return

    print("\n🔐 Credentials erforderlich? (j/n)")
    needs_auth = input("   [n]: ").strip().lower() or "n"

    username = ""
    password = ""

    if needs_auth in ['j', 'y', 'ja', 'yes']:
        print("\n👤 Benutzername:")
        username = input("   ").strip()

        print("🔑 Passwort:")
        password = input("   ").strip()

        print(f"\n✅ Teste mit Credentials: {username}")
    else:
        print("\n✅ Teste ohne Credentials (Gast-Zugriff)")

    # Erstelle temporären Config Manager für Test
    config = ConfigManager()
    original_settings = config.get_settings().copy()

    # Setze Test-Settings
    test_settings = {
        "server_url": server_url,
        "server_login": username,
        "server_password": password
    }
    config.save_settings(test_settings)

    print("\n" + "-" * 70)
    print("🔍 Teste Verbindung...")
    print("-" * 70 + "\n")

    # Teste Verbindung
    success, message = test_server_connection(config)

    if success:
        print("✅ VERBINDUNG ERFOLGREICH!")
        print(f"   {message}\n")
    else:
        print("❌ VERBINDUNG FEHLGESCHLAGEN!")
        print(f"   {message}\n")

        # Spezielle Behandlung für Fehler 1219
        if "1219" in message or "Multiple connections" in message:
            print("⚠️  FEHLER 1219: Mehrfache Verbindungen nicht erlaubt\n")
            print("💡 LÖSUNG:")
            print("   1. Trenne alle Verbindungen: net use * /delete /y")
            print("   2. Oder nutze den Server OHNE Credentials (localhost = bereits angemeldet)")
            print("   3. Für Tests mit Credentials nutze einen ANDEREN Server (nicht localhost)\n")
            print("💡 FÜR LOCALHOST:")
            print("   - Verwende KEINE Credentials (du bist bereits angemeldet)")
            print("   - Der Upload funktioniert mit deinem aktuellen Windows-Benutzer")
        else:
            print("💡 Mögliche Ursachen:")
            print("   - Server nicht erreichbar")
            print("   - Falsche Credentials")
            print("   - Firewall blockiert Verbindung")
            print("   - Falsche Adresse")

    # Stelle Original-Settings wieder her
    config.save_settings(original_settings)

    print("\n" + "-" * 70)
    input("⏸️  Drücken Sie ENTER zum Fortfahren...")


def option_3_upload_test():
    """Option 3: Test-Upload zu SMB-Adresse durchführen"""
    print("\n" + "=" * 70)
    print("📤 OPTION 3: TEST-UPLOAD DURCHFÜHREN")
    print("=" * 70)

    print("\n💡 Geben Sie die SMB-Adresse ein:")
    print("   Beispiele:")
    print("   - smb://169.254.169.254/aktuell")
    print("   - \\\\server\\share")
    print("   - C:\\lokaler\\pfad\n")

    server_url = input("📍 Server-Adresse: ").strip()

    if not server_url:
        print("❌ Keine Adresse eingegeben!")
        return

    print("\n🔐 Credentials erforderlich? (j/n)")
    needs_auth = input("   [n]: ").strip().lower() or "n"

    username = ""
    password = ""

    if needs_auth in ['j', 'y', 'ja', 'yes']:
        print("\n👤 Benutzername:")
        username = input("   ").strip()

        print("🔑 Passwort:")
        password = input("   ").strip()

    # Erstelle Test-Verzeichnis mit Datei
    test_dir = tempfile.mkdtemp(prefix="smb_test_upload_")
    test_file = os.path.join(test_dir, "test.txt")

    with open(test_file, "w") as f:
        f.write(f"SMB Test Upload - {time.strftime('%Y-%m-%d %H:%M:%S')}")

    print(f"\n📁 Test-Verzeichnis erstellt: {test_dir}")
    print(f"   Datei: test.txt")

    print("\n" + "-" * 70)
    print("📤 Starte Upload...")
    print("-" * 70 + "\n")

    # Erstelle temporären Config Manager für Test mit Credentials
    config = ConfigManager()
    original_settings = config.get_settings().copy()

    # Setze Test-Settings
    test_settings = {
        "server_url": server_url,
        "server_login": username,
        "server_password": password
    }
    config.save_settings(test_settings)

    # Führe Upload durch
    try:
        success, message, result_path = upload_to_server_simple(
            test_dir,
            config  # Übergebe ConfigManager mit Credentials!
        )

        if success:
            print("✅ UPLOAD ERFOLGREICH!")
            print(f"   Ziel: {result_path}\n")
        else:
            print("❌ UPLOAD FEHLGESCHLAGEN!")
            print(f"   Fehler: {message}\n")

    except Exception as e:
        print(f"❌ FEHLER: {e}\n")

    # Cleanup: Stelle Original-Settings wieder her
    config.save_settings(original_settings)

    # Cleanup: Lösche Test-Verzeichnis
    import shutil
    try:
        shutil.rmtree(test_dir)
        print("🗑️  Test-Verzeichnis bereinigt")
    except:
        pass

    print("\n" + "-" * 70)
    input("⏸️  Drücken Sie ENTER zum Fortfahren...")


def option_4_start_local_server():
    """Option 4: Lokalen Windows SMB-Server starten (benötigt Admin)"""
    print("\n" + "=" * 70)
    print("🖥️  OPTION 4: WINDOWS SMB-SERVER STARTEN")
    print("=" * 70)
    print("\n⚠️  Benötigt Administrator-Rechte!")

    # Prüfe Admin
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        is_admin = False

    if not is_admin:
        print("\n❌ FEHLER: Nicht als Administrator gestartet!")
        print("\n💡 LÖSUNG:")
        print("   1. PyCharm schließen")
        print("   2. PyCharm mit Rechtsklick → 'Als Administrator ausführen'")
        print("   3. Dieses Skript erneut starten\n")
        input("⏸️  Drücken Sie ENTER zum Fortfahren...")
        return

    print("✅ Administrator-Rechte erkannt\n")

    # Erstelle Share-Verzeichnis
    share_path = tempfile.mkdtemp(prefix="smb_share_")

    server = WindowsSMBShare(
        share_name="uploads",
        share_path=share_path
    )

    if not server.start():
        print("\n❌ Server konnte nicht gestartet werden")
        input("⏸️  Drücken Sie ENTER zum Fortfahren...")
        return

    print("\n" + "=" * 70)
    print("✅ WINDOWS SMB-SERVER LÄUFT")
    print("=" * 70)

    print(f"\n📍 SMB-ADRESSEN:")
    print(f"   smb://localhost/uploads")
    print(f"   \\\\localhost\\uploads")

    print(f"\n📁 LOKALER PFAD:")
    print(f"   {share_path}")

    print(f"\n🔐 CREDENTIALS:")
    print(f"   Username: {os.environ.get('USERNAME', 'Ihr Windows-Benutzer')}")
    print(f"   Password: Ihr Windows-Passwort")

    print("\n" + "-" * 70)
    print("⏸️  Drücken Sie STRG+C zum Stoppen")
    print("-" * 70 + "\n")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Stoppe Server...")
        server.cleanup()
        print("✅ Server gestoppt\n")


def main_menu():
    """Haupt-Menü"""
    while True:
        print("\n" + "=" * 70)
        print("   🚀 QUICK SMB TOOL")
        print("=" * 70)
        print("\nWas möchten Sie tun?\n")

        print("  [1] Schneller lokaler Test")
        print("      ✅ Mock-Server starten (kein Admin)")
        print("      ✅ Lokale Adresse für Tests")
        print()

        print("  [2] SMB-Adresse testen")
        print("      🔍 Verbindung zu smb://... prüfen")
        print("      🔐 Mit oder ohne Credentials")
        print()

        print("  [3] Test-Upload durchführen")
        print("      📤 Upload zu SMB-Adresse testen")
        print("      🔐 Mit oder ohne Credentials")
        print()

        print("  [4] Windows SMB-Server starten")
        print("      🖥️  Echter SMB-Server (benötigt Admin)")
        print("      ✅ Von Netzwerk zugreifbar")
        print()

        print("  [q] Beenden")
        print()

        choice = input("Ihre Wahl: ").strip().lower()

        if choice == "1":
            option_1_quick_test()
        elif choice == "2":
            option_2_test_smb_address()
        elif choice == "3":
            option_3_upload_test()
        elif choice == "4":
            option_4_start_local_server()
        elif choice == "q":
            print("\n👋 Auf Wiedersehen!\n")
            break
        else:
            print("\n❌ Ungültige Wahl!")
            time.sleep(1)


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print("\n\n👋 Programm beendet\n")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Unerwarteter Fehler: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)

