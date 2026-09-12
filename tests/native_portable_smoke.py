"""Exercise installed definition UI and native serialization in the distributed EXE."""
import argparse
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import zipfile
from playwright.sync_api import sync_playwright

def wait(page,expression):
    end=time.monotonic()+35
    while time.monotonic()<end:
        if page.evaluate(expression):return
        time.sleep(.05)
    raise AssertionError(expression)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path,required=True);parser.add_argument('--definitions',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','PYTHONHOME')};env['PATH']=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']
    process=subprocess.Popen([str(args.exe.resolve()),'--no-open','--port',str(port),'--projects',str(out/'projects'),'--definitions',str(out/'definitions'),'--templates',str(out/'templates')],env=env,creationflags=subprocess.CREATE_NO_WINDOW)
    root=f'http://127.0.0.1:{port}';token='';errors=[]
    try:
        end=time.monotonic()+25
        while time.monotonic()<end:
            try:
                with urllib.request.urlopen(root+'/api/session',timeout=1) as response:token=json.load(response)['token']
                break
            except OSError:time.sleep(.1)
        assert token,'EXE failed to start'
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='msedge',headless=True);page=browser.new_page(viewport={'width':1440,'height':1000});page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(root);wait(page,'!!S.token')
            page.locator('#new-original').click();page.locator('#dialog-name').fill('原生词条分发验收');page.locator('#dialog-ok').click();page.locator('[data-page="gameplay"]').click()
            with page.expect_file_chooser() as fc:page.locator('#native-install').click()
            fc.value.set_files(str(args.definitions.resolve()))
            page.locator('#native-search').fill('white_tiger');page.locator('[data-definition="10"]').click();page.locator('[data-native-edit="1:0"]').wait_for()
            page.locator('[data-native-edit="1:0"]').click();page.locator('#native-value').fill('32.5');page.locator('#native-main').check();page.locator('#native-row-save').click()
            wait(page,"S.p.nativeGameplay.abilities[0].rows[0][51]==='32500' && document.querySelector('#busy').hidden")
            page.locator('[data-skill-edit="0"]').click();page.locator('#native-skill-text').fill('逗号, 与 "引号"\n第二行');page.locator('#native-energy').fill('512');page.locator('#native-skill-save').click()
            wait(page,"S.p.nativeGameplay.skills[0].fields[4]==='512' && document.querySelector('#busy').hidden")
            native=page.evaluate('S.p.nativeGameplay');assert native['abilities'][0]['rows'][0][51]=='32500';assert native['skills'][0]['fields'][4]=='512'
            assert native['leader']['sourceKey']=='3'
            page.screenshot(path=str(out/'native-portable.png'),full_page=True)
            result=page.evaluate("async()=>{await saveNow();const result=await api('/api/compile',{id:S.p.id});const raw=await (await fetch('/api/compile-export?id='+S.p.id)).arrayBuffer();return {result,raw:Array.from(new Uint8Array(raw))};}")
            assert any(r['kind']=='native-gameplay' and r['readback'] for r in result['result']['receipts'])
            with zipfile.ZipFile(io.BytesIO(bytes(result['raw']))) as z:
                assert 'native-draft/action_skill.orderedmap' in z.namelist()
                contract=json.loads(z.read('MOD角色接入契约.json'));assert contract['nativeGameplay']==native
                assert contract['integration']['modStudioProjectImport'] and not contract['integration']['gameReady']
            pid=page.evaluate('S.p.id');page.reload();page.locator('[data-open="'+pid+'"]').click();page.locator('[data-page="gameplay"]').click();page.locator('#native-notes').wait_for()
            assert page.evaluate('S.p.nativeGameplay')==native
            page.locator('#shutdown').click();page.get_by_text('工程已保存。',exact=True).wait_for();browser.close()
        process.wait(timeout=10);assert process.returncode==0;assert not errors,errors
        report={'withoutPythonOnPath':True,'definitionInstallUI':True,'officialReference':'10','actualLeaderKey':'3','nativeNumericEdit':True,'skillTextAndEnergyEdit':True,'compiledNativeReadback':True,'reloadPreserved':True,'cleanShutdown':True,'errors':errors}
        (out/'native-portable-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print(json.dumps(report,ensure_ascii=False))
    finally:
        if process.poll() is None:
            try:
                request=urllib.request.Request(root+'/api/shutdown',data=b'{}',headers={'Content-Type':'application/json','X-Studio-Token':token});urllib.request.urlopen(request,timeout=3).close();process.wait(timeout=5)
            except (OSError,subprocess.TimeoutExpired):process.kill();process.wait(timeout=5)

if __name__=='__main__':main()
