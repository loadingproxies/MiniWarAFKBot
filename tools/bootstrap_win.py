"""Windows launcher prerequisites — unblock downloaded DLLs, install .NET / WebView2.

Runs before pywebview/pythonnet import (those crash if .NET is missing or DLLs
are blocked). Bot worker (--bot-worker) does not use this module.
"""
from __future__ import annotations

import os
import subprocess
import sys

_DOTNET_WINGET = "Microsoft.DotNet.DesktopRuntime.8"
_WEBVIEW2_WINGET = "Microsoft.EdgeWebView2Runtime"
_DOTNET_URL = "https://dotnet.microsoft.com/download/dotnet/8.0"
_WEBVIEW2_URL = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"


def app_root() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _message(title: str, text: str, error: bool = False) -> None:
    try:
        import ctypes
        flags = 0x10 if error else 0x40  # MB_ICONERROR / MB_ICONINFORMATION
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        print(text, file=sys.stderr)


def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess | None:
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=flags,
        )
    except Exception:
        return None


def unblock_folder(root: str | None = None) -> None:
    """Clear Windows Zone.Identifier on extracted files (GitHub zip downloads)."""
    root = root or app_root()
    ps = (
        f"$p = '{root.replace(chr(39), chr(39)+chr(39))}'; "
        "Get-ChildItem -LiteralPath $p -Recurse -ErrorAction SilentlyContinue | "
        "Unblock-File -ErrorAction SilentlyContinue"
    )
    _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=120)


def _reg_key_exists(path: str) -> bool:
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def has_dotnet_desktop_8() -> bool:
    if _reg_key_exists(r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx"
                       r"\Microsoft.WindowsDesktop.App"):
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\dotnet\Setup\InstalledVersions\x64\sharedfx"
                r"\Microsoft.WindowsDesktop.App",
            )
            i = 0
            while True:
                try:
                    ver = winreg.EnumKey(key, i)
                    if ver.startswith("8."):
                        winreg.CloseKey(key)
                        return True
                    i += 1
                except OSError:
                    break
            winreg.CloseKey(key)
        except OSError:
            pass
    proc = _run(["dotnet", "--list-runtimes"], timeout=15)
    if proc and proc.returncode == 0 and proc.stdout:
        return "Microsoft.WindowsDesktop.App 8." in proc.stdout
    return False


def has_webview2() -> bool:
    if _reg_key_exists(
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients"
            r"\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"):
        return True
    for sub in (
        r"Microsoft\EdgeWebView\Application",
        r"Microsoft\EdgeCore\Application",
    ):
        base = os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), sub)
        if os.path.isdir(base) and os.listdir(base):
            return True
    return False


def _winget_available() -> bool:
    proc = _run(["winget", "--version"], timeout=10)
    return bool(proc and proc.returncode == 0)


def _winget_install(package_id: str) -> bool:
    proc = _run([
        "winget", "install", "--id", package_id, "-e",
        "--accept-package-agreements", "--accept-source-agreements",
        "--disable-interactivity",
    ], timeout=600)
    return bool(proc and proc.returncode == 0)


def _open_urls(*urls: str) -> None:
    import webbrowser
    for url in urls:
        try:
            webbrowser.open(url)
        except Exception:
            pass


def ensure_launcher_prerequisites() -> None:
    """Unblock files and install missing Windows runtimes when possible."""
    if sys.platform != "win32":
        return

    root = app_root()
    unblock_folder(root)

    need_dotnet = not has_dotnet_desktop_8()
    need_webview = not has_webview2()
    if not need_dotnet and not need_webview:
        return

    if _winget_available():
        if need_dotnet:
            _winget_install(_DOTNET_WINGET)
        if need_webview:
            _winget_install(_WEBVIEW2_WINGET)
        if has_dotnet_desktop_8() and has_webview2():
            return

    still = []
    if not has_dotnet_desktop_8():
        still.append(".NET 8 Desktop Runtime (x64)")
    if not has_webview2():
        still.append("WebView2 Runtime")

    _open_urls(_DOTNET_URL, _WEBVIEW2_URL)
    _message(
        "MiniWar AFK Bot — setup required",
        "Missing: " + ", ".join(still) + ".\n\n"
        "Your browser will open the download pages.\n"
        "Install both (Desktop Runtime x64, not SDK), restart your PC, "
        "then run MiniWarAFKBot again.\n\n"
        "If you already installed them, right-click the ZIP → Properties → "
        "Unblock, extract again, and retry.",
        error=True,
    )
    sys.exit(1)
