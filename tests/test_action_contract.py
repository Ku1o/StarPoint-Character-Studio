import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from action_presets import (ACTION_PRESETS, preset_animation, default_action_contract,
                            normalize_action_contract, action_contract_payload)
from character_contract import export_contract
from source_intake import register_source


class ActionContractTests(unittest.TestCase):
    def test_slot_does_not_invent_selector_or_declared_anchor(self):
        action = preset_animation(ACTION_PRESETS[0])
        before = copy.deepcopy(action)
        result = normalize_action_contract(action)
        self.assertEqual(result["selector"]["status"], "unknown")
        self.assertIsNone(result["selector"]["value"])
        self.assertIsNone(result["feetAnchor"])
        self.assertEqual(action, before)

    def test_declared_intent_anchors_and_unknown_extensions_survive_copy(self):
        action = {"id": "cast", "slot": "skill_ready", "clips": [], "actionContract": {
            **default_action_contract(), "purpose": "作者俯视施法姿态", "sourceCanvas": [32, 40],
            "bodyAnchor": [16, 20], "feetAnchor": [16, 40], "durationTicks": 12,
            "loop": False, "returnState": "normal", "future": {"author": True}}}
        before = copy.deepcopy(action)
        result = action_contract_payload({"animations": [action]})
        self.assertEqual(result[0]["contract"]["future"], {"author": True})
        result[0]["contract"]["future"]["author"] = False
        self.assertEqual(action, before)

    def test_native_verified_selector_requires_context_and_evidence(self):
        for patch in ({"selector": {"status": "verified", "value": 0}},
                      {"selector": {"status": "unknown", "value": 0}},
                      {"feetAnchor": [0, float("nan")]}, {"loop": "true"},
                      {"durationTicks": True}, {"sourceCanvas": [0, 40]}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                normalize_action_contract({"actionContract": patch})
        declared = normalize_action_contract({"actionContract": {"selector": {
            "status": "verified", "value": 0, "context": "acquisition only", "evidence": "trace.json"}}})
        self.assertEqual(declared["selector"]["value"], 0)

    def test_handoff_keeps_observed_mapping_and_unknown_native_boundary(self):
        p = {"id": "fixture", "name": "fixture", "assets": {"frame": {}}, "animations": [
            {"id": "normal", "slot": "neutral", "clips": [{"asset": "frame", "hold": 6,
             "sourceRef": {"source": "source_example", "cell": 27}}]}]}
        source = register_source(p, "author.png", b"original")
        p["animations"][0]["clips"][0]["sourceRef"]["source"] = source["id"]
        before = copy.deepcopy(p)
        result = export_contract(type("Store", (), {"directory": lambda _, pid: Path("unused")})(), p)
        self.assertEqual(result["actionContracts"][0]["frameMapping"][0]["sourceRef"]["cell"], 27)
        self.assertFalse(result["actionContracts"][0]["annotated"])
        self.assertFalse(result["integration"]["gameReady"])
        self.assertEqual(p, before)

    def test_browser_import_and_action_intent_cancel_save_reopen(self):
        """Use the bundled JS browser dependency; no Python Playwright install needed."""
        from PIL import Image, PngImagePlugin
        from studio import create_server
        bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        module = bundle / "node_modules/playwright"
        node = shutil.which("node") or str(bundle / "bin/node.exe")
        if not module.exists():
            self.skipTest("Bundled JS Playwright unavailable")
        with tempfile.TemporaryDirectory(prefix="action-contract-ui-") as directory:
            root = Path(directory)
            image = Image.new("RGBA", (16, 24), (17, 35, 50, 255))
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("author", "original source fixture")
            image.save(root / "author.png", pnginfo=metadata)
            server = create_server(root / "projects")
            threading.Thread(target=server.serve_forever, daemon=True).start()
            script = r'''
const { chromium } = require(process.argv[1]);
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));
  await page.goto(process.argv[2]);
  await page.waitForFunction(()=>S.token.length>0);
  await page.locator('#new-original').click();
  await page.locator('#dialog-name').fill('Action provenance fixture');
  await page.locator('#dialog-ok').click();
  await page.locator('#identity-name').waitFor();
  await page.locator('[data-page="animations"]').click();
  await page.locator('#pixel-action-contract').click();
  await page.locator('#contract-purpose').fill('cancelled intent');
  await page.locator('#contract-cancel').click();
  if(await page.evaluate(()=>!!current().actionContract))throw Error('Cancel mutated action');
  await page.locator('#pixel-batch-import').click();
  await page.locator('#pixel-files-input').setInputFiles(process.argv[3]);
  await page.locator('[data-pixel-file]').waitFor();
  await page.locator('#pixel-import-confirm').click();
  await page.waitForFunction(()=>!document.querySelector('#modal').open&&current().clips.length===1);
  await page.locator('#pixel-action-contract').click();
  await page.locator('summary').filter({hasText:'段画稿来源'}).click();
  if(!(await page.locator('#modal-content').innerText()).includes('author.png'))throw Error('Source path absent');
  await page.locator('#contract-purpose').fill('author top-down walk pose');
  const anchors=await page.evaluate(()=>({canvas:current().actionContract?.sourceCanvas,feet:current().actionContract?.feetAnchor}));
  await page.locator('#contract-duration').fill('0.2');
  await page.locator('#contract-loop').selectOption('false');
  await page.locator('#contract-return').fill('normal');
  await page.locator('#contract-save').click();
  await page.locator('#save').click();
  await page.waitForFunction(()=>!S.dirty&&!S.savePromise);
  const value=await page.evaluate(()=>({pid:S.p.id,aid:current().id,intake:S.p.sourceIntake,contract:current().actionContract}));
  await page.evaluate(async value=>setProject(await api('/api/project?id='+value.pid)),value);
  await page.locator('[data-page="animations"]').click();
  await page.locator('[data-animation="'+value.aid+'"]').click();
  await page.locator('#pixel-action-contract').click();
  if(await page.locator('#contract-purpose').inputValue()!=='author top-down walk pose')throw Error('Save/reopen lost intent');
  if(await page.evaluate(()=>current().actionContract.selector.status)!=='unknown')throw Error('Selector inferred from slot');
  const savedAnchors=await page.evaluate(()=>({canvas:current().actionContract.sourceCanvas??undefined,feet:current().actionContract.feetAnchor??undefined}));
  if(JSON.stringify(savedAnchors)!==JSON.stringify(anchors))throw Error('Anchor changed');
  if(await page.evaluate(()=>current().actionContract.durationTicks)!==12)throw Error('Seconds lost exact ticks');
  await page.setViewportSize({width:720,height:1000});
  if(await page.evaluate(()=>document.querySelector('#modal').scrollWidth>document.querySelector('#modal').clientWidth+2))throw Error('Contract dialog overflow');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({cancelUnchanged:true,rawSourceRetained:value.intake.sources.length===1,intentRoundtrip:true,selectorUnknown:true,narrowNoOverflow:true,errors}));
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
'''
            try:
                result = subprocess.run([node, "-e", script, str(module),
                                         f"http://127.0.0.1:{server.server_port}", str(root / "author.png")],
                                        capture_output=True, text=True, timeout=90)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                evidence = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertTrue(all(evidence[key] for key in evidence if key != "errors"), evidence)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
