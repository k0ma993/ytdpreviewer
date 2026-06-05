"""Export YDD drawable geometry to Wavefront OBJ (+ optional MTL/PNG)."""

from __future__ import annotations

import re
from pathlib import Path

from ytdpreviewer.export_progress import ExportProgressCallback
from ytdpreviewer.ydd_loader import (
    LOD_LABELS,
    YddModel,
    _texture_key,
    load_ydd,
    resolve_lod,
    save_embedded_textures,
    texture_to_pil,
)

_SAFE_NAME_RE = re.compile(r"[^\w.\-]+")


def _safe_name(name: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", name.strip())
    return cleaned.strip("_") or "mesh"


def _gta_to_export_position(x: float, y: float, z: float) -> tuple[float, float, float]:
    """GTA/RAGE Z-up -> Y-up (same transform as the 3D viewer)."""
    return float(x), float(z), float(-y)


def _gta_to_export_normal(nx: float, ny: float, nz: float) -> tuple[float, float, float]:
    ex, ey, ez = _gta_to_export_position(nx, ny, nz)
    length = (ex * ex + ey * ey + ez * ez) ** 0.5
    if length < 1e-8:
        return 0.0, 1.0, 0.0
    return ex / length, ey / length, ez / length


def _mesh_texture_name(mesh, texture_override: str | None) -> str | None:
    if texture_override:
        return texture_override
    return mesh.texture_name


def export_ydd_to_obj(
    model: YddModel,
    output_path: str | Path,
    *,
    lod: str | None = None,
    texture_override: str | None = None,
    export_textures: bool = True,
) -> Path:
    """Write geometry for the chosen LOD to ``output_path`` (.obj).

    Creates ``.mtl`` and diffuse ``.png`` maps next to the OBJ when textures resolve.
    Returns the written OBJ path.
    """
    target = Path(output_path).resolve()
    if target.suffix.lower() != ".obj":
        target = target.with_suffix(".obj")

    resolved_lod = resolve_lod(model, lod or "high")
    drawables = model.drawables_for_lod(resolved_lod)
    if not drawables or not any(mesh.indices for d in drawables for mesh in d.meshes):
        raise ValueError("Нет геометрии для экспорта")

    target.parent.mkdir(parents=True, exist_ok=True)
    mtl_name = f"{target.stem}.mtl"
    mtl_path = target.with_name(mtl_name)

    materials: dict[str, str] = {}
    obj_lines: list[str] = [
        "# YTD Previewer OBJ export",
        f"# Source: {model.path.name}",
        f"# LOD: {LOD_LABELS.get(resolved_lod, resolved_lod)}",
        f"mtllib {mtl_name}",
        "",
    ]
    mtl_lines: list[str] = ["# YTD Previewer MTL export", ""]

    # OBJ face indices are global for the whole file, not per ``o`` group.
    vertex_base = 0

    for drawable in drawables:
        for mesh in drawable.meshes:
            if not mesh.positions or not mesh.indices:
                continue

            object_name = _safe_name(mesh.name or drawable.name)
            obj_lines.append(f"o {object_name}")

            tex_name = _mesh_texture_name(mesh, texture_override)
            mat_key = _texture_key(tex_name) if tex_name else "default"
            mat_name = _safe_name(mat_key)

            if mat_name not in materials:
                map_line = ""
                if export_textures and tex_name:
                    texture = model.resolve_texture(tex_name)
                    if texture is not None:
                        png_name = f"{target.stem}_{mat_name}.png"
                        png_path = target.with_name(png_name)
                        image = texture_to_pil(texture)
                        image.save(png_path, format="PNG")
                        map_line = f"map_Kd {png_name}"
                materials[mat_name] = map_line
                mtl_lines.append(f"newmtl {mat_name}")
                mtl_lines.append("Ka 0.2 0.2 0.2")
                mtl_lines.append("Kd 0.8 0.8 0.8")
                mtl_lines.append("Ks 0.0 0.0 0.0")
                mtl_lines.append("d 1.0")
                if map_line:
                    mtl_lines.append(map_line)
                mtl_lines.append("")

            obj_lines.append(f"usemtl {mat_name}")

            positions = list(mesh.positions)
            normals = list(mesh.normals)
            uvs = list(mesh.uvs)
            if len(normals) != len(positions):
                normals = [(0.0, 0.0, 1.0)] * len(positions)
            if len(uvs) != len(positions):
                uvs = [(0.0, 0.0)] * len(positions)

            for x, y, z in positions:
                ex, ey, ez = _gta_to_export_position(x, y, z)
                obj_lines.append(f"v {ex:.6f} {ey:.6f} {ez:.6f}")

            for nx, ny, nz in normals:
                enx, eny, enz = _gta_to_export_normal(nx, ny, nz)
                obj_lines.append(f"vn {enx:.6f} {eny:.6f} {enz:.6f}")

            # Same UVs as the viewer (already converted in ydd_loader).
            for u, v in uvs:
                obj_lines.append(f"vt {float(u):.6f} {float(v):.6f}")

            for i in range(0, len(mesh.indices), 3):
                ia, ib, ic = mesh.indices[i], mesh.indices[i + 1], mesh.indices[i + 2]
                a = ia + 1 + vertex_base
                b = ib + 1 + vertex_base
                c = ic + 1 + vertex_base
                obj_lines.append(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}")

            vertex_base += len(positions)
            obj_lines.append("")

    target.write_text("\n".join(obj_lines), encoding="utf-8")
    if materials:
        mtl_path.write_text("\n".join(mtl_lines), encoding="utf-8")
    elif mtl_path.is_file():
        mtl_path.unlink()

    return target


def export_ydd_file_to_obj(ydd_path: str | Path, *, lod: str = "high") -> Path:
    """Load a YDD and write ``<stem>_<lod>.obj`` next to the source file."""
    source = Path(ydd_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")
    model = load_ydd(source)
    resolved = resolve_lod(model, lod)
    output = source.with_name(f"{source.stem}_{resolved}.obj")
    return export_ydd_to_obj(model, output, lod=resolved)


def export_ydd_file_textures(
    ydd_path: str | Path,
    *,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[Path, int]:
    """Export textures (embedded + matching .ytd nearby) to ``<stem>_textures/``."""
    source = Path(ydd_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Файл не найден: {source}")
    model = load_ydd(source)
    return save_embedded_textures(model, on_progress=on_progress)


def export_ydd_batch_obj(
    paths: list[str | Path],
    *,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[int, Path | None, list[Path], list[str]]:
    """Export several YDD files to OBJ. Returns (file_count, folder, outputs, errors)."""
    exported = 0
    folder: Path | None = None
    outputs: list[Path] = []
    errors: list[str] = []

    total = len(paths)
    for index, raw in enumerate(paths):
        source = Path(raw)
        try:
            if on_progress is not None:
                on_progress(index + 1, total, f"OBJ {index + 1} из {total}: {source.name}")
            out = export_ydd_file_to_obj(raw)
            exported += 1
            outputs.append(out)
            if folder is None:
                folder = out.parent
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")

    if exported == 0 and errors:
        raise RuntimeError("\n".join(errors))

    return exported, folder, outputs, errors


def export_ydd_batch_textures(
    paths: list[str | Path],
    *,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[int, int, Path | None, list[str]]:
    """Export embedded textures from several YDD files."""
    exported_files = 0
    total_textures = 0
    folder: Path | None = None
    errors: list[str] = []

    file_total = len(paths)
    per_texture = on_progress if file_total == 1 else None

    def _file_progress(file_index: int, message: str) -> None:
        if on_progress is not None:
            on_progress(file_index + 1, file_total, message)

    for file_index, raw in enumerate(paths):
        source = Path(raw)
        try:
            if on_progress is not None and file_total > 1:
                _file_progress(file_index, f"YDD {file_index + 1} из {file_total}: {source.name}")
            out_dir, count = export_ydd_file_textures(raw, on_progress=per_texture)
            exported_files += 1
            total_textures += count
            if folder is None:
                folder = out_dir.parent
        except Exception as exc:
            errors.append(f"{source.name}: {exc}")

    if exported_files == 0 and errors:
        raise RuntimeError("\n".join(errors))

    return total_textures, exported_files, folder, errors


def notify_ydd_export_result(
    path: Path | None = None,
    *,
    count: int | None = None,
    file_count: int | None = None,
    errors: list[str] | None = None,
    error: str | None = None,
    title: str = "YTD Previewer — экспорт OBJ",
) -> None:
    try:
        import ctypes

        if error:
            ctypes.windll.user32.MessageBoxW(0, error, title, 0x10)
            return

        lines: list[str] = []
        if file_count is not None and file_count > 1:
            lines.append(f"Файлов YDD: {file_count}")
            if count is not None:
                lines.append(f"Текстур: {count}")
        elif count is not None and path is not None:
            lines.append(f"Экспортировано текстур: {count}")
        elif path is not None:
            lines.append("Модель сохранена:")
        else:
            lines.append("Готово")

        if path is not None:
            lines.append("")
            lines.append(str(path))

        if errors:
            lines.append("")
            lines.append("Ошибки:")
            lines.extend(errors[:8])
            if len(errors) > 8:
                lines.append(f"… и ещё {len(errors) - 8}")

        icon = 0x30 if errors else 0x40
        ctypes.windll.user32.MessageBoxW(0, "\n".join(lines), title, icon)
    except Exception:
        pass
