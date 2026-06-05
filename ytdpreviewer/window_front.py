"""Raise preview / viewer windows when opened — without staying above all apps forever."""

from __future__ import annotations

import sys
import tkinter as tk

if sys.platform == "win32":
    import ctypes

    _user32 = ctypes.windll.user32
    _HWND_TOPMOST = -1
    _HWND_NOTOPMOST = -2
    _SWP_NOSIZE = 0x0001
    _SWP_NOMOVE = 0x0002
    _SWP_SHOWWINDOW = 0x0040
    _FLASH_TOPMOST_MS = 280


def focus_preview_window(window: tk.Misc) -> None:
    """Bring Tk preview to the front once; user can switch to other apps normally."""
    try:
        window.deiconify()
    except tk.TclError:
        pass

    if sys.platform == "win32":
        _flash_topmost_tk(window)
    else:
        window.lift()

    window.update_idletasks()

    try:
        window.focus_force()
    except tk.TclError:
        pass

    if sys.platform == "win32":
        _win32_foreground_tk(window)


def _flash_topmost_tk(window: tk.Misc) -> None:
    """Brief topmost so Explorer does not keep the window underneath."""
    try:
        window.attributes("-topmost", True)
        window.update_idletasks()
        window.lift()
    except tk.TclError:
        return

    def _clear() -> None:
        try:
            window.attributes("-topmost", False)
            window.lift()
        except tk.TclError:
            pass

    try:
        window.after(_FLASH_TOPMOST_MS, _clear)
    except tk.TclError:
        _clear()


def _win32_foreground_tk(window: tk.Misc) -> None:
    try:
        hwnd = int(window.winfo_id())
    except (tk.TclError, ValueError, TypeError):
        return
    try:
        _user32.SetForegroundWindow(hwnd)
    except OSError:
        pass


def _win32_flash_hwnd(hwnd: int) -> None:
    flags = _SWP_NOSIZE | _SWP_NOMOVE | _SWP_SHOWWINDOW
    try:
        _user32.SetWindowPos(hwnd, _HWND_TOPMOST, 0, 0, 0, 0, flags)
        _user32.SetWindowPos(hwnd, _HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        _user32.SetForegroundWindow(hwnd)
    except OSError:
        pass


def focus_pyglet_window(window: object) -> None:
    """Raise pyglet viewer once (Windows: short Z-order boost, not permanent topmost)."""
    try:
        window.set_visible(True)  # type: ignore[attr-defined]
    except Exception:
        pass

    if sys.platform != "win32":
        try:
            window.activate()  # type: ignore[attr-defined]
        except Exception:
            pass
        return

    hwnd = getattr(window, "_hwnd", None)
    if hwnd:
        _win32_flash_hwnd(hwnd)

    try:
        window.activate()  # type: ignore[attr-defined]
    except Exception:
        pass
