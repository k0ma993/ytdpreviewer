"""Extract drawable geometry and embedded textures from a .ydd file."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ytdpreviewer.export_progress import ExportProgressCallback
from ytdpreviewer.fivefury_bootstrap import read_ydd

LOD_LEVELS = ("high", "med", "low")
LOD_LABELS = {"high": "High", "med": "Medium", "low": "Low"}


Colour4 = tuple[float, float, float, float]


@dataclass
class DrawableMesh:
    name: str
    positions: list[tuple[float, float, float]] = field(default_factory=list)
    normals: list[tuple[float, float, float]] = field(default_factory=list)
    uvs: list[tuple[float, float]] = field(default_factory=list)
    colours0: list[Colour4] = field(default_factory=list)
    colours1: list[Colour4] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)
    texture_name: str | None = None
    material_name: str | None = None
    vertex_count: int = 0
    triangle_count: int = 0

    @property
    def has_vertex_colours(self) -> bool:
        return bool(self.colours0) or bool(self.colours1)


def format_vertex_colour(rgba: Colour4) -> str:
    """Human-readable RGBA for UI (byte 0–255 + normalized)."""
    byte_line, float_line = format_vertex_colour_lines(rgba)
    return f"{byte_line}  {float_line}"


def format_vertex_colour_lines(rgba: Colour4) -> tuple[str, str]:
    """Two short lines for narrow UI panels."""
    r, g, b, a = (max(0.0, min(1.0, float(c))) for c in rgba)
    br, bg, bb, ba = (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)), int(round(a * 255)))
    return (
        f"R={br} G={bg} B={bb} A={ba}",
        f"({r:.3f}, {g:.3f}, {b:.3f}, {a:.3f})",
    )


def model_vertex_colour_stats(model: YddModel, *, lod: str = "high") -> tuple[int, int, Colour4 | None]:
    """Return (meshes_with_colours, total_coloured_vertices, sample_rgba)."""
    meshes_with = 0
    total_verts = 0
    sample: Colour4 | None = None
    for drawable in model.drawables_for_lod(resolve_lod(model, lod)):
        for mesh in drawable.meshes:
            channel = mesh.colours0 if mesh.colours0 else mesh.colours1
            if len(channel) != mesh.vertex_count:
                continue
            meshes_with += 1
            total_verts += mesh.vertex_count
            if sample is None and channel:
                sample = channel[0]
    return meshes_with, total_verts, sample


@dataclass
class DrawableModel:
    name: str
    meshes: list[DrawableMesh] = field(default_factory=list)
    texture_names: list[str] = field(default_factory=list)
    vertex_count: int = 0
    triangle_count: int = 0

    @property
    def has_geometry(self) -> bool:
        return any(mesh.indices for mesh in self.meshes)


@dataclass
class YddModel:
    path: Path
    drawables_by_lod: dict[str, list[DrawableModel]] = field(default_factory=dict)
    embedded_textures: dict[str, object] = field(default_factory=dict)
    external_textures: dict[str, object] = field(default_factory=dict)
    external_ytd_files: list[Path] = field(default_factory=list)

    @property
    def available_lods(self) -> list[str]:
        return [lod for lod in LOD_LEVELS if self.drawables_by_lod.get(lod)]

    def drawables_for_lod(self, lod: str) -> list[DrawableModel]:
        resolved = resolve_lod(self, lod)
        return list(self.drawables_by_lod.get(resolved, []))

    @property
    def drawables(self) -> list[DrawableModel]:
        return self.drawables_for_lod("high")

    @property
    def total_vertices(self) -> int:
        return sum(item.vertex_count for item in self.drawables)

    @property
    def total_triangles(self) -> int:
        return sum(item.triangle_count for item in self.drawables)

    def resolve_texture(self, name: str | None) -> object | None:
        if not name:
            return default_diffuse_texture(self)
        key = _texture_key(name)
        if key in self.embedded_textures:
            return self.embedded_textures[key]
        if key in self.external_textures:
            return self.external_textures[key]
        search_dir = getattr(self, "_texture_search_dir", None) or self.path.parent
        ensure_external_texture(search_dir, name, self.external_textures, self.external_ytd_files)
        if key in self.external_textures:
            return self.external_textures[key]
        if _is_placeholder_texture_key(key):
            return default_diffuse_texture(self)
        return None


def resolve_lod(model: YddModel, lod: str) -> str:
    normalized = lod if lod in LOD_LEVELS else "high"
    if model.drawables_by_lod.get(normalized):
        return normalized
    for fallback in LOD_LEVELS:
        if model.drawables_by_lod.get(fallback):
            return fallback
    return normalized


def next_lod(model: YddModel, current: str) -> str:
    available = model.available_lods
    if not available:
        return current
    resolved = resolve_lod(model, current)
    if resolved not in available:
        return available[0]
    index = available.index(resolved)
    return available[(index + 1) % len(available)]


def _texture_key(name: str) -> str:
    return Path(name).stem.lower()


_PLACEHOLDER_TEXTURE_KEYS = frozenset(
    {"color", "givemechecker", "default", "none", "placeholder", "grey", "gray"}
)
_SKIP_TEXTURE_TOKENS = ("normal", "spec", "bump", "detail", "checker", "noise", "wet", "wrinkle")

_YDD_STEM_RE = re.compile(r"^(.+)_(\d{3})(?:_[a-z])?$")
_TEXTURE_INDEX_RE = re.compile(r"^(.+?)_(?:diff|normal|spec|bump|wrinkle)_(\d{3})(?:_|$)")


def _is_placeholder_texture_key(key: str) -> bool:
    return key in _PLACEHOLDER_TEXTURE_KEYS


def _is_auxiliary_texture_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in _SKIP_TEXTURE_TOKENS)


def ydd_identity_stem(model: YddModel) -> str:
    override = getattr(model, "_identity_stem", None)
    if override:
        return str(override)
    return model.path.stem


def bind_ydd_identity(model: YddModel, identity_ydd: str | Path | None) -> None:
    if identity_ydd is None:
        return
    path = Path(identity_ydd)
    if path.suffix.lower() == ".ydd":
        model._identity_stem = path.stem


def _external_diffuse_texture_keys(model: YddModel) -> list[str]:
    ydd_stem = ydd_identity_stem(model)
    diff_keys = sorted(
        key
        for key in model.external_textures
        if "diff" in key and _texture_matches_ydd(key, ydd_stem, set())
    )
    if diff_keys:
        return diff_keys
    return sorted(key for key in model.external_textures if not _is_auxiliary_texture_key(key))


def default_diffuse_texture_key(model: YddModel) -> str | None:
    keys = _external_diffuse_texture_keys(model)
    if keys:
        return keys[0]
    for key in sorted(model.embedded_textures):
        if not _is_auxiliary_texture_key(key):
            return key
    return None


def default_diffuse_texture(model: YddModel) -> object | None:
    key = default_diffuse_texture_key(model)
    if key is None:
        return None
    if key in model.external_textures:
        return model.external_textures[key]
    return model.embedded_textures.get(key)


def _slot_label(*names: str | None) -> str:
    return " ".join(part for part in names if part).lower()


def _material_texture_names(material) -> list[str]:
    if material is None:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for param in material.parameters:
        if not param.is_texture or param.texture is None or not param.texture.name:
            continue
        key = _texture_key(param.texture.name)
        if key not in seen:
            seen.add(key)
            names.append(param.texture.name)
    for texture in material.textures:
        if not texture.name:
            continue
        key = _texture_key(texture.name)
        if key not in seen:
            seen.add(key)
            names.append(texture.name)
    return names


def _is_diffuse_slot(*names: str | None) -> bool:
    slot = _slot_label(*names)
    return "diffuse" in slot or "albedo" in slot or "texturesampler" in slot


def _param_uv_index(param) -> int:
    uv_index = getattr(param, "uv_index", None)
    if uv_index is not None:
        return int(uv_index)
    texture = getattr(param, "texture", None)
    if texture is not None and getattr(texture, "uv_index", None) is not None:
        return int(texture.uv_index)
    return 0


def _mesh_diffuse_info(material) -> tuple[str | None, int]:
    if material is None:
        return None, 0
    for param in material.parameters:
        if not param.is_texture or param.texture is None or not param.texture.name:
            continue
        if _is_diffuse_slot(param.name, param.texture.parameter_name):
            return param.texture.name, _param_uv_index(param)
    for texture in material.textures:
        if not texture.name:
            continue
        if _is_diffuse_slot(texture.parameter_name):
            return texture.name, int(texture.uv_index or 0)
    names = _material_texture_names(material)
    if names:
        return names[0], 0
    return material.primary_texture_name, 0


def _mesh_texture_name(material) -> str | None:
    name, _ = _mesh_diffuse_info(material)
    return name


def _gta_uv_to_gl(u: float, v: float) -> tuple[float, float]:
    """RAGE/D3D texcoords -> OpenGL.

    Ped pieces like hands store V in 0..1 and must stay as-is.
    Other clothing often uses negative V; convert with ``1 + v``.
    """
    u = float(u)
    v = float(v)
    if v <= 0.0:
        v = 1.0 + v
    return u, v


def _mesh_uvs(mesh, material) -> list[tuple[float, float]]:
    count = len(mesh.positions)
    _, uv_index = _mesh_diffuse_info(material)
    if mesh.texcoords:
        if uv_index < len(mesh.texcoords) and mesh.texcoords[uv_index]:
            channel = mesh.texcoords[uv_index]
            if len(channel) == count:
                return [_gta_uv_to_gl(u, v) for u, v in channel]
        for channel in mesh.texcoords:
            if channel and len(channel) == count:
                return [_gta_uv_to_gl(u, v) for u, v in channel]
    return [(0.0, 0.0)] * count


def _collect_embedded_textures(drawable, bucket: dict[str, object]) -> None:
    lib = drawable.embedded_textures
    if lib is None:
        return
    for texture in lib.textures:
        _register_texture(bucket, texture.name, texture)


def _register_texture(bucket: dict[str, object], name: str, texture: object) -> None:
    bucket.setdefault(_texture_key(name), texture)


def _register_ytd_stem_aliases(bucket: dict[str, object], ytd_path: Path, textures: list) -> None:
    stem = ytd_path.stem.lower()
    if not textures:
        return
    exact = next((tex for tex in textures if _texture_key(tex.name) == stem), None)
    if exact is not None:
        bucket.setdefault(stem, exact)
        return
    if len(textures) == 1:
        bucket.setdefault(stem, textures[0])


def _merge_ytd_file(
    ytd_path: Path,
    bucket: dict[str, object],
    loaded_files: list[Path],
) -> None:
    resolved = ytd_path.resolve()
    if resolved in loaded_files:
        return
    from texfury import ITD

    try:
        td = ITD.load(ytd_path)
    except Exception:
        return
    loaded_files.append(resolved)
    textures = list(td.textures)
    for texture in textures:
        _register_texture(bucket, texture.name, texture)
    _register_ytd_stem_aliases(bucket, ytd_path, textures)


def load_external_ytd_textures(
    folder: Path,
    ydd_stem: str,
    referenced_names: set[str] | None = None,
) -> tuple[dict[str, object], list[Path]]:
    bucket: dict[str, object] = {}
    loaded_files: list[Path] = []
    if not folder.is_dir():
        return bucket, loaded_files

    referenced = {_texture_key(name) for name in (referenced_names or set())}

    priority_names = {Path(ydd_stem).stem.lower(), *referenced}
    ytd_files = sorted(
        (
            path
            for path in folder.glob("*.ytd")
            if _ytd_path_matches_ydd(path, ydd_stem, referenced)
        ),
        key=lambda path: (
            path.stem.lower() not in priority_names,
            path.stem.lower() != Path(ydd_stem).stem.lower(),
            path.name.lower(),
        ),
    )
    for ytd_path in ytd_files:
        _merge_ytd_file(ytd_path, bucket, loaded_files)

    for name in referenced_names or ():
        ensure_external_texture(folder, name, bucket, loaded_files)

    return bucket, loaded_files


def ensure_external_texture(
    folder: Path,
    name: str,
    bucket: dict[str, object],
    loaded_files: list[Path],
) -> None:
    key = _texture_key(name)
    if key in bucket:
        return
    if not folder.is_dir():
        return

    direct = folder / f"{Path(name).stem}.ytd"
    if direct.is_file():
        _merge_ytd_file(direct, bucket, loaded_files)
        if key in bucket:
            return

    for ytd_path in folder.glob("*.ytd"):
        if ytd_path.stem.lower() != key:
            continue
        _merge_ytd_file(ytd_path, bucket, loaded_files)
        if key in bucket:
            return


def _parse_ydd_identity(stem: str) -> tuple[str, str | None]:
    """Component + 3-digit drawable index from ``hand_000_u`` or ``p_head_001``."""
    normalized = Path(stem).stem.lower()
    match = _YDD_STEM_RE.match(normalized)
    if match:
        return match.group(1), match.group(2)
    return normalized.split("_", 1)[0], None


def _parse_texture_identity(key: str) -> tuple[str, str | None]:
    normalized = _texture_key(key)
    match = _TEXTURE_INDEX_RE.match(normalized)
    if match:
        return match.group(1), match.group(2)
    return normalized.split("_", 1)[0], None


def _ydd_component_prefix(ydd_stem: str) -> str:
    return _parse_ydd_identity(ydd_stem)[0]


def _referenced_texture_keys(
    drawables_by_lod: dict[str, list[DrawableModel]],
    *,
    lod: str | None = None,
) -> set[str]:
    keys: set[str] = set()
    lod_names = [lod] if lod else list(drawables_by_lod.keys())
    for lod_name in lod_names:
        for drawable in drawables_by_lod.get(lod_name, []):
            for name in drawable.texture_names:
                key = _texture_key(name)
                if not _is_placeholder_texture_key(key):
                    keys.add(key)
            for mesh in drawable.meshes:
                if mesh.texture_name:
                    key = _texture_key(mesh.texture_name)
                    if not _is_placeholder_texture_key(key):
                        keys.add(key)
    return keys


def _texture_matches_ydd(key: str, ydd_stem: str, referenced_keys: set[str]) -> bool:
    if _is_placeholder_texture_key(key) or _is_auxiliary_texture_key(key):
        return False
    if key in referenced_keys:
        ydd_component, ydd_index = _parse_ydd_identity(ydd_stem)
        tex_component, tex_index = _parse_texture_identity(key)
        if tex_component != ydd_component:
            return False
        if ydd_index is not None and tex_index is not None:
            return ydd_index == tex_index
        return True

    ydd_component, ydd_index = _parse_ydd_identity(ydd_stem)
    tex_component, tex_index = _parse_texture_identity(key)
    if tex_component != ydd_component:
        return False
    if ydd_index is not None and tex_index is not None:
        return ydd_index == tex_index
    return key.startswith(f"{ydd_component}_")


def _ytd_path_matches_ydd(ytd_path: Path, ydd_stem: str, referenced_keys: set[str]) -> bool:
    stem = ytd_path.stem.lower()
    if stem in referenced_keys:
        return True
    return _texture_matches_ydd(stem, ydd_stem, referenced_keys)


def _build_drawable_model(entry, drawable, lod: str) -> DrawableModel | None:
    meshes: list[DrawableMesh] = []
    drawable_verts = 0
    drawable_tris = 0
    texture_names: list[str] = []
    drawable_name = entry.name or "drawable"

    for mesh_index, mesh in enumerate(drawable.iter_meshes(lod=lod)):
        if not mesh.positions or not mesh.indices:
            continue

        material = mesh.material
        mesh_texture = _mesh_texture_name(material)
        for texture_name in _material_texture_names(material):
            if texture_name not in texture_names:
                texture_names.append(texture_name)

        triangle_count = len(mesh.indices) // 3
        normals = list(mesh.normals)
        if len(normals) != len(mesh.positions):
            normals = [(0.0, 1.0, 0.0)] * len(mesh.positions)

        colours0 = list(mesh.colours0) if len(mesh.colours0) == len(mesh.positions) else []
        colours1 = list(mesh.colours1) if len(mesh.colours1) == len(mesh.positions) else []

        meshes.append(
            DrawableMesh(
                name=f"{drawable_name}_{lod}_{mesh_index}",
                positions=list(mesh.positions),
                normals=normals,
                uvs=_mesh_uvs(mesh, material),
                colours0=colours0,
                colours1=colours1,
                indices=list(mesh.indices),
                texture_name=mesh_texture,
                material_name=material.name if material is not None else None,
                vertex_count=len(mesh.positions),
                triangle_count=triangle_count,
            )
        )
        drawable_verts += len(mesh.positions)
        drawable_tris += triangle_count

    if not meshes:
        return None

    return DrawableModel(
        name=drawable_name,
        meshes=meshes,
        texture_names=texture_names,
        vertex_count=drawable_verts,
        triangle_count=drawable_tris,
    )


def load_ydd(
    path: str | Path,
    *,
    texture_root: str | Path | None = None,
    identity_ydd: str | Path | None = None,
) -> YddModel:
    source = Path(path).resolve()
    ydd = read_ydd(str(source))
    drawables_by_lod: dict[str, list[DrawableModel]] = {lod: [] for lod in LOD_LEVELS}
    embedded: dict[str, object] = {}

    for entry in ydd.iter_drawables():
        drawable = entry.drawable
        _collect_embedded_textures(drawable, embedded)
        for lod in LOD_LEVELS:
            model = _build_drawable_model(entry, drawable, lod)
            if model is not None:
                drawables_by_lod[lod].append(model)

    referenced = _referenced_texture_keys(drawables_by_lod)
    identity_stem = Path(identity_ydd).stem if identity_ydd is not None else source.stem
    search_dir = Path(texture_root).resolve() if texture_root is not None else source.parent
    external, external_files = load_external_ytd_textures(search_dir, identity_stem, referenced)

    model = YddModel(
        path=source,
        drawables_by_lod=drawables_by_lod,
        embedded_textures=embedded,
        external_textures=external,
        external_ytd_files=external_files,
    )
    bind_ydd_identity(model, identity_ydd)
    return model


def add_ytd_to_model(model: YddModel, ytd_path: str | Path) -> list[str]:
    path = Path(ytd_path).resolve()
    before = set(model.external_textures.keys())
    _merge_ytd_file(path, model.external_textures, model.external_ytd_files)
    added = [key for key in model.external_textures.keys() if key not in before]
    return sorted(added, key=str.lower)


def all_texture_names(model: YddModel, lod: str = "high") -> list[str]:
    referenced = _referenced_texture_keys(model.drawables_by_lod, lod=lod)
    ydd_stem = ydd_identity_stem(model)

    names: set[str] = set()
    for key in referenced:
        if _texture_matches_ydd(key, ydd_stem, referenced):
            names.add(key)

    for key in model.embedded_textures:
        if _texture_matches_ydd(key, ydd_stem, referenced):
            names.add(key)

    for key in model.external_textures:
        if _texture_matches_ydd(key, ydd_stem, referenced):
            names.add(key)

    names.difference_update(_PLACEHOLDER_TEXTURE_KEYS)
    return sorted(names, key=str.lower)


def texture_to_pil(texture):
    from texfury import Texture as TexTexture

    if isinstance(texture, TexTexture):
        return texture.to_pil()
    data = texture.to_dds_bytes()
    tex = TexTexture.from_dds_bytes(data, name=getattr(texture, "name", ""))
    return tex.to_pil()


def _textures_for_export(model: YddModel) -> dict[str, object]:
    """Embedded + external + referenced textures (deduped by key)."""
    bucket: dict[str, object] = {}
    for key, texture in model.embedded_textures.items():
        bucket.setdefault(key, texture)
    for key, texture in model.external_textures.items():
        bucket.setdefault(key, texture)
    for name in all_texture_names(model):
        texture = model.resolve_texture(name)
        if texture is not None:
            bucket.setdefault(_texture_key(name), texture)
    return bucket


def save_embedded_textures(
    model: YddModel,
    target_dir: str | Path | None = None,
    *,
    on_progress: ExportProgressCallback | None = None,
) -> tuple[Path, int]:
    import re

    safe_stem_re = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    def safe_stem(name: str, fallback: str) -> str:
        cleaned = safe_stem_re.sub("_", name.strip()).strip(" .")
        return cleaned or fallback

    target = Path(target_dir) if target_dir is not None else model.path.parent / f"{model.path.stem}_textures"
    target.mkdir(parents=True, exist_ok=True)

    to_export = _textures_for_export(model)
    if not to_export:
        raise ValueError(
            "В YDD нет текстур для экспорта (ни встроенных, ни в соседних .ytd в той же папке)."
        )

    used: dict[str, int] = {}
    written = 0
    keys = sorted(to_export, key=str.lower)
    total = len(keys)
    for index, key in enumerate(keys):
        texture = to_export[key]
        raw_name = getattr(texture, "name", None) or key
        if on_progress is not None:
            on_progress(index + 1, total, f"{model.path.name}: {raw_name}")
        stem = safe_stem(str(raw_name), str(key))
        count = used.get(stem, 0)
        used[stem] = count + 1
        if count:
            stem = f"{stem}_{count + 1}"

        try:
            image = texture_to_pil(texture)
            image.save(target / f"{stem}.png", format="PNG")
            if hasattr(texture, "save_dds"):
                texture.save_dds(target / f"{stem}.dds")
            written += 1
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"Не удалось сохранить «{raw_name}»: {exc}") from exc

    return target, written
