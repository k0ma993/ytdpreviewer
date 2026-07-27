"""Online update check, download, and in-place upgrade."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

from ytdpreviewer.paths import APP_NAME, default_install_dir, is_frozen, viewer_exe
from ytdpreviewer.version_info import installed_version
from ytdpreviewer.release_config import BUNDLE_ASSET_NAME, GITHUB_REPO
from ytdpreviewer.ui_theme import (
    BG_VIEW,
    FG,
    FG_DIM,
    center_tk_window,
    flat_button,
    setup_dark_ttk,
)

# Optional JSON manifest URL (update_url.txt overrides everything).
DEFAULT_MANIFEST_URL = ""

SKIP_FILE = "update_skip.json"
DOWNLOAD_DIRNAME = "update_cache"
STAGING_DIRNAME = "staging"
STAGING_MARKER = "staging_path.txt"
UPDATE_UI_LOCK = "update_ui.lock"
SKIP_HOURS = 24
CHECK_DELAY_MS = 2000
UPDATE_UI_LOCK_MAX_AGE = 300

_ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
_ui_root: tk.Tk | None = None
_update_dialog_open = False


def _update_ui_lock_path(install_dir: Path) -> Path:
    return install_dir / DOWNLOAD_DIRNAME / UPDATE_UI_LOCK


def _pid_alive(pid: int) -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
        return str(pid) in (proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def _try_acquire_update_ui_lock(install_dir: Path) -> bool:
    lock = _update_ui_lock_path(install_dir)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            pid_s, stamp_s, *_ = lock.read_text(encoding="utf-8").split()
            pid = int(pid_s)
            age = time.time() - float(stamp_s)
            if age < UPDATE_UI_LOCK_MAX_AGE and _pid_alive(pid):
                return False
        except (OSError, ValueError):
            pass
    lock.write_text(f"{os.getpid()} {time.time():.3f}", encoding="ascii")
    return True


def _release_update_ui_lock(install_dir: Path) -> None:
    lock = _update_ui_lock_path(install_dir)
    try:
        if lock.is_file():
            pid_s, *_ = lock.read_text(encoding="utf-8").split()
            if int(pid_s) == os.getpid():
                lock.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _clear_stale_update_ui_lock(install_dir: Path) -> None:
    lock = _update_ui_lock_path(install_dir)
    if not lock.is_file():
        return
    try:
        pid_s, stamp_s, *_ = lock.read_text(encoding="utf-8").split()
        pid = int(pid_s)
        age = time.time() - float(stamp_s)
        if not _pid_alive(pid) or age >= UPDATE_UI_LOCK_MAX_AGE:
            lock.unlink(missing_ok=True)
    except (OSError, ValueError):
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def _flush_ui_queue() -> None:
    try:
        while True:
            fn = _ui_queue.get_nowait()
            fn()
    except queue.Empty:
        pass


def install_ui_pump(root: tk.Tk) -> None:
    """Run UI callbacks from worker threads on the Tk main thread."""
    global _ui_root
    _ui_root = root
    if getattr(install_ui_pump, "_active", False):
        return

    def pump() -> None:
        _flush_ui_queue()
        root.after(50, pump)

    install_ui_pump._active = True  # type: ignore[attr-defined]
    pump()


def _enqueue_ui(fn: Callable[[], None]) -> None:
    """Queue work for the Tk-owned pump without calling Tk from this thread."""
    _ui_queue.put(fn)


def _tray_messagebox(
    root: tk.Tk,
    title: str,
    message: str,
    *,
    kind: str = "info",
) -> None:
    """Message box that stays visible when the tray Tk root is withdrawn."""
    host = tk.Toplevel(root)
    host.withdraw()
    host.attributes("-topmost", True)
    try:
        if kind == "error":
            messagebox.showerror(title, message, parent=host)
        elif kind == "warning":
            messagebox.showwarning(title, message, parent=host)
        else:
            messagebox.showinfo(title, message, parent=host)
    finally:
        try:
            host.destroy()
        except tk.TclError:
            pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    bundle_url: str
    notes: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result of a manual update probe (for tray menu messages)."""

    info: UpdateInfo | None = None
    is_current: bool = False
    error: str = ""


def parse_version(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in value.strip().lstrip("v").split("."):
        head = piece.split("-")[0].split("+")[0]
        try:
            parts.append(int(head))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def is_newer(remote: str, local: str) -> bool:
    return parse_version(remote) > parse_version(local)


def github_repo(install_dir: Path | None = None) -> str | None:
    inst = (install_dir or default_install_dir()).resolve()
    custom = inst / "github_repo.txt"
    if custom.is_file():
        line = custom.read_text(encoding="utf-8").strip()
        if line:
            return line
    env = os.environ.get("YTD_GITHUB_REPO", "").strip()
    if env:
        return env
    if GITHUB_REPO:
        return GITHUB_REPO.strip()
    return None


def manifest_url(install_dir: Path | None = None) -> str | None:
    inst = (install_dir or default_install_dir()).resolve()
    custom = inst / "update_url.txt"
    if custom.is_file():
        line = custom.read_text(encoding="utf-8").strip()
        if line:
            return line
    env = os.environ.get("YTD_UPDATE_URL", "").strip()
    if env:
        return env
    if DEFAULT_MANIFEST_URL:
        return DEFAULT_MANIFEST_URL
    return None


def _skip_path(install_dir: Path) -> Path:
    return install_dir / SKIP_FILE


def should_show_update(info: UpdateInfo, install_dir: Path) -> bool:
    if not is_newer(info.version, installed_version()):
        return False
    skip_file = _skip_path(install_dir)
    if not skip_file.is_file():
        return True
    try:
        data = json.loads(skip_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    if data.get("version") != info.version:
        return True
    until = float(data.get("until", 0))
    return time.time() >= until


def record_skip(info: UpdateInfo, install_dir: Path, hours: float = SKIP_HOURS) -> None:
    payload = {"version": info.version, "until": time.time() + hours * 3600}
    _skip_path(install_dir).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _request_json(url: str, timeout: float = 15.0) -> object | None:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": f"{APP_NAME}/{installed_version()}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        OSError,
        ValueError,
    ):
        return None


def _releases_latest_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest"


def _bundle_url_from_release(repo: str, tag: str, assets: object) -> str:
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if str(asset.get("name", "")).strip() == BUNDLE_ASSET_NAME:
                url = str(asset.get("browser_download_url", "")).strip()
                if url:
                    return url
    tag_slug = tag.strip()
    if tag_slug:
        return (
            f"https://github.com/{repo}/releases/download/"
            f"{tag_slug}/{BUNDLE_ASSET_NAME}"
        )
    return ""


def fetch_update_info_from_github(
    repo: str,
    timeout: float = 15.0,
) -> UpdateInfo | None:
    data = _request_json(
        f"https://api.github.com/repos/{repo}/releases/latest",
        timeout=timeout,
    )
    if not isinstance(data, dict):
        return None

    tag = str(data.get("tag_name", "")).strip()
    version = tag.lstrip("vV")
    if not version:
        return None

    bundle_url = _bundle_url_from_release(repo, tag, data.get("assets"))
    if not bundle_url:
        return None

    notes = str(data.get("body") or data.get("name") or "").strip()
    if len(notes) > 400:
        notes = notes[:400].rstrip() + "…"
    return UpdateInfo(version=version, bundle_url=bundle_url, notes=notes)


def probe_update(inst: Path | None = None) -> UpdateCheckResult:
    """Check GitHub/manifest; distinguish network errors from missing release assets."""
    target = (inst or default_install_dir()).resolve()
    url = manifest_url(target)
    repo = github_repo(target)

    if url:
        info = fetch_update_info(url)
        if info is None:
            return UpdateCheckResult(
                error=(
                    f"Не удалось загрузить манифест обновлений.\n{url}"
                ),
            )
        if not is_newer(info.version, installed_version()):
            return UpdateCheckResult(is_current=True)
        return UpdateCheckResult(info=info)

    if not repo:
        return UpdateCheckResult(
            error="Источник обновлений не настроен (GITHUB_REPO).",
        )

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    data = _request_json(api_url)
    if not isinstance(data, dict):
        return UpdateCheckResult(
            error=(
                "Не удалось связаться с GitHub.\n"
                "Проверьте интернет или повторите позже."
            ),
        )

    tag = str(data.get("tag_name", "")).strip()
    remote_version = tag.lstrip("vV")
    if not remote_version:
        return UpdateCheckResult(
            error="На GitHub нет опубликованных релизов.",
        )

    if not is_newer(remote_version, installed_version()):
        return UpdateCheckResult(is_current=True)

    assets = data.get("assets")
    has_bundle_asset = isinstance(assets, list) and any(
        isinstance(a, dict) and str(a.get("name", "")).strip() == BUNDLE_ASSET_NAME
        for a in assets
    )
    bundle_url = _bundle_url_from_release(repo, tag, assets)
    if not has_bundle_asset:
        page = _releases_latest_url(repo)
        return UpdateCheckResult(
            error=(
                f"Доступна версия {remote_version}, но в релизе нет {BUNDLE_ASSET_NAME} "
                f"для автообновления.\n\n"
                f"Скачайте setup.zip вручную:\n{page}"
            ),
        )

    notes = str(data.get("body") or data.get("name") or "").strip()
    if len(notes) > 400:
        notes = notes[:400].rstrip() + "…"
    return UpdateCheckResult(
        info=UpdateInfo(
            version=remote_version,
            bundle_url=bundle_url,
            notes=notes,
        ),
    )


def fetch_update_info(url: str, timeout: float = 15.0) -> UpdateInfo | None:
    data = _request_json(url, timeout=timeout)
    if not isinstance(data, dict):
        return None
    version = str(data.get("version", "")).strip()
    bundle_url = str(data.get("bundle_url", "")).strip()
    if not version or not bundle_url:
        return None
    notes = str(data.get("notes", "")).strip()
    return UpdateInfo(version=version, bundle_url=bundle_url, notes=notes)


def resolve_update_info(install_dir: Path | None = None) -> UpdateInfo | None:
    inst = (install_dir or default_install_dir()).resolve()
    url = manifest_url(inst)
    if url:
        return fetch_update_info(url)
    repo = github_repo(inst)
    if repo:
        return fetch_update_info_from_github(repo)
    return None


def check_for_update(install_dir: Path | None = None) -> UpdateInfo | None:
    inst = (install_dir or default_install_dir()).resolve()
    if not is_frozen() and not manifest_url(inst) and not github_repo(inst):
        return None
    info = resolve_update_info(inst)
    if info is None:
        return None
    if not should_show_update(info, inst):
        return None
    return info


def download_bundle(
    info: UpdateInfo,
    install_dir: Path,
    on_progress: Callable[[int, str], None] | None = None,
) -> Path:
    cache = install_dir / DOWNLOAD_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "app_bundle.zip"
    tmp = dest.with_suffix(".zip.part")

    def report(percent: int, message: str) -> None:
        if on_progress is not None:
            on_progress(percent, message)

    report(0, "Загрузка обновления…")
    req = urllib.request.Request(
        info.bundle_url,
        headers={"User-Agent": f"{APP_NAME}/{installed_version()}"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        done = 0
        chunk = 256 * 1024
        with tmp.open("wb") as out:
            while True:
                block = resp.read(chunk)
                if not block:
                    break
                out.write(block)
                done += len(block)
                if total > 0:
                    pct = max(1, min(99, int(100 * done / total)))
                    report(pct, f"Загрузка… {done // 1024} КБ")
                else:
                    report(50, f"Загрузка… {done // 1024} КБ")
    tmp.replace(dest)
    report(100, "Загрузка завершена")
    return dest


def _staging_dir(install_dir: Path) -> Path:
    return install_dir / DOWNLOAD_DIRNAME / STAGING_DIRNAME


def _normalize_bundle_root(extracted: Path) -> Path:
    """Zip may contain files at root or under a single release/ folder."""
    if (extracted / "YTDPreviewer.exe").is_file():
        return extracted
    for name in ("release", "YTDPreviewer"):
        nested = extracted / name
        if (nested / "YTDPreviewer.exe").is_file():
            return nested
    return extracted


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for member in zf.infolist():
        target = (root / member.filename).resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root):
            raise ValueError(f"Небезопасный путь в архиве: {member.filename}")
    for member in zf.infolist():
        zf.extract(member, root)


def _extract_bundle_to(zip_path: Path, install_dir: Path) -> Path:
    cache = install_dir / DOWNLOAD_DIRNAME
    cache.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(_staging_dir(install_dir), ignore_errors=True)

    staging = Path(tempfile.mkdtemp(prefix="ytd_stg_", dir=tempfile.gettempdir()))
    (cache / STAGING_MARKER).write_text(str(staging), encoding="utf-8")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            _safe_extract_zip(zf, staging)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return _normalize_bundle_root(staging)


def _read_staging_path(install_dir: Path) -> Path:
    marker = install_dir / DOWNLOAD_DIRNAME / STAGING_MARKER
    if not marker.is_file():
        raise FileNotFoundError(f"Нет данных обновления: {marker}")
    staging = Path(marker.read_text(encoding="utf-8").strip())
    if not staging.is_dir():
        raise FileNotFoundError(f"Папка обновления не найдена: {staging}")
    return staging


def _launch_detached_apply(install_dir: Path) -> None:
    """Start a hidden YTDPreviewer.exe child (no cmd console)."""
    import sys

    from ytdpreviewer.apply_update import is_apply_update_running

    inst = install_dir.resolve()
    if is_apply_update_running(inst):
        return
    staging = _read_staging_path(inst)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
        subprocess, "DETACHED_PROCESS", 0
    )
    if is_frozen():
        exe = viewer_exe()
        if not exe.is_file():
            raise FileNotFoundError(f"Нет исполняемого файла: {exe}")
        cmd = [str(exe), "--apply-update", str(staging), str(inst)]
    else:
        cmd = [
            sys.executable,
            "-m",
            "ytdpreviewer.main",
            "--apply-update",
            str(staging),
            str(inst),
        ]
    subprocess.Popen(cmd, cwd=str(inst), creationflags=flags, close_fds=True)


def apply_downloaded_bundle(
    zip_path: Path,
    install_dir: Path | None = None,
    on_progress: Callable[[int, str], None] | None = None,
    *,
    detached: bool | None = None,
    launch_detached: bool = True,
) -> Path:
    """Apply update bundle. Frozen builds use a detached .bat (avoids self-crash)."""
    inst = (install_dir or default_install_dir()).resolve()
    use_detached = is_frozen() if detached is None else detached

    def step(percent: int, message: str) -> None:
        if on_progress is not None:
            on_progress(percent, message)

    if use_detached:
        step(20, "Распаковка обновления…")
        staging = _extract_bundle_to(zip_path, inst)
        if not (staging / "YTDPreviewer.exe").is_file():
            raise FileNotFoundError(
                "В архиве обновления нет YTDPreviewer.exe.\n"
                "Пересоберите app_bundle.zip (build.bat)."
            )
        step(60, "Подготовка установки…")
        step(90, "Готово к установке…")
        if launch_detached:
            _launch_detached_apply(inst)
            step(100, "Перезапуск программы…")
        else:
            step(100, "Запуск установки…")
        return inst

    from ytdpreviewer.setup_windows import install_with_progress

    source = Path(tempfile.mkdtemp(prefix="ytd_update_"))
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(source)
        payload = _normalize_bundle_root(source)
        target = install_with_progress(
            inst,
            payload,
            dev=False,
            shell_admin=False,
            on_progress=on_progress,
        )
    finally:
        shutil.rmtree(source, ignore_errors=True)
    _restart_background(inst)
    return target


def _restart_background(install_dir: Path) -> None:
    from ytdpreviewer.setup_windows import launch_background_app

    launch_background_app(install_dir)


def _run_update_worker(
    info: UpdateInfo,
    install_dir: Path,
    report: Callable[[int, int, str], None],
) -> None:
    def on_progress(percent: int, message: str) -> None:
        report(max(1, min(percent, 95)), 100, message)

    report(1, 100, "Проверка обновления…")
    bundle = download_bundle(info, install_dir, on_progress=on_progress)
    apply_downloaded_bundle(
        bundle,
        install_dir,
        on_progress=on_progress,
        detached=True,
        launch_detached=False,
    )
    report(95, 100, "Подготовка к установке…")


def _short_release_notes(notes: str, *, limit: int = 140) -> str:
    text = notes.replace("**", "").replace("__", "").strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "…"
    return text


def _show_update_dialog(
    root: tk.Tk,
    info: UpdateInfo,
    install_dir: Path,
    *,
    on_quit: Callable[[], None] | None = None,
    manual: bool = False,
) -> bool:
    global _update_dialog_open

    from ytdpreviewer.apply_update import is_apply_update_running

    if manual:
        _clear_stale_update_ui_lock(install_dir)
        _update_dialog_open = False

    if is_apply_update_running(install_dir):
        if manual:
            _tray_messagebox(
                root,
                "Обновления",
                "Сейчас выполняется установка обновления.\nПодождите несколько секунд.",
                kind="warning",
            )
        return False

    if _update_dialog_open:
        if manual:
            _tray_messagebox(
                root,
                "Обновления",
                "Окно обновления уже открыто.",
            )
        return False

    if not _try_acquire_update_ui_lock(install_dir):
        if manual:
            _tray_messagebox(
                root,
                "Обновления",
                "Окно обновления уже открыто в другом процессе.",
                kind="warning",
            )
        return False

    _update_dialog_open = True
    win = tk.Toplevel(root)
    win.title("YTD Previewer")
    win.configure(bg=BG_VIEW)
    win.resizable(False, False)
    win.attributes("-topmost", True)
    setup_dark_ttk(win)

    frame = tk.Frame(win, bg=BG_VIEW, padx=28, pady=20)
    frame.pack(fill=tk.BOTH, expand=True)
    frame.grid_columnconfigure(0, weight=1)
    frame.grid_rowconfigure(1, weight=1)

    tk.Label(
        frame,
        text="Доступно новое обновление",
        bg=BG_VIEW,
        fg=FG,
        font=("Segoe UI", 12, "bold"),
    ).grid(row=0, column=0, sticky="w")

    detail = (
        f"Установлена версия {installed_version()}.\n"
        f"Доступна версия {info.version}."
    )
    if info.notes:
        detail += f"\n\n{_short_release_notes(info.notes)}"
    tk.Label(
        frame,
        text=detail,
        bg=BG_VIEW,
        fg=FG_DIM,
        font=("Segoe UI", 9),
        justify=tk.LEFT,
        wraplength=380,
    ).grid(row=1, column=0, sticky="nw", pady=(10, 0))

    buttons = tk.Frame(frame, bg=BG_VIEW)
    buttons.grid(row=2, column=0, sticky="e", pady=(18, 0))

    def _close_dialog() -> None:
        global _update_dialog_open
        _update_dialog_open = False
        _release_update_ui_lock(install_dir)
        try:
            win.grab_release()
        except tk.TclError:
            pass
        try:
            win.destroy()
        except tk.TclError:
            pass

    def later() -> None:
        record_skip(info, install_dir)
        _close_dialog()

    def update_now() -> None:
        if getattr(update_now, "_busy", False):
            return
        update_now._busy = True  # type: ignore[attr-defined]
        from ytdpreviewer.export_progress import run_progress_in_host

        def worker(report: Callable[[int, int, str], None]) -> None:
            _run_update_worker(info, install_dir, report)
            report(97, 100, "Установка файлов…")
            _launch_detached_apply(install_dir)
            report(100, 100, "Перезапуск программы…")
            time.sleep(1.2)

        try:
            run_progress_in_host(
                win,
                root,
                "Обновление YTD Previewer",
                worker,
                initial_total=100,
                width=468,
                height=160,
            )
        except Exception as exc:
            update_now._busy = False  # type: ignore[attr-defined]
            _close_dialog()
            messagebox.showerror("Обновление", f"Не удалось установить обновление:\n{exc}")
            return
        _close_dialog()
        if on_quit is not None:
            on_quit()

    flat_button(buttons, "Позже", later).pack(side=tk.RIGHT, padx=(8, 0))
    flat_button(buttons, "Обновить", update_now, accent=True).pack(side=tk.RIGHT)

    win.minsize(440, 220)
    center_tk_window(win, 440, 260)
    win.deiconify()
    win.lift()
    win.focus_force()
    win.grab_set()
    win.protocol("WM_DELETE_WINDOW", later)

    def _on_destroy(_event: tk.Event) -> None:
        global _update_dialog_open
        _update_dialog_open = False
        _release_update_ui_lock(install_dir)

    win.bind("<Destroy>", _on_destroy, add="+")
    return True


def _apply_manual_update_result(
    root: tk.Tk,
    inst: Path,
    result: UpdateCheckResult,
    *,
    on_quit: Callable[[], None] | None,
) -> None:
    if result.error:
        _tray_messagebox(
            root,
            "Обновления",
            f"Текущая версия: {installed_version()}\n\n{result.error}",
            kind="warning",
        )
        return
    if result.is_current:
        _tray_messagebox(
            root,
            "Обновления",
            f"Установлена актуальная версия {installed_version()}.",
        )
        return
    if result.info is not None:
        _show_update_dialog(root, result.info, inst, on_quit=on_quit, manual=True)


def run_manual_update_check(
    root: tk.Tk,
    *,
    install_dir: Path | None = None,
    on_quit: Callable[[], None] | None = None,
) -> None:
    """Tray menu: check GitHub/manifest now (ignores «Позже»)."""
    inst = (install_dir or default_install_dir()).resolve()
    _clear_stale_update_ui_lock(inst)

    if not is_frozen() and not manifest_url(inst) and not github_repo(inst):
        _tray_messagebox(
            root,
            "Обновления",
            f"Текущая версия: {installed_version()}\n\n"
            "Проверка обновлений доступна в установленной программе.",
        )
        return

    wait = tk.Toplevel(root)
    wait.title("Обновления")
    wait.configure(bg=BG_VIEW)
    wait.resizable(False, False)
    wait.attributes("-topmost", True)
    wait.lift()
    tk.Label(
        wait,
        text="Проверка обновлений…",
        bg=BG_VIEW,
        fg=FG_DIM,
        font=("Segoe UI", 10),
        padx=24,
        pady=18,
    ).pack()
    center_tk_window(wait, 260, 90)
    wait.update_idletasks()

    def bg_check() -> None:
        try:
            result = probe_update(inst)

            def finish() -> None:
                try:
                    wait.destroy()
                except tk.TclError:
                    pass
                _apply_manual_update_result(
                    root, inst, result, on_quit=on_quit
                )

            _enqueue_ui(finish)
        except Exception as exc:
            def show_error() -> None:
                try:
                    wait.destroy()
                except tk.TclError:
                    pass
                _tray_messagebox(
                    root,
                    "Обновления",
                    f"Ошибка проверки обновлений:\n{exc}",
                    kind="error",
                )

            _enqueue_ui(show_error)

    threading.Thread(target=bg_check, name="ytd-update-manual", daemon=True).start()


def schedule_update_check(
    root: tk.Tk,
    *,
    install_dir: Path | None = None,
    on_quit: Callable[[], None] | None = None,
    delay_ms: int = CHECK_DELAY_MS,
) -> None:
    inst = (install_dir or default_install_dir()).resolve()

    def bg_check() -> None:
        info = check_for_update(inst)
        if info is not None:
            _enqueue_ui(
                lambda: _show_update_dialog(root, info, inst, on_quit=on_quit)
            )

    def start() -> None:
        threading.Thread(target=bg_check, name="ytd-update-check", daemon=True).start()

    root.after(delay_ms, start)
