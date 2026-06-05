"""Generate icons: app.ico from brand logo; ytd/ydd keep neutral file-type look."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
LOGO_PNG = ASSETS / "logo" / "logo without background.png"

ACCENT = (232, 28, 90)
BG_TOP = (39, 39, 39)
BG_BOTTOM = (29, 29, 29)


def _save_ico(path: Path, image: Image.Image) -> None:
    sizes = [16, 32, 48, 256]
    frames = [image.resize((s, s), Image.Resampling.LANCZOS) for s in sizes]
    frames[0].save(
        path,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )


def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * t)


def _dark_rounded_bg(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = size // 6
    for y in range(size):
        t = y / max(size - 1, 1)
        fill = (
            _lerp(BG_TOP[0], BG_BOTTOM[0], t),
            _lerp(BG_TOP[1], BG_BOTTOM[1], t),
            _lerp(BG_TOP[2], BG_BOTTOM[2], t),
            255,
        )
        draw.line([(0, y), (size, y)], fill=fill)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((1, 1, size - 2, size - 2), radius=r, fill=255)
    img.putalpha(mask)
    ring = ImageDraw.Draw(img)
    ring.rounded_rectangle((1, 1, size - 2, size - 2), radius=r, outline=ACCENT + (220,), width=max(2, size // 64))
    return img


def _load_logo_rgba() -> Image.Image | None:
    if not LOGO_PNG.is_file():
        return None
    img = Image.open(LOGO_PNG)
    img.load()
    return img.convert("RGBA")


def _paste_logo(base: Image.Image, logo: Image.Image, scale: float = 0.72) -> Image.Image:
    size = base.width
    side = max(8, int(size * scale))
    logo = logo.copy()
    logo.thumbnail((side, side), Image.Resampling.LANCZOS)
    x = (size - logo.width) // 2
    y = (size - logo.height) // 2
    base.alpha_composite(logo, (x, y))
    return base


def _brand_fallback(size: int) -> Image.Image:
    img = _dark_rounded_bg(size)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arialbd.ttf", size // 3)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), "YP", fill=ACCENT + (255,), font=font, anchor="mm")
    return img


def icon_app(size: int = 256) -> Image.Image:
    base = _dark_rounded_bg(size)
    logo = _load_logo_rgba()
    if logo is not None:
        return _paste_logo(base, logo)
    return _brand_fallback(size)


def _rounded_bg(draw: ImageDraw.ImageDraw, size: int, color: tuple[int, int, int]) -> None:
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=size // 6, fill=color)


def icon_ytd(size: int = 256) -> Image.Image:
    """Neutral texture-dictionary icon (not app logo)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_bg(draw, size, (46, 125, 50))
    m = size // 5
    draw.rectangle((m, m, size - m, size - m - size // 8), fill=(255, 255, 255, 240))
    draw.polygon(
        [(m, size - m - size // 8), (size // 2, size - m), (size - m, size - m - size // 8)],
        fill=(220, 235, 220, 255),
    )
    draw.ellipse(
        (size // 2 - size // 14, m + size // 12, size // 2 + size // 14, m + size // 6),
        fill=(80, 160, 90),
    )
    return img


def icon_ydd(size: int = 256) -> Image.Image:
    """Neutral drawable-dictionary icon (not app logo)."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_bg(draw, size, (25, 95, 175))
    layer_h = size // 6
    for i, shade in enumerate([(255, 255, 255), (210, 225, 245), (170, 200, 230)]):
        y = size // 4 + i * (layer_h + size // 24)
        draw.rounded_rectangle(
            (size // 5, y, size - size // 5, y + layer_h),
            radius=size // 20,
            fill=shade + (255,),
        )
    try:
        font = ImageFont.truetype("arialbd.ttf", size // 5)
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size - size // 5), "DD", fill=(255, 255, 255), font=font, anchor="mm")
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    _save_ico(ASSETS / "app.ico", icon_app())
    _save_ico(ASSETS / "ytd.ico", icon_ytd())
    _save_ico(ASSETS / "ydd.ico", icon_ydd())
    src = "logo PNG" if LOGO_PNG.is_file() else "monogram"
    print(f"Icons: app.ico ({src}), ytd.ico/ydd.ico (neutral file types)")


if __name__ == "__main__":
    main()
