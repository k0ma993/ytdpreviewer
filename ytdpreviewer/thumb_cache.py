"""Disk thumbnail cache (same keys as shell/YtdThumbnail/ThumbnailCache.cs)."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

from ytdpreviewer.paths import default_install_dir
from ytdpreviewer.ytd_texture_preview import MAX_THUMB_SIDE

_SAMPLE_LEN = 256 * 1024
_LEGACY_SIZES = (1024, 512, 256, 128, 96, 80, 64, 48, 32)


def cache_dir() -> Path:
    return default_install_dir() / "thumbcache"


def _sample_crc32(path: Path) -> int:
    crc = 0xFFFFFFFF
    with path.open("rb") as f:
        remaining = min(_SAMPLE_LEN, path.stat().st_size)
        while remaining > 0:
            chunk = f.read(min(8192, remaining))
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc) & 0xFFFFFFFF
            remaining -= len(chunk)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def _cache_key(path: Path) -> str | None:
    try:
        resolved = Path(path).resolve()
        if not resolved.is_file():
            return None
        sample = _sample_crc32(resolved)
        ext = resolved.suffix.lower()
        material = f"v4|{ext}|{resolved.stat().st_size}|{sample:08X}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    except OSError:
        return None


def cache_png_path(ytd_path: Path, size: int | None = None) -> Path | None:
    key = _cache_key(ytd_path)
    if key is None:
        return None
    side = MAX_THUMB_SIDE if size is None else size
    return cache_dir() / f"{key}_{side}.png"


def find_best_cached_path(ytd_path: Path) -> tuple[Path | None, int]:
    key = _cache_key(ytd_path)
    if key is None:
        return None, 0
    best_path: Path | None = None
    best_side = 0
    for side in _LEGACY_SIZES:
        path = cache_dir() / f"{key}_{side}.png"
        try:
            if path.is_file() and path.stat().st_size > 64 and side > best_side:
                best_path = path
                best_side = side
        except OSError:
            continue
    return best_path, best_side


def is_cached(ytd_path: Path, size: int = MAX_THUMB_SIDE) -> bool:
    path, best_side = find_best_cached_path(ytd_path)
    if path is None:
        return False
    need = max(32, min(size, MAX_THUMB_SIDE))
    if best_side < MAX_THUMB_SIDE and best_side < need:
        return False
    return True
