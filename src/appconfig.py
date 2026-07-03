"""Load/save config.json (kept in the project root, next to run.py)."""
from __future__ import annotations

import json
import os
import sys


def get_root() -> str:
    """Install folder — next to MiniWarAFKBot.exe when frozen, else repo root."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_bundle_dir() -> str:
    """PyInstaller extract dir (read-only bundled assets)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", get_root())
    return get_root()


ROOT = get_root()
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
