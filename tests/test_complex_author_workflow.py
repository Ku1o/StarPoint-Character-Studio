"""Chinese complex cards and help save through the actual local browser UI."""
import copy
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
import wave

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import create_server
from studio_core import ProjectStore,archive_files
import native_gameplay as native
from test_native_gameplay import pack


class ComplexAuthorWorkflowTests(unittest.TestCase):
    def test_conditions_combo_and_saved_help_preserve_original_records(self):
        module=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
        node=shutil.which('node')
        if not module.exists() or not node:self.skipTest('Bundled JS Playwright unavailable')
        with tempfile.TemporaryDirectory(prefix='complex-author-ui-') as temp:
            root=Path(os.environ.get('STUDIO_COMPLEX_TEST_ROOT',temp));root.mkdir(parents=True,exist_ok=True)
            store=ProjectStore(root/'projects');p=store.create('复杂中文方案')
            definitions=pack()
            cr=definitions['characters']['10']['records']['character']['selected']['10']['rows'][0]
            cr[2],cr[3],cr[6],cr[9],cr[14],cr[28]='4','3','4','(None)','','pedestal_reference'
            class Library:
                def load(self):return definitions
            p=native.attach(store,p['id'],p['revision'],Library(),'10')
            reference=Path(os.environ.get('STUDIO_NATIVE_COMPLEX_REFERENCE','missing-reference'))
            ui_reference_loaded=False
            if reference.is_file():
                with zipfile.ZipFile(reference) as archive:
                    ui_reference_loaded='scene/battle/pause_menu.ui.amf3.deflate' in archive.namelist()
                    if ui_reference_loaded:
                        for name in archive.namelist():
                            if name.endswith('/'):continue
                            target=store.directory(p['id'])/'reference'/name
                            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(name))
                            p['referenceFiles'].append(name)
                        # Fixture installation is trusted local setup. Normal
                        # author saves intentionally preserve stored references.
                        store._write(p)
            p['productionBrief']['notes']='已有手填说明：保留原稿，不替换声音。'
            p['productionBrief']['plans']['abilities'][0]['authorDescription']='手填复杂想法：召唤两个月球，并沿用原动作。'
            from PIL import Image
            png=io.BytesIO();Image.new('RGBA',(7,9),(180,40,70,220)).save(png,format='PNG')
            aid=store.add_asset(p,'参考画稿.png',png.getvalue())
            wav=io.BytesIO()
            with wave.open(wav,'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(8000);audio.writeframes(b'\x00\x01'*8000)
            sid=store.add_asset(p,'参考声音.wav',wav.getvalue(),category='audio')
            model={'kind':'once','fps':60,'frameScale':2,'runtimeSpeed':0.5,'clips':[{'id':'first','asset':aid,'hold':4,'x':3,'y':2,'rotation':30,'opacity':0.7,'flip':False},{'id':'second','asset':aid,'hold':8,'x':-2,'y':0,'rotation':0,'opacity':1,'flip':True}]}
            p['animations'].append({'id':'reference_actor','name':'测试参考动作','slot':'reference_actor','variant':'normal',**copy.deepcopy(model)})
            p['effects'].append({'id':'reference_effect','name':'测试参考特效',**copy.deepcopy(model)})
            p['sounds'].append({'id':'reference_sound','name':'测试参考声音','asset':sid})
            # Asset intake persists the registered origins and derived files
            # before normal form saves, which preserve the stored asset list.
            store._write(p)
            p=store.save(p);before=copy.deepcopy(p['nativeGameplay'])
            server=create_server(root/'projects');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            script=r'''
const {chromium}=require(process.argv[1]),fs=require('fs'),assert=require('node:assert/strict'),path=require('path');
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});try{
 const page=await browser.newPage({viewport:{width:1450,height:1100}}),errors=[];
 page.on('pageerror',e=>errors.push(String(e)));
 await page.goto(process.argv[2]);await page.waitForFunction(()=>S.token);
 await page.locator('[data-open="'+process.argv[4]+'"]').click();
 await page.locator('[data-page="gameplay"]').click();await page.locator('#native-notes').click();
 await page.locator('[data-creator-plan="ability0"]').click();
 await page.locator('#creator-trigger').selectOption('skill');
 await page.locator('#creator-target').selectOption('battle_combo');await page.locator('#creator-effect').selectOption('combo_add');
 assert.ok(await page.locator('#creator-time').isHidden());
 assert.ok(await page.locator('#creator-stacking').isHidden());
 await page.locator('#creator-amount').fill('10');await page.locator('#creator-conditions summary').click();
 await page.locator('#creator-condition-0').selectOption('hp_at_least');await page.locator('#creator-condition-value-0').fill('80%');
 await page.locator('#creator-condition-1').selectOption('combo_at_most');await page.locator('#creator-condition-value-1').fill('20');
 await page.locator('#creator-compose').click();
 await page.locator('#creator-target').selectOption('self');await page.locator('#creator-effect').selectOption('skill_gauge_up');
 assert.ok(await page.locator('#creator-time').isHidden());assert.ok(await page.locator('#creator-stacking').isHidden());
 await page.locator('#creator-amount').fill('15%');await page.locator('#creator-main-only').check();
 await page.locator('#creator-compose').click();
 await page.locator('#creator-effect').selectOption('custom');
 await page.locator('#creator-complex-details summary').click();await page.locator('#creator-mechanic').selectOption('summon');
 await page.locator('#creator-detail-reference').fill('凉月原动作');await page.locator('#creator-detail-count').fill('两个月球，最多同时两只');
 await page.locator('#creator-reuse-select').click();await page.locator('#creator-reuse-options').waitFor();
 assert.match(await page.locator('#creator-reuse-options').innerText(),/测试技能/);
 const actor=page.locator('[data-reuse-option]').filter({hasText:'测试参考动作'});
 await actor.locator('[data-reuse-preview]').click();await page.locator('#reference-preview-stage').waitFor();
 assert.ok(await page.locator('#reference-preview-stage').evaluate(c=>c.toDataURL().length>300));
 await page.locator('#reference-preview-play').click();await page.waitForFunction(()=>Number(document.querySelector('#reference-preview-scrub')?.value)>0);
 await page.locator('#reference-preview-scrub').focus();await page.locator('#reference-preview-scrub').press('Home');await page.locator('#reference-preview-scrub').press('ArrowRight');
 assert.equal(await page.locator('#reference-preview-scrub').inputValue(),'1');
 await page.locator('#reference-preview-close').click();assert.equal(await page.locator('#reference-preview-dialog').count(),0);
 await page.locator('[data-reuse-option]').filter({hasText:'测试参考特效'}).locator('[data-reuse-preview]').click();
 await page.locator('#reference-preview-stage').waitFor();await page.locator('#reference-preview-close').click();
 await page.locator('[data-reuse-option]').filter({hasText:'测试参考声音'}).locator('[data-reuse-preview]').click();
 const audio=page.locator('#reference-preview-audio');await audio.waitFor();await audio.evaluate(a=>a.play());
 await page.waitForFunction(()=>document.querySelector('#reference-preview-audio').currentTime>0.1);
 await page.locator('#reference-preview-stop').click();assert.ok(await audio.evaluate(a=>a.paused&&a.currentTime===0));
 await page.locator('#reference-preview-close').click();assert.equal(await page.locator('#reference-preview-dialog').count(),0);
 await actor.locator('[data-reuse-preview]').click();await page.locator('#reference-preview-stage').waitFor();await page.locator('#reference-use').click();
 await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden&&!document.querySelector('#modal').open);
 await page.locator('#creator-complex-details summary').click();
 await page.locator('#creator-compose').click();
 await page.locator('[data-creator-plan="activeSkill"]').click();
 await page.locator('#creator-complex-details summary').click();await page.locator('#creator-mechanic').selectOption('special');
 await page.locator('#creator-detail-recovery').fill('被打断时恢复原姿势，保持原声音');
 await page.locator('#creator-compose').click();
 await page.locator('#author-integration-preview').click();await page.locator('#author-integration-result').waitFor();
 assert.equal(await page.locator('[data-integration-card]').count(),2);
 assert.match(await page.locator('#author-integration-result').innerText(),/连击|80/);
 assert.ok(await page.locator('[data-assistance-request]').count()>=1);
 assert.match(await page.locator('#dependency-assistance').innerText(),/凉月原动作|寿命/);
 assert.equal(await page.locator('#author-mechanics-plans').count(),1);
 assert.match(await page.locator('[data-mechanics-plan="summon"]').innerText(),/两个月球|召唤定义与素材/);
 assert.match(await page.locator('[data-mechanics-plan="special"]').innerText(),/恢复原姿势|结束与恢复/);
 const intent=await page.evaluate(()=>({summon:S.p.productionBrief.plans.abilities[0].authorCards[2].text,special:S.p.productionBrief.plans.activeSkill.authorCards[0].text}));
 assert.match(intent.summon,/召唤物或跟随物|两个月球/);assert.doesNotMatch(intent.summon,/攻击力提高|其他效果.*15%/);
 assert.match(intent.special,/特殊能力或形态变化|恢复原姿势/);assert.doesNotMatch(intent.special,/攻击力提高/);
 let step=page.locator('[data-mechanics-plan="special"] .mechanics-todo-row').first();
 await step.locator('select').selectOption('needs_help');await step.locator('textarea').fill('已说明恢复姿势，等待制作方核验');await step.locator('[data-todo-save]').click();
 await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden&&document.querySelector('#author-mechanics-plans'));
 step=page.locator('[data-mechanics-plan="special"] .mechanics-todo-row').first();assert.equal(await step.locator('select').inputValue(),'needs_help');
 assert.match(await page.locator('#mechanics-todo-history').innerText(),/保留的待办记录/);
 await page.screenshot({path:path.join(process.argv[3],'01-complex-preview.png')});
 await page.locator('[data-assistance-save]').first().click();
 await page.waitForFunction(()=>S.page==='production'&&!S.dirty&&document.querySelector('#busy').hidden);
 const helped=await page.evaluate(()=>structuredClone(S.p));
 assert.match(helped.productionBrief.notes,/已有手填说明/);assert.match(helped.productionBrief.notes,/待协助/);
 fs.writeFileSync(path.join(process.argv[3],'helped.json'),JSON.stringify(helped));
 await page.locator('[data-page="gameplay"]').click();
 await page.locator('#author-integration-preview').click();for(const input of await page.locator('[data-integration-card]').all())await input.check();
 await page.locator('#author-integration-apply').click();
 await page.waitForFunction(()=>!S.dirty&&document.querySelector('#busy').hidden&&!document.querySelector('#modal').open);
 const applied=await page.evaluate(()=>structuredClone(S.p));
 assert.equal(applied.productionBrief.plans.abilities[0].authorCards.length,3);
 assert.ok(applied.productionBrief.plans.abilities[0].authorCards[2].details.referenceChoice);
 assert.ok(applied.productionBrief.plans.abilities[0].authorCards[2].details.referenceDigest);
 assert.match(applied.productionBrief.plans.abilities[0].authorDescription,/手填复杂想法/);
 assert.equal(applied.nativeGameplay.abilities[0].rows.length,3);
 fs.writeFileSync(path.join(process.argv[3],'applied.json'),JSON.stringify(applied));
 await page.locator('[data-page="checks"]').click();await page.locator('#dependency-closure-open').click();
 await page.locator('#dependency-closure-summary').waitFor();
 assert.ok(await page.locator('[data-native-domain]').count()>=9);
 assert.ok(await page.locator('#dependency-assistance').count()===1);
 assert.equal(await page.locator('#native-effect-conversion-summary').count(),1);
 assert.match(await page.locator('#native-effect-conversion-summary').innerText(),/作者不用填写技术条目/);
 assert.match(await page.locator('#native-effect-conversion-summary').innerText(),/能力条目另有.*项检查提示/);
 assert.equal(await page.locator('#common-condition-coverage').count(),0);
 const common=await page.locator('#character-shared-materials').innerText();
 assert.match(common,/命中特效、状态图标/);assert.match(common,/这个角色希望的表现/);
 assert.match(common,/制作方技术报告/);assert.doesNotMatch(common,/暂停|Boss|商店|交易/);
 if(process.argv[5]==='ui-loaded'){
  assert.equal(await page.locator('#native-ui-coverage').count(),0);
  const issues=await page.locator('#dependency-closure-result').innerText();
  assert.doesNotMatch(issues,/商店|交易说明|暂停界面|继续游戏界面|set_text|凭name猜文字表/);
  assert.match(await page.locator('#modal').innerText(),/不计入稿主的素材缺项/);
  const closure=await page.evaluate(async()=> (await api('/api/dependency-closure',{id:S.p.id})).dependencyClosure);
  assert.equal(closure.nativeUiCoverage.length,13);
  assert.ok(closure.nativeUiCoverage.every(row=>row.resourceOwner==='game-common-ui'));
  assert.ok(closure.assistance.technicalRequests.length>0);
  assert.ok(closure.assistance.technicalRequests.every(row=>row.authorInputRequired===false));
  assert.ok(closure.assistance.requests.every(row=>(row.evidence||[]).every(item=>item.resourceOwner!=='game-common-ui')));
  assert.ok(closure.authorCounts.missing<closure.counts.missing);
  assert.ok(closure.authorCounts.dynamic<closure.counts.dynamic);
  assert.ok(closure.nativeDefinitionCoverage.commonConditionalCoverage.some(row=>row.title==='暂停按钮'));
  assert.ok(closure.nativeDefinitionCoverage.commonConditionalCoverage.some(row=>row.resourceOwner==='game-common-ui'));
  fs.writeFileSync(path.join(process.argv[3],'scope-separated-closure.json'),JSON.stringify(closure));
 }
 await page.screenshot({path:path.join(process.argv[3],'02-recursive-help.png')});
 await page.locator('.modal-close').click();
 const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();
 await (await downloadPromise).saveAs(path.join(process.argv[3],'complex.wfchar.zip'));
 assert.deepEqual(errors,[]);fs.writeFileSync(path.join(process.argv[3],'browser-result.json'),JSON.stringify({pageErrors:errors,appliedComplexCards:2,unknownCardsPreserved:2,referenceAnimationPlayed:true,referenceEffectPreviewed:true,referenceOriginalSoundPlayedAndStopped:true,previewChoiceCallback:true,todoSavedAndReopened:true,explicitReferenceSelected:true,specialRecoveryPreserved:true,helpSavedWithoutOverwrite:true,automaticConditionChecks:true,commonUiTechnicalOnly:process.argv[5]==='ui-loaded'}));
}finally{await browser.close();}})().catch(e=>{console.error(e.stack);process.exit(1);});
'''
            try:
                result=subprocess.run([node,'-e',script,str(module),f'http://127.0.0.1:{server.server_port}',str(root),p['id'],'ui-loaded' if ui_reference_loaded else 'ui-unavailable'],capture_output=True,text=True,encoding='utf8',timeout=140)
                self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)
                helped=json.loads((root/'helped.json').read_bytes());applied=json.loads((root/'applied.json').read_bytes())
                self.assertEqual(helped['nativeGameplay'],before)
                self.assertEqual(applied['nativeGameplay']['source'],before['source'])
                self.assertEqual(applied['nativeGameplay']['skills'],before['skills'])
                self.assertEqual(applied['nativeGameplay']['abilities'][0]['rows'][:-2],before['abilities'][0]['rows'])
                self.assertEqual(applied['nativeGameplay']['leader'],before['leader'])
                _,receipt=native.compile_native(applied['nativeGameplay']);self.assertTrue(receipt['readback']);self.assertFalse(receipt['gameReady'])
                exported=archive_files((root/'complex.wfchar.zip').read_bytes());saved=json.loads(exported['project.json'])
                self.assertEqual(saved['nativeGameplay'],applied['nativeGameplay'])
                self.assertEqual(saved['productionBrief']['notes'],applied['productionBrief']['notes'])
                handoff=json.loads(exported['制作交接.json']);self.assertTrue(handoff['assistance']['requests']);self.assertFalse(handoff['gameReady'])
                imported=store.import_archive((root/'complex.wfchar.zip').read_bytes())
                self.assertEqual(imported['nativeGameplay'],applied['nativeGameplay'])
                self.assertEqual(imported['productionBrief']['plans']['abilities'][0]['authorCards'],applied['productionBrief']['plans']['abilities'][0]['authorCards'])
                self.assertEqual(imported['productionBrief']['plans']['abilities'][0]['authorCards'][2]['details']['reference'],'凉月原动作')
                self.assertTrue(handoff['mechanicsIntegration']['plans'])
                self.assertTrue(any(plan['mechanic']=='special' for plan in handoff['mechanicsIntegration']['plans']))
                self.assertEqual(imported['mechanicsTodo'],applied['mechanicsTodo'])
            finally:
                server.shutdown();server.server_close();thread.join(5)


if __name__=='__main__':unittest.main()
