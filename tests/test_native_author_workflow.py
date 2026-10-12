"""Real author controls -> native rows -> closure -> export -> undo."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore, archive_files
import native_gameplay as native
from test_native_gameplay import pack
from test_author_gameplay import card
import author_gameplay as author


class NativeAuthorWorkflowTests(unittest.TestCase):
    def test_native_editor_cannot_hide_real_main_condition_or_change_its_flag_on_value_edit(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ProjectStore(Path(temp)/'projects')
            p=store.create('主位条件保护')
            definitions=pack()
            class Library:
                def load(self):return definitions
            p=native.attach(store,p['id'],p['revision'],Library(),'10')
            plan=p['productionBrief']['plans']['abilities'][0]
            plan['authorCards']=[card(mainOnly=True)]
            plan['authorDescription']=plan['authorCards'][0]['text']
            p=store.save(p); report=author.preview(p)
            p=author.apply(store,p['id'],p['revision'],report['token'],[report['cards'][0]['id']])
            # A genuine precondition is independent from the unison row flag.
            p['nativeGameplay']['abilities'][0]['rows'][-1][1]='true'
            p=store.save(p)
            description=native.describe_native(p['nativeGameplay'])['groups'][1]['rows'][-1]
            self.assertTrue(description['mainOnly'])
            self.assertTrue(description['mainOnlyLocked'])
            before=copy.deepcopy(p)
            with self.assertRaisesRegex(ValueError,'主位执行条件'):
                native.edit(store,p['id'],p['revision'],'patch',1,1,{'mainOnly':False})
            self.assertEqual(store.load(p['id']),before)
            changed=native.edit(store,p['id'],p['revision'],'patch',1,1,{'value':description['value'],'mainOnly':True})
            self.assertEqual(changed['nativeGameplay']['abilities'][0]['rows'][-1],before['nativeGameplay']['abilities'][0]['rows'][-1])

    def test_chinese_cards_actual_rows_dependencies_export_and_undo(self):
        module=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
        node=shutil.which('node')
        if not module.exists() or not node:
            self.skipTest('Bundled JS Playwright unavailable')
        with tempfile.TemporaryDirectory(prefix='native-author-ui-') as temp:
            root=Path(temp)
            if os.environ.get('STUDIO_NATIVE_TEST_ROOT'):
                root=Path(os.environ['STUDIO_NATIVE_TEST_ROOT'])
                root.mkdir(parents=True, exist_ok=True)
            store=ProjectStore(root/'projects')
            p=store.create('中文接入验证')
            definitions=pack()
            class Library:
                def load(self):return definitions
            p=native.attach(store,p['id'],p['revision'],Library(),'10')
            before=copy.deepcopy(p['nativeGameplay'])
            server=create_server(root/'projects')
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            script=r'''
const {chromium}=require(process.argv[1]),fs=require('fs'),assert=require('node:assert/strict'),path=require('path');
(async()=>{
const browser=await chromium.launch({channel:'msedge',headless:true});
try{
 const page=await browser.newPage({viewport:{width:1450,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(process.argv[2]);await page.waitForFunction(()=>S.token);
 await page.locator('[data-open="'+process.argv[4]+'"]').click();
 await page.locator('[data-page="gameplay"]').click();await page.locator('#native-notes').click();
 await page.locator('[data-creator-plan="ability0"]').click();
 await page.locator('#creator-trigger').selectOption('battle_start');
 await page.locator('#creator-target').selectOption('party');
 await page.locator('#creator-effect').selectOption('attack_up');
 await page.locator('#creator-amount').fill('20%');await page.locator('#creator-time').fill('10秒');
 await page.locator('#creator-stacking').selectOption('single');await page.locator('#creator-compose').click();
 await page.locator('#creator-effect').selectOption('custom');await page.locator('#creator-compose').click();
 await page.locator('#author-integration-preview').click();
 await page.locator('[data-integration-card]').waitFor();
 assert.equal(await page.locator('[data-integration-card]').count(),1);
 const text=await page.locator('#author-integration-result').innerText();
 assert.match(text,/攻击力|20/);assert.match(text,/协助|核实/);
 await page.locator('[data-integration-card]').check();await page.screenshot({path:path.join(process.argv[3],'01-native-card-preview.png')});
 await page.locator('#author-integration-apply').click();
 await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden&&!document.querySelector('#modal').open);
 const applied=await page.evaluate(()=>structuredClone(S.p));
 assert.equal(applied.productionBrief.plans.abilities[0].authorCards.length,2);
 assert.equal(applied.nativeGameplay.abilities[0].rows.length,2);
 fs.writeFileSync(path.join(process.argv[3],'applied.json'),JSON.stringify(applied));
 await page.locator('[data-page="checks"]').click();
 await page.locator('#dependency-closure-open').click();await page.locator('#dependency-closure-summary').waitFor();
 assert.ok(await page.locator('[data-native-domain]').count()>=9);
 await page.screenshot({path:path.join(process.argv[3],'02-native-dependencies.png')});
 await page.locator('.modal-close').click();
 const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();
 const download=await downloadPromise;await download.saveAs(path.join(process.argv[3],'integrated.wfchar.zip'));
 await page.locator('[data-page="gameplay"]').click();
 await page.locator('#author-integration-undo').waitFor();await page.locator('#author-integration-undo').click();
 await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden);
 const undone=await page.evaluate(()=>structuredClone(S.p));
 fs.writeFileSync(path.join(process.argv[3],'undone.json'),JSON.stringify(undone));
 assert.equal(undone.nativeGameplay.abilities[0].rows.length,1);
 assert.equal(undone.productionBrief.plans.abilities[0].authorCards.length,2);
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(process.argv[3],'browser-result.json'),JSON.stringify({pageErrors:errors,explicitAppliedCards:1,unknownCardsPreserved:1}));
}finally{await browser.close();}
})().catch(e=>{console.error(e.stack);process.exit(1);});
'''
            try:
                result=subprocess.run([node,'-e',script,str(module),f'http://127.0.0.1:{server.server_port}',str(root),p['id']],
                    capture_output=True,text=True,encoding='utf-8',timeout=100)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                applied=json.loads((root/'applied.json').read_bytes())
                undone=json.loads((root/'undone.json').read_bytes())
                self.assertEqual(applied['nativeGameplay']['source'],before['source'])
                self.assertEqual(applied['nativeGameplay']['skills'],before['skills'])
                self.assertEqual(undone['nativeGameplay'],before)
                native.validate_native(applied['nativeGameplay'])
                native_files,receipt=native.compile_native(applied['nativeGameplay'])
                self.assertTrue(receipt['readback'])
                self.assertFalse(receipt['gameReady'])
                (root/'native-readback.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
                exported=archive_files((root/'integrated.wfchar.zip').read_bytes())
                exported_p=json.loads(exported['project.json'])
                self.assertEqual(exported_p['nativeGameplay'],applied['nativeGameplay'])
                handoff=json.loads(exported['制作交接.json'])
                self.assertFalse(handoff['gameReady'])
                self.assertIn('authorGameplayIntegration',handoff)
                reimported=store.import_archive((root/'integrated.wfchar.zip').read_bytes())
                self.assertEqual(reimported['nativeGameplay'],applied['nativeGameplay'])
                self.assertEqual(reimported['productionBrief']['plans']['abilities'][0]['authorCards'],applied['productionBrief']['plans']['abilities'][0]['authorCards'])
            finally:
                server.shutdown();server.server_close();thread.join(5)
