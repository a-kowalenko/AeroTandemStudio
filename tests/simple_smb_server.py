"""
Einfacher Windows SMB-Server ohne externe Dependencies
Verwendet native Windows 'net share' Befehle
"""
import os
import subprocess
import tempfile
import shutil


class WindowsSMBShare:
    """
    Windows SMB-Freigabe mit 'net share'
    Benötigt Administrator-Rechte
    """

    def __init__(self, share_name="TestShare", share_path=None):
        self.share_name = share_name
        self.is_running = False

        if share_path is None:
            self.share_path = tempfile.mkdtemp(prefix=f"smb_{share_name}_")
            self.is_temp = True
        else:
            self.share_path = share_path
            os.makedirs(share_path, exist_ok=True)
            self.is_temp = False

        print(f"📁 Share-Verzeichnis: {self.share_path}")

    def is_admin(self):
        """Prüft ob mit Admin-Rechten gestartet"""
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            return False

    def start(self, retry=True):
        """Erstellt Windows SMB-Freigabe"""
        if not self.is_admin():
            print("❌ Administrator-Rechte erforderlich!")
            return False

        try:
            # Prüfe zuerst ob Share bereits existiert
            check_result = subprocess.run(
                f'net share {self.share_name}',
                capture_output=True,
                text=True,
                shell=True
            )

            if check_result.returncode == 0:
                # Share existiert bereits
                if retry:
                    print(f"ℹ️  Freigabe '{self.share_name}' existiert bereits, entferne sie...")
                    self._remove_share_silent()
                    # Versuche nochmal
                    return self.start(retry=False)
                else:
                    print(f"❌ Freigabe '{self.share_name}' existiert bereits und konnte nicht entfernt werden")
                    return False

            # Share existiert nicht, erstelle sie
            print(f"🚀 Erstelle Windows-Freigabe '{self.share_name}'...")

            # Erstelle Share mit net share (einfacher Befehl)
            cmd = f'net share {self.share_name}="{self.share_path}"'

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=True
            )

            if result.returncode == 0 or "erfolgreich" in result.stdout.lower() or "successfully" in result.stdout.lower():
                # Freigabe wurde erstellt, jetzt Berechtigungen setzen
                print(f"✅ Freigabe erstellt, setze Berechtigungen...")

                username = os.environ.get('USERNAME', 'DefaultUser')
                computername = os.environ.get('COMPUTERNAME', 'localhost')

                # OPTIMIERTE REIHENFOLGE: Zuerst die zuverlässigsten Methoden!

                # 1. COMPUTERNAME\Username (am zuverlässigsten für aktuellen Benutzer)
                print(f"[1/4] Setze NTFS-Berechtigungen für {computername}\\{username}...")
                domain_user = f"{computername}\\{username}"
                user_cmd = f'icacls "{self.share_path}" /grant "{domain_user}:(OI)(CI)F" /Q'

                user_result = subprocess.run(
                    user_cmd,
                    capture_output=True,
                    text=True,
                    shell=True,
                    timeout=10
                )

                if user_result.returncode == 0:
                    print(f"      ✅ OK")
                else:
                    print(f"      ⚠️  Fehler: {user_result.stderr.strip()[:50]}")

                # 2. Jeder/Everyone (am zuverlässigsten für alle Benutzer)
                print(f"[2/4] Setze NTFS-Berechtigungen für Jeder/Everyone...")
                everyone_set = False
                for everyone_name in ["Jeder", "Everyone"]:
                    everyone_cmd = f'icacls "{self.share_path}" /grant "{everyone_name}:(OI)(CI)F" /Q'

                    everyone_result = subprocess.run(
                        everyone_cmd,
                        capture_output=True,
                        text=True,
                        shell=True,
                        timeout=10
                    )

                    if everyone_result.returncode == 0:
                        print(f"      ✅ OK ({everyone_name})")
                        everyone_set = True
                        break

                if not everyone_set:
                    print(f"      ⚠️  Fehler")

                # 3. Share-Berechtigungen für Jeder/Everyone
                print(f"[3/4] Setze Share-Berechtigungen...")
                share_set = False
                for share_everyone in ["Jeder", "Everyone"]:
                    grant_cmd = f'net share {self.share_name} /GRANT:"{share_everyone}",FULL'

                    grant_result = subprocess.run(
                        grant_cmd,
                        capture_output=True,
                        text=True,
                        shell=True,
                        timeout=10
                    )

                    if grant_result.returncode == 0:
                        print(f"      ✅ OK ({share_everyone})")
                        share_set = True
                        break

                if not share_set:
                    # Versuche mit COMPUTERNAME\Username
                    grant_cmd = f'net share {self.share_name} /GRANT:"{domain_user}",FULL'
                    grant_result = subprocess.run(
                        grant_cmd,
                        capture_output=True,
                        text=True,
                        shell=True,
                        timeout=10
                    )
                    if grant_result.returncode == 0:
                        print(f"      ✅ OK ({domain_user})")
                    else:
                        print(f"      ⚠️  Fehler")

                # 4. Schreibtest
                print(f"[4/4] Teste Schreibrechte...")
                test_file = os.path.join(self.share_path, ".write_test")
                try:
                    with open(test_file, 'w') as f:
                        f.write("test")
                    os.remove(test_file)
                    print(f"      ✅ OK - Schreibrechte funktionieren!")
                except Exception as write_error:
                    print(f"      ❌ FEHLER: {str(write_error)}")
                    print(f"      Upload wird fehlschlagen!")

                self.is_running = True

                print(f"\n✅ Share bereit!")
                print(f"   UNC: \\\\localhost\\{self.share_name}")
                print(f"   UNC: \\\\{os.environ.get('COMPUTERNAME', 'PC')}\\{self.share_name}")
                return True
            else:

                print(f"❌ Fehler beim Erstellen der Freigabe:")
                print(f"   Return Code: {result.returncode}")
                print(f"   Output: {result.stdout}")
                print(f"   Error: {result.stderr}")
                return False

        except Exception as e:
            print(f"❌ Fehler: {e}")
            return False

    def _remove_share_silent(self):
        """Entfernt Share ohne Ausgabe"""
        try:
            # /Y für automatische Bestätigung
            result = subprocess.run(
                f'net share {self.share_name} /DELETE /Y',
                capture_output=True,
                shell=True,
                text=True,
                timeout=10
            )
            # Warte kurz damit Windows die Freigabe wirklich entfernt
            import time
            time.sleep(0.5)
            return result.returncode == 0
        except Exception:
            return False

    def stop(self):
        """Entfernt Windows SMB-Freigabe"""
        if self.is_running:
            print(f"🛑 Entferne Freigabe '{self.share_name}'...")
            try:
                result = subprocess.run(
                    f'net share {self.share_name} /DELETE /Y',
                    capture_output=True,
                    text=True,
                    shell=True,
                    timeout=10
                )

                if result.returncode == 0:
                    print("✅ Freigabe entfernt")
                    self.is_running = False
                    return True
                else:
                    print(f"⚠️  Freigabe konnte nicht entfernt werden: {result.stderr}")
                    self.is_running = False
                    return False
            except Exception as e:
                print(f"⚠️  Fehler beim Entfernen: {e}")
                self.is_running = False
                return False

    def cleanup(self):
        """Räumt auf"""
        self.stop()
        if self.is_temp and os.path.exists(self.share_path):
            try:
                shutil.rmtree(self.share_path)
                print(f"🗑️  Verzeichnis gelöscht")
            except Exception as e:
                print(f"⚠️  Konnte Verzeichnis nicht löschen: {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


class SimpleSMBMock:
    """
    Einfacher Mock-Server - lokales Verzeichnis statt echtem SMB
    Perfekt für Tests ohne Admin-Rechte
    """

    def __init__(self, share_name="TestShare", share_path=None):
        self.share_name = share_name

        if share_path is None:
            self.share_path = tempfile.mkdtemp(prefix=f"mock_{share_name}_")
            self.is_temp = True
        else:
            self.share_path = share_path
            os.makedirs(share_path, exist_ok=True)
            self.is_temp = False

    def start(self):
        """Mock-Start"""
        print(f"📁 Mock SMB-Share erstellt")
        print(f"   Name: {self.share_name}")
        print(f"   Pfad: {self.share_path}")
        print(f"💡 Dies ist ein Mock - kein echter SMB-Server")
        return True

    def stop(self):
        """Mock-Stop"""
        pass

    def cleanup(self):
        """Räumt Mock-Verzeichnis auf"""
        if self.is_temp and os.path.exists(self.share_path):
            try:
                shutil.rmtree(self.share_path)
                print(f"🗑️  Mock-Verzeichnis gelöscht")
            except Exception as e:
                print(f"Fehler beim Löschen des Mock-Verzeichnisses: {e}")

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()

