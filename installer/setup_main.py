"""Graphical installer → setup.exe (PyInstaller)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import tkinter as tk
from tkinter import messagebox, ttk

from installer.setup_ui import (
    ACCENT,
    BG_FOOTER,
    BG_WARN,
    FG,
    FG_DIM,
    FG_WARN,
    FONT_SUB,
    FONT_UI,
    GRAD_BOTTOM,
    GRAD_TOP,
    GradientFrame,
    apply_setup_theme,
    caption,
    card,
    dark_check,
    dark_entry,
    feature_row,
    WIN_BORDER_TOTAL,
    WIN_TITLE_H,
    footer_bar,
    header,
    install_custom_window,
    pill_button,
    section_label,
    warn_card,
)
from ytdpreviewer.app_icon import apply_tk_icon, load_brand_image
from ytdpreviewer.ui_theme import APP_AUTHOR, APP_CREDIT
from ytdpreviewer.paths import default_install_dir
import winreg

from ytdpreviewer.setup_windows import (
    YTD_THUMB_CLSID,
    _com_clsid_registered_hklm,
    _is_admin,
    _shellex_registered,
    install_with_progress,
    launch_background_app,
    register_explorer_thumbnails_admin,
    uninstall_with_progress,
)
from ytdpreviewer.ui_theme import center_tk_window

BUNDLE_DIRNAME = "app_bundle"
WIN_W = 600


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        bundled = meipass / BUNDLE_DIRNAME
        if bundled.is_dir():
            return bundled
        return meipass
    return Path(__file__).resolve().parent.parent / "dist" / "release"


def _extract_bundle() -> Path:
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        zip_path = meipass / "app_bundle.zip"
        if zip_path.is_file():
            staging = Path(tempfile.mkdtemp(prefix="ytd_setup_"))
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(staging)
            return staging
    return _bundle_root()


def _load_header_icon() -> tk.PhotoImage | None:
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(load_brand_image(56))
    except Exception:
        return None


def _load_title_icon() -> tk.PhotoImage | None:
    try:
        from PIL import ImageTk

        return ImageTk.PhotoImage(load_brand_image(20))
    except Exception:
        return None


def _format_install_error(exc: Exception) -> str:
    winerror = getattr(exc, "winerror", None)
    text = str(exc)
    if winerror == 32 or "[WinError 32]" in text:
        return (
            "Файл занят другим процессом.\n\n"
            "• В установщике нажмите «Удалить», затем снова «Установить».\n"
            "• Закройте YTD Previewer (трей → выход).\n"
            "• Запускайте только dist\\setup\\setup.exe после build.bat.\n"
            "• Если не помогает — перезагрузите ПК и установите снова.\n\n"
            f"Технически: {text}"
        )
    if winerror == 5 or "[WinError 5]" in text:
        return (
            "Нет доступа к файлу (нужны права или файл заблокирован).\n\n"
            "Закройте YTD Previewer и проводник в папке установки, "
            "затем повторите.\n\n"
            f"Технически: {text}"
        )
    return text


class SetupApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("YTD Previewer")
        self.root.resizable(False, False)
        apply_tk_icon(self.root)
        apply_setup_theme(self.root)
        self._busy = False
        self._bundle_dir: Path | None = None
        self._icon_ref: tk.PhotoImage | None = _load_header_icon()
        self._title_icon_ref: tk.PhotoImage | None = _load_title_icon()
        self.content = install_custom_window(
            self.root,
            on_close=self._request_close,
            title_icon=self._title_icon_ref,
        )

        footer_outer, footer = footer_bar(self.content)
        footer_outer.pack(side=tk.BOTTOM, fill=tk.X)

        self.progress = ttk.Progressbar(
            footer,
            maximum=100,
            mode="determinate",
            style="Accent.Horizontal.TProgressbar",
        )
        self.progress.pack(fill=tk.X)
        self.status = caption(footer, "Готово к установке", fg=FG, bg=BG_FOOTER)

        btn_row = tk.Frame(footer, bg=BG_FOOTER)
        btn_row.pack(fill=tk.X, pady=(14, 0))
        left_btns = tk.Frame(btn_row, bg=BG_FOOTER)
        left_btns.pack(side=tk.LEFT)
        right_btns = tk.Frame(btn_row, bg=BG_FOOTER)
        right_btns.pack(side=tk.RIGHT)

        self.uninstall_btn = pill_button(left_btns, "Удалить", self._do_uninstall, min_width=100)
        self.uninstall_btn.pack(side=tk.LEFT, padx=(0, 8))
        pill_button(left_btns, "Закрыть", self._request_close, min_width=100).pack(side=tk.LEFT)
        self.install_btn = pill_button(
            right_btns,
            "Установить",
            self._do_install,
            accent=True,
            min_width=148,
        )
        self.install_btn.pack(side=tk.RIGHT)

        credit_row = tk.Frame(footer, bg=BG_FOOTER)
        credit_row.pack(fill=tk.X, pady=(10, 0))
        tk.Label(
            credit_row,
            text=APP_CREDIT,
            bg=BG_FOOTER,
            fg="#5c5c5c",
            font=(FONT_UI[0], 8),
        ).pack(side=tk.RIGHT)
        tk.Label(
            credit_row,
            text=f"© {APP_AUTHOR}",
            bg=BG_FOOTER,
            fg="#454545",
            font=(FONT_UI[0], 8),
        ).pack(side=tk.LEFT)

        header(self.content, self._icon_ref, drag_root=self.root)

        body = GradientFrame(self.content, GRAD_TOP, GRAD_BOTTOM)
        body.pack(fill=tk.BOTH, expand=True)
        body.after_idle(body._repaint)

        feat = card(body, pady=(12, 6))
        section_label(feat, "Возможности")
        feature_row(feat, "Двойной клик по .ytd — превью текстур")
        feature_row(feat, "Превью .ytd в проводнике (один установщик)")
        feature_row(feat, "Автозапуск в системном трее")

        path_card = card(body, pady=6)
        section_label(path_card, "Папка установки")
        self.dir_var = tk.StringVar(value=str(default_install_dir()))
        self.dir_entry = dark_entry(path_card, self.dir_var)

        opts = card(body, pady=6)
        self.explorer_var = tk.BooleanVar(value=True)
        self.explorer_check = dark_check(
            opts,
            "Превью .ytd в проводнике — всё в одной установке (рекомендуется)",
            self.explorer_var,
        )
        self.explorer_check.pack(anchor=tk.W)

        warn = warn_card(body)
        tk.Label(
            warn,
            text="Проводник будет перезапущен",
            bg=BG_WARN,
            fg=FG_WARN,
            font=(FONT_SUB[0], FONT_SUB[1], "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            warn,
            text="Все открытые окна папок закроются. Сохраните работу перед установкой.",
            bg=BG_WARN,
            fg=FG_WARN,
            font=FONT_UI,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor=tk.W, pady=(6, 0))

        self.content.update_idletasks()
        win_h = max(self.content.winfo_reqheight(), 520)
        total_h = win_h + WIN_TITLE_H + WIN_BORDER_TOTAL + 2
        total_w = WIN_W + WIN_BORDER_TOTAL
        center_tk_window(self.root, total_w, total_h)

    def _request_close(self) -> None:
        if self._busy:
            if not messagebox.askyesno(
                "Установка",
                "Операция ещё выполняется. Прервать и закрыть?",
            ):
                return
        self.root.destroy()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.install_btn.set_enabled(not busy)
        self.uninstall_btn.set_enabled(not busy)
        entry_state = tk.DISABLED if busy else tk.NORMAL
        self.dir_entry.config(state=entry_state)
        self.explorer_check.config(state=entry_state)
        self.root.configure(cursor="watch" if busy else "")

    def _update_progress(self, percent: int, message: str) -> None:
        self.progress["value"] = max(0, min(100, percent))
        self.status.config(text=message, fg=ACCENT if percent >= 100 else FG_DIM)

    def _do_install(self) -> None:
        if self._busy:
            return
        target = Path(self.dir_var.get().strip())
        if not target:
            messagebox.showerror("Ошибка", "Укажите папку установки.")
            return
        if not messagebox.askokcancel(
            "Проводник будет перезапущен",
            "Во время установки Windows закроет проводник и откроет его снова.\n\n"
            "Все открытые окна папок будут закрыты.\n"
            "Сохраните несохранённые файлы.\n\n"
            "Продолжить установку?",
            icon=messagebox.WARNING,
        ):
            return
        self._set_busy(True)
        self.progress["value"] = 0
        self.status.config(fg=FG_DIM)
        threading.Thread(target=self._install_worker, args=(target,), daemon=True).start()

    def _install_worker(self, target: Path) -> None:
        try:
            if getattr(sys, "frozen", False):
                setup_exe = Path(sys.executable).resolve()
                try:
                    if setup_exe.parent == target.resolve() or target.resolve() in setup_exe.parents:
                        raise RuntimeError(
                            "Запускайте установку из dist\\setup\\setup.exe, "
                            "а не из папки установки."
                        )
                except OSError:
                    pass

            if self._bundle_dir is None:
                self._bundle_dir = _extract_bundle()

            def on_progress(percent: int, message: str) -> None:
                self.root.after(0, lambda p=percent, m=message: self._update_progress(p, m))

            want_thumbs = self.explorer_var.get()
            if want_thumbs and not _is_admin():
                raise RuntimeError(
                    "Для превью в проводнике нужны права администратора.\n\n"
                    "Запустите setup.exe снова и подтвердите запрос UAC (Да)."
                )

            install_with_progress(
                target,
                source_dir=self._bundle_dir,
                dev=False,
                shell_admin=want_thumbs and _is_admin(),
                explorer_thumbnails=want_thumbs,
                on_progress=on_progress,
            )

            explorer_ok = True
            if want_thumbs:
                explorer_ok = _com_clsid_registered_hklm(YTD_THUMB_CLSID) and _shellex_registered(
                    winreg.HKEY_LOCAL_MACHINE, ".ytd", clsid=YTD_THUMB_CLSID
                )

            self.root.after(0, lambda: self._on_install_done(target, explorer_ok))
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_install_error(e))

    def _on_install_done(self, target: Path, explorer_ok: bool) -> None:
        self._set_busy(False)
        self._update_progress(100, "Установка завершена")
        launch_background_app(target)

        extra = ""
        if self.explorer_var.get():
            if explorer_ok:
                extra = "\n\nПревью .ytd в проводнике включены."
            else:
                extra = (
                    "\n\nПревью в проводнике не зарегистрированы.\n"
                    "Запустите setup.exe от имени администратора и установите снова."
                )

        messagebox.showinfo(
            "Установлено",
            f"Программа установлена в:\n{target}\n\n"
            "• Дважды кликните .ytd — превью текстур\n"
            "• Дважды кликните .ydd — 3D превью\n"
            "• Автозапуск в трее включён"
            f"{extra}",
        )

    def _on_install_error(self, exc: Exception) -> None:
        self._set_busy(False)
        self._update_progress(0, "Ошибка установки")
        self.status.config(fg="#e57373")
        messagebox.showerror("Ошибка установки", _format_install_error(exc))


    def _do_uninstall(self) -> None:
        if self._busy:
            return
        if not messagebox.askyesno(
            "Удаление",
            "Убрать автозапуск, ассоциации и превью в проводнике?\n\n"
            "Проводник будет перезапущен — все окна папок закроются.",
            icon=messagebox.WARNING,
        ):
            return
        self._set_busy(True)
        self.progress["value"] = 0
        threading.Thread(target=self._uninstall_worker, daemon=True).start()

    def _uninstall_worker(self) -> None:
        try:
            target = Path(self.dir_var.get().strip() or default_install_dir())

            def on_progress(percent: int, message: str) -> None:
                self.root.after(0, lambda p=percent, m=message: self._update_progress(p, m))

            uninstall_with_progress(target, on_progress=on_progress)
            self.root.after(0, self._on_uninstall_done)
        except Exception as exc:
            self.root.after(0, lambda e=exc: self._on_install_error(e))

    def _on_uninstall_done(self) -> None:
        self._set_busy(False)
        self._update_progress(100, "Удалено")
        messagebox.showinfo(
            "Готово",
            "Ассоциации и превью удалены.\n"
            "Папку %LOCALAPPDATA%\\YTDPreviewer можно удалить вручную.",
        )

    def run(self) -> None:
        self.root.mainloop()


def _auto_repair_associations() -> None:
    """Fix registry if .ytd/.ydd still point at setup.exe."""
    target = default_install_dir()
    if not (target / "YTDPreviewer.exe").is_file():
        return
    try:
        from ytdpreviewer.setup_windows import (
            _fix_autostart_entry,
            _purge_setup_exe_handlers,
            repair_installation,
        )

        _purge_setup_exe_handlers()
        _fix_autostart_entry(target)
        repair_installation(target, re_register=True, register_thumbnails=False)
    except (FileNotFoundError, OSError, RuntimeError):
        pass


def _find_preview_exe() -> Path | None:
    setup_parent = Path(sys.executable).resolve().parent
    candidates = [
        default_install_dir() / "YTDPreviewer.exe",
        setup_parent / "YTDPreviewer.exe",
        setup_parent / "release" / "YTDPreviewer.exe",
        setup_parent.parent / "YTDPreviewer" / "YTDPreviewer.exe",
        setup_parent.parent / "release" / "YTDPreviewer.exe",
    ]
    for exe in candidates:
        if exe.is_file() and exe.name.lower() != "setup.exe":
            return exe
    return None


def _forward_game_file_if_misassociated() -> bool:
    """If .ytd/.ydd open setup.exe by mistake, launch YTDPreviewer.exe instead."""
    if len(sys.argv) < 2:
        return False
    path_arg = sys.argv[1].strip().strip('"')
    if path_arg.lower() in ("/shell-install", "/uninstall", "uninstall"):
        return False
    if Path(path_arg).suffix.lower() not in (".ytd", ".ydd", ".dds"):
        return False
    exe = _find_preview_exe()
    if exe is not None:
        subprocess.Popen(
            [str(exe), path_arg],
            cwd=str(exe.parent),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return True
    messagebox.showerror(
        "YTD Previewer",
        "Файл .ytd/.ydd привязан к установщику, а программа не установлена.\n\n"
        "Запустите dist\\setup\\setup.exe → Установить.",
    )
    return True


def main() -> None:
    _auto_repair_associations()
    if _forward_game_file_if_misassociated():
        return

    if len(sys.argv) > 1 and sys.argv[1].lower() == "/shell-install":
        if len(sys.argv) < 3:
            raise SystemExit(2)
        target = Path(sys.argv[2].strip('"'))
        ok = register_explorer_thumbnails_admin(target)
        raise SystemExit(0 if ok else 1)

    if len(sys.argv) > 1 and sys.argv[1] == "/uninstall":
        uninstall_with_progress()
        return

    SetupApp().run()


if __name__ == "__main__":
    main()
