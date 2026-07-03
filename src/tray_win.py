"""Windows system-tray icon for the launcher.

Posts commands (show | stop | quit) to cmd_queue; pump from the main thread.
"""
from __future__ import annotations

import queue
import threading
from ctypes import (
    WINFUNCTYPE,
    Structure,
    byref,
    c_int,
    c_long,
    c_uint,
    c_void_p,
    sizeof,
    windll,
    wintypes,
)

user32 = windll.user32
shell32 = windll.shell32
kernel32 = windll.kernel32

WM_USER = 0x0400
WM_TRAY = WM_USER + 20
WM_APP = WM_USER + 21
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_DESTROY = 0x0002

NIM_ADD = 0x00
NIM_DELETE = 0x02
NIF_MESSAGE = 0x01
NIF_ICON = 0x02
NIF_TIP = 0x04

IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x0010
LR_DEFAULTSIZE = 0x0040

MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_BOTTOMALIGN = 0x0020
TPM_LEFTALIGN = 0x0000
TPM_RETURNCMD = 0x0100

ID_SHOW = 1001
ID_STOP = 1002
ID_EXIT = 1003


class NOTIFYICONDATAW(Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
    ]


class TrayWin:
    def __init__(self, icon_path: str, tip: str = "MiniWar AFK Bot"):
        self.icon_path = icon_path
        self.tip = (tip or "MiniWar AFK Bot")[:127]
        self.cmd_queue: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._hwnd = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="tray-win", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=3.0)

    def stop(self) -> None:
        h = self._hwnd
        if h:
            try:
                user32.PostMessageW(h, WM_APP, 0, 0)
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._hwnd = None

    def _run(self) -> None:
        WNDPROC = WINFUNCTYPE(c_long, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        hinst = kernel32.GetModuleHandleW(None)

        class WNDCLASSW(Structure):
            _fields_ = [
                ("style", c_uint),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", c_int),
                ("cbWndExtra", c_int),
                ("hInstance", c_void_p),
                ("hIcon", c_void_p),
                ("hCursor", c_void_p),
                ("hbrBackground", c_void_p),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAY:
                if lparam == WM_LBUTTONUP:
                    self.cmd_queue.put("show")
                elif lparam == WM_RBUTTONUP:
                    menu = user32.CreatePopupMenu()
                    user32.AppendMenuW(menu, MF_STRING, ID_SHOW, "Show panel")
                    user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                    user32.AppendMenuW(menu, MF_STRING, ID_STOP, "Stop bot")
                    user32.AppendMenuW(menu, MF_STRING, ID_EXIT, "Exit")
                    pt = wintypes.POINT()
                    user32.GetCursorPos(byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    cmd = user32.TrackPopupMenu(
                        menu,
                        TPM_BOTTOMALIGN | TPM_LEFTALIGN | TPM_RETURNCMD,
                        pt.x, pt.y, 0, hwnd, None,
                    )
                    user32.DestroyMenu(menu)
                    if cmd == ID_SHOW:
                        self.cmd_queue.put("show")
                    elif cmd == ID_STOP:
                        self.cmd_queue.put("stop")
                    elif cmd == ID_EXIT:
                        self.cmd_queue.put("quit")
                return 0
            if msg == WM_APP:
                user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                nid = NOTIFYICONDATAW()
                nid.cbSize = sizeof(NOTIFYICONDATAW)
                nid.hWnd = hwnd
                nid.uID = 1
                shell32.Shell_NotifyIconW(NIM_DELETE, byref(nid))
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wndproc = wnd_proc

        wc = WNDCLASSW()
        wc.lpfnWndProc = wnd_proc
        wc.hInstance = hinst
        wc.lpszClassName = "MiniWarAFKBotTrayV1"
        user32.RegisterClassW(byref(wc))

        hwnd = user32.CreateWindowExW(
            0, wc.lpszClassName, "MiniWarTray", 0,
            0, 0, 0, 0, None, None, hinst, None,
        )
        self._hwnd = hwnd

        hicon = user32.LoadImageW(
            None, self.icon_path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE,
        )
        if not hicon:
            hicon = user32.LoadIconW(None, IDI_APPLICATION)

        nid = NOTIFYICONDATAW()
        nid.cbSize = sizeof(NOTIFYICONDATAW)
        nid.hWnd = hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = hicon
        nid.szTip = self.tip
        shell32.Shell_NotifyIconW(NIM_ADD, byref(nid))

        self._ready.set()

        msg = wintypes.MSG()
        while user32.GetMessageW(byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(byref(msg))
            user32.DispatchMessageW(byref(msg))
