import os
import sys


def _add_windows_pyzbar_dll_dirs() -> None:
    if sys.platform != "win32":
        return
    if not getattr(sys, "frozen", False):
        return

    candidate_dirs = []

    if hasattr(sys, "_MEIPASS"):
        candidate_dirs.append(os.path.join(sys._MEIPASS, "pyzbar"))
        candidate_dirs.append(sys._MEIPASS)

    executable_dir = os.path.dirname(os.path.abspath(sys.executable))
    candidate_dirs.append(os.path.join(executable_dir, "_internal", "pyzbar"))
    candidate_dirs.append(os.path.join(executable_dir, "_internal"))
    candidate_dirs.append(os.path.join(executable_dir, "pyzbar"))
    candidate_dirs.append(executable_dir)

    for directory in candidate_dirs:
        if os.path.isdir(directory):
            try:
                os.add_dll_directory(directory)
            except (FileNotFoundError, OSError):
                # Ignore invalid or inaccessible directories.
                pass


_add_windows_pyzbar_dll_dirs()
