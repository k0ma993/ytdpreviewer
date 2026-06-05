"""Headless export CLI — no 3D preview, no tray, no IPC."""

from __future__ import annotations

import sys
from pathlib import Path


def _hide_console() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _collect_file_paths(args: list[str], extension: str) -> list[str]:
    ext = extension if extension.startswith(".") else f".{extension}"
    ext = ext.lower()
    paths: list[str] = []
    for arg in args:
        if arg.startswith("-"):
            continue
        if arg in ("ytd-png", "ydd-obj", "ydd-textures", "png-ytd"):
            continue
        if Path(arg).suffix.lower() == ext:
            paths.append(arg)
    return paths


def _collect_ytd_paths(args: list[str]) -> list[str]:
    return _collect_file_paths(args, ".ytd")


def _collect_image_paths(args: list[str]) -> list[str]:
    paths: list[str] = []
    for arg in args:
        if arg.startswith("-"):
            continue
        if arg in ("ytd-png", "ydd-obj", "ydd-textures", "png-ytd"):
            continue
        suffix = Path(arg).suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff", ".dds"):
            paths.append(arg)
    return paths  # argv order = user / shell invocation order


def _collect_ydd_paths(args: list[str]) -> list[str]:
    return _collect_file_paths(args, ".ydd")


def _run_png_ytd_build(paths: list[str]) -> None:
    from ytdpreviewer.ytd_build_window import run_build_window_safe

    run_build_window_safe(paths)


def _export_png_ytd(args: list[str]) -> None:
    from ytdpreviewer.export_batch import join_png_ytd_batch
    from ytdpreviewer.ytd_build import notify_build_result

    paths = _collect_image_paths(args)
    if not paths:
        notify_build_result(None, 0, error="Укажите путь к .png")
        return

    if len(paths) > 1:
        _run_png_ytd_build(paths)
        return

    batched = join_png_ytd_batch(paths[0])
    if batched is None:
        return
    _run_png_ytd_build(batched)


def _run_ytd_png_export(paths: list[str]) -> None:
    from ytdpreviewer.export_progress import run_with_export_progress
    from ytdpreviewer.ytd_export import export_ytd_batch, notify_export_result

    try:
        total, files, folder, errors = run_with_export_progress(
            "Экспорт YTD → PNG",
            lambda report: export_ytd_batch(paths, on_progress=report),
            initial_total=max(1, len(paths)),
        )
        if files == 0 and not errors:
            return
        notify_export_result(folder, total, file_count=files, errors=errors or None)
    except Exception as exc:
        notify_export_result(None, 0, error=str(exc))


def _export_ytd_png(args: list[str]) -> None:
    from ytdpreviewer.export_batch import join_ytd_png_batch
    from ytdpreviewer.ytd_export import notify_export_result

    paths = _collect_ytd_paths(args)
    if not paths:
        notify_export_result(None, 0, error="Укажите путь к .ytd")
        return

    if len(paths) > 1:
        _run_ytd_png_export(paths)
        return

    batched = join_ytd_png_batch(paths[0])
    if batched is None:
        return
    _run_ytd_png_export(batched)


def _run_ydd_obj_export(paths: list[str]) -> None:
    from ytdpreviewer.export_progress import run_with_export_progress
    from ytdpreviewer.ydd_export import export_ydd_batch_obj, notify_ydd_export_result

    try:
        files, folder, outputs, errors = run_with_export_progress(
            "Экспорт YDD → OBJ",
            lambda report: export_ydd_batch_obj(paths, on_progress=report),
            initial_total=max(1, len(paths)),
        )
        if files == 0 and not errors:
            return
        if files == 1 and not errors and outputs:
            notify_ydd_export_result(outputs[0])
            return
        notify_ydd_export_result(folder, file_count=files, errors=errors or None)
    except Exception as exc:
        notify_ydd_export_result(error=str(exc))


def _export_ydd_obj(args: list[str]) -> None:
    from ytdpreviewer.export_batch import join_ydd_obj_batch
    from ytdpreviewer.ydd_export import notify_ydd_export_result

    paths = _collect_ydd_paths(args)
    if not paths:
        notify_ydd_export_result(error="Укажите путь к .ydd")
        return

    if len(paths) > 1:
        _run_ydd_obj_export(paths)
        return

    batched = join_ydd_obj_batch(paths[0])
    if batched is None:
        return
    _run_ydd_obj_export(batched)


def _run_ydd_textures_export(paths: list[str]) -> None:
    from ytdpreviewer.export_progress import run_with_export_progress
    from ytdpreviewer.ydd_export import export_ydd_batch_textures, notify_ydd_export_result

    title = "YTD Previewer — экспорт текстур"
    try:
        total, files, folder, errors = run_with_export_progress(
            "Экспорт текстур YDD",
            lambda report: export_ydd_batch_textures(paths, on_progress=report),
            initial_total=max(1, len(paths)),
        )
        if files == 0 and not errors:
            return
        notify_ydd_export_result(folder, count=total, file_count=files, errors=errors or None, title=title)
    except Exception as exc:
        notify_ydd_export_result(error=str(exc), title=title)


def _export_ydd_textures(args: list[str]) -> None:
    from ytdpreviewer.export_batch import join_ydd_textures_batch
    from ytdpreviewer.ydd_export import notify_ydd_export_result

    title = "YTD Previewer — экспорт текстур"
    paths = _collect_ydd_paths(args)
    if not paths:
        notify_ydd_export_result(error="Укажите путь к .ydd", title=title)
        return

    if len(paths) > 1:
        _run_ydd_textures_export(paths)
        return

    batched = join_ydd_textures_batch(paths[0])
    if batched is None:
        return
    _run_ydd_textures_export(batched)


def _run_thumbnail_cli(args: list[str]) -> bool:
    if "--thumbnail" not in args:
        return False
    idx = args.index("--thumbnail")
    rest = args[idx + 1 :]
    if len(rest) < 3:
        raise SystemExit(2)
    from ytdpreviewer.ytd_texture_preview import render_thumbnail_file

    ok = render_thumbnail_file(Path(rest[0]), Path(rest[1]), max_side=max(32, min(int(rest[2]), 1024)))
    if not ok:
        raise SystemExit(1)
    return True


def run_export_cli(args: list[str]) -> bool:
    """Run export if *args* request it. Returns True when handled."""
    if not args:
        return False

    _hide_console()

    if _run_thumbnail_cli(args):
        return True

    if "--export-ytd-png" in args:
        _export_ytd_png(args)
        return True

    if "--export-ydd-obj" in args:
        _export_ydd_obj(args)
        return True

    if "--export-ydd-textures" in args:
        _export_ydd_textures(args)
        return True

    if "--build-ytd-from-png" in args:
        _export_png_ytd(args)
        return True

    if args[0] == "ytd-png" and len(args) >= 2:
        _export_ytd_png(args)
        return True

    if args[0] == "ydd-obj" and len(args) >= 2:
        _export_ydd_obj(args)
        return True

    if args[0] == "ydd-textures" and len(args) >= 2:
        _export_ydd_textures(args)
        return True

    if args[0] == "png-ytd" and len(args) >= 2:
        _export_png_ytd(args)
        return True

    return False


if __name__ == "__main__":
    raise SystemExit(0 if run_export_cli(sys.argv[1:]) else 1)
