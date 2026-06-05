"""Recompress textures and compute mipmap settings via texfury."""

from __future__ import annotations

from pathlib import Path

from PIL import Image
from texfury import BCFormat, Texture

# Форматы, удобные для GTA V / OpenIV
FORMAT_OPTIONS: list[tuple[str, BCFormat]] = [
    ("DXT1 (BC1)", BCFormat.BC1),
    ("DXT3 (BC2)", BCFormat.BC2),
    ("DXT5 (BC3)", BCFormat.BC3),
    ("BC4", BCFormat.BC4),
    ("BC5 (нормали)", BCFormat.BC5),
    ("BC7", BCFormat.BC7),
    ("A8R8G8B8", BCFormat.A8R8G8B8),
    ("R8G8B8A8", BCFormat.R8G8B8A8),
    ("B5G6R5", BCFormat.B5G6R5),
]

_FORMAT_BY_NAME = {fmt.name: fmt for _label, fmt in FORMAT_OPTIONS}
_FORMAT_LABEL = {fmt: label for label, fmt in FORMAT_OPTIONS}


def format_label(fmt: BCFormat) -> str:
    return _FORMAT_LABEL.get(fmt, fmt.name)


def parse_format(value: str) -> BCFormat:
    for label, fmt in FORMAT_OPTIONS:
        if value == label:
            return fmt
    if value in _FORMAT_BY_NAME:
        return _FORMAT_BY_NAME[value]
    return BCFormat[value]


def max_mip_count(width: int, height: int) -> int:
    count = 1
    dim = max(width, height)
    while dim > 1:
        dim //= 2
        count += 1
    return count


def min_mip_size_for_count(width: int, height: int, mip_count: int) -> int:
    """Подобрать min_mip_size для texfury, чтобы получить нужное число mip."""
    if mip_count <= 1:
        return max(width, height) + 1
    dim = max(width, height)
    return max(1, dim >> (mip_count - 1))


def _resize_rgba(pil: Image.Image, width: int, height: int) -> Image.Image:
    if pil.width == width and pil.height == height:
        return pil
    return pil.resize((width, height), Image.Resampling.LANCZOS)


def _pil_from_image_source(source: str | Path | Image.Image) -> Image.Image:
    if isinstance(source, Image.Image):
        return source.convert("RGBA")

    path = Path(source).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path}")

    if path.suffix.lower() == ".dds":
        dds_tex = Texture.from_dds(path)
        pil = dds_tex.to_pil(0)
        if pil is None:
            raise ValueError(f"Не удалось декодировать DDS: {path.name}")
        return pil.convert("RGBA")

    with Image.open(path) as img:
        return img.convert("RGBA")


def texture_from_pil(
    pil: Image.Image,
    *,
    name: str,
    fmt: BCFormat,
    mip_count: int,
    quality: float = 0.85,
) -> Texture:
    rgba = pil.convert("RGBA")
    mips = max(1, min(mip_count, max_mip_count(rgba.width, rgba.height)))
    return Texture.from_pil(
        rgba,
        format=fmt,
        quality=quality,
        generate_mipmaps=mips > 1,
        min_mip_size=min_mip_size_for_count(rgba.width, rgba.height, mips),
        resize_to_pot=False,
        name=name,
    )


def recompress_texture(
    tex: Texture,
    *,
    name: str,
    fmt: BCFormat,
    mip_count: int,
    width: int | None = None,
    height: int | None = None,
    quality: float = 0.85,
) -> Texture:
    pil = tex.to_pil(0)
    if pil is None:
        raise ValueError("Не удалось декодировать текстуру")
    if width is not None and height is not None:
        pil = _resize_rgba(pil, width, height)
    return texture_from_pil(
        pil,
        name=name or tex.name,
        fmt=fmt,
        mip_count=mip_count,
        quality=quality,
    )


def replace_texture_from_image(
    tex: Texture,
    source: str | Path | Image.Image,
    *,
    name: str | None = None,
    fmt: BCFormat | None = None,
    mip_count: int | None = None,
    width: int | None = None,
    height: int | None = None,
    quality: float = 0.85,
) -> Texture:
    """Replace texture pixels from PNG/JPG/BMP/TGA/DDS at the requested size."""
    pil = _pil_from_image_source(source)
    if width is not None and height is not None:
        pil = _resize_rgba(pil, width, height)

    use_name = (name or tex.name or "").strip() or tex.name
    use_fmt = fmt if fmt is not None else tex.format
    use_mips = mip_count if mip_count is not None else tex.mip_count
    return texture_from_pil(
        pil,
        name=use_name,
        fmt=use_fmt,
        mip_count=use_mips,
        quality=quality,
    )
