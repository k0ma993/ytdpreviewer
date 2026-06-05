"""Online update check, download, and in-place upgrade."""

from __future__ import annotations

import json
import os
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

from ytdpreviewer import __version__
from ytdpreviewer.paths import APP_NAME, default_install_dir, is_frozen, viewer_exe
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
SKIP_HOURS = 24
CHECK_DELAY_MS = 2000


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    bundle_url: str
    notes: str = ""


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
    if not is_newer(info.version, __version__):
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
            "User-Agent": f"{APP_NAME}/{__version__}",
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

    bundle_url = ""
    assets = data.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if str(asset.get("name", "")).strip() == BUNDLE_ASSET_NAME:
                bundle_url = str(asset.get("browser_download_url", "")).strip()
                break
    if not bundle_url:
        return None

    notes = str(data.get("body") or data.get("name") or "").strip()
    if len(notes) > 400:
        notes = notes[:400].rstrip() + "…"
    return UpdateInfo(version=version, bundle_url=bundle_url, notes=notes)


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
        headers={"User-Agent": f"{APP_NAME}/{__version__}"},
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


def _extract_bundle(zip_path: Path) -> Path:
    staging = Path(tempfile.mkdtemp(prefix="ytd_update_"))
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(staging)
    return staging


def apply_downloaded_bundle(
    zip_path: Path,
    install_dir: Path | None = None,
    on_progress: Callable[[int, str], None] | None = None,
) -> Path:
    from ytdpreviewer.setup_windows import install_with_progress

    inst = (install_dir or default_install_dir()).resolve()
    source = _extract_bundle(zip_path)
    try:
        target = install_with_progress(
            inst,
            source,
            dev=False,
            shell_admin=False,
            on_progress=on_progress,
            except_pid=os.getpid(),
        )
    finally:
        shutil.rmtree(source, ignore_errors=True)
    _restart_background(inst)
    return target


def _restart_background(install_dir: Path) -> None:
    exe = install_dir / "YTDPreviewer.exe"
    if not exe.is_file():
        exe = viewer_exe()
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    subprocess.Popen(
        [str(exe), "--background"],
        cwd=str(install_dir),
        creationflags=flags | detached,
        close_fds=True,
    )


def _run_update_worker(
    info: UpdateInfo,
    install_dir: Path,
    report: Callable[[int, int, str], None],
) -> None:
    def on_progress(percent: int, message: str) -> None:
        report(max(1, min(percent, 100)), 100, message)

    bundle = download_bundle(info, install_dir, on_progress=on_progress)
    apply_downloaded_bundle(bundle, install_dir, on_progress=on_progress)


def _show_update_dialog(
    root: tk.Tk,
    info: UpdateInfo,
    install_dir: Path,
    *,
    on_quit: Callable[[], None] | None = None,
) -> None:
    win = tk.Toplevel(root)
    win.title("YTD Previewer")
    win.configure(bg=BG_VIEW)
    win.resizable(False, False)
    win.transient(root)
    win.attributes("-topmost", True)
    setup_dark_ttk(win)

    frame = tk.Frame(win, bg=BG_VIEW, padx=28, pady=22)
    frame.pack(fill=tk.BOTH, expand=True)

    tk.Label(
        frame,
        text="Доступно новое обновление",
        bg=BG_VIEW,
        fg=FG,
        font=("Segoe UI", 12, "bold"),
    ).pack(anchor=tk.W)

    detail = f"Установлена версия {__version__}.\nДоступна версия {info.version}."
    if info.notes:
        detail += f"\n\n{info.notes}"
    tk.Label(
        frame,
        text=detail,
        bg=BG_VIEW,
        fg=FG_DIM,
        font=("Segoe UI", 9),
        justify=tk.LEFT,
        wraplength=380,
    ).pack(anchor=tk.W, pady=(10, 16))

    buttons = tk.Frame(frame, bg=BG_VIEW)
    buttons.pack(anchor=tk.E)

    def later() -> None:
        record_skip(info, install_dir)
        win.destroy()

    def update_now() -> None:
        win.destroy()
        from ytdpreviewer.export_progress import run_with_export_progress

        try:
            run_with_export_progress(
                "Обновление YTD Previewer",
                lambda report: _run_update_worker(info, install_dir, report),
                initial_total=100,
            )
        except Exception as exc:
            messagebox.showerror("Обновление", f"Не удалось установить обновление:\n{exc}")
            return
        if on_quit is not None:
            on_quit()

    flat_button(buttons, "Позже", later).pack(side=tk.RIGHT, padx=(8, 0))
    flat_button(buttons, "Обновить", update_now, accent=True).pack(side=tk.RIGHT)

    center_tk_window(win, 440, 200)
    win.grab_set()
    win.protocol("WM_DELETE_WINDOW", later)


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
            root.after(0, lambda: _show_update_dialog(root, info, inst, on_quit=on_quit))

    def start() -> None:
        threading.Thread(target=bg_check, name="ytd-update-check", daemon=True).start()

    root.after(delay_ms, start)
