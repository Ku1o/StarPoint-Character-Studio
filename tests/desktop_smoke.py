"""Actual owned Windows/WebView2 UI, duplicate launch and save-on-close QA.

Uses an isolated project directory. Only the child started here is terminated on
failure; another user's existing workbench or browser is never selected.
"""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop_host import instance_key


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError("Timed out waiting for desktop state")


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    projects = output / "projects"
    port, debug_port = free_port(), free_port()
    app = Path(__file__).resolve().parents[1]
    launch = [str(args.exe.resolve())] if args.exe else [sys.executable, str(app / "studio.py")]
    launch += ["--open", "--projects", str(projects), "--templates", str(output / "no-templates"), "--port", str(port)]
    env = os.environ.copy()
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={debug_port}"
    if args.exe:
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        env["PATH"] = os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetPropW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user.GetPropW.restype = wintypes.HANDLE
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user.IsIconic.argtypes = [wintypes.HWND]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    key = instance_key(projects)
    def owned_window():
        handles = []
        @callback_type
        def check(hwnd, _):
            if user.GetPropW(hwnd, key):
                handles.append(hwnd)
            return True
        user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
        user.EnumWindows(check, 0)
        return handles[0] if handles else None
    log = (output / "desktop.log").open("w", encoding="utf-8")
    process = subprocess.Popen(launch, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    report = {"pid": process.pid, "command": launch, "projectRoot": str(projects), "errors": []}
    (output / "owned-process.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        hwnd = wait_for(owned_window, 45)
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        assert pid.value == process.pid
        assert user.IsWindowVisible(hwnd)
        assert not (user.GetWindowLongW(hwnd, -20) & 0x80), "Tool window excluded from taskbar"
        report["nativeWindow"] = {"hwnd": hwnd, "visible": True, "taskbarEligible": True}
        with sync_playwright() as pw:
            def connect():
                try:
                    return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{debug_port}", timeout=500)
                except Exception:
                    return None
            browser = wait_for(connect, 20)
            cdp = browser.new_browser_cdp_session()
            def app_page():
                report["targets"] = cdp.send("Target.getTargets")["targetInfos"]
                return next((p for context in browser.contexts for p in context.pages if p.url.rstrip("/") == f"http://127.0.0.1:{port}"), None)
            page = wait_for(app_page)
            page.on("pageerror", lambda error: report["errors"].append(str(error)))
            page.locator("#new-original").wait_for()
            # This must be a native app window with the actual strict-CSP page.
            assert page.evaluate("window.innerWidth") >= 860
            page.locator("#new-original").click()
            page.locator("#dialog-name").fill("桌面窗口验收")
            page.locator("#dialog-ok").click()
            page.locator('[data-page="identity"]').click()
            page.locator("#identity-name").wait_for()
            page.screenshot(path=str(output / "desktop-workbench.png"))
            user.ShowWindow(hwnd, 6)  # SW_MINIMIZE
            assert user.IsIconic(hwnd)
            duplicate = subprocess.Popen(launch, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            report["duplicatePid"] = duplicate.pid
            duplicate.wait(timeout=15)
            assert duplicate.returncode == 0 and process.poll() is None
            wait_for(lambda: not user.IsIconic(hwnd), 5)
            assert owned_window() == hwnd
            report["duplicateLaunch"] = "same native HWND restored; duplicate process exited"
            # A failed save must leave the window and dirty edit intact.
            page.route("**/api/save", lambda route: route.abort("failed"))
            page.locator("#identity-name").fill("保存失败后不能退出")
            user.PostMessageW(hwnd, 0x10, 0, 0)
            wait_for(lambda: "保存未完成" in page.locator("#toast").inner_text(), 8)
            assert process.poll() is None and owned_window() == hwnd
            report["failedSave"] = "window retained and error shown"
            page.unroute("**/api/save")
            # Close during the 1.1s debounce; closing must flush the latest edit.
            page.locator("#identity-name").fill("关闭前最后一次修改已保存")
            identifier = page.evaluate("S.p.id")
            user.PostMessageW(hwnd, 0x10, 0, 0)
            process.wait(timeout=15)
            assert process.returncode == 0
            stored = json.loads((projects / identifier / "project.json").read_bytes())
            assert stored["name"] == "关闭前最后一次修改已保存"
            report["closeWindow"] = "latest dirty edit saved; window and parent process exited"
            assert not owned_window()
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/api/session", timeout=1)
                raise AssertionError("Server remained alive after close")
            except OSError:
                pass
            # Detach only. The app-owned runtime exited with the app itself.
            browser.close()
        assert not report["errors"], report["errors"]
    finally:
        if process.poll() is None:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], timeout=10, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.close()
        (output / "desktop-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
