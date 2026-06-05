"""Folders where companion .ytd textures live (Explorer stream thumbnails have no source path)."""

from __future__ import annotations

from pathlib import Path

from ytdpreviewer.paths import default_install_dir

_MAX_ROOTS = 64


def _roots_file() -> Path:
    return default_install_dir() / "thumb_roots.txt"


def load_thumb_roots() -> list[Path]:
    path = _roots_file()
    if not path.is_file():
        return []
    roots: list[Path] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip().strip('"')
        if not raw:
            continue
        try:
            resolved = str(Path(raw).resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        if Path(resolved).is_dir():
            roots.append(Path(resolved))
    return roots


def append_thumb_root(folder: str | Path) -> None:
    try:
        resolved = Path(folder).resolve()
    except OSError:
        return
    if not resolved.is_dir():
        return

    path = _roots_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_thumb_roots()
    key = str(resolved)
    if any(str(item) == key for item in existing):
        return

    lines = [str(item) for item in existing]
    lines.append(key)
    lines = sorted(set(lines), key=str.casefold)
    if len(lines) > _MAX_ROOTS:
        lines = lines[-_MAX_ROOTS :]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
