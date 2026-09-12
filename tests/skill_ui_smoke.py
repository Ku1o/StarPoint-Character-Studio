"""Real template first-open playback, source/readback timing and gameplay handoff."""
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
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore
from character_contract import export_contract


def wait(page, expression, timeout=60):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if page.evaluate(expression):
            return
        time.sleep(.05)
    raise AssertionError(expression)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exe', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    process = server = None
    if args.exe:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'PYTHONHOME')}
        env['PATH'] = os.environ['SystemRoot'] + '\\System32;' + os.environ['SystemRoot']
        process = subprocess.Popen([str(args.exe.resolve()), '--no-open', '--port', str(port), '--projects', str(output/'projects'), '--templates', str(args.library.resolve())], env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server = create_server(output/'projects', templates=args.library)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_port
    url = f'http://127.0.0.1:{port}'
    errors, report, failed = [], [], []
    try:
        for _ in range(300):
            try:
                urllib.request.urlopen(url+'/api/session', timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1080})
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.on('requestfailed', lambda r: failed.append({'url': r.url, 'error': r.failure}))
            page.add_init_script("window.__soundStarts=0;const start=AudioBufferSourceNode.prototype.start;AudioBufferSourceNode.prototype.start=function(...args){window.__soundStarts++;return start.apply(this,args);};")
            page.goto(url)
            wait(page, '!!S.token')
            for cid in ('10', '1', '131001', '111165', '111006', '121009', '111001', '111004', '311005'):
                page.evaluate("async id=>{await saveNow();setProject(await api('/api/template-create',{id}));}", cid)
                page.locator('[data-page="effects"]').click()
                page.locator('[data-skill-tab="scene"]').click()
                wait(page, "!!S.p.scene.source && !skillPlans.get(S.p.id)?.loading")
                page.evaluate('async()=>{await preloadPreview();draw();await saveNow();}')
                info = page.evaluate("()=>({id:S.p.id,source:S.p.scene.source,duration:S.p.scene.duration,tracks:S.p.scene.tracks.map(t=>({...t,name:skillTrackName(t),frameScale:(t.type==='effect'?S.p.effects:S.p.animations).find(a=>a.id===t.ref)?.frameScale}))})")
                assert info['tracks'], cid
                assert not page.locator('#play').is_disabled(), cid
                fx = [t for t in info['tracks'] if t['type'] == 'effect' and not t.get('endingOf')]
                if cid == '10':
                    assert [t['start'] for t in fx] == [0, 87], fx
                    assert [t['start'] for t in info['tracks'] if t['type'] == 'actor'] == [102]
                elif cid == '1':
                    assert [t['start'] for t in fx] == [0, 44]
                    assert abs(fx[1]['scale']*fx[1]['frameScale']-8) < .00001
                elif cid == '131001':
                    assert len(fx) == 1 and info['source']['deferredCount'] >= 1
                elif cid == '111165':
                    assert [t['start'] for t in fx] == [0, 25]
                elif cid == '111006':
                    assert info['source']['kind'] == 'asset-preview'
                elif cid in ('111001', '111004'):
                    assert any(t.get('phaseOf') for t in fx), 'Pass must continue into its successor'
                elif cid == '121009':
                    assert any(t.get('playMode') == 'once' and t['end']-t['start']>=120 for t in fx)
                elif cid == '311005':
                    assert not fx and '没有可独立播放' in page.locator('#content .notice').inner_text()
                    assert info['source']['deferredCount'] > 0, 'Generic system feedback must stay visible as a gap'
                page.locator('#play').click()
                wait(page, 'S.playing && S.tick>4')
                page.evaluate('stop();S.tick=20;draw();')
                page.screenshot(path=str(output/f'{cid}-skill-preview.png'), full_page=True)
                assert page.evaluate("()=>{const b=PreviewLayout.scene(S.p),r=document.querySelector('#stage').getBoundingClientRect(),v=PreviewLayout.fit(b,r.width,r.height);return v.x+b.minX*v.scale>=31.9&&v.x+b.maxX*v.scale<=r.width-31.9&&v.y+b.minY*v.scale>=31.9&&v.y+b.maxY*v.scale<=r.height-31.9;}")
                if cid in ('10', '1', '121009', '111001', '111004'):
                    readback = page.evaluate("async()=>{await saveNow();const r=await api('/api/compiled-preview',{id:S.p.id,group:'scene',animation:''});return {frames:r.frames.length,visible:r.frames.some(f=>f.length),audio:r.audio.length,ends:r.audio.map(a=>a.end),hashes:r.files.length};}")
                    assert readback['visible'] and readback['frames'] == info['duration'] and readback['hashes'] > 0
                    if cid == '10':
                        assert readback['audio'] > 0
                        page.locator('#compiled-preview').click()
                        page.locator('#readback-play').wait_for(timeout=60000)
                        page.locator('#readback-scrub').fill('88')
                        page.locator('#readback-scrub').dispatch_event('input')
                        page.screenshot(path=str(output/'10-compiled-skill.png'), full_page=True)
                        page.locator('.modal-close').click()
                    info['readback'] = readback
                # Manual changes must survive reopening; loading plans is read-only.
                page.evaluate('async()=>{S.p.scene.tracks[0].x=23;changed();await saveNow();const id=S.p.id;setProject(await api("/api/project?id="+id));S.page="scene";render();}')
                assert page.evaluate('S.p.scene.tracks[0].x') == 23
                report.append(info)
            page.locator('[data-page="gameplay"]').click()
            assert '未携带完整' in page.locator('#content .notice').inner_text()
            page.locator('#gameplay-skill-name').fill('测试技能名称')
            page.locator('#ability-description-1').fill('每释放一次技能，自身攻击力提高 10%，最多叠加 3 次。')
            page.locator('#ability-main-1').check()
            page.locator('#save').click()
            wait(page, '!S.dirty&&!S.savePromise')
            pid = page.evaluate('S.p.id')
            page.evaluate('async()=>{setProject(await api("/api/project?id="+S.p.id));S.page="gameplay";render();}')
            assert page.locator('#gameplay-skill-name').input_value() == '测试技能名称'
            assert page.locator('#ability-main-1').is_checked()
            assert '10%' in page.locator('#ability-description-1').input_value()
            # A legal partial handoff must remain editable without losing slots.
            page.evaluate('()=>{S.p.gameplay={leader:{name:"保留的队长技"},abilities:[{slot:1,name:"已有能力"}]};changed();render();}')
            page.locator('#ability-description-6').fill('进阶能力设计')
            page.locator('#ability-description-6').dispatch_event('change')
            page.locator('#gameplay-leader-description').fill('队长效果设计')
            page.locator('#gameplay-leader-description').dispatch_event('change')
            page.locator('#ability-main-1').check()
            page.locator('#save').click()
            wait(page, '!S.dirty&&!S.savePromise')
            assert page.evaluate('S.p.gameplay.abilities.length') == 6
            assert page.evaluate('S.p.gameplay.leader.name') == '保留的队长技'
            page.screenshot(path=str(output/'gameplay-design.png'), full_page=True)
            store = ProjectStore(output/'projects')
            contract = export_contract(store, store.load(pid))
            assert contract['gameplayDesign']['abilities'][0]['mainOnly']
            assert contract['sourceDefinition']['status'] == 'needs_definition_pack'
            (output/'sample-handoff.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2), 'utf-8')
            assert not errors, errors
            (output/'skill-ui-report.json').write_text(json.dumps({'templates':report,'errors':errors,'soundStarts':page.evaluate('window.__soundStarts')}, ensure_ascii=False, indent=2), 'utf-8')
            browser.close()
    finally:
        (output/'network-failures.json').write_text(json.dumps(failed, ensure_ascii=False, indent=2), 'utf-8')
        if server:
            server.shutdown()
            server.server_close()
        if process:
            if process.poll() is None:
                try:
                    req=urllib.request.Request(url+'/api/shutdown', data=b'{}', headers={'Content-Type':'application/json','X-Studio-Token':json.load(urllib.request.urlopen(url+'/api/session'))['token']})
                    urllib.request.urlopen(req, timeout=5).close()
                    process.wait(timeout=10)
                except Exception:
                    process.terminate()
                    process.wait(timeout=10)
    print(json.dumps({'output':str(output),'templates':len(report),'errors':errors},ensure_ascii=False))


if __name__=='__main__':
    main()
