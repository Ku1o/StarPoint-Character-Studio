"""Native-entry integration of condition unions and unresolved evidence."""
import copy
import sys
from pathlib import Path
import unittest
import tempfile
import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_dependencies import extract_native_roots
from test_native_dependencies import fixture
from test_native_summon_dependencies import flat, fixture as summon_fixture, summon_command
import native_common_dependencies as common
from character_dependencies import analyze_project
from studio_core import ProjectStore, amf_bytes


def common_tables():
    files = {name: flat({}) for group in common.SOUND_TABLES.values() for name in group}
    files[common.SOUND_TABLES['sound'][0]] = flat({'sound_effect/common/fixture': ['0', '0', '0', '6']})
    files[common.SKIN_TABLE] = flat({'1': ['0', 'battle/test/skin/a', 'unused', 'battle/test/skin/extra']})
    return files


class NativeConditionCoverageTests(unittest.TestCase):
    def test_author_flags_cannot_hide_common_candidates_or_claim_runtime_configuration(self):
        project = fixture()
        before = copy.deepcopy(project)
        first = extract_native_roots(project)
        self.assertEqual(project, before)
        forged = copy.deepcopy(project)
        forged['resourceContext'] = {'featuresPermit': {'dashEnabled': False}, 'assetReadKind': 0,
                                     'flipperSkinEnabled': False, 'complete': True}
        second = extract_native_roots(forged)
        self.assertEqual(first['roots'], second['roots'])
        dash = [row for row in first['roots'] if row['logical'] == 'battle/common/layer0/escape_line']
        self.assertTrue(dash)
        self.assertEqual({row['roles'][0] for row in dash}, {'main', 'unison', 'leader'})
        self.assertTrue(all(row['bucket'] == 'Common' and row['origin'] == 'collector-authoring-union' for row in dash))
        self.assertTrue(all(row['definitionEvidence']['condition'] == 'dashEnabled' for row in dash))
        self.assertFalse(first['commonSelection']['observedRuntimeConfiguration'])
        self.assertFalse(first['commonSelection']['authorTechnicalFlagsRequired'])
        self.assertFalse(first['complete'])
        self.assertFalse(first['gameReady'])

    def test_actual_ui_requirements_and_precise_pending_survive_the_main_entry(self):
        result = extract_native_roots(fixture())
        pointers = {row['pointer'] for row in result['problems']}
        self.assertNotIn('/Common/featuresPermit', pointers)
        self.assertNotIn('/Common/assetReadKind', pointers)
        self.assertNotIn('/Attention', pointers)
        self.assertEqual(len([row for row in result['problems'] if 'AttentionThumbnail' in row['reason']]), 1)
        expanded = next(row for row in result['commonConditionalCoverage'] if row['pointer'].endswith('/displaysPause/ui'))
        self.assertIn('scene/battle/pause_menu', expanded['knownLogicals'])
        self.assertFalse(expanded['runtimeContentsVerified'])
        self.assertEqual(expanded['sourceEvidence']['condition'], 'displaysPause')
        self.assertEqual(expanded['status'], 'included-authoring-union')
        ui_roots = [row for row in result['roots'] if row['kind'] in ('ui', 'html')]
        self.assertEqual(len(ui_roots), 36)
        self.assertTrue(all(row['category'] == 'shared' for row in ui_roots))
        self.assertTrue(any(row['logical'] == 'rich_text/settlement' for row in result['requiredReferences']))
        self.assertTrue(any(row['title'] == '冲刺表现' for row in result['commonConditionalCoverage']))
        self.assertEqual(result['domains']['shared']['status'], 'pending')

    def test_saved_effect_conversion_summary_is_not_ability_or_trigger_acceptance(self):
        result = extract_native_roots(fixture())
        summary = result['abilityConversionSummary']
        self.assertGreater(summary['mappedEffectBlocks'], 0)
        self.assertFalse(summary['completeAbilityDomain'])
        self.assertFalse(summary['triggerAdmissionVerified'])
        self.assertEqual(result['domains']['ability']['status'], 'pending')

    def test_unparseable_effect_is_reported_even_without_a_coverage_entry(self):
        project = fixture()
        fields = project['nativeGameplay']['abilities'][0]['rows'][0]
        fields[46], fields[47], fields[51], fields[52], fields[109] = '1', '24', 'NaN', '1', '3'
        before = copy.deepcopy(project)
        result = extract_native_roots(project)
        self.assertEqual(project, before)
        self.assertTrue(any('强度端点' in item['reason'] for item in result['problems']))
        self.assertGreater(result['abilityConversionSummary']['reportedAbilityProblems'], 0)
        self.assertEqual(result['domains']['ability']['status'], 'pending')
        self.assertFalse(result['complete'])
        self.assertFalse(result['gameReady'])

    def test_supplied_tables_reach_native_extraction_with_exact_logical_identity(self):
        for prefix in ('', 'compiled/common/'):
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as temp:
                store = ProjectStore(Path(temp)/'projects')
                project = store.create('冻结表接入')
                project.update(fixture())
                inputs = {prefix+name: raw for name, raw in common_tables().items()}
                inputs['compiled/android/'+common.SKIN_TABLE] = inputs[prefix+common.SKIN_TABLE]
                before_project, before_inputs = copy.deepcopy(project), copy.deepcopy(inputs)
                result = analyze_project(store, project, files=inputs)
                coverage = result['nativeDefinitionCoverage']
                self.assertFalse([p for p in coverage['problems'] if '/flipperSkin/' in p['pointer'] or '/master-loading/' in p['pointer']])
                self.assertEqual(sum(c['status']=='included-authoring-union' for c in coverage['commonConditionalCoverage']),28)
                sound = next(r for r in coverage['roots'] if r['logical']=='sound_effect/common/fixture.mp3')
                self.assertEqual(sound['definitionEvidence']['sha256'], hashlib.sha256(inputs[prefix+common.SOUND_TABLES['sound'][0]]).hexdigest())
                self.assertEqual(project,before_project)
                self.assertEqual(inputs,before_inputs)
                self.assertFalse(result['closure']['completeCharacterTotal'])

    def test_conflicting_table_sources_are_not_selected_or_silently_overridden(self):
        for declared in (True, False):
            with self.subTest(project_reference=declared), tempfile.TemporaryDirectory() as temp:
                store=ProjectStore(Path(temp)/'projects');project=store.create('冲突表保留')
                project.update(fixture())
                inputs=common_tables()
                original=inputs.pop(common.SKIN_TABLE)
                replacement=flat({'1':['0','battle/test/skin/b','unused','battle/test/skin/other']})
                inputs['compiled/common/'+common.SKIN_TABLE]=replacement
                if declared:
                    target=store.directory(project['id'])/'reference'/common.SKIN_TABLE
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(original)
                    project['referenceFiles']=[common.SKIN_TABLE]
                else:
                    inputs[common.SKIN_TABLE]=original
                before=copy.deepcopy(project)
                result=analyze_project(store,project,files=inputs)
                self.assertTrue(any(r['logical']==common.SKIN_TABLE and '冲突' in r['reason'] for r in result['referenceReadErrors']))
                roots=result['nativeDefinitionCoverage']['roots']
                self.assertFalse(any(r['logical'].startswith('battle/test/skin/') for r in roots))
                self.assertTrue(any('/flipperSkin/' in r['pointer'] for r in result['nativeDefinitionCoverage']['problems']))
                self.assertFalse(result['closure']['compiledResourceClosure'])
                self.assertFalse(result['closure']['completeCharacterTotal'])
                self.assertEqual(project,before)
                if declared:self.assertEqual(target.read_bytes(),original)

    def test_three_aliases_cannot_clear_an_existing_conflict_with_the_original_bytes(self):
        for declared in (True,False):
            with self.subTest(project_reference=declared), tempfile.TemporaryDirectory() as temp:
                store=ProjectStore(Path(temp)/'projects');project=store.create('多来源冲突')
                project.update(fixture())
                inputs=common_tables()
                original=inputs[common.SKIN_TABLE]
                replacement=flat({'1':['0','battle/test/skin/b','unused','battle/test/skin/other']})
                aliases={'compiled/common/'+common.SKIN_TABLE:original,
                         'compiled/android/'+common.SKIN_TABLE:replacement,
                         'compiled/ios/'+common.SKIN_TABLE:original}
                if declared:
                    project['referenceFiles']=list(aliases)
                    for name,raw in aliases.items():
                        target=store.directory(project['id'])/'reference'/name
                        target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
                else:
                    del inputs[common.SKIN_TABLE]
                    inputs.update(aliases)
                result=analyze_project(store,project,files=inputs)
                self.assertTrue(any(r['logical']==common.SKIN_TABLE and '冲突' in r['reason'] for r in result['referenceReadErrors']))
                self.assertFalse(any(r['logical'].startswith('battle/test/skin/') for r in result['nativeDefinitionCoverage']['roots']))
                self.assertFalse(result['closure']['compiledResourceClosure'])
                self.assertFalse(result['closure']['completeCharacterTotal'])

    def test_supplied_tables_also_reach_recursive_summon_and_support_parser(self):
        with tempfile.TemporaryDirectory() as temp:
            store=ProjectStore(Path(temp)/'projects');project=store.create('递归表接入')
            logical='battle/action/fixture.action.dsl.amf3.deflate'
            project['dependencyScope']={'roots':[{'logical':logical,'requester':'fixture','source':'frozen-test',
                'category':'skill','bucket':'BattlePart','collection':'project','layer':0}]}
            inputs={**summon_fixture(),logical:amf_bytes(['Block',[['Command',summon_command()] ]])}
            before=copy.deepcopy(inputs)
            result=analyze_project(store,project,files=inputs)
            missing={row['logical'] for row in result['missingReferences']}
            self.assertIn('character/summon_body/pixelart/pixelart',missing)
            self.assertIn('battle/action/support.action.dsl.amf3.deflate',missing)
            self.assertEqual(inputs,before)
            self.assertFalse(result['closure']['completeCharacterTotal'])


if __name__ == '__main__':
    unittest.main()
