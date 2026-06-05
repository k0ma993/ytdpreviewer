"""Ensure only one tray (background) process runs at a time."""

from __future__ import annotations

import ctypes

_KERNEL32 = ctypes.windll.kernel32
_ERROR_ALREADY_EXISTS = 183
_BACKGROUND_MUTEX = "Local\\YTDPreviewer_Background_v1"

_background_mutex_handle: int | None = None


def try_acquire_background_singleton() -> bool:
    """
    Return True if this process became the sole background instance.

    A second ``--background`` launch should exit immediately when this returns False.
    """
    global _background_mutex_handle
    if _background_mutex_handle is not None:
        return True

    handle = _KERNEL32.CreateMutexW(None, True, _BACKGROUND_MUTEX)
    if not handle:
        return True

    last_error = _KERNEL32.GetLastError()
    if last_error == _ERROR_ALREADY_EXISTS:
        _KERNEL32.CloseHandle(handle)
        return False

    _background_mutex_handle = handle
    return True


def background_listener_port_free() -> bool:
    """Return False when another process already listens on the IPC port."""
    import socket

    from ytdpreviewer.ipc import HOST, PORT

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.05)
        probe.connect((HOST, PORT))
        return False
    except OSError:
        return True
    finally:
        probe.close()
