"""Exercise the real PNG-folder, slice-preview and assignment UI under strict CSP."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server


def wait(page, expression, timeout=30):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if page.evaluate(expression):
            return
        time.sleep(.05)
    raise AssertionError(expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "input" / "角色动作"
    for folder, values in (("待机", [(1, "red"), (2, "green"), (10, "blue")]), ("前进", [(1, "yellow"), (2, "purple")])):
        directory = inputs / folder
        directory.mkdir(parents=True, exist_ok=True)
        for index, color in values:
            image = Image.new("RGBA", (32, 40))
            draw = ImageDraw.Draw(image)
            draw.rectangle((9, 4, 23, 18), fill=color)
            draw.rectangle((11, 18, 21, 35), fill=color)
            image.save(directory / f"{folder}_{index}.png")
    sheet = Image.new("RGBA", (96, 32))
    sheet.paste(Image.new("RGBA", (16, 24), "red"), (8, 8))
    sheet.paste(Image.new("RGBA", (16, 24), "blue"), (40, 8))
    sheet_path = output / "input" / "motion_sheet.png"
    sheet.save(sheet_path)
    errors, report = [], {}
    server = process = None
    if args.exe:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
        env["PATH"] = os.environ["SystemRoot"] + "\\System32;" + os.environ["SystemRoot"]
        process = subprocess.Popen([str(args.exe.resolve()), "--no-open", "--port", str(port), "--projects", str(output / "projects")], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server = create_server(output / "projects")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_port
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url + "/api/session", timeout=1) as r:
                    session = json.load(r)
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError("Studio startup timed out")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1500, "height": 1080})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            wait(page, "S.token.length>0")
            page.locator("#new-original").click()
            page.locator("#dialog-name").fill("像素工作流验收")
            page.locator("#dialog-ok").click()
            page.locator("#identity-name").wait_for()
            page.locator('[data-page="animations"]').click()
            wait(page, "document.querySelectorAll('[data-animation]').length===11")
            assert page.locator('[data-animation]').count() == 11
            assert page.evaluate("S.p.animations.every(a=>a.clips.length===0&&a.purpose)")
            page.screenshot(path=str(output / "01-original-slots.png"), full_page=True)
            page.locator("#pixel-batch-import").click()
            page.locator("#pixel-folder-input").set_input_files(str(inputs))
            page.locator('[data-pixel-file]').first.wait_for()
            wait(page, "document.querySelectorAll('[data-pixel-file]').length===5")
            assert page.locator('[data-pixel-target]').count() == 2
            page.locator('[data-pixel-file]').filter(has_text="待机_1.png").click()
            page.locator("#pixel-preview-play").click()
            wait(page, "!document.querySelector('#pixel-preview-status').textContent.startsWith('第 1 ')")
            page.locator("#pixel-preview-play").click()
            page.screenshot(path=str(output / "02-folder-groups.png"), full_page=True)
            page.locator("#pixel-import-confirm").click()
            wait(page, "!document.querySelector('#modal').open && S.p.animations.find(a=>a.slot==='neutral').clips.length===3")
            names = page.evaluate("S.p.animations.find(a=>a.slot==='neutral').clips.map(c=>S.p.assets[c.asset].name)")
            assert names == ["待机_1.png", "待机_2.png", "待机_10.png"], names
            assert page.evaluate("S.p.animations.find(a=>a.slot==='walk_front').clips.length===2")
            neutral_id = page.evaluate("S.p.animations.find(a=>a.slot==='neutral').id")
            page.locator(f'[data-animation="{neutral_id}"]').click()
            page.locator("#compiled-preview").click()
            page.locator("#readback-stage").wait_for()
            page.locator("#readback-play").click()
            wait(page, "Number(document.querySelector('#readback-scrub').value)>0")
            page.screenshot(path=str(output / "03-compiled-directory-action.png"), full_page=True)
            page.locator(".modal-close").click()
            page.locator("#add-frames").click()
            page.locator("#pixel-files-input").set_input_files(str(sheet_path))
            page.locator("#pixel-use-sheet").wait_for()
            page.locator("#pixel-use-sheet").check()
            assert page.locator("#pixel-grid-width").input_value() == "32"
            wait(page, "document.querySelector('#pixel-preview-status').textContent.includes('/ 3 张')")
            page.locator("#pixel-preview-play").click()
            wait(page, "document.querySelector('#pixel-preview-status').textContent.startsWith('第 3 ')")
            page.locator("#pixel-preview-play").click()
            page.locator("#pixel-import-mode").select_option("replace")
            page.screenshot(path=str(output / "04-sprite-sheet-grid-preview.png"), full_page=True)
            page.locator("#pixel-import-confirm").click()
            wait(page, "!document.querySelector('#modal').open && S.p.animations.find(a=>a.slot==='neutral').clips.every(c=>S.p.assets[c.asset].height===32)")
            assert page.evaluate("S.p.animations.find(a=>a.slot==='neutral').clips.length") == 3
            page.locator("#undo").click()
            wait(page, "S.p.animations.find(a=>a.slot==='neutral').clips.every(c=>S.p.assets[c.asset].height===40)")
            page.locator("#pixel-inbox").click()
            page.locator("#inbox-import").click()
            page.locator("#pixel-files-input").set_input_files(str(sheet_path))
            page.locator("#pixel-use-sheet").wait_for()
            # A single image is deliberately retained as one frame unless slicing is enabled.
            assert page.locator('[data-pixel-target]').input_value() == ""
            page.locator("#pixel-import-confirm").click()
            wait(page, "!document.querySelector('#modal').open && S.p.pixelInbox?.length===1")
            page.locator("#pixel-inbox").click()
            inbox_id = page.evaluate("S.p.pixelInbox[0]")
            page.locator(f'[data-inbox-id="{inbox_id}"]').check()
            page.locator("#inbox-use").click()
            wait(page, "!document.querySelector('#modal').open && S.p.animations.find(a=>a.slot==='neutral').clips.length===4")
            page.locator("#save").click()
            wait(page, "!S.dirty && !S.savePromise")
            page.locator("#pixel-add-presets").click()
            assert page.locator('[data-preset-slot="neutral"]').is_disabled()
            page.locator('[data-preset-slot="attack_initial"]').check()
            page.locator("#preset-add").click()
            wait(page, "S.p.animations.length===12 && !document.querySelector('#modal').open")
            page.set_viewport_size({"width": 720, "height": 1000})
            page.locator("#pixel-batch-import").click()
            page.locator("#pixel-files-input").set_input_files(str(sheet_path))
            page.locator("#pixel-use-sheet").wait_for()
            page.locator("#pixel-use-sheet").check()
            assert page.evaluate("document.querySelector('#modal').scrollWidth <= document.querySelector('#modal').clientWidth+2")
            page.screenshot(path=str(output / "05-narrow-grid-dialog.png"), full_page=True)
            page.locator("#pixel-import-close").click()
            report = {"strictCSP": True, "frozen": bool(args.exe), "defaultSlots": 11, "folderActions": 2, "naturalOrder": names,
                      "compiledPlayback": True, "sheetFramesIncludingBlank": 3, "replaceUndo": True, "inboxAssignment": True,
                      "additionalPreset": True, "narrowNoOverflow": True, "errors": errors}
            assert not errors, errors
            browser.close()
    finally:
        if errors:
            print("Browser errors:", errors)
        if server:
            server.shutdown()
            server.server_close()
        if process:
            try:
                request = urllib.request.Request(url + "/api/shutdown", data=b"{}", headers={"Content-Type": "application/json", "X-Studio-Token": session["token"]})
                urllib.request.urlopen(request, timeout=2).close()
                process.wait(timeout=10)
            except Exception:
                process.terminate()
                process.wait(timeout=5)
        (output / "pixel-ui-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
