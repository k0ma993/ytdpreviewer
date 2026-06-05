"""Install directory and bundled asset paths."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "YTDPreviewer"


def default_install_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / APP_NAME


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory of the running application (install dir when frozen)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def assets_dir() -> Path:
    if is_frozen():
        bundled = Path(getattr(sys, "_MEIPASS", app_dir())) / "assets"
        if bundled.is_dir():
            return bundled
    root = Path(__file__).resolve().parent.parent / "assets"
    return root


def viewer_exe() -> Path:
    if is_frozen():
        return Path(sys.executable)
    return app_dir() / "YTDPreviewer.exe"
