"""Shared fingerprint path cache (same layout as shell YddPathResolver)."""

from __future__ import annotations

import hashlib
import zlib
from pathlib import Path

from ytdpreviewer.paths import default_install_dir

_SAMPLE_LEN = 256 * 1024


def _sample_crc32(path: Path) -> int:
    crc = 0xFFFFFFFF
    with path.open("rb") as handle:
        remaining = min(_SAMPLE_LEN, path.stat().st_size)
        while remaining > 0:
            chunk = handle.read(min(8192, remaining))
            if not chunk:
                break
            crc = zlib.crc32(chunk, crc)
            remaining -= len(chunk)
    return crc ^ 0xFFFFFFFF


def _normalize_ext(path: Path) -> str:
    name = path.name.lower()
    if path.suffix.lower() == ".tmp":
        if name.startswith("yddprev_"):
            return ".ydd"
        if name.startswith("ytdprev_"):
            return ".ytd"
    return path.suffix.lower()


def fingerprint_hash8(path: Path) -> str:
    ext = _normalize_ext(path)
    material = f"v10|{ext}|{path.stat().st_size}|{_sample_crc32(path):08X}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()


def read_cached_real_path(scratch_ydd: Path) -> Path | None:
    try:
        key = fingerprint_hash8(scratch_ydd)
        cache_file = default_install_dir() / "thumb_paths" / f"{key}.txt"
        if not cache_file.is_file():
            return None
        real = Path(cache_file.read_text(encoding="utf-8").strip().strip('"'))
        return real if real.is_file() else None
    except OSError:
        return None
