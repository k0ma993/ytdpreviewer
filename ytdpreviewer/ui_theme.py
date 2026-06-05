"""Dark toolbar styling and small UI helpers."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Toolbar palette (Windows 11–like dark)
BG_VIEW = "#1c1c1c"
BG_STRIP = "#242424"
BG_BAR = "#1f1f1f"
BG_BAR_TOP = "#333333"
BG_FIELD = "#2d2d2d"
BG_PILL = "#353535"
FG = "#f0f0f0"
FG_DIM = "#8a8a8a"
ACCENT = "#E81C5A"
ACCENT_HOVER = "#ff4270"
BTN = "#3a3a3a"
BTN_HOVER = "#484848"
APP_AUTHOR = "fus1kk"
APP_CREDIT = "by fus1kk"

_INPUT_WIDGET_CLASSES = frozenset({"Entry", "TEntry", "Spinbox", "Text", "TCombobox"})


def _is_text_input_widget(widget: tk.Misc) -> bool:
    if isinstance(widget, (tk.Entry, tk.Spinbox, tk.Text, ttk.Combobox)):
        return True
    try:
        return widget.winfo_class() in _INPUT_WIDGET_CLASSES
    except tk.TclError:
        return False


def bind_unfocus_inputs_on_click(window: tk.Misc) -> None:
    """Remove focus from entries/combos when clicking elsewhere in the same window."""
    if getattr(bind_unfocus_inputs_on_click, "_installed", False):
        return

    def _on_pointer_click(event: tk.Event) -> None:
        try:
            clicked = event.widget
            top = clicked.winfo_toplevel()
        except tk.TclError:
            return
        if _is_text_input_widget(clicked):
            return
        if clicked.winfo_class() == "Listbox":
            return
        try:
            focused = top.focus_get()
        except tk.TclError:
            return
        if focused is None or focused is clicked:
            return
        if _is_text_input_widget(focused):
            top.focus_set()

    window.bind_all("<Button-1>", _on_pointer_click, add="+")
    bind_unfocus_inputs_on_click._installed = True  # type: ignore[attr-defined]


def center_tk_window(window: tk.Misc, width: int | None = None, height: int | None = None) -> None:
    window.update_idletasks()
    w = width if width is not None else window.winfo_width()
    h = height if height is not None else window.winfo_height()
    if w <= 1:
        w = window.winfo_reqwidth()
    if h <= 1:
        h = window.winfo_reqheight()
    x = max(0, (window.winfo_screenwidth() - w) // 2)
    y = max(0, (window.winfo_screenheight() - h) // 2)
    window.geometry(f"{w}x{h}+{x}+{y}")


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self._widget = widget
        self._text = text
        self._tip: tk.Toplevel | None = None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _event: object = None) -> None:
        if self._tip:
            return
        x = self._widget.winfo_rootx() + 12
        y = self._widget.winfo_rooty() - 28
        self._tip = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(
            tw,
            text=self._text,
            bg="#2a2a2a",
            fg=FG,
            font=("Segoe UI", 9),
            padx=8,
            pady=4,
            relief=tk.FLAT,
        )
        label.pack()

    def _hide(self, _event: object = None) -> None:
        if self._tip:
            self._tip.destroy()
            self._tip = None


def setup_dark_ttk(root: tk.Misc) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(
        "Dark.TCombobox",
        fieldbackground=BG_FIELD,
        background=BG_FIELD,
        foreground=FG,
        arrowcolor=FG_DIM,
        bordercolor=BG_FIELD,
        lightcolor=BG_FIELD,
        darkcolor=BG_FIELD,
        relief="flat",
    )
    style.map(
        "Dark.TCombobox",
        fieldbackground=[("readonly", BG_FIELD), ("disabled", "#262626")],
        foreground=[("disabled", FG_DIM)],
    )
    bind_unfocus_inputs_on_click(root)
    return style


def bar_separator(parent: tk.Misc) -> tk.Frame:
    sep = tk.Frame(parent, bg=BG_BAR_TOP, width=1)
    sep.pack(side=tk.LEFT, fill=tk.Y, padx=12, pady=10)
    return sep


def field_column(parent: tk.Misc, label: str) -> tk.Frame:
    col = tk.Frame(parent, bg=BG_BAR)
    col.pack(side=tk.LEFT, padx=(0, 10))
    tk.Label(
        col,
        text=label.upper(),
        bg=BG_BAR,
        fg=FG_DIM,
        font=("Segoe UI", 7, "bold"),
    ).pack(anchor=tk.W, pady=(0, 2))
    body = tk.Frame(col, bg=BG_BAR)
    body.pack(anchor=tk.W)
    return body


def resolution_pill(parent: tk.Misc) -> tk.Label:
    wrap = tk.Frame(parent, bg=BG_PILL, padx=12, pady=6)
    wrap.pack(side=tk.LEFT, padx=(14, 0), pady=8)
    lbl = tk.Label(
        wrap,
        text="—",
        bg=BG_PILL,
        fg=FG,
        font=("Segoe UI", 11, "bold"),
    )
    lbl.pack()
    lbl._pill_wrap = wrap  # type: ignore[attr-defined]
    return lbl


def flat_button(
    parent: tk.Misc,
    text: str,
    command,
    *,
    accent: bool = False,
) -> tk.Button:
    if accent:
        bg, fg, abg = ACCENT, "#ffffff", ACCENT_HOVER
    else:
        bg, fg, abg = BTN, FG, BTN_HOVER
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=abg,
        activeforeground=fg,
        relief=tk.FLAT,
        font=("Segoe UI", 9),
        padx=14,
        pady=6,
        cursor="hand2",
        bd=0,
        highlightthickness=0,
    )
    return btn
