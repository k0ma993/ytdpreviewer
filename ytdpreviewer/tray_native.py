"""Tray icon via pystray; popup menu via native Win32 (reliable on Windows 11)."""

from __future__ import annotations

import ctypes
from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

import pystray
from pystray._util import win32

@dataclass(frozen=True)
class TrayMenuItem:
    menu_id: int
    label: str
    action: Callable[[], None]


class NativeTray(pystray.Icon):
    """pystray shell icon with a Win32 popup menu on right-click."""

    def __init__(
        self,
        name: str,
        image: Image.Image,
        title: str,
        items: list[TrayMenuItem],
    ) -> None:
        super().__init__(name, image, title, menu=None)
        self._entries = sorted(items, key=lambda item: item.menu_id)
        self._tip = (title or "YTD Previewer")[:127]

    def _update_menu(self) -> None:
        self._menu_handle = None

    def _show(self) -> None:
        super()._show()
        self._update_title()

    def _update_title(self) -> None:
        if not self._hwnd:
            return
        data = win32.NOTIFYICONDATAW(
            cbSize=ctypes.sizeof(win32.NOTIFYICONDATAW),
            hWnd=self._hwnd,
            uID=id(self),
            uFlags=win32.NIF_TIP,
            szTip=self._tip,
        )
        win32.Shell_NotifyIcon(win32.NIM_MODIFY, data)

    def _on_notify(self, wparam, lparam) -> None:
        if lparam == win32.WM_LBUTTONUP:
            self()
        elif lparam == win32.WM_RBUTTONUP:
            self._show_context_menu()

    def _show_context_menu(self) -> None:
        hwnd = self._hwnd
        menu_hwnd = self._menu_hwnd
        if not hwnd or not menu_hwnd:
            return

        menu = win32.CreatePopupMenu()
        callbacks: list[Callable[[], None]] = []
        try:
            for index, item in enumerate(self._entries):
                callbacks.append(item.action)
                menu_info = win32.MENUITEMINFO(
                    cbSize=ctypes.sizeof(win32.MENUITEMINFO),
                    fMask=win32.MIIM_ID | win32.MIIM_STRING | win32.MIIM_STATE | win32.MIIM_FTYPE,
                    wID=index + 1,
                    dwTypeData=item.label,
                    fState=win32.MFS_ENABLED,
                    fType=win32.MFT_STRING,
                )
                win32.InsertMenuItem(menu, index, True, ctypes.byref(menu_info))

            win32.SetForegroundWindow(hwnd)
            point = ctypes.wintypes.POINT()
            win32.GetCursorPos(ctypes.byref(point))
            command = win32.TrackPopupMenuEx(
                menu,
                win32.TPM_RIGHTALIGN
                | win32.TPM_BOTTOMALIGN
                | win32.TPM_RETURNCMD,
                point.x,
                point.y,
                menu_hwnd,
                None,
            )
            if command > 0:
                idx = command - 1
                if 0 <= idx < len(callbacks):
                    try:
                        callbacks[idx]()
                    except Exception:
                        pass
        finally:
            win32.DestroyMenu(menu)
