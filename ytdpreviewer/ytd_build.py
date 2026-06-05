"""Build GTA V .ytd files from images with naming and mip rules."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image
from texfury import BCFormat, ITD, Texture

from ytdpreviewer.texture_edit import (
    FORMAT_OPTIONS,
    min_mip_size_for_count,
    parse_format,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff", ".dds"}
_SAFE_STEM_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# max(width, height) -> mip level count
MIP_COUNT_BY_MAX_SIDE: tuple[tuple[int, int], ...] = (
    (4096, 11),
    (2048, 10),
    (1024, 9),
    (512, 8),
    (256, 7),
    (128, 6),
    (64, 5),
    (32, 4),
    (16, 3),
    (8, 2),
    (4, 1),
)

GTA_COMPONENT_ENTRIES: tuple[tuple[str, str], ...] = (
    ("berd", "маски"),
    ("uppr", "торс / руки / перчатки"),
    ("lowr", "штаны"),
    ("hand", "сумки / парашюты"),
    ("feet", "обувь"),
    ("teef", "цепи / шарфы / галстуки"),
    ("accs", "футболка под верхом"),
    ("task", "броня / разгрузки / жилеты"),
    ("decl", "декали / нашивки / принты"),
    ("jbib", "верх / куртки / худи / рубашки / кофты"),
    ("p_head", "шапки / кепки / шлемы"),
    ("p_eyes", "очки"),
    ("p_ears", "серьги"),
    ("p_lwrist", "часы"),
    ("p_rwrist", "браслеты"),
)

GTA_COMPONENTS: tuple[str, ...] = tuple(code for code, _ in GTA_COMPONENT_ENTRIES)

GTA_COMPONENT_DESCRIPTIONS: dict[str, str] = dict(GTA_COMPONENT_ENTRIES)


def component_combo_label(code: str) -> str:
    desc = GTA_COMPONENT_DESCRIPTIONS.get(code.strip().lower())
    if desc:
        return f"{code} — {desc}"
    return code


def component_combo_values() -> list[str]:
    return [component_combo_label(code) for code in GTA_COMPONENTS]


def normalize_component(value: str) -> str:
    raw = value.strip()
    if not raw:
        return "jbib"
    lower = raw.lower()
    if lower in GTA_COMPONENT_DESCRIPTIONS:
        return lower
    head = raw.split(" — ", 1)[0].strip().lower()
    if head in GTA_COMPONENT_DESCRIPTIONS:
        return head
    head = raw.split(None, 1)[0].strip().lower()
    if head in GTA_COMPONENT_DESCRIPTIONS:
        return head
    return "jbib"


GTA_VARIANTS: tuple[str, ...] = ("uni", "whi")


def normalize_variant(value: str) -> str:
    var = value.strip().lower()
    return var if var in GTA_VARIANTS else "uni"


@dataclass
class TextureBuildItem:
    path: Path
    width: int
    height: int
    mip_count: int
    mip_manual: bool
    component: str
    number: int
    suffix: str
    variant: str
    format_label: str
    texture_name: str
    ytd_name: str


def apply_item_naming(item: TextureBuildItem) -> TextureBuildItem:
    base = format_ytd_basename(item.component, item.number, item.suffix, item.variant)
    return replace(
        item,
        texture_name=base,
        ytd_name=f"{base}.ytd",
    )


def default_format_label() -> str:
    return FORMAT_OPTIONS[2][0]


AUTO_FORMAT = "auto"


def mip_display_value(item: TextureBuildItem) -> str:
    return str(item.mip_count) if item.mip_manual else "auto"


def parse_mip_display(value: str, item: TextureBuildItem) -> tuple[int, bool]:
    if value == "auto":
        return auto_mip_count(item.width, item.height), False
    try:
        count = max(1, min(11, int(value)))
    except ValueError:
        count = auto_mip_count(item.width, item.height)
        return count, False
    return count, True


def auto_mip_count(width: int, height: int) -> int:
    """Mip count from the longer image side (see MIP_COUNT_BY_MAX_SIDE)."""
    side = max(width, height)
    for threshold, count in MIP_COUNT_BY_MAX_SIDE:
        if side >= threshold:
            return count
    return 1


def image_size(path: Path) -> tuple[int, int]:
    if path.suffix.lower() == ".dds":
        tex = Texture.from_dds(path)
        return tex.width, tex.height
    with Image.open(path) as img:
        return img.size


def suffix_letter(index: int) -> str:
    """a, b, c … for texture slots within one drawable number."""
    if index < 26:
        return chr(ord("a") + index)
    return f"z{index - 25}"


def format_ytd_basename(component: str, number: int, suffix: str, variant: str) -> str:
    comp = _safe_stem(component, "tex")
    suf = _safe_stem(suffix, "a").lower()[:8]
    if not suf:
        suf = "a"
    var = variant.strip().lower()
    if var not in ("uni", "whi"):
        var = "uni"
    return f"{comp}_diff_{number:03d}_{suf}_{var}"


def load_build_item(
    path: Path,
    *,
    component: str,
    number: int,
    variant: str,
    suffix: str = "a",
    format_label: str = AUTO_FORMAT,
) -> TextureBuildItem:
    resolved = path.resolve()
    width, height = image_size(resolved)
    base = format_ytd_basename(component, number, suffix, variant)
    return TextureBuildItem(
        path=resolved,
        width=width,
        height=height,
        mip_count=auto_mip_count(width, height),
        mip_manual=False,
        component=component,
        number=number,
        suffix=suffix,
        variant=variant,
        format_label=format_label,
        texture_name=base,
        ytd_name=f"{base}.ytd",
    )


def build_texture(
    item: TextureBuildItem,
    *,
    fmt: BCFormat,
    quality: float = 0.85,
) -> Texture:
    mips = max(1, item.mip_count)
    if item.path.suffix.lower() == ".dds":
        tex = Texture.from_dds(item.path, name=item.texture_name)
        pil = tex.to_pil(0)
        if pil is None:
            raise ValueError(f"Не удалось прочитать: {item.path.name}")
        return Texture.from_pil(
            pil.convert("RGBA"),
            format=fmt,
            quality=quality,
            generate_mipmaps=mips > 1,
            min_mip_size=min_mip_size_for_count(item.width, item.height, mips),
            resize_to_pot=False,
            name=item.texture_name,
        )

    with Image.open(item.path) as img:
        rgba = img.convert("RGBA")
    return Texture.from_pil(
        rgba,
        format=fmt,
        quality=quality,
        generate_mipmaps=mips > 1,
        min_mip_size=min_mip_size_for_count(item.width, item.height, mips),
        resize_to_pot=False,
        name=item.texture_name,
    )


def build_ytd_file(
    item: TextureBuildItem,
    output_dir: Path,
    *,
    fmt: BCFormat,
    quality: float = 0.85,
) -> Path:
    target = Path(output_dir).resolve() / item.ytd_name
    if target.suffix.lower() != ".ytd":
        target = target.with_suffix(".ytd")
    target.parent.mkdir(parents=True, exist_ok=True)
    td = ITD()
    td.add(build_texture(item, fmt=fmt, quality=quality))
    td.save(str(target))
    return target


def build_ytd_files(
    items: list[TextureBuildItem],
    output_dir: Path,
    *,
    quality: float = 0.85,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> list[Path]:
    if not items:
        raise ValueError("Нет текстур для сборки")
    written: list[Path] = []
    total = len(items)
    for index, item in enumerate(items):
        if on_progress is not None:
            on_progress(index + 1, total, f"Сборка {item.ytd_name}…")
        fmt = parse_format(item.format_label)
        written.append(build_ytd_file(item, output_dir, fmt=fmt, quality=quality))
    return written


def _safe_stem(name: str, fallback: str) -> str:
    cleaned = _SAFE_STEM_RE.sub("_", name.strip())
    cleaned = cleaned.strip(" .")
    return (cleaned or fallback).lower()


def notify_build_result(
    folder: Path | None,
    count: int,
    *,
    error: str | None = None,
) -> None:
    try:
        import ctypes

        title = "YTD Previewer — сборка YTD"
        if error:
            ctypes.windll.user32.MessageBoxW(0, error, title, 0x10)
            return
        lines = [f"Файлов YTD: {count}"]
        if folder is not None:
            lines.append("")
            lines.append(str(folder))
        ctypes.windll.user32.MessageBoxW(0, "\n".join(lines), title, 0x40)
    except Exception:
        pass
