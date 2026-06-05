"""Open .ytd texture dictionaries in the preview window."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_YTD_CHILD_ENV = "YTD_YTD_CHILD"


def _python_for_gui() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.is_file():
            return pyw
    return exe


def _subprocess_no_window_kwargs() -> dict:
    if sys.platform != "win32":
        return {}
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return {"creationflags": flags} if flags else {}


def _project_root() -> Path:
    from ytdpreviewer.paths import app_dir

    if getattr(sys, "frozen", False):
        return app_dir()
    return Path(__file__).resolve().parent.parent


def is_ytd_child_process() -> bool:
    return os.environ.get(_YTD_CHILD_ENV) == "1"


def open_ytd_preview(path: str | Path) -> None:
    """Show preview window for a .ytd file (blocks until window closes)."""
    from ytdpreviewer.preview_window import open_preview

    open_preview(path)


def launch_ytd_preview(path: str | Path) -> None:
    """
    Open .ytd reliably from Explorer (no IPC — stale tray must not swallow the path).

    Dev: opens in-process. Frozen install: spawns child with YTD_YTD_CHILD=1.
    """
    resolved = Path(path).resolve()
    if not resolved.is_file():
        _show_error(f"Файл не найден:\n{resolved}")
        return

    if not getattr(sys, "frozen", False):
        open_ytd_preview(resolved)
        return

    if is_ytd_child_process():
        open_ytd_preview(resolved)
        return

    env = os.environ.copy()
    env[_YTD_CHILD_ENV] = "1"
    py = _python_for_gui()
    cmd = [str(py), str(resolved)]

    try:
        subprocess.Popen(cmd, cwd=str(_project_root()), env=env, **_subprocess_no_window_kwargs())
    except OSError as exc:
        _show_error(f"Не удалось открыть YTD:\n{exc}")


def _show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "YTD Previewer", 0x10)
    except Exception:
        print(message, file=sys.stderr)
