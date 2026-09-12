"""Actual click/scroll regression and library selection in source or frozen UI."""
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
import zipfile
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_gameplay import DefinitionLibrary
from studio import create_server

def wait(page,expression,seconds=35):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if page.evaluate(expression):return
        time.sleep(.05)
    raise AssertionError(expression)

def verify_scroll(page,out):
    page.locator('[data-page="animations"]').click()
    page.locator('[data-animation]').first.wait_for()
    rows=page.locator('[data-animation]');assert rows.count()>=11
    target=rows.nth(rows.count()-2)
    target.scroll_into_view_if_needed()
    before=page.evaluate('({top:$(".library-list").scrollTop,y:scrollY,rect:$(".library-list").getBoundingClientRect().top})')
    assert before['top']>50,before
    key=target.get_attribute('data-animation')
    for index in [rows.count()-2,rows.count()-1,rows.count()-2]:
        rows.nth(index).click()
        wait(page,'!S.playing')
        after=page.evaluate('({top:$(".library-list").scrollTop,y:scrollY,rect:$(".library-list").getBoundingClientRect().top})')
        assert all(abs(after[k]-before[k])<2 for k in before),(before,after)
    assert page.evaluate('S.selected')==key
    (page.page if hasattr(page,'page') else page).screenshot(path=str(out/'action-scroll.png'))
    page.locator('#copy-animation').click()
    assert abs(page.locator('.library-list').evaluate('(e)=>e.scrollTop')-before['top'])<2
    page.locator('#undo').click()
    assert abs(page.locator('.library-list').evaluate('(e)=>e.scrollTop')-before['top'])<2
    return before

def verify_picker(page,source,query,out):
    page.locator('[data-page="gameplay"]').click()
    page.locator('[data-native-library="2"]').wait_for()
    prior=page.evaluate('S.p.nativeGameplay.abilities[1].rows')
    origin=page.evaluate('S.p.nativeGameplay.source')
    page.locator('[data-native-library="2"]').click()
    page.locator('#ability-library-search').fill(query)
    page.locator('[data-library-key]').first.wait_for()
    # The search is debounced, so wait for its response before choosing.
    time.sleep(.5)
    page.locator('[data-library-key]').first.click()
    page.locator('#ability-library-use').wait_for()
    assert source in page.locator('#ability-library-source').inner_text()
    assert page.locator('#ability-library-use').is_enabled()
    (page.page if hasattr(page,'page') else page).screenshot(path=str(out/'ability-library.png'))
    page.locator('#ability-library-use').click()
    wait(page,'S.p.nativeGameplay.abilities[1].rows.length>'+str(len(prior))+' && $("#busy").hidden')
    page.locator('[data-native-library="2"]').wait_for()
    current=page.evaluate('S.p.nativeGameplay')
    assert current['source']==origin
    assert current['abilities'][1]['rows'][:len(prior)]==prior
    assert current['abilities'][1]['rows'][len(prior):]==current['borrowedAbilities'][-1]['rows']
    assert current['borrowedAbilities'][-1]['source']==source
    page.locator('#undo').click()
    wait(page,'S.p.nativeGameplay.abilities[1].rows.length=='+str(len(prior)))
    page.locator('[data-native-library="2"]').wait_for()
    page.locator('#redo').click()
    wait(page,'S.p.nativeGameplay.abilities[1].rows.length>'+str(len(prior)))
    page.evaluate('async()=>await saveNow()')
    return current

def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--definitions',type=Path,required=True);p.add_argument('--exe',type=Path);args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    library=DefinitionLibrary(out/'definitions')
    with zipfile.ZipFile(args.definitions) as z:library.install({n:z.read(n) for n in z.namelist() if n.startswith('definitions/')})
    server=process=None;errors=[]
    if args.exe:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')};env['PATH']=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']
        process=subprocess.Popen([str(args.exe.resolve()),'--no-open','--port',str(port),'--projects',str(out/'projects'),'--definitions',str(out/'definitions')],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        server=create_server(out/'projects',definitions=out/'definitions');port=server.server_port
        threading.Thread(target=server.serve_forever,daemon=True).start()
    url=f'http://127.0.0.1:{port}'
    try:
        for _ in range(200):
            try:
                with urllib.request.urlopen(url+'/api/session',timeout=1) as r:session=json.load(r)
                break
            except OSError:time.sleep(.1)
        else:raise AssertionError('startup timeout')
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page(viewport={'width':1500,'height':1080});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(url);wait(page,'typeof S!=="undefined"&&!!S.token')
            page.evaluate("async()=>setProject(await api('/api/new',{name:'滚动与词条验收',kind:'original'}))")
            scroll=verify_scroll(page,out)
            page.evaluate("async()=>{await saveNow();S.p=await api('/api/definition-attach',{id:S.p.id,revision:S.p.revision,character:'10'});S.generation++;S.dirty=false;render();}")
            current=verify_picker(page,'官方离线词条库','white_tiger',out)
            page.reload();wait(page,'typeof S!=="undefined"&&!!S.token');page.locator('[data-open]').first.click();page.locator('[data-page="gameplay"]').click();page.locator('[data-native-library="2"]').wait_for()
            assert page.evaluate('S.p.nativeGameplay')==current
            page.set_viewport_size({'width':720,'height':900})
            page.locator('[data-native-library="leader"]').click();page.locator('#ability-library-search').fill('white_tiger');time.sleep(.5);page.locator('[data-library-key]').first.click();page.locator('#ability-library-use').wait_for()
            assert page.locator('#modal').evaluate('e=>e.scrollWidth<=e.clientWidth+1')
            page.screenshot(path=str(out/'ability-narrow.png'))
            leader_before=page.evaluate('S.p.nativeGameplay.leader.rows.length')
            page.locator('#ability-library-use').click()
            wait(page,'S.p.nativeGameplay.leader.rows.length>'+str(leader_before)+' && $("#busy").hidden')
            browser.close()
        assert not errors,errors
        report={'frozen':bool(args.exe),'source':'官方离线词条库','scrollStable':scroll,'wholeAbilityCopied':True,'undoRedo':True,'savedReopened':True,'narrowModal':True,'errors':errors}
        (out/'authoring-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if server:server.shutdown();server.server_close()
        if process:
            req=urllib.request.Request(url+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Studio-Token':session['token']})
            try:urllib.request.urlopen(req,timeout=5).close();process.wait(timeout=15)
            except Exception:process.terminate();process.wait(timeout=5)

if __name__=='__main__':main()
