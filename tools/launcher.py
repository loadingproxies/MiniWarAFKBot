"""MiniWar AFK Bot — launcher GUI (pywebview / WebView2).

Frameless window to pick items to auto-buy, toggle test mode, and run/stop the bot.
While the bot runs, the window shrinks to an always-on-top status overlay (global
F7 = stop). Everything is saved to config.json — `python run.py` works without it.

Run:  python tools/launcher.py   (or launcher.bat)
"""
APP_NAME = "MiniWar AFK Bot"

import os
import sys
import json
import time
import queue
import ctypes
import base64
import threading
import subprocess

try:
    import webview
except ImportError:
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _r = _tk.Tk(); _r.withdraw()
    _mb.showerror(APP_NAME, "pywebview is not installed.\n\nRun:  pip install pywebview")
    raise SystemExit(1)

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import appconfig
from src.shop_tabs import bot_scan_categories

HERE = appconfig.ROOT
LOGO_PATH = os.path.join(appconfig.get_bundle_dir(), "assets", "logo.png")
LOGO_ICO_PATH = os.path.join(appconfig.get_root(), "assets", "logo.ico")
if not os.path.isfile(LOGO_ICO_PATH):
    LOGO_ICO_PATH = os.path.join(appconfig.get_bundle_dir(), "assets", "logo.ico")


def _logo_data_uri() -> str:
    try:
        with open(LOGO_PATH, "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""

CONFIG = appconfig.CONFIG_PATH

APP_SIZE = (880, 680)
OVERLAY_SIZE = (320, 240)

# ---- Win32 window helpers (move / resize / always-on-top the frameless window) ----
_user32 = ctypes.windll.user32
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
from ctypes import wintypes
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_HWND_TOPMOST, _HWND_NOTOPMOST, _SWP_SHOW = -1, -2, 0x0040


def _hwnd():
    return _user32.FindWindowW(None, APP_NAME)


def _screen():
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def _place(topmost, x, y, w, h):
    h_ = _hwnd()
    if h_:
        after = ctypes.c_void_p(_HWND_TOPMOST if topmost else _HWND_NOTOPMOST)
        _user32.SetWindowPos(h_, after, int(x), int(y), int(w), int(h), _SWP_SHOW)


_INSTANCE_MUTEX = None


def _single_instance() -> bool:
    """True if this is the only instance. Uses a named mutex, which Windows
    releases automatically when the process dies — no stale lock files."""
    global _INSTANCE_MUTEX
    ERROR_ALREADY_EXISTS = 183
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, "RobloxShopBot_SingleInstance_v1")
        if not h:
            return True                       # can't create → fail open
        if k32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        _INSTANCE_MUTEX = h                   # keep the handle for the process lifetime
        return True
    except Exception:
        return True

CATS = [
    ("factory", "Factory", "factory", "#8B5CF6"),
    ("houses", "Houses", "house", "#8B5CF6"),
    ("military", "Military", "shield", "#8B5CF6"),
]

# Fallback item list if config.json has no "catalog" section.
CATALOG = {
    "factory": {"Gold Cave": "Epic", "Bank": "Epic", "Research Labs": "Legendary",
                "Diamond Cave": "Legendary", "Uranium Cave": "Mythic", "Nuclear Reactor": "Mythic",
                "Data Center": "Mythic", "Blackhole Generator": "Secret",
                "Antimatter Reactor": "Secret", "Area 51 Lab": "Secret",
                "Quantum Core Generator": "Divine", "Supernova Accelerator": "Divine"},
    "houses": {"Helix Tower": "Legendary", "The Manor": "Mythic", "Hotel": "Mythic",
               "Giant Skyscraper": "Secret", "Double Turbo Tower": "Secret", "Grand Hotel": "Divine"},
    "military": {"Missile Launcher": "Legendary", "Military Hospital": "Legendary",
                 "General's Base": "Mythic", "Air Base": "Mythic", "Artillery Depot": "Mythic",
                 "Rocket Bunker": "Secret", "Mech Station": "Secret", "Spider Base": "Secret",
                 "Air Fortress": "Divine"},
}


def get_catalog(cfg=None):
    """Item list (name -> rarity per category) from config.json's "catalog"
    section, falling back to the bundled CATALOG."""
    try:
        c = (cfg or load_config()).get("catalog")
        if isinstance(c, dict) and c:
            return c
    except Exception:
        pass
    return CATALOG

# SVG icons (lucide-style) by key
ICONS = {
    "factory": '<path d="M2 20h20M4 20V8l5 4V8l5 4V4l6 4v12"/>',
    "house": '<path d="M3 11l9-8 9 8M5 10v10h14V10"/>',
    "shield": '<path d="M12 2l8 4v6c0 5-4 8-8 10-4-2-8-5-8-10V6z"/>',
    "star": '<path d="M12 2l2.9 6.3 6.9.6-5.2 4.6 1.6 6.8L12 17l-6.2 3.3 1.6-6.8L2.2 8.9l6.9-.6z"/>',
    "flask": '<path d="M9 3v7.6L4.6 19a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L15 10.6V3"/><path d="M8 3h8"/><path d="M7.5 16h9"/>',
}


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


class Api:
    def __init__(self):
        self.proc = None
        self._lphase = "idle"      # idle | launching | running | error
        self._lmsg = ""
        self._lpct = 0             # 0..100 launch progress
        self._pending_update = None
        self._tray = None
        self._overlay_active = False

    # ---- window controls ----
    def minimize(self):
        if webview.windows:
            webview.windows[0].minimize()
        return {"ok": True}

    def _terminate_bot(self):
        """Kill the bot subprocess without blocking the UI thread."""
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()
        except Exception:
            pass

    def close_app(self):
        self._terminate_bot()
        self.tray_stop()
        if webview.windows:
            webview.windows[0].destroy()
        return {"ok": True}

    def start_drag(self):
        # Frameless drag: one bridge call on mousedown, then a thread moves the window
        # via GetCursorPos/SetWindowPos while the button is held (WebView2's CSS
        # drag regions are unreliable).
        if getattr(self, "_dragging", False):
            return {"ok": True}
        self._dragging = True
        threading.Thread(target=self._drag_loop, daemon=True).start()
        return {"ok": True}

    def _drag_loop(self):
        try:
            h = _hwnd()
            if not h:
                return
            pt = wintypes.POINT()
            rect = wintypes.RECT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _user32.GetWindowRect(h, ctypes.byref(rect))
            offx, offy = pt.x - rect.left, pt.y - rect.top
            SWP = 0x0001 | 0x0004 | 0x0010   # NOSIZE | NOZORDER | NOACTIVATE
            while _user32.GetAsyncKeyState(0x01) & 0x8000:   # VK_LBUTTON held
                _user32.GetCursorPos(ctypes.byref(pt))
                _user32.SetWindowPos(h, None, pt.x - offx, pt.y - offy, 0, 0, SWP)
                time.sleep(0.008)
        except Exception:
            pass
        finally:
            self._dragging = False

    # ---- overlay (small always-on-top status widget while the bot runs) ----
    def enter_overlay(self):
        sw, _sh = _screen()
        w, h = OVERLAY_SIZE
        _place(True, sw - w - 24, 26, w, h)        # top-right corner
        return {"ok": True}

    def exit_overlay(self):
        sw, sh = _screen()
        w, h = APP_SIZE
        _place(False, max(0, (sw - w) // 2), max(20, (sh - h) // 2), w, h)
        return {"ok": True}

    def bot_status(self):
        from src import botstatus
        return botstatus.read() or {}

    def bot_events(self, since_seq=0):
        from src import botevents
        seq = int(since_seq or 0)
        return {"events": botevents.read_since(seq), "last_seq": botevents.last_seq()}

    def bot_inventory(self):
        from src import inventory
        return inventory.get_live_state()

    def poll_ui(self, since_seq=0):
        """One bridge round-trip for status + events + inventory + ETA (keeps UI responsive)."""
        from src import botlogs, botstatus, botevents, inventory
        self.pump_tray()
        seq = int(since_seq or 0)
        st = botstatus.read() or {}
        running = self._running()
        hb = int(st.get("heartbeat_ts") or 0)
        now = int(time.time())
        return {
            "running": running,
            "status": st,
            "events": botevents.read_since(seq),
            "last_seq": botevents.last_seq(),
            "inventory": inventory.get_live_state(),
            "restock_eta": botlogs.restock_eta(),
            "heartbeat_ts": hb,
            "heartbeat_stale": bool(running and hb and (now - hb > 120)),
        }

    def _init_tray(self):
        if os.name != "nt" or self._tray:
            return
        ico = LOGO_ICO_PATH if os.path.isfile(LOGO_ICO_PATH) else None
        if not ico:
            return
        try:
            from src.tray_win import TrayWin
            self._tray = TrayWin(ico, APP_NAME)
            self._tray.start()
        except Exception:
            self._tray = None

    def pump_tray(self):
        t = getattr(self, "_tray", None)
        if not t or not webview.windows:
            return {"ok": True}
        win = webview.windows[0]
        while True:
            try:
                cmd = t.cmd_queue.get_nowait()
            except queue.Empty:
                break
            if cmd == "show":
                try:
                    win.show()
                    win.restore()
                    win.evaluate_js("window.expandFromOverlay && window.expandFromOverlay()")
                except Exception:
                    pass
            elif cmd == "stop":
                self.stop()
                try:
                    win.evaluate_js("window.onHotkeyStop && window.onHotkeyStop()")
                except Exception:
                    pass
            elif cmd == "quit":
                self._terminate_bot()
                if getattr(self, "_tray", None):
                    try:
                        self._tray.stop()
                    except Exception:
                        pass
                    self._tray = None
                win.destroy()
        return {"ok": True}

    def tray_stop(self):
        t = getattr(self, "_tray", None)
        if t:
            try:
                t.stop()
            except Exception:
                pass
            self._tray = None
        return {"ok": True}

    def ensure_tray(self):
        try:
            cfg = load_config()
            if (cfg.get("ui") or {}).get("tray_on_run", True) is not False:
                self._init_tray()
        except Exception:
            pass
        return {"ok": True}

    def get_timings(self):
        cfg = load_config()
        t = cfg.get("timings") or {}
        return {"cooldown_sec": float(t.get("cooldown_after_check_sec", 30))}

    def get_bot_log(self, lines=100):
        """Tail of the newest logs/bot_*.log file."""
        import glob
        logdir = os.path.join(HERE, "logs")
        files = glob.glob(os.path.join(logdir, "bot_*.log"))
        if not files:
            return {"path": "", "lines": ["No log yet — press Start to launch the bot."]}
        latest = max(files, key=os.path.getmtime)
        try:
            n = max(1, int(lines))
            with open(latest, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                chunk = min(size, max(n * 256, 65536))
                f.seek(max(0, size - chunk))
                text = f.read().decode("utf-8", errors="replace")
            tail = text.splitlines()[-n:]
            return {
                "path": os.path.basename(latest),
                "lines": [ln.rstrip("\n") for ln in tail],
            }
        except OSError as e:
            return {"path": "", "lines": [f"Could not read log: {e}"]}

    def get_purchase_log(self, lines=60):
        from src import botlogs
        rows = botlogs.tail_jsonl(botlogs.PURCHASES_PATH, limit=lines)
        return {"lines": botlogs.format_purchase_rows(rows)}

    def get_timeline_log(self, lines=60):
        from src import botlogs
        rows = botlogs.tail_jsonl(botlogs.TIMELINE_PATH, limit=lines)
        return {"lines": botlogs.format_timeline_rows(rows)}

    def get_logo_data_uri(self):
        return _logo_data_uri()

    def get_app_version(self):
        from src import updater
        return {"version": updater.read_local_version()}

    def check_for_update(self):
        cfg = load_config()
        upd = cfg.get("update") or {}
        if not upd.get("enabled", True):
            return {"ok": True, "update_available": False, "skipped": True}
        from src import updater
        result = updater.check(str(upd.get("manifest_url") or "").strip())
        self._pending_update = result
        return result

    def download_and_apply_update(self):
        from src import updater
        info = getattr(self, "_pending_update", None) or {}
        url = str(info.get("download_url") or "").strip()
        result = updater.apply_release_zip(url)
        if result.get("ok"):
            def _restart():
                time.sleep(0.6)
                updater.restart_launcher()
            threading.Thread(target=_restart, daemon=True).start()
        return result

    def get_restock_eta(self):
        from src import botlogs
        return botlogs.restock_eta()

    def restock_alert(self):
        """Windows balloon when shop restocks (sound handled in UI)."""
        cfg = load_config()
        alerts = cfg.get("alerts") or {}
        if not alerts.get("desktop", True):
            return {"ok": True}
        if os.name == "nt":
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                ps = (
                    "[Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms')|Out-Null;"
                    "$n=New-Object System.Windows.Forms.NotifyIcon;"
                    "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                    "$n.Visible=$true;"
                    f"$n.ShowBalloonTip(5000,'{APP_NAME}','Shop restocked - opening shop...',"
                    "[System.Windows.Forms.ToolTipIcon]::Info);"
                    "Start-Sleep -Seconds 6;$n.Dispose()"
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                    creationflags=flags,
                )
            except Exception:
                pass
        return {"ok": True}

    def open_logs_folder(self):
        logdir = os.path.join(HERE, "logs")
        os.makedirs(logdir, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(logdir)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", logdir])
            else:
                subprocess.Popen(["xdg-open", logdir])
        except Exception:
            pass
        return {"ok": True}

    # ---- state ----
    def get_state(self):
        cfg = load_config()
        catalog_all = get_catalog(cfg)
        buy = cfg.get("buy", {}) or {}
        buy_items = buy.get("items", {}) or {}
        nav = set(cfg.get("navigation", {}).get("categories") or [c for c, *_ in CATS])
        nav.discard("special")  # legacy — no longer scanned
        discord = cfg.get("discord", {}) or {}
        ui_cfg = cfg.get("ui", {}) or {}
        timings = cfg.get("timings", {}) or {}
        cats = []
        all_buy = set()
        for lst in buy_items.values():
            all_buy.update(lst)
        for key, title, icon, color in CATS:
            buyset = set(buy_items.get(key, []))
            catalog = catalog_all.get(key, {})
            names = list(catalog.keys()) + [n for n in buyset if n not in catalog]
            items = [{"name": n, "rarity": catalog.get(n, ""), "buy": n in all_buy} for n in names]
            cats.append({"key": key, "title": title, "icon": icon, "color": color,
                         "read": key in nav, "items": items})
        scan_only = not bool(buy.get("enabled", True))
        nav_cfg = cfg.get("navigation") or {}
        alerts = cfg.get("alerts") or {}
        cat_pri = buy.get("category_priority") or []
        disabled = buy.get("button_disabled_hsv_low")
        logs_cfg = cfg.get("logs") or {}
        upd_cfg = cfg.get("update") or {}
        settings = {
            "dry_run": bool(buy.get("dry_run", True)),
            "scan_only": scan_only,
            "max_per_item": int(buy.get("max_per_item", 0) or 0),
            "max_per_restock": int(buy.get("max_total_per_restock", 0) or 0),
            "cooldown_sec": float(timings.get("cooldown_after_check_sec", 30)),
            "game_locale": str((cfg.get("game") or {}).get("locale") or "auto"),
            "verify_purchases": bool(buy.get("verify_purchases", True)),
            "debug_screenshots": bool((cfg.get("debug") or {}).get("save_screenshots", False)),
            "clear_logs_on_stop": bool(logs_cfg.get("cleanup_on_stop", True)),
            "scroll_speed": int(nav_cfg.get("wheel_notches_read", 5)),
            "scan_military_first": cat_pri and cat_pri[0] == "military",
            "wishlist_scroll_only": bool(nav_cfg.get("wishlist_scroll_only", True)),
            "vendor_mode": bool(nav_cfg.get("vendor_mode", False)),
            "vendor_soft_focus": nav_cfg.get("vendor_soft_focus", True) is not False,
            "mini_overlay": ui_cfg.get("mini_overlay", True) is not False,
            "tray_on_run": ui_cfg.get("tray_on_run", True) is not False,
            "sound_alert": bool(alerts.get("sound", True)),
            "desktop_alert": bool(alerts.get("desktop", True)),
            "detect_insufficient_funds": disabled is not None,
            "update_enabled": bool(upd_cfg.get("enabled", True)),
            "update_check_on_start": bool(upd_cfg.get("check_on_start", True)),
            "update_manifest_url": str(upd_cfg.get("manifest_url") or ""),
            "discord": {
                "enabled": bool(discord.get("enabled", False)),
                "webhook_url": str(discord.get("webhook_url") or ""),
                "notify_restock": bool(discord.get("notify_restock", True)),
                "notify_scan": bool(discord.get("notify_scan", True)),
                "notify_buy": bool(discord.get("notify_buy", True)),
                "notify_wishlist_in_stock_only": discord.get("notify_wishlist_in_stock_only", False) is not False,
                "notify_error": bool(discord.get("notify_error", True)),
            },
        }
        return {
            "dry_run": settings["dry_run"],
            "settings": settings,
            "cats": cats, "running": self._running(),
        }

    def _apply(self, state):
        cfg = load_config()
        ui_cats = [c["key"] for c in state["cats"] if c.get("read")]
        cfg.setdefault("buy", {}).setdefault("items", {})
        settings = state.get("settings") or {}
        game = cfg.setdefault("game", {})
        game["locale"] = str(settings.get("game_locale") or "auto").strip().lower() or "auto"
        ocr = cfg.setdefault("ocr", {})
        if str(ocr.get("lang_type") or "").strip().lower() in ("", "en") and game["locale"] != "en":
            ocr["lang_type"] = "auto"
        buy = cfg.setdefault("buy", {})
        scan_only = bool(settings.get("scan_only", False))
        buy["enabled"] = not scan_only
        buy["dry_run"] = bool(settings.get("dry_run", True))
        buy["max_per_item"] = max(0, int(settings.get("max_per_item", 0) or 0))
        buy["max_total_per_restock"] = max(0, int(settings.get("max_per_restock", 0) or 0))
        buy["verify_purchases"] = bool(settings.get("verify_purchases", True))
        if settings.get("scan_military_first"):
            buy["category_priority"] = ["military", "factory", "houses"]
        else:
            buy["category_priority"] = []
        if settings.get("detect_insufficient_funds", True):
            buy.setdefault("button_disabled_hsv_low", [0, 0, 70])
            buy.setdefault("button_disabled_hsv_high", [180, 80, 200])
        else:
            buy["button_disabled_hsv_low"] = None
            buy["button_disabled_hsv_high"] = None
        state["dry_run"] = buy["dry_run"]
        timings = cfg.setdefault("timings", {})
        if settings.get("cooldown_sec") is not None:
            timings["cooldown_after_check_sec"] = max(5.0, float(settings["cooldown_sec"]))
        nav = cfg.setdefault("navigation", {})
        nav["wheel_notches_read"] = max(2, min(8, int(settings.get("scroll_speed", 5) or 5)))
        nav["wishlist_scroll_only"] = bool(settings.get("wishlist_scroll_only", True))
        nav["vendor_mode"] = bool(settings.get("vendor_mode", False))
        nav["vendor_soft_focus"] = settings.get("vendor_soft_focus", True) is not False
        alerts = cfg.setdefault("alerts", {})
        alerts["sound"] = bool(settings.get("sound_alert", True))
        alerts["desktop"] = bool(settings.get("desktop_alert", True))
        dbg = cfg.setdefault("debug", {})
        dbg["save_screenshots"] = bool(settings.get("debug_screenshots", False))
        logs = cfg.setdefault("logs", {})
        logs["cleanup_on_stop"] = bool(settings.get("clear_logs_on_stop", True))
        upd = cfg.setdefault("update", {})
        upd["enabled"] = bool(settings.get("update_enabled", True))
        upd["check_on_start"] = bool(settings.get("update_check_on_start", True))
        upd["manifest_url"] = str(settings.get("update_manifest_url") or "").strip()
        discord = cfg.setdefault("discord", {})
        dc = settings.get("discord") or {}
        discord["enabled"] = bool(dc.get("enabled", False))
        discord["webhook_url"] = str(dc.get("webhook_url") or "").strip()
        discord["notify_restock"] = bool(dc.get("notify_restock", True))
        discord["notify_scan"] = bool(dc.get("notify_scan", True))
        discord["notify_buy"] = bool(dc.get("notify_buy", True))
        discord["notify_wishlist_in_stock_only"] = dc.get("notify_wishlist_in_stock_only", False) is not False
        discord["notify_error"] = bool(dc.get("notify_error", True))
        ui = cfg.setdefault("ui", {})
        ui["mini_overlay"] = settings.get("mini_overlay", True) is not False
        ui["tray_on_run"] = settings.get("tray_on_run", True) is not False
        catalog_all = get_catalog(cfg)
        picked_by_tab: dict[str, list[str]] = {c[0]: [] for c in CATS}
        seen: set[str] = set()
        for c in state["cats"]:
            for it in c["items"]:
                if not it.get("buy"):
                    continue
                name = it["name"]
                if name in seen:
                    continue
                picked_by_tab[c["key"]].append(name)
                seen.add(name)
        buy_items = {}
        for tab, picked in picked_by_tab.items():
            order = list(catalog_all.get(tab, {}).keys())
            buy_items[tab] = [n for n in order if n in picked] + \
                             [n for n in picked if n not in order]
        cfg["buy"]["items"] = buy_items
        cfg.setdefault("navigation", {})["categories"] = bot_scan_categories(ui_cats, buy_items)
        save_config(cfg)

    def test_discord(self, settings):
        """Send a test webhook using the settings draft (does not require Save)."""
        cfg = load_config()
        dc = (settings or {}).get("discord") or {}
        url = str(dc.get("webhook_url") or "").strip()
        if not url:
            return {"ok": False, "msg": "Enter a webhook URL first"}
        test_cfg = dict(cfg)
        test_cfg["discord"] = {
            "enabled": True,
            "webhook_url": url,
            "notify_restock": True,
            "notify_buy": True,
            "notify_error": True,
            "notify_scan": True,
            "mention": "",
        }
        try:
            from src import notify
            notify._send(test_cfg, f"{APP_NAME} test ping — Discord notifications are working.")
        except Exception as e:
            return {"ok": False, "msg": repr(e)}
        return {"ok": True, "msg": "Test message sent"}

    def save(self, state):
        try:
            self._apply(state)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "msg": repr(e)}

    def launch(self, state):
        # Returns immediately; the UI polls launch_status() while the bot spawns.
        self._apply(state)
        if self._running():
            return {"ok": False, "running": True, "msg": "Bot is already running"}
        try:
            from src import botstatus
            botstatus.clear()          # drop any stale status so the overlay starts clean
        except Exception:
            pass
        self._lphase = "launching"
        self._lmsg = "Starting engine…"
        self._lpct = 8
        threading.Thread(target=self._do_launch, daemon=True).start()
        return {"ok": True, "async": True}

    def _do_launch(self):
        try:
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            env = os.environ.copy()
            env.setdefault("PYTHONIOENCODING", "utf-8")
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--bot-worker"]
                cwd = HERE
            else:
                exe = sys.executable
                cand = os.path.join(os.path.dirname(exe), "python.exe")
                py = cand if os.path.exists(cand) else exe
                cmd = [py, os.path.join(HERE, "run.py")]
                cwd = HERE
            self.proc = subprocess.Popen(
                cmd, cwd=cwd,
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
            self._lpct = 60
            self._lphase = "running"
            self._lmsg = "Warming up OCR…"
        except Exception as e:
            self._lphase = "error"
            self._lmsg = f"Launch failed: {e.__class__.__name__}"

    def launch_status(self):
        return {"phase": self._lphase, "msg": self._lmsg, "pct": self._lpct, "running": self._running()}

    def _finish_bot_stop(self):
        try:
            if self.proc:
                self.proc.wait(timeout=5)
        except Exception:
            pass
        try:
            from src import botlogs
            botlogs.cleanup_on_stop(HERE, cfg=load_config())
        except Exception:
            pass

    def stop(self):
        if self._running():
            try:
                from src import botlogs, botstatus
                st = botstatus.read() or {}
                botlogs.log_session(
                    checks=int(st.get("checks", 0)),
                    buys=int(st.get("buys", 0)),
                    reason="user_stop",
                )
            except Exception:
                pass
            self._terminate_bot()
            threading.Thread(target=self._finish_bot_stop, daemon=True).start()
        self.tray_stop()
        return {"ok": True, "running": False}

    def is_running(self):
        return {"running": self._running()}

    def _running(self):
        return bool(self.proc and self.proc.poll() is None)


UI_HTML = r"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MiniWar AFK Bot</title>
<style>
  :root{
    --bg:#0B0F17; --surface:#111827; --fg:#F3F4F6; --muted:#6B7280;
    --accent:#8B5CF6; --success:#22C55E; --warning:#F59E0B; --danger:#EF4444;
    --line:rgba(255,255,255,.08); --radius:12px; --shadow:0 4px 24px rgba(0,0,0,.35);
    --space:8px; --font:"Segoe UI","Inter",system-ui,sans-serif;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  html,body{height:100%;overflow:hidden}
  :root{color-scheme:dark}
  body{display:flex;flex-direction:column;color:var(--fg);user-select:none;
    font-family:var(--font);font-weight:400;-webkit-font-smoothing:antialiased;background:var(--bg)}
  #app{flex:1;display:flex;flex-direction:column;overflow:hidden;min-height:0;position:relative}
  ::-webkit-scrollbar{width:6px;height:6px}
  ::-webkit-scrollbar-thumb{background:#374151;border-radius:6px}
  ::-webkit-scrollbar:horizontal{display:none}
  .cat-list,.item-list,.activity-feed,.log-feed,.modal-body{overflow-x:hidden}
  .hidden{display:none!important}
  svg{width:1em;height:1em;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

  /* title bar */
  .titlebar{flex:none;display:flex;align-items:center;height:40px;padding:0 var(--space) 0 calc(var(--space)*2);
    border-bottom:1px solid var(--line);background:var(--surface)}
  .drag{flex:1;display:flex;align-items:center;gap:var(--space);height:100%;font-size:13px;font-weight:600}
  .logo-img{width:22px;height:22px;border-radius:6px;object-fit:cover;display:block;flex:none}
  .logo{width:20px;height:20px;border-radius:6px;display:grid;place-items:center;font-size:10px;font-weight:700;
    background:rgba(139,92,246,.15);color:var(--accent)}
  .tdim{color:var(--muted);font-weight:400}
  .wbtns{display:flex;gap:2px}
  .wbtn{width:28px;height:28px;border:0;border-radius:6px;background:transparent;color:var(--muted);cursor:pointer;
    font-size:13px;display:grid;place-items:center;transition:background .15s}
  .wbtn:hover{background:rgba(255,255,255,.06);color:var(--fg)}
  .wbtn.close:hover{background:var(--danger);color:#fff}

  /* loading */
  #loading{position:fixed;inset:40px 0 0 0;z-index:60;display:flex;align-items:center;justify-content:center;
    background:var(--bg)}
  .ld{width:80%;max-width:360px;display:flex;flex-direction:column;align-items:center;gap:calc(var(--space)*2);text-align:center}
  .ld-spin{width:32px;height:32px;border:2px solid #374151;border-top-color:var(--accent);border-radius:50%;animation:sp .8s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}
  .ld-title{font-size:15px;font-weight:600}
  .ld-bar{width:100%;height:6px;border-radius:99px;background:#1F2937;overflow:hidden}
  .ld-bar i{display:block;height:100%;width:0;border-radius:99px;transition:width .35s ease;background:var(--accent)}
  .ld-row{width:100%;display:flex;justify-content:space-between;font-size:12px;color:var(--muted)}
  #ldPct{font-weight:600;color:var(--fg);font-variant-numeric:tabular-nums}
  .ld-hint{font-size:11px;color:var(--muted);line-height:1.4}
  .ld.err .ld-spin{border-color:#374151;border-top-color:var(--danger)}
  .ld.err .ld-title{color:var(--danger)}

  @keyframes heartbeat{0%,100%{box-shadow:inset 0 0 0 0 transparent}50%{box-shadow:inset 0 0 100px 0 rgba(139,92,246,.04)}}
  #app.heartbeat{animation:heartbeat 2.2s ease-in-out}

  /* ===== APP LAYOUT ===== */

  /* TOP — status bar */
  .status-bar{flex:none;display:flex;align-items:center;gap:calc(var(--space)*2);padding:calc(var(--space)*2) calc(var(--space)*3);
    border-bottom:1px solid var(--line);background:var(--surface)}
  .bot-state{display:flex;align-items:center;gap:var(--space);min-width:100px}
  .state-label{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
  .state-value{font-size:13px;font-weight:600;color:var(--fg)}
  .state-sub{font-size:10px;color:var(--muted);margin-top:2px;line-height:1.3}
  .state-sub.ok{color:var(--success)}
  .state-sub.warn{color:var(--warning)}
  .hero-wrap{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;position:relative;min-height:56px}
  .hero-ring{position:absolute;width:68px;height:68px;border-radius:50%;border:2px solid transparent;pointer-events:none;transition:opacity .4s}
  .hero-ring.idle{opacity:.25;border-top-color:var(--muted);animation:ringSpin 10s linear infinite}
  .hero-ring.running{opacity:.45;border-top-color:var(--accent);animation:ringSpin 4s linear infinite}
  .hero-ring.active{opacity:.55;border-top-color:var(--accent);animation:ringSpin 2.5s linear infinite}
  .hero-ring.restock{opacity:.85;border-color:rgba(139,92,246,.35);animation:ringBurst .7s ease-in-out infinite}
  @keyframes ringSpin{to{transform:rotate(360deg)}}
  @keyframes ringBurst{0%,100%{transform:scale(1);box-shadow:0 0 0 0 rgba(139,92,246,.4)}50%{transform:scale(1.06);box-shadow:0 0 20px 4px rgba(139,92,246,.25)}}
  .hero-timer{position:relative;font-size:32px;font-weight:600;font-variant-numeric:tabular-nums;
    letter-spacing:-.5px;color:var(--fg);transition:color .3s,transform .15s}
  .hero-timer.idle{color:var(--muted);font-size:22px;font-weight:500}
  .hero-timer.running{color:var(--fg)}
  .hero-timer.urgent{animation:timerUrgent .6s ease-in-out infinite}
  @keyframes timerUrgent{0%,100%{transform:scale(1)}50%{transform:scale(1.04)}}
  .hero-timer.active{color:var(--accent);font-size:18px;font-weight:500}
  .hero-timer.restock{color:var(--accent);animation:restockPulse 1.5s ease-in-out infinite}
  @keyframes restockPulse{0%,100%{text-shadow:0 0 8px rgba(139,92,246,.3)}50%{text-shadow:0 0 24px rgba(139,92,246,.7)}}
  .micro-tick{font-size:11px;color:var(--muted);margin-top:4px;height:14px;letter-spacing:.02em;opacity:0;transition:opacity .3s}
  .micro-tick.on{opacity:1}
  .live-ind{display:flex;align-items:center;min-width:24px;justify-content:flex-end}
  .live-dot{width:8px;height:8px;border-radius:50%;background:var(--muted);transition:background .3s;position:relative}
  .live-dot.watching{background:var(--success);animation:livePulseGreen 2s ease-in-out infinite}
  .live-dot.restock{background:var(--warning);animation:livePulseAmber 1.2s ease-in-out infinite}
  @keyframes livePulseGreen{0%,100%{box-shadow:0 0 0 0 rgba(34,197,94,.5)}50%{box-shadow:0 0 0 5px rgba(34,197,94,0)}}
  @keyframes livePulseAmber{0%,100%{box-shadow:0 0 0 0 rgba(245,158,11,.55)}50%{box-shadow:0 0 0 5px rgba(245,158,11,0)}}

  /* MIDDLE — core + activity */
  .main{flex:1;display:flex;min-height:0;overflow:hidden}
  .core{flex:1;display:flex;min-width:0;border-right:1px solid var(--line)}

  /* categories */
  .cat-list{flex:none;width:200px;display:flex;flex-direction:column;gap:var(--space);padding:var(--space);
    border-right:1px solid var(--line);overflow-y:auto;overflow-x:hidden}
  .cat-row{display:flex;align-items:center;justify-content:space-between;gap:var(--space);padding:calc(var(--space)*1.5);
    border-radius:var(--radius);border:1px solid transparent;background:#0d1118;cursor:pointer;
    transition:border-color .15s,background .15s,box-shadow .15s;position:relative}
  .cat-row:not(.selected){border-color:transparent}
  .cat-row:not(.selected) .cat-name{color:#6B7280;font-weight:500}
  .cat-row:not(.selected) .cat-count{color:#4B5563}
  .cat-row:hover:not(.selected){background:#121820}
  .cat-row.selected{border-color:var(--accent);background:#141028;
    box-shadow:0 0 0 1px rgba(139,92,246,.35),0 0 18px rgba(139,92,246,.12)}
  .cat-row.selected .cat-name{color:var(--fg);font-weight:600}
  .cat-row.selected .cat-count{color:var(--muted)}
  .cat-row.snap{animation:catSnap 100ms ease-out}
  @keyframes catSnap{0%{transform:scale(1)}45%{transform:scale(.975)}100%{transform:scale(1)}}
  .cat-row.glow-in{animation:borderGlow 220ms ease-out}
  @keyframes borderGlow{0%{box-shadow:0 0 0 0 rgba(139,92,246,.45),0 0 18px rgba(139,92,246,.12)}100%{box-shadow:0 0 0 1px rgba(139,92,246,.35),0 0 18px rgba(139,92,246,.12)}}
  .cat-tooltip{position:absolute;left:calc(100% + 8px);top:50%;transform:translateY(-50%);z-index:20;
    background:#1F2937;border:1px solid var(--line);border-radius:var(--radius);padding:8px 10px;
    font-size:11px;line-height:1.5;color:var(--muted);white-space:nowrap;pointer-events:none;
    opacity:0;transition:opacity .15s;box-shadow:var(--shadow)}
  .cat-row:hover .cat-tooltip{opacity:1}
  .cat-tooltip b{color:var(--fg);font-weight:500}
  .cat-info{min-width:0;flex:1}
  .cat-name{font-size:13px;display:block;transition:color .15s}
  .cat-count{font-size:11px;margin-top:2px;display:block;font-variant-numeric:tabular-nums;transition:color .15s}

  /* toggle switch */
  .sw{width:36px;height:20px;border-radius:99px;background:#374151;position:relative;flex:none;transition:background .25s;cursor:pointer}
  .sw.on{background:var(--success)}
  .sw .k{position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:#fff;
    box-shadow:0 1px 2px rgba(0,0,0,.3);transition:transform .25s cubic-bezier(.4,1.3,.5,1)}
  .sw.on .k{transform:translateX(16px)}

  /* items panel */
  .item-panel{flex:1;display:flex;flex-direction:column;min-width:0;overflow:hidden}
  .item-header{padding:calc(var(--space)*2) calc(var(--space)*3);border-bottom:1px solid var(--line);
    font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted)}
  .item-list{flex:1;overflow-y:auto;overflow-x:hidden;padding:var(--space);display:flex;flex-direction:column;gap:4px}
  .item-row{display:flex;align-items:center;gap:10px;padding:10px 12px;min-height:36px;
    border-radius:var(--radius);cursor:pointer;border:1px solid transparent;
    transition:background .12s,border-color .12s,box-shadow .12s}
  .item-row:not(.is-selected){opacity:.55}
  .item-row:not(.is-selected) .item-name{color:#6B7280;font-weight:400}
  .item-row.is-selected{opacity:1;border-color:rgba(139,92,246,.22);
    box-shadow:inset 3px 0 0 var(--accent),0 0 12px rgba(139,92,246,.06)}
  .item-row.is-selected .item-name{color:var(--fg);font-weight:500}
  .item-row:hover{background:rgba(255,255,255,.025)}
  .item-row.flash{animation:itemFlash 120ms ease-out}
  @keyframes itemFlash{0%{background:rgba(255,255,255,.06)}100%{background:transparent}}
  .item-name{flex:1;min-width:0;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.2}
  .item-meta{display:flex;align-items:center;gap:8px;flex:none}
  .interaction-dot{width:8px;height:8px;border-radius:50%;flex:none;background:#4B5563;transition:background .15s,box-shadow .15s}
  .interaction-dot.on{background:var(--accent);box-shadow:0 0 7px rgba(139,92,246,.55)}
  .status-label{font-size:9px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;
    padding:2px 7px;border-radius:4px;flex:none;line-height:1.2;white-space:nowrap}
  .status-label.available{background:rgba(34,197,94,.14);color:var(--success)}
  .status-label.unknown{background:rgba(75,85,99,.25);color:#9CA3AF}
  .status-label.out{background:rgba(239,68,68,.14);color:var(--danger);font-weight:700}
  .badge{font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;
    height:20px;display:inline-flex;align-items:center;padding:0 8px;
    border-radius:6px;background:#1F2937;color:var(--muted);flex:none;white-space:nowrap;line-height:1}
  .item-row:not(.is-selected) .badge{opacity:.45}
  .item-empty{padding:calc(var(--space)*5) calc(var(--space)*3);text-align:center;color:var(--muted);display:flex;
    flex-direction:column;align-items:center;gap:var(--space)}
  .item-empty .empty-icon{width:32px;height:32px;opacity:.25;color:var(--muted);margin-bottom:4px}
  .item-empty .empty-title{font-size:13px;font-weight:500;color:var(--muted)}
  .item-empty .empty-sub{font-size:12px;opacity:.7}

  /* RIGHT — activity */
  .activity-panel{flex:none;width:260px;display:flex;flex-direction:column;min-height:0;background:var(--surface)}
  .activity-h{padding:calc(var(--space)*2) calc(var(--space)*3);border-bottom:1px solid var(--line);
    font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:var(--muted);
    display:flex;align-items:center;justify-content:space-between;gap:var(--space)}
  .panel-link{border:0;background:transparent;color:var(--accent);font-size:10px;font-weight:600;
    cursor:pointer;text-transform:none;letter-spacing:0;padding:0}
  .panel-link:hover{text-decoration:underline}
  .log-feed{flex:1;overflow-y:auto;overflow-x:hidden;margin:0;padding:var(--space);font-family:Consolas,"Courier New",monospace;
    font-size:10px;line-height:1.45;color:#9CA3AF;background:var(--bg);white-space:pre-wrap;word-break:break-word}
  .log-tabs{display:flex;gap:4px;padding:0 var(--space) var(--space);border-bottom:1px solid var(--line)}
  .log-tab{flex:1;border:1px solid var(--line);background:#0d1118;color:var(--muted);border-radius:8px;
    padding:6px 4px;font:600 10px/1 var(--font);cursor:pointer;text-transform:uppercase;letter-spacing:.04em}
  .log-tab.active{background:rgba(139,92,246,.12);border-color:rgba(139,92,246,.35);color:var(--accent)}
  .log-tab:hover:not(.active){background:#121820;color:var(--fg)}
  .ctrl.secondary.logs-on{background:rgba(139,92,246,.12);border-color:rgba(139,92,246,.35);color:var(--accent)}
  .activity-feed{flex:1;overflow-y:auto;overflow-x:hidden;padding:var(--space);display:flex;flex-direction:column;gap:6px}
  .act-group{border-radius:var(--radius);overflow:visible}
  .act-group.act-restock,.act-group.act-vendor{background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.15);
    overflow:visible}
  .act-row{font-size:12px;line-height:1.45;color:var(--fg);padding:8px 10px;border-radius:var(--radius);background:var(--bg);
    display:flex;align-items:flex-start;gap:8px}
  .act-group .act-row{background:transparent}
  .act-row.act-head{border-radius:var(--radius) var(--radius) 0 0}
  .act-head{font-weight:500}
  .act-dot{width:6px;height:6px;border-radius:50%;flex:none;margin-top:5px}
  .act-dot.scan{background:#3B82F6}
  .act-dot.purchase{background:var(--success)}
  .act-dot.fail{background:var(--danger)}
  .act-dot.restock{background:var(--accent);box-shadow:0 0 6px rgba(139,92,246,.6)}
  .act-dot.info{background:var(--muted)}
  .act-body{flex:1;min-width:0}
  .act-time{color:var(--muted);font-variant-numeric:tabular-nums;font-size:11px;display:block;margin-bottom:1px}
  .act-msg{color:var(--fg);font-size:12px}
  .act-child{font-size:11px;color:var(--muted);padding:2px 10px 4px 24px;display:flex;gap:6px;align-items:baseline}
  .act-arrow{color:var(--accent);opacity:.7;font-size:10px}
  .act-scan-block{border-top:1px solid rgba(255,255,255,.04)}
  .act-scan-block.nested .act-scan-head{padding-left:12px}
  .act-clickable{cursor:pointer;user-select:none}
  .act-clickable:hover{background:rgba(255,255,255,.03)}
  .act-chevron{font-size:10px;color:var(--muted);flex:none;width:10px;margin-top:2px;line-height:1.4}
  .act-scan-body.collapsed{display:none}
  .act-preview{padding:4px 10px 8px 32px;font-size:11px;line-height:1.45}
  .act-preview .act-match{padding:3px 0;display:flex;gap:6px;align-items:flex-start;font-size:12px;font-weight:500}
  .act-preview .act-match.missing{color:var(--danger)}
  .act-preview .act-match.found{color:var(--success)}
  .act-preview .act-match.new{color:var(--accent)}
  .act-collapsed-hint{padding:6px 10px 10px 28px;font-size:11px;color:var(--muted);font-style:italic}
  .act-scans-wrap{padding-bottom:4px}
  .act-layer.low{font-size:10px;color:#4B5563;padding:3px 10px 2px 28px}
  .act-layer.med{font-size:11px;color:var(--muted);padding:2px 10px 6px 28px}
  .act-layer.none{font-size:11px;color:#4B5563;font-style:italic;padding:2px 10px 6px 28px}
  .act-match{display:flex;align-items:center;gap:7px;padding:5px 10px 5px 28px;font-size:12px;font-weight:500}
  .act-match.found{color:var(--success)}
  .act-match.missing{color:var(--danger)}
  .act-match.unknown{color:var(--muted)}
  .act-match.new{color:var(--accent);font-weight:600}
  .act-tracked{display:flex;flex-direction:column;gap:2px;padding-top:2px}
  .act-icon{font-size:12px;line-height:1;flex:none;width:14px;text-align:center}
  .act-scan-head .act-msg{font-weight:600}

  /* BOTTOM — controls */
  .controls{flex:none;display:flex;align-items:center;gap:var(--space);padding:calc(var(--space)*2) calc(var(--space)*3);
    border-top:1px solid var(--line);background:var(--surface)}
  .ctrl{flex:1;border:0;border-radius:var(--radius);padding:calc(var(--space)*1.5);font:600 13px/1 var(--font);
    cursor:pointer;display:flex;align-items:center;justify-content:center;gap:6px;transition:filter .15s,opacity .15s;
    box-shadow:var(--shadow)}
  .ctrl:disabled{opacity:.35;cursor:default}
  .ctrl.start{background:var(--accent);color:#fff}
  .ctrl.start:not(:disabled):hover{filter:brightness(1.08)}
  .ctrl.stop{background:rgba(239,68,68,.12);color:var(--danger);border:1px solid rgba(239,68,68,.25);box-shadow:none}
  .ctrl.stop:not(:disabled):hover{background:rgba(239,68,68,.2)}
  .ctrl.secondary{background:#1F2937;color:var(--fg);box-shadow:none;border:1px solid var(--line)}
  .ctrl.secondary:hover{background:#374151}
  .ctrl.secondary.on{background:rgba(139,92,246,.12);border-color:rgba(139,92,246,.35);color:var(--accent)}
  .ctrl-icon{width:14px;height:14px}

  /* overlay (compact while bot runs) */
  #app.hidden{display:none!important}
  #overlay.hidden{display:none!important}
  #overlay{position:fixed;inset:0;display:flex;flex-direction:column;background:var(--bg)}
  body.compact-mode .titlebar .drag span{font-size:11px}
  #overlay .ov{flex:1;display:flex;flex-direction:column;justify-content:center;gap:var(--space);padding:calc(var(--space)*2);
    background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);margin:8px}
  .ov-h{display:flex;align-items:center;gap:var(--space)}
  .ov-dot{width:8px;height:8px;border-radius:50%;background:var(--success);flex:none;box-shadow:0 0 6px rgba(34,197,94,.5)}
  .ov-state{font-weight:600;font-size:14px;flex:1}
  .ov-x{margin-left:auto;border:1px solid var(--line);background:#1F2937;color:var(--muted);
    font:600 10px/1 var(--font);padding:6px 8px;border-radius:6px;cursor:pointer}
  .ov-x:hover{background:#374151;color:var(--fg)}
  .ov-act{font-size:12px;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-height:16px}
  .ov-foot{font-size:11px;color:var(--muted);min-height:14px;margin-bottom:6px}
  .ov-feed-label{font-size:10px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-bottom:4px}
  .ov-feed{display:flex;flex-direction:column;gap:4px;max-height:108px;overflow:hidden}
  .ov-feed-row{display:flex;align-items:flex-start;gap:6px;font-size:11px;line-height:1.35;min-width:0}
  .ov-feed-row.sub{padding-left:14px;opacity:.92}
  .ov-feed-dot{width:6px;height:6px;border-radius:50%;flex:none;margin-top:4px;background:var(--muted)}
  .ov-feed-dot.vendor,.ov-feed-dot.restock{background:var(--accent)}
  .ov-feed-dot.scan{background:#60A5FA}
  .ov-feed-dot.purchase{background:var(--success)}
  .ov-feed-dot.fail{background:var(--danger)}
  .ov-feed-time{color:var(--muted);font-variant-numeric:tabular-nums;flex:none;font-size:10px}
  .ov-feed-msg{color:var(--fg);overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;min-width:0}
  .ov-feed-msg.missing{color:var(--danger);font-weight:500}
  .ov-feed-msg.found{color:var(--success);font-weight:500}
  .ov-feed-msg.new{color:var(--accent);font-weight:600}
  .ov-feed-empty{font-size:11px;color:var(--muted);font-style:italic}

  /* settings modal */
  .modal-backdrop{position:fixed;inset:0;background:rgba(0,0,0,.55);display:flex;align-items:center;
    justify-content:center;z-index:200;padding:16px}
  .modal-backdrop.hidden{display:none}
  .modal{width:100%;max-width:440px;max-height:calc(100vh - 32px);overflow:hidden;display:flex;
    flex-direction:column;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);
    box-shadow:0 24px 48px rgba(0,0,0,.5)}
  .modal-head{flex:none;display:flex;align-items:center;justify-content:space-between;
    padding:16px 18px 12px;border-bottom:1px solid var(--line)}
  .modal-title{font:600 15px/1.2 var(--font)}
  .modal-close{border:0;background:transparent;color:var(--muted);font-size:18px;cursor:pointer;
    padding:4px 8px;border-radius:6px;line-height:1}
  .modal-close:hover{background:#1F2937;color:var(--fg)}
  .modal-body{flex:1;overflow-y:auto;padding:14px 18px 8px;display:flex;flex-direction:column;gap:18px}
  .modal-foot{flex:none;display:flex;gap:8px;padding:12px 18px 16px;border-top:1px solid var(--line)}
  .set-section{display:flex;flex-direction:column;gap:10px}
  .set-label{font:600 11px/1 var(--font);letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .set-row{display:flex;align-items:center;justify-content:space-between;gap:12px;font-size:13px}
  .set-row.col{flex-direction:column;align-items:stretch;gap:6px}
  .set-hint{font-size:11px;color:var(--muted);line-height:1.4}
  .set-input{width:100%;box-sizing:border-box;background:#0B0F17;border:1px solid var(--line);
    border-radius:8px;padding:8px 10px;color:var(--fg);font:400 12px/1.4 var(--font)}
  .set-input:focus{outline:none;border-color:rgba(139,92,246,.5)}
  .set-input.num{width:88px;text-align:center;flex:none}
  .set-input:disabled{opacity:.45}
  .mode-pick{display:flex;gap:6px}
  .mode-btn{flex:1;border:1px solid var(--line);background:#1F2937;color:var(--muted);
    border-radius:8px;padding:8px 6px;font:600 12px/1 var(--font);cursor:pointer;transition:all .15s}
  .mode-btn.active{background:rgba(139,92,246,.15);border-color:rgba(139,92,246,.45);color:var(--accent)}
  .mode-btn:disabled{opacity:.4;cursor:default}
  .mode-btn.test.active{background:rgba(245,158,11,.12);border-color:rgba(245,158,11,.4);color:var(--warning)}
  .mode-btn.live.active{background:rgba(34,197,94,.12);border-color:rgba(34,197,94,.4);color:var(--success)}
  .set-checks{display:flex;flex-direction:column;gap:8px;padding-top:2px}
  .set-check{display:flex;align-items:center;gap:8px;font-size:12px;color:var(--fg);cursor:pointer}
  .set-check input{accent-color:var(--accent);width:14px;height:14px;cursor:pointer}
  .set-checks.disabled{opacity:.45;pointer-events:none}
  .set-range{width:100%;accent-color:var(--accent)}
  .set-range-val{font:600 13px/1 var(--font);color:var(--accent);min-width:36px;text-align:right}
  .modal-btn{flex:1;border:0;border-radius:var(--radius);padding:10px;font:600 13px/1 var(--font);cursor:pointer}
  .modal-btn.primary{background:var(--accent);color:#fff}
  .modal-btn.primary:hover{filter:brightness(1.08)}
  .modal-btn.ghost{background:#1F2937;color:var(--fg);border:1px solid var(--line)}
  .modal-btn.ghost:hover{background:#374151}
  .modal-btn.test{width:auto;flex:none;padding:8px 12px;font-size:12px}
  .set-toast{font-size:11px;color:var(--success);min-height:14px}
  .set-toast.err{color:var(--danger)}
  .save-toast{position:fixed;bottom:72px;left:50%;transform:translateX(-50%) translateY(8px);
    background:rgba(34,197,94,.95);color:#fff;font-size:12px;font-weight:600;padding:8px 16px;
    border-radius:8px;opacity:0;pointer-events:none;transition:opacity .2s,transform .2s;z-index:9999;
    box-shadow:0 4px 20px rgba(0,0,0,.35)}
  .save-toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
  .save-toast.err{background:rgba(239,68,68,.95)}
</style></head>
<body>
  <div class="titlebar" id="titlebar">
    <div class="drag pywebview-drag-region">
      <img class="logo-img" id="titleLogo" src="" alt="">
      <span>MiniWar AFK Bot</span>
    </div>
    <div class="wbtns">
      <button class="wbtn" id="minBtn" title="Minimize">&#8211;</button>
      <button class="wbtn close" id="closeBtn" title="Close">&#10005;</button>
    </div>
  </div>

  <div id="app">
    <div class="status-bar">
      <div class="bot-state">
        <div>
          <div class="state-label">Status</div>
          <div class="state-value" id="botState">Idle</div>
          <div class="state-sub" id="engineStatus"></div>
        </div>
      </div>
      <div class="hero-wrap">
        <div class="hero-ring idle" id="heroRing"></div>
        <div class="hero-timer idle" id="heroTimer">Waiting</div>
        <div class="micro-tick" id="microTick"></div>
      </div>
      <div class="live-ind"><span class="live-dot" id="liveDot"></span></div>
    </div>

    <div class="main">
      <div class="core">
        <div class="cat-list" id="catList"></div>
        <div class="item-panel">
          <div class="item-header" id="itemHeader">Items</div>
          <div class="item-list" id="itemList"></div>
        </div>
      </div>
      <div class="activity-panel">
        <div class="activity-h">
          <span id="panelTitle">Activity</span>
          <button class="panel-link hidden" id="openLogFolder" title="Open logs folder">Open folder</button>
        </div>
        <div class="activity-feed" id="activityFeed"></div>
        <div class="log-tabs hidden" id="logTabs">
          <button type="button" class="log-tab active" data-log="bot">Bot</button>
          <button type="button" class="log-tab" data-log="purchases">Purchases</button>
          <button type="button" class="log-tab" data-log="timeline">Timeline</button>
        </div>
        <pre class="log-feed hidden" id="logFeed"></pre>
      </div>
    </div>

    <div class="controls">
      <button class="ctrl start" id="runBtn">
        <svg class="ctrl-icon" viewBox="0 0 24 24" style="fill:currentColor;stroke:none"><path d="M6 4l14 8-14 8z"/></svg>
        Start
      </button>
      <button class="ctrl stop" id="stopBtn" disabled>
        <svg class="ctrl-icon" viewBox="0 0 24 24" style="fill:currentColor;stroke:none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>
        Stop
      </button>
      <button class="ctrl secondary hidden" id="compactBtn" title="Shrink to compact overlay">
        <svg class="ctrl-icon" viewBox="0 0 24 24"><path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/></svg>
        Compact
      </button>
      <button class="ctrl secondary" id="settingsBtn" title="Settings">
        <svg class="ctrl-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        Settings
      </button>
      <button class="ctrl secondary" id="logsBtn" title="View bot logs">
        <svg class="ctrl-icon" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
        Logs
      </button>
    </div>
  </div>

  <div id="loading" class="hidden">
    <div class="ld">
      <div class="ld-spin"></div>
      <div class="ld-title" id="ldTitle">Launching bot…</div>
      <div class="ld-bar"><i id="ldFill"></i></div>
      <div class="ld-row"><span id="ldMsg">Starting…</span><span id="ldPct">0%</span></div>
      <div class="ld-hint" id="ldHint">First run downloads the OCR model — this can take a minute.</div>
    </div>
  </div>

  <div id="settingsModal" class="modal-backdrop hidden">
    <div class="modal" role="dialog" aria-labelledby="settingsTitle">
      <div class="modal-head">
        <span class="modal-title" id="settingsTitle">Settings</span>
        <button class="modal-close" id="settingsClose" title="Close">&times;</button>
      </div>
      <div class="modal-body">
        <div class="set-section">
          <div class="set-label">Language</div>
          <div class="set-row">
            <span>Game UI language</span>
            <select class="set-input" id="setGameLocale" style="max-width:11rem">
              <option value="auto">Auto (all languages)</option>
              <option value="en">English</option>
              <option value="fr">French</option>
              <option value="de">German</option>
              <option value="es">Spanish</option>
              <option value="pt">Portuguese</option>
            </select>
          </div>
          <div class="set-hint">Match your Roblox / Mini War language. Auto works for most players (including French).</div>
        </div>
        <div class="set-section">
          <div class="set-label">Buying</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setScanOnly">
            <span>Scan only <span class="set-hint" style="display:inline">— watch &amp; report, no purchases</span></span>
          </label>
          <div class="set-row col" id="setModeRow">
            <span class="set-hint">Purchase mode</span>
            <div class="mode-pick">
              <button type="button" class="mode-btn test" id="setModeTest">Test</button>
              <button type="button" class="mode-btn live" id="setModeLive">Live</button>
            </div>
            <span class="set-hint" id="setModeHint">Test logs what it would buy. Live clicks buy for real.</span>
          </div>
          <div class="set-row">
            <span>Max per item</span>
            <input class="set-input num" type="number" id="setMaxItem" min="0" max="999" value="1">
          </div>
          <div class="set-hint">0 = buy all available stock. 1 = one per item per restock (recommended).</div>
          <div class="set-row">
            <span>Max per restock</span>
            <input class="set-input num" type="number" id="setMaxRestock" min="0" max="999" value="0">
          </div>
          <div class="set-hint">Total buy clicks across all items in one restock. 0 = unlimited.</div>
        </div>
        <div class="set-section">
          <div class="set-label">Timing</div>
          <div class="set-row">
            <span>Restock cooldown</span>
            <span class="set-range-val" id="setCooldownVal">30s</span>
          </div>
          <input class="set-range" type="range" id="setCooldown" min="10" max="120" step="5" value="30">
          <div class="set-hint" id="setCooldownHint">Seconds before watching again after a shop check (matches the timer).</div>
        </div>
        <div class="set-section">
          <div class="set-label">Scanning</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setVendorMode">
            <span>Stand at vendor <span class="set-hint" style="display:inline">— E to open, X to close, stay at shop</span></span>
          </label>
          <div class="set-hint" id="setVendorHint">Watches the restock banner only — opens with E when &quot;Shop has been restocked!&quot; appears. Soft focus skips timer polls, not a confirmed banner.</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setVendorSoftFocus" checked>
            <span>Soft focus <span class="set-hint" style="display:inline">— only skip manual polls when unfocused; restock banner still runs</span></span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setMiniOverlay" checked>
            <span>Compact overlay while running <span class="set-hint" style="display:inline">— small always-on-top status widget</span></span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setTrayOnRun" checked>
            <span>System tray icon <span class="set-hint" style="display:inline">— right-click: Show / Stop / Exit</span></span>
          </label>
          <div class="set-row">
            <span>Shop scroll speed</span>
            <span class="set-range-val" id="setScrollVal">5</span>
          </div>
          <input class="set-range" type="range" id="setScrollSpeed" min="2" max="8" step="1" value="5">
          <div class="set-hint">Higher = faster scans. Lower if items are missed.</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setMilitaryFirst">
            <span>Scan Military before Factory</span>
          </label>
          <div class="set-hint">Buy Air Fortress etc. before Factory divine items when both restock.</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setWishlistScroll" checked>
            <span>Wishlist-only scroll <span class="set-hint" style="display:inline">— stop after purple-dot items, skip full catalog</span></span>
          </label>
        </div>
        <div class="set-section">
          <div class="set-label">Alerts</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setSoundAlert" checked>
            <span>Sound on restock</span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setDesktopAlert" checked>
            <span>Desktop notification on restock</span>
          </label>
        </div>
        <div class="set-section">
          <div class="set-label">Advanced</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setVerifyPurchases" checked>
            <span>Verify purchases <span class="set-hint" style="display:inline">— confirm stock dropped after each click</span></span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setInsufficientFunds" checked>
            <span>Detect insufficient funds <span class="set-hint" style="display:inline">— grey buy button vs sold out</span></span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setDebugScreenshots">
            <span>Save debug screenshots <span class="set-hint" style="display:inline">— OCR frames to debug/ when troubleshooting</span></span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setClearLogsOnStop" checked>
            <span>Clear logs when stopped <span class="set-hint" style="display:inline">— off = keep logs for debugging</span></span>
          </label>
        </div>
        <div class="set-section">
          <div class="set-label">Updates</div>
          <div class="set-row">
            <span>Version</span>
            <span class="set-range-val" id="setAppVersion">—</span>
          </div>
          <label class="set-row set-check">
            <input type="checkbox" id="setUpdateEnabled" checked>
            <span>Enable update checks</span>
          </label>
          <label class="set-row set-check">
            <input type="checkbox" id="setUpdateOnStart" checked>
            <span>Check on launch</span>
          </label>
          <div class="set-row col">
            <span class="set-hint">Manifest URL (host update.json — see update.json.example)</span>
            <input class="set-input" type="url" id="setUpdateUrl" placeholder="https://raw.githubusercontent.com/loadingproxies/MiniWarAFKBot/main/update.json">
          </div>
          <div class="set-row">
            <span class="set-toast" id="setUpdateToast"></span>
            <button type="button" class="modal-btn ghost test" id="setUpdateCheck">Check now</button>
          </div>
        </div>
        <div class="set-section">
          <div class="set-label">Discord</div>
          <label class="set-row set-check">
            <input type="checkbox" id="setDiscordEnabled">
            <span>Enable Discord notifications</span>
          </label>
          <div class="set-row col">
            <span class="set-hint">Webhook URL</span>
            <input class="set-input" type="url" id="setWebhook" placeholder="https://discord.com/api/webhooks/...">
          </div>
          <div class="set-checks" id="setDiscordToggles">
            <label class="set-row set-check"><input type="checkbox" id="setNotifyRestock"><span>Restock detected</span></label>
            <label class="set-row set-check"><input type="checkbox" id="setNotifyScan"><span>Category scan results</span></label>
            <label class="set-row set-check"><input type="checkbox" id="setNotifyWishlistOnly"><span>Wishlist in-stock only <span class="set-hint" style="display:inline">— skip restock + OOS pings</span></span></label>
            <label class="set-row set-check"><input type="checkbox" id="setNotifyBuy"><span>Purchases</span></label>
            <label class="set-row set-check"><input type="checkbox" id="setNotifyError"><span>Errors</span></label>
          </div>
          <div class="set-row">
            <span class="set-toast" id="setDiscordToast"></span>
            <button type="button" class="modal-btn ghost test" id="setDiscordTest">Send test</button>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <span class="set-hint" style="flex:1;margin:0">Saved to config.json when you click Save.</span>
        <button type="button" class="modal-btn ghost" id="settingsCancel">Cancel</button>
        <button type="button" class="modal-btn primary" id="settingsSave">Save</button>
      </div>
    </div>
  </div>

  <div id="saveToast" class="save-toast" aria-live="polite">Settings saved</div>

  <div id="updateModal" class="modal-backdrop hidden">
    <div class="modal" role="dialog" aria-labelledby="updateTitle">
      <div class="modal-head">
        <span class="modal-title" id="updateTitle">Update available</span>
        <button class="modal-close" id="updateClose" title="Close">&times;</button>
      </div>
      <div class="modal-body">
        <p id="updateMsg" class="set-hint" style="line-height:1.5"></p>
        <pre id="updateNotes" class="log-feed" style="max-height:120px;margin-top:10px;font-size:11px"></pre>
      </div>
      <div class="modal-foot">
        <button type="button" class="modal-btn ghost" id="updateLater">Later</button>
        <button type="button" class="modal-btn primary" id="updateInstall">Download &amp; install</button>
      </div>
    </div>
  </div>

  <div id="overlay" class="hidden pywebview-drag-region">
    <div class="ov">
      <div class="ov-h">
        <span class="ov-dot"></span>
        <span class="ov-state" id="ovState">Working</span>
        <button class="ov-x" id="ovExpand" title="Expand full panel">Expand</button>
        <button class="ov-x" id="ovStop">F7 · stop</button>
      </div>
      <div class="ov-act" id="ovAct">Starting…</div>
      <div class="ov-foot" id="ovMeta"></div>
      <div class="ov-feed-label">Activity</div>
      <div class="ov-feed" id="ovFeed"></div>
    </div>
  </div>

<script>
const ICONS = __ICONS__;
let S = null;
try{ S = __BOOT_STATE__; }catch(e){}
const $ = id => document.getElementById(id);
function apiReady(){return new Promise(res=>{(function w(){var a=window.pywebview&&window.pywebview.api;
  if(a&&a.save) return res(a); setTimeout(w,40);})();});}

let selectedCat = 0;
let _saveT = null;
let _saveToastT = null;
let _statusPoll = null;
let _statusTickBusy = false;
let _botWasRunning = false;
let _overlayCompact = false;
let _lastEventSeq = 0;
let activityLog = [];
let catLastScan = {};
let catActivity = {};
let itemLastSeen = {};
let liveInventory = {items:{}, categories:{}};
let _countdownReset = 0;
let _displayRemaining = 30;
let _targetRemaining = 30;
let _timerRaf = null;
let _microIdx = 0;
let _logPoll = null;
let _showLogs = false;
let _logView = "bot";
let _restockEta = null;
let _currentBotState = "idle";
let COOLDOWN_SEC = 30;
const MICRO_TICKS = ["Scanning", "checking shop", "syncing"];
const STATE_LABEL = {idle:"Idle",watching:"Watching",restock:"Restock",reading:"Scanning",buying:"Buying",stopped:"Stopped",
  scanning:"Scanning",matching:"Matching"};

function showSaveToast(ok, msg){
  const el = $("saveToast");
  if(!el) return;
  el.textContent = msg || (ok ? "Settings saved" : "Could not save settings");
  el.classList.toggle("err", ok === false);
  el.classList.add("show");
  clearTimeout(_saveToastT);
  _saveToastT = setTimeout(()=>el.classList.remove("show"), 2200);
}

function apply(opts){
  ensureSettings();
  S.dry_run = S.settings.dry_run;
  clearTimeout(_saveT);
  const run = async()=>{
    try{
      const a = await apiReady();
      const r = await a.save(S);
      if(opts && opts.toast) showSaveToast(!!(r && r.ok));
      return r;
    }catch(e){
      if(opts && opts.toast) showSaveToast(false);
      throw e;
    }
  };
  if(opts && opts.immediate) return run();
  _saveT = setTimeout(run, 80);
  return Promise.resolve();
}

window.flushSave = async function(){
  clearTimeout(_saveT);
  _saveT = null;
  ensureSettings();
  try{
    const a = await apiReady();
    await a.save(S);
  }catch(e){}
};

function badge(r){
  if(!r) return "";
  return `<span class="badge">${r}</span>`;
}

function normItemKey(name){
  return (name||"").toLowerCase().replace(/[^a-z0-9]/g,"");
}

function findLiveItem(catKey, itemName){
  const items = liveInventory.items || {};
  const exact = catKey + ":" + normItemKey(itemName);
  if(items[exact]) return items[exact];
  const nk = normItemKey(itemName);
  for(const [k, v] of Object.entries(items)){
    if(!k.startsWith(catKey + ":")) continue;
    const kn = k.split(":")[1] || "";
    if(kn === nk || kn.includes(nk) || nk.includes(kn)) return v;
  }
  // Same item can appear in multiple catalog tabs; stock comes from whichever tab was scanned.
  for(const [k, v] of Object.entries(items)){
    const kn = (k.split(":")[1] || "");
    if(kn === nk || kn.includes(nk) || nk.includes(kn)) return v;
  }
  return null;
}

function stockStatus(catKey, itemName){
  const live = findLiveItem(catKey, itemName);
  if(!live) return "unknown";
  if(live.status === "out") return "out";
  if(live.status === "in" || (live.stock != null && live.stock > 0)) return "available";
  return "unknown";
}

function stockLabelText(catKey, itemName){
  const live = findLiveItem(catKey, itemName);
  const st = stockStatus(catKey, itemName);
  if(st === "out") return "Out of Stock!";
  if(st === "available"){
    if(live && live.stock != null && live.stock > 0) return "Stock x" + live.stock;
    return "In Stock";
  }
  return "Unknown";
}

const STATUS_TEXT = {available:"In Stock", unknown:"Unknown", out:"Out of Stock!"};

function statusLabelHtml(catKey, itemName){
  const st = stockStatus(catKey, itemName);
  const text = stockLabelText(catKey, itemName);
  return `<span class="status-label ${st}">${text}</span>`;
}

function interactionDotHtml(selected){
  return `<span class="interaction-dot${selected?" on":""}"></span>`;
}

function flashItemByName(catKey, name){
  if(!S.cats[selectedCat] || S.cats[selectedCat].key !== catKey) return;
  const rows = $("itemList").querySelectorAll(".item-row");
  S.cats[selectedCat].items.forEach((it, i)=>{
    if(it.name === name && rows[i]){
      rows[i].classList.remove("flash");
      void rows[i].offsetWidth;
      rows[i].classList.add("flash");
      setTimeout(()=>rows[i].classList.remove("flash"), 130);
    }
  });
}

function recordCatActivity(key){
  if(!key) return;
  if(!catActivity[key]) catActivity[key] = [];
  catActivity[key].push(Date.now());
  catActivity[key] = catActivity[key].filter(t=>Date.now()-t<120000);
  catLastScan[key] = Date.now();
}

function formatAgo(ts){
  if(!ts) return "never";
  const s = Math.floor((Date.now()-ts)/1000);
  if(s < 2) return "just now";
  if(s < 60) return s + "s ago";
  return Math.floor(s/60) + "m ago";
}

function selectCategory(ci, animate){
  selectedCat = ci;
  renderCategories();
  renderItems();
  if(animate){
    const row = $("catList").children[ci];
    if(row){ row.classList.add("snap","glow-in"); setTimeout(()=>row.classList.remove("snap","glow-in"),220); }
  }
}

function renderCategories(){
  const host = $("catList");
  host.innerHTML = "";
  S.cats.forEach((c, ci)=>{
    const active = c.items.filter(i=>i.buy).length;
    const total = c.items.length;
    const row = document.createElement("div");
    row.className = "cat-row" + (ci === selectedCat ? " selected" : "");
    row.innerHTML = `<div class="cat-info"><span class="cat-name">${c.title}</span>
      <span class="cat-count">${active} / ${total}</span></div>
      <div class="sw ${c.read?'on':''}"><div class="k"></div></div>
      <div class="cat-tooltip">Last scan: <b>${formatAgo(catLastScan[c.key])}</b><br>Items tracked: <b>${total}</b></div>`;
    row.onclick = e=>{
      if(e.target.closest(".sw")) return;
      if(ci !== selectedCat) selectCategory(ci, true);
    };
    const sw = row.querySelector(".sw");
    sw.onclick = e=>{ e.stopPropagation(); c.read = !c.read; sw.classList.toggle("on", c.read); apply(); };
    host.appendChild(row);
  });
}

function flashItemsInCategory(catKey){
  if(S.cats[selectedCat] && S.cats[selectedCat].key === catKey){
    $("itemList").querySelectorAll(".item-row").forEach(r=>{
      r.classList.remove("flash");
      void r.offsetWidth;
      r.classList.add("flash");
      setTimeout(()=>r.classList.remove("flash"), 130);
    });
  }
}

function markCategoryItemsSeen(catKey){
  const cat = S.cats.find(c=>c.key===catKey);
  if(!cat) return;
  const now = Date.now();
  cat.items.forEach(it=>{ itemLastSeen[catKey+":"+it.name] = now; });
  flashItemsInCategory(catKey);
  if(S.cats[selectedCat] && S.cats[selectedCat].key === catKey) updateItemStatus();
}

function updateItemStatus(){
  const c = S.cats[selectedCat];
  if(!c) return;
  const rows = $("itemList").querySelectorAll(".item-row");
  c.items.forEach((it, i)=>{
    const row = rows[i];
    if(!row) return;
    const lbl = row.querySelector(".status-label");
    if(lbl){
      const st = stockStatus(c.key, it.name);
      lbl.className = "status-label " + st;
      lbl.textContent = stockLabelText(c.key, it.name);
    }
    const dot = row.querySelector(".interaction-dot");
    if(dot) dot.classList.toggle("on", !!it.buy);
    row.classList.toggle("is-selected", !!it.buy);
  });
}

function renderItems(){
  const c = S.cats[selectedCat];
  if(!c){ $("itemList").innerHTML = ""; return; }
  $("itemHeader").textContent = c.title;
  const host = $("itemList");
  host.innerHTML = "";
  if(!c.items.length){
    host.innerHTML = `<div class="item-empty">
      <svg class="empty-icon" viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>
      <div class="empty-title">No items tracked in this category</div>
      <div class="empty-sub">Waiting for scan results…</div></div>`;
    return;
  }
  c.items.forEach(it=>{
    const row = document.createElement("div");
    row.className = "item-row" + (it.buy ? " is-selected" : "");
    row.innerHTML = `<span class="item-name">${it.name}</span>
      <span class="item-meta">${interactionDotHtml(it.buy)}${statusLabelHtml(c.key, it.name)}${badge(it.rarity)}</span>`;
    row.onclick = ()=>{
      it.buy = !it.buy;
      row.classList.toggle("is-selected", it.buy);
      row.querySelector(".interaction-dot").classList.toggle("on", it.buy);
      const active = c.items.filter(i=>i.buy).length;
      const catRow = $("catList").children[selectedCat];
      if(catRow) catRow.querySelector(".cat-count").textContent = active + " / " + c.items.length;
      apply();
    };
    host.appendChild(row);
  });
}

function renderApp(){
  if(selectedCat >= S.cats.length) selectedCat = 0;
  S.cats.forEach(c=>{ if(!catActivity[c.key]) catActivity[c.key]=[]; });
  renderCategories();
  renderItems();
  updateSettingsBtn();
}

function ensureSettings(){
  if(!S.settings){
    S.settings = {
      dry_run: !!S.dry_run,
      scan_only: false,
      max_per_item: 1,
      max_per_restock: 0,
      cooldown_sec: COOLDOWN_SEC,
      game_locale: "auto",
      verify_purchases: true,
      debug_screenshots: false,
      clear_logs_on_stop: true,
      scroll_speed: 5,
      scan_military_first: false,
      wishlist_scroll_only: true,
      vendor_mode: false,
      vendor_soft_focus: true,
      mini_overlay: true,
      tray_on_run: true,
      sound_alert: true,
      desktop_alert: true,
      detect_insufficient_funds: true,
      update_enabled: true,
      update_check_on_start: true,
      update_manifest_url: "",
      discord: {
        enabled: false, webhook_url: "",
        notify_restock: true, notify_scan: true, notify_buy: true, notify_error: true,
        notify_wishlist_in_stock_only: false,
      },
    };
  }
  if(!S.settings.discord) S.settings.discord = {};
}

function updateSettingsBtn(){
  ensureSettings();
  const btn = $("settingsBtn");
  const st = S.settings;
  const active = st.scan_only || st.dry_run;
  btn.classList.toggle("on", active);
  const parts = [];
  if(st.scan_only) parts.push("Scan only");
  else if(st.dry_run) parts.push("Test");
  else parts.push("Live");
  if(st.vendor_mode) parts.push("Vendor");
  if(st.verify_purchases) parts.push("Verify");
  btn.title = "Settings (" + parts.join(", ") + ")";
}

let _settingsDraft = null;

function readSettingsForm(){
  const dc = {
    enabled: $("setDiscordEnabled").checked,
    webhook_url: $("setWebhook").value.trim(),
    notify_restock: $("setNotifyRestock").checked,
    notify_scan: $("setNotifyScan").checked,
    notify_wishlist_in_stock_only: $("setNotifyWishlistOnly").checked,
    notify_buy: $("setNotifyBuy").checked,
    notify_error: $("setNotifyError").checked,
  };
  return {
    scan_only: $("setScanOnly").checked,
    dry_run: !$("setModeLive").classList.contains("active"),
    max_per_item: parseInt($("setMaxItem").value, 10) || 0,
    max_per_restock: parseInt($("setMaxRestock").value, 10) || 0,
    cooldown_sec: parseInt($("setCooldown").value, 10) || 30,
    game_locale: $("setGameLocale").value || "auto",
    verify_purchases: $("setVerifyPurchases").checked,
    debug_screenshots: $("setDebugScreenshots").checked,
    clear_logs_on_stop: $("setClearLogsOnStop").checked,
    scroll_speed: parseInt($("setScrollSpeed").value, 10) || 5,
    scan_military_first: $("setMilitaryFirst").checked,
    wishlist_scroll_only: $("setWishlistScroll").checked,
    vendor_mode: $("setVendorMode").checked,
    vendor_soft_focus: $("setVendorSoftFocus").checked,
    mini_overlay: $("setMiniOverlay").checked,
    tray_on_run: $("setTrayOnRun").checked,
    sound_alert: $("setSoundAlert").checked,
    desktop_alert: $("setDesktopAlert").checked,
    detect_insufficient_funds: $("setInsufficientFunds").checked,
    update_enabled: $("setUpdateEnabled").checked,
    update_check_on_start: $("setUpdateOnStart").checked,
    update_manifest_url: $("setUpdateUrl").value.trim(),
    discord: dc,
  };
}

function fillSettingsForm(st){
  $("setScanOnly").checked = !!st.scan_only;
  $("setModeTest").classList.toggle("active", !st.scan_only && !!st.dry_run);
  $("setModeLive").classList.toggle("active", !st.scan_only && !st.dry_run);
  $("setMaxItem").value = st.max_per_item != null ? st.max_per_item : 0;
  $("setMaxRestock").value = st.max_per_restock != null ? st.max_per_restock : 0;
  $("setCooldown").value = st.cooldown_sec || 30;
  $("setCooldownVal").textContent = (st.cooldown_sec || 30) + "s";
  $("setScrollSpeed").value = st.scroll_speed != null ? st.scroll_speed : 5;
  $("setScrollVal").textContent = String(st.scroll_speed != null ? st.scroll_speed : 5);
  if($("setGameLocale")) $("setGameLocale").value = st.game_locale || "auto";
  $("setVerifyPurchases").checked = st.verify_purchases !== false;
  $("setDebugScreenshots").checked = !!st.debug_screenshots;
  $("setClearLogsOnStop").checked = st.clear_logs_on_stop !== false;
  $("setMilitaryFirst").checked = !!st.scan_military_first;
  $("setWishlistScroll").checked = st.wishlist_scroll_only !== false;
  $("setVendorMode").checked = !!st.vendor_mode;
  $("setVendorSoftFocus").checked = st.vendor_soft_focus !== false;
  if($("setMiniOverlay")) $("setMiniOverlay").checked = st.mini_overlay !== false;
  if($("setTrayOnRun")) $("setTrayOnRun").checked = st.tray_on_run !== false;
  $("setSoundAlert").checked = st.sound_alert !== false;
  $("setDesktopAlert").checked = st.desktop_alert !== false;
  $("setInsufficientFunds").checked = st.detect_insufficient_funds !== false;
  $("setUpdateEnabled").checked = st.update_enabled !== false;
  $("setUpdateOnStart").checked = st.update_check_on_start !== false;
  $("setUpdateUrl").value = st.update_manifest_url || "";
  apiReady().then(a=>a.get_app_version()).then(v=>{
    if(v && v.version) $("setAppVersion").textContent = "v" + v.version;
  }).catch(()=>{});
  const dc = st.discord || {};
  $("setDiscordEnabled").checked = !!dc.enabled;
  $("setWebhook").value = dc.webhook_url || "";
  $("setNotifyRestock").checked = dc.notify_restock !== false;
  $("setNotifyScan").checked = dc.notify_scan !== false;
  if($("setNotifyWishlistOnly")) $("setNotifyWishlistOnly").checked = dc.notify_wishlist_in_stock_only !== false;
  $("setNotifyBuy").checked = dc.notify_buy !== false;
  $("setNotifyError").checked = dc.notify_error !== false;
  syncSettingsFormState();
}

function syncSettingsFormState(){
  const scanOnly = $("setScanOnly").checked;
  const discordOn = $("setDiscordEnabled").checked;
  const vendorOn = $("setVendorMode").checked;
  if($("setVendorSoftFocus")) $("setVendorSoftFocus").disabled = !vendorOn;
  if($("setMiniOverlay")) $("setMiniOverlay").disabled = false;
  if($("setTrayOnRun")) $("setTrayOnRun").disabled = false;
  $("setModeTest").disabled = scanOnly;
  $("setModeLive").disabled = scanOnly;
  $("setMaxItem").disabled = scanOnly;
  $("setMaxRestock").disabled = scanOnly;
  $("setModeRow").style.opacity = scanOnly ? ".45" : "1";
  $("setWebhook").disabled = !discordOn;
  $("setDiscordToggles").classList.toggle("disabled", !discordOn);
  $("setDiscordTest").disabled = !discordOn || !$("setWebhook").value.trim();
  const cdHint = $("setCooldownHint");
  const vHint = $("setVendorHint");
  if(cdHint) cdHint.textContent = vendorOn
    ? "Seconds before another restock check after a scan (banner debounce — same as normal mode)."
    : "Seconds before watching again after a shop check (matches the timer).";
  if(vHint) vHint.style.display = vendorOn ? "block" : "block";
  if(scanOnly){
    $("setModeHint").textContent = "Buying controls disabled while scan-only is on.";
  } else if($("setModeLive").classList.contains("active")){
    $("setModeHint").textContent = "Live mode — real purchases when items are in stock.";
  } else {
    $("setModeHint").textContent = "Test mode — logs what it would buy, no clicks.";
  }
}

function openSettingsModal(){
  ensureSettings();
  _settingsDraft = JSON.parse(JSON.stringify(S.settings));
  fillSettingsForm(_settingsDraft);
  $("setDiscordToast").textContent = "";
  $("setDiscordToast").className = "set-toast";
  $("setUpdateToast").textContent = "";
  $("setUpdateToast").className = "set-toast";
  $("settingsModal").classList.remove("hidden");
}

function closeSettingsModal(){
  $("settingsModal").classList.add("hidden");
  _settingsDraft = null;
}

async function saveSettingsModal(){
  const btn = $("settingsSave");
  btn.disabled = true;
  btn.textContent = "Saving…";
  S.settings = readSettingsForm();
  S.dry_run = S.settings.dry_run;
  COOLDOWN_SEC = S.settings.cooldown_sec;
  try{
    await apply({immediate: true, toast: true});
    updateSettingsBtn();
    btn.textContent = "Saved!";
    setTimeout(()=>{
      closeSettingsModal();
      btn.disabled = false;
      btn.textContent = "Save";
    }, 450);
  }catch(e){
    btn.disabled = false;
    btn.textContent = "Save";
    showSaveToast(false);
  }
}

function wireSettingsModal(){
  $("settingsBtn").onclick = openSettingsModal;
  $("settingsClose").onclick = closeSettingsModal;
  $("settingsCancel").onclick = closeSettingsModal;
  $("settingsSave").onclick = ()=>saveSettingsModal();
  $("settingsModal").onclick = e=>{ if(e.target === $("settingsModal")) closeSettingsModal(); };
  $("setScanOnly").onchange = syncSettingsFormState;
  $("setVendorMode").onchange = syncSettingsFormState;
  $("setVendorSoftFocus").onchange = syncSettingsFormState;
  $("setDiscordEnabled").onchange = syncSettingsFormState;
  $("setWebhook").oninput = syncSettingsFormState;
  $("setCooldown").oninput = ()=>{
    $("setCooldownVal").textContent = $("setCooldown").value + "s";
  };
  $("setScrollSpeed").oninput = ()=>{
    $("setScrollVal").textContent = $("setScrollSpeed").value;
  };
  $("setModeTest").onclick = ()=>{
    if($("setScanOnly").checked) return;
    $("setModeTest").classList.add("active");
    $("setModeLive").classList.remove("active");
    syncSettingsFormState();
  };
  $("setModeLive").onclick = ()=>{
    if($("setScanOnly").checked) return;
    $("setModeLive").classList.add("active");
    $("setModeTest").classList.remove("active");
    syncSettingsFormState();
  };
  $("setDiscordTest").onclick = async ()=>{
    const toast = $("setDiscordToast");
    toast.textContent = "Sending…";
    toast.className = "set-toast";
    try{
      const a = await apiReady();
      const r = await a.test_discord({discord: {
        webhook_url: $("setWebhook").value.trim(),
        enabled: true,
      }});
      if(r.ok){
        toast.textContent = r.msg || "Sent!";
        toast.className = "set-toast";
      } else {
        toast.textContent = r.msg || "Failed";
        toast.className = "set-toast err";
      }
    }catch(e){
      toast.textContent = "Failed to send";
      toast.className = "set-toast err";
    }
  };
  $("setUpdateCheck").onclick = async ()=>{
    S.settings = readSettingsForm();
    await apply();
    await runUpdateCheck(true);
  };
}

let _pendingUpdateInfo = null;

function showUpdateModal(info){
  _pendingUpdateInfo = info;
  $("updateMsg").textContent = `Version ${info.local_version} → ${info.remote_version} is available.`;
  $("updateNotes").textContent = info.notes || "(No release notes)";
  $("updateInstall").disabled = false;
  $("updateInstall").textContent = "Download & install";
  $("updateModal").classList.remove("hidden");
}

function closeUpdateModal(){
  $("updateModal").classList.add("hidden");
}

async function runUpdateCheck(showToast){
  const toast = $("setUpdateToast");
  if(showToast && toast){
    toast.textContent = "Checking…";
    toast.className = "set-toast";
  }
  try{
    const a = await apiReady();
    const r = await a.check_for_update();
    if(!r.ok){
      if(showToast && toast){
        toast.textContent = r.error || "Check failed";
        toast.className = "set-toast err";
      }
      return r;
    }
    if(r.update_available){
      showUpdateModal(r);
      if(showToast && toast) toast.textContent = "Update found!";
    } else if(showToast && toast){
      toast.textContent = r.skipped ? "Updates disabled" : "Up to date";
      toast.className = "set-toast";
    }
    return r;
  }catch(e){
    if(showToast && toast){
      toast.textContent = "Check failed";
      toast.className = "set-toast err";
    }
    return null;
  }
}

function wireUpdateModal(){
  $("updateLater").onclick = closeUpdateModal;
  $("updateClose").onclick = closeUpdateModal;
  $("updateModal").onclick = e=>{ if(e.target === $("updateModal")) closeUpdateModal(); };
  $("updateInstall").onclick = async ()=>{
    $("updateInstall").disabled = true;
    $("updateInstall").textContent = "Downloading…";
    try{
      const a = await apiReady();
      const r = await a.download_and_apply_update();
      if(!r.ok){
        $("updateMsg").textContent = r.error || "Update failed";
        $("updateInstall").disabled = false;
        $("updateInstall").textContent = "Download & install";
        return;
      }
      $("updateMsg").textContent = "Installed — restarting…";
    }catch(e){
      $("updateInstall").disabled = false;
      $("updateInstall").textContent = "Download & install";
    }
  };
}

async function checkUpdatesOnStart(){
  ensureSettings();
  if(!S.settings.update_enabled || !S.settings.update_check_on_start) return;
  if(!S.settings.update_manifest_url) return;
  const r = await runUpdateCheck(false);
  if(r && r.update_available) showUpdateModal(r);
}

function formatTrackedItem(t){
  if(t.kind === "missing"){
    return {icon:"⚠", cls:"missing", msg:`${t.name} — Out of Stock`};
  }
  if(t.kind === "unknown"){
    return {icon:"?", cls:"unknown", msg:`${t.name} — Stock unclear (OCR)`};
  }
  if(t.kind === "unseen"){
    return {icon:"—", cls:"unknown", msg:`${t.name} — Not seen in scan`};
  }
  if(t.kind === "newly_available"){
    const sfx = t.stock != null && t.stock > 0 ? ` (x${t.stock})` : "";
    return {icon:"✨", cls:"new", msg:`${t.name} — Just Restocked${sfx}`};
  }
  const sfx = t.stock != null && t.stock > 0 ? ` (x${t.stock})` : "";
  return {icon:"✔", cls:"found", msg:`${t.name} — In Stock${sfx}`};
}

function wishlistSummary(tracked){
  if(!tracked || !tracked.length) return "No wishlist items";
  return tracked.map(t => formatTrackedItem(t).msg).join(" · ");
}

function buildScanBlock(ev, time, nested){
  const cap = s => s ? s.charAt(0).toUpperCase() + s.slice(1) : "";
  const DISPLAY = {special:"Divine Items"};
  const cat = ev.category || "";
  const label = DISPLAY[cat] || cap(cat);
  const matches = (ev.tracked || []).map(formatTrackedItem);
  const tracked = ev.tracked || [];
  return {
    time,
    category: ev.category,
    title: label,
    summary: nested ? wishlistSummary(tracked)
      : ((ev.items_scanned || 0) + " items · " + (tracked.length || 0) + " wishlist"),
    matches,
    nested: !!nested,
    expanded: !nested,
  };
}

function findActiveRestock(){
  for(let i = 0; i < activityLog.length; i++){
    if(activityLog[i].type === "restock") return activityLog[i];
  }
  return null;
}

function findActiveVendor(){
  for(let i = 0; i < activityLog.length; i++){
    if(activityLog[i].type === "vendor") return activityLog[i];
  }
  return null;
}

/** Newest shop-check group (vendor or restock) — scans nest under this row. */
function findActiveScanParent(){
  for(let i = 0; i < activityLog.length; i++){
    const g = activityLog[i];
    if(g.type === "vendor" || g.type === "restock") return g;
  }
  return null;
}

function formatEtaSec(sec){
  if(sec == null || sec < 0) return "";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function playRestockChime(){
  ensureSettings();
  if(!S.settings.sound_alert) return;
  try{
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = 880;
    o.connect(g);
    g.connect(ctx.destination);
    g.gain.setValueAtTime(0.12, ctx.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.45);
    o.start(ctx.currentTime);
    o.stop(ctx.currentTime + 0.5);
  }catch(e){}
}

async function refreshRestockEta(a){
  try{
    const api = a || await apiReady();
    _restockEta = await api.get_restock_eta();
  }catch(e){}
}

function applyRestockEta(eta){
  if(eta) _restockEta = eta;
}

async function fireRestockAlerts(){
  ensureSettings();
  playRestockChime();
  try{
    const a = await apiReady();
    if(S.settings.desktop_alert) await a.restock_alert();
  }catch(e){}
}

const DEBUG_EVENT_TYPES = new Set([
  "scan_started", "scan_complete", "item_found", "item_state_changed", "out_of_stock",
]);

async function processBackendEventsFromData(data){
  if(!data || !data.events || !data.events.length) return;
  for(const ev of data.events){
    _lastEventSeq = ev.seq;
    if(DEBUG_EVENT_TYPES.has(ev.type)) continue;

    const time = new Date((ev.ts||0)*1000).toLocaleTimeString("en-GB",
      {hour:"2-digit",minute:"2-digit",second:"2-digit"});

    if(ev.type === "restock_detected"){
      if(ev.source === "inventory_diff") continue;
      _countdownReset = ev.ts || Math.floor(Date.now()/1000);
      _displayRemaining = COOLDOWN_SEC;
      _targetRemaining = COOLDOWN_SEC;
      fireRestockAlerts();
      refreshRestockEta();
      // Vendor mode uses "Shop check" as the activity row; still play alerts above.
      if(S.settings && S.settings.vendor_mode) continue;
      activityLog.forEach(g=>{ if(g.type === "restock") g.expanded = false; });
      activityLog.unshift({time, msg:"Restock detected", type:"restock", scans:[], expanded:true});
    } else if(ev.type === "vendor_check"){
      activityLog.forEach(g=>{ if(g.type === "vendor" || g.type === "restock") g.expanded = false; });
      activityLog.unshift({time, msg:"Shop check", type:"vendor", scans:[], expanded:true});
    } else if(ev.type === "scan_result"){
      const parent = findActiveScanParent();
      const nested = !!parent;
      const block = buildScanBlock(ev, time, nested);
      if(parent){
        parent.scans = parent.scans || [];
        parent.scans.push(block);
        block.expanded = true;
      } else {
        activityLog.unshift({time, type:"scan", block});
      }
      if(ev.category){
        recordCatActivity(ev.category);
        markCategoryItemsSeen(ev.category);
        flashItemsInCategory(ev.category);
        (ev.tracked||[]).forEach(t=>flashItemByName(ev.category, t.name));
      }
    } else if(ev.type === "purchase_success"){
      const tag = (ev.tag || "").toLowerCase();
      let msg;
      if(tag.includes("unconfirmed")){
        msg = "Purchase unconfirmed — " + ev.name + " ×" + ev.qty;
      } else if(tag.includes("insufficient")){
        msg = "Could not buy — " + ev.name;
      } else if(ev.dry || tag.includes("would buy")){
        msg = "[Test] would buy — " + ev.name + " ×" + ev.qty;
      } else {
        msg = "Purchase success — " + ev.name + " ×" + ev.qty;
      }
      activityLog.unshift({time, msg, type:"purchase", children:[]});
      if(ev.category) flashItemByName(ev.category, ev.name);
    } else if(ev.type === "ocr_ready"){
      const msg = ev.ok ? "OCR engine ready — RapidOCR connected" : ("OCR failed — " + (ev.error || "check install"));
      activityLog.unshift({time, msg, type: ev.ok ? "scan" : "fail", children:[]});
    } else if(ev.type === "check_failed"){
      const msg = "Check failed — " + (ev.error || "see bot log");
      activityLog.unshift({time, msg, type:"fail", children:[]});
    }
  }
  if(activityLog.length > 30) activityLog.length = 30;
  renderActivity(true);
  renderCategories();
}

async function processBackendEvents(a){
  let data;
  try{ data = await a.bot_events(_lastEventSeq); }catch(e){ return; }
  await processBackendEventsFromData(data);
}

function scanBlockPreviewHtml(block){
  const m = block.matches || [];
  if(!m.length) return (block.summary || "Scan complete");
  return m.map(x =>
    `<div class="act-match ${x.cls}"><span class="act-icon">${x.icon}</span><span>${x.msg}</span></div>`
  ).join("");
}

function scanBlockPreview(block){
  const m = block.matches || [];
  if(m.length) return m.map(x => x.msg).join(" · ");
  return block.summary || "Scan complete";
}

function renderScanBlock(block, nested, gi, bi){
  // Under Shop check / Restock: always show colored wishlist rows (same as Military).
  const canToggle = !nested;
  const open = canToggle ? (block.expanded !== false) : true;
  const chev = canToggle ? (open ? "▾" : "▸") : "";
  const matchHtml = (block.matches || []).map(m=>
    `<div class="act-match ${m.cls}"><span class="act-icon">${m.icon}</span><span>${m.msg}</span></div>`
  ).join("");
  const trackedSection = matchHtml
    ? `<div class="act-tracked">${matchHtml}</div>`
    : "";
  const preview = (canToggle && !open)
    ? `<div class="act-preview">${scanBlockPreviewHtml(block)}</div>`
    : "";
  const toggle = (canToggle && gi != null && bi != null)
    ? ` data-toggle="scan" data-gi="${gi}" data-bi="${bi}"` : "";
  const detail = nested
    ? trackedSection
    : `<div class="act-layer med">${block.summary}</div>${trackedSection}`;
  return `<div class="act-scan-block${nested?" nested":""}">
    <div class="act-row act-scan-head${canToggle?" act-clickable":""}"${toggle}>
      ${chev ? `<span class="act-chevron">${chev}</span>` : `<span class="act-chevron" style="visibility:hidden">▸</span>`}
      <span class="act-dot scan"></span>
      <div class="act-body">
        <span class="act-time">${block.time}</span>
        <span class="act-msg">${block.title}</span>
      </div>
    </div>
    ${preview}
    <div class="act-scan-body${open?"":" collapsed"}">
      ${detail}
    </div>
  </div>`;
}

let _activityWired = false;
function wireActivityFeed(){
  if(_activityWired) return;
  _activityWired = true;
  $("activityFeed").addEventListener("click", e=>{
    const el = e.target.closest("[data-toggle]");
    if(!el) return;
    const gi = parseInt(el.dataset.gi, 10);
    const g = activityLog[gi];
    if(!g) return;
    if(el.dataset.toggle === "restock" || el.dataset.toggle === "vendor"){
      g.expanded = g.expanded === false;
    } else if(el.dataset.toggle === "scan"){
      const bi = parseInt(el.dataset.bi, 10);
      if(g.scans && g.scans[bi]) g.scans[bi].expanded = g.scans[bi].expanded === false;
    }
    renderActivity(false);
  });
}

function renderActivity(scrollToLatestScan){
  const host = $("activityFeed");
  host.innerHTML = activityLog.map((g, gi)=>{
    if(g.type === "restock" || g.type === "vendor"){
      const open = g.expanded !== false;
      const chev = open ? "▾" : "▸";
      const n = (g.scans||[]).length;
      const scans = open
        ? `<div class="act-scans-wrap">${(g.scans||[]).map((b,bi)=>renderScanBlock(b,true,gi,bi)).join("")}</div>`
        : `<div class="act-collapsed-hint">${n} scan${n===1?"":"s"} — click to expand</div>`;
      const cls = g.type === "vendor" ? "act-vendor" : "act-restock";
      return `<div class="act-group ${cls}">
        <div class="act-row act-head act-clickable" data-toggle="${g.type}" data-gi="${gi}">
          <span class="act-chevron">${chev}</span>
          <span class="act-dot restock"></span>
          <div class="act-body"><span class="act-time">${g.time}</span><span class="act-msg">${g.msg}</span></div>
        </div>${scans}</div>`;
    }
    if(g.type === "scan" && g.block){
      return `<div class="act-group">${renderScanBlock(g.block, false, gi, 0)}</div>`;
    }
    return `<div class="act-group">
      <div class="act-row act-head">
        <span class="act-dot ${g.type}"></span>
        <div class="act-body"><span class="act-time">${g.time}</span><span class="act-msg">${g.msg}</span></div>
      </div></div>`;
  }).join("");
  if(scrollToLatestScan){
    requestAnimationFrame(()=>{
      const latest = host.querySelector(".act-restock .act-scan-block:last-of-type")
        || host.querySelector(".act-vendor .act-scan-block:last-of-type")
        || host.querySelector(".act-scan-block");
      if(latest) latest.scrollIntoView({block:"end", behavior:"smooth"});
    });
  }
  renderOverlayFeed();
}

async function refreshInventory(a){
  let inv;
  try{ inv = await a.bot_inventory(); }catch(e){ return; }
  liveInventory = inv || {items:{}, categories:{}};
  if(inv && inv.categories){
    for(const [k,v] of Object.entries(inv.categories)){
      if(v.last_scan_ts) catLastScan[k] = v.last_scan_ts * 1000;
    }
  }
  updateItemStatus();
}

function updateHeroRing(mode){
  const ring = $("heroRing");
  ring.className = "hero-ring " + (mode || "idle");
}

function updateMicroTick(remaining, running, state){
  const el = $("microTick");
  if(running && (state === "watching" || state === "idle") && _restockEta && _restockEta.next_in_sec != null){
    el.textContent = "Next restock ~" + formatEtaSec(_restockEta.next_in_sec);
    el.classList.add("on");
    return;
  }
  if(running && state === "watching" && remaining < 15){
    el.textContent = MICRO_TICKS[_microIdx % MICRO_TICKS.length];
    el.classList.add("on");
  } else {
    el.classList.remove("on");
  }
}

function startMicroRotate(){
  if(_microInterval) return;
  _microInterval = setInterval(()=>{ _microIdx++; }, 1600);
}

function stopMicroRotate(){
  if(_microInterval){ clearInterval(_microInterval); _microInterval = null; }
  $("microTick").classList.remove("on");
}

function startTimerAnim(){
  if(_timerRaf) return;
  const tick = ()=>{
    _displayRemaining += (_targetRemaining - _displayRemaining) * 0.18;
    const el = $("heroTimer");
    if(el.classList.contains("running")){
      const v = Math.max(0, Math.round(_displayRemaining));
      el.textContent = String(v).padStart(2,"0") + "s";
      el.classList.toggle("urgent", v <= 5 && v > 0);
      updateMicroTick(v, true, _currentBotState);
    }
    _timerRaf = requestAnimationFrame(tick);
  };
  _timerRaf = requestAnimationFrame(tick);
}

function stopTimerAnim(){
  if(_timerRaf){ cancelAnimationFrame(_timerRaf); _timerRaf = null; }
}

function updateHeroTimer(st, running){
  const el = $("heroTimer");
  if(!running){
    el.textContent = "Waiting";
    el.className = "hero-timer idle";
    updateHeroRing("idle");
    stopTimerAnim();
    return;
  }
  const s = st.state || "idle";
  const phase = st.phase || s;
  _currentBotState = phase === "scanning" || phase === "matching" ? phase : s;
  if(s === "restock" || phase === "scanning"){
    el.textContent = phase === "scanning" && st.action ? st.action.replace(/…$/,"") : "Restock!";
    el.className = "hero-timer restock";
    updateHeroRing("restock");
    stopTimerAnim();
    $("microTick").textContent = MICRO_TICKS[_microIdx % MICRO_TICKS.length];
    $("microTick").classList.add("on");
    return;
  }
  if(s === "reading" || s === "buying" || phase === "matching"){
    el.textContent = (st.action||"Active").replace(/…$/,"");
    el.className = "hero-timer active";
    updateHeroRing("active");
    stopTimerAnim();
    $("microTick").textContent = MICRO_TICKS[_microIdx % MICRO_TICKS.length];
    $("microTick").classList.add("on");
    return;
  }
  $("microTick").classList.remove("on");
  if(st.cooldown_sec) COOLDOWN_SEC = st.cooldown_sec;
  const anchor = st.countdown_reset || st.ts || _countdownReset || 0;
  const cooldown = st.cooldown_sec || COOLDOWN_SEC;
  if(anchor > 0){
    const elapsed = Math.floor(Date.now()/1000 - anchor);
    _targetRemaining = Math.max(0, cooldown - (elapsed % cooldown));
  } else {
    _targetRemaining = cooldown;
  }
  el.className = "hero-timer running";
  updateHeroRing("running");
  startTimerAnim();
}

function updateLiveDot(running, state, phase){
  const dot = $("liveDot");
  dot.className = "live-dot";
  if(!running) return;
  if(state === "restock" || phase === "scanning") dot.classList.add("restock");
  else dot.classList.add("watching");
}

function updateBotState(st, running, pollExtra){
  const phase = st.phase || st.state || "idle";
  const label = STATE_LABEL[phase] || STATE_LABEL[st.state] || (running ? "Running" : "Idle");
  $("botState").textContent = running ? label : "Idle";
  updateLiveDot(running, st.state || "idle", phase);
  const eng = $("engineStatus");
  if(!running){
    eng.textContent = "";
    eng.className = "state-sub";
    return;
  }
  const parts = [];
  if(st.ocr_ready === true) parts.push("OCR ready");
  else if(st.ocr_ready === false) parts.push("OCR failed");
  if(st.roblox_ok === true) parts.push("Roblox connected");
  else if(st.roblox_ok === false) parts.push("Roblox not found");
  if(pollExtra && pollExtra.heartbeat_stale) parts.push("Bot may be stuck");
  else if(st.heartbeat_ts){
    const age = Math.floor(Date.now()/1000 - st.heartbeat_ts);
    if(age >= 90 && age < 300) parts.push("heartbeat " + age + "s ago");
  }
  eng.textContent = parts.join(" · ");
  eng.className = "state-sub" + (st.ocr_ready && st.roblox_ok && !(pollExtra && pollExtra.heartbeat_stale) ? " ok" : (st.roblox_ok === false || (pollExtra && pollExtra.heartbeat_stale) ? " warn" : ""));
}

function updateOverlay(st, running, extra){
  if(!_overlayCompact || !$("overlay") || $("overlay").classList.contains("hidden")) return;
  const phase = (st && (st.phase || st.state)) || "watching";
  $("ovState").textContent = running ? (STATE_LABEL[phase] || "Watching") : "Idle";
  $("ovAct").textContent = running
    ? ((st && st.action) || "Waiting for restock…").replace(/…$/,"")
    : "Bot stopped";
  const parts = [];
  if(st && st.checks != null) parts.push(st.checks + " check" + (st.checks === 1 ? "" : "s"));
  if(_restockEta && _restockEta.next_in_sec != null) parts.push("next ~" + formatEtaSec(_restockEta.next_in_sec));
  if(extra && extra.heartbeat_stale) parts.push("no heartbeat — bot may be stuck");
  else if(st && st.heartbeat_ts){
    const age = Math.max(0, Math.floor(Date.now()/1000 - st.heartbeat_ts));
    if(age < 120) parts.push("alive");
  }
  $("ovMeta").textContent = parts.join(" · ");
  const dot = document.querySelector("#overlay .ov-dot");
  if(dot){
    if(!running) dot.style.background = "var(--muted)";
    else if(st && st.roblox_ok === false) dot.style.background = "var(--danger)";
    else if(phase === "scanning" || phase === "reading" || phase === "restock") dot.style.background = "var(--accent)";
    else dot.style.background = "var(--success)";
  }
  renderOverlayFeed();
}

function overlayFeedRows(maxRows){
  const rows = [];
  for(let i = 0; i < activityLog.length && rows.length < maxRows; i++){
    const g = activityLog[i];
    if(g.type === "vendor" || g.type === "restock"){
      rows.push({time: g.time, msg: g.msg || "Shop check", dot: g.type});
      for(const scan of (g.scans || [])){
        if(rows.length >= maxRows) break;
        for(const m of (scan.matches || [])){
          if(rows.length >= maxRows) break;
          rows.push({time: scan.time || g.time, msg: m.msg, dot: "scan", cls: m.cls, sub: true});
        }
        if((!scan.matches || !scan.matches.length) && rows.length < maxRows){
          const preview = scanBlockPreview(scan);
          if(preview && preview !== "Scan complete"){
            rows.push({time: scan.time || g.time, msg: preview, dot: "scan", sub: true});
          }
        }
      }
      continue;
    }
    if(g.msg && rows.length < maxRows){
      rows.push({time: g.time, msg: g.msg, dot: g.type || "info"});
    }
  }
  return rows.slice(0, maxRows);
}

function renderOverlayFeed(){
  const host = $("ovFeed");
  if(!host) return;
  if(!_overlayCompact){
    host.innerHTML = "";
    return;
  }
  const rows = overlayFeedRows(6);
  if(!rows.length){
    host.innerHTML = '<div class="ov-feed-empty">Waiting for activity…</div>';
    return;
  }
  host.innerHTML = rows.map(r=>`<div class="ov-feed-row${r.sub?" sub":""}">
    <span class="ov-feed-dot ${r.dot||"info"}"></span>
    <span class="ov-feed-time">${r.time||""}</span>
    <span class="ov-feed-msg${r.cls?" "+r.cls:""}">${r.msg||""}</span>
  </div>`).join("");
}

async function enterCompactMode(){
  ensureSettings();
  if(S.settings.mini_overlay === false) return;
  _overlayCompact = true;
  $("app").classList.add("hidden");
  $("overlay").classList.remove("hidden");
  document.body.classList.add("compact-mode");
  syncCompactBtn();
  try{
    const a = await apiReady();
    await a.enter_overlay();
    if(S.settings.tray_on_run !== false) await a.ensure_tray();
  }catch(e){}
  updateOverlay({}, true, {});
}

async function expandFromOverlay(){
  _overlayCompact = false;
  $("overlay").classList.add("hidden");
  $("app").classList.remove("hidden");
  document.body.classList.remove("compact-mode");
  syncCompactBtn();
  try{
    const a = await apiReady();
    await a.exit_overlay();
  }catch(e){}
}
window.expandFromOverlay = expandFromOverlay;

function syncCompactBtn(){
  const btn = $("compactBtn");
  if(!btn) return;
  const running = $("runBtn") && $("runBtn").disabled;
  btn.classList.toggle("hidden", !running || _overlayCompact);
}

async function exitCompactMode(){
  if(!_overlayCompact) return;
  await expandFromOverlay();
}

function botCrashedNotice(){
  const time = new Date().toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  activityLog.unshift({time, msg:"Bot stopped unexpectedly — check logs/bot_*.log", type:"fail", children:[]});
  if(activityLog.length > 30) activityLog.length = 30;
  renderActivity(false);
  showSaveToast(false, "Bot stopped — see logs");
}

function setRunning(r, opts){
  $("runBtn").disabled = r;
  $("stopBtn").disabled = !r;
  if(r){
    _botWasRunning = true;
    startMicroRotate();
    startHeartbeat();
  } else {
    if(_botWasRunning && opts && opts.crashed) botCrashedNotice();
    _botWasRunning = false;
    exitCompactMode();
    $("heroTimer").textContent = "Waiting";
    $("heroTimer").className = "hero-timer idle";
    updateHeroRing("idle");
    updateLiveDot(false);
    stopStatusPoll();
    stopTimerAnim();
    stopMicroRotate();
    stopHeartbeat();
  }
  updateBotState({}, r);
  syncCompactBtn();
}

async function statusTick(){
  if(_statusTickBusy) return;
  _statusTickBusy = true;
  try{
    const a = await apiReady();
    let data;
    try{ data = await a.poll_ui(_lastEventSeq); }catch(e){ return; }
    const running = !!(data && data.running);
    if(!running){
      if(_botWasRunning){
        setRunning(false, {crashed: true});
      } else {
        setRunning(false);
      }
      return;
    }
    _botWasRunning = true;
    if(data.events && data.events.length){
      await processBackendEventsFromData(data);
    }
    if(data.inventory){
      liveInventory = data.inventory;
      if(data.inventory.categories){
        for(const [k,v] of Object.entries(data.inventory.categories)){
          if(v.last_scan_ts) catLastScan[k] = v.last_scan_ts * 1000;
        }
      }
      updateItemStatus();
    }
    if(data.restock_eta) applyRestockEta(data.restock_eta);
    const st = (data && data.status) || {};
    updateHeroTimer(st, true);
    updateBotState(st, true, data);
    updateOverlay(st, true, data);
  } finally {
    _statusTickBusy = false;
  }
}

function startStatusPoll(){
  if(_statusPoll) return;
  statusTick();
  _statusPoll = setInterval(statusTick, 700);
  setInterval(updateItemStatus, 1000);
}

function stopStatusPoll(){
  if(_statusPoll){ clearInterval(_statusPoll); _statusPoll = null; }
}

let _heartbeatTimer = null;
function startHeartbeat(){
  if(_heartbeatTimer) return;
  const pulse = ()=>{
    const app = $("app");
    app.classList.remove("heartbeat");
    void app.offsetWidth;
    app.classList.add("heartbeat");
    _heartbeatTimer = setTimeout(pulse, 10000 + Math.random()*5000);
  };
  _heartbeatTimer = setTimeout(pulse, 12000);
}
function stopHeartbeat(){
  if(_heartbeatTimer){ clearTimeout(_heartbeatTimer); _heartbeatTimer = null; }
}

function setProgress(pct, msg){
  pct = Math.max(0, Math.min(100, pct));
  $("ldFill").style.width = pct + "%";
  $("ldPct").textContent = Math.round(pct) + "%";
  if(msg !== undefined) $("ldMsg").textContent = msg;
}

function showLoading(){
  document.querySelector(".ld").classList.remove("err");
  $("ldTitle").textContent = "Launching bot…";
  $("ldHint").style.display = "";
  setProgress(0, "Starting…");
  $("loading").classList.remove("hidden");
}

function hideLoading(){ $("loading").classList.add("hidden"); }

function loadingError(msg){
  document.querySelector(".ld").classList.add("err");
  $("ldTitle").textContent = "Couldn't start";
  $("ldHint").style.display = "none";
  $("ldMsg").textContent = msg || "Error";
}

async function runBot(){
  const a = await apiReady();
  await window.flushSave();
  showLoading();
  _lastEventSeq = 0;
  activityLog = [];
  liveInventory = {items:{}, categories:{}};
  renderActivity();
  try{
    const t = await a.get_timings();
    if(t.cooldown_sec) COOLDOWN_SEC = t.cooldown_sec;
  }catch(e){}
  try{ await a.launch(S); }catch(e){ loadingError("Launch failed"); setTimeout(hideLoading, 2600); return; }
  let lastPct = 0, stable = 0, wasRunning = false;
  const t = setInterval(async()=>{
    let ls;
    try{ ls = await a.launch_status(); }catch(e){ return; }
    if(ls.phase === "error"){ clearInterval(t); loadingError(ls.msg||"Error"); setTimeout(hideLoading, 3200); return; }
    if(ls.running) wasRunning = true;
    else if(wasRunning){ clearInterval(t); loadingError("Bot stopped on startup — check the bot console."); setTimeout(hideLoading, 3600); return; }
    let pct = ls.pct || 0;
    if(ls.running){ stable++; pct = Math.max(pct, Math.min(97, lastPct + 1.6)); }
    lastPct = Math.max(lastPct, pct);
    setProgress(lastPct, ls.msg);
    if(ls.running){
      let st = {};
      try{ st = await a.bot_status(); }catch(e){}
      const live = st && st.state && st.state !== "stopped" && st.state !== "idle";
      if(live || stable > 60){
        clearInterval(t);
        setProgress(100, "Ready");
        setTimeout(async()=>{
          hideLoading();
          setRunning(true);
          startStatusPoll();
          await enterCompactMode();
        }, 350);
      }
    }
  }, 500);
}

async function stopBot(){
  try{ const a = await apiReady(); await a.stop(); }catch(e){}
  setRunning(false);
  const time = new Date().toLocaleTimeString("en-GB",{hour:"2-digit",minute:"2-digit",second:"2-digit"});
  activityLog.unshift({time, msg:"Bot stopped", type:"info", children:[]});
  renderActivity();
  if(_showLogs) refreshLogFeed();
}

window.onHotkeyStop = stopBot;

function wireOverlayControls(){
  if($("ovStop")) $("ovStop").onclick = ()=> stopBot();
  if($("ovExpand")) $("ovExpand").onclick = ()=> expandFromOverlay();
}

function toggleLogsPanel(){
  _showLogs = !_showLogs;
  $("logsBtn").classList.toggle("logs-on", _showLogs);
  $("activityFeed").classList.toggle("hidden", _showLogs);
  $("logTabs").classList.toggle("hidden", !_showLogs);
  $("logFeed").classList.toggle("hidden", !_showLogs);
  $("openLogFolder").classList.toggle("hidden", !_showLogs);
  $("panelTitle").textContent = _showLogs ? "Logs" : "Activity";
  if(_showLogs){
    refreshLogFeed();
    if(_logPoll) clearInterval(_logPoll);
    _logPoll = setInterval(refreshLogFeed, 1500);
  } else if(_logPoll){
    clearInterval(_logPoll);
    _logPoll = null;
  }
}

function setLogView(view){
  _logView = view;
  document.querySelectorAll(".log-tab").forEach(btn=>{
    btn.classList.toggle("active", btn.dataset.log === view);
  });
  refreshLogFeed();
}

async function refreshLogFeed(){
  try{
    const a = await apiReady();
    const el = $("logFeed");
    let data;
    if(_logView === "purchases"){
      data = await a.get_purchase_log(80);
      el.textContent = "# purchases.jsonl\n\n" + (data.lines || []).join("\n");
    } else if(_logView === "timeline"){
      data = await a.get_timeline_log(80);
      el.textContent = "# restock_timeline.jsonl\n\n" + (data.lines || []).join("\n");
    } else {
      data = await a.get_bot_log(120);
      const header = data.path ? "# " + data.path + "\n\n" : "";
      el.textContent = header + (data.lines || []).join("\n");
    }
    el.scrollTop = el.scrollHeight;
  }catch(e){}
}

function wireApp(){
  $("runBtn").onclick = runBot;
  $("stopBtn").onclick = stopBot;
  if($("compactBtn")) $("compactBtn").onclick = ()=> enterCompactMode();
  wireSettingsModal();
  wireUpdateModal();
  wireActivityFeed();
  wireOverlayControls();
  $("logsBtn").onclick = toggleLogsPanel;
  document.querySelectorAll(".log-tab").forEach(btn=>{
    btn.onclick = ()=>setLogView(btn.dataset.log);
  });
  $("openLogFolder").onclick = ()=>apiReady().then(a=>a.open_logs_folder());
  setInterval(async()=>{
    try{
      if(!_statusPoll){
        const a = await apiReady();
        const r = await a.is_running();
        if(r.running && $("runBtn").disabled === false) setRunning(true);
        if(r.running){
          startStatusPoll();
          if(!_overlayCompact) await enterCompactMode();
        }
      }
    }catch(e){}
  }, 2500);
}

function initDrag(){
  document.querySelectorAll(".pywebview-drag-region").forEach(el=>{
    el.addEventListener("mousedown", e=>{
      if(e.button !== 0) return;
      e.preventDefault();
      try{ if(window.pywebview && window.pywebview.api && window.pywebview.api.start_drag){
        window.pywebview.api.start_drag(); }}catch(_){}
    });
  });
}

function applyTitleLogo(){
  apiReady().then(a=>a.get_logo_data_uri()).then(uri=>{
    const el = $("titleLogo");
    if(el && uri) el.src = uri;
  }).catch(()=>{});
}

function start(){
  applyTitleLogo();
  if(!S){ S = {dry_run:true, cats:[], running:false}; }
  ensureSettings();
  if(S.settings && S.settings.cooldown_sec) COOLDOWN_SEC = S.settings.cooldown_sec;
  $("minBtn").onclick = ()=>apiReady().then(a=>a.minimize());
  $("closeBtn").onclick = async ()=>{
    try{ await window.flushSave(); }catch(e){}
    try{ const a = await apiReady(); await a.close_app(); }catch(e){}
  };
  initDrag();
  wireApp();
  renderApp();
  setRunning(!!S.running);
  apiReady().then(async a=>{
    try{
      const t = await a.get_timings();
      if(t && t.cooldown_sec) COOLDOWN_SEC = t.cooldown_sec;
      await refreshInventory(a);
      await refreshRestockEta(a);
      await checkUpdatesOnStart();
    }catch(e){}
  });
}
start();
</script></body></html>"""


def _f7_loop(api):
    """Global F7 = stop the bot; also pump tray menu commands."""
    prev = False
    while True:
        try:
            api.pump_tray()
        except Exception:
            pass
        down = bool(_user32.GetAsyncKeyState(0x76) & 0x8000)   # VK_F7
        if down and not prev and api._running():
            try:
                if webview.windows:
                    webview.windows[0].evaluate_js("window.onHotkeyStop && window.onHotkeyStop()")
            except Exception:
                pass
        prev = down
        time.sleep(0.04)


def main():
    if not _single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                0, f"{APP_NAME} is already running.\n\nCheck your taskbar.",
                APP_NAME, 0x10 | 0x40000)     # MB_ICONERROR | MB_TOPMOST
        except Exception:
            pass
        raise SystemExit(0)
    api = Api()
    # The JS bridge connects late, so bake the boot state into the HTML; the JS side
    # polls apiReady() before making bridge calls.
    boot = api.get_state()
    html = (UI_HTML.replace("__ICONS__", json.dumps(ICONS))
            .replace("__BOOT_STATE__", json.dumps(boot)))
    window = webview.create_window(APP_NAME, html=html, js_api=api,
                                   width=APP_SIZE[0], height=APP_SIZE[1],
                                   resizable=False, frameless=True, easy_drag=False,
                                   background_color="#0B0F17")

    def _on_closing():
        # Never call evaluate_js here — it deadlocks the WebView2 thread while
        # Python bridge calls are in flight, which freezes the window and blocks X.
        api._terminate_bot()
        api.tray_stop()

    try:
        window.events.closing += _on_closing
    except Exception:
        pass
    threading.Thread(target=_f7_loop, args=(api,), daemon=True).start()
    icon = LOGO_ICO_PATH if os.path.isfile(LOGO_ICO_PATH) else None
    webview.start(icon=icon)


if __name__ == "__main__":
    main()
