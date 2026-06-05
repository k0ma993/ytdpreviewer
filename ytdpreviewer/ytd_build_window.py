"""Window for packing PNG images into GTA V .ytd files (packer-style UI)."""

from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from ytdpreviewer.texture_edit import FORMAT_OPTIONS, parse_format
from ytdpreviewer.ui_theme import (
    ACCENT,
    APP_CREDIT,
    BG_BAR,
    BG_BAR_TOP,
    BG_FIELD,
    BG_STRIP,
    BG_VIEW,
    BTN,
    FG,
    FG_DIM,
    bar_separator,
    center_tk_window,
    flat_button,
    setup_dark_ttk,
)
from ytdpreviewer.ytd_build import (
    AUTO_FORMAT,
    suffix_letter,
    TextureBuildItem,
    apply_item_naming,
    auto_mip_count,
    build_ytd_files,
    component_combo_label,
    component_combo_values,
    default_format_label,
    load_build_item,
    mip_display_value,
    normalize_component,
    normalize_variant,
    notify_build_result,
    parse_mip_display,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tiff", ".dds"}
_FORMAT_LABELS = [label for label, _ in FORMAT_OPTIONS]
_FORMAT_COMBO = [AUTO_FORMAT, *_FORMAT_LABELS]
_MIPS_COMBO = [f"{i}" for i in range(1, 12)]
_ROW_ALT = "#282828"
_SEL_BG = "#2a4034"
_DRAG_HOVER_BG = "#3a5544"
_DRAG_SOURCE_BG = "#323232"
_PREVIEW_PANEL_W = 300
_PREVIEW_MAX = 280
_THUMB_SIZE = 48
_OUTPUT_THUMB = 40
_PLACEHOLDER = "#383838"
_COL_GRIP = 36
_COL_ORDER = 40
_COL_SIZE = 88
_COL_FMT = 108
_COL_MIPS = 52
_COL_THUMB = _THUMB_SIZE + 12
_COL_DEL = 32
_THUMB_PIL_CACHE: dict[tuple[str, int], Image.Image] = {}


def _load_preview_pil(path: Path, max_side: int) -> Image.Image:
    key = (str(path.resolve()), max_side)
    cached = _THUMB_PIL_CACHE.get(key)
    if cached is not None:
        return cached

    if path.suffix.lower() == ".dds":
        from texfury import Texture

        tex = Texture.from_dds(path)
        pil = tex.to_pil(0)
        if pil is None:
            raise ValueError("Не удалось прочитать DDS")
        img = pil.convert("RGBA")
    else:
        with Image.open(path) as im:
            img = im.convert("RGBA")
    resample = Image.Resampling.BILINEAR if max_side <= _THUMB_SIZE else Image.Resampling.LANCZOS
    img.thumbnail((max_side, max_side), resample)
    _THUMB_PIL_CACHE[key] = img
    return img


@dataclass
class _RowUi:
    frame: tk.Frame
    row_frame: tk.Frame
    order_var: tk.StringVar
    format_var: tk.StringVar
    mip_var: tk.StringVar
    sub_label: tk.Label
    name_label: tk.Label
    thumb_label: tk.Label
    grip_label: tk.Label


def _paths_in_user_order(paths: list[str | Path]) -> list[Path]:
    """Preserve picker / argv order; skip duplicates and unsupported types."""
    seen: set[str] = set()
    ordered: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(path.resolve())
    return ordered


class YtdBuildWindow:
    def __init__(self, image_paths: list[Path]) -> None:
        sources = _paths_in_user_order(image_paths)
        if not sources:
            raise ValueError("Нет подходящих изображений")

        self._items: list[TextureBuildItem] = []
        self._rows: list[_RowUi] = []
        self._output_dir = sources[0].parent
        self._drag_row: _RowUi | None = None
        self._drag_hover_index: int | None = None
        self._drag_start_y = 0
        self._drag_moved = False
        self._updating = False
        self._selected_index: int | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._preview_generation = 0
        self._row_thumb_photos: list[ImageTk.PhotoImage | None] = []
        self._row_thumb_generation = 0
        self._thumb_photo_by_path: dict[str, ImageTk.PhotoImage] = {}
        self._output_thumb_generation = 0
        self._output_rows: list[tuple[tk.Frame, tk.Label]] = []
        self._scrollregion_after_id: str | None = None
        self._output_refresh_after_id: str | None = None
        self._list_wheel_bound = False
        self._drag_motion_bind: str | None = None
        self._drag_release_bind: str | None = None

        self.root = tk.Tk()
        self.root.title("YTD Previewer — сборка YTD")
        self.root.configure(bg=BG_VIEW)
        self.root.minsize(1200, 560)
        setup_dark_ttk(self.root)

        self._build_ui()
        self._add_paths(sources)
        from ytdpreviewer.hotkeys import install_clipboard_hotkeys

        install_clipboard_hotkeys(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        center_tk_window(self.root, 1240, 600)

    def _on_close(self) -> None:
        try:
            from ytdpreviewer.hotkeys import release_window_hotkeys

            release_window_hotkeys(self.root)
        except Exception:
            pass
        self._unbind_drag_global()
        self._unbind_list_wheel()
        self.root.destroy()

    def _build_ui(self) -> None:
        header = tk.Frame(self.root, bg=BG_BAR, padx=12, pady=10)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="YTD Previewer — сборка YTD",
            bg=BG_BAR,
            fg=FG,
            font=("Segoe UI", 11, "bold"),
        ).pack(side=tk.LEFT)

        tk.Label(
            header,
            text=APP_CREDIT,
            bg=BG_BAR,
            fg=FG_DIM,
            font=("Segoe UI", 8),
        ).pack(side=tk.RIGHT, padx=(12, 0))

        toolbar = tk.Frame(self.root, bg=BG_BAR, padx=12)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        flat_button(toolbar, "+ Добавить", self._add_files_dialog).pack(side=tk.LEFT)
        flat_button(toolbar, "× Очистить", self._clear_all).pack(side=tk.LEFT, padx=(8, 0))
        bar_separator(toolbar)

        tk.Label(toolbar, text="комп.:", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._default_comp_var = tk.StringVar(value=component_combo_label("jbib"))
        comp_box = ttk.Combobox(
            toolbar,
            textvariable=self._default_comp_var,
            values=component_combo_values(),
            width=22,
            style="Dark.TCombobox",
        )
        comp_box.pack(side=tk.LEFT, padx=(4, 12))
        comp_box.bind("<<ComboboxSelected>>", lambda _e: self._schedule_global_naming())

        tk.Label(toolbar, text="№:", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._default_number_var = tk.StringVar(value="000")
        num_entry = self._entry(toolbar, self._default_number_var, width=5)
        num_entry.pack(side=tk.LEFT, padx=(4, 12))
        self._default_number_var.trace_add("write", lambda *_a: self._schedule_global_naming())

        tk.Label(toolbar, text="тип:", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 8)).pack(side=tk.LEFT)
        self._default_variant_var = tk.StringVar(value="uni")
        variant_box = ttk.Combobox(
            toolbar,
            textvariable=self._default_variant_var,
            values=["uni", "whi"],
            width=5,
            state="readonly",
            style="Dark.TCombobox",
        )
        variant_box.pack(side=tk.LEFT, padx=(4, 12))
        variant_box.bind("<<ComboboxSelected>>", lambda _e: self._schedule_global_naming())

        self._count_label = tk.Label(toolbar, text="0 файлов", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 9))
        self._count_label.pack(side=tk.RIGHT)

        self._global_naming_after_id: str | None = None

        self._build_list_header()

        body = tk.Frame(self.root, bg=BG_VIEW)
        body.pack(fill=tk.BOTH, expand=True, padx=(12, 8), pady=(0, 8))

        list_wrap = tk.Frame(body, bg=BG_VIEW)
        list_wrap.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._list_canvas = tk.Canvas(list_wrap, bg=BG_VIEW, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=self._list_canvas.yview)
        self._list_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._list_inner = tk.Frame(self._list_canvas, bg=BG_VIEW)
        self._list_window = self._list_canvas.create_window((0, 0), window=self._list_inner, anchor=tk.NW)
        self._list_inner.bind("<Configure>", self._on_list_configure)
        self._list_canvas.bind("<Configure>", self._on_list_canvas_configure)
        self._list_inner.bind("<MouseWheel>", self._on_list_wheel, add="+")
        list_wrap.bind("<Enter>", self._bind_list_wheel)
        list_wrap.bind("<Leave>", self._unbind_list_wheel)

        self._build_preview_panel(body)

        footer = tk.Frame(self.root, bg=BG_BAR, padx=12, pady=10)
        footer.pack(fill=tk.X)

        out_row = tk.Frame(footer, bg=BG_BAR)
        out_row.pack(fill=tk.X)
        tk.Label(out_row, text="out:", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self._folder_var = tk.StringVar(value=str(self._output_dir))
        tk.Entry(
            out_row,
            textvariable=self._folder_var,
            bg=BG_FIELD,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        flat_button(out_row, "…", self._pick_folder).pack(side=tk.LEFT)

        self._progress_frame = tk.Frame(footer, bg=BG_BAR)
        self._progress_status = tk.Label(
            self._progress_frame,
            text="",
            bg=BG_BAR,
            fg=FG_DIM,
            font=("Segoe UI", 9),
            anchor=tk.W,
        )
        self._progress_status.pack(fill=tk.X)
        self._progress_pct = tk.StringVar(value="0 %")
        tk.Label(
            self._progress_frame,
            textvariable=self._progress_pct,
            bg=BG_BAR,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.E)
        style = ttk.Style(self.root)
        style.configure(
            "Build.Horizontal.TProgressbar",
            troughcolor=BG_FIELD,
            background=ACCENT,
            bordercolor=BG_FIELD,
            lightcolor=ACCENT,
            darkcolor=ACCENT,
            thickness=8,
        )
        self._progress_bar = ttk.Progressbar(
            self._progress_frame,
            mode="determinate",
            style="Build.Horizontal.TProgressbar",
        )
        self._progress_bar.pack(fill=tk.X, pady=(4, 0))

        self._pack_btn = tk.Button(
            footer,
            text="Собрать YTD →",
            command=self._build,
            bg=ACCENT,
            fg="#ffffff",
            activebackground=ACCENT,
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 11, "bold"),
            pady=10,
            cursor="hand2",
            bd=0,
            highlightthickness=0,
        )
        self._pack_btn.pack(fill=tk.X, pady=(10, 0))

    def _build_list_header(self) -> None:
        bar = tk.Frame(self.root, bg=BG_BAR_TOP)
        bar.pack(fill=tk.X)
        inner = tk.Frame(bar, bg=BG_BAR_TOP, padx=12, pady=6)
        inner.pack(fill=tk.X)
        inner.grid_columnconfigure(0, minsize=_COL_GRIP)
        inner.grid_columnconfigure(1, minsize=_COL_ORDER)
        inner.grid_columnconfigure(2, minsize=0)
        inner.columnconfigure(2, weight=1)
        inner.grid_columnconfigure(3, minsize=_COL_SIZE)
        inner.grid_columnconfigure(4, minsize=_COL_FMT)
        inner.grid_columnconfigure(5, minsize=_COL_MIPS)
        inner.grid_columnconfigure(6, minsize=_COL_THUMB)
        inner.grid_columnconfigure(7, minsize=_COL_DEL)

        grip_sp = tk.Frame(inner, bg=BG_BAR_TOP, width=_COL_GRIP, height=1)
        grip_sp.grid(row=0, column=0, sticky="ns")
        grip_sp.grid_propagate(False)

        header_font = ("Segoe UI", 7, "bold")
        for col, text, padx in (
            (1, "№", (0, 4)),
            (2, "имя", (0, 12)),
            (3, "размер", (0, 8)),
            (4, "сжатие", (0, 6)),
            (5, "mips", (0, 8)),
        ):
            tk.Label(
                inner,
                text=text,
                bg=BG_BAR_TOP,
                fg=FG_DIM,
                font=header_font,
                anchor=tk.W,
            ).grid(row=0, column=col, sticky="w", padx=padx)

        thumb_sp = tk.Frame(inner, bg=BG_BAR_TOP, width=_COL_THUMB, height=1)
        thumb_sp.grid(row=0, column=6, sticky="ns")
        thumb_sp.grid_propagate(False)

        del_sp = tk.Frame(inner, bg=BG_BAR_TOP, width=_COL_DEL, height=1)
        del_sp.grid(row=0, column=7, sticky="ns")
        del_sp.grid_propagate(False)

    def _configure_list_row_grid(self, row: tk.Frame) -> None:
        row.columnconfigure(2, weight=1)
        row.grid_columnconfigure(0, minsize=_COL_GRIP)
        row.grid_columnconfigure(1, minsize=_COL_ORDER)
        row.grid_columnconfigure(3, minsize=_COL_SIZE)
        row.grid_columnconfigure(4, minsize=_COL_FMT)
        row.grid_columnconfigure(5, minsize=_COL_MIPS)
        row.grid_columnconfigure(6, minsize=_COL_THUMB)
        row.grid_columnconfigure(7, minsize=_COL_DEL)

    def _build_preview_panel(self, parent: tk.Frame) -> None:
        panel = tk.Frame(parent, bg=BG_STRIP, width=_PREVIEW_PANEL_W)
        panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        panel.pack_propagate(False)

        tk.Label(
            panel,
            text="Предпросмотр",
            bg=BG_STRIP,
            fg=FG,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(10, 6))

        img_wrap = tk.Frame(panel, bg=_PLACEHOLDER, width=_PREVIEW_MAX, height=_PREVIEW_MAX)
        img_wrap.pack(padx=12)
        img_wrap.pack_propagate(False)

        self._preview_image = tk.Label(img_wrap, bg=_PLACEHOLDER, bd=0)
        self._preview_image.pack(expand=True)

        self._preview_title = tk.Label(
            panel,
            text="—",
            bg=BG_STRIP,
            fg=FG,
            font=("Segoe UI", 9, "bold"),
            wraplength=_PREVIEW_PANEL_W - 24,
            justify=tk.LEFT,
        )
        self._preview_title.pack(anchor=tk.W, padx=12, pady=(10, 2))

        self._preview_meta = tk.Label(
            panel,
            text="Выберите текстуру в списке",
            bg=BG_STRIP,
            fg=FG_DIM,
            font=("Segoe UI", 8),
            wraplength=_PREVIEW_PANEL_W - 24,
            justify=tk.LEFT,
        )
        self._preview_meta.pack(anchor=tk.W, padx=12, pady=(0, 8))

        tk.Label(
            panel,
            text="Будет создано",
            bg=BG_STRIP,
            fg=FG_DIM,
            font=("Segoe UI", 7, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(4, 4))

        out_wrap = tk.Frame(panel, bg=BG_FIELD)
        out_wrap.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        self._output_canvas = tk.Canvas(
            out_wrap,
            bg=BG_FIELD,
            highlightthickness=0,
            bd=0,
        )
        scroll = ttk.Scrollbar(out_wrap, orient=tk.VERTICAL, command=self._output_canvas.yview)
        self._output_canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._output_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._output_inner = tk.Frame(self._output_canvas, bg=BG_FIELD)
        self._output_canvas_window = self._output_canvas.create_window(
            (0, 0),
            window=self._output_inner,
            anchor=tk.NW,
        )
        self._output_inner.bind(
            "<Configure>",
            lambda _e: self._output_canvas.configure(
                scrollregion=self._output_canvas.bbox("all")
            ),
        )
        self._output_canvas.bind(
            "<Configure>",
            lambda e: self._output_canvas.itemconfig(self._output_canvas_window, width=e.width),
        )

    def _entry(self, parent: tk.Misc, textvariable: tk.StringVar, *, width: int = 8) -> tk.Entry:
        return tk.Entry(
            parent,
            textvariable=textvariable,
            width=width,
            bg=BG_FIELD,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        )

    def _row_bg(self, index: int) -> str:
        if self._drag_row is not None and self._drag_hover_index is not None and index == self._drag_hover_index:
            return _DRAG_HOVER_BG
        if self._drag_row is not None and self._drag_moved:
            try:
                if self._rows[index] is self._drag_row:
                    return _DRAG_SOURCE_BG
            except IndexError:
                pass
        if index == self._selected_index:
            return _SEL_BG
        return BG_STRIP if index % 2 == 0 else _ROW_ALT

    def _apply_row_bg(self, row: _RowUi, index: int) -> None:
        bg = self._row_bg(index)
        for widget in (row.frame, row.row_frame, row.sub_label, row.name_label, row.grip_label):
            widget.configure(bg=bg)

    def _row_index(self, row_ui: _RowUi) -> int | None:
        try:
            return self._rows.index(row_ui)
        except ValueError:
            return None

    def _refresh_row_styles(self) -> None:
        for index, row in enumerate(self._rows):
            self._apply_row_bg(row, index)

    def _refresh_selection_styles(self) -> None:
        self._refresh_row_styles()

    def _on_list_configure(self, _event: object = None) -> None:
        if self._scrollregion_after_id is not None:
            self.root.after_cancel(self._scrollregion_after_id)
        self._scrollregion_after_id = self.root.after(80, self._update_scrollregion)

    def _update_scrollregion(self) -> None:
        self._scrollregion_after_id = None
        bbox = self._list_canvas.bbox("all")
        if bbox:
            self._list_canvas.configure(scrollregion=bbox)

    def _on_list_canvas_configure(self, event: tk.Event) -> None:
        self._list_canvas.itemconfig(self._list_window, width=event.width)

    def _bind_list_wheel(self, _event: object = None) -> None:
        if self._list_wheel_bound:
            return
        self._list_wheel_bound = True
        self.root.bind_all("<MouseWheel>", self._on_list_wheel)

    def _unbind_list_wheel(self, _event: object = None) -> None:
        if not self._list_wheel_bound:
            return
        self._list_wheel_bound = False
        self.root.unbind_all("<MouseWheel>")

    def _on_list_wheel(self, event: tk.Event) -> None:
        if not event.delta:
            return
        delta = -1 * (event.delta // 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
        self._list_canvas.yview_scroll(delta, "units")

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(initialdir=self._folder_var.get(), title="Папка для YTD")
        if path:
            self._folder_var.set(path)

    def _update_count(self) -> None:
        n = len(self._items)
        self._count_label.configure(text=f"{n} файлов • {n} ytd")

    def _parse_default_number(self) -> int:
        try:
            return max(0, int(self._default_number_var.get().strip()))
        except ValueError:
            return 1

    def _schedule_global_naming(self) -> None:
        if self._global_naming_after_id is not None:
            self.root.after_cancel(self._global_naming_after_id)
        self._global_naming_after_id = self.root.after(450, self._run_scheduled_global_naming)

    def _run_scheduled_global_naming(self) -> None:
        self._global_naming_after_id = None
        self._apply_global_naming(rebuild=False)

    def _apply_global_naming(self, *, rebuild: bool = True) -> None:
        if self._updating:
            return
        if not self._items:
            if rebuild:
                self._rebuild_list()
            return
        component = normalize_component(self._default_comp_var.get())
        variant = normalize_variant(self._default_variant_var.get())
        number = self._parse_default_number()
        self._updating = True
        try:
            for index, item in enumerate(self._items):
                item = replace(
                    item,
                    component=component,
                    number=number,
                    suffix=suffix_letter(index),
                    variant=variant,
                )
                self._items[index] = apply_item_naming(item)
            self._default_comp_var.set(component_combo_label(component))
            self._default_variant_var.set(variant)
            if rebuild:
                self._rebuild_list()
            else:
                self._sync_order_fields()
                for index, row in enumerate(self._rows):
                    item = self._items[index]
                    row.name_label.configure(text=item.ytd_name)
                    row.sub_label.configure(text=f"{item.path.name}  →  {item.ytd_name}")
                self._schedule_output_refresh()
                if self._selected_index is not None:
                    self._update_preview_meta(self._selected_index)
        finally:
            self._updating = False

    def _schedule_output_refresh(self) -> None:
        if self._output_refresh_after_id is not None:
            self.root.after_cancel(self._output_refresh_after_id)
        self._output_refresh_after_id = self.root.after(200, self._run_output_refresh)

    def _run_output_refresh(self) -> None:
        self._output_refresh_after_id = None
        self._refresh_output_list()

    def _add_paths(self, paths: list[Path]) -> None:
        ordered = _paths_in_user_order(paths)
        if not ordered:
            return
        component = normalize_component(self._default_comp_var.get())
        variant = normalize_variant(self._default_variant_var.get())
        number = self._parse_default_number()
        base_index = len(self._items)
        for offset, path in enumerate(ordered):
            try:
                self._items.append(
                    load_build_item(
                        path,
                        component=component,
                        number=number,
                        suffix=suffix_letter(base_index + offset),
                        variant=variant,
                        format_label=AUTO_FORMAT,
                    )
                )
            except Exception as exc:
                messagebox.showerror("Ошибка", f"{path.name}:\n{exc}", parent=self.root)
        self._apply_global_naming(rebuild=True)
        self._update_count()

    def _add_files_dialog(self) -> None:
        picked = filedialog.askopenfilenames(
            title="Добавить изображения",
            initialdir=self._folder_var.get(),
            filetypes=[
                ("Изображения", "*.png *.jpg *.jpeg *.bmp *.tga *.tiff *.dds"),
                ("Все файлы", "*.*"),
            ],
        )
        if not picked:
            return
        # Tcl returns paths in the order the user selected them in the dialog.
        self._add_paths([Path(p) for p in picked])

    def _clear_all(self) -> None:
        if not self._items:
            return
        if not messagebox.askyesno("Очистить", "Удалить все текстуры из списка?", parent=self.root):
            return
        self._items.clear()
        self._selected_index = None
        self._rebuild_list()
        self._update_count()
        self._clear_preview()

    def _rebuild_list(self) -> None:
        for child in self._list_inner.winfo_children():
            child.destroy()
        self._rows.clear()
        self._row_thumb_photos.clear()
        self._row_thumb_generation += 1

        for index, item in enumerate(self._items):
            selected = index == self._selected_index
            bg = _SEL_BG if selected else (BG_STRIP if index % 2 == 0 else _ROW_ALT)
            block = tk.Frame(self._list_inner, bg=bg)
            block.pack(fill=tk.X, pady=1)

            row = tk.Frame(block, bg=bg)
            row.pack(fill=tk.X)
            self._configure_list_row_grid(row)

            grip = tk.Label(row, text="⋮⋮", bg=bg, fg=FG_DIM, font=("Segoe UI", 9), cursor="fleur")
            grip.grid(row=0, column=0, padx=(8, 4), pady=8, sticky="ns")

            order_var = tk.StringVar(value=str(index + 1))
            order_entry = self._entry(row, order_var, width=4)
            order_entry.grid(row=0, column=1, padx=(0, 4), pady=8, sticky="w")

            name_lbl = tk.Label(
                row,
                text=item.ytd_name,
                bg=bg,
                fg=FG,
                font=("Segoe UI", 8),
                anchor=tk.W,
            )
            name_lbl.grid(row=0, column=2, padx=(0, 12), pady=8, sticky="w")

            res = tk.Label(
                row,
                text=f"{item.width}×{item.height}",
                bg=bg,
                fg=FG_DIM,
                font=("Segoe UI", 8),
                width=10,
                anchor=tk.W,
            )
            res.grid(row=0, column=3, padx=(0, 8), pady=8, sticky="w")

            format_var = tk.StringVar(value=item.format_label if item.format_label in _FORMAT_COMBO else AUTO_FORMAT)
            fmt = ttk.Combobox(
                row,
                textvariable=format_var,
                values=_FORMAT_COMBO,
                width=13,
                state="readonly",
                style="Dark.TCombobox",
            )
            fmt.grid(row=0, column=4, padx=(0, 6), pady=8, sticky="w")

            mip_var = tk.StringVar(value=mip_display_value(item))
            mip = ttk.Combobox(
                row,
                textvariable=mip_var,
                values=["auto", *_MIPS_COMBO],
                width=5,
                state="readonly",
                style="Dark.TCombobox",
            )
            mip.grid(row=0, column=5, padx=(0, 8), pady=8, sticky="w")

            thumb_wrap = tk.Frame(row, bg=_PLACEHOLDER, width=_THUMB_SIZE + 4, height=_THUMB_SIZE + 4)
            thumb_wrap.grid(row=0, column=6, padx=(0, 4), pady=6, sticky="e")
            thumb_wrap.grid_propagate(False)
            thumb_lbl = tk.Label(thumb_wrap, bg=_PLACEHOLDER, bd=0)
            thumb_lbl.pack(expand=True, fill=tk.BOTH)

            sub = tk.Label(
                block,
                text=f"{item.path.name}  →  {item.ytd_name}",
                bg=bg,
                fg=FG_DIM,
                font=("Segoe UI", 7),
                anchor=tk.W,
            )
            sub.pack(fill=tk.X, padx=(36, 12), pady=(0, 6))

            row_ui = _RowUi(
                frame=block,
                row_frame=row,
                order_var=order_var,
                format_var=format_var,
                mip_var=mip_var,
                sub_label=sub,
                name_label=name_lbl,
                thumb_label=thumb_lbl,
                grip_label=grip,
            )

            tk.Button(
                row,
                text="×",
                command=lambda r=row_ui: self._remove_row_ui(r),
                bg=bg,
                fg=FG_DIM,
                activebackground=BTN,
                activeforeground=FG,
                relief=tk.FLAT,
                font=("Segoe UI", 10),
                width=2,
                cursor="hand2",
                bd=0,
            ).grid(row=0, column=7, padx=(4, 8), pady=6, sticky="e")

            fmt.bind("<<ComboboxSelected>>", lambda _e, r=row_ui: self._commit_row(r))
            mip.bind("<<ComboboxSelected>>", lambda _e, r=row_ui: self._commit_row(r))
            self._bind_drag(grip, row_ui)
            self._bind_drag(row_ui.grip_label, row_ui)
            order_entry.bind("<Return>", lambda _e, r=row_ui: self._move_row_by_order(r))
            order_entry.bind("<FocusOut>", lambda _e, r=row_ui: self._move_row_by_order(r))

            for w in (block, row, sub, name_lbl, thumb_wrap, thumb_lbl):
                self._bind_row_select(w, row_ui)

            self._rows.append(row_ui)

        self._on_list_configure()
        self._load_row_thumbs()
        if self._items and self._selected_index is None:
            self._selected_index = 0
        self._refresh_output_list()
        if self._selected_index is not None and 0 <= self._selected_index < len(self._items):
            self._load_preview(self._selected_index)
        elif not self._items:
            self._clear_preview()

    def _bind_row_select(self, widget: tk.Widget, row_ui: _RowUi) -> None:
        widget.bind("<Button-1>", lambda e, r=row_ui: self._on_row_click(r, e), add="+")

    def _on_row_click(self, row_ui: _RowUi, _event: tk.Event) -> None:
        index = self._row_index(row_ui)
        if index is not None:
            self._select_row(index)

    def _select_row(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            return
        prev = self._selected_index
        self._selected_index = index
        if prev is not None and prev < len(self._rows):
            self._apply_row_bg(self._rows[prev], prev)
        if index < len(self._rows):
            self._apply_row_bg(self._rows[index], index)
        self._load_preview(index)
        self._update_preview_meta(index)

    def _clear_preview(self) -> None:
        self._preview_photo = None
        self._preview_image.configure(image="", bg=_PLACEHOLDER)
        self._preview_title.configure(text="—")
        self._preview_meta.configure(text="Выберите текстуру в списке")
        self._refresh_output_list()

    def _update_preview_meta(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            return
        item = self._items[index]
        mips = mip_display_value(item)
        fmt = item.format_label
        self._preview_title.configure(text=item.ytd_name)
        self._preview_meta.configure(
            text=(
                f"{item.texture_name}\n"
                f"{item.width}×{item.height}  •  mips: {mips}  •  {fmt}\n"
                f"{item.path.name}"
            )
        )

    def _load_preview(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            return
        self._update_preview_meta(index)
        self._preview_generation += 1
        generation = self._preview_generation
        path = self._items[index].path

        def work() -> None:
            try:
                pil = _load_preview_pil(path, _PREVIEW_MAX)
                err: str | None = None
            except Exception as exc:
                pil = Image.new("RGBA", (_PREVIEW_MAX, _PREVIEW_MAX), (56, 56, 56, 255))
                err = str(exc)

            def apply() -> None:
                if generation != self._preview_generation:
                    return
                photo = ImageTk.PhotoImage(pil)
                self._preview_photo = photo
                self._preview_image.configure(image=photo, bg=_PLACEHOLDER)
                if err:
                    self._preview_meta.configure(
                        text=f"{self._items[index].path.name}\n(ошибка превью: {err})"
                    )

            self.root.after(0, apply)

        threading.Thread(target=work, name="ytd-build-preview", daemon=True).start()

    def _load_row_thumbs(self) -> None:
        generation = self._row_thumb_generation
        pending: list[tuple[int, Path]] = []

        for index, item in enumerate(self._items):
            if index >= len(self._rows):
                break
            path_key = str(item.path.resolve())
            cached_photo = self._thumb_photo_by_path.get(path_key)
            if cached_photo is not None:
                self._rows[index].thumb_label.configure(image=cached_photo, bg=_PLACEHOLDER)
                continue
            pending.append((index, item.path))

        if not pending:
            return

        def batch_work() -> None:
            loaded: list[tuple[int, Image.Image, str]] = []
            for index, path in pending:
                if generation != self._row_thumb_generation:
                    return
                try:
                    pil = _load_preview_pil(path, _THUMB_SIZE)
                except Exception:
                    pil = Image.new("RGBA", (_THUMB_SIZE, _THUMB_SIZE), (56, 56, 56, 255))
                loaded.append((index, pil, str(path.resolve())))

            def apply_all() -> None:
                if generation != self._row_thumb_generation:
                    return
                for index, pil, path_key in loaded:
                    if index >= len(self._rows):
                        continue
                    photo = self._thumb_photo_by_path.get(path_key)
                    if photo is None:
                        photo = ImageTk.PhotoImage(pil)
                        self._thumb_photo_by_path[path_key] = photo
                    self._rows[index].thumb_label.configure(image=photo, bg=_PLACEHOLDER)

            self.root.after(0, apply_all)

        threading.Thread(target=batch_work, name="ytd-build-thumbs", daemon=True).start()

    def _refresh_output_list(self) -> None:
        for frame, _lbl in self._output_rows:
            frame.destroy()
        self._output_rows.clear()
        self._output_thumb_generation += 1

        if not self._items:
            empty = tk.Label(
                self._output_inner,
                text="—",
                bg=BG_FIELD,
                fg=FG_DIM,
                font=("Segoe UI", 8),
                anchor=tk.W,
            )
            empty.pack(anchor=tk.W, padx=4, pady=4)
            return

        for raw in self._items:
            item = apply_item_naming(raw)
            row = tk.Frame(self._output_inner, bg=BG_FIELD)
            row.pack(fill=tk.X, pady=3)

            thumb_wrap = tk.Frame(
                row,
                bg=_PLACEHOLDER,
                width=_OUTPUT_THUMB + 4,
                height=_OUTPUT_THUMB + 4,
            )
            thumb_wrap.pack(side=tk.LEFT, padx=(0, 6))
            thumb_wrap.pack_propagate(False)
            thumb_lbl = tk.Label(thumb_wrap, bg=_PLACEHOLDER, bd=0)
            thumb_lbl.pack(expand=True, fill=tk.BOTH)

            text_col = tk.Frame(row, bg=BG_FIELD)
            text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
            tk.Label(
                text_col,
                text=item.ytd_name,
                bg=BG_FIELD,
                fg=FG,
                font=("Segoe UI", 8, "bold"),
                anchor=tk.W,
                justify=tk.LEFT,
            ).pack(anchor=tk.W)
            tk.Label(
                text_col,
                text=item.texture_name,
                bg=BG_FIELD,
                fg=FG_DIM,
                font=("Segoe UI", 7),
                anchor=tk.W,
                justify=tk.LEFT,
            ).pack(anchor=tk.W)

            self._output_rows.append((row, thumb_lbl))

        self._load_output_thumbs()

    def _load_output_thumbs(self) -> None:
        generation = self._output_thumb_generation
        pending: list[tuple[int, Path]] = []
        for index, raw in enumerate(self._items):
            if index >= len(self._output_rows):
                break
            path_key = str(raw.path.resolve())
            cached = self._thumb_photo_by_path.get(path_key)
            if cached is not None:
                self._output_rows[index][1].configure(image=cached, bg=_PLACEHOLDER)
                continue
            pending.append((index, raw.path))

        if not pending:
            return

        def batch_work() -> None:
            loaded: list[tuple[int, Image.Image, str]] = []
            for index, path in pending:
                if generation != self._output_thumb_generation:
                    return
                try:
                    pil = _load_preview_pil(path, _OUTPUT_THUMB)
                except Exception:
                    pil = Image.new("RGBA", (_OUTPUT_THUMB, _OUTPUT_THUMB), (56, 56, 56, 255))
                loaded.append((index, pil, str(path.resolve())))

            def apply_all() -> None:
                if generation != self._output_thumb_generation:
                    return
                for index, pil, path_key in loaded:
                    if index >= len(self._output_rows):
                        continue
                    photo = self._thumb_photo_by_path.get(path_key)
                    if photo is None:
                        photo = ImageTk.PhotoImage(pil)
                        self._thumb_photo_by_path[path_key] = photo
                    self._output_rows[index][1].configure(image=photo, bg=_PLACEHOLDER)

            self.root.after(0, apply_all)

        threading.Thread(target=batch_work, name="ytd-build-output-thumbs", daemon=True).start()

    def _bind_drag(self, widget: tk.Widget, row_ui: _RowUi) -> None:
        widget.bind(
            "<ButtonPress-1>",
            lambda e, r=row_ui: self._drag_start(r, e),
            add="+",
        )

    def _bind_drag_global(self) -> None:
        self._unbind_drag_global()
        self.root.bind_all("<B1-Motion>", self._drag_motion)
        self.root.bind_all("<ButtonRelease-1>", self._drag_release_global)

    def _unbind_drag_global(self) -> None:
        try:
            self.root.unbind_all("<B1-Motion>")
        except tk.TclError:
            pass
        try:
            self.root.unbind_all("<ButtonRelease-1>")
        except tk.TclError:
            pass
        self._drag_motion_bind = None
        self._drag_release_bind = None

    def _drag_release_global(self, event: tk.Event) -> None:
        row_ui = self._drag_row
        if row_ui is None:
            self._unbind_drag_global()
            return
        self._unbind_drag_global()
        self._drag_end(row_ui, event)

    def _sync_order_fields(self) -> None:
        self._updating = True
        try:
            for index, row in enumerate(self._rows):
                row.order_var.set(str(index + 1))
        finally:
            self._updating = False

    def _finish_reorder(self) -> None:
        self._apply_global_naming(rebuild=False)
        self._repaint_order()
        self._sync_order_fields()
        self._refresh_row_styles()
        self._schedule_output_refresh()

    def _reorder_items(self, from_idx: int, to_idx: int) -> None:
        if from_idx < 0 or to_idx < 0 or from_idx >= len(self._items) or to_idx >= len(self._items):
            return
        if from_idx == to_idx:
            return

        item = self._items.pop(from_idx)
        row_ui = self._rows.pop(from_idx)
        self._items.insert(to_idx, item)
        self._rows.insert(to_idx, row_ui)

        if self._selected_index is not None:
            sel = self._selected_index
            if sel == from_idx:
                sel = to_idx
            elif from_idx < sel <= to_idx:
                sel -= 1
            elif to_idx <= sel < from_idx:
                sel += 1
            self._selected_index = sel

        self._finish_reorder()

    def _move_row_by_order(self, row_ui: _RowUi) -> None:
        if self._updating:
            return
        index = self._row_index(row_ui)
        if index is None:
            return
        try:
            new_pos = int(row_ui.order_var.get().strip())
        except ValueError:
            row_ui.order_var.set(str(index + 1))
            return

        new_index = max(1, min(len(self._items), new_pos)) - 1
        if new_index == index:
            row_ui.order_var.set(str(index + 1))
            return

        self._reorder_items(index, new_index)

    def _commit_row(self, row_ui: _RowUi) -> None:
        if self._updating:
            return
        index = self._row_index(row_ui)
        if index is None:
            return
        row = row_ui

        mip_count, mip_manual = parse_mip_display(row.mip_var.get(), self._items[index])
        item = self._items[index]
        item = replace(
            item,
            format_label=row.format_var.get() or AUTO_FORMAT,
            mip_count=mip_count,
            mip_manual=mip_manual,
        )
        self._items[index] = apply_item_naming(item)
        row.name_label.configure(text=self._items[index].ytd_name)
        row.sub_label.configure(text=f"{item.path.name}  →  {self._items[index].ytd_name}")
        if index == self._selected_index:
            self._update_preview_meta(index)

    def _remove_row_ui(self, row_ui: _RowUi) -> None:
        index = self._row_index(row_ui)
        if index is not None:
            self._remove_row(index)

    def _remove_row(self, index: int) -> None:
        if index < 0 or index >= len(self._items):
            return
        was_selected = index == self._selected_index
        self._rows[index].frame.destroy()
        del self._items[index]
        del self._rows[index]
        if was_selected:
            self._selected_index = min(index, len(self._items) - 1) if self._items else None
        elif self._selected_index is not None and index < self._selected_index:
            self._selected_index -= 1
        self._apply_global_naming(rebuild=False)
        self._sync_order_fields()
        self._refresh_row_styles()
        self._schedule_output_refresh()
        self._update_count()
        self._on_list_configure()

    def _repaint_order(self) -> None:
        for row in self._rows:
            row.frame.pack_forget()
        for row in self._rows:
            row.frame.pack(fill=tk.X, pady=1)
        self._on_list_configure()

    def _drop_index_at_y(self, y_root: int) -> int:
        if not self._rows:
            return 0
        self.root.update_idletasks()
        rows = self._rows
        first_y = rows[0].frame.winfo_rooty()
        if y_root < first_y:
            return 0
        last = rows[-1]
        last_y = last.frame.winfo_rooty()
        last_h = max(last.frame.winfo_height(), 1)
        if y_root >= last_y + last_h:
            return len(rows) - 1
        for i, row in enumerate(rows):
            y = row.frame.winfo_rooty()
            h = max(row.frame.winfo_height(), 1)
            if y <= y_root < y + h // 2:
                return i
            if y + h // 2 <= y_root < y + h:
                return min(i + 1, len(rows) - 1)
        return len(rows) - 1

    def _drag_start(self, row_ui: _RowUi, event: tk.Event) -> str:
        if self._drag_row is not None:
            return "break"
        self._drag_row = row_ui
        self._drag_hover_index = self._row_index(row_ui)
        self._drag_start_y = event.y_root
        self._drag_moved = False
        self._bind_drag_global()
        return "break"

    def _drag_motion(self, event: tk.Event) -> None:
        if self._drag_row is None:
            return
        if abs(event.y_root - self._drag_start_y) > 4:
            self._drag_moved = True
        from_idx = self._row_index(self._drag_row)
        if from_idx is None:
            return
        hover = self._drop_index_at_y(event.y_root)
        if hover != self._drag_hover_index:
            self._drag_hover_index = hover
            self._refresh_row_styles()

    def _drag_end(self, row_ui: _RowUi, event: tk.Event) -> None:
        from_idx = self._row_index(row_ui)
        was_moved = self._drag_moved
        self._drag_row = None
        self._drag_hover_index = None
        self._drag_moved = False
        self._refresh_row_styles()

        if from_idx is None:
            return
        if not was_moved:
            self._select_row(from_idx)
            return

        target = self._drop_index_at_y(event.y_root)
        if target == from_idx:
            return
        self._reorder_items(from_idx, target)

    def _index_at_root_y(self, y_root: int) -> int | None:
        if not self._rows:
            return None
        return self._drop_index_at_y(y_root)

    def _resolve_items_for_build(self) -> list[TextureBuildItem]:
        self._updating = True
        try:
            for row in self._rows:
                self._commit_row(row)
        finally:
            self._updating = False

        resolved: list[TextureBuildItem] = []
        built_in_fmt = default_format_label()

        for item in self._items:
            fmt = built_in_fmt if item.format_label == AUTO_FORMAT else item.format_label
            if item.mip_manual:
                mips = item.mip_count
            else:
                mips = auto_mip_count(item.width, item.height)
            resolved.append(
                replace(
                    item,
                    format_label=fmt,
                    mip_count=mips,
                )
            )
        return resolved

    def _show_build_progress(self, total: int) -> None:
        self._pack_btn.configure(state=tk.DISABLED)
        self._progress_bar.configure(maximum=max(1, total), value=0)
        self._progress_pct.set("0 %")
        self._progress_status.config(text="Сборка…")
        self._progress_frame.pack(fill=tk.X, pady=(8, 0), before=self._pack_btn)

    def _update_build_progress(self, current: int, total: int, message: str) -> None:
        total = max(1, total)
        current = max(0, min(current, total))
        self._progress_bar.configure(maximum=total, value=current)
        pct = int(round(100 * current / total))
        self._progress_pct.set(f"{pct} %")
        self._progress_status.config(text=message)

    def _hide_build_progress(self) -> None:
        self._progress_frame.pack_forget()
        self._pack_btn.configure(state=tk.NORMAL)

    def _build(self) -> None:
        if not self._items:
            return
        out = Path(self._folder_var.get().strip())
        if not out.is_dir():
            messagebox.showerror("Ошибка", "Укажите существующую папку", parent=self.root)
            return

        try:
            items = self._resolve_items_for_build()
            for item in items:
                parse_format(item.format_label)
        except Exception as exc:
            messagebox.showerror("Ошибка", str(exc), parent=self.root)
            return

        self._show_build_progress(len(items))

        def work() -> None:
            try:

                def report(current: int, total: int, message: str) -> None:
                    self.root.after(0, lambda c=current, t=total, m=message: self._update_build_progress(c, t, m))

                paths = build_ytd_files(items, out, on_progress=report)
                self.root.after(0, lambda: self._on_built(out, len(paths), None))
            except Exception as exc:
                self.root.after(0, lambda: self._on_built(None, 0, str(exc)))

        threading.Thread(target=work, name="ytd-build", daemon=True).start()

    def _on_built(self, folder: Path | None, count: int, error: str | None) -> None:
        self._hide_build_progress()
        if error:
            messagebox.showerror("Сборка YTD", error, parent=self.root)
            return
        notify_build_result(folder, count)
        self._unbind_list_wheel()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def open_ytd_build_window(image_paths: list[str | Path]) -> None:
    paths = _paths_in_user_order([Path(p) for p in image_paths])
    try:
        YtdBuildWindow(paths).run()
    except ValueError as exc:
        notify_build_result(None, 0, error=str(exc))


def run_build_window_safe(image_paths: list[str | Path]) -> None:
    try:
        open_ytd_build_window(image_paths)
    except Exception as exc:
        notify_build_result(None, 0, error=str(exc))
