"""Bootstrap fivefury without broken native jenk_hash (Python 3.12)."""

from __future__ import annotations

import importlib
import sys
import types
from functools import lru_cache
from pathlib import Path


def _fivefury_dir() -> Path:
    for entry in sys.path:
        candidate = Path(entry) / "fivefury" / "data" / "lut.dat"
        if candidate.is_file():
            return candidate.parent.parent
    raise RuntimeError("fivefury не установлен. Выполните: pip install fivefury")


def _read_lut() -> bytes:
    ff = _fivefury_dir()
    data = (ff / "data" / "lut.dat").read_bytes()
    if len(data) != 256:
        raise RuntimeError("fivefury lut.dat повреждён")
    return data


@lru_cache(maxsize=1)
def _lut() -> bytes:
    return _read_lut()


def jenk_partial_hash(value: str | bytes, *, encoding: str = "utf-8") -> int:
    lut = _lut()
    data = value if isinstance(value, bytes) else value.lower().encode(encoding)
    h = 0
    for b in data:
        h = (h + lut[b]) & 0xFFFFFFFF
        h = (h + ((h << 10) & 0xFFFFFFFF)) & 0xFFFFFFFF
        h ^= (h >> 6)
        h &= 0xFFFFFFFF
    return h


def jenk_finalize_hash(partial_hash: int) -> int:
    h = int(partial_hash) & 0xFFFFFFFF
    h = (h + ((h << 3) & 0xFFFFFFFF)) & 0xFFFFFFFF
    h ^= (h >> 11)
    h &= 0xFFFFFFFF
    h = (h + ((h << 15) & 0xFFFFFFFF)) & 0xFFFFFFFF
    return h


def jenk_hash(value: str | bytes, *, encoding: str = "utf-8") -> int:
    text = value if isinstance(value, str) else value.decode(encoding)
    return jenk_finalize_hash(jenk_partial_hash(text, encoding=encoding))


def _install_hashing_module() -> None:
    hm = types.ModuleType("fivefury.hashing")
    hm.jenk_hash = jenk_hash
    hm.jenk_partial_hash = jenk_partial_hash
    hm.jenk_finalize_hash = jenk_finalize_hash
    hm._get_lut = _lut
    hm._read_lut_bytes = _read_lut
    sys.modules["fivefury.hashing"] = hm


def ensure_fivefury() -> None:
    if "fivefury.ydd.reader" in sys.modules:
        return

    _install_hashing_module()

    ff_dir = _fivefury_dir()
    if "fivefury" not in sys.modules or not hasattr(sys.modules["fivefury"], "__path__"):
        pkg = types.ModuleType("fivefury")
        pkg.__path__ = [str(ff_dir)]
        pkg.__package__ = "fivefury"
        sys.modules["fivefury"] = pkg


def read_ydd(path):
    ensure_fivefury()
    mod = importlib.import_module("fivefury.ydd.reader")
    return mod.read_ydd(path, path=path)
