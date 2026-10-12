"""Opt-in real Edge and legacy-artifact integration checks in an explicit root.

Set STUDIO_UPGRADE_TEST_ROOT, STUDIO_TEST_NODE, STUDIO_TEST_NODE_MODULES and
STUDIO_TEST_EDGE to run browser checks. STUDIO_TEST_LEGACY_WFCHAR selects a
read-only input copied by import into the isolated test store.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_core import ProjectStore, png_bytes, archive_files
from studio_compile import compile_project
from character_audit import compiled_report
from studio import create_server


BROWSER_SCRIPT = r"""
const fs=require('fs'),assert=require('assert'),{chromium}=require('playwright');
const options=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
 const browser=await chromium.launch({executablePath:options.edge,headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1080}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 async function check(name,fn){try{const detail=await fn();checks.push({name,passed:true,detail});}catch(e){checks.push({name,passed:false,error:e.message});await page.screenshot({path:options.artifacts+'/failed-check-'+checks.length+'.png'});}}
 try{
 await page.goto(options.url);await page.locator('[data-open="'+options.fixture+'"]').click();
 await page.locator('[data-page="effects"]').click();await page.locator('[data-skill-tab="scene"]').click();
 await check('Ball HideCharacter warning and deferred displayed',async()=>{
   await page.getByText('已知无效',{exact:true}).first().waitFor();
   assert((await page.locator('#content').innerText()).includes('Ball不支持HideCharacter'));
   const source=await page.evaluate(()=>S.p.scene.source);
   assert(source.deferred.some(d=>d.status==='known-invalid'&&d.subject===-18));
   assert.strictEqual(source.trust.nativeVerified,false);
   await page.screenshot({path:options.artifacts+'/skill-invalid-ball.png'});
   return {deferred:source.deferred,trust:source.trust};
 });
 await check('manual scene and compiled preview retain offline trust',async()=>{
   await page.locator('#add-actor').click();await page.locator('[data-skill-pick]').first().click();
   await page.locator('#save').click();
   assert((await page.locator('#content').innerText()).includes('原生坐标和命中待核'));
   const data=await page.evaluate(async()=>{await saveNow();return await api('/api/compiled-preview',{id:S.p.id,group:'scene',animation:''});});
   assert.strictEqual(data.trust.nativeVerified,false);
   assert.strictEqual(data.trust.previewKind,'compiled_material_arrangement');
   assert(data.issues.some(x=>x.includes('不证明世界坐标')));
   await page.locator('#compiled-preview').click();await page.locator('#readback-stage').waitFor();
   assert((await page.locator('#modal-content').innerText()).includes('游戏镜头、场景和命中行为仍需接入验证'));
   await page.locator('.modal-close').click();
   return {sourceKind:await page.evaluate(()=>S.p.scene.source.kind),trust:data.trust,issues:data.issues};
 });
 await check('character audit final check page button and declaration save',async()=>{
   await page.locator('[data-page="checks"]').click();await page.locator('#compile-assets').waitFor();
   await page.locator('#character-audit-open').waitFor({timeout:3000});
   await page.locator('#character-audit-open').click();await page.locator('#character-audit-json').waitFor({state:'attached'});
   assert((await page.locator('#modal-content').innerText()).includes('GPU draw calls 未测'));
   const declaration={scope:{roles:['main'],forms:['normal'],switches:[],closed:false},dependencies:[{logical:'fixture/sheet',bucket:'BattlePart',collection:'main',layer:0,width:20,height:30,category:'skill',source:'headless-fixture',requester:'caster',collectionDedupe:'logical'}],futureField:{preserve:true}};
   await page.locator('#modal-content details').click();await page.locator('#character-audit-json').fill(JSON.stringify(declaration));
   await page.locator('#character-audit-save').click();
   await page.waitForFunction(()=>document.querySelector('#character-audit-json')?.value.includes('futureField'));
   const persisted=await page.evaluate(async()=>await api('/api/project?id='+S.p.id));
   assert.deepStrictEqual(persisted.characterAudit,declaration);
   const audit=await page.evaluate(async()=>await api('/api/character-audit',{id:S.p.id}));
   assert.strictEqual(audit.layers['0'].knownAreaPixels,22*32);
   assert.strictEqual(audit.closure.completeCharacterTotal,false);
   await page.screenshot({path:options.artifacts+'/character-audit.png'});
   await page.locator('.modal-close').click();
   return {declarationPreserved:true,closure:audit.closure};
 });
 await check('nameplate full and half preview decode as 320x50 and 160x25',async()=>{
   if(await page.locator('#modal').evaluate(e=>e.open))await page.locator('.modal-close').click();
   await page.locator('[data-page="degrees"]').click();
   const full=page.getByAltText('铭牌原尺寸'),half=page.getByAltText('铭牌半尺寸');
   await full.waitFor();await full.evaluate(e=>e.decode());await half.evaluate(e=>e.decode());
   assert.deepStrictEqual(await full.evaluate(e=>[e.naturalWidth,e.naturalHeight]),[320,50]);
   const halfInfo=await half.evaluate(e=>({size:[e.naturalWidth,e.naturalHeight],src:e.src,currentSrc:e.currentSrc}));
   assert.deepStrictEqual(halfInfo.size,[160,25],JSON.stringify(halfInfo));
   await page.locator('#degree-check').click();await page.locator('#modal-content pre').waitFor();
   const report=JSON.parse(await page.locator('#modal-content pre').innerText());
   assert.strictEqual(report.gameReady,false);assert.strictEqual(report.degrees[0].nativeVerified,false);
   await page.screenshot({path:options.artifacts+'/degree-preview.png'});
   await page.locator('.modal-close').click();return report;
 });
 await check('nameplate lettering selection upload and missing-layer state',async()=>{
   await page.locator('[data-degree-lettering]').click();await page.locator('[data-choose="'+options.lettering+'"]').click();
   await page.getByAltText('完整文字效果层').waitFor();
   await page.locator('[data-degree-mask]').click();await page.locator('[data-choose="'+options.safeMask+'"]').click();
   await page.locator('[data-degree-evidence]').fill('headless fixture declared inner mask');
   await page.locator('[data-degree-evidence]').dispatchEvent('change');
   await page.locator('#save').click();
   await page.locator('#degree-check').click();await page.locator('#modal-content pre').waitFor();
   const before=JSON.parse(await page.locator('#modal-content pre').innerText()).degrees[0];
   assert.strictEqual(before.safeAreaCheckObject,'lettering_with_outline_and_shadow');
   assert.strictEqual(before.letteringOutsideSafePixels,0);assert(before.wholeArtworkCandidateOutsideSafePixels>0);
   assert.strictEqual(before.safeAreaStatus,'inside_declared_mask');
   await page.locator('.modal-close').click();
   await page.locator('[data-degree-lettering-upload]').click();await page.locator('#media-input').setInputFiles(options.letteringPath);
   await page.waitForFunction(old=>S.p.degrees[0].letteringAsset&&S.p.degrees[0].letteringAsset!==old,options.lettering);
   await page.locator('#save').click();
   const saved=await page.evaluate(async()=>{await saveNow();return await api('/api/project?id='+S.p.id);});
   assert(saved.degrees[0].letteringAsset&&saved.degrees[0].letteringAsset!==options.lettering);
   await page.screenshot({path:options.artifacts+'/degree-lettering-ui.png'});
   await page.locator('[data-degree-lettering-clear]').click();await page.locator('#save').click();
   const after=await page.evaluate(async()=>{await saveNow();return await api('/api/degree-check',{id:S.p.id});});
   assert.strictEqual(after.degrees[0].safeAreaStatus,'needs_lettering_layer');
   assert.strictEqual(after.degrees[0].safeAreaCheckObject,'whole_artwork_candidate');
   assert.strictEqual(after.degrees[0].letteringOutsideSafePixels,null);
   return {selection:before,uploadPersisted:true,removedLayerStatus:after.degrees[0].safeAreaStatus};
 });
 await check('old project optional nameplate page is safe to browse',async()=>{
   await page.locator('#home').click();await page.locator('[data-open="'+options.legacy+'"] ').click();
   await page.locator('[data-page="degrees"]').click();
   assert((await page.locator('#content').innerText()).includes('没有铭牌需求也可以交接角色工程'));
   return {optional:true};
 });
 await check('no browser pageerrors',async()=>{assert.deepStrictEqual(errors,[]);return errors;});
 }finally{await browser.close();}
 const report={browser:'Edge headless',checks,pageerrors:errors};console.log(JSON.stringify(report));
 if(checks.some(c=>!c.passed))process.exitCode=1;
})().catch(e=>{console.log(JSON.stringify({fatal:e.stack}));process.exitCode=1;});
"""


class UpgradePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path(os.environ.get('STUDIO_UPGRADE_TEST_ROOT', tempfile.gettempdir())).resolve()
        cls.output.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='upgrade-preview-', dir=cls.output)
        cls.root = Path(cls.temp.name)
        cls.store = ProjectStore(cls.root / 'projects')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @unittest.skipUnless(os.environ.get('STUDIO_TEST_LEGACY_WFCHAR'), 'real legacy wfchar input not selected')
    def test_real_legacy_import_compiled_report_does_not_invent_collection(self):
        source = Path(os.environ['STUDIO_TEST_LEGACY_WFCHAR']).resolve()
        original = source.read_bytes(); source_hash = hashlib.sha256(original).hexdigest()
        try:
            project = self.store.import_archive(original)
        except Exception as exc:
            (self.output / 'legacy-preview-result.json').write_text(json.dumps({'source': str(source), 'sourceSHA256': source_hash,
                'status': 'failed-import', 'errorType': type(exc).__name__, 'error': str(exc),
                'originalUnchanged': source.read_bytes() == original}, ensure_ascii=False, indent=2), 'utf-8')
            raise
        project_path = self.store.directory(project['id']) / 'project.json'
        before = project_path.read_bytes()
        loaded = self.store.load(project['id'])
        artifact, report = compile_project(self.store, project['id'])
        self.assertEqual(project_path.read_bytes(), before)
        audit = compiled_report(loaded, archive_files(artifact))
        self.assertTrue(audit['compiledSheets'])
        self.assertGreater(audit['assetBytes'], 0)
        self.assertFalse(audit['closure']['completeCharacterTotal'])
        self.assertFalse(audit['nativePackingVerified'])
        self.assertFalse(report['gameReady'])
        self.assertEqual(source.read_bytes(), original)
        evidence = {'source': str(source), 'sourceSHA256': source_hash, 'isolatedProject': project['id'],
                    'originalUnchanged': True, 'importedProjectReadUnchanged': True,
                    'compiledFiles': len(report['files']), 'compiledSheets': len(audit['compiledSheets']),
                    'compiledParts': len(audit['compiledParts']), 'closure': audit['closure'],
                    'unknownCount': len(audit['unknown']), 'nativePackingVerified': False, 'gameReady': False}
        (self.output / 'legacy-preview-result.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), 'utf-8')

    @unittest.skipUnless(all(os.environ.get(key) for key in ('STUDIO_TEST_NODE', 'STUDIO_TEST_NODE_MODULES', 'STUDIO_TEST_EDGE', 'STUDIO_UPGRADE_TEST_ROOT')), 'explicit browser runtime and artifact root not selected')
    def test_headless_ui_warning_declaration_save_and_optional_degrees(self):
        project = self.store.create('Headless upgrade fixture')
        actor_asset = self.store.add_asset(project, 'body.png', png_bytes(Image.new('RGBA', (16, 24), (20, 90, 110, 255))), 'pixel')
        degree_asset = self.store.add_asset(project, 'degree.png', png_bytes(Image.new('RGBA', (320, 50), (20, 90, 110, 255))), 'degree')
        lettering = Image.new('RGBA', (320, 50)); lettering.putpixel((120, 25), (255, 240, 20, 255))
        lettering_asset = self.store.add_asset(project, 'complete-lettering.png', png_bytes(lettering), 'image')
        safe_mask = Image.new('RGBA', (320, 50)); safe_mask.paste((0, 0, 0, 255), (100, 10, 220, 40))
        safe_mask_asset = self.store.add_asset(project, 'fixture-safe-mask.png', png_bytes(safe_mask), 'image')
        lettering.putpixel((120, 25), (254, 239, 19, 255))
        lettering_path = self.root / 'uploaded-lettering.png'; lettering.save(lettering_path)
        project['animations'][0]['clips'] = [{'asset': actor_asset, 'hold': 30, 'x': 0, 'y': 0, 'scale': 1, 'rotation': 0, 'opacity': 1}]
        project['effects'] = [{'id': 'fixture_effect', 'name': 'Stage fixture', 'kind': 'once', 'fps': 60, 'frameScale': 1,
                               'clips': [{'asset': actor_asset, 'hold': 30, 'x': 0, 'y': 0, 'scale': 1, 'rotation': 0, 'opacity': 1}]}]
        project['template'] = {'name': 'Isolated scripted fixture', 'version': 'fixture'}
        project['degrees'] = [{'id': 'test_degree', 'name': 'Fixture degree', 'asset': degree_asset, 'safeAreaEvidence': '', 'note': ''}]
        self.store._write(project)
        reference = self.store.directory(project['id']) / 'reference/data_readable'
        reference.mkdir(parents=True)
        (reference / 'skill_dependencies.json').write_text(json.dumps({'programs': [{'logical': 'fixture/action', 'tree': ['Block', [['Command', ['HideCharacter', -18, 48]]]]}]}), 'utf-8')
        legacy = self.store.create('Old optional fixture')
        for key in ('degrees', 'sourceIntake', 'characterAudit', 'skillPreview'):
            legacy.pop(key, None)
        self.store._write(legacy)
        legacy_path = self.store.directory(legacy['id']) / 'project.json'
        original_legacy = legacy_path.read_bytes()
        server = create_server(self.store.root)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            options = {'url': f'http://127.0.0.1:{server.server_port}', 'fixture': project['id'], 'legacy': legacy['id'],
                       'edge': os.environ['STUDIO_TEST_EDGE'], 'artifacts': self.output.as_posix(), 'lettering': lettering_asset,
                       'safeMask': safe_mask_asset, 'letteringPath': str(lettering_path)}
            env = dict(os.environ, NODE_PATH=os.environ['STUDIO_TEST_NODE_MODULES'])
            run = subprocess.run([os.environ['STUDIO_TEST_NODE'], '-e', BROWSER_SCRIPT], input=json.dumps(options),
                                 text=True, encoding='utf-8', capture_output=True, env=env, timeout=90)
            (self.output / 'browser-preview-result.json').write_text(run.stdout, 'utf-8')
            (self.output / 'browser-preview-stderr.log').write_text(run.stderr, 'utf-8')
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(legacy_path.read_bytes(), original_legacy)
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
