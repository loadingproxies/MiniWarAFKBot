"""Build MiniWar AFK Bot for distribution (zip and/or Windows exe folder).

Usage (from project root):
  python tools/build_release.py              # source zip only
  python tools/build_release.py --exe        # dist/MiniWarAFKBot/ folder with MiniWarAFKBot.exe
  python tools/build_release.py --exe --obfuscate   # PyArmor on src/ first (pip install pyarmor)

Give users the whole  dist/MiniWarAFKBot/  folder (or zip it).
They run MiniWarAFKBot.exe — config.json lives beside the exe.

Optional obfuscation after exe build:
  pip install pyarmor
  pyarmor gen --pack MiniWarAFKBot.spec -r src tools run.py
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, "MiniWarAFKBot")
SKIP = {
    "logs", "events", "debug", "timed", "dist", "build", ".git", ".venv", "venv",
    "__pycache__", ".cursor", "config.json", "obf_build",
}


def _read_version() -> str:
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        return v if (v := f.read().strip()) else "0.0.0"


def build_zip(version: str) -> str:
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, f"MiniWarAFKBot-v{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP]
            rel_dir = os.path.relpath(dirpath, ROOT)
            if rel_dir == ".":
                rel_dir = ""
            top = rel_dir.split(os.sep)[0] if rel_dir else ""
            if top in SKIP:
                continue
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                rel = os.path.join(rel_dir, name) if rel_dir else name
                if rel.replace("\\", "/").startswith("dist/"):
                    continue
                zf.write(os.path.join(dirpath, name), rel)
    return out


def _run(cmd: list[str], cwd: str | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.check_call(cmd, cwd=cwd or ROOT)


def obfuscate_sources() -> str:
    """Run PyArmor on src/ into obf_build/ (optional). Returns source root for PyInstaller."""
    try:
        import pyarmor  # noqa: F401
    except ImportError:
        raise SystemExit("PyArmor not installed.  pip install pyarmor")

    obf = os.path.join(ROOT, "obf_build")
    if os.path.isdir(obf):
        shutil.rmtree(obf)
    _run([
        sys.executable, "-m", "pyarmor", "gen",
        "-O", obf,
        "-r", "src", "tools", "run.py",
    ])
    return obf


def _ensure_ocr_models() -> None:
    """Cache OCR weights in site-packages so collect_all('rapidocr') bundles them."""
    print("Ensuring OCR models are cached for the build...")
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from src.appconfig import load
    from src.vision import Vision

    Vision(load()).warmup()
    print("OCR models ready.")


def build_exe(obfuscate: bool = False) -> str:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        raise SystemExit("Install PyInstaller:  pip install pyinstaller")

    if obfuscate:
        print("Note: for best results use PyArmor pack with the spec file directly.")
        print("      See: pyarmor gen --pack MiniWarAFKBot.spec -r src tools run.py")
        obfuscate_sources()

    if os.path.isdir(APP_DIR):
        shutil.rmtree(APP_DIR)
    _ensure_ocr_models()
    spec = os.path.join(ROOT, "MiniWarAFKBot.spec")
    _run([sys.executable, "-m", "PyInstaller", "--noconfirm", spec])

    exe = os.path.join(APP_DIR, "MiniWarAFKBot.exe")
    if not os.path.isfile(exe):
        raise SystemExit(f"Build finished but exe missing: {exe}")

    # User-facing files next to the exe (config is created/edited in the GUI)
    assets_dst = os.path.join(APP_DIR, "assets")
    os.makedirs(assets_dst, exist_ok=True)
    for name in ("logo.ico", "logo.png"):
        src = os.path.join(ROOT, "assets", name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(assets_dst, name))

    for name in ("update.json.example", "update.json"):
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(APP_DIR, name))

    # Ship a clean default config (no webhook / personal wishlist)
    cfg_src = os.path.join(ROOT, "config.default.json")
    if not os.path.isfile(cfg_src):
        cfg_src = os.path.join(ROOT, "config.json")
    shutil.copy2(cfg_src, os.path.join(APP_DIR, "config.json"))

    for name in ("VERSION", "README.md", "Start MiniWar Bot.bat"):
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(APP_DIR, name))

    return exe


def zip_app_folder(version: str) -> str:
    """Zip the built exe folder for update.json url."""
    if not os.path.isdir(APP_DIR):
        raise SystemExit("Build exe first")
    out = os.path.join(DIST, f"MiniWarAFKBot-v{version}-win64.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _, filenames in os.walk(APP_DIR):
            for name in filenames:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, DIST)
                zf.write(full, rel)
    return out


def main():
    ap = argparse.ArgumentParser(description="Build MiniWar AFK Bot release")
    ap.add_argument("--exe", action="store_true", help="Build dist/MiniWarAFKBot/ with MiniWarAFKBot.exe")
    ap.add_argument("--obfuscate", action="store_true", help="Run PyArmor on sources before build")
    ap.add_argument("--zip-exe", action="store_true", help="Also zip the exe folder (for update.json)")
    args = ap.parse_args()
    version = _read_version()

    if args.exe:
        epath = build_exe(obfuscate=args.obfuscate)
        print(f"\nBuilt: {epath}")
        print(f"Distribute folder: {APP_DIR}")
        if args.zip_exe:
            z = zip_app_folder(version)
            print(f"Upload zip: {z}")
    else:
        zpath = build_zip(version)
        print(f"Created source zip: {zpath}")

    print("\nBump VERSION before each release.")
    print("Point update.json at the zip URL (see update.json.example).")


if __name__ == "__main__":
    main()
