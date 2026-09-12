"""Visible Windows workbench with an OS-owned, project-directory single instance.

The localhost server remains usable without this optional host for automated QA.
The host never exposes a Python object or a filesystem API to page Javascript.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import threading
import time


from app_metadata import TITLE


def instance_key(projects: Path) -> str:
    canonical = os.path.normcase(str(Path(projects).resolve()))
    return "StarPoint.CharacterStudio." + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class WindowsInstance:
    """Kernel objects disappear after a crash; there is no stale PID/lock file."""

    def __init__(self, projects: Path):
        self.key = instance_key(projects)
        self.mutex = None
        self.event = None
        self.owner = False
        if os.name != "nt":
            self.owner = True
            return
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateEventW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
        self.kernel.SetEvent.argtypes = [wintypes.HANDLE]
        self.kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype = wintypes.DWORD
        self.user.SetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.HANDLE]
        self.user.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user.GetPropW.restype = wintypes.HANDLE
        self.user.RemovePropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user.IsIconic.argtypes = [wintypes.HWND]
        self.user.SetForegroundWindow.argtypes = [wintypes.HWND]
        self.user.BringWindowToTop.argtypes = [wintypes.HWND]
        self.mutex = self.kernel.CreateMutexW(None, True, "Local\\" + self.key)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.owner = ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS
        self.event = self.kernel.CreateEventW(None, False, False, "Local\\" + self.key + ".Activate")
        if not self.event:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def register_window(self, hwnd: int):
        if os.name == "nt" and not self.user.SetPropW(hwnd, self.key, 1):
            raise ctypes.WinError(ctypes.get_last_error())

    def unregister_window(self, hwnd: int):
        if os.name == "nt":
            self.user.RemovePropW(hwnd, self.key)

    def activate(self) -> bool:
        """The second, user-launched process can foreground the existing HWND."""
        if os.name != "nt":
            return False
        found = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def inspect(hwnd, _):
            if self.user.GetPropW(hwnd, self.key):
                found.append(hwnd)
                return False
            return True

        self.user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        self.user.EnumWindows(inspect, 0)
        if not found:
            return False
        hwnd = found[0]
        if self.user.IsIconic(hwnd):
            self.user.ShowWindow(hwnd, 9)  # SW_RESTORE
        self.user.BringWindowToTop(hwnd)
        self.user.SetForegroundWindow(hwnd)
        return True

    def notify_existing(self, wait_seconds=3.0):
        if self.event:
            self.kernel.SetEvent(self.event)
            deadline = time.monotonic() + wait_seconds
            while time.monotonic() < deadline:
                if self.activate():
                    return
                time.sleep(.1)

    def wait_activation(self, milliseconds=250) -> bool:
        if not self.event:
            time.sleep(milliseconds / 1000)
            return False
        return self.kernel.WaitForSingleObject(self.event, milliseconds) == 0

    def close(self):
        if self.event:
            self.kernel.CloseHandle(self.event)
            self.event = None
        if self.mutex:
            if self.owner:
                self.kernel.ReleaseMutex(self.mutex)
            self.kernel.CloseHandle(self.mutex)
            self.mutex = None


class CloseGate:
    """Do not destroy a window until the page has saved and shut its server down."""

    def __init__(self, dispatch):
        self.dispatch = dispatch
        self.pending = False
        self.allowed = False

    def request(self):
        if self.allowed:
            return True
        if not self.pending:
            self.pending = True
            # WinForms fires FormClosing on its UI thread. Never block that
            # thread waiting for WebView2 to execute a Javascript request.
            threading.Thread(target=self.dispatch, daemon=True).start()
        return False

    def cancel(self):
        self.pending = False


def show_error(message):
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, str(message), TITLE, 0x10)
    else:
        print(message)


def run_desktop(server, address: str, instance: WindowsInstance, base: Path):
    """Block until the native window and the exact local server are both closed."""
    import webview

    # Windows owns the taskbar entry and groups it independently of Python or Edge.
    if os.name == "nt":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StarPoint.CharacterStudio")
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["ALLOW_FILE_URLS"] = False
    window = webview.create_window(TITLE, address, width=1440, height=940,
                                  min_size=(860, 620), background_color="#191c24",
                                  confirm_close=False)
    stopped = threading.Event()
    page_ready = threading.Event()
    hwnd = [0]
    initialization_error = []

    def dispatch_close():
        if not page_ready.wait(8):
            gate.cancel()
            show_error("页面尚未完成加载，请稍候再关闭窗口。")
            return
        try:
            # run_js executes a fixed script as-is and preserves the strict CSP.
            window.run_js("window.dispatchEvent(new Event('studio-desktop-close'));")
        except Exception as exc:
            gate.cancel()
            show_error("无法完成保存，已保留窗口。请先保存或导出工程再关闭。\n" + str(exc))

    gate = CloseGate(dispatch_close)
    server.desktop_close_cancel = gate.cancel
    server.desktop_ready = page_ready.set
    server.desktop_mode = True
    window.events.closing += gate.request

    def shown():
        native = window.native
        hwnd[0] = int(native.Handle.ToInt64())
        instance.register_window(hwnd[0])
        # WinForms already extracts the embedded EXE icon on its UI thread.
        # Its shown event runs this callback on a worker thread: assigning Icon
        # here can deadlock against WebView2.Focus during initial navigation.

    def initialized(renderer):
        if renderer != "edgechromium":
            initialization_error.append("请安装 Microsoft Edge WebView2 Runtime 后重新打开角色工坊。")
            return False

    def closed():
        stopped.set()
        if hwnd[0]:
            instance.unregister_window(hwnd[0])
        if not server.studio_stopped.is_set():
            server.shutdown()

    def run_server():
        try:
            server.serve_forever(poll_interval=.1)
        finally:
            server.studio_stopped.set()
            gate.allowed = True
            # /api/shutdown is called only after saveNow succeeds in the page.
            if not stopped.is_set() and window.events.shown.is_set():
                window.destroy()

    def watch_activation():
        while not stopped.is_set():
            if instance.wait_activation() and not stopped.is_set():
                window.events.shown.wait(5)
                instance.activate()

    window.events.shown += shown
    window.events.initialized += initialized
    window.events.closed += closed
    worker = threading.Thread(target=run_server, daemon=True)
    worker.start()
    activation = threading.Thread(target=watch_activation, daemon=True)
    activation.start()
    try:
        # System WebView2 is used in an app-owned window; no browser profile or
        # browser tab belonging to the user is opened, closed, or inspected.
        webview.start(gui="edgechromium", private_mode=True,
                      storage_path=str(server.store.root.parent / ".webview-cache"))
        if initialization_error:
            raise RuntimeError(initialization_error[0])
    finally:
        stopped.set()
        gate.allowed = True
        if not server.studio_stopped.is_set():
            server.shutdown()
        worker.join(timeout=5)
        activation.join(timeout=1)
