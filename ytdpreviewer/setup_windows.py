"""Register autostart, .ytd / .ydd associations and custom icons."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import time
import winreg
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ProgressCallback = Callable[[int, str], None]

from ytdpreviewer.paths import APP_NAME, app_dir, assets_dir, default_install_dir

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
INSTALL_MARKER = ".ytdpreviewer-install"

_SAFE_INSTALL_ENTRIES = {
    INSTALL_MARKER,
    "_internal",
    "assets",
    "export.pyw",
    "github_repo.txt",
    "open.pyw",
    "pythonw.txt",
    "registershell.exe",
    "sharpshell.dll",
    "start_background.cmd",
    "thumb.log",
    "thumb_paths",
    "thumb_roots.txt",
    "thumbcache",
    "thumbnail.cmd",
    "thumbnail.pyw",
    "tray.pyw",
    "update_cache",
    "update_skip.json",
    "update_url.txt",
    "version.json",
    "version.txt",
    "yddproperties.dll",
    "ytdpreviewer.exe",
    "ytdpreviewer.propdesc",
    "ytdthumbnail.dll",
}


@dataclass(frozen=True)
class ExtensionSpec:
    ext: str
    prog_id: str
    description: str
    icon_name: str


EXTENSIONS = (
    ExtensionSpec(".ytd", f"{APP_NAME}.ytd", "GTA V Texture Dictionary", "ytd.ico"),
    ExtensionSpec(".ydd", f"{APP_NAME}.ydd", "GTA V Drawable Dictionary", "ydd.ico"),
    ExtensionSpec(".dds", f"{APP_NAME}.dds", "DirectDraw Surface (DDS) texture", "ytd.ico"),
)

# IThumbnailProvider for .ytd (Explorer large icons / tiles)
YTD_THUMB_CLSID = "{8F3C2A1E-9D4B-4E67-B102-7E5D4A3B2C10}"
YTD_THUMB_SHELLEX = "{E357FCCD-A995-4576-B01F-234630154E96}"
YTD_THUMB_PROG_ID = "YTDPreviewer.YtdThumbnail"
YTD_THUMB_CLASS = "YtdThumbnail.ThumbnailProvider"
YTD_THUMB_ASSEMBLY = "YtdThumbnail"
YDD_THUMB_CLSID = "{4C8E1F2A-6B3D-4E59-9C01-2F7E6D5A4B3C}"
YDD_THUMB_PROG_ID = "YTDPreviewer.YddThumbnail"
YDD_THUMB_CLASS = "YtdThumbnail.YddSharpHandler"
YDD_PROPERTY_DLL = "YddProperties.dll"
YDD_PROPERTY_SCHEMA = "YTDPreviewer.propdesc"
YTD_ICON_SHELLEX = "IconHandler"
# RegAsm also registers this for managed in-proc COM (required by Explorer).
DOTNET_COM_CATEGORY = "{62C8FE65-4EBB-45E7-B440-6E39B2CDBF29}"


def _reg_path(*parts: str) -> str:
    return "\\".join(parts)


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def validate_public_install_dir(install_dir: Path) -> Path:
    """Reject any destructive install target except our dedicated app folder."""
    target = install_dir.resolve()
    expected = default_install_dir().resolve()
    if os.path.normcase(str(target)) != os.path.normcase(str(expected)):
        raise ValueError(
            "В целях безопасности YTD Previewer можно устанавливать только в отдельную папку:\n"
            f"{expected}"
        )
    if target.exists() and not target.is_dir():
        raise ValueError(f"Путь установки не является папкой:\n{target}")
    if target.is_dir():
        entries = list(target.iterdir())
        if entries and not (
            (target / INSTALL_MARKER).is_file()
            or (target / "YTDPreviewer.exe").is_file()
        ):
            raise ValueError(
                "Папка установки содержит чужие файлы и не является установкой YTD Previewer.\n"
                "Установка остановлена без удаления файлов."
            )
        unknown = sorted(
            entry.name for entry in entries if entry.name.casefold() not in _SAFE_INSTALL_ENTRIES
        )
        if unknown:
            preview = "\n".join(f"• {name}" for name in unknown[:8])
            raise ValueError(
                "В папке установки найдены неизвестные файлы или программы.\n"
                "Установка остановлена без удаления файлов:\n\n"
                f"{preview}"
            )
    return target


def _property_schema_call(function_name: str, schema: Path) -> bool:
    if function_name not in {"PSRegisterPropertySchema", "PSUnregisterPropertySchema"}:
        return False
    # Keep the native Property System call outside the installer process.
    # Some Windows builds/third-party shell extensions can crash inside propsys;
    # an isolated helper must not take the setup UI down with it.
    schema_arg = str(schema.resolve()).replace("'", "''")
    script = rf"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class YtdPropertySchema {{
    [DllImport("propsys.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    public static extern int PSRegisterPropertySchema(string path);
    [DllImport("propsys.dll", CharSet = CharSet.Unicode, PreserveSig = true)]
    public static extern int PSUnregisterPropertySchema(string path);
}}
'@
$hr = [YtdPropertySchema]::{function_name}('{schema_arg}')
if ($hr -lt 0) {{ exit 1 }}
"""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            creationflags=flags,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _register_ydd_property_handler(install_dir: Path) -> bool:
    dll = install_dir / YDD_PROPERTY_DLL
    schema = install_dir / YDD_PROPERTY_SCHEMA
    if not dll.is_file() or not schema.is_file() or not _is_admin():
        return False
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["regsvr32.exe", "/s", str(dll)],
            capture_output=True,
            timeout=30,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    if not _property_schema_call("PSRegisterPropertySchema", schema):
        subprocess.run(
            ["regsvr32.exe", "/s", "/u", str(dll)],
            capture_output=True,
            timeout=30,
            creationflags=flags,
        )
        return False
    return True


def _unregister_ydd_property_handler(install_dir: Path) -> None:
    dll = install_dir / YDD_PROPERTY_DLL
    schema = install_dir / YDD_PROPERTY_SCHEMA
    if schema.is_file() and _is_admin():
        _property_schema_call("PSUnregisterPropertySchema", schema)
    if dll.is_file() and _is_admin():
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            subprocess.run(
                ["regsvr32.exe", "/s", "/u", str(dll)],
                capture_output=True,
                timeout=30,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _notify_shell() -> None:
    SHCNE_ASSOCCHANGED = 0x08000000
    SHCNF_IDLIST = 0x0000
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def _thumbnail_dll_candidates(source_dir: Path, project_root: Path) -> list[Path]:
    names = ("YtdThumbnail.dll",)
    dirs = (
        source_dir,
        project_root,
        project_root / "shell" / "YtdThumbnail" / "bin" / "Release" / "net48",
        project_root / "shell" / "YtdThumbnail" / "bin" / "x64" / "Release" / "net48",
        project_root / "dist" / "release",
        project_root / "dist" / "YTDPreviewer",
    )
    out: list[Path] = []
    for base in dirs:
        for name in names:
            path = base / name
            if path.is_file():
                out.append(path)
    return out


def _mscoree_path() -> Path:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    for sub in ("Framework64", "Framework"):
        candidate = windir / "Microsoft.NET" / sub / "v4.0.30319" / "mscoree.dll"
        if candidate.is_file():
            return candidate
    return windir / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "mscoree.dll"


def _assembly_version(dll_path: Path) -> str:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    ps = (
        f"[System.Reflection.AssemblyName]::GetAssemblyName('{dll_path}').Version.ToString()"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except OSError:
        pass
    return "1.0.0.0"


def _read_regasm_regfile_text(reg_file: Path) -> str:
    data = reg_file.read_bytes()
    if data.startswith(b"\xff\xfe"):
        return data.decode("utf-16-le")
    return data.decode("utf-8", errors="replace")


def _import_regasm_regfile(reg_file: Path, *, classes_root: str, label: str) -> bool:
    """RegAsm writes ASCII REGEDIT4; must stay ASCII for reg import."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        text = _read_regasm_regfile_text(reg_file)
        if "REGEDIT" not in text:
            return False
        text = text.replace("HKEY_CLASSES_ROOT", classes_root)
        out = reg_file.with_name(f"ytdpreviewer_{label}.reg")
        out.write_bytes(text.encode("utf-8"))
        import_reg = subprocess.run(
            ["reg", "import", str(out)],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
        )
        return import_reg.returncode == 0
    except OSError:
        return False


def _register_dotnet_com_regasm_regfile(dll_path: Path, *, classes_root: str, label: str) -> bool:
    regasm = _mscoree_path().parent / "RegAsm.exe"
    if not regasm.is_file():
        return False

    reg_file = Path(os.environ.get("TEMP", ".")) / "ytdpreviewer_com.reg"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [str(regasm), str(dll_path.resolve()), "/regfile:" + str(reg_file), "/codebase", "/nologo"],
            capture_output=True,
            text=True,
            timeout=60,
            creationflags=flags,
        )
        if proc.returncode != 0 or not reg_file.is_file():
            return False
        return _import_regasm_regfile(reg_file, classes_root=classes_root, label=label)
    except OSError:
        return False


def _register_dotnet_com_regasm_hkcu(dll_path: Path) -> bool:
    return _register_dotnet_com_regasm_regfile(
        dll_path,
        classes_root=r"HKEY_CURRENT_USER\Software\Classes",
        label="hkcu",
    )


def _register_dotnet_com_regasm_hklm(dll_path: Path) -> bool:
    return _register_dotnet_com_regasm_regfile(
        dll_path,
        classes_root=r"HKEY_LOCAL_MACHINE\Software\Classes",
        label="hklm",
    )


def _com_clsid_registered_hklm(clsid: str) -> bool:
    key = _reg_path("Software", "Classes", "CLSID", clsid, "InprocServer32")
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as opened:
            winreg.QueryValueEx(opened, "Assembly")
            return True
    except OSError:
        return False


def _register_dotnet_com_manual(
    dll_path: Path,
    *,
    clsid: str,
    prog_id: str,
    class_name: str,
    assembly_name: str,
    hive: int,
) -> None:
    """Register in-process .NET COM (RegAsm layout) under HKCU or HKLM."""
    dll_uri = dll_path.resolve().as_uri()
    version = _assembly_version(dll_path)
    mscoree = str(_mscoree_path())

    clsid_key = _reg_path("Software", "Classes", "CLSID", clsid)
    with winreg.CreateKey(hive, clsid_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, class_name)

    assembly_ref = f"{assembly_name}, Version={version}, Culture=neutral, PublicKeyToken=null"
    runtime = "v4.0.30319"

    inproc = _reg_path(clsid_key, "InprocServer32")
    with winreg.CreateKey(hive, inproc) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, mscoree)
        winreg.SetValueEx(key, "ThreadingModel", 0, winreg.REG_SZ, "Both")
        winreg.SetValueEx(key, "Assembly", 0, winreg.REG_SZ, assembly_ref)
        winreg.SetValueEx(key, "Class", 0, winreg.REG_SZ, class_name)
        winreg.SetValueEx(key, "CodeBase", 0, winreg.REG_SZ, dll_uri)
        winreg.SetValueEx(key, "RuntimeVersion", 0, winreg.REG_SZ, runtime)

    asm_key = _reg_path(inproc, version)
    with winreg.CreateKey(hive, asm_key) as key:
        winreg.SetValueEx(key, "Assembly", 0, winreg.REG_SZ, assembly_ref)
        winreg.SetValueEx(key, "Class", 0, winreg.REG_SZ, class_name)
        winreg.SetValueEx(key, "CodeBase", 0, winreg.REG_SZ, dll_uri)
        winreg.SetValueEx(key, "RuntimeVersion", 0, winreg.REG_SZ, runtime)

    with winreg.CreateKey(hive, _reg_path(clsid_key, "ProgId")) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, prog_id)

    prog_key = _reg_path("Software", "Classes", prog_id)
    with winreg.CreateKey(hive, prog_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, class_name)
    with winreg.CreateKey(hive, _reg_path(prog_key, "CLSID")) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, clsid)

    cat_key = _reg_path(
        "Software", "Classes", "CLSID", clsid, "Implemented Categories", DOTNET_COM_CATEGORY
    )
    with winreg.CreateKey(hive, cat_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "")

    _apply_thumbnail_com_extras(clsid)


def _register_dotnet_com_hkcu(
    dll_path: Path,
    *,
    clsid: str,
    prog_id: str,
    class_name: str,
    assembly_name: str,
) -> None:
    _register_dotnet_com_manual(
        dll_path,
        clsid=clsid,
        prog_id=prog_id,
        class_name=class_name,
        assembly_name=assembly_name,
        hive=winreg.HKEY_CURRENT_USER,
    )


def _apply_thumbnail_com_extras(clsid: str) -> None:
    """Let Explorer load the managed thumbnail handler in-process (see MS thumbnail docs)."""
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        clsid_key = _reg_path("Software", "Classes", "CLSID", clsid)
        try:
            with winreg.CreateKey(hive, clsid_key) as key:
                winreg.SetValueEx(key, "DisableProcessIsolation", 0, winreg.REG_DWORD, 1)
            for cat in (DOTNET_COM_CATEGORY, YTD_THUMB_SHELLEX):
                cat_key = _reg_path(clsid_key, "Implemented Categories", cat)
                with winreg.CreateKey(hive, cat_key) as key:
                    winreg.SetValueEx(key, None, 0, winreg.REG_SZ, "")
        except OSError:
            continue


def _register_thumbnail_shell_extras(
    *, clsid: str, ext: str, label: str, hive: int = winreg.HKEY_CURRENT_USER
) -> None:
    """Keys required by Explorer on Windows 10/11 (Approved + ThumbnailHandlers)."""
    approved = _reg_path(
        "Software", "Microsoft", "Windows", "CurrentVersion", "Shell Extensions", "Approved"
    )
    with winreg.CreateKey(hive, approved) as key:
        winreg.SetValueEx(key, clsid, 0, winreg.REG_SZ, label)

    handlers = _reg_path(
        "Software", "Microsoft", "Windows", "CurrentVersion", "Explorer", "ThumbnailHandlers"
    )
    with winreg.CreateKey(hive, handlers) as key:
        winreg.SetValueEx(key, ext, 0, winreg.REG_SZ, clsid)

    # Do not set PerceivedType=image — Explorer would ignore our handler and use WIC/Photos.


def _unregister_thumbnail_shell_extras(
    *, clsid: str, ext: str, hive: int = winreg.HKEY_CURRENT_USER
) -> None:
    approved = _reg_path(
        "Software", "Microsoft", "Windows", "CurrentVersion", "Shell Extensions", "Approved"
    )
    try:
        with winreg.OpenKey(hive, approved, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, clsid)
    except OSError:
        pass

    handlers = _reg_path(
        "Software", "Microsoft", "Windows", "CurrentVersion", "Explorer", "ThumbnailHandlers"
    )
    try:
        with winreg.OpenKey(hive, handlers, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, ext)
    except OSError:
        pass


def _shellex_registered(hive: int, ext: str, *, clsid: str | None = None) -> bool:
    expected = (clsid or YTD_THUMB_CLSID).upper()
    key = _reg_path("Software", "Classes", ext, "shellex", YTD_THUMB_SHELLEX)
    try:
        with winreg.OpenKey(hive, key) as opened:
            val, _ = winreg.QueryValueEx(opened, None)
            return str(val).upper() == expected
    except OSError:
        return False


def _unregister_dotnet_com_hkcu(*, clsid: str, prog_id: str) -> None:
    _unregister_dotnet_com(clsid=clsid, prog_id=prog_id)


def _unregister_dotnet_com(*, clsid: str, prog_id: str) -> None:
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _delete_tree(_reg_path("Software", "Classes", "CLSID", clsid), hive=hive)
        _delete_tree(_reg_path("Software", "Classes", prog_id), hive=hive)


def _write_thumbnail_pyw(install_dir: Path, project_root: Path, *, dev: bool = False) -> Path:
    root = str(project_root.resolve()).replace("\\", "\\\\")
    install = str(install_dir.resolve()).replace("\\", "\\\\")
    use_source = "True" if dev else "False"
    pyw = install_dir / "thumbnail.pyw"
    pyw.write_text(
        "\n".join(
            [
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "",
                f'INSTALL = Path(r"{install}")',
                f'ROOT = Path(r"{root}")',
                f"USE_SOURCE = {use_source}",
                "",
                "def _output_ok(path: Path) -> bool:",
                "    try:",
                "        return path.is_file() and path.stat().st_size > 512",
                "    except OSError:",
                "        return False",
                "",
                'if __name__ == "__main__":',
                "    if len(sys.argv) < 4:",
                "        raise SystemExit(2)",
                "    src, out, size = sys.argv[1], sys.argv[2], sys.argv[3]",
                "    extra = sys.argv[4:] if len(sys.argv) > 4 else []",
                "    fast = any(x in ('1', 'fast', '--fast') for x in extra)",
                "    out_path = Path(out)",
                "    src_path = Path(src)",
                "    if 'ydd' in extra:",
                "        is_ydd = True",
                "    elif 'ytd' in extra:",
                "        is_ydd = False",
                "    else:",
                "        is_ydd = src_path.suffix.lower() == '.ydd' or (",
                "            src_path.name.lower().startswith('yddprev_')",
                "            and src_path.suffix.lower() == '.tmp'",
                "        )",
                "    thumb_flag = '--ydd-thumbnail' if is_ydd else '--thumbnail'",
                "    if not USE_SOURCE:",
                "        exe = INSTALL / 'YTDPreviewer.exe'",
                "        if exe.is_file():",
                "            cmd = [str(exe), thumb_flag, src, out, size]",
                "            if not is_ydd and fast:",
                "                cmd.append('--fast')",
                "            subprocess.call(cmd)",
                "            if _output_ok(out_path):",
                "                raise SystemExit(0)",
                "    if USE_SOURCE:",
                "        if str(ROOT) not in sys.path:",
                "            sys.path.insert(0, str(ROOT))",
                "    else:",
                "        internal = INSTALL / '_internal'",
                "        if internal.is_dir() and str(internal) not in sys.path:",
                "            sys.path.insert(0, str(internal))",
                "    texture_root = None",
                "    identity_ydd = None",
                "    if is_ydd:",
                "        for arg in extra:",
                "            if arg.lower().endswith('.ydd'):",
                "                p = Path(arg)",
                "                if p.is_file():",
                "                    texture_root = p.parent",
                "                    identity_ydd = p",
                "                    break",
                "    if is_ydd:",
                "        from ytdpreviewer.ydd_thumbnail import render_ydd_thumbnail_file",
                "        ok = render_ydd_thumbnail_file(",
                "            Path(src),",
                "            Path(out),",
                "            max_side=max(32, int(size)),",
                "            texture_root=texture_root,",
                "            identity_ydd=identity_ydd,",
                "            allow_placeholder=False,",
                "        )",
                "    else:",
                "        from ytdpreviewer.ytd_texture_preview import render_thumbnail_file",
                "        ok = render_thumbnail_file(Path(src), Path(out), max_side=max(32, int(size)), fast=fast)",
                "    raise SystemExit(0 if ok else 1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return pyw


def _resolve_pythonw_for_thumbnails() -> Path | None:
    """Real pythonw.exe for dev installs — never setup.exe / YTDPreviewer.exe."""
    exe = Path(sys.executable).resolve()
    if exe.name.lower() == "pythonw.exe":
        return exe
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.is_file():
            return candidate
    if exe.name.lower() in ("setup.exe", "ytdpreviewer.exe"):
        return None

    sibling = exe.parent / "pythonw.exe"
    if sibling.is_file():
        return sibling

    local = os.environ.get("LOCALAPPDATA", "")
    for ver in ("313", "312", "311", "310"):
        candidate = Path(local) / "Programs" / "Python" / f"Python{ver}" / "pythonw.exe"
        if candidate.is_file():
            return candidate

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["where", "pythonw"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                path = Path(line.strip())
                if path.is_file() and path.name.lower() == "pythonw.exe":
                    return path
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _write_thumbnail_cmd_for_exe(install_dir: Path) -> None:
    app_exe = install_dir / "YTDPreviewer.exe"
    if not app_exe.is_file():
        return
    exe = str(app_exe.resolve()).replace('"', '""')
    (install_dir / "thumbnail.cmd").write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f'set "EXE={exe}"',
                'set "SRC=%~1"',
                'set "OUT=%~2"',
                'set "SZ=%~3"',
                'if /I "%~4"=="ydd" (',
                '  "%EXE%" --ydd-thumbnail "%SRC%" "%OUT%" "%SZ%"',
                "  exit /b %ERRORLEVEL%",
                ")",
                'if /I "%~5"=="fast" (',
                '  "%EXE%" --thumbnail "%SRC%" "%OUT%" "%SZ%" --fast',
                ") else (",
                '  "%EXE%" --thumbnail "%SRC%" "%OUT%" "%SZ%"',
                ")",
                "endlocal",
                "",
            ]
        ),
        encoding="ascii",
    )


def _write_thumbnail_launcher(install_dir: Path) -> None:
    pythonw = _resolve_pythonw_for_thumbnails()
    cfg = install_dir / "pythonw.txt"
    if pythonw is not None:
        cfg.write_text(str(pythonw.resolve()), encoding="utf-8")
        pyw = str(pythonw.resolve()).replace('"', '""')
        (install_dir / "thumbnail.cmd").write_text(
            f'@echo off\r\n"{pyw}" "%~dp0thumbnail.pyw" %*\r\n',
            encoding="ascii",
        )
        return

    if cfg.is_file():
        try:
            line = cfg.read_text(encoding="utf-8").strip().lower()
            if line.endswith("setup.exe") or line.endswith("ytdpreviewer.exe"):
                cfg.unlink()
        except OSError:
            pass

    _write_thumbnail_cmd_for_exe(install_dir)


def _seed_thumb_roots(*folders: Path) -> None:
    from ytdpreviewer.thumb_roots import append_thumb_root

    for folder in folders:
        try:
            resolved = folder.resolve()
        except OSError:
            continue
        if resolved.is_dir():
            append_thumb_root(resolved)


def _register_ytd_thumbnail(
    install_dir: Path,
    source_dir: Path,
    project_root: Path,
    *,
    dev: bool = False,
    shell_admin: bool = False,
) -> None:
    dll_dst = _ensure_thumbnail_dll(
        install_dir, source_dir, project_root, shell_admin=shell_admin
    )
    if dll_dst is None:
        print("WARNING: YtdThumbnail.dll not found — build shell\\YtdThumbnail first.")
        return

    _write_thumbnail_pyw(install_dir, project_root, dev=dev)
    _write_thumbnail_launcher(install_dir)

    ytd_spec = EXTENSIONS[0]
    for base in (
        _reg_path("Software", "Classes", ytd_spec.prog_id, "shellex", YTD_ICON_SHELLEX),
        _reg_path("Software", "Classes", ytd_spec.ext, "shellex", YTD_ICON_SHELLEX),
        _reg_path(
            "Software", "Classes", "SystemFileAssociations", ytd_spec.ext, "shellex", YTD_ICON_SHELLEX
        ),
    ):
        _delete_tree(base)

    # Remove legacy second-CLSID registration (broken on .NET manual COM).
    _unregister_dotnet_com_hkcu(
        clsid="{7E5D4A3B-2C10-4E67-B102-8F3C2A1E9D4B}",
        prog_id="YTDPreviewer.ytd.IconHandler",
    )
    use_system = shell_admin and _is_admin()
    if use_system:
        if not _register_sharpshell_explorer(dll_dst, project_root):
            print("WARNING: SharpShell registration failed — run install_shell_admin.bat as Administrator")
    elif not _register_dotnet_com_regasm_hkcu(dll_dst):
        _register_dotnet_com_hkcu(
            dll_dst,
            clsid=YTD_THUMB_CLSID,
            prog_id=YTD_THUMB_PROG_ID,
            class_name=YTD_THUMB_CLASS,
            assembly_name=YTD_THUMB_ASSEMBLY,
        )

    shellex_targets = (
        _reg_path("Software", "Classes", ytd_spec.prog_id, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", ytd_spec.ext, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", "SystemFileAssociations", ".ytd", "shellex", YTD_THUMB_SHELLEX),
    )
    hives = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER] if use_system else [winreg.HKEY_CURRENT_USER]
    for hive in hives:
        for base in shellex_targets:
            with winreg.CreateKey(hive, base) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, YTD_THUMB_CLSID)
        _register_thumbnail_shell_extras(
            clsid=YTD_THUMB_CLSID,
            ext=ytd_spec.ext,
            label="YTD Previewer texture thumbnail",
            hive=hive,
        )

    _apply_thumbnail_com_extras(YTD_THUMB_CLSID)
    _disable_thumbnail_type_overlay(ytd_spec)
    # IconHandler on the same .NET CLSID breaks Explorer thumbnails (8007007E).
    # Static ytd.ico is set in _register_extension; previews use IThumbnailProvider only.
    _unregister_ydd_thumbnail_shellex(shell_admin=shell_admin)


def _unregister_ydd_thumbnail_shellex(*, shell_admin: bool = False) -> None:
    """Remove Explorer thumbnail handler for .ydd (static ydd.ico only, no render)."""
    ydd_spec = next(s for s in EXTENSIONS if s.ext == ".ydd")
    use_system = shell_admin and _is_admin()
    shellex_targets = (
        _reg_path("Software", "Classes", ydd_spec.prog_id, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", ydd_spec.ext, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", "SystemFileAssociations", ".ydd", "shellex", YTD_THUMB_SHELLEX),
    )
    hives = [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER] if use_system else [winreg.HKEY_CURRENT_USER]
    for hive in hives:
        _unregister_thumbnail_shell_extras(clsid=YDD_THUMB_CLSID, ext=ydd_spec.ext, hive=hive)
        for base in shellex_targets:
            _delete_tree(base, hive=hive)


def _unregister_sharpshell(install_dir: Path | None, project_root: Path | None) -> bool:
    """Remove SharpShell handler registration (required if install_shell_admin was used)."""
    candidates: list[tuple[Path, Path]] = []
    if install_dir is not None:
        candidates.append((install_dir, install_dir))
    root = project_root or Path(__file__).resolve().parent.parent
    built = root / "shell" / "RegisterShell" / "bin" / "Release" / "net48"
    candidates.append((built, install_dir or built))

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for reg_exe_dir, cwd in candidates:
        reg_exe = reg_exe_dir / "RegisterShell.exe"
        if not reg_exe.is_file():
            continue
        print(f"  SharpShell: {reg_exe}", flush=True)
        try:
            proc = subprocess.run(
                [str(reg_exe), "uninstall"],
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=25,
                creationflags=flags,
            )
            if proc.stdout:
                print(proc.stdout.strip(), flush=True)
            if proc.returncode == 0:
                return True
        except subprocess.TimeoutExpired:
            print("  WARNING: SharpShell uninstall timed out (continuing)", flush=True)
        except OSError as exc:
            print(f"  WARNING: SharpShell uninstall failed: {exc}", flush=True)
    return False


def _unregister_ytd_thumbnail(
    install_dir: Path | None = None, project_root: Path | None = None
) -> None:
    inst = install_dir or default_install_dir()
    root = project_root or Path(__file__).resolve().parent.parent
    print("  останавливаем проводник (разблокировать DLL)...", flush=True)
    _stop_explorer()
    _unregister_sharpshell(inst, root)
    _unregister_dotnet_com(clsid=YTD_THUMB_CLSID, prog_id=YTD_THUMB_PROG_ID)
    _unregister_dotnet_com(clsid=YDD_THUMB_CLSID, prog_id=YDD_THUMB_PROG_ID)
    ytd_spec = EXTENSIONS[0]
    ydd_spec = next(s for s in EXTENSIONS if s.ext == ".ydd")
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        _unregister_thumbnail_shell_extras(clsid=YTD_THUMB_CLSID, ext=ytd_spec.ext, hive=hive)
        _unregister_thumbnail_shell_extras(clsid=YDD_THUMB_CLSID, ext=ydd_spec.ext, hive=hive)
    thumb_shellex = (
        _reg_path("Software", "Classes", ytd_spec.prog_id, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", ytd_spec.ext, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", "SystemFileAssociations", ".ytd", "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", ydd_spec.prog_id, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", ydd_spec.ext, "shellex", YTD_THUMB_SHELLEX),
        _reg_path("Software", "Classes", "SystemFileAssociations", ".ydd", "shellex", YTD_THUMB_SHELLEX),
    )
    icon_shellex = (
        _reg_path("Software", "Classes", ytd_spec.prog_id, "shellex", YTD_ICON_SHELLEX),
        _reg_path("Software", "Classes", ytd_spec.ext, "shellex", YTD_ICON_SHELLEX),
        _reg_path(
            "Software", "Classes", "SystemFileAssociations", ytd_spec.ext, "shellex", YTD_ICON_SHELLEX
        ),
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for rel in icon_shellex + thumb_shellex:
            _delete_tree(rel, hive=hive)


def _unregister_directory_warm_verb() -> None:
    for suffix in ("Directory", r"Directory\Background"):
        _delete_tree(_reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs", "command"))
        _delete_tree(_reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs"))


def _clear_thumbnail_caches(install_dir: Path | None = None) -> None:
    """Remove our PNG cache and Explorer thumb DBs (old .ytd previews otherwise stay visible)."""
    dirs: list[Path] = []
    if install_dir is not None:
        dirs.append(install_dir)
    dirs.append(default_install_dir())
    program_data = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / APP_NAME
    dirs.append(program_data)

    for base in dirs:
        cache = base / "thumbcache"
        if cache.is_dir():
            shutil.rmtree(cache, ignore_errors=True)

    explorer = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Explorer"
    if explorer.is_dir():
        for pattern in ("thumbcache_*.db", "iconcache_*.db"):
            for path in explorer.glob(pattern):
                try:
                    path.unlink()
                except OSError:
                    pass


def _restart_explorer() -> None:
    """Kill and restart Explorer (refresh shell / thumbnail handlers)."""
    _stop_explorer()
    time.sleep(0.5)
    _start_explorer()
    time.sleep(0.4)
    if _explorer_is_running():
        print("  проводник запущен.", flush=True)
    else:
        print(
            "  если рабочий стол пустой: Ctrl+Shift+Esc → Файл → Запустить explorer.exe",
            flush=True,
        )


def _ensure_explorer_running() -> None:
    if _explorer_is_running():
        return
    _start_explorer()
    time.sleep(0.4)
    if not _explorer_is_running():
        explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "open", str(explorer), None, None, 1
            )
        except OSError:
            pass


def _delete_tree(key_path: str, hive: int = winreg.HKEY_CURRENT_USER) -> None:
    if hive == winreg.HKEY_LOCAL_MACHINE and not _is_admin():
        return
    try:
        with winreg.OpenKey(hive, key_path, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                    _delete_tree(f"{key_path}\\{sub}", hive=hive)
                except OSError:
                    break
            winreg.DeleteKey(hive, key_path)
    except OSError:
        pass


def _remove_extension_default_icon(prog_id: str) -> None:
    _delete_tree(_reg_path("Software", "Classes", prog_id, "DefaultIcon"))


def _set_extension_type_icon(spec: ExtensionSpec, install_dir: Path) -> None:
    """Мелкие значки в проводнике: ytd.ico (зелёный), ydd.ico (синий)."""
    icon_file = install_dir / "assets" / spec.icon_name
    if not icon_file.is_file():
        icon_file = assets_dir() / spec.icon_name
    if not icon_file.is_file():
        return
    icon_value = f'"{icon_file.resolve()}",0'
    for rel in (spec.prog_id, spec.ext, f"SystemFileAssociations\\{spec.ext}"):
        key_path = _reg_path("Software", "Classes", rel, "DefaultIcon")
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                winreg.SetValueEx(key, None, 0, winreg.REG_SZ, icon_value)
        except OSError:
            pass


def _disable_thumbnail_type_overlay(spec: ExtensionSpec) -> None:
    """
    Убрать значок приложения в правом нижнем углу превью в проводнике.
    MSDN: TypeOverlay = "" — оверлей не рисуется; иначе — иконка программы (app.ico).
    """
    rel_paths = (
        spec.prog_id,
        spec.ext,
        f"SystemFileAssociations\\{spec.ext}",
        YTD_THUMB_PROG_ID,
    )
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        if hive == winreg.HKEY_LOCAL_MACHINE and not _is_admin():
            continue
        for rel in rel_paths:
            key_path = _reg_path("Software", "Classes", rel)
            try:
                with winreg.CreateKey(hive, key_path) as key:
                    winreg.SetValueEx(key, "TypeOverlay", 0, winreg.REG_SZ, "")
            except OSError:
                pass


def _read_run_autostart() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(val)
    except OSError:
        return None


def _fix_autostart_entry(install_dir: Path) -> None:
    app_exe = install_dir / "YTDPreviewer.exe"
    if not app_exe.is_file():
        return
    correct = f'"{app_exe}" --background'
    current = _read_run_autostart()
    if current is None:
        return
    low = current.lower()
    if "setup.exe" in low or current.strip() != correct:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, correct)


def _start_menu_shortcut_path() -> Path:
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "YTD Previewer.lnk"


def _create_start_menu_shortcut(install_dir: Path) -> bool:
    app_exe = (install_dir / "YTDPreviewer.exe").resolve()
    if not app_exe.is_file():
        return False
    shortcut = _start_menu_shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)

    def ps_quote(value: str) -> str:
        return value.replace("'", "''")

    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$link = $shell.CreateShortcut('{ps_quote(str(shortcut))}'); "
        f"$link.TargetPath = '{ps_quote(str(app_exe))}'; "
        "$link.Arguments = '--background'; "
        f"$link.WorkingDirectory = '{ps_quote(str(app_exe.parent))}'; "
        f"$link.IconLocation = '{ps_quote(str(app_exe))},0'; "
        "$link.Description = 'YTD Previewer'; "
        "$link.Save()"
    )
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            creationflags=flags,
        )
        return proc.returncode == 0 and shortcut.is_file()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _remove_start_menu_shortcut() -> None:
    shortcuts = (
        _start_menu_shortcut_path(),
        _start_menu_shortcut_path().with_name(f"{APP_NAME}.lnk"),
    )
    for shortcut in shortcuts:
        try:
            shortcut.unlink(missing_ok=True)
        except OSError:
            pass


def _apply_ftype_assoc(spec: ExtensionSpec, open_command: str) -> None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["cmd", "/c", "assoc", f"{spec.ext}={spec.prog_id}"],
            capture_output=True,
            creationflags=flags,
            timeout=10,
        )
        subprocess.run(
            ["cmd", "/c", "ftype", f"{spec.prog_id}={open_command}"],
            capture_output=True,
            creationflags=flags,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _purge_setup_exe_handlers() -> None:
    """Remove mistaken open/warm commands pointing at setup.exe."""
    bad_markers = ("setup.exe", "dist\\setup", "dist/setup")
    for spec in EXTENSIONS:
        open_key = _reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, open_key, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, None)
            low = str(val).lower()
            if any(m in low for m in bad_markers):
                _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command"))
                _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", "open"))
        except OSError:
            pass
        ext_open = _reg_path("Software", "Classes", spec.ext, "shell", "open", "command")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ext_open, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, None)
            if any(m in str(val).lower() for m in bad_markers):
                _delete_tree(ext_open)
        except OSError:
            pass
    for suffix in ("Directory", r"Directory\Background"):
        cmd_key = _reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs", "command")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cmd_key, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, None)
            if any(m in str(val).lower() for m in bad_markers):
                _delete_tree(cmd_key)
                _delete_tree(_reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs"))
        except OSError:
            pass


def _force_open_handlers(install_dir: Path) -> None:
    """Always point .ytd/.ydd open at YTDPreviewer.exe (never setup.exe)."""
    app_exe = install_dir / "YTDPreviewer.exe"
    if not app_exe.is_file():
        return
    open_cmd = f'"{app_exe.resolve()}" "%1"'
    for spec in EXTENSIONS:
        open_key = _reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, open_key) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, open_cmd)
        _apply_ftype_assoc(spec, open_cmd)


def repair_installation(
    install_dir: Path | None = None,
    *,
    re_register: bool = True,
    register_thumbnails: bool = False,
) -> Path:
    """
    Fix autostart/open commands (never setup.exe), set green/blue .ytd/.ydd icons,
    re-apply associations to YTDPreviewer.exe.
    """
    target = (install_dir or default_install_dir()).resolve()
    app_exe = target / "YTDPreviewer.exe"
    if not app_exe.is_file():
        raise FileNotFoundError(
            f"Не найден {app_exe}. Сначала установите программу (build.bat → dist\\setup\\setup.exe)."
        )

    project_root = Path(__file__).resolve().parent.parent
    _purge_setup_exe_handlers()
    _fix_autostart_entry(target)
    _force_open_handlers(target)

    for spec in EXTENSIONS:
        _set_extension_type_icon(spec, target)
        _disable_thumbnail_type_overlay(spec)

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pythonw = Path(sys.executable)

    open_cmd, autostart_cmd, export_png_cmd, export_obj_cmd, export_ydd_tex_cmd, build_ytd_cmd = (
        _launch_commands(target, project_root, pythonw, dev=False)
    )
    if "setup.exe" in open_cmd.lower():
        raise RuntimeError("Внутренняя ошибка: обработчик setup.exe")

    if re_register:
        for spec in EXTENSIONS:
            shell_verbs: dict[str, tuple[str, str]] = {}
            if spec.ext == ".ytd":
                shell_verbs["exportpng"] = ("Экспортировать в PNG", export_png_cmd)
            elif spec.ext == ".ydd":
                shell_verbs["exportobj"] = ("Экспортировать в OBJ", export_obj_cmd)
                shell_verbs["exporttex"] = ("Экспортировать вложенные текстуры", export_ydd_tex_cmd)
            _register_extension(spec, target, open_cmd, shell_verbs)
            _apply_ftype_assoc(spec, open_cmd)

        warm_cmd = _warm_thumbs_command(target, project_root, pythonw, dev=False)
        _register_directory_warm_verb(warm_cmd)

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_cmd)

    _write_thumbnail_pyw(target, target, dev=False)
    _write_thumbnail_launcher(target)
    _unregister_ydd_thumbnail_shellex(shell_admin=_is_admin())
    if register_thumbnails:
        _register_ytd_thumbnail(target, target, project_root, dev=False, shell_admin=_is_admin())

    _notify_shell()
    return target


def diagnose_registry(install_dir: Path | None = None) -> None:
    target = (install_dir or default_install_dir()).resolve()
    print(f"Install dir: {target}", flush=True)
    print(f"YTDPreviewer.exe: {(target / 'YTDPreviewer.exe').is_file()}", flush=True)
    print(f"YtdThumbnail.dll: {(target / 'YtdThumbnail.dll').is_file()}", flush=True)
    print(f"Autostart: {_read_run_autostart()!r}", flush=True)
    for spec in EXTENSIONS:
        open_key = _reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, open_key, 0, winreg.KEY_READ) as key:
                val, _ = winreg.QueryValueEx(key, None)
            print(f"Open {spec.ext}: {val}", flush=True)
        except OSError:
            print(f"Open {spec.ext}: (not set)", flush=True)
    print(f"HKLM thumb COM: {_com_clsid_registered_hklm(YTD_THUMB_CLSID)}", flush=True)
    print(f"HKLM shellex .ytd: {_shellex_registered(winreg.HKEY_LOCAL_MACHINE, '.ytd')}", flush=True)
    pyw_cfg = target / "pythonw.txt"
    if pyw_cfg.is_file():
        pyw_line = pyw_cfg.read_text(encoding="utf-8").strip()
        print(f"pythonw.txt: {pyw_line}", flush=True)
        if pyw_line.lower().endswith("setup.exe"):
            print(
                "ОШИБКА: pythonw.txt указывает на setup.exe — при превью в проводнике "
                "открывается установщик. Запустите: python -m ytdpreviewer.setup_windows repair",
                flush=True,
            )


def _register_shell_verb(prog_id: str, verb: str, label: str, command: str) -> None:
    verb_key = _reg_path("Software", "Classes", prog_id, "shell", verb)
    verb_cmd_key = _reg_path("Software", "Classes", prog_id, "shell", verb, "command")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, label)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, verb_cmd_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)


def _register_extension(
    spec: ExtensionSpec,
    install_dir: Path,
    open_command: str,
    shell_verbs: dict[str, tuple[str, str]] | None = None,
) -> None:
    ext_key = _reg_path("Software", "Classes", spec.ext)
    prog_key = _reg_path("Software", "Classes", spec.prog_id)
    open_key = _reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command")

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, ext_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, spec.prog_id)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, prog_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, spec.description)

    _set_extension_type_icon(spec, install_dir)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, open_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, open_command)

    for verb, (label, command) in (shell_verbs or {}).items():
        _register_shell_verb(spec.prog_id, verb, label, command)

    _disable_thumbnail_type_overlay(spec)


def _bundle_source_dir(project_root: Path) -> Path:
    """Prefer a PyInstaller output folder over the bare project root."""
    for candidate in (
        project_root / "dist" / "YTDPreviewer",
        project_root / "dist" / "release",
        app_dir(),
    ):
        if (candidate / "YTDPreviewer.exe").is_file():
            return candidate
    return app_dir()


def _is_locked_os_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (5, 32):
        return True
    return False


def _stop_running_app(install_dir: Path, *, except_pid: int | None = None) -> None:
    """Stop tray/viewer processes so the install dir can be updated."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if except_pid is None:
        try:
            subprocess.run(
                ["taskkill", "/IM", f"{APP_NAME}.exe", "/F", "/T"],
                capture_output=True,
                creationflags=flags,
            )
        except OSError:
            pass
    else:
        try:
            subprocess.run(
                [
                    "taskkill",
                    "/FI",
                    f"PID ne {except_pid}",
                    "/IM",
                    f"{APP_NAME}.exe",
                    "/F",
                    "/T",
                ],
                capture_output=True,
                creationflags=flags,
            )
        except OSError:
            pass
    install = str(install_dir.resolve())
    if install:
        esc = install.replace("'", "''")
        pid_filter = ""
        if except_pid is not None:
            pid_filter = f" -and $_.ProcessId -ne {except_pid}"
        ps = (
            "Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
            f"Where-Object {{ $_.ExecutablePath -and "
            f"$_.ExecutablePath.StartsWith('{esc}', "
            f"[System.StringComparison]::OrdinalIgnoreCase){pid_filter} }} | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps],
                capture_output=True,
                timeout=30,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    time.sleep(0.8)


def _explorer_is_running() -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq explorer.exe", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=flags,
        )
        return "explorer.exe" in (proc.stdout or "").lower()
    except (OSError, subprocess.TimeoutExpired):
        return False


def _wait_explorer_stopped(*, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _explorer_is_running():
            return
        time.sleep(0.25)


def _stop_explorer() -> None:
    if not _explorer_is_running():
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.run(
            ["taskkill", "/f", "/im", "explorer.exe"],
            capture_output=True,
            timeout=15,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    _wait_explorer_stopped()
    time.sleep(1.2)


def _start_explorer() -> None:
    """Start explorer.exe — CREATE_NO_WINDOW hides the desktop shell."""
    explorer = Path(os.environ.get("WINDIR", r"C:\Windows")) / "explorer.exe"
    if not explorer.is_file():
        return
    try:
        subprocess.Popen([str(explorer)], cwd=str(explorer.parent), close_fds=True)
        return
    except OSError:
        pass
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "open", str(explorer), None, None, 1)
    except OSError:
        pass


def launch_background_app(install_dir: Path | None = None) -> bool:
    """Start YTDPreviewer tray; ShellExecute avoids launching elevated from setup."""
    target = (install_dir or default_install_dir()).resolve()
    exe = target / "YTDPreviewer.exe"
    if not exe.is_file():
        return False
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "open", str(exe), "--background", str(target), 0
        )
        if rc > 32:
            return True
    except OSError:
        pass
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    detached = getattr(subprocess, "DETACHED_PROCESS", 0)
    try:
        subprocess.Popen(
            [str(exe), "--background"],
            cwd=str(target),
            creationflags=flags | detached,
            close_fds=True,
        )
        return True
    except OSError:
        return False


def _programdata_install_dir() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "YTDPreviewer"


def _thumbnail_install_dir(dll_path_or_dir: Path) -> Path:
    """_ensure_thumbnail_dll returns a .dll path; SharpShell needs the install folder."""
    resolved = dll_path_or_dir.resolve()
    if resolved.suffix.lower() == ".dll":
        return resolved.parent
    return resolved


def _find_registershell_exe(install_dir: Path, project_root: Path) -> Path | None:
    for base in (install_dir, project_root, project_root / "shell" / "RegisterShell" / "bin" / "Release" / "net48"):
        candidate = base / "RegisterShell.exe"
        if candidate.is_file():
            return candidate
    return None


def _register_sharpshell_explorer(dll_path_or_dir: Path, project_root: Path) -> bool:
    """Register thumbnail handler via SharpShell (works in Explorer; manual mscoree does not)."""
    install_dir = _thumbnail_install_dir(dll_path_or_dir)
    install_dir.mkdir(parents=True, exist_ok=True)

    reg_built = project_root / "shell" / "RegisterShell" / "bin" / "Release" / "net48"
    for name in ("RegisterShell.exe", "YtdThumbnail.dll", "SharpShell.dll"):
        src = reg_built / name
        if src.is_file():
            try:
                shutil.copy2(src, install_dir / name)
            except OSError:
                pass

    reg_exe = _find_registershell_exe(install_dir, project_root)
    if reg_exe is None:
        print("WARNING: RegisterShell.exe not found in install package.", flush=True)
        return False

    for name in ("YtdThumbnail.dll", "SharpShell.dll"):
        src = install_dir / name
        if not src.is_file():
            src = reg_exe.parent / name
        if src.is_file() and src.parent.resolve() != install_dir.resolve():
            try:
                shutil.copy2(src, install_dir / name)
            except OSError:
                pass

    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.run(
            [str(reg_exe), "install"],
            cwd=str(install_dir),
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=flags,
        )
        if proc.stdout:
            print(proc.stdout.strip(), flush=True)
        if proc.returncode != 0:
            if proc.stderr:
                print(proc.stderr.strip(), flush=True)
            return False
        return _com_clsid_registered_hklm(YTD_THUMB_CLSID)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"WARNING: RegisterShell failed: {exc}", flush=True)
        return False


def _ensure_thumbnail_dll(
    install_dir: Path,
    source_dir: Path,
    project_root: Path,
    *,
    shell_admin: bool = False,
) -> Path | None:
    """Copy YtdThumbnail.dll to a stable path; return path used for COM CodeBase."""
    candidates = _thumbnail_dll_candidates(source_dir, project_root)
    if not candidates:
        return None

    src = candidates[0]
    install_dir.mkdir(parents=True, exist_ok=True)
    primary = install_dir / "YtdThumbnail.dll"

    def _try_copy(dst: Path) -> bool:
        try:
            _copy2_retry(src, dst)
            return True
        except OSError:
            return False

    if _try_copy(primary):
        return primary

    staging = install_dir / "YtdThumbnail_new.dll"
    if _try_copy(staging):
        try:
            os.replace(staging, primary)
            return primary
        except OSError:
            pass

    if shell_admin:
        _stop_explorer()
        if _try_copy(primary):
            _start_explorer()
            return primary

        pd_dir = _programdata_install_dir()
        pd_dir.mkdir(parents=True, exist_ok=True)
        pd_dll = pd_dir / "YtdThumbnail.dll"
        if _try_copy(pd_dll):
            print(f"NOTE: DLL installed to {pd_dll} (Explorer had locked %LocalAppData% copy).")
            _start_explorer()
            return pd_dll
        _start_explorer()

    print(f"WARNING: Could not copy DLL to {install_dir} (file locked?).")
    print(f"  Using build output for COM registration: {src}")
    return src.resolve()


def _copy2_retry(src: Path, dst: Path, *, attempts: int = 10, delay: float = 0.5) -> None:
    last_err: OSError | None = None
    parent = dst.parent
    for attempt in range(attempts):
        try:
            shutil.copy2(src, dst)
            return
        except OSError as exc:
            if not _is_locked_os_error(exc):
                raise
            last_err = exc
            if attempt == 0:
                _stop_running_app(parent)
            time.sleep(delay)
    if last_err is not None:
        raise last_err


def _replace_tree(src: Path, dst: Path) -> None:
    """Replace a directory tree; use staging so a failed delete does not corrupt the install."""
    parent = dst.parent
    staging = parent / f"{dst.name}.new"
    backup = parent / f"{dst.name}.old"

    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(src, staging)

    if not dst.exists():
        os.replace(staging, dst)
        return

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)

    last_err: OSError | None = None
    for attempt in range(10):
        try:
            os.replace(dst, backup)
            last_err = None
            break
        except OSError as exc:
            if not _is_locked_os_error(exc):
                raise
            last_err = exc
            if attempt == 0:
                _stop_running_app(parent)
            time.sleep(0.5)
    else:
        try:
            shutil.rmtree(dst)
            last_err = None
        except OSError as exc:
            last_err = exc

    if last_err is not None:
        shutil.rmtree(staging, ignore_errors=True)
        raise PermissionError(
            f"Не удалось обновить «{dst.name}»: файлы заняты другим процессом. "
            "Закройте YTD Previewer, дождитесь окончания установки и повторите."
        ) from last_err

    try:
        os.replace(staging, dst)
    except OSError:
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        os.replace(staging, dst)

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


_INSTALL_STAGING_SUFFIX = ".__staging"
_INSTALL_LEGACY_SUFFIX = ".__legacy"


def _robocopy_tree(src: Path, dst: Path) -> None:
    """Mirror *src* into *dst* (Windows). Exit codes 0–7 are success."""
    dst.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [
            "robocopy",
            str(src),
            str(dst),
            "/E",
            "/COPY:DAT",
            "/R:4",
            "/W:1",
            "/NFL",
            "/NDL",
            "/NJH",
            "/NJS",
            "/NC",
            "/NS",
        ],
        capture_output=True,
        text=True,
        timeout=600,
        creationflags=flags,
    )
    if proc.returncode >= 8:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise OSError(f"robocopy: код {proc.returncode}" + (f" — {detail}" if detail else ""))


def _schedule_delete_on_reboot(path: Path) -> None:
    try:
        ctypes.windll.kernel32.MoveFileExW(str(path), None, 4)
    except OSError:
        pass


def _release_install_locks(
    install_dir: Path,
    *,
    except_pid: int | None = None,
) -> None:
    _stop_running_app(install_dir, except_pid=except_pid)
    _stop_explorer()
    _stop_shell_preview_hosts()


def _stop_shell_preview_hosts() -> None:
    """Stop disposable Windows hosts that may keep the thumbnail DLL loaded."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    for image_name in (
        "dllhost.exe",
        "prevhost.exe",
        "DataExchangeHost.exe",
        "SearchFilterHost.exe",
        "SearchProtocolHost.exe",
    ):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", image_name],
                capture_output=True,
                timeout=15,
                creationflags=flags,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    time.sleep(0.8)


def _materialize_payload(source_dir: Path, dest_dir: Path) -> None:
    """Copy a full app tree into *dest_dir* (must be empty or new)."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / INSTALL_MARKER).write_text("YTD Previewer\n", encoding="utf-8")
    (dest_dir / "assets").mkdir(exist_ok=True)

    exe_src = source_dir / "YTDPreviewer.exe"
    if exe_src.is_file():
        shutil.copy2(exe_src, dest_dir / "YTDPreviewer.exe")

    internal = source_dir / "_internal"
    if internal.is_dir():
        shutil.copytree(internal, dest_dir / "_internal")

    icon_names = {spec.icon_name for spec in EXTENSIONS} | {"app.ico", "ytd.ico", "ydd.ico", "dds.ico"}
    for icon_name in icon_names:
        src_icon = source_dir / "assets" / icon_name
        if not src_icon.is_file():
            src_icon = assets_dir() / icon_name
        if src_icon.is_file():
            shutil.copy2(src_icon, dest_dir / "assets" / icon_name)

    for shell_name in (
        "YtdThumbnail.dll",
        "SharpShell.dll",
        "RegisterShell.exe",
        YDD_PROPERTY_DLL,
        YDD_PROPERTY_SCHEMA,
    ):
        src_shell = source_dir / shell_name
        if src_shell.is_file():
            shutil.copy2(src_shell, dest_dir / shell_name)


def _promote_staged_install(
    staging: Path,
    install_dir: Path,
    *,
    except_pid: int | None = None,
) -> None:
    """Replace *install_dir* with contents of *staging* (avoids overwriting locked files in place)."""
    if not staging.is_dir():
        raise FileNotFoundError(f"Нет временной папки установки: {staging}")

    _release_install_locks(install_dir, except_pid=except_pid)

    if not install_dir.exists():
        os.replace(staging, install_dir)
        return

    legacy = install_dir.parent / f"{install_dir.name}{_INSTALL_LEGACY_SUFFIX}"
    shutil.rmtree(legacy, ignore_errors=True)

    last_err: OSError | None = None
    for attempt in range(12):
        try:
            if legacy.exists():
                shutil.rmtree(legacy, ignore_errors=True)
            os.replace(install_dir, legacy)
            last_err = None
            break
        except OSError as exc:
            if not _is_locked_os_error(exc):
                raise
            last_err = exc
            _release_install_locks(install_dir, except_pid=except_pid)
            time.sleep(0.8)

    if last_err is not None:
        try:
            _robocopy_tree(staging, install_dir)
            shutil.rmtree(staging, ignore_errors=True)
            _schedule_delete_on_reboot(legacy)
            return
        except OSError as rob_exc:
            shutil.rmtree(staging, ignore_errors=True)
            raise PermissionError(
                "Не удалось заменить папку установки: файлы всё ещё заняты.\n"
                "Закройте YTD Previewer, перезагрузите ПК и запустите установку снова."
            ) from rob_exc

    try:
        os.replace(staging, install_dir)
    except OSError:
        _robocopy_tree(staging, install_dir)
        shutil.rmtree(staging, ignore_errors=True)

    shutil.rmtree(legacy, ignore_errors=True)
    if legacy.exists():
        _schedule_delete_on_reboot(legacy)


def copy_payload(
    source_dir: Path,
    install_dir: Path,
    *,
    except_pid: int | None = None,
) -> None:
    staging = install_dir.parent / f"{install_dir.name}{_INSTALL_STAGING_SUFFIX}"
    shutil.rmtree(staging, ignore_errors=True)
    _materialize_payload(source_dir, staging)
    _promote_staged_install(staging, install_dir, except_pid=except_pid)


def _ensure_bundled_exe(project_root: Path, install_dir: Path) -> Path | None:
    exe = install_dir / "YTDPreviewer.exe"
    if exe.is_file():
        return exe

    candidates = [
        project_root / "dist" / "YTDPreviewer" / "YTDPreviewer.exe",
        project_root / "dist" / "release" / "YTDPreviewer.exe",
        app_dir() / "YTDPreviewer.exe",
    ]
    for candidate in candidates:
        if not candidate.is_file():
            continue
        shutil.copy2(candidate, exe)
        internal_src = candidate.parent / "_internal"
        if internal_src.is_dir():
            dest_internal = install_dir / "_internal"
            if dest_internal.exists():
                shutil.rmtree(dest_internal)
            shutil.copytree(internal_src, dest_internal)
        return exe
    return None


def _write_pyw_launchers(install_dir: Path, project_root: Path) -> tuple[Path, Path]:
    root = str(project_root.resolve()).replace("\\", "\\\\")
    tray = install_dir / "tray.pyw"
    opener = install_dir / "open.pyw"
    tray.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "",
                f'ROOT = r"{root}"',
                "os.chdir(ROOT)",
                "if ROOT not in sys.path:",
                "    sys.path.insert(0, ROOT)",
                "",
                "from ytdpreviewer.background import run_background",
                "",
                'if __name__ == "__main__":',
                "    run_background()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    opener.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "",
                f'ROOT = r"{root}"',
                "os.chdir(ROOT)",
                "if ROOT not in sys.path:",
                "    sys.path.insert(0, ROOT)",
                "",
                "from ytdpreviewer.main import main",
                "",
                'if __name__ == "__main__":',
                "    if len(sys.argv) < 2:",
                "        raise SystemExit(1)",
                '    sys.argv = ["ytdpreviewer.main", sys.argv[1]]',
                "    main()",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return tray, opener


def _register_system_file_verb(ext: str, verb: str, label: str, command: str) -> None:
    base = _reg_path("Software", "Classes", "SystemFileAssociations", ext, "shell", verb)
    cmd_key = _reg_path("Software", "Classes", "SystemFileAssociations", ext, "shell", verb, "command")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, label)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)


def _register_directory_warm_verb(command: str) -> None:
    """Context menu: parallel pre-render of .ytd thumbnails in a folder."""
    label = "Прогрузить превью YTD (параллельно)"
    for suffix in ("Directory", r"Directory\Background"):
        base = _reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs")
        cmd_key = _reg_path("Software", "Classes", suffix, "shell", "warmytdthumbs", "command")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, label)
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, cmd_key) as key:
            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, command)


def _unregister_system_file_verbs(ext: str, verb: str) -> None:
    _delete_tree(_reg_path("Software", "Classes", "SystemFileAssociations", ext, "shell", verb, "command"))
    _delete_tree(_reg_path("Software", "Classes", "SystemFileAssociations", ext, "shell", verb))


def _write_export_pyw(install_dir: Path, project_root: Path, *, dev: bool = False) -> Path:
    root = str(project_root.resolve()).replace("\\", "\\\\")
    install = str(install_dir.resolve()).replace("\\", "\\\\")
    use_source = "True" if dev else "False"
    export_pyw = install_dir / "export.pyw"
    export_pyw.write_text(
        "\n".join(
            [
                "import os",
                "import subprocess",
                "import sys",
                "from pathlib import Path",
                "",
                f'INSTALL = Path(r"{install}")',
                f'ROOT = Path(r"{root}")',
                f"USE_SOURCE = {use_source}",
                "",
                "FLAG_MAP = {",
                '    "ytd-png": "--export-ytd-png",',
                '    "ydd-obj": "--export-ydd-obj",',
                '    "ydd-textures": "--export-ydd-textures",',
                '    "png-ytd": "--build-ytd-from-png",',
                "}",
                "",
                'if __name__ == "__main__":',
                "    if len(sys.argv) < 3:",
                "        raise SystemExit(1)",
                "    mode = sys.argv[1]",
                "    targets = sys.argv[2:]",
                "    flag = FLAG_MAP.get(mode)",
                "    if flag is None:",
                "        raise SystemExit(1)",
                "    exe = INSTALL / 'YTDPreviewer.exe'",
                "    if not USE_SOURCE and exe.is_file():",
                "        raise SystemExit(subprocess.call([str(exe), flag, *targets]))",
                "    os.chdir(ROOT)",
                "    if str(ROOT) not in sys.path:",
                "        sys.path.insert(0, str(ROOT))",
                "    from ytdpreviewer.export_main import run_export_cli",
                "    raise SystemExit(0 if run_export_cli([flag, *targets]) else 1)",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return export_pyw


def _warm_thumbs_command(
    install_dir: Path,
    project_root: Path,
    pythonw: Path,
    *,
    dev: bool = False,
) -> str:
    exe = install_dir / "YTDPreviewer.exe"
    if not dev and exe.is_file():
        return f'"{exe}" --warm-ytd-thumbs "%V"'
    root = str(project_root.resolve())
    return (
        f'"{pythonw}" -c "import sys; sys.path.insert(0, r\'{root}\'); '
        f"from ytdpreviewer.thumb_warm import main; raise SystemExit(main([r'%V']))\""
    )


def _launch_commands(
    install_dir: Path,
    project_root: Path,
    pythonw: Path,
    *,
    dev: bool = False,
) -> tuple[str, str, str, str, str, str]:
    exe = install_dir / "YTDPreviewer.exe"
    if not dev and not exe.is_file():
        ensured = _ensure_bundled_exe(project_root, install_dir)
        if ensured is not None:
            exe = ensured

    if exe.name.lower() == "setup.exe":
        exe = install_dir / "YTDPreviewer.exe"

    if not dev and exe.is_file():
        open_cmd = f'"{exe}" "%1"'
        autostart_cmd = f'"{exe}" --background'
        export_png_cmd = f'"{exe}" --export-ytd-png "%1"'
        export_obj_cmd = f'"{exe}" --export-ydd-obj "%1"'
        export_ydd_tex_cmd = f'"{exe}" --export-ydd-textures "%1"'
        build_ytd_cmd = f'"{exe}" --build-ytd-from-png "%1"'
        return open_cmd, autostart_cmd, export_png_cmd, export_obj_cmd, export_ydd_tex_cmd, build_ytd_cmd

    tray, opener = _write_pyw_launchers(install_dir, project_root)
    export_pyw = install_dir / "export.pyw"
    open_cmd = f'"{pythonw}" "{opener}" "%1"'
    autostart_cmd = f'"{pythonw}" "{tray}"'
    export_png_cmd = f'"{pythonw}" "{export_pyw}" ytd-png "%1"'
    export_obj_cmd = f'"{pythonw}" "{export_pyw}" ydd-obj "%1"'
    export_ydd_tex_cmd = f'"{pythonw}" "{export_pyw}" ydd-textures "%1"'
    build_ytd_cmd = f'"{pythonw}" "{export_pyw}" png-ytd "%1"'
    return open_cmd, autostart_cmd, export_png_cmd, export_obj_cmd, export_ydd_tex_cmd, build_ytd_cmd


def _resolve_project_root(source: Path, *, dev: bool) -> Path:
    if dev:
        return Path(__file__).resolve().parent.parent
    return source


def install_with_progress(
    install_dir: Path | None = None,
    source_dir: Path | None = None,
    *,
    dev: bool = False,
    shell_admin: bool = False,
    explorer_thumbnails: bool | None = None,
    on_progress: ProgressCallback | None = None,
    except_pid: int | None = None,
) -> Path:
    def step(percent: int, message: str) -> None:
        if on_progress is not None:
            on_progress(percent, message)

    target = (install_dir or default_install_dir()).resolve()
    if not dev:
        target = validate_public_install_dir(target)
    dev_root = Path(__file__).resolve().parent.parent
    source = (source_dir or _bundle_source_dir(dev_root)).resolve()
    project_root = _resolve_project_root(source, dev=dev)
    enable_thumbs = explorer_thumbnails if explorer_thumbnails is not None else shell_admin

    step(5, "Остановка старых процессов...")
    _stop_running_app(target, except_pid=except_pid)

    step(10, "Остановка проводника...")
    _stop_explorer()

    if (target / "YtdThumbnail.dll").is_file() or (target / "RegisterShell.exe").is_file():
        step(12, "Снятие старого обработчика превью...")
        _unregister_sharpshell(target, project_root)
        _unregister_ydd_property_handler(target)
        time.sleep(0.6)

    step(15, "Копирование файлов программы...")
    copy_payload(source, target, except_pid=except_pid)

    step(18, "Запуск проводника...")
    _start_explorer()

    if not dev and not (target / "YTDPreviewer.exe").is_file():
        raise FileNotFoundError(
            f"В папке установки нет YTDPreviewer.exe.\n"
            f"Пересоберите проект (build.bat) и установите снова из dist\\setup\\setup.exe."
        )

    step(22, "Исправление старых ассоциаций...")
    try:
        repair_installation(target, re_register=False, register_thumbnails=False)
    except FileNotFoundError:
        pass

    step(28, "Настройка компонентов...")
    _write_export_pyw(target, project_root, dev=dev)
    thumb_root = project_root if dev else target
    _write_thumbnail_pyw(target, thumb_root, dev=dev)
    _write_thumbnail_launcher(target)

    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        pythonw = Path(sys.executable)

    open_cmd, autostart_cmd, export_png_cmd, export_obj_cmd, export_ydd_tex_cmd, build_ytd_cmd = (
        _launch_commands(target, project_root, pythonw, dev=dev)
    )
    if dev and (project_root / "ytdpreviewer").is_dir():
        _write_project_launchers(project_root, autostart_cmd, open_cmd)

    step(42, "Ассоциации .ytd и .ydd...")
    _purge_setup_exe_handlers()
    _force_open_handlers(target)
    for spec in EXTENSIONS:
        shell_verbs: dict[str, tuple[str, str]] = {}
        if spec.ext == ".ytd":
            shell_verbs["exportpng"] = ("Экспортировать в PNG", export_png_cmd)
        elif spec.ext == ".ydd":
            shell_verbs["exportobj"] = ("Экспортировать в OBJ", export_obj_cmd)
            shell_verbs["exporttex"] = ("Экспортировать вложенные текстуры", export_ydd_tex_cmd)
        if "setup.exe" in open_cmd.lower():
            raise RuntimeError(
                "Неверная команда открытия: setup.exe не может быть обработчиком .ytd/.ydd"
            )
        _register_extension(spec, target, open_cmd, shell_verbs)
        _apply_ftype_assoc(spec, open_cmd)

    step(55, "Контекстное меню...")
    _register_system_file_verb(".png", "buildytd", "Собрать в YTD", build_ytd_cmd)
    warm_cmd = _warm_thumbs_command(target, project_root, pythonw, dev=dev)
    _register_directory_warm_verb(warm_cmd)

    if enable_thumbs:
        step(68, "Превью .ytd в проводнике...")
        _register_ytd_thumbnail(target, source, project_root, dev=dev, shell_admin=shell_admin)
        properties_ok = _register_ydd_property_handler(target)
        if not dev and shell_admin and not properties_ok:
            raise RuntimeError(
                "Не удалось зарегистрировать столбец «Текстуры» для .ydd."
            )
        _seed_thumb_roots(project_root, target)
    else:
        step(68, "Превью в проводнике отключено...")
        _unregister_ydd_thumbnail_shellex(shell_admin=shell_admin and _is_admin())
        _unregister_ydd_property_handler(target)

    step(82, "Автозапуск...")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_cmd)
    if not dev:
        _create_start_menu_shortcut(target)

    step(92, "Обновление оболочки Windows...")
    _notify_shell()

    if enable_thumbs and shell_admin and _is_admin():
        step(96, "Очистка кэша миниатюр...")
        _clear_thumbnail_caches(target)
        step(98, "Перезапуск проводника...")
        _restart_explorer()
    else:
        step(98, "Запуск проводника...")
        _ensure_explorer_running()

    step(99, "Запуск YTD Previewer...")
    launch_background_app(target)

    step(100, "Готово")
    return target


def register_explorer_thumbnails_admin(install_dir: Path | None = None) -> bool:
    """HKLM + SharpShell (requires Administrator). Called from setup.exe /shell-install."""
    target = (install_dir or default_install_dir()).resolve()
    step = lambda m: print(m, flush=True)
    step("Регистрация превью .ytd / .ydd (администратор)...")
    _stop_running_app(target)
    _stop_explorer()
    ok = _register_ytd_thumbnail(target, target, target, dev=False, shell_admin=True)
    _apply_thumbnail_com_extras(YTD_THUMB_CLSID)
    _clear_thumbnail_caches(target)
    _notify_shell()
    _restart_explorer()
    return ok and _com_clsid_registered_hklm(YTD_THUMB_CLSID)


def request_admin_explorer_thumbnails(install_dir: Path) -> bool:
    """UAC: RegisterShell.exe (preferred) or setup.exe /shell-install — no installer UI."""
    target = install_dir.resolve()
    reg_exe = target / "RegisterShell.exe"
    if reg_exe.is_file() and (target / "YtdThumbnail.dll").is_file():
        try:
            rc = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", str(reg_exe), "install", str(target), 1
            )
            if rc > 32:
                return True
        except OSError:
            pass

    setup_exe = Path(sys.executable)
    if not getattr(sys, "frozen", False):
        candidate = Path(__file__).resolve().parent.parent / "dist" / "setup" / "setup.exe"
        if candidate.is_file():
            setup_exe = candidate
    params = f'/shell-install "{target}"'
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(setup_exe), params, str(setup_exe.parent), 0
        )
        return rc > 32
    except OSError:
        return False


def install(
    install_dir: Path | None = None,
    source_dir: Path | None = None,
    *,
    dev: bool = False,
    shell_admin: bool = False,
    on_progress: ProgressCallback | None = None,
) -> Path:
    return install_with_progress(
        install_dir,
        source_dir,
        dev=dev,
        shell_admin=shell_admin,
        on_progress=on_progress,
    )


def uninstall_with_progress(
    install_dir: Path | None = None,
    *,
    clear_caches: bool = True,
    restart_explorer: bool = True,
    on_progress: ProgressCallback | None = None,
) -> None:
    def step(percent: int, message: str) -> None:
        if on_progress is not None:
            on_progress(percent, message)

    target = (install_dir or default_install_dir()).resolve()
    project_root = Path(__file__).resolve().parent.parent

    step(10, "Остановка YTD Previewer...")
    _stop_running_app(target)

    step(25, "Автозапуск и ассоциации...")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass
    _remove_start_menu_shortcut()

    for spec in EXTENSIONS:
        for verb in ("exportpng", "exportobj", "exporttex"):
            _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", verb, "command"))
            _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", verb))
        _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", "open", "command"))
        _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell", "open"))
        _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "shell"))
        _delete_tree(_reg_path("Software", "Classes", spec.prog_id, "DefaultIcon"))
        _delete_tree(_reg_path("Software", "Classes", spec.prog_id))
        _delete_tree(_reg_path("Software", "Classes", spec.ext))

    step(45, "Контекстное меню...")
    _unregister_system_file_verbs(".png", "buildytd")
    _unregister_directory_warm_verb()

    step(60, "Превью в проводнике...")
    _unregister_ydd_property_handler(target)
    _unregister_ytd_thumbnail(target, project_root)

    if clear_caches:
        step(78, "Очистка кэша миниатюр...")
        _clear_thumbnail_caches(target)

    step(90, "Обновление Windows...")
    _notify_shell()

    if restart_explorer:
        step(98, "Перезапуск проводника...")
        _restart_explorer()

    step(100, "Удалено")


def _write_project_launchers(project_root: Path, autostart_cmd: str, open_cmd: str) -> None:
    bg_cmd = _vbs_path(autostart_cmd)
    (project_root / "launch_background.vbs").write_text(
        "\n".join(
            [
                'Set sh = CreateObject("Wscript.Shell")',
                f'sh.Run "{bg_cmd}", 0, False',
                "",
            ]
        ),
        encoding="utf-8",
    )

    opener = open_cmd.rsplit(' "%1"', 1)[0]
    open_prefix = _vbs_path(opener)
    (project_root / "launch_open.vbs").write_text(
        "\n".join(
            [
                "Set args = WScript.Arguments",
                "If args.Count = 0 Then WScript.Quit 1",
                "path = args(0)",
                'Set sh = CreateObject("Wscript.Shell")',
                f'cmd = "{open_prefix} "" & Chr(34) & path & Chr(34)',
                "sh.Run cmd, 1, False",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _vbs_path(value: Path | str) -> str:
    return str(value).replace('"', '""')


def uninstall(
    install_dir: Path | None = None,
    *,
    clear_caches: bool = True,
    restart_explorer: bool = True,
    on_progress: ProgressCallback | None = None,
) -> None:
    uninstall_with_progress(
        install_dir,
        clear_caches=clear_caches,
        restart_explorer=restart_explorer,
        on_progress=on_progress,
    )
    target = install_dir or default_install_dir()
    if _shellex_registered(winreg.HKEY_LOCAL_MACHINE, ".ytd") or _com_clsid_registered_hklm(
        YTD_THUMB_CLSID
    ):
        print(
            "ВНИМАНИЕ: превью .ytd всё ещё в реестре HKLM (нужны права администратора).\n"
            "  Запустите: scripts\\uninstall_shell_admin.bat",
            flush=True,
        )


def _print_thumbnail_hint(install_dir: Path, *, shell_admin: bool = False) -> None:
    if not (install_dir / "YtdThumbnail.dll").is_file():
        print("Превью в проводнике: соберите shell\\YtdThumbnail (dotnet build) и переустановите.")
        return
    hkcu_ytd = _shellex_registered(winreg.HKEY_CURRENT_USER, ".ytd", clsid=YTD_THUMB_CLSID)
    hklm_ytd = _shellex_registered(winreg.HKEY_LOCAL_MACHINE, ".ytd", clsid=YTD_THUMB_CLSID)
    hklm_com_ytd = _com_clsid_registered_hklm(YTD_THUMB_CLSID)
    if shell_admin and hklm_ytd and hklm_com_ytd:
        print("Превью .ytd в проводнике: зарегистрировано (HKLM). .ydd — только иконка.")
        print("  Затем: scripts\\refresh_explorer_thumbs.bat")
    elif shell_admin and not hklm_com_ytd:
        print("ОШИБКА: COM не попал в HKLM — превью .ytd в проводнике не заработает.")
        print("  Повторите scripts\\install_shell_admin.bat от имени администратора.")
    elif hkcu_ytd:
        print("Превью .ytd: COM установлен. Для Windows 11 (HKLM) запустите от администратора:")
        print("  scripts\\install_shell_admin.bat")
        print("  затем scripts\\refresh_explorer_thumbs.bat")
    else:
        print("Превью .ytd в проводнике: обработчик не полный — повторите install.bat / install_shell_admin.bat")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        print("Старт удаления YTD Previewer...", flush=True)
        no_restart = "--no-restart-explorer" in sys.argv
        uninstall(restart_explorer=not no_restart)
        print(
            "\nГотово: автозапуск, ассоциации .ytd / .ydd, обработчик превью, кэш миниатюр.\n"
            "Папку %LOCALAPPDATA%\\YTDPreviewer можно удалить вручную.",
            flush=True,
        )
    elif len(sys.argv) > 1 and sys.argv[1].lower() == "shell-install":
        if len(sys.argv) < 3:
            sys.exit(2)
        target = Path(sys.argv[2].strip('"'))
        ok = register_explorer_thumbnails_admin(target)
        sys.exit(0 if ok else 1)
    elif len(sys.argv) > 1 and sys.argv[1] == "shell-uninstall":
        if not _is_admin():
            print("ERROR: shell-uninstall requires Administrator.")
            sys.exit(1)
        uninstall(restart_explorer=True)
        print("Полное удаление превью .ytd (HKLM + SharpShell) выполнено.")
    elif len(sys.argv) > 1 and sys.argv[1] == "repair":
        target = Path(sys.argv[2].strip('"')) if len(sys.argv) > 2 else default_install_dir()
        repair_installation(target, re_register=True, register_thumbnails=False)
        print("Ассоциации исправлены. Для превью в проводнике:", flush=True)
        print("  scripts\\install_shell_admin.bat  (от администратора)", flush=True)
        print("  scripts\\refresh_explorer_thumbs.bat", flush=True)
    elif len(sys.argv) > 1 and sys.argv[1] == "diagnose":
        target = Path(sys.argv[2].strip('"')) if len(sys.argv) > 2 else default_install_dir()
        diagnose_registry(target)
    elif len(sys.argv) > 1 and sys.argv[1] in ("dev", "shell-admin"):
        shell_admin = sys.argv[1] == "shell-admin"
        if shell_admin and not _is_admin():
            print("ERROR: shell-admin requires Administrator (use scripts\\install_shell_admin.bat).")
            sys.exit(1)
        path = install(dev=True, shell_admin=shell_admin)
        label = "Shell (admin)" if shell_admin else "Dev"
        print(f"{label}-установка: {path}")
        if (path / "YTDPreviewer.exe").is_file():
            print("Автозапуск: YTDPreviewer.exe (имя и иконка в диспетчере задач).")
        else:
            print("Автозапуск: pythonw + tray.pyw (без Windows Script Host).")
            print("Для имени YTDPreviewer в диспетчере задач соберите build.bat.")
        print("Иконки .ytd и .ydd обновлены.")
        print("Контекстное меню .png: «Собрать в YTD».")
        _print_thumbnail_hint(path, shell_admin=shell_admin)
    else:
        path = install()
        print(f"Установлено в: {path}")
        print("Иконки .ytd и .ydd обновлены.")
        _print_thumbnail_hint(path)
