"""Flat texture thumbnails for .ydd (Explorer / CLI)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from ytdpreviewer.ydd_loader import (
    LOD_LEVELS,
    default_diffuse_texture_key,
    load_ydd,
    resolve_lod,
    texture_to_pil,
)
from ytdpreviewer.thumb_paths import read_cached_real_path
from ytdpreviewer.thumb_roots import append_thumb_root, load_thumb_roots
from ytdpreviewer.ytd_texture_preview import fit_max_side

MAX_THUMB_SIDE = 512
DEFAULT_THUMB_SIDE = 128


def placeholder_ydd_thumbnail(max_side: int) -> Image.Image:
    side = max(32, min(max_side, MAX_THUMB_SIDE))
    from ytdpreviewer.paths import assets_dir, default_install_dir

    for base in (default_install_dir() / "assets", assets_dir()):
        for name in ("ydd.ico", "app.ico"):
            ico = base / name
            if ico.is_file():
                try:
                    with Image.open(ico) as loaded:
                        img = loaded.convert("RGBA")
                        img.thumbnail((side, side), Image.Resampling.LANCZOS)
                        out = Image.new("RGBA", (side, side), (40, 44, 48, 255))
                        ox = (side - img.width) // 2
                        oy = (side - img.height) // 2
                        out.paste(img, (ox, oy), img)
                        return out
                except OSError:
                    pass
    return Image.new("RGBA", (side, side), (48, 52, 58, 255))


def _pick_lod(model, *, thumb: bool = False) -> str:
    order = ("med", "low", "high") if thumb else LOD_LEVELS
    for lod in order:
        if lod in model.available_lods:
            resolved = resolve_lod(model, lod)
            for drawable in model.drawables_for_lod(resolved):
                for mesh in drawable.meshes:
                    if mesh.indices and mesh.positions:
                        return resolved
    return resolve_lod(model, "med" if thumb else "high")


def _is_scratch_ydd(path: Path) -> bool:
    name = path.name.lower()
    return name.startswith("yddprev_") and path.suffix.lower() == ".tmp"


_SKIP_DIRS = frozenset(
    {
        "$recycle.bin",
        ".git",
        "appdata",
        "node_modules",
        "nuget",
        "packages",
        "program files",
        "program files (x86)",
        "system volume information",
        "windows",
    }
)


def _matches_scratch(candidate: Path, size: int, head: bytes) -> bool:
    try:
        if candidate.stat().st_size != size:
            return False
        return candidate.read_bytes()[:4096] == head
    except OSError:
        return False


def _scan_tree(start: Path, size: int, head: bytes, max_depth: int) -> Path | None:
    pending: list[tuple[Path, int]] = [(start, 0)]
    while pending:
        folder, depth = pending.pop(0)
        if folder.name.lower() in _SKIP_DIRS:
            continue
        try:
            for candidate in folder.glob("*.ydd"):
                if _matches_scratch(candidate, size, head):
                    return candidate
            if depth < max_depth:
                for sub in folder.iterdir():
                    if sub.is_dir():
                        pending.append((sub, depth + 1))
        except OSError:
            continue
    return None


def discover_scratch_source(scratch_ydd: Path) -> tuple[Path | None, Path | None]:
    """Return (texture_root, real .ydd path) for Explorer stream copies."""
    cached = read_cached_real_path(scratch_ydd)
    if cached is not None:
        return cached.parent, cached

    try:
        size = scratch_ydd.stat().st_size
        head = scratch_ydd.read_bytes()[:4096]
    except OSError:
        return None, None

    drives: set[str] = set()
    for root in load_thumb_roots():
        hit = _scan_tree(root, size, head, max_depth=8)
        if hit is not None:
            return hit.parent, hit
        drives.add(str(root.drive).upper())

    for drive in sorted(drives):
        if not drive:
            continue
        hit = _scan_tree(Path(f"{drive}\\"), size, head, max_depth=14)
        if hit is not None:
            append_thumb_root(hit.parent)
            return hit.parent, hit
    return None, None


def discover_texture_root(scratch_ydd: Path) -> Path | None:
    root, _ = discover_scratch_source(scratch_ydd)
    return root


def _bind_texture_search_dir(model, texture_root: Path | None) -> None:
    if texture_root is not None:
        model._texture_search_dir = texture_root.resolve()


def _resolve_scratch_context(
    path: Path,
    *,
    texture_root: Path | None,
    identity_ydd: Path | None,
) -> tuple[Path | None, Path | None]:
    root = texture_root
    identity = identity_ydd
    if _is_scratch_ydd(path):
        discovered_root, discovered_identity = discover_scratch_source(path)
        if root is None:
            root = discovered_root
        if identity is None:
            identity = discovered_identity
    return root, identity


def render_ydd_flat_thumbnail(
    ydd_path: str | Path,
    *,
    max_side: int = DEFAULT_THUMB_SIDE,
    texture_root: Path | None = None,
    identity_ydd: Path | None = None,
) -> Image.Image:
    """Fast Explorer preview: first diffuse texture (no OpenGL)."""
    path = Path(ydd_path).resolve()
    side = max(32, min(int(max_side), MAX_THUMB_SIDE))
    root, identity = _resolve_scratch_context(path, texture_root=texture_root, identity_ydd=identity_ydd)
    model = load_ydd(path, texture_root=root, identity_ydd=identity)
    _bind_texture_search_dir(model, root or path.parent)
    tex_key = default_diffuse_texture_key(model)
    if not tex_key:
        lod = _pick_lod(model, thumb=True)
        for drawable in model.drawables_for_lod(lod):
            for mesh in drawable.meshes:
                if mesh.texture_name:
                    tex_key = mesh.texture_name
                    break
            if tex_key:
                break
    if not tex_key:
        raise ValueError("В YDD нет текстур для превью")
    tex = model.resolve_texture(tex_key)
    if tex is None:
        raise ValueError(f"Текстура не найдена: {tex_key}")
    pil = texture_to_pil(tex)
    return fit_max_side(pil.convert("RGBA"), side, fast=True, allow_upscale=True)


def render_ydd_thumbnail_file(
    ydd_path: str | Path,
    out_path: str | Path,
    *,
    max_side: int = DEFAULT_THUMB_SIDE,
    texture_root: Path | None = None,
    identity_ydd: Path | None = None,
    allow_placeholder: bool = True,
) -> bool:
    """Render .ydd diffuse texture to PNG."""
    side = max(32, min(int(max_side), MAX_THUMB_SIDE))
    out = Path(out_path)
    path = Path(ydd_path).resolve()
    root, identity = _resolve_scratch_context(path, texture_root=texture_root, identity_ydd=identity_ydd)
    img: Image.Image | None = None
    try:
        img = render_ydd_flat_thumbnail(
            ydd_path, max_side=side, texture_root=root, identity_ydd=identity
        )
    except (ValueError, OSError, RuntimeError):
        img = None
    if img is None:
        if not allow_placeholder:
            return False
        img = placeholder_ydd_thumbnail(side)

    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(out, format="JPEG", quality=92)
        else:
            img.save(out, format="PNG")
        ok = out.is_file() and out.stat().st_size > 512
        if ok:
            if root is not None:
                append_thumb_root(root)
            elif path.suffix.lower() == ".ydd" and not _is_scratch_ydd(path):
                append_thumb_root(path.parent)
        return ok
    except OSError:
        return False
