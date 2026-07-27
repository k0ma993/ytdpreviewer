"""Photo-style viewer for textures inside a .ytd file."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from texfury import ITD, Texture

from ytdpreviewer.ytd_texture_preview import thumb_mip_level
from ytdpreviewer.texture_edit import (
    FORMAT_OPTIONS,
    format_label,
    max_mip_count,
    parse_format,
    recompress_texture,
    replace_texture_from_image,
)
from ytdpreviewer.app_icon import apply_tk_icon
from ytdpreviewer.ui_theme import (
    ACCENT,
    APP_CREDIT,
    BG_BAR,
    BG_FIELD,
    FG,
    FG_DIM,
    ToolTip,
    bar_separator,
    center_tk_window,
    field_column,
    flat_button,
    setup_dark_ttk,
)

BG_VIEW = "#1c1c1c"
BG_STRIP = "#242424"
THUMB_SIZE = 88
THUMB_PAD = 8
BAR_H = 62
PLACEHOLDER = "#383838"
FORMAT_VALUES = [label for label, _ in FORMAT_OPTIONS]


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} Б"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} КБ"
    return f"{num_bytes / (1024 * 1024):.1f} МБ"


def _thumb_from_pil(image: Image.Image) -> Image.Image:
    img = image.convert("RGBA")
    img.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.Resampling.BILINEAR)
    return img


class PreviewWindow:
    def __init__(self, root: tk.Misc, ytd_path: str | Path) -> None:
        self.root = root
        if isinstance(root, tk.Toplevel):
            root.protocol("WM_DELETE_WINDOW", self._on_close)
        elif isinstance(root, tk.Tk):
            root.configure(bg=BG_VIEW)
            root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.path = Path(ytd_path).resolve()
        self._dds_only = self.path.suffix.lower() == ".dds"
        self._td: ITD | None = None
        self._textures: list = []
        self._dirty = False
        self._applying = False
        self._main_photo: ImageTk.PhotoImage | None = None
        self._thumb_photos: list[ImageTk.PhotoImage | None] = []
        self._thumb_labels: list[tk.Label] = []
        self._pil_cache: dict[tuple[int, int], Image.Image] = {}
        self._selected = -1
        self._current_pil: Image.Image | None = None
        self._decode_generation = 0
        self._resize_after: str | None = None
        self._zoom_after: str | None = None
        self._quality_after: str | None = None
        self._cache_lock = threading.Lock()
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag: tuple[int, int, float, float, float, float] | None = None
        self._image_id: int | None = None
        self._rendered_zoom = 0.0
        self._rendered_size: tuple[int, int] = (0, 0)

        ZOOM_MIN, ZOOM_MAX, ZOOM_STEP = 0.08, 40.0, 1.12
        self._ZOOM_MIN = ZOOM_MIN
        self._ZOOM_MAX = ZOOM_MAX
        self._ZOOM_STEP = ZOOM_STEP

        self.root.title(self.path.name)
        self.root.minsize(640, 480)
        self.root.geometry("1000x700")
        apply_tk_icon(self.root)
        self.root.configure(bg=BG_VIEW)

        from ytdpreviewer.window_front import focus_preview_window

        self.root.after(0, lambda: focus_preview_window(self.root))

        self._strip: tk.Frame | None = None
        self._thumb_btns: list[tk.Frame] = []

        self._content = tk.Frame(self.root, bg=BG_VIEW)
        self._content.pack(fill=tk.BOTH, expand=True)

        self._view_host = tk.Frame(self._content, bg=BG_VIEW)
        self._view_host.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(self._view_host, bg=BG_VIEW, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas_bg_id: int | None = None
        self.canvas.bind("<Map>", self._ensure_canvas_bg)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda e: self._on_wheel(e, delta=120))
        self.canvas.bind("<Button-5>", lambda e: self._on_wheel(e, delta=-120))
        self.canvas.bind("<ButtonPress-1>", self._on_pan_start)
        self.canvas.bind("<B1-Motion>", self._on_pan_move)
        self.canvas.bind("<ButtonRelease-1>", self._on_pan_end)
        self.canvas.bind("<Double-Button-1>", lambda _e: self._reset_view(redraw=True))

        tk.Frame(self.root, bg="#333333", height=1).pack(fill=tk.X, side=tk.BOTTOM)

        bar = tk.Frame(self.root, bg=BG_BAR, height=BAR_H)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)

        setup_dark_ttk(self.root)

        left = tk.Frame(bar, bg=BG_BAR)
        left.pack(side=tk.LEFT, fill=tk.Y)

        fields = tk.Frame(left, bg=BG_BAR)
        fields.pack(side=tk.LEFT, pady=8)

        entry_style = {
            "bg": BG_FIELD,
            "fg": FG,
            "insertbackground": FG,
            "relief": tk.FLAT,
            "font": ("Segoe UI", 10),
            "highlightthickness": 1,
            "highlightbackground": "#454545",
            "highlightcolor": ACCENT,
        }

        size_body = field_column(fields, "Размер")
        size_row = tk.Frame(size_body, bg=BG_BAR)
        size_row.pack(anchor=tk.W)
        self._width_var = tk.StringVar(value="1")
        self._height_var = tk.StringVar(value="1")
        self._width_spin = tk.Spinbox(
            size_row,
            from_=1,
            to=8192,
            width=5,
            textvariable=self._width_var,
            **entry_style,
            buttonbackground="#454545",
        )
        self._width_spin.pack(side=tk.LEFT, ipady=4)
        tk.Label(size_row, text="×", bg=BG_BAR, fg=FG_DIM, font=("Segoe UI", 10)).pack(
            side=tk.LEFT, padx=4
        )
        self._height_spin = tk.Spinbox(
            size_row,
            from_=1,
            to=8192,
            width=5,
            textvariable=self._height_var,
            **entry_style,
            buttonbackground="#454545",
        )
        self._height_spin.pack(side=tk.LEFT, ipady=4)

        name_body = field_column(fields, "Имя")
        self._name_var = tk.StringVar()
        self._name_entry = tk.Entry(name_body, textvariable=self._name_var, width=16, **entry_style)
        self._name_entry.pack(ipady=4)

        fmt_body = field_column(fields, "Сжатие")
        self._format_var = tk.StringVar(value=FORMAT_VALUES[0])
        self._format_combo = ttk.Combobox(
            fmt_body,
            textvariable=self._format_var,
            values=FORMAT_VALUES,
            state="readonly",
            width=14,
            style="Dark.TCombobox",
            font=("Segoe UI", 10),
        )
        self._format_combo.pack(ipady=2)

        mip_body = field_column(fields, "Mip")
        self._mip_var = tk.StringVar(value="1")
        self._mip_spin = tk.Spinbox(
            mip_body,
            from_=1,
            to=16,
            width=5,
            textvariable=self._mip_var,
            **entry_style,
            buttonbackground="#454545",
        )
        self._mip_spin.pack(ipady=4)

        bar_separator(left)

        actions = tk.Frame(left, bg=BG_BAR)
        actions.pack(side=tk.LEFT, pady=10)

        self._btn_apply = flat_button(actions, "Обновить", self._apply_edits)
        self._btn_apply.pack(side=tk.LEFT, padx=(0, 6))
        ToolTip(
            self._btn_apply,
            "Перекодировать текущую текстуру.\n"
            "Размер, формат и mip — из полей панели.",
        )

        self._btn_replace = flat_button(actions, "Заменить…", self._replace_texture)
        self._btn_replace.pack(side=tk.LEFT, padx=(0, 6))
        ToolTip(
            self._btn_replace,
            "Подставить PNG/JPG/DDS вместо выбранной текстуры.\n"
            "Или перетащите файл на окно превью.\n"
            "Итоговый размер — из полей «Размер»; имя/формат/mip — ниже.",
        )

        save_label = "Сохранить DDS" if self._dds_only else "Сохранить YTD"
        self._btn_save = flat_button(actions, save_label, self._save_file, accent=True)
        self._btn_save.pack(side=tk.LEFT)
        ToolTip(
            self._btn_save,
            "Записать изменения в файл на диске.",
        )

        self._set_edit_enabled(False)

        center = tk.Frame(bar, bg=BG_BAR)
        center.pack(side=tk.LEFT, fill=tk.Y, expand=True, padx=8)
        self._status_label = tk.Label(
            center,
            text="Загрузка…",
            bg=BG_BAR,
            fg=FG_DIM,
            font=("Segoe UI", 9),
            anchor=tk.W,
        )
        self._status_label.pack(side=tk.LEFT, pady=12)

        try:
            size = self.path.stat().st_size
            kind = ".dds" if self._dds_only else ".ytd"
            file_hint = f"{kind} · {_format_size(size)}"
        except OSError:
            file_hint = ".dds" if self._dds_only else ".ytd"

        tk.Label(
            bar,
            text=APP_CREDIT,
            bg=BG_BAR,
            fg=FG_DIM,
            font=("Segoe UI", 8),
            anchor=tk.E,
            padx=8,
        ).pack(side=tk.RIGHT, fill=tk.Y, pady=14)

        self.file_label = tk.Label(
            bar,
            text=file_hint,
            bg=BG_BAR,
            fg=FG_DIM,
            font=("Segoe UI", 10),
            anchor=tk.E,
            padx=14,
        )
        self.file_label.pack(side=tk.RIGHT, fill=tk.Y)

        self._show_loading()
        self.root.update_idletasks()
        self.canvas.configure(bg=BG_VIEW)
        center_tk_window(self.root, 1000, 700)
        self.root.after_idle(self._setup_file_drop)
        self.root.after_idle(self._install_hotkeys)

        threading.Thread(target=self._load_worker, name="ytd-load", daemon=True).start()

    def _install_hotkeys(self) -> None:
        from ytdpreviewer.hotkeys import attach_window_key_hooks, install_preview_hotkeys

        install_preview_hotkeys(
            self.root,
            save=self._save_file,
            replace_texture=self._replace_texture,
            paste_image_extra=self._paste_image_from_clipboard,
        )
        attach_window_key_hooks(self.root)

    def _setup_file_drop(self) -> None:
        try:
            from ytdpreviewer.file_drop import bind_file_drop, filter_image_paths

            def on_paths(paths: list[Path]) -> None:
                images = filter_image_paths(paths)
                if not images:
                    self._set_status("Перетащите PNG/JPG/DDS…")
                    return
                if self._applying:
                    self._set_status("Дождитесь завершения операции…")
                    return
                if self._selected < 0 or not self._textures:
                    self._set_status("Дождитесь загрузки текстур…")
                    return
                self._replace_texture(images[0])

            bind_file_drop(self.root, on_paths)
        except Exception:
            pass

    def _refresh_file_drop(self) -> None:
        try:
            from ytdpreviewer.file_drop import refresh_file_drop

            refresh_file_drop(self.root)
        except Exception:
            pass

    def _ensure_canvas_bg(self, _event: object | None = None) -> None:
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if self._canvas_bg_id is None:
            self._canvas_bg_id = self.canvas.create_rectangle(
                0, 0, cw, ch, fill=BG_VIEW, outline=BG_VIEW, tags=("bg",)
            )
        else:
            self.canvas.coords(self._canvas_bg_id, 0, 0, cw, ch)
        self.canvas.tag_lower("bg")

    @staticmethod
    def _load_dds_texture(path: Path) -> Texture:
        try:
            return Texture.from_dds(str(path))
        except Exception as primary_exc:
            try:
                with Image.open(path) as img:
                    pil = img.convert("RGBA")
            except Exception:
                raise RuntimeError(
                    f"Не удалось прочитать DDS ({path.name}):\n{primary_exc}"
                ) from primary_exc
            from texfury import BCFormat

            return Texture.from_pil(
                pil,
                format=BCFormat.BC3,
                quality=0.85,
                generate_mipmaps=False,
                resize_to_pot=False,
                name=path.stem,
            )

    def _show_loading(self) -> None:
        self.canvas.delete("all")
        self._canvas_bg_id = None
        self._ensure_canvas_bg()
        cw = max(self.canvas.winfo_width(), 200)
        ch = max(self.canvas.winfo_height(), 200)
        self.canvas.create_text(
            cw // 2,
            ch // 2,
            text="Загрузка…",
            fill=FG_DIM,
            font=("Segoe UI", 12),
            tags=("loading",),
        )

    def _load_worker(self) -> None:
        if self._dds_only:
            try:
                tex = self._load_dds_texture(self.path)
                pil = tex.to_pil(0)
                if pil is None:
                    raise ValueError("Не удалось декодировать DDS (пустой mip 0)")
                with self._cache_lock:
                    self._pil_cache[(0, 0)] = pil.convert("RGBA")
                self.root.after(0, lambda t=tex: self._on_loaded_dds(t))
            except Exception as exc:
                err = str(exc)
                self.root.after(0, lambda e=err: self._on_load_error(RuntimeError(e)))
            return

        try:
            td = ITD.load(str(self.path))
            textures = list(td.textures)
            if not textures:
                self.root.after(0, lambda: self._on_load_empty())
                return
            try:
                pil = textures[0].to_pil(0)
                if pil is not None:
                    with self._cache_lock:
                        self._pil_cache[(0, 0)] = pil.convert("RGBA")
            except Exception:
                pass
            strip_thumbs: list[Image.Image] = []
            for tex in textures:
                try:
                    mip = thumb_mip_level(tex, THUMB_SIZE)
                    decoded = tex.to_pil(mip)
                    if decoded is None:
                        raise ValueError("empty")
                    strip_thumbs.append(_thumb_from_pil(decoded))
                except Exception:
                    strip_thumbs.append(
                        Image.new("RGBA", (THUMB_SIZE, THUMB_SIZE), (60, 60, 60, 255))
                    )
            self.root.after(0, lambda: self._on_loaded(td, textures, strip_thumbs))
        except Exception as exc:
            self.root.after(0, lambda: self._on_load_error(exc))

    def _on_load_empty(self) -> None:
        messagebox.showinfo("Пусто", "В этом YTD нет текстур.", parent=self.root)
        self.root.destroy()

    def _on_load_error(self, exc: Exception) -> None:
        messagebox.showerror("Ошибка", f"Не удалось открыть файл:\n{exc}", parent=self.root)
        self.root.destroy()

    def _on_loaded_dds(self, tex: Texture) -> None:
        self._td = None
        self._textures = [tex]
        self._strip_thumbs = []
        self._dirty = False
        self._update_title()
        try:
            size = self.path.stat().st_size
            self.file_label.config(
                text=f".dds · {_format_size(size)} · {format_label(tex.format)}"
            )
        except OSError:
            self.file_label.config(text=".dds")
        self._set_edit_enabled(True)
        self._set_status("Готово", ok=True)
        self._select(0)
        self.root.after_idle(self._refresh_file_drop)
        self.root.after_idle(self._install_hotkeys)

    def _on_loaded(self, td: ITD, textures: list, strip_thumbs: list[Image.Image]) -> None:
        self._td = td
        self._textures = textures
        self._strip_thumbs = strip_thumbs
        self._dirty = False
        self._update_title()
        self.file_label.config(
            text=f".ytd · {_format_size(self.path.stat().st_size)} · {len(textures)} текстур"
        )
        self._set_edit_enabled(True)
        self._set_status("Готово", ok=True)

        if len(textures) > 1:
            self._build_strip_shell()

        self._select(0)
        self.root.after_idle(self._refresh_file_drop)
        self.root.after_idle(self._install_hotkeys)

    def _set_edit_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self._name_entry.configure(state=state)
        self._width_spin.configure(state=state)
        self._height_spin.configure(state=state)
        self._mip_spin.configure(state=state)
        self._format_combo.configure(state="readonly" if enabled else tk.DISABLED)
        self._btn_apply.configure(state=state)
        self._btn_replace.configure(state=state)
        self._btn_save.configure(state=state)

    def _set_status(self, text: str, *, ok: bool = False) -> None:
        self._status_label.config(text=text, fg=ACCENT if ok else FG_DIM)

    def _update_title(self) -> None:
        mark = " *" if self._dirty else ""
        self.root.title(f"{self.path.name}{mark}")

    def _fill_edit_fields(self, tex) -> None:
        self._name_var.set(tex.name or "")
        self._format_var.set(format_label(tex.format))
        self._mip_var.set(str(tex.mip_count))
        self._width_var.set(str(tex.width))
        self._height_var.set(str(tex.height))
        max_mip = max_mip_count(tex.width, tex.height)
        self._mip_spin.configure(to=max_mip)

    def _invalidate_cache(self, index: int) -> None:
        with self._cache_lock:
            drop = [k for k in self._pil_cache if k[0] == index]
            for k in drop:
                del self._pil_cache[k]

    def _read_edit_params(self) -> tuple[str, object, int, int, int] | None:
        name = self._name_var.get().strip()
        if not name:
            messagebox.showwarning("Имя", "Введите имя текстуры.", parent=self.root)
            return None

        try:
            width = int(self._width_var.get())
            height = int(self._height_var.get())
        except ValueError:
            messagebox.showwarning("Размер", "Укажите целые ширину и высоту.", parent=self.root)
            return None
        if width < 1 or height < 1:
            messagebox.showwarning("Размер", "Ширина и высота должны быть ≥ 1.", parent=self.root)
            return None

        try:
            mip_count = int(self._mip_var.get())
        except ValueError:
            messagebox.showwarning("Mip", "Укажите целое число mip-уровней.", parent=self.root)
            return None
        max_mip = max_mip_count(width, height)
        if mip_count < 1 or mip_count > max_mip:
            messagebox.showwarning(
                "Mip",
                f"Для {width}×{height} допустимо от 1 до {max_mip} mip.",
                parent=self.root,
            )
            return None

        try:
            fmt = parse_format(self._format_var.get())
        except (KeyError, ValueError) as exc:
            messagebox.showerror("Формат", f"Неизвестный формат: {exc}", parent=self.root)
            return None

        self._mip_spin.configure(to=max_mip)
        return name, fmt, mip_count, width, height

    def _begin_texture_job(self, status: str) -> None:
        self._applying = True
        self._btn_apply.configure(state=tk.DISABLED, text="…")
        self._btn_replace.configure(state=tk.DISABLED)
        self._set_status(status)

    def _end_texture_job_buttons(self) -> None:
        self._applying = False
        self._btn_apply.configure(state=tk.NORMAL, text="Обновить")
        self._btn_replace.configure(state=tk.NORMAL)

    def _apply_edits(self) -> None:
        if self._td is None or self._selected < 0 or self._applying:
            return

        params = self._read_edit_params()
        if params is None:
            return
        name, fmt, mip_count, width, height = params

        idx = self._selected
        tex = self._textures[idx]
        old_name = tex.name

        self._begin_texture_job("Перекодирование…")

        def work() -> None:
            try:
                new_tex = recompress_texture(
                    tex,
                    name=name,
                    fmt=fmt,
                    mip_count=mip_count,
                    width=width,
                    height=height,
                )
                err = None
            except Exception as exc:
                new_tex = None
                err = str(exc)
            self.root.after(0, lambda: self._on_applied(idx, old_name, new_tex, err))

        threading.Thread(target=work, name="ytd-apply", daemon=True).start()

    def _paste_image_from_clipboard(self) -> None:
        if self._selected < 0 or self._applying or not self._textures:
            return

        clip_img: Image.Image | None = None
        clip_path: Path | None = None
        try:
            from PIL import ImageGrab

            clip = ImageGrab.grabclipboard()
            if isinstance(clip, Image.Image):
                clip_img = clip
            elif isinstance(clip, list) and clip:
                candidate = Path(str(clip[0]))
                if candidate.is_file():
                    clip_path = candidate
        except Exception:
            pass

        if clip_img is not None:
            self._replace_texture(clip_img)
        elif clip_path is not None:
            self._replace_texture(clip_path)

    def _replace_texture(self, image_path: str | Path | Image.Image | None = None) -> None:
        if self._selected < 0 or self._applying or not self._textures:
            return

        params = self._read_edit_params()
        if params is None:
            return
        name, fmt, mip_count, width, height = params

        source: str | Path | Image.Image
        job_label: str

        if isinstance(image_path, Image.Image):
            source = image_path
            job_label = "буфера обмена"
        elif image_path is None:
            picked = filedialog.askopenfilename(
                parent=self.root,
                title="Заменить текстуру",
                initialdir=str(self.path.parent),
                filetypes=[
                    ("Изображения", "*.png;*.jpg;*.jpeg;*.bmp;*.tga;*.dds"),
                    ("PNG", "*.png"),
                    ("JPEG", "*.jpg;*.jpeg"),
                    ("DDS", "*.dds"),
                    ("Все файлы", "*.*"),
                ],
            )
            if not picked:
                return
            source = Path(picked).resolve()
            if not source.is_file():
                messagebox.showwarning("Замена", f"Файл не найден:\n{source}", parent=self.root)
                return
            job_label = source.name
        else:
            source = Path(image_path).resolve()
            if not source.is_file():
                messagebox.showwarning("Замена", f"Файл не найден:\n{source}", parent=self.root)
                return
            job_label = source.name

        idx = self._selected
        tex = self._textures[idx]
        old_name = tex.name

        self._begin_texture_job(f"Замена из {job_label}…")

        def work() -> None:
            try:
                new_tex = replace_texture_from_image(
                    tex,
                    source,
                    name=name,
                    fmt=fmt,
                    mip_count=mip_count,
                    width=width,
                    height=height,
                )
                err = None
            except Exception as exc:
                new_tex = None
                err = str(exc)
            self.root.after(0, lambda: self._on_applied(idx, old_name, new_tex, err))

        threading.Thread(target=work, name="ytd-replace", daemon=True).start()

    def _on_applied(self, index: int, old_name: str, new_tex, err: str | None) -> None:
        self._end_texture_job_buttons()

        if err or new_tex is None:
            self._set_status("Ошибка")
            messagebox.showerror("Обновить", err or "Неизвестная ошибка", parent=self.root)
            return

        if self._td is not None:
            for i, t in enumerate(self._td._textures):
                if t.name.lower() == old_name.lower():
                    self._td._textures[i] = new_tex
                    break
        self._textures[index] = new_tex

        self._invalidate_cache(index)
        self._dirty = True
        self._update_title()
        self._fill_edit_fields(new_tex)
        save_hint = "Сохранить DDS" if self._dds_only else "Сохранить YTD"
        self._set_status(f"Изменения в памяти — нажмите «{save_hint}»")

        if index < len(self._thumb_labels):
            threading.Thread(
                target=self._load_thumb_worker,
                args=(index,),
                name=f"ytd-thumb-{index}",
                daemon=True,
            ).start()

        self._select(index)

    def _save_file(self) -> bool:
        try:
            if self._dds_only:
                if not self._textures:
                    return False
                self._textures[0].save_dds(str(self.path))
            else:
                if self._td is None:
                    return False
                self._td.save(str(self.path))
        except Exception as exc:
            messagebox.showerror("Сохранение", str(exc), parent=self.root)
            return False

        self._dirty = False
        self._update_title()
        try:
            size = self.path.stat().st_size
            if self._dds_only and self._textures:
                tex = self._textures[0]
                self.file_label.config(
                    text=f".dds · {_format_size(size)} · {format_label(tex.format)}"
                )
            else:
                self.file_label.config(
                    text=f".ytd · {_format_size(size)} · {len(self._textures)} текстур"
                )
        except OSError:
            pass
        self._set_status("Сохранено на диск", ok=True)
        return True

    def _on_close(self) -> None:
        try:
            from ytdpreviewer.hotkeys import release_window_hotkeys

            release_window_hotkeys(self.root)
        except Exception:
            pass
        if self._dirty:
            kind = "DDS" if self._dds_only else "YTD"
            ans = messagebox.askyesnocancel(
                "Сохранить?",
                f"Есть несохранённые изменения в {kind}.",
                parent=self.root,
            )
            if ans is None:
                return
            if ans and not self._save_file():
                return
        self.root.destroy()

    def _decode(self, index: int, mip: int) -> Image.Image:
        key = (index, mip)
        with self._cache_lock:
            cached = self._pil_cache.get(key)
            if cached is not None:
                return cached

        pil = self._textures[index].to_pil(mip)
        if pil is None:
            raise ValueError("Пустая текстура")
        img = pil.convert("RGBA")

        with self._cache_lock:
            self._pil_cache[key] = img
        return img

    def _build_strip_shell(self) -> None:
        self._strip = tk.Frame(self._content, bg=BG_STRIP, width=THUMB_SIZE + THUMB_PAD * 2)
        self._strip.pack(side=tk.LEFT, fill=tk.Y, before=self._view_host)
        self._strip.pack_propagate(False)

        inner = tk.Frame(self._strip, bg=BG_STRIP)
        inner.pack(fill=tk.BOTH, expand=True, padx=THUMB_PAD, pady=THUMB_PAD)

        strip_thumbs = getattr(self, "_strip_thumbs", [])

        for i in range(len(self._textures)):
            cell = tk.Frame(inner, bg=BG_STRIP, cursor="hand2")
            cell.pack(pady=4)
            cell.bind("<Button-1>", lambda _e, idx=i: self._select(idx))

            border = tk.Frame(cell, bg=BG_STRIP, padx=2, pady=2)
            border.pack()
            border.bind("<Button-1>", lambda _e, idx=i: self._select(idx))

            thumb_img = strip_thumbs[i] if i < len(strip_thumbs) else None
            if thumb_img is None:
                thumb_img = Image.new("RGBA", (THUMB_SIZE, THUMB_SIZE), (56, 56, 56, 255))
            photo = ImageTk.PhotoImage(thumb_img)
            self._thumb_photos.append(photo)

            lbl = tk.Label(border, image=photo, bg=PLACEHOLDER, bd=0)
            lbl.pack()
            lbl.bind("<Button-1>", lambda _e, idx=i: self._select(idx))

            self._thumb_btns.append(border)
            self._thumb_labels.append(lbl)

    def _load_thumb_worker(self, index: int) -> None:
        try:
            tex = self._textures[index]
            mip = thumb_mip_level(tex, THUMB_SIZE)
            thumb = _thumb_from_pil(self._decode(index, mip))
            self.root.after(0, lambda t=thumb, i=index: self._apply_thumb(i, t))
        except Exception:
            gray = Image.new("RGBA", (THUMB_SIZE, THUMB_SIZE), (60, 60, 60, 255))
            self.root.after(0, lambda t=gray, i=index: self._apply_thumb(i, t))

    def _apply_thumb(self, index: int, thumb: Image.Image) -> None:
        if index >= len(self._thumb_labels):
            return
        photo = ImageTk.PhotoImage(thumb)
        if index < len(self._thumb_photos):
            self._thumb_photos[index] = photo
        self._thumb_labels[index].configure(image=photo)

    def _select(self, index: int) -> None:
        if index < 0 or index >= len(self._textures):
            return

        self._selected = index
        self._decode_generation += 1
        generation = self._decode_generation
        self._reset_view(redraw=False)
        tex = self._textures[index]
        self._fill_edit_fields(tex)

        for i, border in enumerate(self._thumb_btns):
            border.configure(bg=ACCENT if i == index else BG_STRIP)

        cached = self._pil_cache.get((index, 0))
        if cached is not None:
            self._current_pil = cached
            self._draw_main()
            return

        self._show_loading()

        def work() -> None:
            try:
                pil = self._decode(index, 0)
                err: str | None = None
            except Exception as exc:
                pil = None
                err = str(exc)
            self.root.after(0, lambda: self._apply_main(generation, pil, err))

        threading.Thread(target=work, name="ytd-decode", daemon=True).start()

    def _apply_main(
        self, generation: int, pil: Image.Image | None, err: str | None
    ) -> None:
        if generation != self._decode_generation:
            return
        if err:
            self._current_pil = None
            self.canvas.delete("all")
            self._canvas_bg_id = None
            self._ensure_canvas_bg()
            self.canvas.create_text(
                24,
                24,
                anchor=tk.NW,
                fill="#f08080",
                text=f"Не удалось декодировать:\n{err}",
                font=("Segoe UI", 11),
            )
            return
        if pil is None:
            self.canvas.delete("all")
            self.canvas.create_text(
                24,
                24,
                anchor=tk.NW,
                fill="#f08080",
                text="Не удалось декодировать текстуру",
                font=("Segoe UI", 11),
            )
            return
        self._current_pil = pil
        self._reset_view(redraw=False)
        self._draw_main()

    def _reset_view(self, *, redraw: bool) -> None:
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._drag = None
        if self._image_id is not None:
            self.canvas.delete(self._image_id)
        self._image_id = None
        self._rendered_zoom = 0.0
        self.canvas.configure(cursor="")
        if redraw and self._current_pil is not None:
            self._draw_main()

    def _canvas_size(self) -> tuple[int, int]:
        return max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)

    def _view_metrics(self) -> tuple[float, int, int, int, int] | None:
        """fit_scale, display_w, display_h, img_x, img_y"""
        if self._current_pil is None:
            return None
        cw, ch = self._canvas_size()
        img = self._current_pil
        fit = min(cw / img.width, ch / img.height)
        scale = fit * self._zoom
        dw = max(1, int(img.width * scale))
        dh = max(1, int(img.height * scale))
        ix = int((cw - dw) // 2 + self._pan_x)
        iy = int((ch - dh) // 2 + self._pan_y)
        return fit, dw, dh, ix, iy

    def _on_wheel(self, event, delta: int | None = None) -> None:
        if self._current_pil is None:
            return
        d = delta if delta is not None else event.delta
        if d == 0:
            return

        metrics = self._view_metrics()
        if metrics is None:
            return
        fit, dw, dh, ix, iy = metrics
        cw, ch = self._canvas_size()

        mx, my = event.x, event.y
        rel_x = (mx - ix) / dw if dw else 0.5
        rel_y = (my - iy) / dh if dh else 0.5

        factor = self._ZOOM_STEP if d > 0 else 1.0 / self._ZOOM_STEP
        new_zoom = max(self._ZOOM_MIN, min(self._ZOOM_MAX, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-6:
            return

        img = self._current_pil
        new_scale = fit * new_zoom
        ndw = max(1, int(img.width * new_scale))
        ndh = max(1, int(img.height * new_scale))
        self._pan_x = mx - rel_x * ndw - (cw - ndw) / 2
        self._pan_y = my - rel_y * ndh - (ch - ndh) / 2
        self._zoom = new_zoom
        if self._zoom_after is None:
            self._zoom_after = self.root.after(8, lambda: self._draw_main(fast=True))
        self._schedule_quality_render()

    def _on_pan_start(self, event) -> None:
        if self._current_pil is None:
            return
        image_x, image_y = (0.0, 0.0)
        if self._image_id is not None:
            coords = self.canvas.coords(self._image_id)
            if len(coords) >= 2:
                image_x, image_y = coords[0], coords[1]
        self._drag = (event.x, event.y, self._pan_x, self._pan_y, image_x, image_y)
        self.canvas.configure(cursor="fleur")

    def _on_pan_move(self, event) -> None:
        if self._drag is None or self._current_pil is None:
            return
        dx = event.x - self._drag[0]
        dy = event.y - self._drag[1]
        self._pan_x = self._drag[2] + dx
        self._pan_y = self._drag[3] + dy
        if self._zoom_after is None:
            self._zoom_after = self.root.after(
                8,
                lambda: self._draw_main(pan_only=True, fast=True),
            )

    def _on_pan_end(self, _event) -> None:
        self._drag = None
        self.canvas.configure(cursor="")
        if self._zoom_after is not None:
            self.root.after_cancel(self._zoom_after)
            self._zoom_after = None
        if self._quality_after is not None:
            self.root.after_cancel(self._quality_after)
            self._quality_after = None
        self._draw_main()

    def _on_canvas_resize(self, _event: object) -> None:
        self._ensure_canvas_bg()
        if self._current_pil is None:
            return
        if self._resize_after is not None:
            self.root.after_cancel(self._resize_after)
        self._resize_after = self.root.after(50, self._draw_main)

    def _schedule_quality_render(self) -> None:
        if self._quality_after is not None:
            self.root.after_cancel(self._quality_after)
        self._quality_after = self.root.after(140, self._draw_quality)

    def _draw_quality(self) -> None:
        self._quality_after = None
        self._draw_main()

    def _draw_main(self, *, pan_only: bool = False, fast: bool = False) -> None:
        self._resize_after = None
        self._zoom_after = None
        if self._current_pil is None:
            return
        self.canvas.delete("loading")

        metrics = self._view_metrics()
        if metrics is None:
            return
        _fit, dw, dh, ix, iy = metrics
        cw, ch = self._canvas_size()
        fully_visible = ix >= 0 and iy >= 0 and ix + dw <= cw and iy + dh <= ch

        same_scale = (
            pan_only
            and fully_visible
            and self._image_id is not None
            and abs(self._zoom - self._rendered_zoom) < 1e-6
            and self._rendered_size == (dw, dh)
        )
        if same_scale:
            self.canvas.coords(self._image_id, ix, iy)
            return

        img = self._current_pil
        visible_left = max(0, ix)
        visible_top = max(0, iy)
        visible_right = min(cw, ix + dw)
        visible_bottom = min(ch, iy + dh)
        if visible_right <= visible_left or visible_bottom <= visible_top:
            if self._image_id is not None:
                self.canvas.itemconfigure(self._image_id, state=tk.HIDDEN)
            return

        shown_w = visible_right - visible_left
        shown_h = visible_bottom - visible_top
        if fully_visible:
            resampling = Image.Resampling.NEAREST if fast else Image.Resampling.BILINEAR
            shown = (
                img.resize((dw, dh), resampling)
                if dw != img.width or dh != img.height
                else img
            )
        else:
            source_box = (
                (visible_left - ix) * img.width / dw,
                (visible_top - iy) * img.height / dh,
                (visible_right - ix) * img.width / dw,
                (visible_bottom - iy) * img.height / dh,
            )
            shown = img.transform(
                (shown_w, shown_h),
                Image.Transform.EXTENT,
                source_box,
                Image.Resampling.NEAREST if fast else Image.Resampling.BILINEAR,
            )

        self._main_photo = ImageTk.PhotoImage(shown)
        self._ensure_canvas_bg()
        if self._image_id is None:
            self._image_id = self.canvas.create_image(
                visible_left,
                visible_top,
                anchor=tk.NW,
                image=self._main_photo,
            )
        else:
            self.canvas.itemconfigure(self._image_id, image=self._main_photo, state=tk.NORMAL)
            self.canvas.coords(self._image_id, visible_left, visible_top)
        self._rendered_zoom = self._zoom
        self._rendered_size = (dw, dh)


def open_preview(ytd_path: str | Path, master: tk.Misc | None = None) -> None:
    path = Path(ytd_path)
    if not path.is_file():
        messagebox.showerror("Ошибка", f"Файл не найден:\n{path}")
        return

    if master is not None:
        top = tk.Toplevel(master)
        top.transient(master)
        PreviewWindow(top, path)
        return

    root = tk.Tk()
    PreviewWindow(root, path)
    root.mainloop()


def open_preview_toplevel(master: tk.Misc, ytd_path: str | Path) -> None:
    open_preview(ytd_path, master=master)
