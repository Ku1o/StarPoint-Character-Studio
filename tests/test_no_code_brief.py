"""Author intent stays editable without identifiers or fabricated assets."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from production_brief import (author_guidance, author_readme, author_submission_form,
                              checks, default_production_brief, export_handoff,
                              normalize_production_brief)


class NoCodeBriefTests(unittest.TestCase):
    def project(self):
        return {'productionBrief': default_production_brief(), 'assets': {},
                'name': '旧名称', 'identity': {'title': '旧头衔'},
                'skill': {'name': '旧技能', 'description': '旧说明'},
                'gameplay': {'skill': {'name': '旧技能', 'description': '旧说明'},
                             'leader': {}, 'abilities': []}}

    def test_detailed_assistance_replaces_missing_text_but_never_claims_assets(self):
        p = self.project()
        b = p['productionBrief']
        for key in ('characterName', 'title', 'role', 'race', 'baseForm', 'evolvedForm'):
            b['authorPolicy']['identity'][key] = {'state': 'cannot_provide', 'reason': '暂未确定，请根据已提供的设定提出候选方案', 'reference': '角色设定稿'}
        for key in ('activeSkill', 'pf', 'leader'):
            b['plans'][key]['authorPolicy'].update(state='needs_help', reason='希望做月光守护效果，缺少数值请协助设计', reference='母版画稿')
        for kind in ('resources', 'voices', 'sounds'):
            for row in b[kind]:
                row['authorPolicy'].update(state='cannot_provide', reason='没有此用途的成品，希望制作方按画稿补充', reference='设定稿')
        guidance = author_guidance(p)
        self.assertEqual(guidance['textAuthorPending'], [])
        self.assertEqual(guidance['authorPending'], [])
        self.assertTrue(guidance['makerPending'])
        self.assertFalse(guidance['gameReady'])
        self.assertTrue(all(not row['integrationVerified'] for row in guidance['rows'] + guidance['textRows']))
        self.assertTrue(all(row['status'] == 'missing' for row in guidance['rows']))
        issues = checks(p)
        self.assertFalse(any('尚未填写名称' in issue['text'] or '尚未填写自然语言' in issue['text'] or '作者填写包缺少' in issue['text'] for issue in issues))
        handoff = export_handoff(p)
        for payload in (handoff['authorGuide'], handoff['authorSubmissionForm']):
            self.assertIn('希望做月光守护效果', payload)
            self.assertIn('暂未确定，请根据已提供', payload)
            self.assertIn('制作方待核', payload)
        self.assertEqual(handoff['authorGuidance'], guidance)

    def test_empty_assistance_still_has_actionable_gap_and_bad_provided_links_survive(self):
        p = self.project()
        p['productionBrief']['plans']['activeSkill']['authorPolicy']['state'] = 'needs_help'
        self.assertIn('productionBrief.plans.activeSkill', author_guidance(p)['textAuthorPending'])
        self.assertTrue(any('请补充具体理由' in row['text'] for row in checks(p)))
        r = p['productionBrief']['resources'][0]
        r.update(status='provided', assetIds=['missing'])
        r['authorPolicy'].update(state='needs_help', reason='希望制作方核对')
        row = author_guidance(p)['rows'][0]
        self.assertFalse(row['authorComplete'])
        self.assertTrue(any(issue['code'] == 'asset_missing' for issue in row['issues']))

    def test_normalize_is_read_only_and_keeps_unknown_cards_policy_and_raw_fields(self):
        p = self.project()
        plan = p['productionBrief']['plans']['activeSkill']
        plan['authorCards'] = [{'condition': '受击后', 'future': {'keep': True}}]
        plan['authorPolicy'].update(state='cannot_provide', reason='请协助', future={'keep': 1})
        p['productionBrief']['authorPolicy']['identity']['title'] = {'state': 'needs_help', 'reason': '头衔尚未确定', 'extra': 2}
        p['productionBrief']['future'] = {'raw': [None, '保留']}
        before = copy.deepcopy(p)
        normalized = normalize_production_brief(p)
        self.assertEqual(p, before)
        self.assertEqual(normalized['plans']['activeSkill']['authorCards'], plan['authorCards'])
        self.assertEqual(normalized['plans']['activeSkill']['authorPolicy']['future'], {'keep': 1})
        self.assertEqual(normalized['authorPolicy']['identity']['title']['extra'], 2)
        self.assertEqual(normalized['future'], {'raw': [None, '保留']})
        self.assertEqual(normalize_production_brief(json.loads(json.dumps(normalized))), normalized)

    def test_default_docs_offer_human_assistance_without_asset_id_instruction(self):
        for doc in (author_readme(), author_submission_form()):
            self.assertIn('请协助制作', doc)
            self.assertIn('暂时无法提供', doc)
            self.assertNotIn('请写母版或工程素材 ID', doc)

    def test_current_browser_module_behavior_without_project_or_server_writes(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node not available for browser-module contract check')
        code = r'''
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[1],'utf8'), p=JSON.parse(process.argv[2]);
const nodes={}, bindings={};const node=id=>nodes[id]??={value:'',dataset:{},innerHTML:'',close(){}};
const context=vm.createContext({S:{p},mutate:fn=>fn(),esc:s=>String(s??''),uid:()=> 'voice-id',assetUrl:id=>'asset:'+id,
  $:selector=>node(selector),$$:selector=>bindings[selector]||[],modal:html=>node('#modal-content').innerHTML=html,
  toast(){},header:()=>'',busy:async(label,fn)=>fn(),location:{href:''},saveNow:async()=>{await Promise.resolve();context.saved=true;},
  api:async(path,data)=>{assert.equal(path,'/api/check');assert.deepEqual(Object.keys(data),['id']);context.checkRequest={path,data};return {issues:[]};}});
vm.runInContext(source,context);
const before=JSON.stringify(p);context.pbConflicts();assert.equal(JSON.stringify(p),before);
context.pbSet('author.characterName','新角色');assert.equal(p.name,'新角色');
context.pbSet('plans.activeSkill.name','新技能');assert.equal(p.skill.name,'新技能');assert.equal(p.gameplay.skill.name,'新技能');
context.pbSet('plans.pf.authorDescription','强化弹射说明');assert.equal(p.gameplay.pf.description,'强化弹射说明');
context.pbSet('plans.abilities.2.name','第三能力');assert.equal(p.gameplay.abilities.find(a=>a.slot===3).name,'第三能力');
p.assets.image={id:'image',name:'母版.png',mime:'image/png'};p.assets.voice={id:'voice',name:'台词.wav',mime:'audio/wav'};
context.pbBindAssets('resources.0',['image']);assert.equal(p.productionBrief.resources[0].assetIds[0],'image');assert.equal(p.portraits.base,'image');
context.pbBindAssets('voices.0',['voice']);assert.equal(p.voices[0].asset,'voice');assert.equal(p.productionBrief.voices[0].assetId,'voice');
const html=context.pbResourceRow(p.productionBrief.resources[0],0);assert.ok(html.includes('data-pb-pick'));assert.ok(html.includes('data-pb-upload'));assert.ok(!html.includes('工程素材 ID'));assert.ok(html.includes('母版.png'));
const audio=context.pbAudioRow(p.productionBrief.voices[0],0);assert.ok(audio.includes('希望在哪里播放'));assert.ok(audio.includes('战斗中播放'));assert.ok(!audio.includes('工程音频素材 ID'));
assert.equal(context.pbTextState('',{state:'needs_help',reason:'请协助'}).authorComplete,true);
context.bindProductionBrief();
(async()=>{await node('#production-export').onclick();assert.equal(context.saved,true);assert.ok(context.location.href.includes('/api/production-handoff'));await node('#production-run-check').onclick();assert.equal(context.checkRequest.path,'/api/check');console.log('behavior-ok');})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run([node, '-e', code, str(ROOT / 'web/production-brief.js'), json.dumps(self.project(), ensure_ascii=False)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('behavior-ok', result.stdout)


if __name__ == '__main__':
    unittest.main()
