"""Export all textures from a .ytd file to PNG."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from texfury import ITD

from ytdpreviewer.export_progress import ExportProgressCallback

_SAFE_STEM_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_stem(name: str, fallback: str) -> str:
    cleaned = _SAFE_STEM_RE.sub("_", name.strip())
    cleaned = cleaned.strip(" .")
    return cleaned or fallback


def _flat_png_stem(ytd_stem: str, texture_stem: str) -> str:
    if texture_stem.lower() == ytd_stem.lower():
        return texture_stem
    return f"{ytd_stem}_{texture_stem}"


def export_ytd_to_png(
    ytd_path: str | Path,
    *,
    out_dir: Path | None = None,
    flat: bool = False,
    used_names: dict[str, int] | None = None,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[Path, int]:
    """Write every texture in the YTD to PNG files.

    Default output: ``<ytd_dir>/<stem>_png/``.
    With *out_dir* and *flat*: all PNG files directly in *out_dir*.
    """
    source = Path(ytd_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")

    td = ITD.load(str(source))
    textures = list(td.textures)
    if not textures:
        raise ValueError("В YTD нет текстур")

    if out_dir is None:
        target = source.parent / f"{source.stem}_png"
    else:
        target = Path(out_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)

    used = used_names if used_names is not None else {}
    written = 0
    total = len(textures)
    for index, texture in enumerate(textures):
        raw_name = getattr(texture, "name", None) or f"texture_{index:03d}"
        if on_progress is not None:
            on_progress(
                index + 1,
                total,
                f"{source.name}: {raw_name}",
            )
        stem = _safe_stem(str(raw_name), f"texture_{index:03d}")
        file_stem = _flat_png_stem(source.stem, stem) if flat else stem
        count = used.get(file_stem, 0)
        used[file_stem] = count + 1
        if count:
            file_stem = f"{file_stem}_{count + 1}"
        png_path = target / f"{file_stem}.png"
        texture.to_pil().save(png_path, format="PNG")
        written += 1

    return target, written


def export_ytd_batch(
    paths: list[str | Path],
    *,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[int, int, Path | None, list[str]]:
    """Export one or more YTD files. Returns (texture_count, file_count, root_folder, errors)."""
    sources = [Path(path).resolve() for path in paths]
    sources = [path for path in sources if path.suffix.lower() == ".ytd"]
    if not sources:
        raise ValueError("Не выбрано ни одного .ytd")

    layout = "separate"
    single_root: Path | None = None
    if len(sources) > 1:
        from ytdpreviewer.win_dialog import ask_ytd_batch_layout

        layout = ask_ytd_batch_layout(len(sources))
        if layout is None:
            return 0, 0, None, []
        if layout == "single":
            from ytdpreviewer.win_dialog import pick_folder

            initial = sources[0].parent
            single_root = pick_folder("Папка для экспорта PNG", initial)
            if single_root is None:
                return 0, 0, None, []

    total_textures = 0
    exported_files = 0
    errors: list[str] = []
    summary_folder: Path | None = None
    shared_names: dict[str, int] = {}

    file_total = len(sources)
    per_texture = on_progress if file_total == 1 else None
    for file_index, source in enumerate(sources):
        try:
            if on_progress is not None:
                on_progress(
                    file_index + 1,
                    file_total,
                    f"Файл {file_index + 1} из {file_total}: {source.name}",
                )

            if layout == "single":
                folder, count = export_ytd_to_png(
                    source,
                    out_dir=single_root,
                    flat=True,
                    used_names=shared_names,
                    on_progress=per_texture,
                )
            else:
                folder, count = export_ytd_to_png(source, on_progress=per_texture)
            total_textures += count
            exported_files += 1
            if len(sources) == 1:
                summary_folder = folder
            elif layout == "single" and summary_folder is None:
                summary_folder = single_root
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")

    if exported_files == 0 and errors:
        raise RuntimeError("\n".join(errors))

    return total_textures, exported_files, summary_folder, errors


def notify_export_result(
    folder: Path | None,
    count: int,
    *,
    file_count: int = 1,
    errors: list[str] | None = None,
    error: str | None = None,
) -> None:
    try:
        import ctypes

        if error:
            ctypes.windll.user32.MessageBoxW(0, error, "YTD Previewer — экспорт PNG", 0x10)
            return

        lines = [f"Файлов YTD: {file_count}", f"Текстур: {count}"]
        if folder is not None:
            lines.append("")
            lines.append(str(folder))
        if errors:
            lines.append("")
            lines.append("Ошибки:")
            lines.extend(errors[:8])
            if len(errors) > 8:
                lines.append(f"… и ещё {len(errors) - 8}")
        ctypes.windll.user32.MessageBoxW(
            0,
            "\n".join(lines),
            "YTD Previewer — экспорт PNG",
            0x40 if not errors else 0x30,
        )
    except Exception:
        pass
