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

from production_brief import (AUTHOR_POLICY_STATES, author_guidance, author_readme,
                              author_submission_form, checks, default_production_brief,
                              export_handoff, normalize_production_brief)
from studio_core import ProjectStore, fresh_project, project_checks


class AuthorGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.project = {"productionBrief": default_production_brief(), "assets": {}}

    def row(self, kind, key):
        return next(row for row in self.project["productionBrief"][kind] if row["id"] == key)

    def guidance_row(self, kind, key):
        return next(row for row in author_guidance(self.project)["rows"] if row["kind"] == kind and row["id"] == key)

    def test_one_master_reuse_and_no_voice_resolve_author_intent_not_integration(self):
        brief = self.project["productionBrief"]
        self.project["assets"]["master"] = {"mime": "image/png"}
        for row in brief["resources"]:
            row["authorPolicy"].update(state="maker_derive", reference="master", reason="可从原稿派生，先给预览")
        self.row("resources", "portrait_base").update(status="provided", assetIds=["master"])
        self.row("resources", "portrait_evolved")["authorPolicy"].update(state="explicit_reuse", reference="portrait_base")
        for row in brief["resources"]:
            if row["group"] in ("skill", "pf", "atlas"):
                row["authorPolicy"].update(state="explicit_reuse", reference="官方角色明确技能来源")
        brief["authorPolicy"].update(voiceMode="none", voiceReason="角色本轮无配音")
        for row in brief["sounds"]:
            row["authorPolicy"].update(state="explicit_reuse", reference="官方技能音效")
        guidance = author_guidance(self.project)
        self.assertEqual(guidance["authorPending"], [])
        self.assertTrue(guidance["makerPending"])
        self.assertFalse(guidance["gameReady"])
        self.assertFalse(any(row["integrationVerified"] for row in guidance["rows"]))
        self.assertFalse(any(issue.get("owner") == "author" for issue in checks(self.project) if issue.get("id")))
        self.assertFalse(any("语音未成对" in issue["text"] for issue in checks(self.project)))

    def test_invalid_provided_asset_cannot_be_hidden_by_a_policy(self):
        row = self.row("resources", "portrait_base")
        row.update(status="provided", assetIds=["deleted"])
        for state in ("unmarked", "explicit_reuse", "maker_derive", "not_applicable", "maker_review"):
            with self.subTest(state=state):
                row["authorPolicy"].update(state=state, reference="mother.png", reason="范围明确")
                actual = self.guidance_row("resources", "portrait_base")
                self.assertFalse(actual["authorComplete"])
                self.assertIn("asset_missing", [issue["code"] for issue in actual["issues"]])

    def test_explicit_official_reuse_does_not_require_author_to_import_game_files(self):
        for kind, key in (("resources", "skill_projectile"), ("voices", "home_base")):
            row = self.row(kind, key)
            row["status"] = "reuse_official"
            row["authorPolicy"].update(state="explicit_reuse", reference="官方角色及指定入口")
            actual = self.guidance_row(kind, key)
            self.assertTrue(actual["authorComplete"])
            self.assertTrue(actual["makerPending"])
            self.assertFalse(actual["integrationVerified"])
            self.assertTrue(any(issue["code"] == "asset_unlinked" for issue in actual["issues"]))
            self.assertFalse(any(issue["owner"] == "author" for issue in actual["issues"]))

    def test_provided_voice_requires_actual_audio_entry_and_complete_text_even_without_voicing(self):
        row = self.row("voices", "acquisition")
        row.update(status="provided", assetId="voice")
        self.project["assets"]["voice"] = {"mime": "audio/wav"}
        self.project["productionBrief"]["authorPolicy"].update(voiceMode="none", voiceReason="无配音")
        actual = self.guidance_row("voices", "acquisition")
        self.assertFalse(actual["authorComplete"])
        self.assertEqual({i["code"] for i in actual["issues"] if i["owner"] == "author"}, {"voice_entry_missing", "voice_textJapanese_missing"})
        row.update(entry="character/acquisition", textJapanese="保留完整句尾。")
        self.assertTrue(self.guidance_row("voices", "acquisition")["authorComplete"])
        self.project["assets"]["voice"]["mime"] = "image/png"
        self.assertFalse(self.guidance_row("voices", "acquisition")["authorComplete"])

    def test_declarations_need_reference_or_reason_and_no_voice_does_not_cover_sound(self):
        row = self.row("resources", "detail_base")
        for state in ("explicit_reuse", "maker_derive", "not_applicable", "maker_review"):
            row["authorPolicy"].update(state=state, reference="", reason="")
            self.assertFalse(self.guidance_row("resources", "detail_base")["authorComplete"])
        self.project["productionBrief"]["authorPolicy"].update(voiceMode="none", voiceReason="本轮不配音")
        self.assertTrue(self.guidance_row("voices", "home_base")["authorComplete"])
        self.assertFalse(self.guidance_row("sounds", "skill_sfx")["authorComplete"])
        row["authorPolicy"].update(state="not_applicable", reason="没有这个用途")
        self.assertTrue(self.guidance_row("resources", "detail_base")["authorComplete"])

    def test_legacy_defaults_are_unmarked_and_unknown_policy_fields_survive(self):
        brief = self.project["productionBrief"]
        brief.pop("authorPolicy")
        for kind in ("resources", "voices", "sounds"):
            for row in brief[kind]:
                row.pop("authorPolicy")
        before = copy.deepcopy(self.project)
        normalized = normalize_production_brief(self.project)
        self.assertEqual(self.project, before)
        self.assertEqual(normalized["authorPolicy"]["voiceMode"], "unmarked")
        self.assertTrue(all(row["state"] == "unmarked" and not row["integrationVerified"] for row in author_guidance(self.project)["rows"]))
        self.assertTrue(author_guidance(self.project)["authorPending"])
        normalized["resources"][0]["authorPolicy"]["future"] = {"keep": 3}
        self.assertEqual(normalize_production_brief(normalized)["resources"][0]["authorPolicy"]["future"], {"keep": 3})

    def test_generated_docs_and_handoff_share_the_schema_and_issues(self):
        row = self.row("resources", "detail_base")
        row["authorPolicy"].update(state="maker_derive", reference="原稿|母版.png", reason="保留原稿\n先看预览")
        handoff = export_handoff(self.project)
        self.assertEqual(handoff["authorGuidance"], author_guidance(self.project))
        self.assertEqual(handoff["authorGuide"], author_readme(self.project))
        self.assertEqual(handoff["authorSubmissionForm"], author_submission_form(self.project))
        for kind in ("resources", "voices", "sounds"):
            for item in self.project["productionBrief"][kind]:
                self.assertIn(f"`{kind}.{item['id']}`", handoff["authorSubmissionForm"])
        for row in handoff["authorGuidance"]["rows"]:
            for issue in row["issues"]:
                self.assertIn(issue["path"], handoff["authorGuide"])
                self.assertIn(issue["text"], handoff["authorGuide"])
        root = Path(__file__).resolve().parents[1] / "docs/author-experience"
        self.assertEqual((root / "01-稿主资源提供指南.md").read_text(encoding="utf-8"), author_readme())
        self.assertEqual((root / "starter-pack/00-需求单.md").read_text(encoding="utf-8"), author_submission_form())
        self.assertTrue((root / "starter-pack/README.md").is_file())
        self.assertNotIn("04-稿主素材包最小模板", (root / "starter-pack/README.md").read_text(encoding="utf-8"))
        self.assertIn("原稿\\|母版.png", handoff["authorSubmissionForm"])

    def test_author_policy_export_import_roundtrip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ProjectStore(Path(directory) / "a")
            project = store.create("责任声明回读")
            project["productionBrief"]["authorPolicy"].update(voiceMode="none", voiceReason="没有配音")
            project["productionBrief"]["resources"][0]["authorPolicy"].update(state="explicit_reuse", reference="官方角色母版")
            store.save(project)
            imported = ProjectStore(Path(directory) / "b").import_archive(store.export(project["id"]))
            self.assertEqual(imported["productionBrief"], project["productionBrief"])
            self.assertEqual(author_guidance(imported), author_guidance(project))

    def test_core_uses_required_intent_declarations_without_requiring_optional_rows(self):
        project = fresh_project("只声明复用与派生")
        for kind in ("resources", "voices", "sounds"):
            for row in project["productionBrief"][kind]:
                if row["required"]:
                    row["authorPolicy"].update(state="explicit_reuse", reference="明确指定的官方资源")
        self.assertEqual(author_guidance(project)["authorPending"], [])
        author_gaps = [issue for issue in project_checks(project)["issues"]
                       if issue["level"] == "todo" and issue["page"] in ("portraits", "animations", "effects", "voices")]
        self.assertEqual(author_gaps, [])

    def test_ui_row_states_match_python_for_failure_and_policy_cases(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node runtime unavailable; UI state parity requires Node")
        cases = []
        for kind in ("resources", "voices", "sounds"):
            for state, _ in AUTHOR_POLICY_STATES:
                for status in ("missing", "provided", "reuse_official", "not_applicable", "needs_review"):
                    for valid in (False, True):
                        row = copy.deepcopy(self.project["productionBrief"][kind][0])
                        row.update(status=status)
                        row["authorPolicy"].update(state=state, reason="明确原因", reference="母版")
                        if kind == "resources":
                            row["assetIds"] = ["asset"]
                        else:
                            row.update(assetId="asset", entry="真实入口" if valid else "", textJapanese="完整台词" if valid else "")
                        project = {"productionBrief": default_production_brief(), "assets": {"asset": {"mime": "image/png" if kind == "resources" else "audio/wav"}} if valid else {}}
                        project["productionBrief"][kind][0] = row
                        project["productionBrief"]["authorPolicy"].update(voiceMode="none", voiceReason="明确无配音")
                        expected = author_guidance(project)["rows"]
                        expected = next(r for r in expected if r["kind"] == kind and r["id"] == row["id"])
                        cases.append({"project": project, "item": row, "kind": kind, "expected": {key: expected[key] for key in ("authorComplete", "makerPending", "integrationVerified")}})
        script = """const fs=require('fs'),vm=require('vm');const context={S:{p:{}}};vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);const data=JSON.parse(fs.readFileSync(0,'utf8'));let failures=[];for(const [i,test] of data.entries()){context.S.p=test.project;const actual=vm.runInContext('pbRowGuidance('+JSON.stringify(test.item)+','+JSON.stringify(test.kind)+')',context);if(JSON.stringify(actual)!==JSON.stringify(test.expected))failures.push({i,actual,expected:test.expected});}const states=vm.runInContext('PB_AUTHOR_POLICY',context);console.log(JSON.stringify({failures,states,count:data.length}));"""
        result = subprocess.run([node, "-e", script, str(Path(__file__).resolve().parents[1] / "web/production-brief.js")], input=json.dumps(cases, ensure_ascii=False), text=True, capture_output=True, check=True, encoding="utf-8")
        result = json.loads(result.stdout)
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["states"], [list(item) for item in AUTHOR_POLICY_STATES])
        self.assertEqual(result["count"], 3 * len(AUTHOR_POLICY_STATES) * 5 * 2)

    def test_browser_author_policy_save_export_import_and_read_only_open(self):
        """Exercise visible author fields and real archive roundtrip in isolation."""
        from PIL import Image
        import wave
        from studio import create_server
        bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        module = bundle / "node_modules/playwright"
        node = shutil.which("node") or str(bundle / "bin/node.exe")
        if not module.exists():
            self.skipTest("Bundled JS Playwright unavailable")
        with tempfile.TemporaryDirectory(prefix="author-guidance-ui-") as directory:
            root = Path(directory)
            Image.new("RGBA", (32, 40), (32, 70, 110, 180)).save(root / "mother.png")
            with wave.open(str(root / "original-voice.wav"), "wb") as sound:
                sound.setnchannels(1)
                sound.setsampwidth(2)
                sound.setframerate(44100)
                sound.writeframes(b"\0\0" * 4410)
            server = create_server(root / "projects")
            threading.Thread(target=server.serve_forever, daemon=True).start()
            legacy = server.store.create("只读旧工程")
            legacy.pop("productionBrief")
            server.store._write(legacy)
            legacy_path = server.store.directory(legacy["id"]) / "project.json"
            legacy_before = legacy_path.read_bytes()
            script = r'''
const {chromium}=require(process.argv[1]);
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1400,height:1000}}),errors=[],writes=[];
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('request',r=>{if(r.method()==='POST'&&!r.url().endsWith('/api/desktop-ready'))writes.push(r.url());});
  await page.goto(process.argv[2]);await page.waitForFunction(()=>S.token.length>0);
  await page.locator('[data-open="'+process.argv[5]+'"]').click();
  await page.locator('[data-page="production"]').click();
  await page.waitForFunction(()=>document.querySelector('#production-run-check')!==null);
  if(writes.length)throw Error('Read-only legacy open sent POST: '+JSON.stringify(writes));
  const readonly={noPost:true,policy:await page.evaluate(()=>S.p.productionBrief.authorPolicy.voiceMode)};
  await page.locator('#home').click();
  await page.locator('#new-original').click();await page.locator('#dialog-name').fill('Author minimal master fixture');await page.locator('#dialog-ok').click();
  await page.locator('#identity-name').waitFor();
  await page.locator('[data-page="portraits"]').click();await page.locator('#portrait-upload').click();await page.locator('#media-input').setInputFiles(process.argv[3]);
  await page.waitForFunction(()=>Object.keys(S.p.assets).length===1&&!!S.p.portraits.base);
  const mother=await page.evaluate(()=>S.p.portraits.base);
  await page.locator('[data-page="production"]').click();
  async function input(path,value){
   const field=page.locator('[data-pb-path="'+path+'"]');
   await field.evaluate(node=>{for(let p=node.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});
   if(await field.evaluate(node=>node.tagName)==='SELECT')await field.selectOption(value);
   else {await field.fill(value);await field.blur();}
  }
  for(const [key,value] of Object.entries({characterName:'原稿角色',title:'资料头衔',role:'辅助',race:'人',baseForm:'母版基础',evolvedForm:'明确沿用基础'}))await input('author.'+key,value);
  for(const key of ['activeSkill','pf','leader']){await input('plans.'+key+'.name','明确玩法');await input('plans.'+key+'.authorDescription','对全队提升攻击，数值待协商');}
  const resources=await page.evaluate(()=>S.p.productionBrief.resources.map((r,i)=>({id:r.id,group:r.group,i})));
  for(const row of resources){const prefix='resources.'+row.i;
   if(row.id==='portrait_base'){
    const button=page.locator('[data-pb-pick="'+prefix+'"]');
    await button.evaluate(node=>{for(let p=node.parentElement;p;p=p.parentElement)if(p.tagName==='DETAILS')p.open=true;});
    await button.click();await page.locator('#pb-asset-options input[value="'+mother+'"]').check();await page.locator('#pb-asset-confirm').click();
   }
   else {const reuse=['skill','pf','atlas'].includes(row.group)||row.id==='portrait_evolved';if(reuse)await input(prefix+'.status','reuse_official');await input(prefix+'.authorPolicy.state',reuse?'explicit_reuse':'maker_derive');await input(prefix+'.authorPolicy.reference',row.id==='portrait_evolved'?'portrait_base':['skill','pf','atlas'].includes(row.group)?'官方角色指定技能':mother);}
  }
  await input('authorPolicy.voiceMode','none');await input('authorPolicy.voiceReason','本轮无配音');
  const sounds=await page.evaluate(()=>S.p.productionBrief.sounds.map((r,i)=>i));
  for(const i of sounds){await input('sounds.'+i+'.authorPolicy.state','explicit_reuse');await input('sounds.'+i+'.authorPolicy.reference','官方技能原声音效');}
  await page.locator('#save').click();await page.waitForFunction(()=>!S.dirty&&!S.savePromise);
  const original=await page.evaluate(()=>({id:S.p.id,brief:S.p.productionBrief,progress:pbProgress(S.p.productionBrief)}));
  if(original.progress.resources[0]!==original.progress.resources[1]||original.progress.voices[0]!==original.progress.voices[1])throw Error('Minimal intent creates author gaps');
  const handoff=await page.evaluate(async()=>api('/api/production-handoff?id='+S.p.id));
  if(handoff.authorGuidance.authorPending.length||handoff.gameReady!==false)throw Error('Handoff has false gaps/readiness');
  const source=await page.evaluate(async()=>api('/api/project?id='+S.p.id));
  await page.locator('[data-page="voices"]').click();
  if(!(await page.locator('.audio-requirements').innerText()).includes('作者已说明 · 接入待核'))throw Error('Audio page ignores no-voice declaration');
  const check=await page.evaluate(async()=>api('/api/check',{id:S.p.id}));
  const authorFalseGaps=check.issues.filter(i=>i.level==='todo'&&['portraits','animations','effects','voices'].includes(i.page));
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;await download.saveAs(process.argv[4]);
  await page.locator('#home').click();await page.locator('#import-project').click();await page.locator('#zip-input').setInputFiles(process.argv[4]);
  await page.waitForFunction(id=>S.p?.id&&S.p.id!==id,original.id);await page.locator('[data-page="production"]').click();
  const restored=await page.evaluate(()=>S.p.productionBrief);
  if(JSON.stringify(restored)!==JSON.stringify(original.brief))throw Error('Archive roundtrip changed author state');
  const restoredHandoff=await page.evaluate(async()=>api('/api/production-handoff?id='+S.p.id));
  if(JSON.stringify(restoredHandoff.authorGuidance)!==JSON.stringify(handoff.authorGuidance))throw Error('Roundtrip guidance changed');
  // An invalid provided file stays incomplete even behind a reuse declaration.
  const badIndex=resources.find(r=>r.id==='detail_base').i;
  await input('resources.'+badIndex+'.status','provided');
  // Corrupt the imported fixture in memory, not through an author ID input.
  await page.evaluate(i=>mutate(()=>{S.p.productionBrief.resources[i].assetIds=['removed'];}),badIndex);
  if(await page.evaluate(i=>pbRowGuidance(S.p.productionBrief.resources[i],'resources').authorComplete,badIndex))throw Error('Broken provided asset green');
  await page.locator('#undo').click();await page.locator('#undo').click();
  await page.locator('#save').click();await page.waitForFunction(()=>!S.dirty&&!S.savePromise);
  await page.locator('[data-page="voices"]').click();
  await page.locator('[data-audio-requirement="acquisition"]').click();await page.locator('#media-input').setInputFiles(process.argv[6]);
  await page.waitForFunction(()=>S.p.productionBrief.voices.find(r=>r.id==='acquisition').status==='provided');
  let blockedVoice=await page.evaluate(()=>pbRowGuidance(S.p.productionBrief.voices.find(r=>r.id==='acquisition'),'voices'));
  if(blockedVoice.authorComplete)throw Error('Provided voice without entry/text is green under overall no-voice policy');
  const voiceId=await page.evaluate(()=>S.p.voices.find(v=>v.productionId==='acquisition').id);
  const audioRow=page.locator('[data-audio-name="'+voiceId+'"]').locator('..').locator('..');
  if(!(await page.locator('[data-audio-requirement="acquisition"]').locator('..').innerText()).includes('作者待补'))throw Error('Audio requirement UI hides incomplete provided voice');
  await page.locator('[data-voice-entry="'+voiceId+'"]').selectOption('ally');
  await page.locator('[data-audio-text="'+voiceId+'"]').fill('完整获取台词，保留句尾。');await page.locator('[data-audio-text="'+voiceId+'"]').blur();
  await page.locator('#save').click();await page.waitForFunction(()=>!S.dirty&&!S.savePromise);
  const voiceSynced=await page.evaluate(id=>{const b=S.p.productionBrief.voices.find(r=>r.id==='acquisition'),d=S.p.voiceDeclarations.find(r=>r.voiceId===id);return b.entry==='ally'&&b.textJapanese==='完整获取台词，保留句尾。'&&d.entry==='ally'&&d.text===b.textJapanese;},voiceId);
  if(!voiceSynced)throw Error('Voice UI entry/text did not synchronize declaration and author brief');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({readonly,authorProgress:original.progress,authorPending:handoff.authorGuidance.authorPending,roundtrip:true,brokenProvidedBlocked:true,providedVoiceBlocked:true,voiceSynced,authorFalseGaps,errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
'''
            try:
                result = subprocess.run([node, "-e", script, str(module),
                    f"http://127.0.0.1:{server.server_port}", str(root / "mother.png"),
                    str(root / "author.wfchar.zip"), legacy["id"], str(root / "original-voice.wav")], capture_output=True,
                    text=True, encoding="utf-8", timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                evidence = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(evidence["readonly"], {"noPost": True, "policy": "unmarked"})
                self.assertEqual(legacy_path.read_bytes(), legacy_before)
                self.assertEqual(evidence["authorFalseGaps"], [], evidence["authorFalseGaps"])
                self.assertEqual(evidence["authorPending"], [])
                self.assertTrue(evidence["roundtrip"])
                self.assertTrue(evidence["brokenProvidedBlocked"])
                self.assertTrue(evidence["providedVoiceBlocked"])
                self.assertTrue(evidence["voiceSynced"])
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
