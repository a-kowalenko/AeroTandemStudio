import os
import shutil
import tempfile
import urllib.request
import zipfile
import platform

# Windows-only imports are guarded when used
try:
    import winreg
    import ctypes
except Exception:
    winreg = None
    ctypes = None

def _add_to_user_path_windows(bin_path, report):
    """Add bin_path to HKCU\Environment Path and broadcast change (best-effort)."""
    if winreg is None:
        report("Skipping PATH update: winreg not available.")
        return

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as key:
            try:
                current = winreg.QueryValueEx(key, "Path")[0]
            except FileNotFoundError:
                current = os.environ.get("PATH", "")
    except Exception:
        current = os.environ.get("PATH", "")

    # Only add if not already present (case-insensitive)
    path_elems = [p for p in current.split(os.pathsep) if p]
    if any(os.path.normcase(bin_path) == os.path.normcase(p) for p in path_elems):
        report(f"`{bin_path}` already in user PATH.")
        # still update current process PATH
        if bin_path not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
        return

    new_path = current + (os.pathsep if current and not current.endswith(os.pathsep) else "") + bin_path
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, new_path)
        # update current process PATH
        os.environ["PATH"] = bin_path + os.pathsep + os.environ.get("PATH", "")
        report(f"Added `{bin_path}` to user PATH.")
        # Broadcast WM_SETTINGCHANGE so other processes see the change (best-effort)
        try:
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None)
        except Exception:
            report("Could not broadcast environment change; PATH will be active for new sessions.")
    except Exception as e:
        report(f"Failed to update user PATH: {e}")

def _add_to_user_path_unix(bin_path, report):
    """Ensure bin_path is added to `~/.profile` or `~/.bashrc` PATH (best-effort)."""
    home = os.path.expanduser("~")
    candidates = [os.path.join(home, ".profile"), os.path.join(home, ".bash_profile"), os.path.join(home, ".bashrc")]
    export_line = f'\n# added by ffmpeg installer\nexport PATH="{bin_path}:$PATH"\n'
    for fname in candidates:
        try:
            if os.path.exists(fname):
                with open(fname, "r", encoding="utf-8") as f:
                    content = f.read()
                if bin_path in content:
                    report(f"`{bin_path}` already present in {fname}.")
                    return
            # append to the first file that exists or to .profile if none exist
            target = fname if os.path.exists(fname) else candidates[0]
            with open(target, "a", encoding="utf-8") as f:
                f.write(export_line)
            report(f"Appended PATH export to `{target}`. New shells will pick it up.")
            return
        except Exception:
            continue
    report("Could not persist PATH to profile files; please add the folder to your PATH manually.")

def ensure_ffmpeg_installed(progress_callback=None, install_dir=None, add_to_user_path=True):
    """
    Ensure FFmpeg is installed. Install into a user-wide location and optionally add to user PATH.
    Returns path to ffmpeg executable on success, raises on failure.
    """
    def report(msg):
        if progress_callback:
            try:
                progress_callback(msg)
            except Exception:
                pass

    report("Checking for existing FFmpeg on PATH...")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        report(f"FFmpeg found: {ffmpeg_path}")
        return ffmpeg_path

    system = platform.system()
    # default install dirs per-platform (user-writable)
    if install_dir is None:
        if system == "Windows":
            install_dir = os.path.join(os.getenv("LOCALAPPDATA") or os.path.expanduser("~"), "ffmpeg")
        elif system == "Darwin":
            install_dir = os.path.join(os.path.expanduser("~"), ".local", "ffmpeg")
        else:
            # Linux / others
            install_dir = os.path.join(os.path.expanduser("~"), ".local", "ffmpeg")

    bin_name = "ffmpeg.exe" if system == "Windows" else "ffmpeg"
    bin_path = os.path.join(install_dir, "bin", bin_name)

    if os.path.exists(bin_path):
        report(f"FFmpeg already present at `{bin_path}`")
        # ensure it's on current PATH for this process
        if os.path.dirname(bin_path) not in os.environ.get("PATH", ""):
            os.environ["PATH"] = os.path.dirname(bin_path) + os.pathsep + os.environ.get("PATH", "")
        return bin_path

    report("FFmpeg not found — downloading and installing to user location...")

    ffmpeg_zip_url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" if system == "Windows" else \
                     "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
    temp_zip = os.path.join(tempfile.gettempdir(), "ffmpeg_download.tmp")

    try:
        report("Downloading FFmpeg...")
        urllib.request.urlretrieve(ffmpeg_zip_url, temp_zip)
        report("Extracting FFmpeg...")
        # create target bin dir
        os.makedirs(os.path.join(install_dir, "bin"), exist_ok=True)

        if ffmpeg_zip_url.endswith(".zip"):
            with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
                zip_ref.extractall(install_dir)
            # try to locate extracted bin folder
            extracted_root = next(
                (os.path.join(install_dir, d) for d in os.listdir(install_dir)
                 if os.path.isdir(os.path.join(install_dir, d)) and "ffmpeg" in d.lower()),
                install_dir
            )
            candidate_bin = os.path.join(extracted_root, "bin")
            if os.path.exists(candidate_bin):
                for item in os.listdir(candidate_bin):
                    src = os.path.join(candidate_bin, item)
                    dst = os.path.join(install_dir, "bin", item)
                    try:
                        shutil.move(src, dst)
                    except Exception:
                        shutil.copy2(src, dst)
        else:
            # handle tar.xz style archives for Linux/macOS
            import tarfile
            with tarfile.open(temp_zip, "r:*") as tar:
                tar.extractall(install_dir)
            extracted_root = next(
                (os.path.join(install_dir, d) for d in os.listdir(install_dir)
                 if os.path.isdir(os.path.join(install_dir, d)) and "ffmpeg" in d.lower()),
                install_dir
            )
            # binary often in extracted_root
            for root, dirs, files in os.walk(extracted_root):
                if bin_name in files:
                    src = os.path.join(root, bin_name)
                    dst = os.path.join(install_dir, "bin", bin_name)
                    shutil.move(src, dst)
                    break

        if not os.path.exists(bin_path):
            raise RuntimeError("FFmpeg binary not found after extraction.")

        # make executable on unix
        if system != "Windows":
            try:
                os.chmod(bin_path, 0o755)
            except Exception:
                pass

        report(f"FFmpeg installed to `{bin_path}`")

        if add_to_user_path:
            if system == "Windows":
                _add_to_user_path_windows(os.path.dirname(bin_path), report)
            else:
                _add_to_user_path_unix(os.path.dirname(bin_path), report)

        return bin_path

    except Exception as e:
        report(f"Error during FFmpeg install: {e}")
        raise