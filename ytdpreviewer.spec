# -*- mode: python ; coding: utf-8 -*-
# pyinstaller ytdpreviewer.spec

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)
assets = [(str(ROOT / "assets"), "assets")]

texfury_datas, texfury_binaries, texfury_hidden = collect_all("texfury")
fivefury_datas, fivefury_binaries, fivefury_hidden = collect_all("fivefury")
a = Analysis(
    [str(ROOT / "ytdpreviewer" / "main.py")],
    pathex=[str(ROOT)],
    binaries=texfury_binaries + fivefury_binaries,
    datas=assets + texfury_datas + fivefury_datas,
    hiddenimports=[
        "PIL._tkinter_finder",
        "pystray._win32",
        "texfury",
        "fivefury.ydd.reader",
        "fivefury.ydr.reader",
        "ytdpreviewer.fivefury_bootstrap",
        "ytdpreviewer.ydd_loader",
        "ytdpreviewer.ydd_viewer",
        "ytdpreviewer.ydd_export",
        "ytdpreviewer.ytd_export",
        "ytdpreviewer.export_main",
        "ytdpreviewer.ytd_texture_preview",
        "pyglet",
        "pyglet.gl",
        "pyglet.gl.glu",
        "pyglet.window.win32",
        "pyglet.canvas.win32",
        *texfury_hidden,
        *fivefury_hidden,
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
    name="YTDPreviewer",
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
    name="YTDPreviewer",
)
