"""Keyboard shortcuts that work on any keyboard layout (EN/RU/…)."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import tkinter as tk
from tkinter import ttk

from ytdpreviewer.ui_theme import _is_text_input_widget

_WIN_VK_BY_LETTER: dict[str, int] = {
    chr(ord("a") + i): 0x41 + i for i in range(26)
}

_RU_LETTER_BY_US: dict[str, str] = {
    "a": "ф",
    "b": "и",
    "c": "с",
    "d": "в",
    "e": "у",
    "f": "а",
    "g": "п",
    "h": "р",
    "i": "ш",
    "j": "о",
    "k": "л",
    "l": "д",
    "m": "ь",
    "n": "т",
    "o": "щ",
    "p": "з",
    "q": "й",
    "r": "к",
    "s": "ы",
    "t": "е",
    "u": "г",
    "v": "м",
    "w": "ц",
    "x": "ч",
    "y": "н",
    "z": "я",
}

_RU_PUNCT_BY_US: dict[str, str] = {
    "[": "х",
    "]": "ъ",
}

_WM_CUT = 0x0300
_WM_COPY = 0x0301
_WM_PASTE = 0x0302

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.SendMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    _user32.SendMessageW.restype = wintypes.LPARAM


def _char_codes(*chars: str) -> frozenset[int]:
    out: set[int] = set()
    for ch in chars:
        out.add(ord(ch))
        if len(ch) == 1 and ch.islower():
            out.add(ord(ch.upper()))
    return frozenset(out)


def _ru_alias_codes(us_letter: str) -> frozenset[int]:
    ru = _RU_LETTER_BY_US.get(us_letter.lower())
    if not ru:
        return frozenset()
    return _char_codes(ru)


def _ctrl_down(state: int) -> bool:
    return bool(state & 0x4) or bool(state & 0x20000)


def _alt_down(state: int) -> bool:
    return bool(state & 0x8)


def _shift_down(state: int) -> bool:
    return bool(state & 0x1)


@dataclass(frozen=True)
class _HotkeySpec:
    vk: int
    letter: str
    callback: Callable[[], None]
    ctrl: bool = False
    alt: bool = False
    shift: bool = False


def _letter_event_match(letter: str, keysym: str, char: str) -> bool:
    us = letter.lower()
    sym = keysym.lower() if keysym else ""
    if sym in {us, us.upper()}:
        return True
    ru = _RU_LETTER_BY_US.get(us)
    if ru and sym in {ru, ru.upper()}:
        return True
    if char:
        ch = char.lower()
        if ch == us:
            return True
        if ru and ch == ru:
            return True
    return False


def _hotkey_matches(
    spec: _HotkeySpec,
    *,
    vk: int,
    keysym: str,
    char: str,
    ctrl: bool,
    alt: bool,
    shift: bool,
) -> bool:
    # Windows often sets extra modifier bits in event.state (e.g. Alt with Ctrl).
    if spec.ctrl and not ctrl:
        return False
    if spec.alt and not alt:
        return False
    if spec.shift and not shift:
        return False
    if vk == spec.vk:
        return True
    if sys.platform == "win32" and spec.ctrl:
        return False
    return _letter_event_match(spec.letter, keysym, char)


def _app_tk_root(widget: tk.Misc) -> tk.Misc:
    root = widget.winfo_toplevel()
    master = getattr(root, "master", None)
    while isinstance(root, tk.Toplevel) and master not in (None, ""):
        root = master
        master = getattr(root, "master", None)
    return root


def _dispatch_keypress(top: tk.Misc, event: tk.Event) -> str | None:
    if getattr(top, "_ytd_hotkeys_disabled", False):
        return None

    specs = getattr(top, "_ytd_hotkeys", ())
    if not specs:
        return None

    vk = int(event.keycode)
    keysym = str(event.keysym or "")
    char = str(event.char or "")
    ctrl = _ctrl_down(int(event.state))
    alt = _alt_down(int(event.state))
    shift = _shift_down(int(event.state))
    if not ctrl and not alt and not shift:
        return None

    for spec in specs:
        if _hotkey_matches(
            spec,
            vk=vk,
            keysym=keysym,
            char=char,
            ctrl=ctrl,
            alt=alt,
            shift=shift,
        ):
            spec.callback()
            return "break"
    return None


def _widget_key_handler(top: tk.Misc, event: tk.Event) -> str | None:
    try:
        if event.widget.winfo_toplevel() != top:
            return None
    except tk.TclError:
        return None
    return _dispatch_keypress(top, event)


def _iter_widgets(root: tk.Misc) -> Iterable[tk.Misc]:
    stack = [root]
    while stack:
        widget = stack.pop()
        yield widget
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue


def _attach_widget_hook(widget: tk.Misc, top: tk.Misc) -> None:
    hooked: set[str] = getattr(top, "_ytd_hooked_widgets", set())  # type: ignore[attr-defined]
    path = str(widget)
    if path in hooked:
        return
    hooked.add(path)
    top._ytd_hooked_widgets = hooked  # type: ignore[attr-defined]
    widget.bind("<KeyPress>", lambda e, t=top: _widget_key_handler(t, e), add="+")


def attach_window_key_hooks(window: tk.Misc) -> None:
    """Bind KeyPress on the window and every child (bind_all alone is unreliable on Windows)."""
    top = window.winfo_toplevel()
    for widget in _iter_widgets(top):
        _attach_widget_hook(widget, top)

    if not getattr(top, "_ytd_global_key_hook", False):
        top._ytd_global_key_hook = True  # type: ignore[attr-defined]
        app = _app_tk_root(top)

        def _global_handler(event: tk.Event) -> str | None:
            try:
                event_top = event.widget.winfo_toplevel()
            except tk.TclError:
                return None
            if event_top is not top:
                return None
            return _widget_key_handler(top, event)

        app.bind_all("<KeyPress>", _global_handler, add="+")


def release_window_hotkeys(window: tk.Misc) -> None:
    top = window.winfo_toplevel()
    top._ytd_hotkeys_disabled = True  # type: ignore[attr-defined]


def bind_layout_hotkey(
    window: tk.Misc,
    key: str,
    callback: Callable[[], None],
    *,
    ctrl: bool = False,
    alt: bool = False,
    shift: bool = False,
) -> None:
    letter = key.lower()
    vk = _WIN_VK_BY_LETTER.get(letter)
    if vk is None:
        raise ValueError(f"Unsupported hotkey letter: {key!r}")

    top = window.winfo_toplevel()
    if not hasattr(top, "_ytd_hotkeys"):
        top._ytd_hotkeys = []  # type: ignore[attr-defined]
    top._ytd_hotkeys.append(  # type: ignore[attr-defined]
        _HotkeySpec(
            vk=vk,
            letter=letter,
            callback=callback,
            ctrl=ctrl,
            alt=alt,
            shift=shift,
        )
    )


def _focused_text_widget(top: tk.Misc) -> tk.Misc | None:
    try:
        focused = top.focus_get()
    except tk.TclError:
        return None
    if focused is None:
        return None
    if isinstance(focused, ttk.Combobox) and str(focused.cget("state")) == "readonly":
        return None
    if not _is_text_input_widget(focused):
        return None
    return focused


def _selection_text(widget: tk.Misc) -> str | None:
    try:
        if isinstance(widget, tk.Text):
            if widget.tag_ranges(tk.SEL):
                return widget.get(tk.SEL_FIRST, tk.SEL_LAST)
            return None
        if hasattr(widget, "selection_present") and widget.selection_present():
            return widget.selection_get()
    except tk.TclError:
        return None
    return None


def _delete_selection(widget: tk.Misc) -> None:
    try:
        if isinstance(widget, tk.Text):
            if widget.tag_ranges(tk.SEL):
                widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
        elif hasattr(widget, "selection_present") and widget.selection_present():
            widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
    except tk.TclError:
        pass


def _try_win32_edit_msg(widget: tk.Misc, msg: int) -> bool:
    if sys.platform != "win32":
        return False
    try:
        hwnd = int(widget.winfo_id())
        result = _user32.SendMessageW(hwnd, msg, 0, 0)
        return bool(result)
    except (tk.TclError, ValueError, OSError):
        return False


def copy_to_focused_input(window: tk.Misc) -> bool:
    top = window.winfo_toplevel()
    focused = _focused_text_widget(top)
    if focused is None:
        return False

    text = _selection_text(focused)
    if not text:
        return False
    top.clipboard_clear()
    top.clipboard_append(text)
    return True


def cut_to_focused_input(window: tk.Misc) -> bool:
    top = window.winfo_toplevel()
    focused = _focused_text_widget(top)
    if focused is None:
        return False

    text = _selection_text(focused)
    if not text:
        return False
    top.clipboard_clear()
    top.clipboard_append(text)
    _delete_selection(focused)
    return True


def paste_to_focused_input(window: tk.Misc) -> bool:
    top = window.winfo_toplevel()
    focused = _focused_text_widget(top)
    if focused is None:
        return False

    try:
        text = top.clipboard_get()
    except tk.TclError:
        return False

    _delete_selection(focused)
    try:
        focused.insert(tk.INSERT, text)
        return True
    except tk.TclError:
        return False


def install_clipboard_hotkeys(
    window: tk.Misc,
    *,
    extra_paste: Callable[[], None] | None = None,
) -> None:
    top = window.winfo_toplevel()
    if getattr(top, "_ytd_clipboard_hotkeys", False):
        if extra_paste is not None:
            top._ytd_clipboard_extra_paste = extra_paste  # type: ignore[attr-defined]
        attach_window_key_hooks(window)
        return

    top._ytd_clipboard_hotkeys = True  # type: ignore[attr-defined]
    if extra_paste is not None:
        top._ytd_clipboard_extra_paste = extra_paste  # type: ignore[attr-defined]

    def _paste_extra() -> None:
        if paste_to_focused_input(window):
            return
        extra = getattr(top, "_ytd_clipboard_extra_paste", None)
        if extra is not None:
            extra()

    bind_layout_hotkey(window, "c", lambda: copy_to_focused_input(window), ctrl=True)
    bind_layout_hotkey(window, "v", _paste_extra, ctrl=True)
    bind_layout_hotkey(window, "x", lambda: cut_to_focused_input(window), ctrl=True)
    attach_window_key_hooks(window)


def pyglet_key_matches(symbol: int, en_key: int) -> bool:
    if symbol == en_key:
        return True
    try:
        from pyglet.window import key
    except ImportError:
        return False

    us_char = _pyglet_us_char(en_key)
    if us_char:
        return symbol in _ru_alias_codes(us_char)
    if en_key == key.BRACKETLEFT:
        return symbol in (_char_codes("[") | _char_codes(_RU_PUNCT_BY_US["["]))
    if en_key == key.BRACKETRIGHT:
        return symbol in (_char_codes("]") | _char_codes(_RU_PUNCT_BY_US["]"]))
    return False


def pyglet_ctrl_letter(symbol: int, letter: str, modifiers: int) -> bool:
    try:
        from pyglet.window import key
    except ImportError:
        return False
    if not (modifiers & key.MOD_CTRL):
        return False
    en = getattr(key, letter.upper(), None)
    if en is None:
        return False
    return pyglet_key_matches(symbol, en)


def _pyglet_us_char(en_key: int) -> str | None:
    try:
        from pyglet.window import key
    except ImportError:
        return None
    if ord("a") <= en_key <= ord("z"):
        return chr(en_key)
    if ord("A") <= en_key <= ord("Z"):
        return chr(en_key).lower()
    for letter, attr in zip(
        "abcdefghijklmnopqrstuvwxyz",
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        strict=True,
    ):
        if en_key == getattr(key, attr, None):
            return letter
    return None


def install_preview_hotkeys(
    window: tk.Misc,
    *,
    save: Callable[[], None],
    replace_texture: Callable[[], None],
    paste_image_extra: Callable[[], None] | None = None,
) -> None:
    install_clipboard_hotkeys(window, extra_paste=paste_image_extra)
    bind_layout_hotkey(window, "s", save, ctrl=True)
    bind_layout_hotkey(window, "r", replace_texture, ctrl=True)
    attach_window_key_hooks(window)
