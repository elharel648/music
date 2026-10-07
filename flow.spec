# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec: `pyinstaller flow.spec --noconfirm` -> dist/FLOW.app (macOS) or dist/FLOW/ (Windows)
import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
hidden = collect_submodules("scipy.signal") + collect_submodules("scipy.special") + ["soundfile", "cryptography", "webview"]

a = Analysis(
    ["run_flow.py"],
    pathex=["."],
    binaries=[],
    datas=[("flow/ui/index.html", "flow/ui"), ("LICENSE", ".")],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "pandas"],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="FLOW",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="packaging/flow.icns" if sys.platform == "darwin" else ("packaging/flow.ico" if sys.platform.startswith("win") else None),
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="FLOW")

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="FLOW.app",
        icon="packaging/flow.icns",
        bundle_identifier="com.flowproducer.flow",
        info_plist={
            "CFBundleName": "FLOW",
            "CFBundleDisplayName": "FLOW",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "© 2026 Harel Eliyahu. All rights reserved.",
            "LSMinimumSystemVersion": "12.0",
            "NSRequiresAquaSystemAppearance": False,
        },
    )
