"""Check for updates and apply release zips from a hosted manifest (update.json)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from urllib.request import urlopen

from src import appconfig

VERSION_PATH = os.path.join(appconfig.ROOT, "VERSION")

# Never overwrite user data when applying a source zip update.
_SKIP_TOP = {
    "config.json", "logs", "events", "debug", "timed", "venv", ".venv",
    "__pycache__", ".git", ".cursor",
}


def read_local_version() -> str:
    try:
        with open(VERSION_PATH, encoding="utf-8") as f:
            v = f.read().strip()
            return v or "0.0.0"
    except OSError:
        return "0.0.0"


def _parse_version(v: str) -> tuple[int, int, int]:
    nums = [int(x) for x in re.findall(r"\d+", v or "")]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums[:3])


def is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


def _fetch_json(url: str, timeout: float = 12.0) -> dict:
    with urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(manifest_url: str) -> dict:
    """Compare VERSION file to remote update.json."""
    local = read_local_version()
    if not manifest_url:
        return {
            "ok": False,
            "local_version": local,
            "error": "No update manifest URL configured",
        }
    try:
        manifest = _fetch_json(manifest_url.strip())
        remote = str(manifest.get("version") or "").strip()
        if not remote:
            return {"ok": False, "local_version": local, "error": "Manifest missing version"}
        return {
            "ok": True,
            "local_version": local,
            "remote_version": remote,
            "update_available": is_newer(remote, local),
            "download_url": str(manifest.get("url") or "").strip(),
            "page_url": str(manifest.get("page_url") or manifest.get("url") or "").strip(),
            "notes": str(manifest.get("notes") or "").strip(),
        }
    except Exception as e:
        return {"ok": False, "local_version": local, "error": str(e)}


def _download(url: str, dest: str, timeout: float = 120.0) -> None:
    with urlopen(url, timeout=timeout) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out)


def _zip_root_dir(zf: zipfile.ZipFile) -> str | None:
    """If zip has a single top-level folder, return its name."""
    tops = set()
    for name in zf.namelist():
        part = name.split("/")[0].split("\\")[0]
        if part:
            tops.add(part)
    return tops.pop() if len(tops) == 1 else None


def apply_release_zip(download_url: str) -> dict:
    """Download a release zip and merge into the install folder."""
    if not download_url:
        return {"ok": False, "error": "No download URL"}
    tmp = tempfile.mkdtemp(prefix="minwar_update_")
    zip_path = os.path.join(tmp, "release.zip")
    try:
        _download(download_url, zip_path)
        with zipfile.ZipFile(zip_path) as zf:
            root = appconfig.ROOT
            prefix = _zip_root_dir(zf)
            for info in zf.infolist():
                if info.is_dir():
                    continue
                rel = info.filename.replace("\\", "/")
                if prefix and rel.startswith(prefix + "/"):
                    rel = rel[len(prefix) + 1:]
                elif prefix and rel == prefix:
                    continue
                if not rel or rel.endswith("/"):
                    continue
                top = rel.split("/")[0]
                if top in _SKIP_TOP:
                    continue
                dest = os.path.join(root, rel)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        return {"ok": True, "version": read_local_version()}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def restart_launcher() -> None:
    """Start a fresh launcher process and exit this one."""
    root = appconfig.ROOT
    exe = sys.executable
    launcher = os.path.join(root, "tools", "launcher.py")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if getattr(sys, "frozen", False):
        subprocess.Popen([exe], cwd=root, creationflags=flags)
    elif os.name == "nt" and os.path.isfile(os.path.join(root, "launcher.bat")):
        subprocess.Popen(["cmd", "/c", "start", "", "launcher.bat"], cwd=root, creationflags=flags)
    else:
        subprocess.Popen([exe, launcher], cwd=root, creationflags=flags)
    sys.exit(0)
