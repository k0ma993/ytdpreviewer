# -*- mode: python ; coding: utf-8 -*-
# pyinstaller setup.spec  (run after ytdpreviewer.spec + build.bat stage)
# onedir layout — avoids "Failed to load Python DLL" in one-file temp (_MEI*).

import sys
from pathlib import Path

ROOT = Path(SPECPATH)
sys.path.insert(0, str(ROOT))
from pyinstaller_tk_datas import tkinter_datas_and_binaries  # noqa: E402
bundle_zip = ROOT / "dist" / "app_bundle.zip"

datas = []
if bundle_zip.is_file():
    datas.append((str(bundle_zip), "."))

_assets = ROOT / "assets"
if (_assets / "app.ico").is_file():
    datas.append((str(_assets / "app.ico"), "assets"))
_logo = _assets / "logo"
if _logo.is_dir():
    datas.append((str(_logo), "assets/logo"))

_tk_datas, _tk_bins = tkinter_datas_and_binaries()
datas += _tk_datas

binaries = list(_tk_bins)
if sys.platform == "win32":
    py_root = Path(sys.base_prefix)
    for dll_name in (
        "python312.dll",
        "python3.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
    ):
        dll_path = py_root / dll_name
        if dll_path.is_file():
            binaries.append((str(dll_path), "."))

a = Analysis(
    [str(ROOT / "installer" / "setup_main.py")],
    pathex=[str(ROOT), str(ROOT / "installer")],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "_tkinter",
        "tkinter",
        "installer.setup_ui",
        "ytdpreviewer",
        "ytdpreviewer.setup_windows",
        "ytdpreviewer.paths",
        "ytdpreviewer.app_icon",
        "ytdpreviewer.ui_theme",
        "ytdpreviewer.thumb_warm",
        "ytdpreviewer.ytd_texture_preview",
        "PIL.ImageTk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="setup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "app.ico") if (ROOT / "assets" / "app.ico").is_file() else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="setup_build",
)
