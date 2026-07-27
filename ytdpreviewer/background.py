"""System tray background process (autostart)."""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from ytdpreviewer.version_info import installed_version, tray_version_label
from ytdpreviewer.app_icon import load_pil_icon
from ytdpreviewer.ipc import start_listener
from ytdpreviewer.preview_window import open_preview_toplevel
from ytdpreviewer.tray_native import NativeTray, TrayMenuItem
from ytdpreviewer.ydd_viewer import launch_ydd_viewer

_MENU_VERSION = 1001
_MENU_CHECK_UPDATES = 1002
_MENU_OPEN = 1003
_MENU_QUIT = 1004


def _tray_log(message: str) -> None:
    try:
        from ytdpreviewer.paths import default_install_dir

        log_path = default_install_dir() / "update_cache" / "tray.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(message + "\n")
    except OSError:
        pass


def _warmup() -> None:
    """Pre-load heavy modules while the tray process is idle."""
    try:
        import texfury  # noqa: F401
        from texfury import ITD  # noqa: F401
    except Exception:
        pass
    try:
        from ytdpreviewer.fivefury_bootstrap import ensure_fivefury

        ensure_fivefury()
    except Exception:
        pass


def _tray_image() -> Image.Image:
    return load_pil_icon(64)


class BackgroundApp:
    def __init__(self) -> None:
        self._tk_root: tk.Tk | None = None
        self._tk_thread: threading.Thread | None = None
        self._icon: NativeTray | None = None

    def run(self) -> None:
        ipc = start_listener(self.open_file)
        if ipc is None:
            _tray_log("ipc bind failed; tray starts without file listener")
        threading.Thread(target=_warmup, name="ytd-warmup", daemon=True).start()

        def _init_tray_ui(root: tk.Tk) -> None:
            from ytdpreviewer.paths import default_install_dir
            from ytdpreviewer.update import (
                _clear_stale_update_ui_lock,
                install_ui_pump,
                schedule_update_check,
            )

            _clear_stale_update_ui_lock(default_install_dir())
            install_ui_pump(root)
            schedule_update_check(root, on_quit=self._request_quit)

        root = self._ensure_tk(_init_tray_ui)

        ver = tray_version_label()
        menu_items = [
            TrayMenuItem(_MENU_VERSION, f"Версия {ver}", self._version_info),
            TrayMenuItem(
                _MENU_CHECK_UPDATES,
                "Проверить обновления",
                self._check_updates,
            ),
            TrayMenuItem(_MENU_OPEN, "Открыть YTD...", self._pick_file),
            TrayMenuItem(_MENU_QUIT, "Выход", self._quit),
        ]
        _tray_log(f"native tray menu items={len(menu_items)} version={ver}")
        self._icon = NativeTray(
            "ytdpreviewer",
            _tray_image(),
            f"YTD Previewer {ver}",
            menu_items,
        )
        self._icon.run()

    def _ensure_tk(self, on_ready: Callable[[tk.Tk], None] | None = None) -> tk.Tk:
        if self._tk_root is None:
            ready = threading.Event()

            def run() -> None:
                self._tk_root = tk.Tk()
                self._tk_root.withdraw()
                if on_ready is not None:
                    on_ready(self._tk_root)
                ready.set()
                self._tk_root.mainloop()

            self._tk_thread = threading.Thread(target=run, name="ytd-tk", daemon=True)
            self._tk_thread.start()
            ready.wait()

        return self._tk_root  # type: ignore[return-value]

    def _schedule_tk(self, fn: Callable[[], None]) -> None:
        from ytdpreviewer.update import _enqueue_ui

        self._ensure_tk()
        _enqueue_ui(fn)

    def open_file(self, path: str | Path) -> None:
        root = self._ensure_tk()
        p = Path(path)

        def show() -> None:
            ext = p.suffix.lower()
            if ext == ".ydd":
                launch_ydd_viewer(p)
            elif ext == ".dds":
                from ytdpreviewer.dds_preview import launch_dds_preview

                launch_dds_preview(p)
            elif ext == ".ytd":
                open_preview_toplevel(root, p)

        self._schedule_tk(show)

    def _pick_file(self) -> None:
        root = self._ensure_tk()

        def dialog() -> None:
            from tkinter import filedialog

            path = filedialog.askopenfilename(
                title="Открыть файл",
                filetypes=[
                    ("GTA V assets", "*.ytd *.ydd *.dds"),
                    ("Texture Dictionary", "*.ytd"),
                    ("DDS texture", "*.dds"),
                    ("Drawable Dictionary", "*.ydd"),
                    ("Все файлы", "*.*"),
                ],
            )
            if path:
                p = Path(path)
                ext = p.suffix.lower()
                if ext == ".ydd":
                    launch_ydd_viewer(p)
                elif ext == ".dds":
                    from ytdpreviewer.dds_preview import launch_dds_preview

                    launch_dds_preview(p)
                elif ext == ".ytd":
                    open_preview_toplevel(root, p)

        self._schedule_tk(dialog)

    def _version_info(self) -> None:
        root = self._ensure_tk()
        from ytdpreviewer.update import _tray_messagebox

        self._schedule_tk(
            lambda: _tray_messagebox(
                root,
                "YTD Previewer",
                f"Установлена версия {installed_version()}.",
            )
        )

    def _check_updates(self) -> None:
        root = self._ensure_tk()
        from ytdpreviewer.update import run_manual_update_check

        self._schedule_tk(
            lambda: run_manual_update_check(root, on_quit=self._request_quit)
        )

    def _request_quit(self) -> None:
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass
        if self._tk_root:
            self._schedule_tk(self._tk_root.quit)

    def _quit(self) -> None:
        self._request_quit()


def run_background() -> None:
    from ytdpreviewer.single_instance import try_acquire_background_singleton

    if not try_acquire_background_singleton():
        return

    BackgroundApp().run()

