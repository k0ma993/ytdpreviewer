"""Shared application icon for tray, windows and file associations."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ytdpreviewer.paths import assets_dir

APP_ICON_NAME = "app.ico"
LOGO_REL = Path("logo") / "logo without background.png"
ACCENT_RGBA = (232, 28, 90, 255)
BG_RGBA = (29, 29, 29, 255)


def logo_png_path() -> Path:
    return assets_dir() / LOGO_REL


def app_icon_path() -> Path:
    path = assets_dir() / APP_ICON_NAME
    if path.is_file():
        return path
    return path


def _brand_fallback_rgba(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=size // 6, fill=BG_RGBA)
    draw.rounded_rectangle((2, 2, size - 3, size - 3), radius=size // 6, outline=ACCENT_RGBA, width=max(2, size // 32))
    try:
        font = ImageFont.truetype("arialbd.ttf", max(10, size // 3))
    except OSError:
        font = ImageFont.load_default()
    draw.text((size // 2, size // 2), "YP", fill=ACCENT_RGBA, font=font, anchor="mm")
    return img


def load_brand_image(size: int | None = None) -> Image.Image:
    """Logo PNG if present, else app.ico, else pink monogram (never Python / feather)."""
    logo = logo_png_path()
    if logo.is_file():
        image = Image.open(logo)
        image.load()
        rgba = image.convert("RGBA")
        if size is not None:
            rgba.thumbnail((size, size), Image.Resampling.LANCZOS)
            out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            x = (size - rgba.width) // 2
            y = (size - rgba.height) // 2
            out.paste(rgba, (x, y), rgba)
            return out
        return rgba

    return load_pil_icon(size)


def load_pil_icon(size: int | None = None) -> Image.Image:
    path = app_icon_path()
    if path.is_file():
        image = Image.open(path)
        image.load()
        rgba = image.convert("RGBA")
        if size is not None:
            rgba = rgba.resize((size, size), Image.Resampling.LANCZOS)
        return rgba

    return _brand_fallback_rgba(size or 64)


def apply_tk_icon(window) -> None:
    path = app_icon_path()
    if path.is_file():
        try:
            window.iconbitmap(default=str(path))
            return
        except Exception:
            pass
    try:
        from PIL import ImageTk

        photo = ImageTk.PhotoImage(load_pil_icon(32))
        window.iconphoto(True, photo)
        window._ytd_icon_ref = photo  # type: ignore[attr-defined]
    except Exception:
        pass


def apply_pyglet_icon(window) -> None:
    path = app_icon_path()
    if not path.is_file():
        return
    try:
        import pyglet

        window.set_icon(pyglet.image.load(str(path)))
    except Exception:
        pass
