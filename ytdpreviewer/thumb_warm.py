"""Parallel pre-render of .ytd thumbnails into the shared disk cache."""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from ytdpreviewer.thumb_cache import cache_dir, cache_png_path, find_best_cached_path, is_cached
from ytdpreviewer.ytd_texture_preview import MAX_THUMB_SIDE
from ytdpreviewer.ytd_texture_preview import render_thumbnail_file


def _render_one(ytd: Path, *, size: int, fast: bool) -> tuple[Path, bool, str]:
    try:
        if is_cached(ytd, size):
            return ytd, True, "cached"
        out = cache_png_path(ytd, MAX_THUMB_SIDE)
        if out is None:
            return ytd, False, "invalid path"
        _, best_side = find_best_cached_path(ytd)
        if best_side >= MAX_THUMB_SIDE:
            return ytd, True, "cached"
        out.parent.mkdir(parents=True, exist_ok=True)
        render_thumbnail_file(ytd, out, max_side=MAX_THUMB_SIDE, fast=fast)
        if out.stat().st_size <= 64:
            out.unlink(missing_ok=True)
            return ytd, False, "empty png"
        return ytd, True, "ok"
    except Exception as exc:
        return ytd, False, str(exc)


def warm_folder(
    folder: Path,
    *,
    size: int = 1024,
    workers: int = 4,
    fast: bool = False,
) -> tuple[int, int]:
    folder = folder.resolve()
    if not folder.is_dir():
        raise NotADirectoryError(folder)

    from ytdpreviewer.thumb_roots import append_thumb_root

    append_thumb_root(folder)

    files = sorted(folder.glob("*.ytd"))
    if not files:
        return 0, 0

    workers = max(1, min(workers, 16))
    ok = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_render_one, path, size=size, fast=fast): path for path in files
        }
        for fut in as_completed(futures):
            _, success, _ = fut.result()
            if success:
                ok += 1

    return ok, len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-render .ytd thumbnails in parallel")
    parser.add_argument("folder", type=Path, help="Folder with .ytd files")
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--fast", action="store_true", help="Faster but softer thumbnails")
    args = parser.parse_args(argv)

    cache_dir().mkdir(parents=True, exist_ok=True)
    ok, total = warm_folder(
        args.folder,
        size=max(32, min(args.size, 1024)),
        workers=args.workers,
        fast=args.fast,
    )
    print(f"YTD thumbnails: {ok}/{total} ready in {cache_dir()}")
    return 0 if ok == total or ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
