"""A real browser author path using ordinary controls, with retained originals."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from PIL import Image

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore, archive_files, png_bytes

class NoCodeWorkflowTests(unittest.TestCase):
    def test_original_author_choices_assistance_source_search_and_roundtrip(self):
        module=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
        node=shutil.which('node')
        if not module.exists() or not node:self.skipTest('Bundled JS Playwright unavailable')
        with tempfile.TemporaryDirectory(prefix='no-code-author-') as temp:
            root=Path(temp)
            raw=png_bytes(Image.new('RGBA',(16,16),(120,60,240,255)))
            with zipfile.ZipFile(root/'author.zip','w',zipfile.ZIP_DEFLATED) as archive:
                for index in range(120):archive.writestr(f'art/image_{index:03}.png',raw)
                archive.writestr('notes/author.txt','允许裁切派生；未知玩法请协助。')
            (root/'idle.png').write_bytes(raw)
            (root/'idle_glow.png').write_bytes(raw)
            before=hashlib.sha256((root/'author.zip').read_bytes()).hexdigest()
            server=create_server(root/'projects')
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            script=r'''
const {chromium}=require(process.argv[1]),fs=require('fs'),assert=require('assert'),path=require('path');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1400,height:1100}}),errors=[];
  page.on('pageerror',error=>errors.push(String(error)));await page.goto(process.argv[2]);await page.waitForFunction(()=>S.token);
  await page.locator('#new-original').click();await page.locator('#dialog-name').fill('不会代码的作者');await page.locator('#dialog-ok').click();await page.locator('#identity-name').waitFor();
  assert.equal(await page.locator('#identity-code').count(),0);
  await page.locator('#identity-title').fill('星光旅人');await page.locator('#identity-title').blur();
  assert.equal(await page.evaluate(()=>S.p.productionBrief.author.title),'星光旅人');
  await page.locator('[data-page="guide"]').click();assert.equal(await page.locator('[data-creator-go]').count(),8);
  await page.locator('[data-creator-go="gameplay"]').click();
  await page.locator('#creator-plan-name').fill('星光祝福');await page.locator('#creator-plan-name').blur();
  await page.locator('#creator-trigger').selectOption('battle_start');await page.locator('#creator-target').selectOption('party');await page.locator('#creator-effect').selectOption('attack_up');
  await page.locator('#creator-amount').fill('20%');await page.locator('#creator-time').fill('10秒');await page.locator('#creator-compose').click();
  assert((await page.locator('#creator-plan-description').inputValue()).includes('20%'));
  assert.equal(await page.evaluate(()=>S.p.gameplay.skill.name),'星光祝福');
  await page.locator('#creator-plan-help').fill('希望协助确认是否支持该效果。');await page.locator('[data-creator-plan="leader"]').click();await page.locator('[data-creator-plan="activeSkill"]').click();
  assert.equal(await page.locator('#creator-plan-help').inputValue(),'希望协助确认是否支持该效果。');
  assert.equal(await page.locator('#creator-trigger').inputValue(),'battle_start');await page.locator('#creator-request-help').click();await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden);
  await page.locator('[data-page="identity"]').click();
  const chooser=page.waitForEvent('filechooser');await page.locator('#source-intake-upload').click();await (await chooser).setFiles(path.join(process.argv[3],'author.zip'));
  await page.waitForFunction(()=>S.p.sourceIntake?.sources.length===121);
  await page.locator('#source-intake-search').evaluate(node=>node.closest('details').open=true);
  await page.locator('#source-intake-next').click();await page.locator('#source-intake-next').click();assert((await page.locator('#source-intake-list').innerText()).includes('image_119.png'));
  await page.locator('#source-intake-search').fill('image_119.png');assert.equal(await page.locator('[data-source-use]').count(),1);await page.locator('[data-source-use]').click();await page.waitForFunction(()=>Object.keys(S.p.assets).length===1&&document.querySelector('#busy').hidden);
  await page.locator('[data-page="animations"]').click();await page.locator('#pixel-batch-import').click();await page.locator('#pixel-files-input').setInputFiles([path.join(process.argv[3],'idle.png'),path.join(process.argv[3],'idle_glow.png')]);
  await page.locator('#pixel-companion-notice').waitFor({state:'visible'});
  assert((await page.locator('#pixel-companion-notice').innerText()).includes('1 组同路径/动作/序号的纯本体与合成素材'));
  assert((await page.locator('#pixel-source-summary').innerText()).includes('纯本体 1 / 疑似合成 1 / 未分类 0'));
  assert.equal(await page.locator('.pixel-source-plain').count(),1);assert.equal(await page.locator('.pixel-source-composite').count(),1);
  const compositeGroup=page.locator('.pixel-import-group').filter({has:page.locator('.pixel-source-composite')});
  assert.equal(await compositeGroup.locator('[data-pixel-target]').inputValue(),'');
  const baseTarget=await page.evaluate(()=>S.p.animations.find(a=>a.slot==='neutral'&&!a.native)?.id||'preset:neutral');
  await compositeGroup.locator('[data-pixel-target]').selectOption(baseTarget);await page.locator('#pixel-import-risk').waitFor({state:'visible'});
  const untouched=await page.evaluate(()=>JSON.stringify({assets:S.p.assets,animations:S.p.animations,sourceIntake:S.p.sourceIntake}));
  await page.locator('#pixel-import-confirm').click();await page.locator('#toast').waitFor({state:'visible'});
  assert((await page.locator('#toast').innerText()).includes('疑似合成帧'));
  assert.equal(await page.evaluate(()=>JSON.stringify({assets:S.p.assets,animations:S.p.animations,sourceIntake:S.p.sourceIntake})),untouched);
  await page.locator('[data-pixel-filter="plain"]').click();
  assert((await page.locator('#pixel-source-summary').innerText()).includes('纯本体 1 / 疑似合成 0 / 未分类 0'));
  assert.equal(await page.locator('.pixel-source-composite').count(),0);assert.equal(await page.locator('.pixel-import-group').count(),1);
  assert((await page.locator('#pixel-companion-notice').innerText()).includes('筛选排除 1 个文件'));
  await page.locator('[data-pixel-filter="all"]').click();await page.locator('#pixel-import-risk').waitFor({state:'visible'});
  assert.equal(await compositeGroup.locator('[data-pixel-target]').inputValue(),baseTarget);
  await page.locator('#pixel-risk-inbox').click();assert.equal(await compositeGroup.locator('[data-pixel-target]').inputValue(),'');
  await page.locator('#pixel-import-risk').waitFor({state:'hidden'});await page.locator('#pixel-import-close').click();
  await page.locator('[data-page="production"]').click();
  await page.locator('[data-pb-pick="resources.0"]').evaluate(node=>node.closest('details').open=true);await page.locator('[data-pb-pick="resources.0"]').click();await page.locator('#pb-asset-options input').first().check();await page.locator('#pb-asset-confirm').click();
  assert.equal(await page.evaluate(()=>S.p.productionBrief.resources[0].assetIds.length),1);
  const voiceMode=page.locator('[data-pb-path="authorPolicy.voiceMode"]');await voiceMode.evaluate(node=>node.closest('details').open=true);await voiceMode.selectOption('none');
  await page.locator('[data-pb-path="authorPolicy.voiceReason"]').fill('角色暂不配音，音效请协助。');await page.locator('[data-pb-path="authorPolicy.voiceReason"]').blur();
  await page.locator('[data-pb-path="notes"]').fill('这是立即导出的最新协助说明。');await page.locator('[data-pb-path="notes"]').blur();
  const handoffDownload=page.waitForEvent('download');await page.locator('#production-export').click();await (await handoffDownload).saveAs(path.join(process.argv[3],'handoff.json'));
  await page.locator('[data-page="checks"]').click();await page.locator('#dependency-closure-open').waitFor();
  assert.equal(await page.locator('#character-audit-json,#dependency-scope-json,#atlas-options-json').count(),0);
  await page.locator('#dependency-closure-open').click();await page.locator('#dependency-closure-summary').waitFor();assert((await page.locator('#modal-content').innerText()).includes('尚未全部核验'));await page.locator('.modal-close').click();
  await page.locator('[data-page="guide"]').click();await page.screenshot({path:path.join(process.argv[3],'creator-guide.png'),fullPage:true});
  await page.locator('[data-page="gameplay"]').click();await page.screenshot({path:path.join(process.argv[3],'creator-gameplay.png'),fullPage:true});
  const exported=page.waitForEvent('download');await page.locator('#export').click();await (await exported).saveAs(path.join(process.argv[3],'author.wfchar.zip'));
  const final=await page.evaluate(()=>({id:S.p.id,brief:S.p.productionBrief,sourceIntake:S.p.sourceIntake,identity:S.p.identity,gameplay:S.p.gameplay,hasNative:!!S.p.nativeGameplay}));
  await page.locator('#home').click();await page.locator('#import-project').click();await page.locator('#zip-input').setInputFiles(path.join(process.argv[3],'author.wfchar.zip'));await page.waitForFunction(id=>S.p?.id&&S.p.id!==id,final.id);
  assert.deepStrictEqual(await page.evaluate(()=>S.p.productionBrief),final.brief);assert.deepStrictEqual(await page.evaluate(()=>S.p.sourceIntake),final.sourceIntake);assert(!final.hasNative);
  assert.deepStrictEqual(errors,[]);fs.writeFileSync(path.join(process.argv[3],'result.json'),JSON.stringify({...final,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
'''
            try:
                result=subprocess.run([node,'-e',script,str(module),f'http://127.0.0.1:{server.server_port}',str(root)],capture_output=True,text=True,encoding='utf-8',timeout=120)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                final=json.loads((root/'result.json').read_text(encoding='utf-8'))
                restored=server.store.load(final['id'])
                handoff=json.loads((root/'handoff.json').read_text(encoding='utf-8'))
                self.assertIn('这是立即导出的最新协助说明。',json.dumps(handoff,ensure_ascii=False))
                self.assertFalse(handoff['gameReady'])
                members=archive_files((root/'author.wfchar.zip').read_bytes())
                original_members=[value for name,value in members.items() if name.startswith('sources/')]
                self.assertEqual(len(final['sourceIntake']['sources']),121)
                self.assertTrue(all(any(hashlib.sha256(value).hexdigest()==row['sha256'] for value in original_members)
                                    for row in final['sourceIntake']['sources']))
                self.assertEqual({row['path'] for row in final['sourceIntake']['sources']},
                                 {f'art/image_{index:03}.png' for index in range(120)}|{'notes/author.txt'})
                self.assertEqual(hashlib.sha256((root/'author.zip').read_bytes()).hexdigest(),before)
                self.assertEqual(final['brief']['plans']['activeSkill']['authorCards'][0]['amount'],'20%')
                evidence=os.environ.get('NO_CODE_WORKFLOW_EVIDENCE')
                if evidence:
                    output=Path(evidence);output.mkdir(parents=True,exist_ok=True)
                    for name in ['result.json','creator-guide.png','creator-gameplay.png','author.wfchar.zip','handoff.json']:shutil.copy2(root/name,output/name)
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':unittest.main()
