"""YTD Previewer — autostart tray + double-click .ytd / .ydd to preview."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

MAX_YDD_THUMB_SIDE = 512


def _collect_paths(argv: list[str]) -> list[Path]:
    paths: list[Path] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--view-ydd", "--export-ytd-png", "--export-ydd-obj", "--export-ydd-textures", "--build-ytd-from-png"):
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        p = Path(arg)
        name = p.name.lower()
        if name.startswith("yddprev_") or name.startswith("ytdprev_"):
            continue
        if p.suffix.lower() in (".ytd", ".ydd", ".dds"):
            paths.append(p)
    return paths


def _run_ydd_thumbnail_cli(args: list[str]) -> bool:
    if "--ydd-thumbnail" not in args:
        return False
    idx = args.index("--ydd-thumbnail")
    rest = args[idx + 1 :]
    if len(rest) < 3:
        raise SystemExit(2)
    from ytdpreviewer.ydd_thumbnail import render_ydd_thumbnail_file

    src = Path(rest[0])
    out = Path(rest[1])
    try:
        size = int(rest[2])
    except ValueError:
        raise SystemExit(2) from None
    ok = render_ydd_thumbnail_file(
        src, out, max_side=max(32, min(size, MAX_YDD_THUMB_SIDE))
    )
    if not ok:
        raise SystemExit(1)
    return True


def _run_thumbnail_cli(args: list[str]) -> bool:
    if "--thumbnail" not in args:
        return False
    idx = args.index("--thumbnail")
    rest = args[idx + 1 :]
    if len(rest) < 3:
        raise SystemExit(2)
    from ytdpreviewer.ytd_texture_preview import render_thumbnail_file

    src = Path(rest[0])
    out = Path(rest[1])
    try:
        size = int(rest[2])
    except ValueError:
        raise SystemExit(2) from None
    fast = "--fast" in rest[3:]
    ok = render_thumbnail_file(src, out, max_side=max(32, min(size, 1024)), fast=fast)
    if not ok:
        raise SystemExit(1)
    return True


def _run_apply_update_cli(args: list[str]) -> bool:
    if "--apply-update" not in args:
        return False
    idx = args.index("--apply-update")
    rest = args[idx + 1 :]
    if len(rest) < 2:
        raise SystemExit(2)
    from ytdpreviewer.apply_update import run_apply_update

    run_apply_update(Path(rest[0]), Path(rest[1]))
    raise SystemExit(0)


def _run_warm_thumbs_cli(args: list[str]) -> bool:
    if "--warm-ytd-thumbs" not in args:
        return False
    idx = args.index("--warm-ytd-thumbs")
    if idx + 1 >= len(args):
        raise SystemExit(2)
    from ytdpreviewer.thumb_warm import warm_folder

    folder = Path(args[idx + 1])
    workers = 4
    for i, arg in enumerate(args):
        if arg == "--workers" and i + 1 < len(args):
            workers = int(args[i + 1])
    warm_folder(folder, workers=workers)
    return True


def main() -> None:
    args = sys.argv[1:]

    if _run_apply_update_cli(args):
        return

    if _run_thumbnail_cli(args):
        return

    if _run_ydd_thumbnail_cli(args):
        return

    if _run_warm_thumbs_cli(args):
        return

    if "--view-ydd" in args:
        idx = args.index("--view-ydd")
        if idx + 1 >= len(args):
            print("Укажите путь к .ydd после --view-ydd")
            return
        from ytdpreviewer.ydd_viewer import _is_shell_scratch_ydd, run_viewer_safe

        ydd_arg = Path(args[idx + 1])
        if _is_shell_scratch_ydd(ydd_arg):
            return
        run_viewer_safe(args[idx + 1])
        return

    # A normal double-click (including a Start-menu shortcut) should launch
    # the resident tray app. Explicit CLI/file arguments keep their old modes.
    background = "--background" in args or not args

    if background:
        from ytdpreviewer.background import run_background

        run_background()
        return

    paths = _collect_paths(args)
    if not paths:
        print("Использование:")
        print("  python -m ytdpreviewer.main --background      # фон + трей")
        print("  python -m ytdpreviewer.main file.ytd          # превью текстур")
        print("  python -m ytdpreviewer.main file.dds          # превью DDS")
        print("  python -m ytdpreviewer.main file.ydd          # 3D превью (OpenGL)")
        print("  python -m ytdpreviewer.main --view-ydd f.ydd  # только 3D окно")
        print("  python -m ytdpreviewer.main --ydd-thumbnail f.ydd out.png 128")
        print("  python -m ytdpreviewer.export_main --export-ytd-png f.ytd")
        print("  python -m ytdpreviewer.export_main --export-ydd-obj f.ydd")
        print("  python -m ytdpreviewer.export_main --export-ydd-textures f.ydd")
        print("  python -m ytdpreviewer.export_main --build-ytd-from-png f.png")
        print("  python -m ytdpreviewer.png_to_dds texture.png   # PNG → DDS")
        print("  python -m ytdpreviewer.setup_windows dev        # установка")
        return

    from ytdpreviewer.ydd_viewer import launch_ydd_viewer

    for path in paths:
        if path.name.lower().startswith(("yddprev_", "ytdprev_")):
            continue
        resolved = str(path.resolve())
        ext = path.suffix.lower()
        if ext == ".ydd":
            from ytdpreviewer.ydd_viewer import _is_shell_scratch_ydd, launch_ydd_viewer

            if not _is_shell_scratch_ydd(path):
                from ytdpreviewer.thumb_roots import append_thumb_root

                append_thumb_root(path.parent)
                launch_ydd_viewer(resolved)
            continue
        if ext == ".dds":
            from ytdpreviewer.dds_preview import launch_dds_preview

            launch_dds_preview(resolved)
            continue
        if ext == ".ytd":
            from ytdpreviewer.ytd_preview import launch_ytd_preview

            launch_ytd_preview(resolved)
            continue


if __name__ == "__main__":
    argv = sys.argv[1:]
    try:
        if _run_apply_update_cli(argv):
            raise SystemExit(0)
        if _run_thumbnail_cli(argv):
            raise SystemExit(0)
        if _run_ydd_thumbnail_cli(argv):
            raise SystemExit(0)
        from ytdpreviewer.export_main import run_export_cli

        if run_export_cli(argv):
            raise SystemExit(0)
        main()
    except SystemExit:
        raise
    except Exception as exc:
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                0,
                f"{exc}\n\n{traceback.format_exc()}",
                "YTD Previewer",
                0x10,
            )
        except Exception:
            traceback.print_exc()
        raise SystemExit(1) from exc
