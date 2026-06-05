"""Decode first texture from a .ytd file into a PIL image (thumbnails / shell)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

MAX_THUMB_SIDE = 1024


def thumb_mip_level(tex, max_side: int) -> int:
    """Largest mip whose longest side still fits *max_side* (fast path)."""
    return preview_mip_level(tex, max_side)


def preview_mip_level(tex, max_side: int) -> int:
    """Largest mip whose longest side still fits *max_side* (scale up mip 0 if texture is tiny)."""
    if tex.mip_count <= 1:
        return 0
    w, h = tex.width, tex.height
    target = max(max_side, 1)
    for mip in range(tex.mip_count):
        side = max(max(1, w >> mip), max(1, h >> mip))
        if side <= target:
            return mip
    return 0


def shell_mip_level(tex, max_side: int) -> int:
    """Always full-resolution mip 0 (texfury mip indices != bit-shift sizes)."""
    _ = max_side
    return 0


def pick_thumbnail_texture(textures: list) -> object:
    """Use the largest texture — first slot is not always the diffuse."""
    best = textures[0]
    best_area = int(getattr(best, "width", 0) or 0) * int(getattr(best, "height", 0) or 0)
    for tex in textures[1:]:
        area = int(getattr(tex, "width", 0) or 0) * int(getattr(tex, "height", 0) or 0)
        if area > best_area:
            best = tex
            best_area = area
    return best


def fit_max_side(
    img: Image.Image, max_side: int, *, fast: bool = False, allow_upscale: bool = True
) -> Image.Image:
    """Scale up or down so the image fits in a max_side × max_side box (keeps aspect ratio)."""
    if max_side <= 0:
        return img
    w, h = img.size
    if w < 1 or h < 1:
        return img
    scale = min(max_side / w, max_side / h)
    if scale > 1.0 and not allow_upscale:
        return img
    if abs(scale - 1.0) < 0.02:
        return img
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    if scale > 1.0 or not fast:
        resample = Image.Resampling.LANCZOS
    else:
        resample = Image.Resampling.BILINEAR
    return img.resize((nw, nh), resample)


def placeholder_thumbnail(max_side: int) -> Image.Image:
    """Fallback when YTD has no textures or decode fails (shell / Explorer)."""
    from ytdpreviewer.paths import assets_dir, default_install_dir

    side = max(32, min(max_side, MAX_THUMB_SIDE))
    for base in (default_install_dir() / "assets", assets_dir()):
        ico = base / "ytd.ico"
        if ico.is_file():
            try:
                with Image.open(ico) as loaded:
                    return fit_max_side(loaded.convert("RGBA"), side, fast=False)
            except OSError:
                pass
    return Image.new("RGBA", (side, side), (40, 44, 48, 255))


def first_texture_image(
    path: Path, *, max_side: int = 256, fast: bool = False, allow_upscale: bool = True
) -> Image.Image:
    from texfury import ITD

    ytd_path = Path(path).resolve()
    td = ITD.load(str(ytd_path))
    textures = list(td.textures)
    if not textures:
        raise ValueError("В YTD нет текстур")

    tex = pick_thumbnail_texture(textures)
    max_side = max(32, min(max_side, MAX_THUMB_SIDE))
    mip = thumb_mip_level(tex, max_side) if fast else shell_mip_level(tex, max_side)

    pil = tex.to_pil(mip)
    if pil is None:
        raise ValueError("Не удалось декодировать текстуру")

    img = pil.convert("RGBA")
    return fit_max_side(img, max_side, fast=fast, allow_upscale=allow_upscale)


def render_thumbnail_file(path: Path, out_path: Path, *, max_side: int = 256, fast: bool = False) -> bool:
    # Shell / cache: mip0 at native res (no 64×64 mip); never upscale small textures.
    side = MAX_THUMB_SIDE if not fast else max(32, min(max_side, MAX_THUMB_SIDE))
    try:
        img = first_texture_image(path, max_side=side, fast=fast, allow_upscale=False)
    except (ValueError, OSError, RuntimeError):
        img = placeholder_thumbnail(side)

    out = Path(out_path)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if out.suffix.lower() in (".jpg", ".jpeg"):
            img.convert("RGB").save(out, format="JPEG", quality=92)
        else:
            img.save(out, format="PNG")
        return out.is_file() and out.stat().st_size > 64
    except OSError:
        return False
