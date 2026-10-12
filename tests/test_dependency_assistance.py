"""Actual help derivation must retain gaps and hand-written author intent."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dependency_assistance import build
from character_dependencies import analyze_project
from studio_core import ProjectStore


class DependencyAssistanceTests(unittest.TestCase):
    def test_recursive_missing_materials_get_specific_help_without_author_debt(self):
        project={'id':'p','revision':4,'productionBrief':{'notes':'已经有的手填说明'}}
        closure={'missingReferences':[{'logical':'master/multiball/7','reason':'缺少表定义'},
                    {'logical':'battle/common/hit','reason':'缺少图片'}],
                 'characterSemanticGaps':[{'domain':'summon','reason':'nested support unresolved'}]}
        before=copy.deepcopy((project,closure))
        result=build(project,closure)
        self.assertEqual((project,closure),before)
        self.assertEqual(result['requestCount'],2)
        summon=next(r for r in result['requests'] if r['domain']=='summon')
        self.assertEqual(summon['owner'],'maker')
        self.assertIn('嵌套召唤',summon['makerAction'])
        self.assertIn('存活多久',summon['authorInput'])
        self.assertEqual(summon['observedItems'],2)
        self.assertIn('通常可复用',next(r for r in result['requests'] if r['domain']=='shared')['authorInput'])
        self.assertFalse(result['gameReady'])
        self.assertEqual(build(project,closure),result)

    def test_supported_cards_not_requested_again_and_free_text_preserved(self):
        project={'id':'p','revision':2}
        gameplay={'items':[{'id':'a','status':'applied'},{'id':'b','status':'supported'},
            {'id':'c','status':'pending','planLabel':'主动技能','text':'召唤两个月球',
             'reason':'尚缺移动和结束规则'}],
            'pending':[{'plan':'activeSkill','planLabel':'主动技能','text':'手工补充：不要改变动画'}]}
        result=build(project,gameplay=gameplay)
        self.assertEqual(result['requestCount'],2)
        self.assertIn('召唤两个月球',result['requests'][0]['requestText'])
        self.assertIn('结束方式',result['requests'][0]['authorInput'])
        self.assertEqual(result['requests'][1]['text'],'手工补充：不要改变动画')
        self.assertTrue(all(not r['integrationVerified'] for r in result['requests']))

    def test_fresh_project_reports_missing_definition_without_saving_or_faking_closure(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ProjectStore(Path(temp)/'projects');created=store.create('缺参考')
            project=store.load(created['id'])
            before=copy.deepcopy(project)
            result=analyze_project(store,project,files={})
            self.assertEqual(project,before)
            self.assertEqual(store.load(project['id']),before)
            self.assertTrue(result['assistance']['requestCount'])
            self.assertFalse(result['closure']['characterSemanticClosure'])
            self.assertTrue(any(r['domain']=='definition' for r in result['assistance']['requests']))

    def test_machine_evidence_and_special_labels_do_not_disappear(self):
        project={'id':'p','revision':1}
        gap={'domain':'ability','reason':'bad bool','source':'<script>', 'row':3}
        result=build(project,{'sourceDefinitionProblems':[gap,gap]})
        self.assertEqual(result['requests'][0]['observedItems'],1)
        self.assertEqual(result['requests'][0]['evidence'][0]['source'],'<script>')
        self.assertNotIn('<script>',result['requests'][0]['requestText'])
        self.assertNotEqual(result['requests'][0]['id'],build(project,{'sourceDefinitionProblems':[{**gap,'row':4}]})['requests'][0]['id'])

    def test_structured_complex_prompts_keep_provided_detail_and_request_missing_rules(self):
        gameplay={'items':[{'status':'pending','id':'summon','planLabel':'主动技能',
            'detailPrompts':[{'field':'reference','label':'复用参考','value':'凉月原动作','status':'provided'},
                             {'field':'lifetime','label':'寿命与退场规则','value':'','status':'needed'}]}]}
        result=build({'id':'p','revision':1},gameplay=gameplay)
        self.assertIn('凉月原动作',result['requests'][0]['authorInput'])
        self.assertIn('寿命与退场规则：可以补充或请协助',result['requests'][0]['requestText'])


if __name__=='__main__': unittest.main()
