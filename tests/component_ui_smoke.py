"""Official Rem: editable channels, actual compiled output and component authoring."""
import argparse
import base64
import copy
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
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore
from effect_channels import compose_frames
from studio_compile import compiled_preview

def wait(page,expression,timeout=40):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if page.evaluate(expression):return
        time.sleep(.05)
    raise AssertionError(expression+'; toast='+page.locator('#toast').inner_text())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--resources',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--exe',type=Path);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False);server=process=None;errors=[];report={}
    if args.exe:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')};env['PATH']=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']
        process=subprocess.Popen([str(args.exe.resolve()),'--no-open','--port',str(port),'--projects',str(out/'projects'),'--templates',str(args.resources.resolve()/'templates'),'--definitions',str(args.resources.resolve()/'definitions')],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server=create_server(out/'projects',templates=args.resources/'templates',definitions=args.resources/'definitions');port=server.server_port;threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{port}';session=None
    try:
        for _ in range(200):
            try:session=json.load(urllib.request.urlopen(url+'/api/session',timeout=1));break
            except OSError:time.sleep(.1)
        assert session,'startup timeout'
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1600,'height':1100});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url);wait(page,'!!S.token')
            page.evaluate("async()=>setProject(await api('/api/template-create',{id:'121027'}))")
            pid=page.evaluate('S.p.id');report['project']=pid
            report['effects']=page.evaluate('S.p.effects.map(e=>({name:e.name,channels:e.channels?.length,frames:e.nativeFrames.length}))')
            assert len(report['effects'])==3 and all(e['channels']>0 for e in report['effects']),report
            assert page.evaluate('S.p.nativeGameplay.source.data.character.code')=='rem'
            page.locator('[data-page="effects"]').click();page.locator('#channel-replace').wait_for()
            # Simulate the existing old project shape without changing the user project.
            page.evaluate("async()=>{const e=S.p.effects[0];delete e.channels;delete e.channelDuration;for(const f of e.nativeFrames)for(const c of f){delete c.channel;delete c.channelOrder;}changed();await saveNow();render();}")
            page.locator('#channel-prepare').click();wait(page,'!!current().channels && $("#busy").hidden');page.locator('#channel-replace').wait_for()
            page.locator('[data-animation]').nth(1).click();page.locator('#channel-replace').wait_for()
            eid=page.evaluate('current().id');channels=page.evaluate('current().channels.length');assert channels>1
            page.locator('.channel-row').last.scroll_into_view_if_needed();scroll=page.locator('.channel-list').evaluate('e=>e.scrollTop')
            page.locator('.channel-row').last.locator('button').first.click();assert abs(page.locator('.channel-list').evaluate('e=>e.scrollTop')-scroll)<2
            page.locator('#channel-x').fill('24');page.locator('#channel-x').dispatch_event('change')
            assert page.evaluate('selectedChannel(current()).x')==24
            channel=page.evaluate('selectedChannel(current()).id')
            original=page.evaluate('selectedChannel(current()).sourceAsset')
            # Replacement through the same file input exposed to the creator.
            image=Image.new('RGBA',(24,24),(240,50,170,200));buffer=io.BytesIO();image.save(buffer,'PNG')
            page.locator('#channel-replace').click();page.locator('#media-input').set_input_files({'name':'channel-replacement.png','mimeType':'image/png','buffer':buffer.getvalue()})
            wait(page,'!!selectedChannel(current()).asset && $("#busy").hidden')
            assert page.evaluate('selectedChannel(current()).asset')!=original
            page.locator('#channel-key-add').click();first=page.evaluate('S.tick');end=page.evaluate('Math.min(selectedChannel(current()).end-1,S.tick+5)')
            page.locator('#scrub').fill(str(end));page.locator('#scrub').dispatch_event('input');page.locator('#channel-x').fill('45');page.locator('#channel-x').dispatch_event('change')
            wait(page,'selectedChannel(current()).keys.length>=1')
            # Copy an instance, then undo/redo proves native source identity is stable.
            page.locator('#channel-copy').click();assert page.evaluate('current().channels.length')==channels+1
            page.locator('#undo').click();assert page.evaluate('current().channels.length')==channels
            page.locator('#redo').click();assert page.evaluate('current().channels.length')==channels+1
            page.evaluate('async()=>{await saveNow();await preloadPreview();draw();}')
            page.locator('#stage').scroll_into_view_if_needed();page.screenshot(path=str(out/'rem-editable-channels.png'),full_page=True)
            before=page.evaluate('clone(current())')
            page.locator('#compiled-preview').click();page.locator('#readback-play').wait_for(timeout=60000)
            page.locator('#readback-play').click();wait(page,'Number($("#readback-scrub").value)>2')
            page.screenshot(path=str(out/'rem-compiled-effect.png'));page.locator('.modal-close').click()
            readback=page.evaluate("async()=>api('/api/compiled-preview',{id:S.p.id,group:'effects',animation:current().id})")
            expected=compose_frames(before);assert len(readback['frames'])==len(expected)
            for wants,gots in zip(expected,readback['frames']):
                assert len(wants)==len(gots)
                for a,b in zip(wants,gots):
                    assert all(abs(x-y)<=1/4096+1e-9 for x,y in zip(a['matrix'],b['matrix']))
                    assert abs(a['alpha']-b['alpha'])<=1/255+1e-9
            report['compiledFrames']=len(readback['frames']);report['compiledFiles']=len(readback['files'])
            # Separate condition / trigger / effect controls, with normal units.
            page.locator('[data-page="gameplay"]').click();page.locator('[data-native-compose="6"]').wait_for();prior=page.evaluate('S.p.nativeGameplay.abilities[5].rows.length')
            page.locator('[data-native-compose="6"]').click();page.locator('#ability-cell-47').wait_for()
            page.locator('#ability-cell-27').select_option('23');page.locator('#ability-cell-47').select_option('34')
            page.locator('#ability-cell-51').fill('25');page.locator('#ability-cell-52').fill('50');page.locator('#ability-cell-57').fill('2');page.locator('#ability-cell-58').fill('2')
            page.locator('#ability-main-only').check()
            page.locator('.ability-preconditions>summary').click();page.locator('#ability-cell-6').select_option('4')
            wait(page,'!$("#ability-row-save").disabled')
            assert '25' in page.locator('#ability-row-description').inner_text()
            # Import just the effect block from a different Rem ability.
            page.locator('[data-ability-block="instant_content"] [data-block-action="take"]').click();page.locator('#ability-library-search').fill('rem');page.wait_for_timeout(500)
            page.locator('[data-library-key]').first.click();page.locator('#ability-library-use').wait_for();page.locator('#ability-library-use').click();page.locator('#ability-cell-47').wait_for()
            assert page.locator('#ability-cell-27').input_value()=='23';assert page.locator('#ability-cell-6').input_value()=='4'
            page.locator('#ability-cell-47').select_option('34');page.locator('#ability-cell-51').fill('25');page.locator('#ability-cell-52').fill('50')
            wait(page,'!$("#ability-row-save").disabled');page.locator('#ability-row-description').scroll_into_view_if_needed();page.screenshot(path=str(out/'ability-components.png'))
            page.locator('#ability-row-save').click();wait(page,'!$("#modal").open && S.p.nativeGameplay.abilities[5].rows.length=='+str(prior+1))
            row=page.evaluate('S.p.nativeGameplay.abilities[5].rows.at(-1)');assert row[6]=='4' and row[27]=='23' and row[47]=='34' and row[51:53]==['25000','50000'] and row[1]=='false',row
            page.locator('[data-native-transfer="6:'+str(prior)+'"]').click();page.locator('#ability-transfer-slot').select_option('5');page.locator('#ability-transfer-save').click();wait(page,'!$("#modal").open')
            assert page.evaluate('S.p.nativeGameplay.abilities[4].rows.at(-1)')==row
            page.evaluate('async()=>await saveNow()');native=page.evaluate('clone(S.p.nativeGameplay)')
            page.reload();wait(page,'!!S.token');page.locator('[data-open="'+pid+'"]').click();page.locator('[data-page="gameplay"]').click();page.locator('[data-native-compose="6"]').wait_for()
            assert page.evaluate('S.p.nativeGameplay')==native
            page.set_viewport_size({'width':740,'height':1000});page.locator('[data-native-decompose="6:'+str(prior)+'"]').click();page.locator('#ability-cell-47').wait_for();assert page.locator('#modal').evaluate('e=>e.scrollWidth<=e.clientWidth+1');page.screenshot(path=str(out/'ability-narrow.png'))
            report.update(frozen=bool(args.exe),legacyUpgrade=True,replacement=True,keyframes=True,copyUndoRedo=True,componentBorrow=True,freeCombination=True,savedReopened=True,errors=errors)
            assert not errors,errors
            browser.close()
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if server:server.shutdown();server.server_close()
        if process:
            try:
                req=urllib.request.Request(url+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Studio-Token':session['token']});urllib.request.urlopen(req,timeout=5).close();process.wait(timeout=15)
            except Exception:process.terminate();process.wait(timeout=5)

if __name__=='__main__':main()
