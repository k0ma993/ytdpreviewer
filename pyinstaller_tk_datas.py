"""Shared Tcl/Tk bundling for PyInstaller (setup.exe + YTDPreviewer.exe)."""

from __future__ import annotations

import sys
from pathlib import Path


def tkinter_datas_and_binaries() -> tuple[list, list]:
    datas: list = []
    binaries: list = []
    if sys.platform != "win32":
        return datas, binaries

    py_root = Path(sys.base_prefix)
    tcl_dir = py_root / "tcl"
    if tcl_dir.is_dir():
        datas.append((str(tcl_dir), "_tcl_data"))

    dll_dir = py_root / "DLLs"
    if dll_dir.is_dir():
        for pattern in ("tcl*.dll", "tk*.dll"):
            for dll_path in sorted(dll_dir.glob(pattern)):
                binaries.append((str(dll_path), "."))

    return datas, binaries
