"""Detached in-place upgrade (no console window)."""

from __future__ import annotations

import os
import subprocess
import time
import traceback
from pathlib import Path

from ytdpreviewer.paths import APP_NAME, default_install_dir

STAGING_MARKER = "staging_path.txt"
APPLY_LOG_NAME = "apply.log"
APPLY_LOCK_NAME = "applying.lock"
UPDATE_UI_LOCK_NAME = "update_ui.lock"
FINISH_BATCH_NAME = "finish_update.bat"
RUN_HIDDEN_VBS_NAME = "run_hidden.vbs"
WAIT_GRACE_SEC = 12
UPDATER_EXIT_DELAY_SEC = 3
LOCK_MAX_AGE_SEC = 600
UPDATE_CACHE_DIRNAME = "update_cache"


def _append_log(log_path: Path, message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass


def _show_apply_error(exc: BaseException, log_path: Path) -> None:
    text = (
        f"Не удалось установить обновление:\n{exc}\n\n"
        f"Подробности: {log_path}"
    )
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "YTD Previewer", 0x10)
    except Exception:
        pass


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


def _kill_pid(pid: int) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            capture_output=True,
            timeout=15,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _lock_path(install_dir: Path) -> Path:
    return install_dir / UPDATE_CACHE_DIRNAME / APPLY_LOCK_NAME


def is_apply_update_running(install_dir: Path | None = None) -> bool:
    target = (install_dir or default_install_dir()).resolve()
    lock = _lock_path(target)
    if not lock.is_file():
        return False
    try:
        pid_s, stamp_s, *_ = lock.read_text(encoding="utf-8").split()
        pid = int(pid_s)
        age = time.time() - float(stamp_s)
        return age < LOCK_MAX_AGE_SEC and _pid_alive(pid)
    except (OSError, ValueError):
        return False


def _acquire_apply_lock(install_dir: Path, my_pid: int) -> bool:
    lock = _lock_path(install_dir)
    lock.parent.mkdir(parents=True, exist_ok=True)
    if lock.is_file():
        try:
            pid_s, stamp_s, *_ = lock.read_text(encoding="utf-8").split()
            pid = int(pid_s)
            age = time.time() - float(stamp_s)
            if pid != my_pid and age < LOCK_MAX_AGE_SEC and _pid_alive(pid):
                return False
        except (OSError, ValueError):
            pass
    lock.write_text(f"{my_pid} {time.time():.3f}", encoding="ascii")
    return True


def _release_apply_lock(install_dir: Path, my_pid: int) -> None:
    lock = _lock_path(install_dir)
    try:
        if lock.is_file():
            pid_s, *_ = lock.read_text(encoding="utf-8").split()
            if int(pid_s) == my_pid:
                lock.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _install_ytd_processes(install_dir: Path) -> list[tuple[int, str]]:
    """Return (pid, command_line) for YTDPreviewer.exe launched from *install_dir*."""
    install = str(install_dir.resolve())
    esc = install.replace("'", "''")
    ps = (
        f"$base = '{esc}'; "
        f"Get-CimInstance Win32_Process -Filter \"Name='{APP_NAME}.exe'\" "
        "-ErrorAction SilentlyContinue | "
        "Where-Object { $_.ExecutablePath -and "
        "$_.ExecutablePath.StartsWith($base, [StringComparison]::OrdinalIgnoreCase) } | "
        "Select-Object ProcessId, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    raw = (proc.stdout or "").strip()
    if not raw:
        return []
    try:
        import json

        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = [payload]
        rows: list[tuple[int, str]] = []
        for item in payload:
            pid = int(item["ProcessId"])
            cmd = str(item.get("CommandLine") or "")
            rows.append((pid, cmd))
        return rows
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def _blocking_pids(install_dir: Path, except_pid: int) -> list[int]:
    """Processes that must exit before files can be replaced (not other updaters)."""
    pids: list[int] = []
    for pid, cmdline in _install_ytd_processes(install_dir):
        if pid == except_pid:
            continue
        cmd = cmdline.lower()
        if "--apply-update" in cmd:
            continue
        pids.append(pid)
    return pids


def _kill_other_apply_updates(install_dir: Path, except_pid: int, log) -> None:
    for pid, cmdline in _install_ytd_processes(install_dir):
        if pid == except_pid:
            continue
        if "--apply-update" in (cmdline or "").lower():
            log(f"terminate stale apply-update pid={pid}")
            _kill_pid(pid)


def _write_finish_batch(
    install_dir: Path,
    staging: Path,
    *,
    updater_pid: int,
    need_explorer: bool,
) -> Path:
    install = str(install_dir.resolve())
    stage = str(staging.resolve())
    log_file = str((install_dir / UPDATE_CACHE_DIRNAME / APPLY_LOG_NAME).resolve())
    bat = install_dir / UPDATE_CACHE_DIRNAME / FINISH_BATCH_NAME
    bat.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal EnableExtensions",
                f'set "INSTALL={install}"',
                f'set "STAGING={stage}"',
                f"set NEED_EXPLORER={1 if need_explorer else 0}",
                f'set "LOG={log_file}"',
                "echo %DATE% %TIME% finish helper start>>\"%LOG%\"",
                f"ping 127.0.0.1 -n {UPDATER_EXIT_DELAY_SEC} >nul",
                "echo %DATE% %TIME% copying files>>\"%LOG%\"",
                "if %NEED_EXPLORER%==1 (",
                "  taskkill /f /im explorer.exe >nul 2>&1",
                "  ping 127.0.0.1 -n 2 >nul",
                ")",
                (
                    'robocopy "%STAGING%" "%INSTALL%" /E /COPY:DAT '
                    f"/XD {UPDATE_CACHE_DIRNAME} /R:8 /W:2 "
                    "/NFL /NDL /NJH /NJS /NC /NS"
                ),
                "set RC=%ERRORLEVEL%",
                "if %RC% GEQ 8 (",
                "  echo %DATE% %TIME% robocopy failed code %RC%>>\"%LOG%\"",
                "  exit /b 1",
                ")",
                'if exist "%STAGING%\\version.json" copy /Y "%STAGING%\\version.json" "%INSTALL%\\version.json" >nul',
                'if exist "%STAGING%\\version.txt" copy /Y "%STAGING%\\version.txt" "%INSTALL%\\version.txt" >nul',
                'if exist "%STAGING%" rmdir /s /q "%STAGING%" >nul 2>&1',
                f'del "%INSTALL%\\{UPDATE_CACHE_DIRNAME}\\{STAGING_MARKER}" >nul 2>&1',
                f'del "%INSTALL%\\{UPDATE_CACHE_DIRNAME}\\{APPLY_LOCK_NAME}" >nul 2>&1',
                f'del "%INSTALL%\\{UPDATE_CACHE_DIRNAME}\\{UPDATE_UI_LOCK_NAME}" >nul 2>&1',
                "if %NEED_EXPLORER%==1 start explorer.exe",
                f"taskkill /f /im {APP_NAME}.exe /t >nul 2>&1",
                "ping 127.0.0.1 -n 2 >nul",
                'start "" /D "%INSTALL%" "%INSTALL%\\YTDPreviewer.exe" --background',
                "echo %DATE% %TIME% finish helper done>>\"%LOG%\"",
                "endlocal",
                "",
            ]
        ),
        encoding="ascii",
    )
    return bat


def _ensure_run_hidden_vbs(install_dir: Path) -> Path:
    vbs = install_dir / UPDATE_CACHE_DIRNAME / RUN_HIDDEN_VBS_NAME
    if not vbs.is_file():
        vbs.parent.mkdir(parents=True, exist_ok=True)
        vbs.write_text(
            'CreateObject("Wscript.Shell").Run "cmd /c """ & WScript.Arguments(0) & """", 0, False\r\n',
            encoding="ascii",
        )
    return vbs


def _spawn_finish_helper(
    install_dir: Path,
    staging: Path,
    *,
    updater_pid: int,
    need_explorer: bool,
) -> None:
    bat = _write_finish_batch(
        install_dir,
        staging,
        updater_pid=updater_pid,
        need_explorer=need_explorer,
    )
    vbs = _ensure_run_hidden_vbs(install_dir)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["wscript.exe", "//nologo", str(vbs), str(bat)],
        cwd=str(install_dir),
        creationflags=flags,
        close_fds=True,
    )


def run_apply_update(staging: Path, install_dir: Path | None = None) -> None:
    """
    Stop tray/viewers, then hand off file copy to a hidden helper.

    The updater runs from the install dir and locks its own DLLs; robocopy must
    run only after this process exits.
    """
    stage = staging.resolve()
    target = (install_dir or default_install_dir()).resolve()
    my_pid = os.getpid()
    log_path = target / UPDATE_CACHE_DIRNAME / APPLY_LOG_NAME

    def log(message: str) -> None:
        _append_log(log_path, message)

    if not _acquire_apply_lock(target, my_pid):
        log(f"skip pid={my_pid}: another apply-update is already running")
        return

    try:
        if not stage.is_dir():
            raise FileNotFoundError(f"Папка обновления не найдена: {stage}")
        if not (stage / "YTDPreviewer.exe").is_file():
            raise FileNotFoundError(
                "В обновлении нет YTDPreviewer.exe.\n"
                "Пересоберите app_bundle.zip (build.bat)."
            )

        need_explorer = (stage / "YtdThumbnail.dll").is_file()
        log(f"start pid={my_pid} staging={stage} install={target}")

        _kill_other_apply_updates(target, my_pid, log)

        from ytdpreviewer.setup_windows import (
            _stop_explorer,
            _stop_running_app,
            _stop_shell_preview_hosts,
        )

        deadline = time.monotonic() + WAIT_GRACE_SEC
        while time.monotonic() < deadline:
            others = _blocking_pids(target, my_pid)
            if not others:
                break
            log(f"waiting for tray/viewers: {others}")
            time.sleep(0.5)

        log("stop running app instances")
        _stop_running_app(target, except_pid=my_pid)
        time.sleep(0.6)

        if need_explorer:
            log("stop explorer")
            _stop_explorer()
            log("stop shell preview hosts")
            _stop_shell_preview_hosts()

        log("spawn finish helper and exit")
        _spawn_finish_helper(
            target,
            stage,
            updater_pid=my_pid,
            need_explorer=need_explorer,
        )
        _release_apply_lock(target, my_pid)
        os._exit(0)
    except Exception as exc:
        log(f"ERROR: {exc}\n{traceback.format_exc()}")
        _release_apply_lock(target, my_pid)
        _show_apply_error(exc, log_path)
        raise SystemExit(1) from exc
