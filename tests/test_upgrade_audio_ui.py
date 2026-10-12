"""Isolated browser acceptance for original audio and NewEntry candidates."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import create_server


class UpgradeAudioUiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "audio measurement tools unavailable")
    def test_original_candidate_explicit_apply_and_entry_layout_roundtrip(self):
        bundle = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node"
        module = bundle / "node_modules/playwright"
        node = shutil.which("node") or str(bundle / "bin/node.exe")
        if not module.exists():
            self.skipTest("Bundled JS Playwright unavailable")
        fixture_root = os.environ.get("WORKSHOP_ENTRY_FIXTURE_DIR")
        input_fixtures = {}
        texts = {"original": "这是完整的原文……\n最后一句必须保留。",
                 "shortened": "这是原文……最后一句必须保留。", "source": "self-contained text fixture"}
        if fixture_root:
            fixture_root = Path(fixture_root)
            v2_path, v3_path = fixture_root / "v2/candidate-report.json", fixture_root / "v3/candidate-report.json"
            for path in (v2_path, v3_path):
                input_fixtures[path] = path.read_bytes()
            v2, v3 = (json.loads(input_fixtures[path]) for path in (v2_path, v3_path))
            texts = {"original": v2["original_complete_text_with_forced_breaks"],
                     "shortened": v3["candidate_text"], "source": "retained text reports"}
            self.assertEqual([len(texts["original"]), len(texts["original"].replace("\n", "")), len(texts["shortened"])], [85, 83, 78])
        with tempfile.TemporaryDirectory(prefix="upgrade-audio-ui-") as temporary:
            root = Path(temporary)
            original_path = root / "author-original-stereo.wav"
            with wave.open(str(original_path), "wb") as writer:
                writer.setnchannels(2)
                writer.setsampwidth(2)
                writer.setframerate(44100)
                writer.writeframes(b"".join(struct.pack("<hh",
                    int(6000 * math.sin(2 * math.pi * 440 * i / 44100)),
                    int(3500 * math.sin(2 * math.pi * 440 * i / 44100))) for i in range(132300)))
            original_bytes = original_path.read_bytes()
            (root / "texts.json").write_text(json.dumps(texts, ensure_ascii=False), encoding="utf-8")
            server = create_server(root / "projects")
            threading.Thread(target=server.serve_forever, daemon=True).start()
            script = r'''
const {chromium}=require(process.argv[1]),fs=require('fs');
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1400,height:1100}}),errors=[],warnings=[],responses=[];
  const texts=JSON.parse(fs.readFileSync(process.argv[4],'utf8'));
  page.on('pageerror',e=>errors.push(String(e)));
  page.on('console',message=>{if(['warning','error'].includes(message.type()))warnings.push({type:message.type(),text:message.text()});});
  page.on('response',r=>{if(r.status()>=400)responses.push({status:r.status(),url:r.url()});});
  await page.goto(process.argv[2]);await page.waitForFunction(()=>S.token.length>0);
  await page.locator('#new-original').click();await page.locator('#dialog-name').fill('Audio and acquisition UI fixture');await page.locator('#dialog-ok').click();await page.locator('#identity-name').waitFor();
  await page.locator('[data-page="voices"]').click();await page.locator('[data-audio-requirement="acquisition"]').click();await page.locator('#media-input').setInputFiles(process.argv[3]);
  await page.waitForFunction(()=>S.p.voices.some(v=>v.productionId==='acquisition'));
  const initial=await page.evaluate(()=>{const voice=S.p.voices.find(v=>v.productionId==='acquisition');return {id:voice.id,asset:voice.asset,pid:S.p.id,originalSha:S.p.assets[voice.asset].sha256};});
  await page.locator('[data-voice-entry="'+initial.id+'"]').selectOption('ally');
  await page.locator('[data-audio-text="'+initial.id+'"]').fill(texts.original);await page.locator('[data-audio-text="'+initial.id+'"]').blur();
  if(!(await page.locator('[data-audio-requirement="acquisition"]').locator('..').innerText()).includes('作者已说明 · 接入待核'))throw Error('Author intent panel did not redraw after entry/text');
  await page.locator('[data-audio-usage="'+initial.id+'"]').selectOption('battle_start');
  if(!await page.evaluate(id=>S.p.voiceDeclarations.find(v=>v.voiceId===id)?.usage==='battle_start',initial.id))throw Error('Editing voice usage did not synchronize declaration');
  await page.locator('[data-audio-usage="'+initial.id+'"]').selectOption('join');
  if(!await page.evaluate(id=>S.p.voiceDeclarations.find(v=>v.voiceId===id)?.usage==='join',initial.id))throw Error('Restoring acquisition usage did not synchronize declaration');
  await page.locator('#audio-filter').selectOption('join');
  if(await page.locator('[data-voice-entry="'+initial.id+'"]').count()!==1)throw Error('Filtered audio row lost upgrade fields');
  await page.locator('[data-audio-profile="targetLufs"]').fill('-23');
  await page.locator('[data-audio-profile="truePeakCeilingDbtp"]').fill('-2');
  await page.locator('#audio-profile-references').selectOption([initial.asset]);
  await page.locator('#audio-profile-save').click();
  await page.waitForFunction(()=>S.p.audioProfile?.voice?.targetLufs===-23&&document.querySelector('#busy').hidden);
  await page.locator('[data-audio-candidate="'+initial.id+'"]').click();await page.locator('#candidate-apply').waitFor();
  const candidate=await page.evaluate(()=>S.p.audioCandidates.at(-1));
  if(!candidate.originalPreserved||!candidate.candidateNotApplied||candidate.nativeVerified)throw Error('Candidate creation lacks preservation/boundary flags');
  if(candidate.originalAsset!==initial.asset||candidate.candidateAsset===initial.asset)throw Error('Candidate overwrote original');
  if(await page.evaluate(id=>S.p.voices.find(v=>v.id===id).asset,initial.id)!==initial.asset)throw Error('Candidate applied before explicit action');
  if(!candidate.postEncodeDecode.fullDecode||candidate.postEncodeDecode.measurementChannels!==1)throw Error('Encoded candidate was not fully decoded in mono');
  await page.locator('#candidate-apply').click();
  await page.waitForFunction(({id,cid})=>S.p.voices.find(v=>v.id===id).asset===cid&&!document.querySelector('#modal').open,{id:initial.id,cid:candidate.candidateAsset});
  const applied=await page.evaluate(id=>{const v=S.p.voices.find(v=>v.id===id),b=S.p.productionBrief.voices.find(v=>v.id==='acquisition'),d=S.p.voiceDeclarations.find(v=>v.voiceId===id);return {candidateOf:v.candidateOf,briefAsset:b.assetId,declarationAsset:d.asset};},initial.id);
  if(applied.candidateOf!==initial.asset||applied.briefAsset!==candidate.candidateAsset||applied.declarationAsset!==candidate.candidateAsset)throw Error('Explicit candidate application lost relations');
  await page.locator('[data-entry-layout="'+initial.id+'"]').click();await page.locator('#entry-original').waitFor();
  await page.waitForFunction(()=>document.querySelector('#entry-preview-result')?.textContent.includes('原文'));
  if(await page.locator('#entry-original').inputValue()!==texts.original)throw Error('Preview changed original');
  if(!(await page.locator('#modal').innerText()).includes('近似'))throw Error('Preview claims native geometry');
  await page.locator('#entry-remove-breaks').click();
  await page.waitForFunction(()=>document.querySelector('#busy').hidden);
  if(await page.locator('#entry-candidate').inputValue()!==texts.original.replace(/[\r\n]/g,''))throw Error('Remove line breaks changed words');
  if(await page.locator('#entry-original').inputValue()!==texts.original)throw Error('Removing breaks changed original');
  const removedBreaks=await page.evaluate(async texts=>api('/api/entry-layout',{original:texts.original,candidate:document.querySelector('#entry-candidate').value}),texts);
  if(removedBreaks.wordingChanged||!removedBreaks.approximate||removedBreaks.nativeVerified)throw Error('Newline-only candidate misreported scope');
  await page.locator('#entry-layout-save').click();
  const firstLayout=await page.evaluate(id=>S.p.voices.find(v=>v.id===id),initial.id);
  if(firstLayout.text!==texts.original||firstLayout.entryLayout.original!==texts.original||firstLayout.entryLayout.authorConfirmed)throw Error('Saving candidate overwrote text or implied approval');
  await page.locator('[data-entry-layout="'+initial.id+'"]').click();
  const deletedWord=texts.original.replace(/[\r\n]/g,'').slice(1);
  await page.locator('#entry-candidate').fill(deletedWord);await page.locator('#entry-preview').click();
  await page.waitForFunction(()=>document.querySelector('#entry-preview-result')?.textContent.includes('字词变化需稿主确认'));
  const deletionDiff=await page.evaluate(async texts=>api('/api/entry-layout',{original:texts.original,candidate:document.querySelector('#entry-candidate').value}),texts);
  if(!deletionDiff.wordingChanged||!deletionDiff.changes.some(change=>change.operation==='delete'))throw Error('Deleted word has no visible deletion diff');
  if(await page.locator('#entry-author-confirmed').isChecked())throw Error('Deletion was automatically confirmed');
  await page.locator('#entry-layout-save').click();
  const unconfirmed=await page.evaluate(id=>S.p.voices.find(v=>v.id===id),initial.id);
  if(unconfirmed.text!==texts.original||unconfirmed.entryLayout.authorConfirmed)throw Error('Unconfirmed deletion changed source or approval');
  await page.locator('[data-entry-layout="'+initial.id+'"]').click();await page.locator('#entry-candidate').fill(texts.shortened);await page.locator('#entry-preview').click();
  await page.waitForFunction(()=>document.querySelector('#entry-preview-result')?.textContent.includes('字词变化需稿主确认'));
  const shortened=await page.evaluate(async texts=>api('/api/entry-layout',{original:texts.original,candidate:document.querySelector('#entry-candidate').value}),texts);
  if(!shortened.wordingChanged||!shortened.changes.length)throw Error('Word changes have no explicit diff');
  if(await page.locator('#entry-author-confirmed').isChecked())throw Error('Word changes implicitly confirmed');
  await page.locator('#entry-author-confirmed').check();
  await page.locator('#entry-candidate').fill(texts.shortened+' ');
  if(await page.locator('#entry-author-confirmed').isChecked())throw Error('Editing a checked candidate retained prior approval');
  await page.locator('#entry-candidate').fill(texts.shortened);
  await page.locator('#entry-author-confirmed').check();await page.locator('#entry-layout-save').click();
  await page.locator('[data-entry-layout="'+initial.id+'"]').click();
  if(!await page.locator('#entry-author-confirmed').isChecked())throw Error('Saved approval did not reopen as recorded');
  await page.locator('#entry-candidate').fill(texts.shortened.slice(1));
  if(await page.locator('#entry-author-confirmed').isChecked())throw Error('Reopened confirmed candidate retained approval after deletion');
  await page.locator('#entry-layout-save').click();
  const revised=await page.evaluate(id=>S.p.voices.find(v=>v.id===id),initial.id);
  if(revised.entryLayout.authorConfirmed||revised.text!==texts.original||revised.entryLayout.original!==texts.original)throw Error('Saving edited candidate inherited approval or changed original');
  await page.locator('[data-entry-layout="'+initial.id+'"]').click();
  await page.locator('#entry-candidate').fill(texts.shortened+'\n');await page.locator('#entry-author-confirmed').check();
  await page.locator('#entry-remove-breaks').click();
  if(await page.locator('#entry-author-confirmed').isChecked())throw Error('Removing breaks retained approval of previous candidate');
  await page.waitForFunction(()=>document.querySelector('#busy').hidden);
  await page.locator('#entry-author-confirmed').check();await page.locator('#entry-layout-save').click();
  await page.locator('#save').click();await page.waitForFunction(()=>!S.dirty&&!S.savePromise);
  const final=await page.evaluate(id=>({voice:S.p.voices.find(v=>v.id===id),profile:S.p.audioProfile,candidates:S.p.audioCandidates,intake:S.p.sourceIntake}),initial.id);
  if(final.voice.text!==texts.original||final.voice.entryLayout.original!==texts.original||final.voice.entryLayout.candidate!==texts.shortened||!final.voice.entryLayout.authorConfirmed)throw Error('Confirmed layout candidate changed source text');
  const handoff=await page.evaluate(async()=>api('/api/production-handoff?id='+S.p.id));
  const reviewed=handoff.audioReview.rows.find(row=>row.id===initial.id),entry=handoff.entryLayout.entries.find(row=>row.id===initial.id);
  if(!reviewed.packagingRoundtrip||!reviewed.postEncodeDecode.fullDecode||reviewed.runtimeAccepted||reviewed.pathStatus!=='needs_native_registration')throw Error('Audio handoff has invalid acceptance boundary');
  if(!entry.wordingChanged||!entry.authorConfirmed||entry.nativeVerified||handoff.gameReady)throw Error('Layout handoff has invalid acceptance boundary');
  const downloadPromise=page.waitForEvent('download');await page.locator('#export').click();const download=await downloadPromise;await download.saveAs(process.argv[5]);
  await page.locator('#home').click();await page.locator('#import-project').click();await page.locator('#zip-input').setInputFiles(process.argv[5]);await page.waitForFunction(id=>S.p?.id&&S.p.id!==id,initial.pid);
  await page.locator('[data-page="voices"]').click();
  const restored=await page.evaluate(id=>({id:S.p.id,voice:S.p.voices.find(v=>v.id===id),profile:S.p.audioProfile,candidates:S.p.audioCandidates,intake:S.p.sourceIntake,originalSha:S.p.assets[S.p.voices.find(v=>v.id===id).candidateOf].sha256}),initial.id);
  for(const key of ['voice','profile','candidates','intake'])if(JSON.stringify(restored[key])!==JSON.stringify(final[key]))throw Error('Archive roundtrip lost '+key);
  if(restored.originalSha!==initial.originalSha)throw Error('Roundtrip original hash changed');
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({originalAsset:initial.asset,candidateAsset:candidate.candidateAsset,restoredId:restored.id,originalSha256:initial.originalSha,textFixtureSource:texts.source,counts:{original:texts.original.length,withoutBreaks:removedBreaks.candidateCharacters,shortened:shortened.candidateCharacters},postEncodeDecode:candidate.postEncodeDecode,durationDeltaSeconds:candidate.durationDeltaSeconds,originalPreserved:true,explicitApply:true,roundtrip:true,originalTextPreserved:true,newlineOnlyCandidate:true,wordDeletionDiff:true,unconfirmedCandidatePreserved:true,wordChangeDiff:true,explicitAuthorConfirmation:true,editClearsConfirmation:true,reopenedEditRequiresReconfirmation:true,removeBreaksClearsConfirmation:true,usageDeclarationSynced:true,nativeVerified:false,pageErrors:errors,consoleWarnings:warnings,httpErrors:responses,iconWarnings:warnings.filter(w=>/icon|favicon/i.test(w.text))}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
'''
            try:
                result = subprocess.run([node, "-e", script, str(module),
                    f"http://127.0.0.1:{server.server_port}", str(original_path),
                    str(root / "texts.json"), str(root / "audio.wfchar.zip")],
                    capture_output=True, text=True, encoding="utf-8", timeout=120)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                evidence = json.loads(result.stdout.strip().splitlines()[-1])
                restored = server.store.load(evidence["restoredId"])
                self.assertEqual(server.store.asset_bytes(restored, evidence["originalAsset"]), original_bytes)
                self.assertEqual(hashlib.sha256(original_path.read_bytes()).hexdigest(), evidence["originalSha256"])
                self.assertEqual(evidence["pageErrors"], [])
                self.assertEqual(evidence["httpErrors"], [])
                log_root = os.environ.get("WORKSHOP_UI_VERIFICATION_DIR")
                if log_root:
                    log_root = Path(log_root)
                    log_root.mkdir(parents=True, exist_ok=True)
                    (log_root / "audio-entry-ui-final.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                for path, raw in input_fixtures.items():
                    self.assertEqual(path.read_bytes(), raw)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
