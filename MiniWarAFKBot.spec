# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — run:  pyinstaller MiniWarAFKBot.spec"""
import os

from PyInstaller.utils.hooks import collect_all

root = os.path.abspath(SPECPATH)

# RapidOCR needs default_models.yaml, config.yaml, and optional .onnx files beside the package.
rapidocr_datas, rapidocr_binaries, rapidocr_hidden = collect_all("rapidocr")
ort_datas, ort_binaries, ort_hidden = collect_all("onnxruntime")

a = Analysis(
    [os.path.join(root, "tools", "entry.py")],
    pathex=[root],
    binaries=rapidocr_binaries + ort_binaries,
    datas=[
        (os.path.join(root, "assets"), "assets"),
        (os.path.join(root, "VERSION"), "."),
    ] + rapidocr_datas + ort_datas,
    hiddenimports=[
        "webview",
        "clr_loader",
        "pythonnet",
        "cv2",
        "numpy",
        "mss",
        "PIL",
        "PIL.Image",
        "rapidfuzz",
        "requests",
        "win32api",
        "win32gui",
        "win32con",
        "win32process",
        "src",
        "src.watcher",
        "src.navigator",
        "src.vision",
        "src.inventory",
        "src.parser",
        "src.notify",
        "src.botlogs",
        "src.updater",
        "src.appconfig",
        "src.window",
        "src.capture",
        "src.input_control",
        "src.budget",
        "src.botstatus",
        "src.game_locale",
        "src.botevents",
        "src.shop_tabs",
        "tools.launcher",
        "tools.bootstrap_win",
    ] + rapidocr_hidden + ort_hidden,
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
    name="MiniWarAFKBot",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(root, "assets", "logo.ico") if os.path.isfile(
        os.path.join(root, "assets", "logo.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=["pythonnet", "clr_loader", "Python.Runtime.dll", "ClrLoader.dll"],
    name="MiniWarAFKBot",
)
