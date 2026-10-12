"""Compiler, persistence, HTTP and real browser integration for atlas workflows."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from atlas_editor import atlas_data
from studio import create_server
from studio_compile import compile_pixelart, compile_project, compiled_preview
from studio_core import ProjectStore, archive_files, png_bytes


def tree_state(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


def fixture(store):
    p = store.create('Atlas integration fixture')
    p['identity']['code'] = 'atlas_fixture'
    image = Image.new('RGBA', (8, 12), (191, 29, 87, 0))
    image.putpixel((1, 2), (255, 10, 40, 255))
    image.putpixel((6, 10), (0, 180, 255, 160))
    aid = store.add_asset(p, 'author.png', png_bytes(image))
    p['animations'] = [{'id': 'action1', 'name': '待机', 'slot': 'neutral', 'variant': 'normal',
                        'kind': 'loop', 'fps': 60, 'frameScale': 6,
                        'clips': [{'asset': aid, 'hold': 9, 'x': -4, 'y': -12,
                                   'flip': False, 'rotation': 0, 'scale': 1, 'opacity': 1}]}]
    p['futureField'] = {'preserved': True}
    store._write(p)
    return p


class AtlasWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='atlas-workflow-integration-')
        self.root = Path(self.temp.name)
        self.store = ProjectStore(self.root / 'projects')
        self.p = fixture(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_layout_and_read_only_optimization_preserve_compiled_payloads(self):
        before = tree_state(self.store.root)
        baseline_zip, baseline = compile_project(self.store, self.p['id'])
        optimized_zip, optimized = compile_project(self.store, self.p['id'], optimize=True)
        old, new = archive_files(baseline_zip), archive_files(optimized_zip)
        source, _ = compile_pixelart(self.store, self.p, self.p['animations'], 'normal', 'atlas_fixture')
        for path, raw in source.items():
            self.assertEqual(raw, old['compiled/common/' + path])
        self.assertFalse(baseline['atlasOptimization']['enabled'])
        self.assertEqual(optimized['atlasOptimization']['optimizedBundles'], 1)
        self.assertGreater(optimized['atlasOptimization']['savedPaddedArea'], 0)
        receipt = optimized['atlasOptimization']['bundles'][0]
        permitted = {receipt['png'], receipt['atlas'], 'report.json', '图集无损优化.json',
                     '整角色图集审计.json', '角色依赖闭包.json'}
        self.assertEqual(set(old), set(new))
        for path in old:
            if path not in permitted:
                self.assertEqual(old[path], new[path], path)
        self.assertEqual(tree_state(self.store.root), before)
        self.assertFalse(optimized['gameReady'])
        self.assertFalse(optimized['dependencyClosure']['closure']['completeCharacterTotal'])

    def test_enabled_preview_export_and_config_roundtrip_agree(self):
        original = compiled_preview(self.store, self.p['id'], 'animations', 'action1')
        p = self.store.load(self.p['id'])
        p['atlasOptimization'] = {'enabled': True, 'futureRecipe': {'keep': 'unknown'}}
        p['dependencyScope'] = {'kind': 'project-resources', 'futureScope': ['preserve']}
        saved = self.store.save(p)
        before = tree_state(self.store.root)
        optimized = compiled_preview(self.store, p['id'], 'animations', 'action1')
        for key in ('frames', 'assets', 'audio', 'scale', 'kind', 'runtimeSpeed'):
            self.assertEqual(original[key], optimized[key], key)
        self.assertEqual(optimized['atlasOptimization']['optimizedBundles'], 1)
        sheet, records, label, _ = atlas_data(self.store, saved, 'animations', 'action1')
        raw, report = compile_project(self.store, p['id'])
        receipt = report['atlasOptimization']['bundles'][0]
        self.assertEqual(list(sheet.size), [receipt['after']['width'], receipt['after']['height']])
        self.assertIn('无损优化已核验', label)
        archive = self.store.export(p['id'])
        self.assertEqual(tree_state(self.store.root), before)
        restored_store = ProjectStore(self.root / 'restored')
        restored = restored_store.import_archive(archive)
        for key in ('atlasOptimization', 'dependencyScope', 'futureField'):
            self.assertEqual(saved[key], restored[key])
        restored['atlasOptimization']['enabled'] = False
        restored_store.save(restored)
        _, report = compile_project(restored_store, restored['id'])
        self.assertFalse(report['atlasOptimization']['enabled'])

    def test_invalid_options_scope_and_future_format_reject_without_write(self):
        for changes in ({'atlasOptimization': {'enabled': 'true'}},
                        {'atlasOptimization': {'enabled': True, 'max_ticks': 0}},
                        {'dependencyScope': {'roots': [{'logical': '../game/private'}]}},
                        {'formatVersion': 999}):
            proposed = copy.deepcopy(self.p)
            proposed.update(changes)
            before = tree_state(self.store.root)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.store.save(proposed)
            self.assertEqual(tree_state(self.store.root), before)

    def test_global_budget_preview_matches_whole_project_skipped_sheet(self):
        p = self.store.load(self.p['id'])
        special = copy.deepcopy(p['animations'][0])
        special.update(id='special1', variant='special', name='特殊动作')
        p['animations'].append(special)
        p['atlasOptimization'] = {'enabled': True, 'max_pixels': 20000}
        saved = self.store.save(p)
        raw, report = compile_project(self.store, saved['id'])
        self.assertEqual(report['atlasOptimization']['optimizedBundles'], 1)
        self.assertEqual(report['atlasOptimization']['skippedBundles'], 1)
        # Stable optimizer file ordering spends the budget on special first.
        preview = compiled_preview(self.store, saved['id'], 'animations', 'action1')
        self.assertEqual(preview['atlasOptimization']['selectionBasis'], 'whole-project-budget')
        self.assertEqual(preview['atlasOptimization']['selectedBundles'][0]['status'], 'skipped')
        files = archive_files(raw)
        for record in preview['files']:
            self.assertEqual(record['sha256'], hashlib.sha256(files['compiled/common/' + record['path']]).hexdigest())
        sheet, _, label, _ = atlas_data(self.store, saved, 'animations', 'action1')
        self.assertEqual(sheet.width, 1024)
        self.assertIn('保留原布局', label)

    def test_http_analysis_requires_token_and_does_not_save_revision(self):
        server = create_server(self.store.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}'
        try:
            session = json.load(urllib.request.urlopen(url + '/api/session'))
            body = json.dumps({'id': self.p['id']}).encode()
            before = tree_state(self.store.root)
            for endpoint in ('/api/atlas-optimization', '/api/dependency-closure'):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(url + endpoint, data=body))
                self.assertEqual(error.exception.code, 400)
                response = json.load(urllib.request.urlopen(urllib.request.Request(url + endpoint, data=body,
                    headers={'X-Studio-Token': session['token'], 'Content-Type': 'application/json'})))
                self.assertEqual(response['sourceRevision'], self.p['revision'])
                self.assertFalse(response['gameReady'])
            self.assertEqual(tree_state(self.store.root), before)
            draft = self.store.load(self.p['id'])
            draft['identity']['code'] = ''
            self.store._write(draft)
            before = tree_state(self.store.root)
            response = json.load(urllib.request.urlopen(urllib.request.Request(url + '/api/dependency-closure', data=body,
                headers={'X-Studio-Token': session['token'], 'Content-Type': 'application/json'})))
            self.assertEqual(response['dependencyClosure']['compiledCoverage']['status'], 'unavailable')
            self.assertTrue(response['dependencyClosure']['sourceDefinitionProblems'])
            self.assertFalse(response['dependencyClosure']['closure']['completeCharacterTotal'])
            self.assertEqual(tree_state(self.store.root), before)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_browser_preview_enable_undo_save_reload_scope_and_archive(self):
        scope = {'kind': 'character-semantic', 'closed': True, 'roles': ['main'],
                 'forms': ['base'], 'futureScope': {'keep': True}}
        p = self.store.load(self.p['id'])
        p['dependencyScope'] = scope
        self.p = self.store.save(p)
        bundle = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node'
        module = bundle / 'node_modules/playwright'
        node = shutil.which('node') or str(bundle / 'bin/node.exe')
        if not module.exists():
            self.skipTest('Bundled JS Playwright unavailable')
        server = create_server(self.store.root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        script = r'''
const {chromium}=require(process.argv[1]),fs=require('fs'),assert=require('assert');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1400,height:1080}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/save'))writes.push(r.url());});
  await page.goto(process.argv[2]);await page.locator('[data-open="'+process.argv[3]+'"]').click();
  await page.locator('[data-page="checks"]').click();await page.locator('#atlas-optimize-preview').waitFor();
  const revision=await page.evaluate(()=>S.p.revision),initialWrites=writes.length;
  await page.locator('#atlas-optimize-preview').click();await page.locator('#atlas-optimization-enable').waitFor();
  const summary=await page.locator('#atlas-optimization-summary').innerText();
  assert(summary.includes('可整理 1 套'));assert(!summary.includes('减少 0 '));
  const report={optimizedBundles:1};
  assert.strictEqual(await page.locator('#atlas-options-json').count(),0);
  assert.strictEqual(await page.evaluate(()=>S.p.revision),revision);
  assert.strictEqual(writes.length,initialWrites);assert(!await page.evaluate(()=>S.p.atlasOptimization?.enabled));
  await page.locator('#atlas-optimization-enable').click();
  await page.waitForFunction(()=>S.p.atlasOptimization?.enabled&&!document.querySelector('#modal').open&&!S.dirty);
  await page.locator('#atlas-workflow-panel').waitFor();
  await page.locator('#undo').click();await page.evaluate(async()=>saveNow());
  assert(!await page.evaluate(()=>S.p.atlasOptimization?.enabled));
  await page.locator('#redo').click();await page.evaluate(async()=>saveNow());
  assert(await page.evaluate(()=>S.p.atlasOptimization.enabled));
  await page.reload();await page.locator('[data-open="'+process.argv[3]+'"]').click();
  await page.locator('[data-page="checks"]').click();await page.locator('#dependency-closure-open').waitFor();
  assert(await page.evaluate(()=>S.p.atlasOptimization.enabled));
  await page.locator('#dependency-closure-open').click();await page.locator('#dependency-closure-result').waitFor();
  const checked=await page.evaluate(async()=>api('/api/dependency-closure',{id:S.p.id}));
  assert.strictEqual(checked.dependencyClosure.closure.completeCharacterTotal,false);
  assert.strictEqual(checked.dependencyClosure.closure.characterSemanticClosure,false);
  assert((await page.locator('#modal-content').innerText()).includes('尚未全部核验'));
  assert.strictEqual(await page.locator('#dependency-scope-json').count(),0);
  const scope={kind:'character-semantic',closed:true,roles:['main'],forms:['base'],futureScope:{keep:true}};
  await page.locator('.modal-close').click();
  const download=page.waitForEvent('download');await page.locator('#export').click();await (await download).saveAs(process.argv[4]);
  await page.locator('#home').click();await page.locator('#import-project').click();await page.locator('#zip-input').setInputFiles(process.argv[4]);
  await page.waitForFunction(id=>S.p?.id&&S.p.id!==id,process.argv[3]);
  assert.deepStrictEqual(await page.evaluate(()=>S.p.dependencyScope),scope);assert(await page.evaluate(()=>S.p.atlasOptimization.enabled));
  await page.locator('[data-page="checks"]').click();await page.locator('#atlas-optimization-disable').waitFor();
  await page.locator('#atlas-optimization-disable').click();await page.waitForFunction(()=>S.p.atlasOptimization.enabled===false&&!S.dirty);
  const persisted=await page.evaluate(async()=>api('/api/project?id='+S.p.id));assert.strictEqual(persisted.atlasOptimization.enabled,false);
  assert.deepStrictEqual(errors,[]);
  console.log(JSON.stringify({previewReadOnly:true,optimizedBundles:report.optimizedBundles,enableUndoRedo:true,reload:true,scopeRoundtrip:true,noFalseClosure:true,disableSaved:true,pageErrors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
'''
        try:
            result = subprocess.run([node, '-e', script, str(module),
                f'http://127.0.0.1:{server.server_port}', self.p['id'], str(self.root / 'workflow.wfchar')],
                capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            evidence = os.environ.get('ATLAS_WORKFLOW_TEST_REPORT')
            if evidence:
                Path(evidence).write_text(result.stdout, encoding='utf-8')
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
