# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas = [("icon.ico", ".")]
binaries = []
hiddenimports = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "pygame.mixer",
]

ctk_datas, ctk_binaries, ctk_hidden = collect_all("customtkinter")
datas += ctk_datas
binaries += ctk_binaries
hiddenimports += ctk_hidden
hiddenimports += collect_submodules("mutagen")

a = Analysis(
    ["tinytune.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pygame.tests",
        "pygame.examples",
        "pygame.docs",
        "tkinter.test",
        "test",
        "unittest",
        "pytest",
        "pydoc_data",
        "setuptools",
        "pip",
        "wheel",
        "pkg_resources",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TinyTune",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=["icon.ico"],
    version="version_info.txt",
)
