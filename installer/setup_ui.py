"""Visual theme for setup.exe (matches YTD Previewer dark UI)."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from ytdpreviewer.ui_theme import ACCENT, ACCENT_HOVER, BG_FIELD, BG_PILL, BTN, BTN_HOVER, FG, FG_DIM

# Background gradient (180deg: top → bottom)
GRAD_TOP = "#272727"
GRAD_BOTTOM = "#1d1d1d"
BG_VIEW = GRAD_BOTTOM

# Installer-specific
BG_CARD = "#2e2e2e"
BG_WARN = "#352029"
FG_WARN = "#f5a8c0"
WARN_STRIPE = ACCENT
BORDER = "#404040"
BORDER_OUTER = "#080808"
BORDER_MID = "#4a4a4a"
BORDER_INNER = "#2e2e2e"
BG_FOOTER = GRAD_BOTTOM
BORDER_TOP = "#3a3a3a"
WIN_TITLE_H = 36
WIN_BORDER_TOTAL = 4  # 1px outer + 1px mid ring on each side
BTN_SECONDARY = "#3d3d3d"
BTN_SECONDARY_HOVER = "#4d4d4d"
HEADER_BG = GRAD_TOP
HEADER_SUB = "#b0b0b0"

_FONT_FAMILY = "Segoe UI"
FONT_UI = (_FONT_FAMILY, 10)
FONT_TITLE = (_FONT_FAMILY, 22, "bold")
FONT_SUB = (_FONT_FAMILY, 11)
FONT_SMALL = (_FONT_FAMILY, 9)
FONT_CAPTION = (_FONT_FAMILY, 8)
FONT_BTN = (_FONT_FAMILY, 10)
FONT_BTN_ACCENT = (_FONT_FAMILY, 10, "bold")


def _hex_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _gradient_photo(width: int, height: int, top: str = GRAD_TOP, bottom: str = GRAD_BOTTOM):
    from PIL import Image, ImageTk

    w = max(width, 1)
    h = max(height, 1)
    r1, g1, b1 = _hex_rgb(top)
    r2, g2, b2 = _hex_rgb(bottom)
    img = Image.new("RGB", (w, h))
    px = img.load()
    denom = max(h - 1, 1)
    for y in range(h):
        t = y / denom
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        for x in range(w):
            px[x, y] = (r, g, b)
    return ImageTk.PhotoImage(img)


def bind_window_drag(widget: tk.Misc, root: tk.Tk) -> None:
    """Drag frameless window by holding title bar / header."""

    def _start(event: tk.Event) -> None:
        widget._drag_x = event.x  # type: ignore[attr-defined]
        widget._drag_y = event.y  # type: ignore[attr-defined]

    def _move(event: tk.Event) -> None:
        x = root.winfo_x() + event.x - widget._drag_x  # type: ignore[attr-defined]
        y = root.winfo_y() + event.y - widget._drag_y  # type: ignore[attr-defined]
        root.geometry(f"+{x}+{y}")

    widget.bind("<ButtonPress-1>", _start)
    widget.bind("<B1-Motion>", _move)


def _chrome_icon_button(parent: tk.Misc, text: str, command, *, hover_fg: str = ACCENT) -> tk.Label:
    lbl = tk.Label(
        parent,
        text=text,
        bg=HEADER_BG,
        fg="#888888",
        font=(_FONT_FAMILY, 12),
        padx=12,
        pady=4,
        cursor="hand2",
    )

    def _enter(_e: tk.Event) -> None:
        lbl.config(fg=hover_fg, bg="#333333")

    def _leave(_e: tk.Event) -> None:
        lbl.config(fg="#888888", bg=HEADER_BG)

    def _click(_e: tk.Event) -> None:
        command()

    lbl.bind("<Enter>", _enter)
    lbl.bind("<Leave>", _leave)
    lbl.bind("<Button-1>", _click)
    return lbl


def install_custom_window(root: tk.Tk, *, on_close=None, title_icon: tk.PhotoImage | None = None) -> tk.Frame:
    """
    Frameless window with layered custom border and title bar.
    Returns the inner content frame (pack all UI into it).
    """
    close_fn = on_close or root.destroy
    root.overrideredirect(True)
    root.configure(bg=BORDER_OUTER)

    shell = tk.Frame(root, bg=BORDER_OUTER)
    shell.pack(fill=tk.BOTH, expand=True)

    ring_outer = tk.Frame(shell, bg=BORDER_OUTER, padx=1, pady=1)
    ring_outer.pack(fill=tk.BOTH, expand=True)

    ring_mid = tk.Frame(ring_outer, bg=BORDER_MID, padx=1, pady=1)
    ring_mid.pack(fill=tk.BOTH, expand=True)

    stack = tk.Frame(ring_mid, bg=BORDER_INNER)
    stack.pack(fill=tk.BOTH, expand=True)

    tk.Frame(stack, bg=ACCENT, height=2).pack(fill=tk.X)

    titlebar = tk.Frame(stack, bg=HEADER_BG, height=WIN_TITLE_H)
    titlebar.pack(fill=tk.X)
    titlebar.pack_propagate(False)

    title_inner = tk.Frame(titlebar, bg=HEADER_BG)
    title_inner.pack(fill=tk.BOTH, expand=True, padx=(14, 6))

    title_left = tk.Frame(title_inner, bg=HEADER_BG)
    title_left.pack(side=tk.LEFT, pady=6)
    if title_icon is not None:
        tk.Label(title_left, image=title_icon, bg=HEADER_BG).pack(side=tk.LEFT, padx=(0, 8))
    tk.Label(
        title_left,
        text="YTD Previewer",
        bg=HEADER_BG,
        fg=FG_DIM,
        font=(_FONT_FAMILY, 9),
    ).pack(side=tk.LEFT)

    _chrome_icon_button(title_inner, "✕", close_fn, hover_fg=ACCENT).pack(side=tk.RIGHT)

    bind_window_drag(titlebar, root)
    bind_window_drag(title_inner, root)

    content = tk.Frame(stack, bg=GRAD_BOTTOM)
    content.pack(fill=tk.BOTH, expand=True)

    root.bind("<Escape>", lambda _e: close_fn())
    return content


class GradientFrame(tk.Frame):
    """Vertical gradient background (#272727 → #1d1d1d)."""

    def __init__(self, parent: tk.Misc, top: str = GRAD_TOP, bottom: str = GRAD_BOTTOM, **kwargs) -> None:
        kwargs.setdefault("bg", bottom)
        super().__init__(parent, **kwargs)
        self._top = top
        self._bottom = bottom
        self._photo: tk.PhotoImage | None = None
        self._canvas = tk.Canvas(self, highlightthickness=0, bd=0, bg=bottom)
        self._canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.bind("<Configure>", self._repaint)

    def _repaint(self, _event: tk.Event | None = None) -> None:
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        self._photo = _gradient_photo(w, h, self._top, self._bottom)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, image=self._photo, anchor="nw")


def _pick_ui_family(root: tk.Tk) -> str:
    families = {f.lower(): f for f in tkfont.families(root)}
    for candidate in (
        "bahnschrift",
        "segoe ui variable display",
        "segoe ui variable text",
        "segoe ui variable small",
        "cascadia ui",
        "corbel",
        "calibri",
    ):
        if candidate in families:
            return families[candidate]
    for key, name in families.items():
        if key.startswith("bahnschrift") and "condensed" not in key and "semibold" not in key and "light" not in key:
            return name
    return "Segoe UI"


def install_setup_fonts(root: tk.Tk) -> None:
    global _FONT_FAMILY, FONT_UI, FONT_TITLE, FONT_SUB, FONT_SMALL, FONT_CAPTION, FONT_BTN, FONT_BTN_ACCENT
    _FONT_FAMILY = _pick_ui_family(root)
    FONT_UI = (_FONT_FAMILY, 10)
    FONT_TITLE = (_FONT_FAMILY, 22, "bold")
    FONT_SUB = (_FONT_FAMILY, 11)
    FONT_SMALL = (_FONT_FAMILY, 9)
    FONT_CAPTION = (_FONT_FAMILY, 8)
    FONT_BTN = (_FONT_FAMILY, 10)
    FONT_BTN_ACCENT = (_FONT_FAMILY, 10, "bold")


def apply_setup_theme(root: tk.Tk) -> ttk.Style:
    install_setup_fonts(root)
    root.configure(bg=GRAD_BOTTOM)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure("Card.TFrame", background=BG_CARD)
    style.configure(
        "Accent.Horizontal.TProgressbar",
        troughcolor=BG_FIELD,
        background=ACCENT,
        bordercolor=BG_FOOTER,
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=8,
    )
    return style


def footer_bar(parent: tk.Misc) -> tuple[tk.Frame, tk.Frame]:
    outer = tk.Frame(parent, bg=BG_FOOTER)
    tk.Frame(outer, bg=BORDER_MID, height=1).pack(fill=tk.X)
    tk.Frame(outer, bg=ACCENT, height=2).pack(fill=tk.X)
    tk.Frame(outer, bg=BORDER_TOP, height=1).pack(fill=tk.X)
    inner = tk.Frame(outer, bg=BG_FOOTER, padx=20, pady=16)
    inner.pack(fill=tk.X)
    return outer, inner


class PillButton(tk.Canvas):
    _RADIUS = 10

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command=None,
        *,
        accent: bool = False,
        min_width: int = 96,
        height: int = 42,
    ) -> None:
        self._text = text
        self._command = command
        self._accent = accent
        self._hover = False
        self._enabled = True
        self._font = FONT_BTN_ACCENT if accent else FONT_BTN

        measure = tk.Label(parent, text=text, font=self._font)
        measure.update_idletasks()
        tw = measure.winfo_reqwidth()
        measure.destroy()
        w = max(min_width, tw + 36)

        try:
            parent_bg = parent.cget("bg")
        except tk.TclError:
            parent_bg = BG_FOOTER

        super().__init__(parent, width=w, height=height, highlightthickness=0, bd=0, bg=parent_bg, cursor="hand2")
        self._shape: int | None = None
        self._label: int | None = None

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)
        self._redraw()

    def _fill_colors(self) -> tuple[str, str]:
        if not self._enabled:
            return "#2a2a2a", "#666666"
        if self._accent:
            fill = ACCENT_HOVER if self._hover else ACCENT
            return fill, "#ffffff"
        fill = BTN_SECONDARY_HOVER if self._hover else BTN_SECONDARY
        return fill, FG

    def _round_rect(self, x1: int, y1: int, x2: int, y2: int, r: int, **kwargs):
        points = [
            x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
        ]
        return self.create_polygon(points, smooth=True, **kwargs)

    def _redraw(self) -> None:
        if self._shape is not None:
            self.delete(self._shape)
        if self._label is not None:
            self.delete(self._label)

        w = int(self["width"])
        h = int(self["height"])
        fill, fg = self._fill_colors()
        self._shape = self._round_rect(1, 1, w - 1, h - 1, self._RADIUS, fill=fill, outline="")
        self._label = self.create_text(w // 2, h // 2, text=self._text, fill=fg, font=self._font)

    def _on_enter(self, _event: tk.Event) -> None:
        if self._enabled:
            self._hover = True
            self._redraw()

    def _on_leave(self, _event: tk.Event) -> None:
        self._hover = False
        self._redraw()

    def _on_click(self, _event: tk.Event) -> None:
        if self._enabled and self._command:
            self._command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow")
        self._redraw()


def pill_button(
    parent: tk.Misc,
    text: str,
    command=None,
    *,
    accent: bool = False,
    min_width: int = 96,
) -> PillButton:
    return PillButton(parent, text, command, accent=accent, min_width=min_width)


def card(parent: tk.Misc, *, padx: int = 20, pady: int = 8) -> tk.Frame:
    try:
        gap_bg = parent.cget("bg")
    except tk.TclError:
        gap_bg = GRAD_TOP
    outer = tk.Frame(parent, bg=gap_bg)
    outer.pack(fill=tk.X, padx=padx, pady=pady)
    ring = tk.Frame(outer, bg=BORDER_MID, padx=1, pady=1)
    ring.pack(fill=tk.X)
    frame = tk.Frame(ring, bg=BG_CARD, highlightbackground=BORDER_INNER, highlightthickness=1)
    frame.pack(fill=tk.X)
    inner = tk.Frame(frame, bg=BG_CARD, padx=16, pady=12)
    inner.pack(fill=tk.X)
    return inner


def warn_card(parent: tk.Misc) -> tk.Frame:
    try:
        gap_bg = parent.cget("bg")
    except tk.TclError:
        gap_bg = GRAD_TOP
    outer = tk.Frame(parent, bg=gap_bg)
    outer.pack(fill=tk.X, padx=20, pady=(0, 6))
    ring = tk.Frame(outer, bg=BORDER_MID, padx=1, pady=1)
    ring.pack(fill=tk.X)
    row_wrap = tk.Frame(ring, bg=BG_WARN)
    row_wrap.pack(fill=tk.X)
    bar = tk.Frame(row_wrap, bg=WARN_STRIPE, width=4)
    body = tk.Frame(row_wrap, bg=BG_WARN)
    bar.pack(side=tk.LEFT, fill=tk.Y)
    body.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    inner = tk.Frame(body, bg=BG_WARN, padx=14, pady=10)
    inner.pack(fill=tk.X)
    return inner


def header(parent: tk.Misc, icon_image: tk.PhotoImage | None = None, *, drag_root: tk.Tk | None = None) -> tk.Frame:
    wrap = tk.Frame(parent, bg=HEADER_BG)
    wrap.pack(fill=tk.X)
    tk.Frame(wrap, bg=ACCENT, height=2).pack(fill=tk.X, side=tk.BOTTOM)

    row = tk.Frame(wrap, bg=HEADER_BG)
    row.pack(fill=tk.X, padx=22, pady=(16, 18))

    if drag_root is not None:
        bind_window_drag(wrap, drag_root)
        bind_window_drag(row, drag_root)

    if icon_image is not None:
        tk.Label(row, image=icon_image, bg=HEADER_BG).pack(side=tk.LEFT, padx=(0, 16))

    text_col = tk.Frame(row, bg=HEADER_BG)
    text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
    tk.Label(
        text_col,
        text="YTD Previewer",
        bg=HEADER_BG,
        fg="#ffffff",
        font=FONT_TITLE,
        anchor=tk.W,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(0, 4))
    tk.Label(
        text_col,
        text="Установка и настройка для GTA V",
        bg=HEADER_BG,
        fg=HEADER_SUB,
        font=FONT_SUB,
        anchor=tk.W,
        justify=tk.LEFT,
    ).pack(anchor=tk.W, pady=(0, 2))
    return wrap


def feature_row(parent: tk.Misc, text: str) -> None:
    row = tk.Frame(parent, bg=BG_CARD)
    row.pack(fill=tk.X, pady=2)
    tk.Label(row, text="●", bg=BG_CARD, fg=ACCENT, font=(_FONT_FAMILY, 8)).pack(side=tk.LEFT, padx=(0, 10))
    tk.Label(row, text=text, bg=BG_CARD, fg=FG, font=FONT_UI, anchor=tk.W, justify=tk.LEFT).pack(
        side=tk.LEFT, fill=tk.X, expand=True
    )


def dark_entry(parent: tk.Misc, textvariable: tk.StringVar) -> tk.Entry:
    wrap = tk.Frame(parent, bg=BG_PILL, padx=1, pady=1)
    wrap.pack(fill=tk.X, pady=(6, 0))
    entry = tk.Entry(
        wrap,
        textvariable=textvariable,
        bg=BG_FIELD,
        fg=FG,
        insertbackground=FG,
        relief=tk.FLAT,
        font=FONT_UI,
        bd=0,
        highlightthickness=8,
        highlightbackground=BG_PILL,
        highlightcolor=ACCENT,
    )
    entry.pack(fill=tk.X, ipady=8, ipadx=10)
    return entry


def dark_check(parent: tk.Misc, text: str, variable: tk.BooleanVar) -> tk.Checkbutton:
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        bg=BG_CARD,
        fg=FG,
        activebackground=BG_CARD,
        activeforeground=FG,
        selectcolor=BG_FIELD,
        font=FONT_SMALL,
        anchor=tk.W,
        justify=tk.LEFT,
        wraplength=540,
        highlightthickness=0,
        bd=0,
        cursor="hand2",
    )


def section_label(parent: tk.Misc, text: str) -> None:
    tk.Label(
        parent,
        text=text.upper(),
        bg=BG_CARD,
        fg=FG_DIM,
        font=FONT_CAPTION,
    ).pack(anchor=tk.W, pady=(0, 4))


def caption(parent: tk.Misc, text: str, *, fg: str = FG_DIM, bg: str | None = None) -> tk.Label:
    try:
        parent_bg = bg if bg is not None else parent.cget("bg")
    except tk.TclError:
        parent_bg = GRAD_BOTTOM
    lbl = tk.Label(parent, text=text, bg=parent_bg, fg=fg, font=FONT_SMALL)
    lbl.pack(anchor=tk.W)
    return lbl


def action_button(parent: tk.Misc, text: str, command, *, accent: bool = False, width: int | None = None) -> tk.Button:
    if accent:
        bg, fg, abg = ACCENT, "#ffffff", ACCENT_HOVER
        font = FONT_BTN_ACCENT
        padx = 22
    else:
        bg, fg, abg = BTN, FG, BTN_HOVER
        font = FONT_UI
        padx = 16
    kw: dict = dict(
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=abg,
        activeforeground=fg,
        relief=tk.FLAT,
        font=font,
        padx=padx,
        pady=10,
        cursor="hand2",
        bd=0,
        highlightthickness=0,
    )
    if width:
        kw["width"] = width
    return tk.Button(parent, **kw)
