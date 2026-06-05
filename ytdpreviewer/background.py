"""System tray background process (autostart)."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path

import pystray
from PIL import Image

from ytdpreviewer.app_icon import load_pil_icon
from ytdpreviewer.ipc import start_listener
from ytdpreviewer.preview_window import open_preview_toplevel
from ytdpreviewer.ydd_viewer import launch_ydd_viewer


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
        self._icon: pystray.Icon | None = None

    def run(self) -> None:
        start_listener(self.open_file)
        threading.Thread(target=_warmup, name="ytd-warmup", daemon=True).start()
        root = self._ensure_tk()
        from ytdpreviewer.update import schedule_update_check

        schedule_update_check(root, on_quit=self._request_quit)

        menu = pystray.Menu(
            pystray.MenuItem("Открыть YTD…", self._pick_file),
            pystray.MenuItem("Выход", self._quit),
        )
        self._icon = pystray.Icon("ytdpreviewer", _tray_image(), "YTD Previewer", menu)
        self._icon.run()

    def _ensure_tk(self) -> tk.Tk:
        if self._tk_root is None:
            ready = threading.Event()

            def run() -> None:
                self._tk_root = tk.Tk()
                self._tk_root.withdraw()
                ready.set()
                self._tk_root.mainloop()

            self._tk_thread = threading.Thread(target=run, name="ytd-tk", daemon=True)
            self._tk_thread.start()
            ready.wait()

        return self._tk_root  # type: ignore[return-value]

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

        root.after(0, show)

    def _pick_file(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
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

        root.after(0, dialog)

    def _request_quit(self) -> None:
        if self._icon:
            self._icon.stop()
        if self._tk_root:
            self._tk_root.after(0, self._tk_root.quit)

    def _quit(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._request_quit()


def run_background() -> None:
    BackgroundApp().run()
