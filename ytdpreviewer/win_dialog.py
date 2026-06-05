"""Native Windows file and color dialogs."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

RgbColor = tuple[float, float, float]

OFN_EXPLORER = 0x00080000
OFN_FILEMUSTEXIST = 0x00001000
OFN_PATHMUSTEXIST = 0x00000800
OFN_NOCHANGEDIR = 0x00000008
OFN_HIDEREADONLY = 0x00000004
OFN_OVERWRITEPROMPT = 0x00000002


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", wintypes.LPVOID),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", wintypes.LPVOID),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


def _win_pick_open_file(
    title: str,
    initial_dir: str | Path | None,
    parent_hwnd: int | None,
) -> Path | None:
    buffer = ctypes.create_unicode_buffer(65536)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = parent_hwnd or 0
    ofn.lpstrFilter = "YTD (*.ytd)\0*.ytd\0Все файлы (*.*)\0*.*\0\0"
    ofn.nFilterIndex = 1
    ofn.lpstrFile = buffer
    ofn.nMaxFile = len(buffer)
    if initial_dir:
        ofn.lpstrInitialDir = str(Path(initial_dir).resolve())
    ofn.lpstrTitle = title
    ofn.Flags = (
        OFN_EXPLORER
        | OFN_FILEMUSTEXIST
        | OFN_PATHMUSTEXIST
        | OFN_NOCHANGEDIR
        | OFN_HIDEREADONLY
    )
    ofn.lpstrDefExt = "ytd"

    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn)):
        return None
    selected = buffer.value.strip()
    return Path(selected) if selected else None


def _tk_pick_open_file(title: str, initial_dir: str | Path | None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askopenfilename(
        title=title,
        initialdir=str(initial_dir) if initial_dir else None,
        filetypes=[("YTD", "*.ytd"), ("Все файлы", "*.*")],
    )
    root.destroy()
    if not path:
        return None
    return Path(path)


def pick_open_file(
    title: str = "Открыть файл",
    initial_dir: str | Path | None = None,
    parent_hwnd: int | None = None,
) -> Path | None:
    if sys.platform == "win32":
        return _win_pick_open_file(title, initial_dir, parent_hwnd)
    return _tk_pick_open_file(title, initial_dir)


def _tk_pick_folder(title: str, initial_dir: str | Path | None) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.askdirectory(
        title=title,
        initialdir=str(initial_dir) if initial_dir else None,
        mustexist=False,
    )
    root.destroy()
    if not path:
        return None
    return Path(path)


def pick_folder(
    title: str = "Выберите папку",
    initial_dir: str | Path | None = None,
) -> Path | None:
    return _tk_pick_folder(title, initial_dir)


def ask_ytd_batch_layout(file_count: int) -> str | None:
    """Ask how to lay out a multi-file YTD export.

    Returns ``single``, ``separate``, or ``None`` when cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return None

    result: list[str | None] = [None]

    root = tk.Tk()
    root.title("YTD Previewer — экспорт PNG")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    pad = {"padx": 16, "pady": 6}
    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0, sticky="nsew")

    ttk.Label(
        frame,
        text=f"Выбрано файлов YTD: {file_count}",
        font=("Segoe UI", 10, "bold"),
    ).grid(row=0, column=0, columnspan=1, sticky="w", pady=(0, 8))

    ttk.Label(frame, text="Куда сохранить PNG?").grid(row=1, column=0, sticky="w", pady=(0, 12))

    buttons = ttk.Frame(frame)
    buttons.grid(row=2, column=0, sticky="ew")
    buttons.columnconfigure(0, weight=1)

    def choose(value: str | None) -> None:
        result[0] = value
        root.destroy()

    ttk.Button(buttons, text="Все PNG в одну папку", command=lambda: choose("single")).grid(
        row=0, column=0, sticky="ew", **pad
    )
    ttk.Button(buttons, text="Папка для каждого YTD", command=lambda: choose("separate")).grid(
        row=1, column=0, sticky="ew", **pad
    )
    ttk.Button(buttons, text="Отмена", command=lambda: choose(None)).grid(row=2, column=0, sticky="ew", **pad)

    root.update_idletasks()
    w = root.winfo_width()
    h = root.winfo_height()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    root.grab_set()
    root.protocol("WM_DELETE_WINDOW", lambda: choose(None))
    root.mainloop()
    return result[0]


def _win_pick_save_file(
    title: str,
    initial_dir: str | Path | None,
    initial_file: str | None,
    parent_hwnd: int | None,
    file_filter: str,
    def_ext: str,
) -> Path | None:
    buffer = ctypes.create_unicode_buffer(65536)
    if initial_file:
        buffer.value = initial_file
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = parent_hwnd or 0
    ofn.lpstrFilter = file_filter
    ofn.nFilterIndex = 1
    ofn.lpstrFile = buffer
    ofn.nMaxFile = len(buffer)
    if initial_dir:
        ofn.lpstrInitialDir = str(Path(initial_dir).resolve())
    ofn.lpstrTitle = title
    ofn.Flags = OFN_EXPLORER | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR | OFN_HIDEREADONLY | OFN_OVERWRITEPROMPT
    ofn.lpstrDefExt = def_ext

    if not ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn)):
        return None
    selected = buffer.value.strip()
    return Path(selected) if selected else None


def _tk_pick_save_file(
    title: str,
    initial_dir: str | Path | None,
    initial_file: str | None,
    filetypes: list[tuple[str, str]],
    defaultextension: str,
) -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    path = filedialog.asksaveasfilename(
        title=title,
        initialdir=str(initial_dir) if initial_dir else None,
        initialfile=initial_file,
        defaultextension=defaultextension,
        filetypes=filetypes,
    )
    root.destroy()
    if not path:
        return None
    return Path(path)


def pick_save_file(
    title: str = "Сохранить файл",
    initial_dir: str | Path | None = None,
    initial_file: str | None = None,
    parent_hwnd: int | None = None,
    *,
    filetypes: list[tuple[str, str]] | None = None,
    defaultextension: str = "obj",
) -> Path | None:
    types = filetypes or [("Wavefront OBJ", "*.obj"), ("Все файлы", "*.*")]
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if sys.platform != "win32":
            return None
    else:
        return _tk_pick_save_file(title, initial_dir, initial_file, types, defaultextension)

    filter_parts = [f"{label}\0{pattern}\0" for label, pattern in types]
    filter_parts.append("\0")
    return _win_pick_save_file(
        title,
        initial_dir,
        initial_file,
        parent_hwnd,
        "".join(filter_parts),
        defaultextension,
    )


CC_RGBINIT = 0x00000001
CC_FULLOPEN = 0x00000002


class CHOOSECOLORW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("rgbResult", wintypes.COLORREF),
        ("lpCustColors", ctypes.POINTER(wintypes.DWORD)),
        ("Flags", wintypes.DWORD),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", wintypes.LPVOID),
        ("lpTemplateName", wintypes.LPCWSTR),
    ]


def _rgb_to_colorref(rgb: RgbColor) -> int:
    r, g, b = (max(0, min(255, int(component * 255))) for component in rgb)
    return (b << 16) | (g << 8) | r


def _colorref_to_rgb(colorref: int) -> RgbColor:
    return (
        (colorref & 0xFF) / 255.0,
        ((colorref >> 8) & 0xFF) / 255.0,
        ((colorref >> 16) & 0xFF) / 255.0,
    )


def _win_pick_color(
    title: str,
    initial_rgb: RgbColor,
    parent_hwnd: int | None,
) -> RgbColor | None:
    custom = (wintypes.DWORD * 16)(
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
        0x00FFFFFF,
    )
    cc = CHOOSECOLORW()
    cc.lStructSize = ctypes.sizeof(CHOOSECOLORW)
    cc.hwndOwner = parent_hwnd or 0
    cc.rgbResult = _rgb_to_colorref(initial_rgb)
    cc.lpCustColors = custom
    cc.Flags = CC_RGBINIT | CC_FULLOPEN

    if not ctypes.windll.comdlg32.ChooseColorW(ctypes.byref(cc)):
        return None
    return _colorref_to_rgb(int(cc.rgbResult))


def _tk_pick_color(title: str, initial_rgb: RgbColor) -> RgbColor | None:
    try:
        import tkinter as tk
        from tkinter import colorchooser
    except ImportError:
        return None

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    rgb, _hex = colorchooser.askcolor(
        color=tuple(int(component * 255) for component in initial_rgb),
        title=title,
    )
    root.destroy()
    if rgb is None:
        return None
    return rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0


def pick_color(
    title: str = "Выбор цвета",
    initial_rgb: RgbColor = (1.0, 1.0, 1.0),
    parent_hwnd: int | None = None,
) -> RgbColor | None:
    if sys.platform == "win32":
        return _win_pick_color(title, initial_rgb, parent_hwnd)
    return _tk_pick_color(title, initial_rgb)
