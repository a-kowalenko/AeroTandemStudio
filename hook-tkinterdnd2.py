"""PyInstaller hook for tkinterdnd2 (Drag & Drop native libraries)."""

from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("tkinterdnd2")
