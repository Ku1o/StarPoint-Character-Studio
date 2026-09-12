"""Exercise real UI flows in an isolated Edge profile; never launch the game."""
import argparse
import io
import json
import sys
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import make_zip


def wait_for(page, expression, timeout=30000):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        time.sleep(.05)
    raise AssertionError("Timed out: " + expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    inputs = output / "input"
    inputs.mkdir(exist_ok=True)
    for n in range(3):
        img = Image.new("RGBA", (32, 40))
        draw = ImageDraw.Draw(img)
        draw.rectangle((10, 5 + n, 22, 18 + n), fill=(130, 160, 250, 255))
        draw.rectangle((8, 20, 24, 32), fill=(80, 100, 200, 255))
        draw.rectangle((8, 32, 13, 39), fill=(220, 200, 130, 255))
        draw.rectangle((20, 32, 25, 39), fill=(220, 200, 130, 255))
        img.save(inputs / f"frame_{n:02}.png")
    server = create_server(output / "projects")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors = []
    summary = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{server.server_port}")
            wait_for(page, "S.token.length > 0")
            page.screenshot(path=str(output / "01-welcome.png"), full_page=True)
            page.locator("#new-original").click()
            page.locator("#dialog-name").fill("原创流程验收")
            page.locator("#dialog-ok").click()
            page.locator("#identity-name").wait_for()
            page.locator('[data-page="animations"]').click()
            assert page.locator('[data-animation]').count() == 11
            assert page.evaluate("S.p.animations.every(a=>a.clips.length===0&&a.purpose)")
            neutral_id = page.evaluate("S.p.animations.find(a=>a.slot==='neutral').id")
            page.locator(f'[data-animation="{neutral_id}"]').click()
            page.locator("#add-frames").click()
            page.locator("#pixel-files-input").set_input_files([str(inputs / f"frame_{n:02}.png") for n in range(3)])
            page.locator('[data-pixel-file]').first.wait_for()
            assert page.locator('[data-pixel-target]').input_value() == neutral_id
            page.locator("#pixel-import-confirm").click()
            wait_for(page, "!document.querySelector('#modal').open && current().clips.length === 3")
            assert page.locator(".frame-tile").count() == 3
            page.locator("#clip-hold").fill("12")
            page.locator("#clip-hold").dispatch_event("change")
            wait_for(page, "current().clips[0].hold === 12")
            page.locator("#play").click()
            page.wait_for_timeout(140)
            assert page.evaluate("S.tick") > 0
            page.locator("#play").click()
            page.locator("#frame-copy").click()
            assert page.locator(".frame-tile").count() == 4
            page.locator("#frame-right").click()
            page.locator("#save").click()
            wait_for(page, "!S.dirty && !S.savePromise")
            page.locator("#compiled-preview").click()
            page.locator("#readback-stage").wait_for()
            page.locator("#readback-play").click()
            page.wait_for_timeout(180)
            assert int(page.locator("#readback-scrub").input_value()) > 0
            page.screenshot(path=str(output / "02b-compiled-preview.png"), full_page=True)
            page.locator(".modal-close").click()
            summary["original"] = page.evaluate("({id:S.p.id, clips:current().clips.length, total:duration(current()), defaultSlots:S.p.animations.length})")
            page.screenshot(path=str(output / "02-original-timeline.png"), full_page=True)
            page.locator('[data-page="effects"]').click()
            page.locator('[data-skill-tab="scene"]').click()
            page.locator("#add-actor").click()
            page.locator(f'[data-skill-pick="{neutral_id}"]').click()
            page.locator('.skill-track-advanced summary').click()
            page.locator("#track-x").fill("15")
            page.locator("#track-x").dispatch_event("change")
            page.locator("#save").click()
            wait_for(page, "!S.dirty && !S.savePromise")
            with page.expect_download() as download:
                page.locator("#export").click()
            exported = output / "original-roundtrip.wfchar.zip"
            download.value.save_as(exported)
            page.locator("#home").click()
            page.locator("#import-project").click()
            page.locator("#zip-input").set_input_files(str(exported))
            wait_for(page, "S.p && S.p.name === '原创流程验收' && S.p.id !== '" + summary["original"]["id"] + "'")
            assert page.evaluate("S.p.animations.find(a=>a.slot==='neutral').clips.length") == 4
            assert page.evaluate("S.p.scene.tracks[0].x") == 15
            summary["roundtrip"] = True
            if args.reference:
                reference = args.reference.resolve()
                files = {}
                for file in reference.rglob("*"):
                    if file.is_file():
                        relative = file.relative_to(reference).as_posix()
                        if (relative.startswith("reference/ui/") and "/story/" not in relative and file.suffix == ".png") or (relative.startswith("reference/pixelart/") and len(Path(relative).parts) == 3 and file.suffix in (".png", ".json")) or relative in ("reference/data_readable/identity.json", "reference/REFERENCE_REPORT.json") or (relative.startswith("reference/effect/") and file.suffix in (".json", ".png") and "/cells/" not in relative):
                            files[relative] = file.read_bytes()
                bundle = output / "real-reference.zip"
                bundle.write_bytes(make_zip(files))
                page.locator("#home").click()
                page.locator("#import-template").click()
                page.locator("#template-import-file").click()
                page.locator("#zip-input").set_input_files(str(bundle))
                wait_for(page, "S.p && S.p.template !== null || !document.querySelector('#toast').hidden && document.querySelector('#toast').classList.contains('error')", timeout=30000)
                assert page.evaluate("!!S.p?.template"), page.locator("#toast").inner_text()
                page.locator(".frame-tile").first.wait_for(timeout=30000)
                summary["reference"] = page.evaluate("({name:S.p.template.name, version:S.p.template.version, actions:S.p.animations.length, effects:S.p.effects.length, assets:Object.keys(S.p.assets).length})")
                page.locator('[data-animation]').nth(1).click()
                page.wait_for_timeout(400)
                page.screenshot(path=str(output / "03-reference-animation.png"), full_page=True)
                page.locator('[data-page="portraits"]').click()
                page.wait_for_timeout(600)
                page.screenshot(path=str(output / "04-portrait.png"), full_page=True)
                page.locator('[data-slot="square_132_132"]').click()
                page.locator("#portrait-readback").click()
                page.locator(".portrait-readback").wait_for(timeout=30000)
                wait_for(page, "document.querySelector('.portrait-readback')?.naturalWidth===132")
                page.locator(".modal-close").click()
                page.locator('[data-page="effects"]').click()
                page.wait_for_timeout(500)
                page.screenshot(path=str(output / "05-effects.png"), full_page=True)
                page.locator('[data-page="checks"]').click()
                page.locator("#compile-assets").wait_for(timeout=30000)
                page.screenshot(path=str(output / "06-handoff.png"), full_page=True)
                page.set_viewport_size({"width": 720, "height": 1000})
                page.locator('[data-page="animations"]').click()
                page.wait_for_timeout(300)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                page.screenshot(path=str(output / "07-narrow.png"), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)
    summary["browserErrors"] = errors
    summary["strictCSP"] = True
    (output / "ui-report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise AssertionError(errors)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
