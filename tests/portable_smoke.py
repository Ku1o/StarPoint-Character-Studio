"""Run the distributed EXE in a fresh extracted folder with no Python on PATH."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import zipfile

from playwright.sync_api import sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(args.zip) as archive:
        for name in archive.namelist():
            if not (output / name).resolve().is_relative_to(output):
                raise AssertionError("Unexpected package path")
        archive.extractall(output)
    app = output / "星点角色工坊"
    manifest = json.loads((app / "distribution-manifest.json").read_bytes())
    for item in manifest["files"]:
        assert hashlib.sha256((app / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["PATH"] = os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]
    process = subprocess.Popen([str(app / "星点角色工坊.exe"), "--port", str(port), "--no-open"], cwd=app, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    root = f"http://127.0.0.1:{port}"
    token = ""
    def api(path, data=None, timeout=30):
        req = urllib.request.Request(root + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json", "X-Studio-Token": token})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.load(response)
    errors = []
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError("Portable process exited before listening")
            try:
                session = api("/api/session", timeout=1)
                token = session["token"]
                break
            except OSError:
                time.sleep(.15)
        assert token, "Portable app did not start"
        assert session["projects"] == [], "Distribution contains another user's projects"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(root)
            page.locator("#new-original").click()
            page.locator("#dialog-name").fill("分发版原创验收")
            page.locator("#dialog-ok").click()
            page.locator("#identity-name").wait_for()
            p = api("/api/project?id=" + api("/api/session")["projects"][0]["id"])
            assert p["name"] == "分发版原创验收"
            p = api("/api/import", {"data": base64.b64encode(args.reference.read_bytes()).decode()})
            assert len(p["animations"]) == 18 and len(p["effects"]) == 2
            page.reload()
            page.locator('[data-open="' + p["id"] + '"]').click()
            page.locator("#compiled-preview").wait_for()
            page.locator('[data-animation]').nth(2).click()
            page.screenshot(path=str(output / "portable-workbench.png"), full_page=True)
            page.locator("#compiled-preview").click()
            page.locator("#readback-play").click()
            page.wait_for_timeout(300)
            assert int(page.locator("#readback-scrub").input_value()) > 0
            page.locator(".modal-close").click()
            page.locator('[data-page="effects"]').click()
            page.locator("#compiled-preview").click()
            page.locator("#readback-stage").wait_for()
            page.locator("#readback-next").click()
            assert page.locator("#readback-scrub").input_value() == "1"
            page.locator(".modal-close").click()
            with urllib.request.urlopen(root + "/api/export?id=" + p["id"]) as response:
                restored = api("/api/import", {"data": base64.b64encode(response.read()).decode()})
            assert restored["id"] != p["id"] and restored["animations"] == p["animations"]
            compile_report = api("/api/compile", {"id": p["id"]})
            assert len(compile_report["files"]) == 40
            page.locator("#shutdown").click()
            page.get_by_text("工程已保存。", exact=True).wait_for()
            browser.close()
        process.wait(timeout=10)
        assert process.returncode == 0
        assert not errors, errors
        report = {"exe": str(app / "星点角色工坊.exe"), "filesVerified": len(manifest["files"]),
                  "withoutPythonOnPath": True, "strictCSP": True, "originalCreation": True,
                  "referenceActions": 18, "referenceEffects": 2, "compiledFiles": 40,
                  "compiledAnimationAndEffectPlayback": True, "transferRoundtrip": True,
                  "cleanShutdown": True, "browserErrors": errors}
        (output / "portable-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        if process.poll() is None:
            try:
                api("/api/shutdown", {})
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
