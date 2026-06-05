"""Explorer file drag-and-drop onto tkinter windows (Windows)."""

from __future__ import annotations

import ctypes
import queue
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Callable

WM_DROPFILES = 0x0233
GWLP_WNDPROC = -4

IMAGE_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".dds", ".tif", ".tiff", ".webp"}
)

DropCallback = Callable[[list[Path]], None]

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

if ctypes.sizeof(ctypes.c_void_p) == 8:
    _LRESULT = ctypes.c_int64
    _WPARAM = ctypes.c_uint64
    _LPARAM = ctypes.c_int64
    _SetWindowLongPtr = user32.SetWindowLongPtrW
    _GetWindowLongPtr = user32.GetWindowLongPtrW
else:
    _LRESULT = ctypes.c_long
    _WPARAM = wintypes.WPARAM
    _LPARAM = wintypes.LPARAM
    _SetWindowLongPtr = user32.SetWindowLongW
    _GetWindowLongPtr = user32.GetWindowLongW

_GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
_GetWindowLongPtr.restype = _LRESULT
_SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, _LRESULT]
_SetWindowLongPtr.restype = _LRESULT

user32.CallWindowProcW.argtypes = [
    _LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    _WPARAM,
    _LPARAM,
]
user32.CallWindowProcW.restype = _LRESULT

shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
shell32.DragQueryFileW.argtypes = [
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPWSTR,
    wintypes.UINT,
]
shell32.DragQueryFileW.restype = wintypes.UINT
shell32.DragFinish.argtypes = [wintypes.HANDLE]

_WndProcType = ctypes.WINFUNCTYPE(
    _LRESULT,
    wintypes.HWND,
    wintypes.UINT,
    _WPARAM,
    _LPARAM,
)

_EnumChildProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = [wintypes.HWND, _EnumChildProc, wintypes.LPARAM]
user32.EnumChildWindows.restype = wintypes.BOOL


def _descendant_hwnds(root_hwnd: int) -> list[int]:
    """Toplevel + every child HWND (Explorer drops onto the widget under the cursor)."""
    hwnds: list[int] = [root_hwnd]
    keepalive: list[_EnumChildProc] = []

    @_EnumChildProc
    def _collect(hwnd, _lparam):
        hwnds.append(int(hwnd))
        return True

    keepalive.append(_collect)
    user32.EnumChildWindows(root_hwnd, _collect, 0)
    return hwnds


class _FileDropHook:
    def __init__(self, hwnd: int, callback: DropCallback) -> None:
        self._hwnd = hwnd
        self._callback = callback
        self._proc = _WndProcType(self._wnd_proc)
        self._old_proc = _GetWindowLongPtr(hwnd, GWLP_WNDPROC)
        _SetWindowLongPtr(
            hwnd,
            GWLP_WNDPROC,
            ctypes.cast(self._proc, ctypes.c_void_p).value,
        )
        shell32.DragAcceptFiles(hwnd, True)

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                self._on_drop(ctypes.c_void_p(wparam))
            except Exception:
                pass
            return 0
        return user32.CallWindowProcW(
            self._old_proc,
            hwnd,
            msg,
            wparam,
            lparam,
        )

    def _on_drop(self, drop_handle: ctypes.c_void_p) -> None:
        try:
            count = shell32.DragQueryFileW(drop_handle, 0xFFFFFFFF, None, 0)
            if not count:
                return
            paths: list[Path] = []
            for i in range(count):
                length = shell32.DragQueryFileW(drop_handle, i, None, 0)
                buf = ctypes.create_unicode_buffer(length + 1)
                shell32.DragQueryFileW(drop_handle, i, buf, length + 1)
                paths.append(Path(buf.value))
        finally:
            shell32.DragFinish(drop_handle)

        if paths:
            self._callback(paths)


def _toplevel_hwnd(widget) -> int:
    """HWND of the tk toplevel — hook the same window Explorer drops onto."""
    widget.update_idletasks()
    return int(widget.winfo_toplevel().winfo_id())


class _DropState:
    __slots__ = ("enqueue", "hooked", "hooks", "polling")

    def __init__(self, enqueue: DropCallback) -> None:
        self.enqueue = enqueue
        self.hooked: set[int] = set()
        self.hooks: list[_FileDropHook] = []
        self.polling = False


def _hook_hwnd(state: _DropState, hwnd: int) -> None:
    if hwnd in state.hooked:
        return
    state.hooked.add(hwnd)
    state.hooks.append(_FileDropHook(hwnd, state.enqueue))


def _hook_widget_tree(state: _DropState, widget) -> None:
    root_hwnd = _toplevel_hwnd(widget)
    for hwnd in _descendant_hwnds(root_hwnd):
        try:
            _hook_hwnd(state, hwnd)
        except (OSError, ctypes.ArgumentError):
            continue


def refresh_file_drop(widget) -> None:
    """Attach drop handlers to any new child HWNDs (e.g. after thumbnails load)."""
    state: _DropState | None = getattr(widget, "_ytd_file_drop_state", None)
    if state is None:
        return
    _hook_widget_tree(state, widget)


def bind_file_drop(widget, callback: DropCallback) -> bool:
    """Accept dropped files on a tk window. Returns False if unsupported."""
    if sys.platform != "win32":
        return False

    pending: queue.Queue[list[Path]] = queue.Queue()

    def _enqueue(paths: list[Path]) -> None:
        pending.put(paths)

    state = _DropState(_enqueue)

    def _poll() -> None:
        try:
            while True:
                callback(pending.get_nowait())
        except queue.Empty:
            pass
        refresh_file_drop(widget)
        try:
            widget.after(200, _poll)
        except Exception:
            state.polling = False
            return

    try:
        _hook_widget_tree(state, widget)
    except OSError:
        return False
    except ctypes.ArgumentError:
        return False

    if not state.hooks:
        return False

    widget._ytd_file_drop_state = state  # type: ignore[attr-defined]
    if not state.polling:
        state.polling = True
        widget.after(200, _poll)
    return True


def filter_image_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            out.append(p.resolve())
    return out
