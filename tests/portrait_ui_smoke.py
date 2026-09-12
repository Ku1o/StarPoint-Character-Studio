"""Real Rem UI assets, crop editing, exact downloads and actual atlas readback."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore, UI_SLOTS, image_from
from portrait_editor import render


def wait(page, expression, timeout=45):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if page.evaluate(expression):
            return
        time.sleep(.05)
    raise AssertionError(expression + '; ' + page.locator('#toast').inner_text())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    server = process = None
    errors, report = [], {}
    if args.exe:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        env['PATH'] = os.environ['SystemRoot'] + '\\System32;' + os.environ['SystemRoot']
        process = subprocess.Popen([str(args.exe.resolve()), '--no-open', '--port', str(port), '--projects', str(out/'projects'), '--templates', str(args.resources.resolve()/'templates'), '--definitions', str(args.resources.resolve()/'definitions')], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server = create_server(out/'projects', templates=args.resources/'templates', definitions=args.resources/'definitions')
        port = server.server_port
        threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{port}'
    try:
        for _ in range(200):
            try:
                urllib.request.urlopen(url+'/api/session', timeout=1).close(); break
            except OSError:
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1550, 'height': 1100}, accept_downloads=True)
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(url); wait(page, '!!S.token')
            page.evaluate("async()=>setProject(await api('/api/template-create',{id:'121027'}))")
            pid = page.evaluate('S.p.id'); report['project'] = pid
            store = ProjectStore(out/'projects'); project = store.load(pid)
            expected = project['uiSources']; assert len(expected) == 24
            for key, aid in expected.items():
                form, slot = key.split(':')
                assert render(store, project, form, slot) == store.asset_bytes(project, aid), key
            report['officialExactImages'] = len(expected)
            page.locator('[data-page="portraits"]').click()
            page.locator('[data-slot="square_132_132"]').click()
            wait(page, "Portrait.key===Portrait.pending && Portrait.image?.naturalWidth===132")
            assert page.locator('.portrait-status').inner_text().endswith('官方原图 · 132 × 132')
            page.screenshot(path=str(out/'rem-official-ui.png'), full_page=True)
            with page.expect_download() as download:
                page.locator('#portrait-export').click()
            downloaded = Path(download.value.path()).read_bytes()
            assert downloaded == store.asset_bytes(project, expected['base:square_132_132'])
            page.locator('#portrait-crop').click(); page.locator('#crop-left').fill('360'); page.locator('#crop-left').dispatch_event('change')
            page.locator('#crop-top').fill('55'); page.locator('#crop-top').dispatch_event('change')
            page.locator('#crop-width').fill('380'); page.locator('#crop-width').dispatch_event('change')
            wait(page, 'Portrait.key===Portrait.pending && !S.dirty')
            before = page.evaluate('portraitSelection().rect.x')
            canvas = page.locator('#crop-source'); canvas.scroll_into_view_if_needed()
            geometry = page.evaluate("()=>{const b=$('#crop-source').getBoundingClientRect(),v=Portrait.sourceView,r=portraitSelection().rect;return {x:b.left+v.x+(r.x+r.width/2)*v.scale,y:b.top+v.y+(r.y+r.height/2)*v.scale};}")
            page.mouse.move(geometry['x'], geometry['y']); page.mouse.down(); page.mouse.move(geometry['x']+20, geometry['y']+12, steps=4); page.mouse.up()
            assert page.evaluate('portraitSelection().rect.x') != before
            page.evaluate('async()=>await saveNow()'); wait(page, 'Portrait.key===Portrait.pending')
            page.screenshot(path=str(out/'rem-crop-editor.png'), full_page=True)
            with page.expect_download() as download:
                page.locator('#portrait-export').click()
            cropped = Path(download.value.path()).read_bytes()
            assert cropped == render(store, store.load(pid), 'base', 'square_132_132')
            # Import an externally modified, same-sized picture into only this slot.
            image = image_from(cropped); image.putpixel((20, 20), (255, 12, 99, 140))
            buf = io.BytesIO(); image.save(buf, 'PNG')
            page.locator('#portrait-upload').click(); page.locator('#media-input').set_input_files({'name': 'my-face.png', 'mimeType': 'image/png', 'buffer': buf.getvalue()})
            wait(page, "portraitSelection().mode==='image' && S.p.assets[portraitSelection().asset].name==='my-face.png' && !S.dirty")
            assert page.evaluate("portraitSelection('base','square').asset") == expected['base:square']
            assert page.evaluate("portraitSelection('evolved','square_132_132').asset") == expected['evolved:square_132_132']
            page.locator('#portrait-original').click(); wait(page, '!S.dirty')
            page.locator('#ui-atlas').click(); page.locator('#atlas-cell-export').wait_for(timeout=60000)
            page.locator('#atlas-cell').select_option('3')
            with page.expect_download() as download:
                page.locator('#atlas-cell-export').click()
            assert image_from(Path(download.value.path()).read_bytes()).size == (212,212)
            page.screenshot(path=str(out/'rem-ui-atlas.png')); page.locator('.modal-close').click()
            page.locator('#image-library').click(); page.locator('#image-query').fill('battle_control_board_0')
            page.locator('[data-image-detail]').click()
            with page.expect_download() as download:
                page.locator('#modal-content .image-download').click()
            assert Path(download.value.path()).read_bytes() == store.asset_bytes(project, expected['base:battle_control_board'])
            page.locator('.modal-close').click()
            page.locator('[data-page="animations"]').click(); page.locator('#animation-atlas').click(); page.locator('#atlas-cell-export').wait_for(timeout=60000)
            with page.expect_download() as download:
                page.locator('#atlas-cell-export').click()
            assert image_from(Path(download.value.path()).read_bytes()).width > 0
            page.screenshot(path=str(out/'rem-pixel-atlas.png')); page.locator('.modal-close').click()
            page.locator('[data-page="effects"]').click(); page.locator('#channel-export-image').wait_for()
            with page.expect_download() as download:
                page.locator('#channel-export-image').click()
            assert image_from(Path(download.value.path()).read_bytes()).width > 0
            page.locator('#animation-atlas').click(); page.locator('#atlas-cell-export').wait_for(timeout=60000); page.locator('.modal-close').click()
            page.locator('[data-page="portraits"]').click(); page.set_viewport_size({'width':740,'height':1000})
            assert page.locator('body').evaluate('e=>e.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(out/'portrait-narrow.png'), full_page=True)
            page.reload(); wait(page, '!!S.token'); page.locator('[data-open="'+pid+'"]').click(); page.locator('[data-page="portraits"]').click()
            assert page.evaluate("portraitSelection('base','square_132_132').asset") == expected['base:square_132_132']
            report.update(frozen=bool(args.exe),officialDownload=True,cropDrag=True,cropExportParity=True,independentReplacement=True,restoreOfficial=True,uiAtlas=True,pixelAtlas=True,effectAtlas=True,channelDownload=True,narrowLayout=True,reopen=True,errors=errors)
            assert not errors, errors
            browser.close()
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
    finally:
        if server:
            server.shutdown(); server.server_close()
        if process:
            process.terminate(); process.wait(timeout=10)


if __name__ == '__main__':
    main()
