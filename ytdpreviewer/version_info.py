"""Installed app version (readable after in-place updates)."""

from __future__ import annotations

import json
from pathlib import Path

from ytdpreviewer import __version__
from ytdpreviewer.paths import app_dir, default_install_dir


def parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in value.strip().lstrip("vV").split("."):
        head = piece.split("-")[0].split("+")[0]
        try:
            parts.append(int(head))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def _read_version_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                value = str(data.get("version", "")).strip()
                return value or None
        line = path.read_text(encoding="utf-8").strip()
        return line.splitlines()[0].strip() if line else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def installed_version() -> str:
    """Best-known version from install files and the running bundle."""
    candidates = [
        app_dir() / "version.txt",
        default_install_dir() / "version.txt",
        app_dir() / "version.json",
        default_install_dir() / "version.json",
    ]
    found: list[str] = []
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        value = _read_version_file(resolved)
        if value:
            found.append(value.lstrip("vV"))

    found.append(__version__.lstrip("vV"))
    return max(found, key=parse_version)


def tray_version_label() -> str:
    """Short safe version string for the tray menu/tooltip."""
    try:
        value = installed_version().strip().lstrip("vV")
    except Exception:
        value = __version__.strip().lstrip("vV")
    if not value:
        return "?"
    if len(value) > 24:
        return value[:24] + "…"
    return value
