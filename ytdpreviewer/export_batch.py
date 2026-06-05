"""Merge simultaneous Explorer export launches into one batch."""

from __future__ import annotations

import ctypes
import os
import time
from pathlib import Path

_KERNEL32 = ctypes.windll.kernel32
_STABLE_S = 0.65
_MAX_WAIT_S = 20.0
_LOCK_STALE_S = 30.0
_SEQ_FILE = "sequence.counter"

_KINDS: dict[str, tuple[str, str]] = {
    "ytd_png": ("Global\\YTDPreviewer_YTD_PNG_Batch", "ytd_png_batch"),
    "ydd_obj": ("Global\\YTDPreviewer_YDD_OBJ_Batch", "ydd_obj_batch"),
    "ydd_textures": ("Global\\YTDPreviewer_YDD_TEX_Batch", "ydd_textures_batch"),
    "png_ytd": ("Global\\YTDPreviewer_PNG_YTD_Batch", "png_ytd_batch"),
}


def _batch_dir(kind: str) -> Path:
    _, dir_name = _KINDS[kind]
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = root / "YTDPreviewer" / dir_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _dedupe_paths(paths: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for raw in paths:
        key = str(Path(raw).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(raw)
    return unique


def _alloc_batch_ticket(batch_dir: Path, resolved: str) -> None:
    """Queue path with monotonic ticket so order matches registration (selection) order."""
    seq_file = batch_dir / _SEQ_FILE
    try:
        seq = int(seq_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seq = 0
    seq += 1
    seq_file.write_text(str(seq), encoding="utf-8")
    (batch_dir / f"{seq:010d}.path").write_text(resolved, encoding="utf-8")


def _clear_batch_queue(batch_dir: Path) -> None:
    for item in batch_dir.glob("*.path"):
        try:
            item.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        (batch_dir / _SEQ_FILE).unlink(missing_ok=True)
    except OSError:
        pass


def _read_queued_paths(kind: str) -> list[str]:
    batch = _batch_dir(kind)
    paths: list[str] = []
    for item in sorted(batch.glob("*.path"), key=lambda p: p.name):
        try:
            text = item.read_text(encoding="utf-8").strip()
            if text:
                paths.append(text)
        except OSError:
            pass
    _clear_batch_queue(batch)
    return _dedupe_paths(paths)


def _leader_flag(kind: str) -> Path:
    return _batch_dir(kind) / "leader.pid"


def _activity_file(kind: str) -> Path:
    return _batch_dir(kind) / "activity.txt"


def _clear_stale_leader(kind: str) -> None:
    flag = _leader_flag(kind)
    if not flag.exists():
        return
    try:
        if time.time() - flag.stat().st_mtime > _LOCK_STALE_S:
            flag.unlink(missing_ok=True)
            _activity_file(kind).unlink(missing_ok=True)
    except OSError:
        pass


def _with_batch_lock(mutex_name: str):
    mutex = _KERNEL32.CreateMutexW(None, False, mutex_name)
    _KERNEL32.WaitForSingleObject(mutex, 0xFFFFFFFF)
    return mutex


def _release_batch_lock(mutex) -> None:
    _KERNEL32.ReleaseMutex(mutex)
    _KERNEL32.CloseHandle(mutex)


def join_export_batch(file_path: str, kind: str) -> list[str] | None:
    """Register *file_path* and return all paths if this process should export."""
    if kind not in _KINDS:
        raise ValueError(f"Unknown batch kind: {kind}")

    mutex_name, _ = _KINDS[kind]
    batch_dir = _batch_dir(kind)
    resolved = str(Path(file_path).resolve())

    mutex = _with_batch_lock(mutex_name)
    try:
        _clear_stale_leader(kind)
        _alloc_batch_ticket(batch_dir, resolved)

        leader = _leader_flag(kind)
        is_leader = not leader.exists()
        if is_leader:
            leader.write_text(str(os.getpid()), encoding="utf-8")

        _activity_file(kind).write_text(str(time.time()), encoding="utf-8")
    finally:
        _release_batch_lock(mutex)

    if not is_leader:
        return None

    start = time.time()
    while time.time() - start < _MAX_WAIT_S:
        time.sleep(0.12)
        try:
            last = float(_activity_file(kind).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last = 0.0
        if time.time() - last >= _STABLE_S:
            break

    paths = _read_queued_paths(kind)
    try:
        _leader_flag(kind).unlink(missing_ok=True)
        _activity_file(kind).unlink(missing_ok=True)
    except OSError:
        pass

    return paths or None


def join_ytd_png_batch(ytd_path: str) -> list[str] | None:
    return join_export_batch(ytd_path, "ytd_png")


def join_ydd_obj_batch(ydd_path: str) -> list[str] | None:
    return join_export_batch(ydd_path, "ydd_obj")


def join_ydd_textures_batch(ydd_path: str) -> list[str] | None:
    return join_export_batch(ydd_path, "ydd_textures")


def join_png_ytd_batch(png_path: str) -> list[str] | None:
    return join_export_batch(png_path, "png_ytd")
